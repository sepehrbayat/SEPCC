<div align="center">

# SEPCC — Unlimited Claude Code, with context that survives

> **v2.3.0** — Semantic Enrichment · Quality Gates · AI-Assisted Dev Guardrails · Prompt Observability · Recovery Layer · 1,916 Tests

A free and open-source proxy that gives you **unlimited Claude Code** access by routing API calls through any provider you choose. Built on [Free Claude Code](https://github.com/Alishahryar1/free-claude-code), SEPCC adds sessions you can actually resume, a context handoff that survives crashes, visible auto prompt enhancement, an agent debugger and fixer pipeline, a knowledge graph for codebase-wide structural understanding, and a one-command project bootstrapper — everything you need for real, multi-session work with **unlimited Claude Code** usage, no Anthropic rate limits, no per-token bills.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json&style=for-the-badge)](https://github.com/astral-sh/uv)

</div>

---

## Contents

- [The short version](#the-short-version)
- [What SEPCC adds](#what-sepcc-adds)
- [Quality Gates](#quality-gates)
- [Quick Start](#quick-start)
  - [1. Install](#1-install)
  - [2. Start the proxy](#2-start-the-proxy)
  - [3. Configure a provider](#3-configure-a-provider)
  - [4. Bootstrap your project](#4-bootstrap-your-project-context-features)
  - [5. Launch Claude Code](#5-launch-claude-code)
- [Providers](#providers)
- [Connect your editor](#connect-your-editor)
- [Discord and Telegram bots](#discord-and-telegram-bots)
- [Agent Debugger](#agent-debugger)
- [Knowledge Graph](#knowledge-graph-graphify)
- [Auto prompt enhancement](#auto-prompt-enhancement)
- [Your first prompt](#your-first-prompt)
- [How it works](#how-it-works)
- [V2Ray system proxy (port 10808)](#v2ray-system-proxy-port-10808)
- [Windows Desktop Shortcut](#windows-desktop-shortcut)
  - [Creating the shortcut](#creating-the-shortcut)
  - [Zero-config first launch](#zero-config-first-launch-auto-dependency-installation)
  - [First-run setup](#first-run-setup)
  - [How it works](#how-it-works-1)
  - [Empty folder? No projects yet?](#empty-folder-no-projects-yet)
  - [Changing the projects root later](#changing-the-projects-root-later)
  - [How this differs on Linux and macOS](#how-this-differs-on-linux-and-macos)
  - [Opting out](#opting-out)
- [Development](#development)
- [Contributing](#contributing)
- [License and Attributions](#license-and-attributions)

---

## The short version

Claude Code is the best AI coding assistant out there. The catch? Anthropic's pricing and rate limits. If you code all day, the costs add up fast.

SEPCC is a **free Claude Code alternative** that sits between Claude Code and the API layer. Claude Code thinks it's talking to Anthropic — but you're routing through DeepSeek, Gemini, OpenRouter, a local Llama, whatever you want. The result is **unlimited Claude Code** sessions. No rate caps. No per-message billing. You own the backend, you set the rules.

The proxy part existed in FCC already. SEPCC adds a full context-hardening layer on top: sessions you can pick back up after a crash, a handoff file that keeps your place between restarts, visible prompt refinement before work begins, and a bootstrapper that scaffolds an entire project for long-running **unlimited Claude Code** work in one command. If you're looking for a **Claude Code without limits** setup, this is it.

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

### Visible auto prompt enhancement

SEPCC can refine ordinary user prompts before the model starts working. `AUTO_PROMPT_ENHANCER=true` is enabled by default in the bootstrapped hook environment, and the enhancer uses the same proxy URL you already configured for Claude Code. The default enhancer model is `claude-haiku-4-5-20251001`, configurable with `PROMPT_ENHANCER_MODEL`.

The behavior is intentionally visible. In Claude Code hook launches, `UserPromptSubmit` cannot replace the text you typed, so SEPCC injects the enhanced prompt as additional context and prints a system message showing the refined version that will guide the turn. In Discord and Telegram sessions, SEPCC can rewrite the prompt before launching the CLI and emits a `prompt_enhancement` status event when it changes anything. Slash commands such as `/handoff`, `/recall`, `/verify-context`, and `/enhance` are never auto-rewritten.

If the enhancer cannot run because the proxy URL is missing, the upstream provider returns invalid JSON, or the request times out, SEPCC fails open: your original prompt is used and the visible status tells you why nothing changed. That makes enhancement auditable instead of silent.

### One command to bootstrap a project

```bash
fcc-bootstrap-context
```

Drops 50+ files into the target project:

- `CLAUDE.md` and `CLAUDE.local.md` — project rules and local machine facts
- `.claude/agents/` — four project agents (code reviewer, context auditor, product logic reviewer, researcher)
- `.claude/skills/` — three Claude Code skills (context-recall, handoff-writer, route-task)
- `.claude/commands/` — slash commands: `handoff`, `recall`, `verify-context`
- `.codex/agents/` and `.agents/skills/` — matching Codex project agents and local skills
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
- knowledge graph health (missing, stale, >50MB warning)

### Agent Debugger — automatic post-task review and repair

SEPCC watches subagent output. When you finish one task and start another, it automatically analyzes the completed work and dispatches a fixer agent to repair any issues found — all in the background while you keep working.

```text
You: "add rate limiting to the API"

┌──────────────────────────────────────────────────────┐
│  FOREGROUND: Agent works on your new task             │
│                                                       │
│  BACKGROUND CHAIN:                                     │
│  ┌─────────────────────────────────────────┐           │
│  │ fcc-agent-debugger                       │           │
│  │ Analyzes correctness, completeness,      │           │
│  │ and process compliance of task 1         │           │
│  │ → Produces structured DebugReport        │           │
│  └──────────────┬──────────────────────────┘           │
│                 │                                      │
│  ┌──────────────▼──────────────────────────┐           │
│  │ fcc-agent-fixer                          │           │
│  │ Fixes bugs (git worktree isolation)      │           │
│  │ Runs tests after each batch              │           │
│  │ Commits fixes, writes FixReport          │           │
│  └──────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────┘
```

The debugger checks:
- **Correctness** — bugs, logic errors, type mismatches, race conditions, test failures
- **Completeness** — missing files, half-implemented features, TODO markers, stubs
- **Process** — did the agent follow CLAUDE.md rules, run tests, document decisions?

The fixer runs in a git worktree so it never conflicts with your active work. The pipeline is completely automatic — detected by the `UserPromptSubmit` hook when your next prompt describes a different task. No configuration needed.

### Knowledge Graph (Graphify) — v2.2

SEPCC builds a structural map of your entire codebase — 6,993 entities, 16,247 relations, 282 communities — using the [Graphify](https://github.com/safishamsi/graphify) knowledge graph engine (MIT-licensed, 58k★, 33 languages via tree-sitter). Agents get pre-computed codebase understanding without re-reading the entire codebase every session.

```bash
fcc-bootstrap-context --install-graphify
```

Once installed, every session starts with a compact structural summary:

```
## Project Structure
Primary domains:
  • Community 17 (67 nodes) — API service layer
  • Community 5 (83 nodes) — Provider factory

Key abstractions:
  • Settings (god, 1.00 centrality, 227 connections)
  • MessagesRequest (god, 0.54 centrality, 111 connections)
```

When you mention entities in a prompt, the graph injects their neighborhood:

```
[Graph Context]
Matched entities:
  • Settings (config/settings.py:L110), 227 connections
    Community: 203
  • ModelRouter (api/model_router.py:L37), 52 connections
    Community: 17
```

**Nine MCP tools** available during sessions:

| Tool | Description |
|---|---|
| `fcc_graph_search` | Full-text search with progressive token-level recall (FTS5 → LIKE → token-AND → token-OR) |
| `fcc_graph_neighbors` | N-hop neighbourhood — dependencies, dependents, community peers |
| `fcc_graph_impact` | Transitive closure with relation-type filtering and test-file exclusion |
| `fcc_graph_explain` | Human-readable entity summary — in/out-degree, production vs test dependents |
| `fcc_graph_path` | Shortest dependency path with edge-type filtering and test exclusion |
| `fcc_graph_god_nodes` | Most-depended-on entities ranked by **in-degree** centrality (what depends on me) |
| `fcc_graph_community` | Community membership and peer listing |
| `fcc_graph_entity` | Full entity detail by ID |
| `fcc_graph_stats` | Graph summary + commit staleness detection (`needs_update: true/false`) |

**v2.2 improvements:** directional centrality based on in-degree (not total degree), test-file filtering across all tools (`exclude_tests: true`), builtin/external entity filtering (`exclude_external: true`), rationale/docstring entity filtering from impact results, MCP server connection caching (zero leak), JSON-RPC compliance (-32602/-32700), progressive search fallbacks for naming convention mismatches (snake_case → PascalCase), graphify 0.8.x format support.

**Reliability:** 308 dedicated graph tests · 99.0% entity line-number accuracy · 0 builtins in god nodes · 0 rationale entities in impact results · graph health checks in doctor (missing, stale, oversized, multigraph edge-collapse risk, git hook status, token savings benchmark).

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
| Auto prompt enhancement | no | **yes — visible, fail-open, configurable model** |
| Project bootstrapper | no | **yes — one command, 50+ files** |
| Context doctor | no | **yes — validation + auto-repair** |
| Agent runtime contract | no | **yes — hook-injected every session** |
| Project subagent definitions | no | **4 specialized agents** |
| Claude Code project skills | no | **3 project skills** |
| Codex project scaffold | no | **agents, skills, config, and hooks included** |
| Slash commands | no | **handoff, recall, verify-context** |
| Gemini thinking controls | bugged | **fixed** |
| System proxy support | no | **yes** |
| Windows launcher | basic | **self-heals duplicate local server ports** |
| Agent debugger & fixer | no | **yes — automatic post-task review and repair** |
| Knowledge graph integration | no | **yes — Graphify, SQLite + FTS5, 9 MCP tools, directional centrality, test-filtered impact** |
| Graph-informed routing | no | **yes — god nodes → Opus, unknown entities → Haiku** |
| 30+ verified bug fixes | no | **yes — adversarial audit, 42 edge-case tests** |

---

## Quality Gates

**Every SEPCC session enforces AI-assisted development guardrails.** Before any task, the agent runtime requires reading `.fcc/context/quality-gates.md` — a binding quality contract covering:

- **Pre-task gate**: scope, boundaries, outcome, failure modes, verification — must be answered before starting
- **Product-centered rule**: every change must support a real user story
- **Controlled confidence**: inspect context, preserve conventions, document tradeoffs
- **Red flags**: multiple warning signs of poor AI-assisted outcomes
- **Architecture, security, and testing gates**: specific anti-patterns to avoid
- **Definition of done**: scope respected, tests pass, TODOs documented
- **Golden rules**: don't trust polished UI without clear journey, don't trust tests that only cover happy paths, don't add features without purpose

The one-line rule: *"A project becomes poorly AI-assisted when its appearance moves faster than understanding, implementation moves faster than review, and claims move faster than reality."*

The quality gates are injected into every SessionStart alongside CLAUDE.md and the handoff. They're copied automatically for new projects via `fcc-bootstrap-context`.

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

Prompt enhancement also goes through this same local proxy. The default enhancement model is `claude-haiku-4-5-20251001`; change `PROMPT_ENHANCER_MODEL` in your environment if you want the enhancer to use a different model.

### 4. Bootstrap your project (context features)

```bash
fcc-bootstrap-context
```

Run this once in your project root. It drops 50+ scaffolding files: hook scripts, agent definitions, slash commands, the handoff system, and `.claude/settings.json` with all five lifecycle hooks wired up.

**Without this step, the proxy still works** — routing, session tracking, auto-resume, everything on the network layer. What you won't get is the context layer: the handoff that survives crashes, visible prompt enhancement in Claude Code hooks, the agent runtime contract injected into every session, the SubagentStop hook that keeps state after subagents run, the project skills and slash commands.

Run `fcc-bootstrap-context` again later with `--force` to refresh the scaffold, or `fcc context doctor` to check what's in place.

### 5. Launch Claude Code

```bash
fcc
```

`fcc` sets the environment variables Claude Code needs, runs a quick update check, then launches the real `claude` command. Keep `fcc-server` running in another terminal.

When the context scaffold is installed, `fcc` and `fcc-claude` also expose the package root and prompt enhancer settings to the hook scripts. That means ordinary prompts are refined automatically; you only need `/enhance` when you explicitly want to run manual inline enhancement.

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
{ "name": "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "value": "1000000" },
{ "name": "AUTO_PROMPT_ENHANCER", "value": "true" },
{ "name": "PROMPT_ENHANCER_MODEL", "value": "claude-haiku-4-5-20251001" },
{ "name": "PROMPT_ENHANCER_TIMEOUT", "value": "12" }
```

If VS Code is launching Claude Code outside `fcc` or `fcc-claude`, also set `FCC_PACKAGE_ROOT` to the SEPCC checkout path used to install the hook scripts. The launcher sets it automatically; direct editor launches need it so prompt enhancement, routing hints, and handoff helpers all import the same shared code.

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

## Agent Debugger

SEPCC includes an automatic agent debugger pipeline that monitors subagent output, detects when you move from one task to the next, and dispatches a debugger→fixer chain to analyze and repair the previous task's work — all without blocking your forward progress.

### How it works

When the `UserPromptSubmit` hook detects that your next prompt describes a fundamentally different task from what you were just working on (keyword overlap < 40%), it captures the previous task's metadata — transcript path, changed files, git commit range — and injects a dispatch instruction into the agent's context. The debugger and fixer run as background subagents while you continue working:

1. **fcc-agent-debugger** — reads the previous task's full transcript, runs `git diff` on changed files, checks correctness (bugs, logic errors, type mismatches, race conditions), completeness (missing features, TODO markers, stubs, coverage gaps), and process compliance (did the agent follow CLAUDE.md rules, run tests, document decisions?). Produces a structured `DebugReport` to `.fcc/debugger/reports/`.

2. **fcc-agent-fixer** — reads the DebugReport, creates a git worktree for isolation, fixes findings in priority order (correctness → completeness → process), runs tests after each fix batch, commits results, and writes a `FixReport` to `.fcc/debugger/fixes/`. The worktree ensures zero conflict with your active work.

The existing `SubagentStop` hook feeds both agents' results into `.fcc/context/handoff.md` automatically — future sessions see what was found and fixed.

### Transition detection

The trigger compares your new prompt's keywords against the previous task title. Continuations and clarifications pass through without interruption. Genuine task switches fire the pipeline. Cancellation terms ("skip debug", "cancel debug", "never mind") flush the pending queue.

### File layout

```
.fcc/debugger/
├── pending/           # Tasks awaiting analysis
├── reports/           # DebugReport output
├── fixes/             # FixReport output
├── failed/            # Unprocessable reports
├── skipped/           # User-cancelled tasks
└── lock               # Prevents concurrent fixer execution
```

### Error handling

- No previous task → silent skip
- Debugger subagent fails → Fixer detects missing report, writes failure notice to handoff
- Rapid task switching → Queue in `pending/`, processed sequentially
- Fixer and main agent touch same files → Git worktree isolation prevents any conflict
- No test suite → All fixes flagged as `verified: false`

---

## Knowledge Graph (Graphify)

SEPCC integrates [Graphify](https://github.com/safishamsi/graphify) (MIT-licensed, 58k★) as a knowledge graph layer. Graphify parses code (33 languages via tree-sitter AST) and unstructured content into a structured graph with entities, relations, communities, and intent annotations. SEPCC wraps it in a thin FCC-native layer (`core/graph/`) that loads the graph into SQLite with FTS5 full-text search, provides graph traversal query tools, and injects structural summaries into sessions.

### Bootstrap

```bash
fcc-bootstrap-context --install-graphify
```

This installs `graphifyy[leiden]` (Leiden community detection), builds the initial graph to `.fcc/graph/graph.json`, registers the `fcc-graph` MCP server in `.mcp.json`, and installs a git hook that auto-rebuilds the graph on every commit (AST-only, no API cost).

### How agents use it

| Touchpoint | What happens |
|---|---|
| **Session start** | Community overview + god nodes (top 8, test-filtered, usage-site-excluded) + changed files from git diff |
| **Every prompt** | Entity matches from graph injected with docstring excerpts + graph-driven multi-entity routing hints |
| **During work** | 10 MCP tools: search (progressive FTS5→LIKE→token-AND→token-OR), neighbors, impact (relation-filtered, test-excluded), explain (in/out, prod/test split), path (edge-filtered, test-excluded), god nodes (in-degree ranked, builtin+test+usage-site filtered), community, entity, stats (staleness), **inspect** (signature+docstring+callers) |
| **Pre-compaction** | Adaptive, conversation-aware context — extracts identifiers from transcript, injects only conversation-relevant entities and their communities |
| **Handoff** | `## Structural Context` section with active communities, modified god nodes, graph version |
| **Context doctor** | 6 graph health checks: missing, stale (commit mismatch), oversized (>50MB), multigraph edge-collapse risk, git hook installed, token savings benchmark |
| **Routing** | `graph_rules` in `.fcc/router.yml` + aggregate centrality scoring: multi-entity matching in `_graph_routing_hint()` routes to Opus when sum_centrality > 1.0 or wide cross-community |

### Centrality and Direction

SEPCC uses **directional centrality** — computed from in-degree (how many things depend on this entity), not total degree. Multiple filters eliminate false positives:

- `exclude_external: true` filters Python builtins (`str`, `int`, `Exception`) from god node results
- `exclude_test_only: true` (default) removes entities whose dependents are 100% test files (e.g., `SmokeConfig` with 128 test-only dependents)
- `is_usage_site()` distinguishes definition sites from import references — `Settings` in `api/model_router.py` is an import, not the Settings class

### Semantic Enrichment (v2.3)

`core/graph/enrich.py` populates docstrings and signatures directly from source code using AST parsing — no LLM needed. After every `load_graph()`, enrichment extracts:

- Function/class signatures (type-annotated)
- Docstrings (first sentence)
- Base classes and decorators
- Entity kind (function, async function, class, property)

4,600+ entities enriched (90% of code entities). `inspect(entity_id)` returns a complete entity card — signature, docstring, callers, dependencies, community peers — without opening the source file. `fcc_graph_inspect` is the 10th MCP tool.

### Entity-Level Diff

`query.diff("last_build")` returns added, removed, and modified entities between graph builds. The entity snapshot is stored in `schema_meta` on every `load_graph()`. Supports git range diff for file-level change detection.

### Architecture

```
graphify . --output .fcc/graph/     ← extraction (once, on bootstrap or commit)
       │
       ▼
.fcc/graph/graph.json               ← source of truth
       │
       ▼
core/graph/loader.py                ← validates, normalizes, ingests, centrality
       │
       ▼
core/graph/enrich.py                ← AST parses source files, extracts docstrings + signatures
       │
       ▼
core/graph/store.py                 ← SQLite + FTS5 + in_degree/out_degree columns
       │
       ▼
core/graph/query.py                 ← search, neighbors, impact, path, explain, inspect, diff
       │
       ▼
core/graph/context.py               ← builds injection strings for hooks
       │
       ▼
core/hanser.py                      ← graph-native complexity scoring + prompt enrichment
       │
       ▼
scripts/hooks/session_start.py      ← structural summary + changed_files at session start
scripts/hooks/user_prompt_submit.py ← entity matches + graph-driven routing hints
scripts/hooks/precompact.py         ← adaptive conversation-aware graph context
scripts/graph/mcp_server.py         ← 10 MCP tools (incl. fcc_graph_inspect)
```

### Graph-informed model routing

`.fcc/router.yml` includes `graph_rules` that the `route-task` skill evaluates:

```yaml
graph_rules:
  - match: "graph:centrality > 0.8"
    tier: opus
    reason: "Editing a god node — broad transitive effects"
  - match: "graph:community:size > 20"
    tier: opus
    reason: "Large architectural domain warrants stronger reasoning"
  - match: "graph:impact:files > 10"
    tier: opus
    reason: "Broad change requires careful planning across many files"
  - match: "graph:unknown"
    tier: haiku
    reason: "No matching entity — exploratory task, start with fast model"
```

Beyond single-entity rules, **aggregate centrality scoring** (`_graph_routing_hint()`) scans all entities matched from the prompt, sums centrality, counts community span, and escalates to Opus even when no individual entity exceeds 0.8 — a prompt touching 5 medium-impact entities across 7 communities triggers Opus.

### Graph System Observability

- **`fcc-prompts-stats`** — aggregates prompt enhancement metrics from `.fcc/prompt_stats.jsonl` and server.log TRACE events: status breakdown, avg char deltas, time range, effectiveness verdict
- **Entity-level diff** — `fcc_graph_diff` detects added/removed/modified entities between builds, supporting file-level change detection via git range diff
- **Entity snapshot** — stored in `schema_meta` on every `load_graph()`, enabling delta-based change awareness
- **Hanser complexity engine** — `core/hanser.py` provides graph-native complexity scoring (0.0–1.0) and model tier suggestion without LLM calls

### Error handling

- No graph exists → all injections return empty (graph is an enhancement, not a requirement)
- Graph corrupted → MCP returns distinct "corrupted" vs "missing" diagnostic
- Graph stale vs git HEAD → `fcc_graph_stats.needs_update` flag; doctor warns
- `graph.json` malformed → `GraphLoadError` raised; hooks catch and surface gracefully
- Entity not found → queries return `None` or empty; MCP returns structured `{error: "not_found"}`
- FTS5 unavailable → search falls back to `LIKE` on name+docstring, then token-level AND/OR
- Missing required params → JSON-RPC -32602 (Invalid params), not generic -32603
- Parse errors → JSON-RPC -32700 response, not silent skip

### Provider Recovery Layer (v2.3)

`providers/recovery.py` fills the gap between error definitions and ad-hoc retry logic in provider clients. The `ProviderRecovery` class classifies errors as `TRANSIENT` (retry), `CIRCUIT` (retry with backoff), or `FATAL` (never retry), then wraps any async operation with retry + exponential backoff + jitter. Fatal errors (auth, validation) are never retried. ConnectError gets one retry with 500ms delay — the proxy may still be starting when the hook fires.

---

## Auto prompt enhancement

Auto enhancement is designed for the exact moment where a vague prompt would otherwise waste a turn. When `AUTO_PROMPT_ENHANCER=true`, SEPCC sends the user prompt plus lightweight project context through the configured proxy, asks the enhancer model to make it more actionable, then feeds that refined prompt back into the active workflow.

The default settings are:

```bash
AUTO_PROMPT_ENHANCER=true
PROMPT_ENHANCER_MODEL=claude-haiku-4-5-20251001
PROMPT_ENHANCER_TIMEOUT=12
PROMPT_ENHANCER_MAX_OUTPUT_CHARS=2000
```

What you should see:

- In Claude Code launched through `fcc` or `fcc-claude`, a visible system message appears when the prompt is enhanced. Claude Code hooks do not let external tools replace the original submitted text, so SEPCC injects the enhanced prompt as additional context and shows you the refined version.
- In Discord and Telegram sessions, SEPCC rewrites the prompt before launching Claude Code and emits a prompt-enhancement status update so you can tell that the rewritten prompt is the one being used.
- If no proxy URL is available, the provider returns malformed JSON, or the enhancer times out, SEPCC reports that failure and continues with your original prompt.

Manual enhancement still exists:

```text
/enhance tighten this into a precise implementation prompt
```

`/enhance` returns the refined prompt inline so you can inspect or edit it before sending another message. Auto enhancement skips slash commands by design, so command protocols remain deterministic.

If the enhancer cannot reach the proxy (connection refused, still starting), it retries once with a 500ms delay. All errors now surface the actual exception type and message in the visible status output (e.g., `ConnectError: Connection refused`) instead of a generic "error" — making enhancement failures auditable and debuggable. Fatal errors (auth, validation) are never retried.

When you connect an editor directly instead of using `fcc`, make sure the editor process has the same proxy and enhancer environment variables. For source checkouts, `FCC_PACKAGE_ROOT` should point at the SEPCC repo root so hook scripts can import shared code instead of falling back to a degraded mode.

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
- `UserPromptSubmit` — names active sessions, handles handoff recall, injects routing hints, and surfaces visible prompt enhancement
- `Stop` — final persistence

Prompt enhancement is just another Anthropic-compatible request through `/v1/messages`. The enhancer accepts both streaming SSE and non-streaming JSON responses, extracts the refined text, and falls back to the original prompt with a visible reason when the proxy URL, upstream response, or timeout prevents enhancement. Compacting logic also keeps unmatched code fences from swallowing all later context, so the handoff stays useful even when a transcript contains broken Markdown.

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

On Windows, SEPCC comes with a desktop shortcut launcher that starts the proxy server and drops you directly into a project — no terminal commands needed. Double-click, pick a project, start coding.

### Creating the shortcut

The repo doesn't include a `.lnk` file (they don't track well in git). Instead, after cloning, double-click this file in Explorer:

```
scripts\windows\create-desktop-shortcut.bat
```

This drops an `SEPCC.lnk` on your desktop pointing at `launch-fcc-claude.cmd`. The script resolves paths from its own location, so it works wherever you cloned the repo.

If you move the repo later, just re-run the `.bat` — it overwrites the old shortcut with updated paths.

### Zero-config first launch (auto dependency installation)

The very first time you double-click the shortcut, **you don't need to have anything pre-installed** except a shell. The launcher checks everything and installs what's missing:

1. **`uv` not found?** The launcher automatically runs `scripts/install.ps1` which downloads `uv`, Python 3.14, and all SEPCC dependencies. This only happens once.
2. **Virtual environment missing?** It runs `uv python install 3.14.0` and `uv venv` to create `.venv314`.
3. **SEPCC binaries missing?** It runs `uv sync` to compile and install `fcc-server`, `fcc-claude`, and `fcc-bootstrap-context`.

After the first launch, everything is cached. Subsequent launches go straight to the proxy and project picker — no install step.

If the launcher can't download anything (no internet, firewall, restricted network), it prints:

```
Dependency installation failed.

It looks like a network connectivity issue. If you are
behind a firewall or internet restriction, enable your
proxy and try again:

  Common proxy ports:
    V2Ray / V2RayN  →  socks5://127.0.0.1:10808
    Clash / Verge   →  http://127.0.0.1:7890
    Shadowsocks     →  socks5://127.0.0.1:1080
    V2Ray HTTP      →  http://127.0.0.1:10809
    Generic HTTP    →  port 3128, 8118, or 8888

After enabling your proxy, set it in the terminal:

  set HTTP_PROXY=http://127.0.0.1:10809
  set HTTPS_PROXY=http://127.0.0.1:10809

Then run this shortcut again.
```

The launcher recognizes network errors (connection refused, timeout, DNS failure, TLS errors) and surfaces them with the right proxy ports. It checks the same well-known local proxy ports that SEPCC's `AUTO_DETECT_SYSTEM_PROXY` uses — the same mechanism documented in the [V2Ray section](#v2ray-system-proxy-port-10808) above.

### First-run setup

The very first time you launch the shortcut, a setup wizard appears in the terminal:

```
============================================================
  SEPCC — First-Time Setup
============================================================

Where should your projects live?

  Suggested: C:\Users\<you>\Projects

  [Enter]  Accept the suggestion above
  [    B]  Browse for a different folder
  [    0]  Type a path manually
```

Press Enter to accept `%USERPROFILE%\Projects`. The wizard then asks:

```
Create 'C:\Users\<you>\Projects' as your projects folder? [Y/n]
```

Confirm, and the path is saved to `%APPDATA%\SEPCC\projects-root.txt`. You'll never see this screen again unless the stored path gets deleted or you explicitly reset it.

If you already have files in `%USERPROFILE%\projects` (a common default), the wizard detects it and adopts it silently — no prompt, no delay.

### How it works

Every launch after the first:

1. The launcher script stops any existing SEPCC `fcc-server` already bound to the configured port, then starts a fresh proxy server in a separate window.
2. It waits for the server to become healthy (up to 30 seconds).
3. `pick-project.ps1` reads your saved projects root and shows a numbered list of every project folder inside it.
4. You pick a project — by number, by [B]rowse dialog, or by [0] typing a path manually. You can also press [R] to reset and pick a new projects root.
5. **The projects root itself can never be selected as a project** — you must pick a subfolder inside it. If you browse to a folder outside the root, you get a friendly reminder but it still opens.
6. If the project hasn't been bootstrapped yet (no `.claude/settings.json`), the launcher auto-runs `fcc-bootstrap-context` to scaffold hooks, agents, and the handoff system.
7. It launches `fcc-claude` pointed at that project folder, with the full context layer active.

The path chain:

```
Desktop shortcut (launch-fcc-claude.cmd)
  → Resolves repo root from its own location (%~dp0..\..)
  → Runs stop-fcc-server-on-port.ps1 for the configured FCC port
  → Starts proxy server on port 8082
  → Runs pick-project.ps1:
      → Loads saved projects root from %APPDATA%\SEPCC\projects-root.txt
      → Lists subdirectories as numbered choices
      → [B]rowse, [0] type path, or [R] change projects root
  → Auto-bootstraps if needed
  → Launches fcc-claude
```

### Empty folder? No projects yet?

If your projects root exists but has no subfolders yet, the picker tells you exactly what to do:

```
  No project folders found yet.

  What to do:
    1. Create a subfolder here for your project, then re-launch.
    2. Copy an existing project folder into this location.
    3. Use B to browse to a project outside this root (not recommended).
```

You can still press B to browse anywhere or 0 to type a path directly — the picker won't block you. But the recommended workflow is: create a subfolder first (one per project), then re-launch. That way every project shows up in the list going forward.

If you pick a folder that's completely empty (no files at all), the launcher gives you a choice:

- **Press Enter** — start fresh. Auto-bootstrap runs, Claude Code launches, you tell it what to build.
- **Type `q`** — quit, copy your existing project into the folder, re-launch.

### Changing the projects root later

You have three options, from easiest to most deliberate:

1. **During picker**: Press `R` at the project selection prompt. This deletes the saved config and exits. Next launch shows the first-run wizard again.
2. **Delete the config file**: Delete `%APPDATA%\SEPCC\projects-root.txt`. Same effect — next launch re-runs setup.
3. **Use an environment variable**: Set `FCC_PROJECTS_ROOT` system-wide or in your shell. The picker uses this instead of the saved config. Useful for portable setups or if you share a machine.

```cmd
set "FCC_PROJECTS_ROOT=D:\all-my-coding-projects"
```

The env var takes priority over the saved config, so you can switch roots without deleting anything.

### How this differs on Linux and macOS

The desktop shortcut is Windows-only. On Linux and macOS, you use the terminal:

**Linux:**
- Install via `install.sh`
- Start the proxy: `fcc-server` in one terminal
- Launch Claude: `fcc-claude /path/to/your/project` in another
- No interactive picker — you navigate by path
- Projects config would live at `~/.config/sepcc/projects-root.txt`
- You can create a `.desktop` file for one-click launch if you want

**macOS:**
- Same install and two-terminal workflow as Linux
- Config would live at `~/Library/Application Support/sepcc/projects-root.txt`
- You can wrap this in a `.app` bundle or Dock shortcut for one-click behavior
- Neither a `.app` bundle nor a Dock shortcut is provided today

On all platforms, the `FCC_PROJECTS_ROOT` environment variable is the universal override. Set it in `.bashrc`, `.zshrc`, or your shell profile and both `fcc` and `fcc-claude` respect it.

### Opting out

If you don't want the picker, the stored path, or any of this logic:

- **Skip the shortcut entirely.** Start `fcc-server` in one terminal, run `fcc <project-path>` in another. The picker only runs when you click the desktop shortcut.
- **Set `FCC_PROJECTS_ROOT` to the exact project path you want.** The picker skips entirely because a single project isn't a projects root — it just opens directly.
- **Delete `%APPDATA%\SEPCC\projects-root.txt`** to clear the saved config and go back to square one.
- **Don't want the shortcut at all?** Delete `launch-fcc-claude.cmd` and `pick-project.ps1` from your install. Nothing else depends on them.

---

## Development

### Project layout

```
SEPCC/
├── server.py              # entry point
├── api/                   # FastAPI routes, admin UI, model router
├── core/
│   ├── _sys.py            # shared process/slug utilities
│   ├── anthropic/         # protocol helpers, SSE, thinking, tools
│   ├── context/           # handoff, retrieval, SQLite store, summarizer
│   ├── debugger/          # agent debugger — report schema + trigger logic
│   └── graph/             # knowledge graph — store, loader, query, context
├── providers/             # 17 provider transports + registry
├── messaging/             # Discord, Telegram, voice
├── cli/                   # launcher, session mgmt, bootstrap, doctor
├── config/                # settings, provider catalog
├── scripts/
│   ├── hooks/             # lifecycle hook scripts (5 events)
│   ├── graph/             # MCP server (8 knowledge graph tools)
│   └── windows/           # desktop shortcut launcher
├── .agents/               # Codex project skills used by this repo
├── .claude/
│   ├── agents/            # project agents (code-review, debugger, fixer, ...)
│   ├── skills/            # Claude Code project skills
│   └── commands/          # slash commands
├── .codex/                # Codex project agents, config, and hooks
├── .fcc/                  # handoff, decisions, indexes, and local runtime state
├── templates/project/     # bootstrap scaffold
├── docs/                  # design specs and implementation plans
└── tests/                 # 1,804 unit, integration, contract, advanced, and smoke tests
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
uv run ty check
uv run pytest
```

### Package entry points

- `fcc` — Claude Code launcher
- `sdc` — alias for `fcc`
- `fcc-server` — start the proxy
- `fcc-init` — scaffold `~/.fcc/.env`
- `fcc-claude` — compatibility launcher
- `fcc-bootstrap-context` — scaffold project context (hooks, agents, skills, handoff)
- `fcc-bootstrap-context --install-graphify` — also install knowledge graph tooling
- `fcc context doctor` — validate and auto-repair context scaffolding
- `fcc sessions list/doctor` — session registry management
- `free-claude-code` — alias for `fcc-server`

### Adding a provider

Extend `OpenAIChatTransport` (OpenAI-compatible) or `AnthropicMessagesTransport` (Anthropic-compatible). Register in `config/provider_catalog.py` and `providers/registry.py`.

---

## Contributing

Keep PRs small and tested. Don't open Docker PRs. Don't open README PRs — open an issue instead. Run `ruff format`, `ruff check`, `ty check`, and `pytest` before pushing. Do not add `# type: ignore` or `# ty: ignore`; fix the underlying type issue.

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
