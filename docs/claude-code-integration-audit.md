# Claude Code Integration Audit

Date: 2026-05-31

## Findings

Claude Code already owns a large part of the workflow layer FCC was beginning to recreate.
Official docs currently list built-in commands for initialization, context inspection,
compaction, review, large-work batching, app verification, diagnostics, settings, themes,
status lines, terminal setup, and fullscreen rendering:

- Commands: https://code.claude.com/docs/en/commands
- Extension model: https://code.claude.com/docs/en/features-overview
- `.claude` directory and file ownership: https://code.claude.com/docs/en/claude-directory
- Output styles and system-prompt customization: https://code.claude.com/docs/en/output-styles
- Terminal configuration and themes: https://code.claude.com/docs/en/terminal-config
- Status line: https://code.claude.com/docs/en/statusline
- Hooks: https://code.claude.com/docs/en/hooks

FCC should remain the provider/router, context hardening, messaging, session-resume,
and provider-compatibility layer. It should not become a second Claude Code command
implementation.

## Command Protocol

The default scaffold now adds three command-aware surfaces:

- `.fcc/context/agent-runtime.md` tells agents to prefer built-in Claude Code commands
  before adding FCC orchestration.
- `.claude/skills/claude-command-router/SKILL.md` gives the agent a reusable decision
  table for commands such as `/init`, `/context`, `/compact`, `/diff`, `/code-review`,
  `/security-review`, `/run`, `/verify`, `/doctor`, `/debug`, `/config`, `/theme`,
  `/statusline`, `/terminal-setup`, and `/tui fullscreen`.
- `UserPromptSubmit` emits short command hints for prompts that look like context
  pressure, project setup, review, verification, CLI UI setup, or RTL-language input.

The protocol is advisory because Claude Code slash commands are control input. FCC must
not silently rewrite `/init` into prose or replace `/compact` with a different prompt.

## Prompt Enhancer Alignment

The prompt enhancer is useful for Discord/Telegram style plain-language prompts, but it
must stay below Claude Code's command layer:

- Explicit slash commands now bypass enhancement.
- Empty prompts bypass enhancement.
- `PROMPT_ENHANCER_MAX_OUTPUT_CHARS` is wired from settings into `CLISession`.

Long-term, prefer Claude Code Skills and `UserPromptSubmit` additional context for
command-aware behavior. Use full prompt rewriting only when the input is normal user text.

## RTL Support

Claude Code's terminal input and transcript rendering are owned by the upstream TUI and
the terminal or IDE host. FCC cannot reliably fix Persian, Arabic, or Hebrew input order
inside the core Claude Code terminal prompt from the provider proxy layer.

What FCC can own:

- Browser/admin UI fields should use browser BiDi handling. Admin text inputs and
  textareas now use `dir="auto"` plus `unicode-bidi: plaintext`.
- Messaging platforms should preserve Unicode text and let Discord/Telegram handle BiDi
  rendering.
- Project guidance should warn that code blocks, tool output, file paths, commands, and
  diffs remain LTR even when surrounding prose is RTL.

Best current workaround for the terminal prompt is to use a terminal or IDE surface with
working BiDi rendering, or the Claude Code VS Code ecosystem extensions that apply
`dir="auto"` to the webview.

## CLI Appearance

Use Claude Code built-ins first:

- `/theme` or `/config` for built-in and custom themes.
- `~/.claude/themes/*.json` for custom theme tokens.
- `/statusline` or `statusLine` settings for a custom bottom row.
- `/tui fullscreen` or `CLAUDE_CODE_NO_FLICKER=1` for fullscreen rendering.
- `/terminal-setup` for Shift+Enter and terminal keybinding setup where supported.

FCC bootstrap now installs `scripts/statusline/fcc_statusline.py` and configures a compact
status line that shows FCC, the model display name, project directory, and context usage.
