# Agentic Tooling Audit

Source reviewed: https://github.com/hesreallyhim/awesome-claude-code

The upstream repo is most useful as a curated index of Claude Code practices. Its top-level license is CC BY-NC-ND 4.0, so this project should not vendor or modify its resource files. The safe path is to adopt the ideas that improve evidence gathering and verification, then express them as original Codex-native skills, agents, and project instructions.

## Integrated

- Global Codex skill: `dan-agent-accuracy`
  - Canonical path: `~/.agents/skills/dan-agent-accuracy` (Windows: `%USERPROFILE%\.agents\skills\dan-agent-accuracy`)
  - Active Codex bridge: `~/.codex/skills/dan-agent-accuracy` (Windows: `%USERPROFILE%\.codex\skills\dan-agent-accuracy`)
  - Purpose: context priming, resource adoption review, bug/PR workflows, browser QA, verification ladder, and durable memory guidance.

- Global custom agents:
  - `dan_repo_mapper`: read-only repo intake and owner-code mapping.
  - `dan_review_auditor`: read-only correctness/security/test-risk review.
  - `dan_browser_qa`: Playwright/browser QA for frontend and local web behavior.
  - `dan_tooling_scout`: external skill/plugin/MCP/hook adoption review.

## Selected Patterns

- Context priming before edits: read local instructions, map files, identify manifests, and locate checks.
- Issue and bug workflow: reproduce, isolate the owner path, add tests, fix narrowly, verify.
- Review workflow: lead with evidence and file references, not broad taste or speculative advice.
- UI workflow: verify live behavior with Playwright/browser tooling when user-facing UI is involved.
- Tool adoption workflow: inspect license, hooks, shell execution, network access, persistent state, and uninstall path before installing.
- Memory workflow: keep durable project lessons in a small note or memory MCP only after verification.

## Deliberately Not Installed

- Claude-only hooks and auto-approval packages: high implicit-execution risk and not directly portable to Codex.
- Large orchestrators/swarms: powerful, but too broad as a default for this proxy project.
- Usage dashboards/status lines: useful observability for humans, not a default accuracy improvement.
- Unclear-license or no-derivatives resource contents: linked as inspiration only.

## Project Fit

For `free-claude-code`, the immediate accuracy gains are stronger provider/proxy verification, live smoke checks, and repeatable review workflows. A heavyweight semantic memory layer is not installed by default; use `docs/agent-memory.md` for stable project facts until a dedicated memory MCP is intentionally selected.
