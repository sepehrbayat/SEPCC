# Auto Prompting Enhancer — Design Spec

**Date:** 2026-05-30
**Status:** Awaiting approval

## Overview

A "Prompt Enhancer" (Auto Prompting Enhancer) that automatically improves user prompts using project context before they reach the agent. Controlled by a settings toggle (default ON). Manual `/enhance` command available when auto is off.

## Architecture Decision

**Insertion point:** `cli/session.py:CLISession.start_task()`, after lock acquisition, before the `-p` flag is built for the Claude CLI subprocess.

**Why:** This is the single universal choke point for all clients (CLI, Discord, Telegram, VS Code, JetBrains). The Claude Code hook system (`UserPromptSubmit`) cannot replace prompts — it only adds `additionalContext` or blocks entirely. The proxy API layer has no workspace context access.

## Design Decisions (Non-Obvious)

- **Fail-open invariant:** `enhance_prompt()` MUST always return a non-empty string. Any exception, timeout, or empty LLM response returns the original prompt unchanged. Enhancement is a convenience, never a blocker.
- **Enhancement inside `_cli_lock`:** This serializes during enhancement, but is correct because the LLM call is a prerequisite for the agent's work. Messages to other sessions are unaffected.
- **Stateless:** No caching of context. Files change between calls (especially handoff.md). Read fresh each time.
- **Self-calling:** The enhancer calls the proxy's own `/v1/messages` endpoint. This avoids duplicating provider logic, auth, or routing.
- **Single-turn only:** Enhancement is a stateless single-turn call — no conversation, no tool use. 512 max tokens output.

## Data Flow

```
User: "fix the login bug"
  │
  ▼
CLISession.start_task(prompt="fix the login bug")
  │
  ├─ _maybe_enhance_prompt() checks: AUTO_PROMPT_ENHANCER=true?
  │   ├─ Reads CLAUDE.md, AGENTS.md, CLAUDE.local.md,
  │   │   .fcc/context/*.md from self.workspace
  │   ├─ Builds enhancer system prompt with compacted context
  │   ├─ POSTs to http://127.0.0.1:{port}/v1/messages (single-turn, SSE stream)
  │   ├─ Returns enhanced prompt (or original on failure)
  │   └─ Traces outcome: prompt.enhanced / prompt.enhancement.skipped
  │
  ▼
cmd = ["claude", "-p", enhanced_prompt, "--output-format", "stream-json", ...]
```

## Implementation Plan

### Phase 1 — Settings (1 file)

**File:** `config/settings.py`

Add three fields to `Settings` class (after line 356, before `model_config`):

```python
# ==================== Auto Prompting Enhancer ====================
auto_prompt_enhancer: bool = Field(
    default=True, validation_alias="AUTO_PROMPT_ENHANCER"
)
prompt_enhancer_timeout: float = Field(
    default=12.0, validation_alias="PROMPT_ENHANCER_TIMEOUT"
)
prompt_enhancer_max_output_chars: int = Field(
    default=2000, validation_alias="PROMPT_ENHANCER_MAX_OUTPUT_CHARS"
)
```

**Verification:** Running proxy with `AUTO_PROMPT_ENHANCER=false` disables enhancement. Default (unset) enables it.

### Phase 2 — Core Enhancer Module (1 new file)

**File:** `core/prompt_enhancer.py` (NEW)

Exports a single async function:

```python
async def enhance_prompt(
    prompt: str,
    workspace_path: str,
    *,
    timeout: float = 12.0,
    max_output_chars: int = 2000,
) -> str:
```

Internal structure:
- `_read_project_context(workspace)` — reads CLAUDE.md, AGENTS.md, CLAUDE.local.md, `.fcc/context/agent-runtime.md`, `.fcc/context/handoff.md`, `.fcc/context/facts.md`, `.fcc/context/decisions.md`. Each compacted to max 15 lines / 1200 chars. Missing files silently skipped.
- `_build_enhancement_request(prompt, context, max_output)` — constructs the single-turn Messages API request body with a system prompt instructing the LLM to improve the prompt using context, without inventing facts or leaking credentials.
- `_call_enhancement_llm(request_body, timeout)` — POSTs to `http://127.0.0.1:{port}/v1/messages`, streams SSE response, collects text, returns joined string.
- Top-level `enhance_prompt()` wraps everything in try/except — any failure returns original `prompt`.

