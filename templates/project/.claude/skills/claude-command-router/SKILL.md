---
name: claude-command-router
description: Choose when to use Claude Code built-in commands before adding FCC-specific workflow.
---

# Claude Command Router

Use this skill when a user asks which Claude Code command to run, when a task looks like a known Claude Code workflow, or when you are about to add FCC-specific orchestration.

## Protocol

Prefer Claude Code built-ins when they already fit:

- Project onboarding: suggest `/init` to create or refresh `CLAUDE.md`; use `fcc-bootstrap-context` only for FCC hooks, handoff files, subagents, and retrieval policy.
- Context pressure: suggest `/context all` to inspect usage, then `/compact <focus>` when the session should continue with less history.
- Diff review: suggest `/diff` for inspection, `/code-review` for correctness, and `/security-review` for security-specific risk.
- Large codebase changes: suggest `/batch` when independent worktree units make sense; otherwise plan in the main session and use FCC subagents only for bounded research or review.
- Runtime problems: suggest `/doctor`, `/debug`, `/status`, or `fcc context doctor` depending on whether the problem is Claude Code, provider/proxy, or FCC scaffold.
- App verification: suggest `/run` or `/verify` when a user-facing app change needs live validation.
- Interface ergonomics: suggest `/config`, `/theme`, `/statusline`, `/terminal-setup`, or `/tui fullscreen`.

Do not rewrite an explicit slash command. Let commands such as `/init`, `/compact`, and `/context all` pass through unchanged.

If no built-in command fits, continue with the normal FCC workflow: use project context, subagents only when they reduce risk or noise, and run the repository checks before finalizing code changes.
