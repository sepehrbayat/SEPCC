"""Stateless prompt enhancement using project context.

Reads project context files from a workspace, builds an enhancer system prompt,
and calls the proxy's own Messages API to produce an improved prompt. Fails open:
any error returns the original prompt unchanged.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from core.trace import trace_event

_CONTEXT_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "CLAUDE.local.md",
    ".fcc/context/agent-runtime.md",
    ".fcc/context/handoff.md",
    ".fcc/context/facts.md",
    ".fcc/context/decisions.md",
)

DEFAULT_PROMPT_ENHANCER_MODEL = "claude-haiku-4-5-20251001"

_ENHANCER_SYSTEM_PROMPT = """You are a prompt enhancer. Your job is to improve the user's prompt using the project context provided below.

Rules:
- Understand the user's intent and make it more specific, actionable, and precise.
- Incorporate relevant project conventions, facts, architecture, and decisions from the context.
- Do NOT invent facts, files, or conventions not present in the context.
- Do NOT expand the scope beyond what the user asked for.
- Do NOT repeat API keys, tokens, passwords, or credentials from the context.
- Preserve the original language and tone of the prompt.
- Return ONLY the enhanced prompt text. No explanations, no prefixes, no markdown fences.
- If the prompt is already well-formed and specific, return it mostly unchanged — only add relevant context if clearly missing.
"""


@dataclass(frozen=True)
class PromptEnhancementResult:
    """Structured result for callers that need visible enhancement status."""

    original_prompt: str
    enhanced_prompt: str
    status: str
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.enhanced_prompt.strip() != self.original_prompt.strip()


def _should_enhance_prompt(prompt: str) -> bool:
    """Return whether the prompt is normal user text rather than CLI control input."""
    stripped = prompt.lstrip()
    return bool(stripped) and not stripped.startswith("/")


def _compact(text: str, *, max_lines: int = 15, max_chars: int = 1200) -> str:
    """Compact text for context injection (same logic as _shared.compact_lines)."""
    out: list[str] = []
    used = 0
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            closing_index = next(
                (
                    candidate
                    for candidate in range(index + 1, len(lines))
                    if lines[candidate].strip().startswith("```")
                ),
                None,
            )
            if closing_index is None:
                index += 1
                continue
            index = closing_index + 1
            continue
        if not line.strip():
            index += 1
            continue
        next_len = len(line) + 1
        if used + next_len > max_chars:
            break
        out.append(line)
        used += next_len
        if len(out) >= max_lines:
            break
        index += 1
    return "\n".join(out)


def _read_project_context(workspace_path: str) -> str:
    """Read and compact project context files from the workspace."""
    root = Path(workspace_path)
    sections: list[str] = []
    for rel_path in _CONTEXT_FILES:
        file_path = root / rel_path
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        compacted = _compact(content)
        if compacted:
            label = rel_path.split("/")[-1].replace(".md", "").replace("-", " ").title()
            sections.append(f"### {label} ({rel_path})\n{compacted}")
    return "\n\n".join(sections)


def _build_enhancement_request(
    prompt: str,
    context: str,
    *,
    model: str = DEFAULT_PROMPT_ENHANCER_MODEL,
    max_tokens: int = 512,
    stream: bool = True,
) -> dict[str, Any]:
    """Build a single-turn Messages API request body for enhancement."""
    system = _ENHANCER_SYSTEM_PROMPT
    if context:
        system += f"\n\n## Project Context\n\n{context}"

    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream,
    }


def _extract_error_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message.strip()
    message = data.get("message")
    return message.strip() if isinstance(message, str) else ""


def _extract_message_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        if parts:
            return "".join(parts).strip()
    text = data.get("text")
    if isinstance(text, str):
        return text.strip()
    completion = data.get("completion")
    if isinstance(completion, str):
        return completion.strip()
    return ""


def _extract_non_stream_text(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ""
    return _extract_message_text(data)


def _extract_non_stream_error(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ""
    return _extract_error_message(data)


async def _call_enhancement_llm(
    request_body: dict[str, Any], timeout: float, *, api_url: str, api_key: str
) -> str:
    """Call the proxy's Messages API, collecting SSE or JSON response text."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client,
        client.stream(
            "POST",
            api_url,
            json=request_body,
            headers=headers,
        ) as response,
    ):
        if response.status_code != 200:
            body = (await response.aread()).decode("utf-8", errors="replace").strip()
            detail = _extract_non_stream_error(body) or body[:300]
            logger.warning(
                "Enhancement LLM returned status {}: {}",
                response.status_code,
                detail or "empty body",
            )
            return ""

        text_parts: list[str] = []
        fallback_lines: list[str] = []
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                if line.strip():
                    fallback_lines.append(line)
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            event_type = data.get("type", "")
            if event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        text_parts.append(text)

        streamed = "".join(text_parts).strip()
        if streamed:
            return streamed

        fallback_body = "\n".join(fallback_lines).strip()
        if not fallback_body:
            return ""

        non_stream_text = _extract_non_stream_text(fallback_body)
        if non_stream_text:
            return non_stream_text

        error_message = _extract_non_stream_error(fallback_body)
        if error_message:
            logger.warning(
                "Enhancement LLM returned non-streaming error: {}", error_message
            )
        else:
            logger.warning(
                "Enhancement LLM returned non-SSE body without text: chars={}",
                len(fallback_body),
            )
        return ""


