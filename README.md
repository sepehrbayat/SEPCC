<div align="center">

# 🚀 SEPCC — Unlimited Cloud Code

**SEPCC (Software-Enabled Proxy for Claude Code)** — the **Unlimited Cloud Code** platform. Use Claude Code CLI, VS Code, JetBrains ACP, or chat bots through your own Anthropic-compatible proxy with **zero usage limits**. Free, open-source, and provider-agnostic.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json&style=for-the-badge)](https://github.com/astral-sh/uv)
[![Code style: Ruff](https://img.shields.io/badge/code%20formatting-ruff-f5a623.svg?style=for-the-badge)](https://github.com/astral-sh/ruff)
[![Logging: Loguru](https://img.shields.io/badge/logging-loguru-4ecdc4.svg?style=for-the-badge)](https://github.com/Delgan/loguru)

**Unlimited Cloud Code** is a free AI coding proxy that routes Anthropic Messages API traffic from Claude Code to any provider — giving you **unlimited access to AI-powered coding** through free, paid, or local models. No rate limits, no per-message billing, no vendor lock-in.

*Forked from [Free Claude Code](https://github.com/Alishahryar1/free-claude-code) by Ali Khokhar.*

[Quick Start](#quick-start) · [Providers](#choose-a-provider) · [Clients](#connect-claude-code) · [Integrations](#optional-integrations) · [Development](#development) · [License & Attributions](#license-and-attributions)

</div>

<div align="center">
  <img src="assets/pic.png" alt="SEPCC Unlimited Cloud Code in action" width="700">
</div>

## Star History

<div align="center">
  <a href="https://star-history.com/#sepehrbayat/SEPCC&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=sepehrbayat/SEPCC&type=Date&theme=dark">
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=sepehrbayat/SEPCC&type=Date">
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=sepehrbayat/SEPCC&type=Date" width="700">
    </picture>
  </a>
</div>

---

## What is SEPCC Unlimited Cloud Code?

**SEPCC (Unlimited Cloud Code)** is a drop-in proxy that lets you use Claude Code — Anthropic's flagship AI coding assistant — while routing all API traffic through your own backend providers. This means **unlimited coding sessions** without Anthropic API quotas, per-token charges, or usage caps.

SEPCC is a fork of [Free Claude Code](https://github.com/Alishahryar1/free-claude-code) by Ali Khokhar. We took FCC's solid provider-proxy foundation and built an entire **deterministic context layer** on top of it — turning a stateless proxy into a stateful, resumable, long-running AI coding platform.

### Why Unlimited Cloud Code?

| Feature | SEPCC Unlimited Cloud Code | Standard Claude Code |
|---------|---------------------------|---------------------|
| **Usage limits** | None (your provider, your rules) | Anthropic rate limits |
| **Per-message cost** | Free with free-tier providers | Pay-per-token |
| **Provider choice** | 17+ backends | Anthropic only |
| **Model mixing** | Route Opus/Sonnet/Haiku to different providers | Single provider |
| **Local models** | LM Studio, llama.cpp, Ollama | Not supported |
| **Offline coding** | Yes (local models) | No |
| **Discord/Telegram bots** | Built-in | Not available |
| **Voice notes** | Whisper + NVIDIA NIM | Not available |
| **Session resume** | Full project-local session recovery | Limited transcript replay |
| **Context hardening** | Deterministic handoff, memory, facts | Chat-only context |

---

## What SEPCC Built on Top of FCC

FCC was a provider-router — it proxied API calls. SEPCC adds **five major systems** that turn it from a stateless proxy into a full AI coding platform with deterministic context, session resilience, and automated project bootstrapping.

### 1. Context Hardening System (`core/context/`)

The original FCC lost all context on session restart. SEPCC introduces a **deterministic context layer** that survives crashes, compaction, and restarts:

- **Handoff Engine** (`handoff.py`) — persists *what must not be forgotten* across sessions: current task, decisions made, next concrete step. Unlike raw transcripts, the handoff is a compact structured file that gets injected into every `SessionStart`.
- **SQLite Sidecar** (`sqlite_store.py`) — stores raw terminal and tool outputs by handle, queryable via `fcc-context-store` and `fcc-context-query`. Keeps the handoff slim while making raw data retrievable on demand.
- **Retrieval Pipeline** (`retrieval.py`, `summarizer.py`, `storage.py`) — fetches, summarizes, and stores relevant context snippets so subagents and resumed sessions have exactly what they need without replaying full transcripts.

### 2. Project Bootstrapper (`cli/bootstrap_context.py`)

One command scaffolds an entire project for long-running Claude Code work:

```bash
fcc-bootstrap-context
```

This installs 50+ files into the target project:

- **CLAUDE.md** and **CLAUDE.local.md** with project rules and local-machine facts
- **Compact FCC hooks** (`scripts/hooks/`) — `SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact`, `SubagentStop` — each with a single owner, no hook collisions
- **Token Savior MCP** config in `.mcp.json` for deterministic code retrieval
- **FCC context files** (`.fcc/context/`) — runtime contract, handoff, decisions, facts
- **Plugin policy** (`.fcc/plugin-policy.yml`) — enforces single-owner rules for memory, code retrieval, and hooks
- **Project subagents** (`.claude/agents/`) — specialized agents for code review, context auditing, product-logic review, and research
- **Claude Code skills** (`.claude/skills/`) — context-recall, handoff-writer, route-task
- **Slash commands** (`.claude/commands/`) — `handoff`, `recall`, `verify-context`

Flags: `--force`, `--install-token-savior`, `--install-memsearch`, `--large-repo`.

### 3. Context Doctor (`cli/context_doctor.py`)

Validates and auto-repairs the FCC runtime scaffolding:

```bash
fcc context doctor
```

Checks and reports on:
- Runtime contract file existence
- Plugin policy integrity
- Agent definition completeness
- Supported hook configuration (all 5 required hooks)
- Duplicate hook owner detection
- MemSearch vs Claude-mem mutual exclusion
- Token Savior baseline ownership
- Ralph Loop policy (bounded, verified iterations with max cap)
- SubagentStop as the stable subagent lifecycle hook (per official Claude Code docs)

Run it anytime to verify your project's context layer is intact.

### 4. Terminal Session Management (`cli/session_registry.py`, `cli/session_resume.py`, `cli/fcc_cli.py`)

FCC sessions were ephemeral. SEPCC adds a **project-local session registry** (`.fcc/sessions.sqlite`) that makes sessions resumable:

```bash
fcc                  # launch (or auto-resume latest in project)
fcc resume           # resume latest compatible session
fcc resume <id>      # resume specific session
fcc sessions list    # list all sessions in project
fcc sessions last    # show most recent
fcc sessions doctor  # health check
fcc sessions clean   # remove stale entries
fcc sessions rename <id> "name"
```

How resume works:
- If the native Claude transcript exists → `claude --resume` for full context
- If the transcript is lost but `handoff.md` exists → fresh session injected with compact handoff + retrieval snippets, linked as a continuation
- `FCC_AUTO_RESUME_LAST_SESSION=true` auto-resumes the latest compatible session on plain `fcc`
- `FCC_AUTO_RESUME_MAX_AGE_DAYS` and `FCC_AUTO_RESUME_PROJECT_SCOPED` tune auto-resume behavior

### 5. Agent Runtime & Hook Architecture

SEPCC ships a complete agent runtime contract (`.fcc/context/agent-runtime.md`) injected via `SessionStart` into every main chat. Subagents inherit operating rules from project agent definitions. Six hook scripts handle lifecycle events:

| Hook | Script | Purpose |
|------|--------|---------|
| `SessionStart` | `session_start.py` | Injects runtime contract, local facts, current handoff |
| `UserPromptSubmit` | `user_prompt_submit.py` | Processes handoff recall on request |
| `PreCompact` | `precompact.py` | Preserves critical context before compaction |
| `SubagentStop` | `subagent_stop.py` | Refreshes handoff after delegated subagent work |
| `Stop` | `stop.py` | Final state persistence on session end |

### Provider Enhancements

Beyond the context layer, SEPCC fixed and extended several providers from the FCC base:
- **Gemini**: fixed dual thinking controls that caused malformed requests
- **Provider Registry**: extended with dynamic registration and validation
- **Settings**: expanded configuration surface with system proxy support
- **Admin UI**: extended sidebar with session and context management views

### Summary: FCC vs SEPCC

| Capability | Original FCC | SEPCC |
|-----------|-------------|-------|
| Provider proxy (17 backends) | Yes | Yes |
| Model routing (Opus/Sonnet/Haiku) | Yes | Yes |
| Admin UI | Yes | Yes (extended) |
| Discord/Telegram bots | Yes | Yes |
| Voice notes | Yes | Yes |
| **Context hardening** | No | **Built from scratch** |
| **Handoff persistence** | No | **SQLite-backed, compact, injectable** |
| **Session resume** | No | **Full project-local registry + smart resume** |
| **Project bootstrapper** | No | **One-command full scaffold (50+ files)** |
| **Context doctor** | No | **Validation + auto-repair** |
| **Agent runtime contract** | No | **Deterministic, hook-injected** |
| **Subagent definitions** | No | **4 specialized FCC agents** |
| **Claude Code skills** | No | **3 project skills** |
| **Slash commands** | No | **handoff, recall, verify-context** |
| **Gemini fix** | Bugged | **Fixed dual thinking controls** |
| **System proxy support** | No | **Auto-detect + configure** |

### Subagent Architecture

SEPCC supports Claude Code's subagent system through project agent definitions and the `SubagentStop` hook — the [officially documented](https://docs.anthropic.com/en/docs/claude-code/hooks) stable hook for subagent lifecycle management. Official Claude Code docs list `SubagentStop`, not a stable `SubagentStart`, so subagent startup awareness is provided through project agent definitions and supported hooks (`SessionStart`, `UserPromptSubmit`, `Stop`, `PreCompact`, `SubagentStop`). Subagents inherit operating rules from their project agent definitions, and `SubagentStop` refreshes handoff state after delegated work completes.

Sources: [Claude Code Hooks documentation](https://docs.anthropic.com/en/docs/claude-code/hooks), [Claude Code Subagents documentation](https://docs.anthropic.com/en/docs/claude-code/subagents).

---

## Quick Start

### 1. Fast Install

Install or update Claude Code, install or update uv, then install Python 3.14.0 and SEPCC Unlimited Cloud Code:

**macOS/Linux:**

```bash
curl -fsSL "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.sh?raw=1" | sh
```

**Windows PowerShell:**

```powershell
irm "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.ps1?raw=1" | iex
```

### 2. Start The Proxy

```bash
fcc-server
```

After startup, Uvicorn prints the proxy bind address and the app logs the admin URL:

```text
INFO:     Admin UI: http://127.0.0.1:8082/admin (local-only)
```

Many terminals make these clickable. Use your configured `PORT` if it is not `8082`.

### 3. Open The Admin UI And Configure DeepSeek

Open the **Admin UI** URL from the terminal output.

Need a DeepSeek API key? Use the **[DeepSeek provider](#deepseek-provider)** section below, then scroll back up here.

<div align="center">
  <img src="assets/admin-page.png" alt="SEPCC Unlimited Cloud Code admin UI" width="700">
</div>

Paste your DeepSeek API key into `DEEPSEEK_API_KEY`, then click **Validate** and **Apply**.

The default model is already set to `deepseek/deepseek-v4-pro`. You can change it later from the same Admin UI.

### 4. Run Claude Code

```bash
fcc
```

`fcc` reads the current configured port and auth token each time it starts, sets Claude Code environment variables (including a 190k-token `CLAUDE_CODE_AUTO_COMPACT_WINDOW` and package-manager auto-update opt-in), runs a throttled best-effort Claude Code update check, and then launches the real `claude` command.

Terminal sessions are project-local and resumable — see [Session & Context Commands](#1-claude-code-cli) below.

---

## Choose A Provider

Pick one provider, enter its key or local URL in the Admin UI, and set `MODEL` to a provider-prefixed model slug. `MODEL` is the fallback. `MODEL_OPUS`, `MODEL_SONNET`, and `MODEL_HAIKU` can override routing for Claude Code's model tiers.

<a id="nvidia-nim-provider"></a>

### 1. [NVIDIA NIM](https://build.nvidia.com/)

Get a key at [build.nvidia.com/settings/api-keys](https://build.nvidia.com/settings/api-keys).

In the Admin UI, paste it into `NVIDIA_NIM_API_KEY`. The default `MODEL` is `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`.

Popular examples:

- `nvidia_nim/nvidia/nemotron-3-super-120b-a12b`
- `nvidia_nim/z-ai/glm5.1`
- `nvidia_nim/moonshotai/kimi-k2.5`
- `nvidia_nim/minimaxai/minimax-m2.5`

Browse models at [build.nvidia.com](https://build.nvidia.com/explore/discover).

### 2. [OpenRouter](https://openrouter.ai/)

Get a key at [openrouter.ai/keys](https://openrouter.ai/keys).

In the Admin UI, paste it into `OPENROUTER_API_KEY`, then set `MODEL` to an OpenRouter slug such as `open_router/stepfun/step-3.5-flash:free`.

Browse [all models](https://openrouter.ai/models) or [free models](https://openrouter.ai/collections/free-models).

### 3. [Google AI Studio (Gemini)](https://aistudio.google.com/)

Get a Gemini API key at [Google AI Studio](https://aistudio.google.com/apikey) (see Google's [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai) docs).

In the Admin UI, paste it into `GEMINI_API_KEY`, then set `MODEL` to a Gemini model slug such as `gemini/gemini-2.5-flash` or `gemini/gemini-3.1-flash-lite`.

The Gemini API exposes an OpenAI-compatible endpoint at `https://generativelanguage.googleapis.com/v1beta/openai/`. Free tier quotas are per-model; prompts may be used to improve Google's products outside the UK/CH/EEA/EU unless your account region says otherwise — see Google's terms.

Popular examples:

- `gemini/gemini-2.5-flash`
- `gemini/gemini-3.1-flash-lite`

<a id="deepseek-provider"></a>

### 4. [DeepSeek](https://platform.deepseek.com/)

Get a key at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys).

In the Admin UI, paste it into `DEEPSEEK_API_KEY`, then set `MODEL` to a DeepSeek slug such as `deepseek/deepseek-v4-pro`.

This provider uses DeepSeek's Anthropic-compatible endpoint, not the OpenAI chat-completions endpoint.

Current official DeepSeek API model IDs are:

- `deepseek/deepseek-v4-pro`
- `deepseek/deepseek-v4-flash`

The legacy `deepseek/deepseek-chat` and `deepseek/deepseek-reasoner` compatibility names are scheduled for retirement on 2026-07-24.

### 5. [Mistral La Plateforme](https://console.mistral.ai/)

[Mistral](https://mistral.ai) hosts an OpenAI-compatible Chat Completions API at `https://api.mistral.ai/v1`. Activate the **Experiment** plan on [console.mistral.ai](https://console.mistral.ai/) for free-tier API access with rate limits (upgrade for higher quotas).

In the Admin UI, paste your API key into `MISTRAL_API_KEY`, then set `MODEL` to a Mistral model slug such as `mistral/devstral-small-latest` or `mistral/mistral-small-latest`.

Popular examples:

- `mistral/devstral-small-latest`
- `mistral/mistral-small-latest`

Browse models at [Mistral documentation](https://docs.mistral.ai/).

### 6. [Mistral Codestral](https://console.mistral.ai/)

Mistral's **Codestral** gateway uses a **separate API key** from La Plateforme: provision `CODESTRAL_API_KEY`, then route with the `mistral_codestral/` prefix. The default upstream is **`https://codestral.mistral.ai/v1`** (OpenAI-compatible Chat Completions; same request shaping as the `mistral` provider). See Mistral's [coding / FIM domains](https://docs.mistral.ai/mistral-vibe/using-fim-api); the curated [free LLM API list](https://github.com/cheahjs/free-llm-api-resources#mistral-codestral) summarizes typical Codestral access terms.

Popular examples:

- `mistral_codestral/codestral-latest`

### 7. [OpenCode Zen](https://opencode.ai/)

Get an API key at [opencode.ai/auth](https://opencode.ai/auth).

In the Admin UI, paste it into `OPENCODE_API_KEY`, then set `MODEL` to an OpenCode Zen model slug such as `opencode/gpt-5.3-codex`. The same `OPENCODE_API_KEY` powers **OpenCode Go** (below); use `opencode_go/` slugs there.

OpenCode Zen is a curated model gateway that provides access to models from Anthropic, OpenAI, Google, DeepSeek, and more through a single API key and OpenAI-compatible endpoint at `https://opencode.ai/zen/v1`.

Popular examples:

- `opencode/gpt-5.3-codex`
- `opencode/claude-sonnet-4`
- `opencode/deepseek-v4-flash-free` (free)
- `opencode/gemini-3-flash`
- `opencode/big-pickle` (free)
- `opencode/glm-5.1`

Browse available models at [opencode.ai](https://opencode.ai).

### 8. [OpenCode Go](https://opencode.ai/)

Get an API key at [opencode.ai/auth](https://opencode.ai/auth) (same as OpenCode Zen).

In the Admin UI, use `OPENCODE_API_KEY`, then set `MODEL` to an OpenCode Go model slug such as `opencode_go/minimax-m2.7`.

OpenCode Go is a subscription gateway with its own curated catalog and OpenAI-compatible endpoint at `https://opencode.ai/zen/go/v1`. It shares the **same OpenCode API key** as Zen; only the slug prefix (`opencode_go/` vs `opencode/`) and upstream path differ.

Popular examples:

- `opencode_go/minimax-m2.7`

Browse available models at [opencode.ai](https://opencode.ai).

### 9. [Wafer](https://wafer.ai/)

Get a key from [wafer.ai](https://wafer.ai). In the Admin UI, paste it into `WAFER_API_KEY`, then set `MODEL` to a Wafer Pass model such as `wafer/DeepSeek-V4-Pro`.

Popular examples:

- `wafer/DeepSeek-V4-Pro`
- `wafer/MiniMax-M2.7`
- `wafer/Qwen3.5-397B-A17B`
- `wafer/GLM-5.1`

This provider uses Wafer's Anthropic-compatible endpoint at `https://pass.wafer.ai/v1/messages`.

### 10. [Kimi](https://platform.moonshot.ai/)

Get a key at [platform.moonshot.ai/console/api-keys](https://platform.moonshot.ai/console/api-keys).

In the Admin UI, paste it into `KIMI_API_KEY`, then set `MODEL` to a Kimi slug such as `kimi/kimi-k2.5`.

This provider calls Kimi's **Anthropic-compatible** Messages API (`https://api.moonshot.ai/anthropic/v1/messages`; model discovery uses OpenAI-compat `GET https://api.moonshot.ai/v1/models`). It is **not** the OpenAI Chat Completions path.

Browse models at [platform.moonshot.ai](https://platform.moonshot.ai).

### 11. [Cerebras Inference](https://inference-docs.cerebras.ai/quickstart)

Sign up and create an API key in the [Cerebras Cloud Console](https://cloud.cerebras.ai) (see [Quickstart](https://inference-docs.cerebras.ai/quickstart)).

In the Admin UI, set `CEREBRAS_API_KEY`, then route with `MODEL` such as `cerebras/llama3.1-8b` or `cerebras/gpt-oss-120b` (ids from [List models](https://inference-docs.cerebras.ai/api-reference/models/list-models)).

Cerebras exposes an OpenAI-compatible API at `https://api.cerebras.ai/v1` ([OpenAI compatibility](https://inference-docs.cerebras.ai/resources/openai)). Non-standard request fields should go in `extra_body` when using the OpenAI client; see the same page. For reasoning models and parameters, see [Reasoning](https://inference-docs.cerebras.ai/capabilities/reasoning). This proxy follows other OpenAI-compat adapters for thinking via `reasoning_content` when Claude-style thinking is enabled.

### 12. [Groq](https://console.groq.com/)

Get an API key at [console.groq.com/keys](https://console.groq.com/keys).

In the Admin UI, paste it into `GROQ_API_KEY`, then set `MODEL` to a Groq OpenAI-compat model slug such as `groq/llama-3.3-70b-versatile`.

Groq routes through `https://api.groq.com/openai/v1` ([OpenAI-compatible Chat Completions](https://console.groq.com/docs/openai)). Some request fields yield HTTP 400; this adapter strips known-unsupported shapes (documented in Groq's compatibility notes).

Reasoning-heavy models expose extra knobs documented under [Groq reasoning](https://console.groq.com/docs/reasoning). This release mirrors other OpenAI-compat adapters for thinking via `reasoning_content` deltas when Claude-style thinking is enabled; you can tune advanced parameters through request `extra_body` when needed.

Browse models at [console.groq.com/docs/models](https://console.groq.com/docs/models).

### 13. [Fireworks AI](https://fireworks.ai/)

Get an API key at [fireworks.ai/account/api-keys](https://fireworks.ai/account/api-keys).

In the Admin UI, paste it into `FIREWORKS_API_KEY`, then set `MODEL` to a Fireworks model slug such as `fireworks/accounts/fireworks/models/llama-v3p3-70b-instruct`.

Fireworks exposes an **Anthropic-compatible** Messages API at `https://api.fireworks.ai/inference/v1/messages` (same inference host as before; Chat Completions is not used here). Vendor-specific JSON keys can still be merged from request `extra_body` when allowed.

Browse models at [fireworks.ai/models](https://fireworks.ai/models).

### 14. [Z.ai](https://z.ai/)

Get an API key at [Z.ai/manage-apikey/apikey-list](https://z.ai/manage-apikey/apikey-list).

In the Admin UI, paste it into `ZAI_API_KEY`, then set `MODEL` to a Z.ai model slug such as `zai/glm-5.1`.

This provider calls Z.ai's **Anthropic-compatible** Messages API (`https://api.z.ai/api/anthropic/v1/messages`). The former OpenAI Coding Plan base (`https://api.z.ai/api/coding/paas/v4`) is **not** used by this gateway.

Popular examples:

- `zai/glm-5.1`
- `zai/glm-5-turbo`

Browse models at [Z.ai](https://z.ai).

### 15. [LM Studio](https://lmstudio.ai/)

Start LM Studio's local server and load a model. In the Admin UI, keep or update `LM_STUDIO_BASE_URL`, then set `MODEL` to the model identifier shown by LM Studio, prefixed with `lmstudio/`.

Prefer models with tool-use support for Claude Code workflows.

### 16. [llama.cpp](https://github.com/ggml-org/llama.cpp)

Start `llama-server` with an Anthropic-compatible `/v1/messages` endpoint and enough context for Claude Code requests.

In the Admin UI, keep or update `LLAMACPP_BASE_URL`, then set `MODEL` to the local model slug, prefixed with `llamacpp/`.

For local coding models, context size matters. If llama.cpp returns HTTP 400 for normal Claude Code requests, increase `--ctx-size` and verify the model/server build supports the requested features.

### 17. [Ollama](https://ollama.com/)

Run Ollama and pull a model:

```bash
ollama pull llama3.1
ollama serve
```

In the Admin UI, keep or update `OLLAMA_BASE_URL`, then set `MODEL` to the same tag shown by `ollama list`, prefixed with `ollama/`.

`OLLAMA_BASE_URL` is the Ollama server root; do not append `/v1`. Example model slugs include `ollama/llama3.1` and `ollama/llama3.1:8b`.

### 18. Mix Providers By Model Tier

Each model tier can use a different provider by setting `MODEL_OPUS`, `MODEL_SONNET`, and `MODEL_HAIKU` in the Admin UI. Leave a tier blank to inherit `MODEL`.

For example, you can route Opus to `nvidia_nim/moonshotai/kimi-k2.5`, Sonnet to `open_router/deepseek/deepseek-r1-0528:free`, Haiku to `lmstudio/unsloth/GLM-4.7-Flash-GGUF`, and keep the fallback `MODEL` on `zai/glm-5.1`.

---

## Connect Claude Code

### 1. Claude Code CLI

For terminal use, prefer the installed launcher:

```bash
fcc
```

Keep `fcc-server` running while you work. The Admin UI manages proxy config, restarts the server when runtime settings change, and `fcc` reads the current Admin UI-managed port and auth token every time it starts. It also sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to `190000` for auto-compaction and resumes recent project sessions when enabled.

**Session commands (SEPCC context layer):**

```bash
fcc                  # launch Claude Code (auto-resume latest if configured)
fcc resume           # resume latest compatible session
fcc resume <session-id-or-name>
fcc sessions list    # list all sessions in this project
fcc sessions last    # show most recent session
fcc sessions doctor  # health check session registry
fcc sessions clean   # remove stale entries
fcc sessions rename <session-id> "new-name"
```

**Context commands (SEPCC context hardening):**

```bash
fcc context doctor   # validate and auto-repair context scaffolding
fcc-bootstrap-context            # scaffold a project for long-running work
fcc-bootstrap-context --force    # overwrite existing scaffolding
fcc-bootstrap-context --large-repo  # add Claude Context MCP for large repos
```

`sdc` is an alias for the same terminal facade, so `sdc resume` and `sdc sessions list` are equivalent.

When `FCC_AUTO_RESUME_LAST_SESSION=true`, a plain `fcc` from a project root auto-resumes the latest compatible session, or shows a compact picker when multiple recent sessions exist (`FCC_SESSION_PICKER_ON_AMBIGUOUS`). If the native Claude transcript is available, SEPCC launches with `--resume` for full context. If the transcript is missing but `.fcc/context/handoff.md` exists, SEPCC starts a fresh session with compact handoff + retrieval snippets and links it as a continuation. `FCC_AUTO_RESUME_MAX_AGE_DAYS` and `FCC_AUTO_RESUME_PROJECT_SCOPED` tune auto-resume behavior. `fcc-claude` remains available as a compatibility launcher.

Bootstrapped projects include the agent runtime contract, plugin policy, project subagents, FCC hooks, and Token Savior MCP config. `SessionStart` injects the runtime contract + current handoff into every main chat. Subagents inherit operating rules from project agent definitions, and `SubagentStop` refreshes handoff after delegated work. Run `fcc context doctor` any time to verify the scaffolding is intact.

### 2. VS Code Extension

Open Settings, search for `claude-code.environmentVariables`, choose **Edit in settings.json**, and add:

```json
"claudeCode.environmentVariables": [
  { "name": "ANTHROPIC_BASE_URL", "value": "http://localhost:8082" },
  { "name": "ANTHROPIC_AUTH_TOKEN", "value": "freecc" },
  { "name": "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "value": "1" },
  { "name": "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "190000" }
]
```

Reload the extension. If the extension shows a login screen, choose the Anthropic Console path once; the local proxy still handles model traffic after the environment variables are active.

### 3. JetBrains ACP

Edit the installed Claude ACP config:

- Windows: `C:\Users\%USERNAME%\AppData\Roaming\JetBrains\acp-agents\installed.json`
- Linux/macOS: `~/.jetbrains/acp.json`

Set the environment for `acp.registry.claude-acp`:

```json
"env": {
  "ANTHROPIC_BASE_URL": "http://localhost:8082",
  "ANTHROPIC_AUTH_TOKEN": "freecc",
  "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
  "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "190000"
}
```

Restart the IDE after changing the file.

### 4. Model Picker

<div align="center">
  <img src="assets/cc-model-picker.png" alt="Claude Code model picker showing gateway models" width="700">
</div>

---

## Optional Integrations

For every integration below, change **managed proxy settings** only in the **Admin UI** at `/admin`: edit fields, click **Validate**, then **Apply**. The footer shows where the managed config is stored; this README does not walk through editing that file by hand.

### 1. Discord And Telegram Bots

The bot wrapper runs Claude Code sessions remotely, streams progress, supports reply-based conversation branches, and can stop or clear tasks.

**Discord**

1. Create the bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent**.
3. Invite the bot with read, send, and message history permissions.
4. Copy the bot token and the numeric channel ID (or IDs) where the bot should respond.

**Telegram**

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the bot token.
2. Get your numeric user ID from [@userinfobot](https://t.me/userinfobot) so only you can use the bot.

**Configure in the Admin UI**

1. With `fcc-server` running, open the **Admin UI** URL from the terminal output.
2. In the sidebar, choose **Messaging**.
3. Set **Messaging Platform** to **discord** or **telegram**.
4. For Discord, paste **Discord Bot Token** and **Allowed Discord Channels**. For Telegram, paste **Telegram Bot Token** and **Allowed Telegram User ID**.
5. Set **Allowed Directory** to an absolute path on the machine running the proxy — the workspace root the bot may use.
6. Click **Validate**, then **Apply**. Restart the server if the UI says one is required.

<div align="center">
  <img src="assets/admin-messaging.png" alt="SEPCC Admin UI Messaging view with bot and voice settings" width="700">
</div>

<p align="center"><em>Admin UI → Messaging (platform, bots, and Voice)</em></p>

**Useful commands**

- `/stop` cancels a task; reply to a task message to stop only that branch.
- `/clear` resets sessions; reply to clear one branch.
- `/stats` shows session state.

### 2. Voice Notes

Voice notes work on Discord and Telegram after you extend your SEPCC Unlimited Cloud Code install with the matching optional extras.

**macOS/Linux:**

```bash
# NVIDIA NIM transcription (Riva gRPC)
curl -fsSL "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.sh?raw=1" | sh -s -- --voice-nim

# Local Whisper (CPU or CUDA)
curl -fsSL "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.sh?raw=1" | sh -s -- --voice-local

# Both backends
curl -fsSL "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.sh?raw=1" | sh -s -- --voice-all

# Local Whisper with CUDA
curl -fsSL "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.sh?raw=1" | sh -s -- --voice-local --torch-backend cu130
```

**Windows PowerShell:**

```powershell
# NVIDIA NIM transcription (Riva gRPC)
& ([scriptblock]::Create((irm "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.ps1?raw=1"))) -VoiceNim

# Local Whisper (CPU or CUDA)
& ([scriptblock]::Create((irm "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.ps1?raw=1"))) -VoiceLocal

# Both backends
& ([scriptblock]::Create((irm "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.ps1?raw=1"))) -VoiceAll

# Local Whisper with CUDA
& ([scriptblock]::Create((irm "https://github.com/sepehrbayat/SEPCC/blob/main/scripts/install.ps1?raw=1"))) -VoiceLocal -TorchBackend cu130
```

Restart `fcc-server` after reinstalling.

In the **Admin UI**, open **Messaging** and scroll to **Voice**. Turn on **Voice Notes**, choose **Whisper Device** (`cpu`, `cuda`, or `nvidia_nim`), set **Whisper Model**, and enter **Hugging Face Token** when your setup needs it. For **nvidia_nim** transcription, install the `voice` extra and set **NVIDIA NIM API Key** on the **Providers** view. The screenshot above shows the **Voice** block in the same view.

---

## How It Works

<div align="center">
  <img src="assets/how-it-works.svg" alt="SEPCC Unlimited Cloud Code request flow architecture" width="900">
</div>

Diagram source: [`assets/how-it-works.mmd`](assets/how-it-works.mmd).

Architecture layers (bottom to top):

- **Provider Layer** (`providers/`) — 17 backends with per-model routing. Each provider extends `AnthropicMessagesTransport` or `OpenAIChatTransport`. The registry maps provider IDs to transport factories with dynamic validation.
- **Core Protocol Layer** (`core/anthropic/`) — SSE streaming, thinking/reasoning normalization, tool-use translation, token counting, content conversion. Provider-agnostic Anthropic protocol utilities shared across all transports.
- **Context Layer** (`core/context/`) — **SEPCC's key addition above FCC.** Handoff persistence, SQLite sidecar for raw outputs, retrieval pipeline, summarization, and deterministic storage. Ensures session state survives crashes and restarts.
- **API Layer** (`api/`) — FastAPI routes (`/v1/messages`, `/v1/messages/count_tokens`, `/v1/models`), model routing, request optimization handlers, Admin UI with session and context management views.
- **CLI Layer** (`cli/`) — `fcc` launcher, session registry, resume logic, Claude process manager. Bootstrapper (`bootstrap_context.py`) and doctor (`context_doctor.py`) for project scaffolding.
- **Hook Scripts** (`scripts/hooks/`) — Six lifecycle hooks that inject context, persist handoff, and handle compaction. Each hook has a single owner enforced by the plugin policy.
- **Templates** (`templates/project/`) — Complete project scaffold: CLAUDE.md pair, agent definitions, skills, slash commands, context files, MCP config, plugin policy, hook settings.

Request flow: Claude Code CLI → FastAPI routes → model routing → provider transport → upstream API. `SessionStart` hook injects the runtime contract + handoff at session open. `SubagentStop` hook writes updated handoff after subagent delegation. `PreCompact` hook preserves critical context before context window compaction.

---

## Development

### 1. Project Structure

```text
SEPCC/
├── server.py                 # ASGI entry point
├── api/                      # FastAPI routes, service layer, routing, optimizations
│   └── admin_static/         # Admin UI frontend (extended for SEPCC)
├── core/
│   ├── anthropic/            # Shared Anthropic protocol helpers, SSE utilities
│   └── context/              # ★ SEPCC ADDITION: handoff, retrieval, SQLite store, summarizer
├── providers/                # 17 provider transports, registry, rate limiting (Gemini fixed)
├── messaging/                # Discord/Telegram adapters, sessions, voice
├── cli/                      # ★ SEPCC EXTENDED: session registry, resume, bootstrap, doctor
├── config/                   # Settings (extended with system proxy), provider catalog, logging
├── scripts/
│   ├── hooks/                # ★ SEPCC ADDITION: SessionStart, SubagentStop, PreCompact, etc.
│   └── windows/              # ★ SEPCC ADDITION: Windows launcher helpers
├── templates/project/        # ★ SEPCC ADDITION: full project bootstrap (50+ files)
├── docs/                     # ★ SEPCC ADDITION: context hardening, agent memory, tooling audit
└── tests/                    # Unit, contract, smoke tests (extended for SEPCC modules)
```

### 2. Run From Source

Use this path if you are developing or want to run directly from a checkout:

```bash
git clone https://github.com/sepehrbayat/SEPCC.git
cd SEPCC
uv run uvicorn server:app --host 0.0.0.0 --port 8082
```

### 3. Commands

```bash
uv run ruff format
uv run ruff check
uv run pytest
```

Run them in that order before pushing. CI enforces the same checks.

### 4. Package Scripts

`pyproject.toml` installs:

- `fcc`: primary terminal Claude Code launcher with project-local session resume commands.
- `sdc`: compatibility alias for `fcc`.
- `fcc-server`: starts the proxy with configured host and port.
- `fcc-init`: optional advanced scaffold for `~/.fcc/.env`; prefer the **Admin UI** for normal configuration.
- `fcc-claude`: compatibility launcher for Claude Code with the configured local proxy URL, auth token, model discovery flag, package-manager auto-update opt-in, and a 190k `CLAUDE_CODE_AUTO_COMPACT_WINDOW` for auto-compaction.
- `free-claude-code`: compatibility alias for `fcc-server`.

### 5. Extending

- Add OpenAI-compatible providers by extending `OpenAIChatTransport`.
- Add Anthropic Messages providers by extending `AnthropicMessagesTransport`.
- Register provider metadata in `config.provider_catalog` and factory wiring in `providers.registry`.
- Add messaging platforms by implementing the `MessagingPlatform` interface in `messaging/`.

---

## Contributing

- [`.env.example`](.env.example) lists env key names as a read-only reference for contributors; use the **Admin UI** to change managed proxy settings.
- Report bugs and feature requests in [Issues](https://github.com/sepehrbayat/SEPCC/issues).
- Keep changes small and covered by focused tests.
- Do not open Docker integration PRs.
- Do not open README change PRs — just open an issue for it.
- Run the full check sequence before opening a pull request.
- The syntax `except X, Y` is brought back in Python 3.14 final version (not in 3.14 alpha). Keep in mind before opening PRs.

---

## License and Attributions

### Primary License

SEPCC — Unlimited Cloud Code is licensed under the **MIT License**.

```
MIT License

Copyright (c) 2026 Ali Khokhar
Copyright (c) 2026 Sepehr Bayat

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

See [LICENSE](LICENSE) for the full text.

### Third-Party Dependency Licenses

SEPCC Unlimited Cloud Code builds on these open-source projects. Their licenses are included here as required by each respective license:

| Package | License | Usage |
|---------|---------|-------|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | Web framework and API routing |
| [Uvicorn](https://github.com/encode/uvicorn) | BSD 3-Clause | ASGI server |
| [httpx](https://github.com/encode/httpx) | BSD 3-Clause | HTTP client for provider backends |
| [Pydantic](https://github.com/pydantic/pydantic) | MIT | Data validation and settings |
| [Pydantic Settings](https://github.com/pydantic/pydantic-settings) | MIT | Environment-based settings management |
| [tiktoken](https://github.com/openai/tiktoken) | MIT | Token counting for Anthropic API |
| [OpenAI Python](https://github.com/openai/openai-python) | Apache 2.0 | OpenAI-compatible provider adapters |
| [aiohttp](https://github.com/aio-libs/aiohttp) | Apache 2.0 | Async HTTP server for streaming |
| [Loguru](https://github.com/Delgan/loguru) | MIT | Structured logging |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | BSD 3-Clause | Environment variable loading |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py) | MIT | Markdown rendering |
| [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) | LGPLv3 | Telegram bot integration |
| [discord.py](https://github.com/Rapptz/discord.py) | MIT | Discord bot integration |

#### Optional Voice Dependencies

| Package | License | Usage |
|---------|---------|-------|
| [gRPC](https://github.com/grpc/grpc) | Apache 2.0 | Riva client transport for NVIDIA NIM voice |
| [nvidia-riva-client](https://github.com/nvidia-riva) | NVIDIA Proprietary | NVIDIA NIM voice transcription client |
| [PyTorch](https://github.com/pytorch/pytorch) | BSD 3-Clause | Local Whisper model inference |
| [Transformers](https://github.com/huggingface/transformers) | Apache 2.0 | Hugging Face model pipeline |
| [Accelerate](https://github.com/huggingface/accelerate) | Apache 2.0 | Distributed inference optimization |
| [librosa](https://github.com/librosa/librosa) | ISC | Audio processing and analysis |

#### Development Dependencies

| Package | License | Usage |
|---------|---------|-------|
| [pytest](https://github.com/pytest-dev/pytest) | MIT | Test framework |
| [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | Apache 2.0 | Async test support |
| [pytest-cov](https://github.com/pytest-dev/pytest-cov) | MIT | Test coverage reporting |
| [pytest-xdist](https://github.com/pytest-dev/pytest-xdist) | MIT | Parallel test execution |
| [Ruff](https://github.com/astral-sh/ruff) | MIT | Linting and formatting |
| [Ty](https://github.com/paulz/ty) | MIT | Static type checking |

### Anthropic / Claude Code

SEPCC is a proxy layer and is **not** affiliated with, endorsed by, or associated with Anthropic PBC. Claude Code is a product of Anthropic PBC. The Anthropic API, Messages API, and Claude Code client protocol are governed by Anthropic's own terms of service and commercial terms.

### Upstream Attribution

This project is a fork of [Free Claude Code](https://github.com/Alishahryar1/free-claude-code) by Ali Khokhar, originally created as a middleware proxy between Claude Code CLI and NVIDIA NIM. We gratefully acknowledge the original author's work in establishing this provider-agnostic proxy architecture.

---

## SEO Keywords

**Unlimited Cloud Code**, **SEPCC**, **free Claude Code**, **Claude Code alternative**, **unlimited AI coding**, **free AI coding assistant**, **Anthropic API proxy**, **Claude Code without limits**, **AI pair programming free**, **unlimited Claude Code proxy**, **free coding AI unlimited**, **Claude Code free tier alternative**, **open source Claude Code proxy**, **multi-provider AI coding**, **SEPCC unlimited cloud coding**.

---

<div align="center">

**SEPCC — Unlimited Cloud Code** · Free AI coding, unlimited.

[GitHub](https://github.com/sepehrbayat/SEPCC) · [Issues](https://github.com/sepehrbayat/SEPCC/issues) · [Upstream](https://github.com/Alishahryar1/free-claude-code)

</div>