**Tests:**
- `tests/test_prompt_enhancer.py` — mock the LLM caller, test context reading, system prompt structure, fail-open on timeout, fail-open on empty response, fail-open on exception, original prompt preserved on error.

### Phase 3 — Session Layer Integration (3 files)

**File:** `cli/session.py`
- Add `auto_prompt_enhancer: bool = True` and `prompt_enhancer_timeout: float = 12.0` to `ClaudeCliConfig` dataclass
- Add same parameters to `CLISession.__init__` and store as `self.enhancer_enabled` / `self.enhancer_timeout`
- Add `_maybe_enhance_prompt()` async method (fail-open wrapper around `enhance_prompt`)
- Insert call in `start_task()` at line 115: `prompt = await self._maybe_enhance_prompt(prompt)`

**File:** `cli/manager.py`
- Add `auto_prompt_enhancer: bool = True` and `prompt_enhancer_timeout: float = 12.0` to `CLISessionManager.__init__`
- Pass to `CLISession(...)` constructor in `get_or_create_session` (line 81-89)

**File:** `api/runtime.py`
- Pass `auto_prompt_enhancer=self.settings.auto_prompt_enhancer` and `prompt_enhancer_timeout=self.settings.prompt_enhancer_timeout` to `CLISessionManager(...)` (after line 255)

### Phase 4 — Manual `/enhance` Command (1 file)

**File:** `messaging/handler.py`

In `_handle_message_impl`, after `parse_command_base` (line 125), insert before `dispatch_command` (line 146):

```python
text = incoming.text or ""
if text.startswith("/enhance ") or text == "/enhance":
    stripped = text[len("/enhance"):].strip()
    if not stripped:
        await self.platform.queue_send_message(
            incoming.chat_id,
            self.format_status("✨", "Usage:", "/enhance <your prompt>"),
            fire_and_forget=False,
        )
        return
    try:
        from core.prompt_enhancer import enhance_prompt
        enhanced = await enhance_prompt(
            stripped, self.cli_manager.workspace,
            timeout=getattr(self.cli_manager, '_prompt_enhancer_timeout', 12.0),
        )
        incoming = incoming.model_copy(update={"text": enhanced})
    except Exception:
        incoming = incoming.model_copy(update={"text": stripped})
```

`/enhance` is NOT added to `command_dispatcher.py` dispatch table. It transforms the message content and falls through to normal processing.

### Phase 5 — Integration & Edge Case Tests

1. Auto ON (default): send prompt, verify enhancement in trace logs
2. Auto OFF (`AUTO_PROMPT_ENHANCER=false`): verify prompt passes through unmodified
3. Manual `/enhance fix the login bug`: verify enhanced prompt reaches agent
4. Manual `/enhance` (empty): verify usage hint shown
5. Kill proxy mid-enhancement: verify original prompt passes through (fail-open)
6. Very short prompt ("hi"): verify no degradation
7. Very long prompt (2000+ chars): verify no truncation
8. CLAUDE.local.md secrets: verify not present in enhanced prompt (manual audit or grep test)
9. CI checks pass: `uv run ruff format`, `uv run ruff check`, `uv run ty check`, `uv run pytest`

### Files Summary

| Action | File | Purpose |
|--------|------|---------|
| NEW | `core/prompt_enhancer.py` | Stateless enhancement function |
| NEW | `tests/test_prompt_enhancer.py` | Unit tests for enhancer |
| EDIT | `config/settings.py` | Add 3 settings fields |
| EDIT | `cli/session.py` | Intercept prompt before -p flag |
| EDIT | `cli/manager.py` | Thread settings to session |
| EDIT | `api/runtime.py` | Wire settings at startup |
| EDIT | `messaging/handler.py` | `/enhance` prefix handling |
