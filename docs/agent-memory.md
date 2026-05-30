# Agent Memory

Use this file for durable, verified facts that future agents should know about this project. Do not store secrets, raw environment values, access tokens, private URLs, or guesses.

## Verified Facts

- 2026-05-29: This project uses `uv run` and Python 3.14.0 for local commands.
- 2026-05-29: Required check order is `uv run ruff format`, `uv run ruff check`, `uv run ty check`, then `uv run pytest`.
- 2026-05-29: Project default model configuration is intended to stay on `deepseek/deepseek-v4-pro` unless the user explicitly changes it.
- 2026-05-29: Playwright is installed as a dev dependency and Chromium is available for browser smoke checks.

## Memory Rules

- Add only reusable facts with a date and verification method.
- Prefer file paths, commands, and stable architecture decisions.
- Remove stale facts when project behavior changes.