async def enhance_prompt_with_metadata(
    prompt: str,
    workspace_path: str,
    *,
    api_url: str = "http://127.0.0.1:8080/v1/messages",
    api_key: str = "",
    model: str = DEFAULT_PROMPT_ENHANCER_MODEL,
    timeout: float = 12.0,
    max_output_chars: int = 2000,
) -> PromptEnhancementResult:
    """Enhance a user prompt using project context with status metadata."""
    if not _should_enhance_prompt(prompt):
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.skipped",
            source="session",
            reason="control_input",
            original_chars=len(prompt),
        )
        return PromptEnhancementResult(prompt, prompt, "skipped", "control_input")

    try:
        context = _read_project_context(workspace_path)
    except Exception:
        logger.warning("Failed to read project context for enhancement, skipping")
        return PromptEnhancementResult(prompt, prompt, "context_error")

    request_body = _build_enhancement_request(prompt, context, model=model)

    try:
        enhanced = await asyncio.wait_for(
            _call_enhancement_llm(
                request_body, timeout, api_url=api_url, api_key=api_key
            ),
            timeout=timeout,
        )
    except TimeoutError:
        logger.warning(
            "Enhancement LLM timed out after {}s, using original prompt", timeout
        )
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.timeout",
            source="session",
            original_chars=len(prompt),
        )
        return PromptEnhancementResult(prompt, prompt, "timeout")
    except Exception:
        logger.warning("Enhancement LLM call failed, using original prompt")
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.error",
            source="session",
            original_chars=len(prompt),
        )
        return PromptEnhancementResult(prompt, prompt, "error")

    if not enhanced:
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.empty",
            source="session",
            original_chars=len(prompt),
        )
        return PromptEnhancementResult(prompt, prompt, "empty")

    if len(enhanced) > max_output_chars:
        enhanced = enhanced[:max_output_chars]

    if enhanced.strip() == prompt.strip():
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.unchanged",
            source="session",
            original_chars=len(prompt),
            enhanced_chars=len(enhanced),
        )
        return PromptEnhancementResult(prompt, enhanced, "unchanged")

    trace_event(
        stage="enhancement",
        event="prompt.enhanced",
        source="session",
        original_chars=len(prompt),
        enhanced_chars=len(enhanced),
    )
    return PromptEnhancementResult(prompt, enhanced, "enhanced")


async def enhance_prompt(
    prompt: str,
    workspace_path: str,
    *,
    api_url: str = "http://127.0.0.1:8080/v1/messages",
    api_key: str = "",
    model: str = DEFAULT_PROMPT_ENHANCER_MODEL,
    timeout: float = 12.0,
    max_output_chars: int = 2000,
) -> str:
    """Enhance a user prompt using project context. Returns original on failure."""
    result = await enhance_prompt_with_metadata(
        prompt,
        workspace_path,
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_output_chars=max_output_chars,
    )
    return result.enhanced_prompt


def enhance_prompt_sync(
    prompt: str,
    workspace_path: str,
    *,
    api_url: str = "http://127.0.0.1:8080/v1/messages",
    api_key: str = "",
    model: str = DEFAULT_PROMPT_ENHANCER_MODEL,
    timeout: float = 12.0,
    max_output_chars: int = 2000,
) -> PromptEnhancementResult:
    """Synchronous wrapper for standalone hook scripts."""
    return asyncio.run(
        enhance_prompt_with_metadata(
            prompt,
            workspace_path,
            api_url=api_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_output_chars=max_output_chars,
        )
    )
