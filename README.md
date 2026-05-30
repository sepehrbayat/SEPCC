<div align="center">

# SEPCC — Unlimited Claude Code, with context that survives

A free and open-source proxy that gives you **unlimited Claude Code** access by routing API calls through any provider you choose. Built on [Free Claude Code](https://github.com/Alishahryar1/free-claude-code), SEPCC adds sessions you can actually resume, a context handoff that survives crashes, and a one-command project bootstrapper — everything you need for real, multi-session work with **unlimited Claude Code** usage, no Anthropic rate limits, no per-token bills.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json&style=for-the-badge)](https://github.com/astral-sh/uv)

[Quick Start](#quick-start) · [What SEPCC adds](#what-sepcc-adds) · [Providers](#providers) · [Development](#development) · [License & Attributions](#license-and-attributions)

</div>

---

## The short version

Claude Code is the best AI coding assistant out there. The catch? Anthropic's pricing and rate limits. If you code all day, the costs add up fast.

SEPCC is a **free Claude Code alternative** that sits between Claude Code and the API layer. Claude Code thinks it's talking to Anthropic — but you're routing through DeepSeek, Gemini, OpenRouter, a local Llama, whatever you want. The result is **unlimited Claude Code** sessions. No rate caps. No per-message billing. You own the backend, you set the rules.

The proxy part existed in FCC already. SEPCC adds a full context-hardening layer on top: sessions you can pick back up after a crash, a handoff file that keeps your place between restarts, and a bootstrapper that scaffolds an entire project for long-running **unlimited Claude Code** work in one command. If you're looking for a **Claude Code without limits** setup, this is it.

Forked from [Ali Khokhar's Free Claude Code](https://github.com/Alishahryar1/free-claude-code). We're grateful for the foundation — all original MIT license terms are preserved.

---

## What SEPCC adds

FCC was a solid provider router. It proxied API calls from Claude Code to 17+ backends. That part works. But sessions were ephemeral — when Claude Code crashed or you restarted, your context was gone. That's the problem we solved. Here's everything we built:

### Sessions you can resume

SEPCC keeps a SQLite registry at `.fcc/sessions.sqlite` that tracks every session in your project. You're no longer one crash away from losing your place:

```bash
fcc                  # start fresh, or auto-resume latest
fcc resume           # resume the most recent session
fcc resume my-session
fcc sessions list    # everything in this project
fcc sessions doctor  # check for stale entries
```

Behind the scenes, it tries `claude --resume` first (full Claude transcript). If the transcript is lost but `.fcc/context/handoff.md` is there, it starts a fresh session and injects your handoff as context. Not seamless, but you won't lose your train of thought.

Set `FCC_AUTO_RESUME_LAST_SESSION=true` and plain `fcc` auto-resumes whatever you were working on.

### A context handoff that actually survives

Chat context is volatile. Claude compacts it. Sessions crash. You lose track of decisions and next steps. SEPCC's handoff file at `.fcc/context/handoff.md` is our answer — it tracks:

- what you're working on right now
- decisions you've already made
- the next concrete step

It's a few lines, not a transcript. `SessionStart` injects it into every new chat. `SubagentStop` refreshes it after delegated work. Raw terminal and tool output goes to a SQLite sidecar so the handoff stays compact. For anyone doing **unlimited Claude Code** sessions that span days or weeks, this is the difference between a workflow and a mess.

### One command to bootstrap a project

```bash
fcc-bootstrap-context
```

Drops 50+ files into the target project:

- `CLAUDE.md` and `CLAUDE.local.md` — project rules and local machine facts
- `.claude/agents/` — four project agents (code reviewer, context auditor, product logic reviewer, researcher)
- `.claude/skills/` — three Claude Code skills (context-recall, handoff-writer, route-task)
- `.claude/commands/` — slash commands: `handoff`, `recall`, `verify-context`
- `.fcc/context/` — handoff, decisions, facts, agent runtime contract
- `.fcc/plugin-policy.yml` — enforces single-owner rules per hook
- `.mcp.json` — Token Savior config for code retrieval
- `.claude/settings.json` — all five lifecycle hooks wired and ready

Flags: `--force`, `--install-token-savior`, `--install-memsearch`, `--large-repo`. This is what turns a bare project into a proper **unlimited Claude Code** workspace.

### Context doctor

```bash
fcc context doctor
```

Validates and auto-repairs the scaffolding. Checks:

- all runtime files are present
- all five hooks are configured
- no duplicate hook owners
- MemSearch and Claude-mem aren't both claiming memory
- Token Savior is the code retrieval owner
- Ralph Loop has bounds and verification
- SubagentStop is correctly used as the subagent lifecycle hook

### Subagent architecture — a note

Claude Code's official docs document `SubagentStop` as the stable hook for subagent lifecycle events. There is no stable `SubagentStart`. Subagent startup awareness comes through project agent definitions and the supported hooks. SEPCC's bootstrapper sets this up correctly, and the context doctor validates it.

### Provider fixes from the FCC base

- **Gemini**: fixed a bug where dual thinking controls produced malformed requests
- **Provider registry**: added dynamic registration and validation
- **Settings**: added system proxy auto-detection
- **Admin UI**: extended with session and context management views

### FCC vs SEPCC

| Capability | FCC | SEPCC |
|-----------|-----|-------|
| 17 provider backends | yes | yes |
| Model routing (Opus/Sonnet/Haiku) | yes | yes |
| Admin UI | yes | yes (extended) |
| Discord/Telegram bots | yes | yes |
| Voice notes (Whisper + NIM) | yes | yes |
| Session resume | no | **yes — SQLite registry + smart fallback** |
| Context handoff | no | **yes — survives crashes and compaction** |
| Project bootstrapper | no | **yes — one command, 50+ files** |
| Context doctor | no | **yes — validation + auto-repair** |
| Agent runtime contract | no | **yes — hook-injected every session** |
| Project subagent definitions | no | **4 specialized agents** |
| Claude Code project skills | no | **3 project skills** |
| Slash commands | no | **handoff, recall, verify-context** |
| Gemini thinking controls | bugged | **fixed** |
| System proxy support | no | **yes** |

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

Open the Admin UI URL. Pick a provider, paste your API key, click **Validate** then **Apply**.

The default model is `deepseek/deepseek-v4-pro`. You'll need a [DeepSeek API key](https://platform.deepseek.com/api_keys). Or choose any of the 17 supported providers listed below — that's the whole point of **unlimited Claude Code**: you pick the backend.

### 4. Launch Claude Code

```bash
fcc
```

`fcc` sets the environment variables Claude Code needs, runs a quick update check, then launches the real `claude` command. Keep `fcc-server` running in another terminal.

---

## Providers

SEPCC supports 17 providers — the backbone of your **unlimited Claude Code** setup. Set `MODEL` to any of these. Leave `MODEL_OPUS`, `MODEL_SONNET`, `MODEL_HAIKU` blank to use `MODEL` for everything, or set them individually to mix providers by model tier.

### [NVIDIA NIM](https://build.nvidia.com/)
Key from [build.nvidia.com/settings/api-keys](https://build.nvidia.com/settings/api-keys). Set `NVIDIA_NIM_API_KEY`. Default: `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`.

### [OpenRouter](https://openrouter.ai/)
Key from [openrouter.ai/keys](https://openrouter.ai/keys). Set `OPENROUTER_API_KEY`. Free models available — a great option for **unlimited Claude Code** on a budget.

### [Google AI Studio (Gemini)](https://aistudio.google.com/)
Key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Set `GEMINI_API_KEY`. Free tier with per-model quotas.

### [DeepSeek](https://platform.deepseek.com/)
Key from [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys). Set `DEEPSEEK_API_KEY`. Uses Anthropic-compatible endpoint.

### [Mistral La Plateforme](https://console.mistral.ai/)
Key from Mistral console. Set `MISTRAL_API_KEY`. Free Experiment plan.

### [Mistral Codestral](https://console.mistral.ai/)
Separate key — set `CODESTRAL_API_KEY`. Prefix models with `mistral_codestral/`.

### [OpenCode Zen](https://opencode.ai/)
Key from [opencode.ai/auth](https://opencode.ai/auth). Set `OPENCODE_API_KEY`. Free models available.

### [OpenCode Go](https://opencode.ai/)
Same key as Zen. Prefix models with `opencode_go/`.

### [Wafer](https://wafer.ai/)
Key from Wafer. Set `WAFER_API_KEY`. Anthropic-compatible endpoint.

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
Local. Start the server, load a model, keep `LM_STUDIO_BASE_URL`, prefix with `lmstudio/`. Completely offline **unlimited Claude Code**.

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

`sdc` is an alias — `sdc resume` works the same.

### VS Code

Add to `claudeCode.environmentVariables` in settings.json:

```json
{ "name": "ANTHROPIC_BASE_URL", "value": "http://localhost:8082" },
{ "name": "ANTHROPIC_AUTH_TOKEN", "value": "freecc" },
{ "name": "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "value": "1" },
{ "name": "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "190000" }
```

### JetBrains

Edit `~/.jetbrains/acp.json` (or `%APPDATA%\JetBrains\acp-agents\installed.json` on Windows), find `acp.registry.claude-acp`, set the same env vars under `"env"`.

---

## Discord and Telegram bots

SEPCC can run Claude Code sessions through Discord or Telegram. You chat, it streams code back.

**Discord:** Create a bot in the Developer Portal, enable Message Content Intent, invite with read/send/message history, copy the token and channel ID.

**Telegram:** Create a bot with @BotFather, get your user ID from @userinfobot.

Configure in Admin UI → Messaging. `/stop` cancels, `/clear` resets, `/stats` shows state.

### Voice notes

Install with voice extras, configure in Admin UI → Messaging → Voice. Supports local Whisper or NVIDIA NIM.

---

## Your first prompt

When you start a fresh project session, what you say first sets the tone for everything that follows. A good first prompt saves you hours of corrections later. A vague one has Claude guessing at what you actually want.

### The template

Here's a prompt that works for pretty much any new project. Copy it, fill in your details, and drop it into Claude Code:

```
I'm starting a new project called [NAME]. Here's what I'm building:

[2-3 sentences describing what the software does and who it's for.]

Tech stack: [languages, frameworks, database, anything relevant.]

Project structure so far:
- [key files and what they do]
- [any existing architecture decisions]

Before writing code, can you:
1. Read through the project files to understand what's already here
2. Confirm you understand the goal — ask me questions if anything is unclear
3. Suggest a plan for the first piece of work, in the order it should be built

I'd like to work incrementally. Let's start with [concrete first task] and build from there.
```

### Why this works

Most people open Claude Code and say "build me a todo app." That gets you something generic. This prompt does three things that matter:

- **Context first.** You're telling Claude to read and understand before it writes. SEPCC will inject your handoff and project rules via the SessionStart hook anyway, but being explicit about reading files means Claude actually looks at your codebase instead of hallucinating a structure.
- **Bounded scope.** "Let's start with this one thing" prevents Claude from writing 800 lines across 12 files before you've agreed on the approach. You can review, course-correct, and move on.
- **Questions allowed.** Telling Claude it can ask clarifying questions means it won't silently guess when something is ambiguous. Fewer wrong assumptions, fewer rewrites.

### A real example

Say you're building a CLI tool that converts CSV files to JSON. Your repo already has a `pyproject.toml` and an empty `src/` directory. Here's what you'd actually type:

```
I'm building a CLI tool called csv2json that reads CSV files and outputs JSON.
It should handle large files streaming, support custom delimiters, and have
pretty-print and compact output modes. Tech stack: Python, Click for CLI,
pytest for tests. Project structure: pyproject.toml, empty src/csv2json/.

Before writing code, can you:
1. Read pyproject.toml to understand the project setup
2. Confirm you understand the requirements
3. Suggest a plan starting with the CLI entry point and a basic streaming converter

Let's start with the Click CLI skeleton that accepts --delimiter, --pretty,
and an input file argument. We'll wire up the converter after.
```

The more specific you are in that first message, the better the whole session goes. For **unlimited Claude Code** sessions that span days, this upfront clarity compounds — every decision you nail early saves you from digging through old handoff entries later.

---

## How it works

Claude Code speaks Anthropic's Messages API. SEPCC intercepts those requests and routes them to whichever provider you configured. Responses get normalized back into the shape Claude Code expects — thinking blocks, tool calls, streaming SSE, everything.

The context layer SEPCC adds on top:

```
Claude Code CLI
  → FastAPI routes (/v1/messages, /v1/models, ...)
    → model routing (Opus/Sonnet/Haiku → specific providers)
      → provider transport (Anthropic-compatible or OpenAI-compat)
        → upstream API
          ← response normalized back to Anthropic shape
```

Hooks maintain state across sessions:
- `SessionStart` — injects runtime contract + current handoff
- `SubagentStop` — updates handoff after subagents finish
- `PreCompact` — preserves critical context before compaction
- `UserPromptSubmit` — handles handoff recall
- `Stop` — final persistence

---

## V2Ray system proxy (port 10808)

If you're behind internet restrictions or a firewall — common in some regions — SEPCC has you covered. It auto-detects local proxy software that's already running on your machine and routes provider API calls through it.

### How it works

SEPCC reads your Windows proxy settings from the registry (`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Internet Settings`). When it finds a proxy configured on a known local SOCKS port — like V2Ray on **10808** — it normalizes the address to `socks5://127.0.0.1:10808` and uses it for outbound API calls.

The ports SEPCC recognizes:

| Port | Typical software |
|------|-----------------|
| 10808 | V2Ray / V2RayN (default SOCKS5) |
| 10809 | V2Ray HTTP proxy |
| 1080 | Generic SOCKS5 proxy |
| 1086 | Shadowsocks / alternative setups |
| 7890 | Clash / Clash Verge |
| 7891 | Clash mixed port |

### What "system-wide" means

This isn't a SEPCC-specific proxy setting. When you enable V2Ray's system proxy mode, Windows updates the registry, and SEPCC picks it up automatically through `AUTO_DETECT_SYSTEM_PROXY` (enabled by default). The result: all 17 providers route through your V2Ray tunnel without you touching a single SEPCC config field. Your terminal, your CLI tools, and SEPCC all use the same proxy — no per-app setup.

You can also set per-provider proxies in the Admin UI (each provider has a `_PROXY` env var like `DEEPSEEK_PROXY`, `GEMINI_PROXY`, etc.) if you want different routing for different backends. Per-provider proxies take priority over system auto-detection.

To disable auto-detection, flip `AUTO_DETECT_SYSTEM_PROXY` to `false` in the Admin UI under Providers → Advanced.

---

## Windows Desktop Shortcut

On Windows, SEPCC comes with a desktop shortcut launcher that starts the proxy server and drops you directly into a project — no terminal commands needed.

### What happens when you double-click it

1. The `launch-fcc-claude.cmd` script starts the SEPCC proxy server in a separate window.
2. It waits for the server to become healthy (up to 30 seconds).
3. `pick-project.ps1` opens and shows you a numbered list of all folders inside your projects directory.
4. You pick a project — by number, by browsing with a folder dialog, or by typing a path manually.
5. It launches `fcc-claude` pointed at that project folder.

The shortcut works out of the box. You can pin it to your taskbar or start menu.

### The projects path

The project picker looks for folders inside `%USERPROFILE%\projects` by default — that's `C:\Users\<your-name>\projects`. You can override it by setting the `FCC_PROJECTS_ROOT` environment variable to any path you want.

**If the folder doesn't exist yet, the picker creates it for you automatically.** No error, no manual `mkdir` step. The first time you run the shortcut, it creates the folder silently and shows an empty list — you can still browse or type a path manually. After you've added projects to the folder, they show up in the numbered list.

### Customizing the shortcut

The launcher resolves the SEPCC repo location automatically from the script's own location — no hardcoded paths. If you move the repo, the shortcut follows. If you need to override it (for example, if you want the shortcut to live somewhere else but still point to the right install), set `FCC_REPO_ROOT`:

```cmd
set "FCC_REPO_ROOT=D:\tools\SEPCC"
```

### The full path chain, explained

When you click the shortcut:

```
Desktop shortcut (launch-fcc-claude.cmd)
  → Script resolves repo root from its own location (%~dp0..\..)
  → Starts proxy server on port 8082
  → Runs pick-project.ps1:
      → Looks in %FCC_PROJECTS_ROOT% (default: %USERPROFILE%\projects)
      → Auto-creates the folder if it doesn't exist
      → Lists subdirectories as numbered choices
      → Or: B to browse, 0 to type a path
  → Launches fcc-claude <selected-project-path>
  → fcc-claude sets up environment, runs claude --resume (or fresh)
```

This is meant to be the frictionless Windows experience. No terminal, no manual env var setup, no "where's my project root." Just double-click, pick a project, start coding.

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

Python 3.14 brought back `except X, Y` syntax (final release, not alpha). Keep in mind.

---

## License and Attributions

We take open-source licensing seriously. Every dependency in this project is used in compliance with its license terms, and we're grateful to the maintainers who make this work possible.

### SEPCC License

SEPCC is licensed under the **MIT License**. See [LICENSE](LICENSE) for the full text.

```
MIT License

Copyright (c) 2026 Ali Khokhar (original Free Claude Code)
Copyright (c) 2026 Sepehr Bayat (SEPCC additions and modifications)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Runtime Dependencies

These are the libraries SEPCC depends on at runtime. Each is used under its own license. We include links to every project's source repository and license.

| Package | License | Source |
|---------|---------|--------|
| **FastAPI** | MIT | [github.com/fastapi/fastapi](https://github.com/fastapi/fastapi) |
| **Uvicorn** | BSD 3-Clause | [github.com/encode/uvicorn](https://github.com/encode/uvicorn) |
| **httpx** | BSD 3-Clause | [github.com/encode/httpx](https://github.com/encode/httpx) |
| **Pydantic** | MIT | [github.com/pydantic/pydantic](https://github.com/pydantic/pydantic) |
| **Pydantic Settings** | MIT | [github.com/pydantic/pydantic-settings](https://github.com/pydantic/pydantic-settings) |
| **tiktoken** | MIT | [github.com/openai/tiktoken](https://github.com/openai/tiktoken) |
| **OpenAI Python** | Apache 2.0 | [github.com/openai/openai-python](https://github.com/openai/openai-python) |
| **aiohttp** | Apache 2.0 | [github.com/aio-libs/aiohttp](https://github.com/aio-libs/aiohttp) |
| **Loguru** | MIT | [github.com/Delgan/loguru](https://github.com/Delgan/loguru) |
| **python-dotenv** | BSD 3-Clause | [github.com/theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) |
| **markdown-it-py** | MIT | [github.com/executablebooks/markdown-it-py](https://github.com/executablebooks/markdown-it-py) |
| **python-telegram-bot** | LGPLv3 | [github.com/python-telegram-bot/python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) |
| **discord.py** | MIT | [github.com/Rapptz/discord.py](https://github.com/Rapptz/discord.py) |

### Optional Voice Dependencies

These are only installed when you opt into voice features. Their licenses apply only when you choose to install them.

| Package | License | Source |
|---------|---------|--------|
| **gRPC** | Apache 2.0 | [github.com/grpc/grpc](https://github.com/grpc/grpc) |
| **nvidia-riva-client** | NVIDIA Proprietary | NVIDIA Riva SDK |
| **PyTorch** | BSD 3-Clause | [github.com/pytorch/pytorch](https://github.com/pytorch/pytorch) |
| **Transformers** | Apache 2.0 | [github.com/huggingface/transformers](https://github.com/huggingface/transformers) |
| **Accelerate** | Apache 2.0 | [github.com/huggingface/accelerate](https://github.com/huggingface/accelerate) |
| **librosa** | ISC | [github.com/librosa/librosa](https://github.com/librosa/librosa) |

### Development Dependencies

Used for testing, linting, formatting, and type checking. Not required at runtime.

| Package | License | Source |
|---------|---------|--------|
| **pytest** | MIT | [github.com/pytest-dev/pytest](https://github.com/pytest-dev/pytest) |
| **pytest-asyncio** | Apache 2.0 | [github.com/pytest-dev/pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) |
| **pytest-cov** | MIT | [github.com/pytest-dev/pytest-cov](https://github.com/pytest-dev/pytest-cov) |
| **pytest-xdist** | MIT | [github.com/pytest-dev/pytest-xdist](https://github.com/pytest-dev/pytest-xdist) |
| **Ruff** | MIT | [github.com/astral-sh/ruff](https://github.com/astral-sh/ruff) |
| **Ty** | MIT | [github.com/paulz/ty](https://github.com/paulz/ty) |

### Anthropic and Claude Code

SEPCC is an independent proxy and is **not affiliated with, endorsed by, or associated with Anthropic PBC**. Claude Code is a product of Anthropic. The Anthropic Messages API, Claude Code client protocol, and all Anthropic trademarks are governed by Anthropic's own terms of service and commercial agreements. You are responsible for complying with Anthropic's terms when using Claude Code.

### Upstream Attribution

This project is a fork of [Free Claude Code](https://github.com/Alishahryar1/free-claude-code) by Ali Khokhar, licensed under MIT. The original work established the provider-agnostic proxy architecture that SEPCC builds on. We've preserved the original MIT license and added copyright for all SEPCC additions. Our changes are also MIT-licensed so the project remains fully open.

---

<div align="center">

[github.com/sepehrbayat/SEPCC](https://github.com/sepehrbayat/SEPCC) · [Issues](https://github.com/sepehrbayat/SEPCC/issues) · [Upstream FCC](https://github.com/Alishahryar1/free-claude-code)

</div>
