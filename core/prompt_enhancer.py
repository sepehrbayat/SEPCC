"""Stateless prompt enhancement using project context.

Reads project context files from a workspace, builds an enhancer system prompt,
and calls the proxy's own Messages API to produce an improved prompt. Fails open:
any error returns the original prompt unchanged.
"""

from __future__ import annotations

import asyncio
import json
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


def _compact(text: str, *, max_lines: int = 15, max_chars: int = 1200) -> str:
    """Compact text for context injection (same logic as _shared.compact_lines)."""
    out: list[str] = []
    used = 0
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        next_len = len(line) + 1
        if used + next_len > max_chars:
            break
        out.append(line)
        used += next_len
        if len(out) >= max_lines:
            break
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
    max_tokens: int = 512,
) -> dict[str, Any]:
    """Build a single-turn Messages API request body for enhancement."""
    system = _ENHANCER_SYSTEM_PROMPT
    if context:
        system += f"\n\n## Project Context\n\n{context}"

    return {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }


async def _call_enhancement_llm(
    request_body: dict[str, Any], timeout: float, *, api_url: str, api_key: str
) -> str:
    """Call the proxy's Messages API, stream SSE response, collect text."""
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
            logger.warning(
                "Enhancement LLM returned status {}, using original prompt",
                response.status_code,
            )
            return ""

        text_parts: list[str] = []
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
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

        return "".join(text_parts).strip()


async def enhance_prompt(
    prompt: str,
    workspace_path: str,
    *,
    api_url: str = "http://127.0.0.1:8080/v1/messages",
    api_key: str = "",
    timeout: float = 12.0,
    max_output_chars: int = 2000,
) -> str:
    """Enhance a user prompt using project context. Returns original on failure."""
    try:
        context = _read_project_context(workspace_path)
    except Exception:
        logger.warning("Failed to read project context for enhancement, skipping")
        return prompt

    request_body = _build_enhancement_request(prompt, context)

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
        return prompt
    except Exception:
        logger.warning("Enhancement LLM call failed, using original prompt")
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.error",
            source="session",
            original_chars=len(prompt),
        )
        return prompt

    if not enhanced:
        trace_event(
            stage="enhancement",
            event="prompt.enhancement.empty",
            source="session",
            original_chars=len(prompt),
        )
        return prompt

    if len(enhanced) > max_output_chars:
        enhanced = enhanced[:max_output_chars]

    trace_event(
        stage="enhancement",
        event="prompt.enhanced",
        source="session",
        original_chars=len(prompt),
        enhanced_chars=len(enhanced),
    )
    return enhanced
