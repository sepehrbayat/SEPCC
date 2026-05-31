# FCC Context Hardening

FCC remains the provider/router layer. This scaffold adds deterministic context files, compact hooks, Token Savior code retrieval, and a single designated persistent-memory owner, MemSearch, without adding a second routing proxy.

## Bootstrap

From another project root:

```bash
fcc-bootstrap-context
```

Useful flags:

```bash
fcc-bootstrap-context --force
fcc-bootstrap-context --install-token-savior
fcc-bootstrap-context --install-memsearch
fcc-bootstrap-context --large-repo
```

Default bootstrap configures Token Savior MCP. `--install-token-savior` only prefetches the external package. `--install-memsearch` installs the designated MemSearch CLI. `--large-repo` is the only flag that adds Claude Context MCP. Token Savior stays the default code-retrieval owner.

## Critical Facts

Put facts that must survive session loss in `CLAUDE.local.md`, not in chat. Chat context is volatile, can be compacted, and cannot be trusted as a durable source of machine-local facts such as paths, ports, local service names, temporary credentials, and operator preferences.

Use:

- `CLAUDE.md` for concise project rules that are safe to commit.
- `CLAUDE.local.md` for volatile local-machine facts.
- `.fcc/context/handoff.md` for current state.
- `.fcc/context/decisions.md` for concise durable decisions.
- SQLite sidecar handles for raw logs and large tool output.

## Owner Rules

Use one owner per job:

- Persistent memory owner: MemSearch. Install it with `--install-memsearch` when a project needs persistent external memory.
- Code retrieval owner: Token Savior.
- Provider/router owner: FCC.

Do not run overlapping default owners. In particular:

- If MemSearch is selected, do not install Claude-mem as a default memory owner.
- If Token Savior is baseline, do not add Claude Context MCP unless `--large-repo` is explicitly chosen.
- Do not stack multiple hook owners on the same lifecycle event. SessionStart, UserPromptSubmit, Stop, and PreCompact should each have one active owner unless you intentionally audit the interaction.

## Baseline Tools

Token Savior is configured in `.mcp.json` with:

```bash
uvx --from token-savior-recall==4.4.1 token-savior server
```

MemSearch is the designated persistent memory owner. The bootstrap helper can install the `memsearch[onnx]` CLI with `--install-memsearch`; install the Claude Code MemSearch plugin only when you want its hook-driven memory capture.

## Optional Only

These are optional integrations, not defaults:

- context-mode
- Claude Context MCP
- MOS
- Claude-mem
- Caveman
- Cymbal
- Claude Token Saver
- ccpost
- cco

Treat them as project-specific additions. Add one only when it has a concrete job that MemSearch, Token Savior, FCC hooks, or the SQLite sidecar do not already cover.

## Sandbox Options

Security restrictions are not required for this scaffold. Full local access is allowed by default. If a project wants sandboxing, document it as a local optional policy in `CLAUDE.local.md` or `.claude/settings.local.json`; do not make sandboxing a default bootstrap requirement.

## Handoff Discipline

The handoff is the current-state file, not a transcript. Keep it short:

- What must not be forgotten.
- What is currently true.
- Decisions made.
- Next concrete step.

Store raw terminal and tool outputs in the SQLite sidecar and recall them by handle with:

```bash
some-command 2>&1 | fcc-context-store --kind terminal --source "some-command"
fcc-context-store --file logs/tool-output.txt --kind tool --source "tool-name"
```

Query stored output with:

```bash
fcc-context-query "search terms"
```

## Terminal Session Resume

FCC stores terminal chat session metadata in the project-local `.fcc/sessions.sqlite` registry and reuses the existing handoff and memory layers for continuity. It does not replay raw transcripts.

Use:

```bash
fcc
fcc resume
fcc resume <session-id-or-name>
fcc sessions list
fcc sessions doctor
```

`sdc` exposes the same commands for installs that use that name.

When `FCC_AUTO_RESUME_LAST_SESSION=true`, a plain interactive `fcc` in a project resumes one recent compatible session automatically, or shows a compact picker when more than one recent session exists. `FCC_AUTO_RESUME_MAX_AGE_DAYS`, `FCC_AUTO_RESUME_PROJECT_SCOPED`, and `FCC_SESSION_PICKER_ON_AMBIGUOUS` tune that behavior.

If the native Claude transcript is available, FCC launches Claude Code with native `--resume`. If the transcript is missing but `.fcc/context/handoff.md` exists, FCC starts a fresh native session with only compact handoff and retrieval snippets, then links it as a continuation of the previous FCC session.

## Default Agent Runtime

Bootstrapped projects include `.fcc/context/agent-runtime.md`, `.fcc/plugin-policy.yml`, FCC hooks, project subagents under `.claude/agents/`, a command-router skill under `.claude/skills/`, and a compact FCC status line. `SessionStart` injects the compact runtime contract, local facts, command-startup advice, and current handoff into every main chat. `UserPromptSubmit` adds short routing and built-in-command hints when the user asks for context management, project setup, review, verification, CLI UI setup, or RTL-language work. Subagents inherit the same operating rules from their project agent definitions, and `SubagentStop` refreshes handoff state after delegated work. Claude Code now documents both `SubagentStart` and `SubagentStop`; FCC's default scaffold only needs `SubagentStop` because startup awareness is provided through project agent definitions and `SessionStart`.

Use:

```bash
fcc context doctor
fcc sessions doctor
```

The doctor checks runtime files, supported hooks, duplicate hook owners, MemSearch/Claude-mem mutual exclusion, Token Savior baseline ownership, and Ralph Loop policy. Ralph Loop is optional and should be used only for bounded, test-verifiable loops with explicit completion criteria and a max-iteration cap. FCC never replays raw transcripts; raw output belongs in the SQLite sidecar and compact handoff/memory snippets carry continuity.

## Claude Code Built-ins First

FCC should not reimplement Claude Code's slash-command layer. The command-router skill and hook hints prefer:

- `/init` for `CLAUDE.md` project documentation.
- `/context all` and `/compact <focus>` for context pressure.
- `/diff`, `/code-review`, and `/security-review` for local review workflows.
- `/batch` for large independent worktree units when a git repository is available.
- `/run` and `/verify` for live app validation.
- `/doctor`, `/debug`, `/status`, and `fcc context doctor` for diagnostics.
- `/config`, `/theme`, `/statusline`, `/terminal-setup`, and `/tui fullscreen` for CLI ergonomics.

Prompt enhancement must not rewrite explicit slash commands. Slash commands are control input and should pass through unchanged.
