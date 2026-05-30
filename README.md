<div align="center">

# SEPCC — Free Claude Code, with context that survives

A proxy for Claude Code that routes API calls to whatever provider you want. Built on top of [Free Claude Code](https://github.com/Alishahryar1/free-claude-code), but with a whole layer of stuff FCC didn't have: sessions you can actually resume, a context handoff that survives crashes, and a one-command project bootstrapper.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json&style=for-the-badge)](https://github.com/astral-sh/uv)

[Quick Start](#quick-start) · [What SEPCC adds](#what-sepcc-adds) · [Providers](#providers) · [Development](#development) · [License](#license)

</div>

---

## The short version

Claude Code is great. The problem is Anthropic's pricing and rate limits.

SEPCC sits between Claude Code and the API, so you can point Claude Code at any backend — DeepSeek, Gemini, OpenRouter, a local Llama, whatever. Claude Code thinks it's talking to Anthropic. You're not paying Anthropic prices.

That part existed already in FCC. What SEPCC adds is the stuff that makes it practical to use for real, multi-session work: context that doesn't evaporate when a session dies, a way to resume where you left off, and tooling to bootstrap a project for long-running Claude Code sessions.

Forked from [Ali Khokhar's Free Claude Code](https://github.com/Alishahryar1/free-claude-code).

---

## What SEPCC adds

FCC was a router — it proxied API calls from Claude Code to other providers. That part works. But when a session crashed or you had to restart, all the context was gone.

These are the things we built on top:

### Sessions you can resume

There's a SQLite registry at `.fcc/sessions.sqlite` that tracks every session in your project. Instead of losing everything when Claude Code crashes, you can pick up where you were:

```bash
fcc                  # start fresh, or auto-resume latest
fcc resume           # resume the most recent session
fcc resume my-session
fcc sessions list    # everything in this project
fcc sessions doctor  # check for stale entries
```

It tries `claude --resume` first (full transcript). If the transcript is gone but the handoff file is there, it starts a fresh session and injects the handoff as context. Not perfect, but you don't lose everything.

Set `FCC_AUTO_RESUME_LAST_SESSION=true` and plain `fcc` just resumes your last session automatically.

### A context handoff that actually survives

The problem with chat context is that it's volatile — Claude compacts it, sessions crash, you lose track of what you were doing.

SEPCC keeps a handoff file at `.fcc/context/handoff.md` that tracks:
- what you're working on right now
- decisions you've made
- what step comes next

It's not a transcript. It's a few lines. The `SessionStart` hook injects it into every new chat. `SubagentStop` refreshes it after subagents do work. Raw terminal output and tool results go to a SQLite sidecar, not the handoff, so the handoff stays short.

### One command to bootstrap a project

```bash
fcc-bootstrap-context
```

Drops 50+ files into your project:

- `CLAUDE.md` and `CLAUDE.local.md` — project rules and local machine facts
- `.claude/agents/` — four project agents (code reviewer, context auditor, product logic reviewer, researcher)
- `.claude/skills/` — three Claude Code skills (context-recall, handoff-writer, route-task)
- `.claude/commands/` — slash commands for handoff, recall, verify-context
- `.fcc/context/` — handoff, decisions, facts, agent runtime contract
- `.fcc/plugin-policy.yml` — enforces one owner per hook, no conflicts
- `.mcp.json` — Token Savior config for code retrieval
- `.claude/settings.json` — all five lifecycle hooks wired up

Flags: `--force`, `--install-token-savior`, `--install-memsearch`, `--large-repo`.

### Context doctor

```bash
fcc context doctor
```

Checks that the scaffolding is intact and fixes what it can. Validates:

- all runtime files are present
- all five hooks are configured
- no duplicate hook owners
- MemSearch and Claude-mem aren't both claiming memory ownership
- Token Savior is the code retrieval owner
- Ralph Loop has bounds and verification requirements
- SubagentStop is correctly used as the subagent lifecycle hook

### Subagent architecture — a note

Claude Code docs officially document `SubagentStop` as the stable hook for subagent lifecycle events. There is no stable `SubagentStart`. Subagent startup awareness comes through project agent definitions and the supported hooks. SEPCC's bootstrapper sets this up correctly.

### Provider fixes from the FCC base

- **Gemini**: fixed a bug where dual thinking controls produced malformed requests
- **Provider registry**: added dynamic registration and validation
- **Settings**: added system proxy auto-detection
- **Admin UI**: extended sidebar with session and context views

### What's different: FCC vs SEPCC

| Thing | FCC | SEPCC |
|-------|-----|-------|
| Provider proxy (17 backends) | yes | yes |
| Model routing | yes | yes |
| Admin UI | yes | yes (extended) |
| Discord/Telegram bots | yes | yes |
| Voice notes | yes | yes |
| Session resume | no | **yes — SQLite registry + smart fallback** |
| Context handoff | no | **yes — survives crashes and compaction** |
| Project bootstrapper | no | **yes — one command, 50+ files** |
| Context doctor | no | **yes — validation + auto-repair** |
| Agent runtime contract | no | **yes — hook-injected every session** |
| Project subagents | no | **4 specialized agents** |
| Claude Code skills | no | **3 project skills** |
| Slash commands | no | **handoff, recall, verify-context** |
| Gemini thinking fix | bugged | **fixed** |
| System proxy | no | **yes** |

---

## Quick Start

### 1. Install

**macOS / Linux:**

```bash
curl -fsSL "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.sh?raw=1" | sh
```

**Windows (PowerShell):**

```powershell
irm "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.ps1?raw=1" | iex
```

### 2. Start the proxy

```bash
fcc-server
```

You'll see something like:

```text
INFO:     Admin UI: http://127.0.0.1:8082/admin (local-only)
```

### 3. Configure a provider

Open the Admin UI URL from the terminal. Pick a provider, paste your API key, click Validate then Apply.

The default model is `deepseek/deepseek-v4-pro`. You need a [DeepSeek API key](https://platform.deepseek.com/api_keys) for that. Or pick any of the 17 providers below.

### 4. Launch Claude Code

```bash
fcc
```

`fcc` sets up the environment variables Claude Code needs, does a quick update check, and launches the real `claude` command. Keep `fcc-server` running in another terminal.

---

## Providers

Set `MODEL` to any of these prefixes. Leave `MODEL_OPUS`, `MODEL_SONNET`, `MODEL_HAIKU` blank to use `MODEL` for everything, or set them individually to mix providers by model tier.

### [NVIDIA NIM](https://build.nvidia.com/)
Key from [build.nvidia.com/settings/api-keys](https://build.nvidia.com/settings/api-keys). Set `NVIDIA_NIM_API_KEY`. Default model: `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`.

### [OpenRouter](https://openrouter.ai/)
Key from [openrouter.ai/keys](https://openrouter.ai/keys). Set `OPENROUTER_API_KEY`. Free models available.

### [Google AI Studio (Gemini)](https://aistudio.google.com/)
Key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Set `GEMINI_API_KEY`. Free tier available.

### [DeepSeek](https://platform.deepseek.com/)
Key from [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys). Set `DEEPSEEK_API_KEY`. Uses Anthropic-compatible endpoint.

### [Mistral La Plateforme](https://console.mistral.ai/)
Key from Mistral console. Set `MISTRAL_API_KEY`. Free Experiment plan available.

### [Mistral Codestral](https://console.mistral.ai/)
Separate key — set `CODESTRAL_API_KEY`. Prefix with `mistral_codestral/`.

### [OpenCode Zen](https://opencode.ai/)
Key from [opencode.ai/auth](https://opencode.ai/auth). Set `OPENCODE_API_KEY`. Free models available (e.g. `opencode/deepseek-v4-flash-free`).

### [OpenCode Go](https://opencode.ai/)
Same key as Zen. Prefix with `opencode_go/`.

### [Wafer](https://wafer.ai/)
Key from Wafer. Set `WAFER_API_KEY`. Uses Anthropic-compatible endpoint.

### [Kimi](https://platform.moonshot.ai/)
Key from [platform.moonshot.ai](https://platform.moonshot.ai/console/api-keys). Set `KIMI_API_KEY`.

### [Cerebras](https://inference-docs.cerebras.ai/quickstart)
Key from Cerebras Cloud Console. Set `CEREBRAS_API_KEY`.

### [Groq](https://console.groq.com/)
Key from [console.groq.com/keys](https://console.groq.com/keys). Set `GROQ_API_KEY`.

### [Fireworks AI](https://fireworks.ai/)
Key from [fireworks.ai/account/api-keys](https://fireworks.ai/account/api-keys). Set `FIREWORKS_API_KEY`.

### [Z.ai](https://z.ai/)
Key from Z.ai. Set `ZAI_API_KEY`.

### [LM Studio](https://lmstudio.ai/)
Local. Start the server, load a model, keep `LM_STUDIO_BASE_URL`, prefix with `lmstudio/`.

### [llama.cpp](https://github.com/ggml-org/llama.cpp)
Local. Start `llama-server`, keep `LLAMACPP_BASE_URL`, prefix with `llamacpp/`.

### [Ollama](https://ollama.com/)
Local. `ollama pull <model>`, `ollama serve`, prefix with `ollama/`.

---

## Connect your editor

### Claude Code CLI

```bash
fcc                  # launch (or resume latest)
fcc resume           # latest session
fcc resume <name>
fcc sessions list
fcc sessions doctor
fcc context doctor
fcc-bootstrap-context
```

`sdc` is an alias — `sdc resume` does the same thing.

### VS Code

Add to `claudeCode.environmentVariables` in settings.json:

```json
{
  "name": "ANTHROPIC_BASE_URL", "value": "http://localhost:8082"
},
{
  "name": "ANTHROPIC_AUTH_TOKEN", "value": "freecc"
},
{
  "name": "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "value": "1"
},
{
  "name": "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "190000"
}
```

### JetBrains

Edit `~/.jetbrains/acp.json` (or `%APPDATA%\JetBrains\acp-agents\installed.json` on Windows), find `acp.registry.claude-acp`, and set the same env vars under `"env"`.

---

## Discord and Telegram bots

SEPCC can run Claude Code sessions through Discord or Telegram. You chat, it codes, streams output back.

**Discord:** Create a bot in the Developer Portal, enable Message Content Intent, invite it with read/send/message history, copy the token and channel ID.

**Telegram:** Create a bot with @BotFather, get your user ID from @userinfobot.

Configure in the Admin UI under Messaging. `/stop` cancels a task, `/clear` resets, `/stats` shows state.

### Voice notes

Install with the voice extras, then configure in Admin UI → Messaging → Voice. Works with local Whisper or NVIDIA NIM.

---

## How it works

Claude Code talks Anthropic's Messages API. SEPCC sits in the middle, takes those requests, and routes them to whatever provider you picked. The provider's response gets normalized back into the shape Claude Code expects — thinking blocks, tool calls, streaming SSE, all of it.

The part SEPCC adds on top of FCC is the context layer:

```
Claude Code CLI
  → FastAPI routes (/v1/messages, /v1/models, ...)
    → model routing (Opus/Sonnet/Haiku → specific providers)
      → provider transport (Anthropic-compatible or OpenAI-compat)
        → upstream API
          ← response normalized back to Anthropic shape
```

Around that, the hook system maintains state across sessions:
- `SessionStart` — injects the runtime contract and current handoff
- `SubagentStop` — updates the handoff after subagents finish
- `PreCompact` — saves critical context before compaction kicks in
- `UserPromptSubmit` — handles handoff recall requests
- `Stop` — final persistence

---

## Development

### Project layout

```
SEPCC/
├── server.py              # entry point
├── api/                   # FastAPI routes, admin UI, model router
├── core/
│   ├── anthropic/         # protocol helpers, SSE, thinking, tools
│   └── context/           # handoff, retrieval, SQLite store (SEPCC)
├── providers/             # 17 provider transports + registry
├── messaging/             # Discord, Telegram, voice
├── cli/                   # launcher, session mgmt, bootstrap, doctor
├── config/                # settings, provider catalog
├── scripts/hooks/         # lifecycle hook scripts
├── templates/project/     # bootstrap scaffold
├── docs/                  # context hardening docs
└── tests/                 # unit, contract, smoke
```

### Running from source

```bash
git clone https://github.com/sepehrbayat/SEPCC.git
cd SEPCC
uv run uvicorn server:app --host 0.0.0.0 --port 8082
```

### Checks before pushing

```bash
uv run ruff format
uv run ruff check
uv run pytest
```

### Package entry points

- `fcc` — Claude Code launcher
- `sdc` — alias for `fcc`
- `fcc-server` — start the proxy
- `fcc-init` — scaffold `~/.fcc/.env`
- `fcc-claude` — compatibility launcher
- `free-claude-code` — alias for `fcc-server`

### Adding a provider

Extend `OpenAIChatTransport` (OpenAI-compatible) or `AnthropicMessagesTransport` (Anthropic-compatible). Register in `config/provider_catalog.py` and `providers/registry.py`.

---

## Contributing

Keep PRs small and tested. Don't open Docker PRs. Don't open README PRs — open an issue instead. Run `ruff format`, `ruff check`, and `pytest` before pushing.

Python 3.14 brought back `except X, Y` syntax (it's in the final release, wasn't in the alpha). Keep that in mind.

---

## License

MIT — see [LICENSE](LICENSE).

Copyright (c) 2026 Ali Khokhar (original Free Claude Code)
Copyright (c) 2026 Sepehr Bayat (SEPCC additions)

### What we depend on

| Package | License | What it does |
|---------|---------|--------------|
| FastAPI | MIT | API framework |
| Uvicorn | BSD 3-Clause | ASGI server |
| httpx | BSD 3-Clause | HTTP client |
| Pydantic | MIT | Data validation |
| Pydantic Settings | MIT | Env-based config |
| tiktoken | MIT | Token counting |
| OpenAI Python | Apache 2.0 | OpenAI-compat adapters |
| aiohttp | Apache 2.0 | Async HTTP |
| Loguru | MIT | Logging |
| python-dotenv | BSD 3-Clause | .env loading |
| markdown-it-py | MIT | Markdown rendering |
| python-telegram-bot | LGPLv3 | Telegram bot |
| discord.py | MIT | Discord bot |

Voice extras: gRPC (Apache 2.0), nvidia-riva-client (NVIDIA proprietary), PyTorch (BSD), Transformers (Apache 2.0), Accelerate (Apache 2.0), librosa (ISC).

Dev: pytest (MIT), pytest-asyncio (Apache 2.0), pytest-cov (MIT), pytest-xdist (MIT), Ruff (MIT), Ty (MIT).

### Not affiliated with Anthropic

SEPCC is a proxy. Claude Code is Anthropic's product. We're not associated with Anthropic. Their API, their terms, their trademarks.

---

<div align="center">

[github.com/sepehrbayat/SEPCC](https://github.com/sepehrbayat/SEPCC) · [Issues](https://github.com/sepehrbayat/SEPCC/issues) · [Upstream FCC](https://github.com/Alishahryar1/free-claude-code)

</div>
