# Decisions

- Persistent memory owner: MemSearch.
- Code retrieval owner: Token Savior.
- FCC remains the provider/router layer.
- UserPromptSubmit hooks may add enhanced prompt context and visible status, but must not rewrite explicit slash commands.
- Prompt enhancement model is configurable through `PROMPT_ENHANCER_MODEL`.
- Local session databases are runtime state and should not be committed with prompt/session excerpts.
## 2026-05-31
- Persistent memory owner: MemSearch
- Code retrieval owner: Token Savior
- UserPromptSubmit hooks may add enhanced prompt context and visible status, but must not rewrite explicit slash commands
## 2026-06-02
- The full graph is never rebuilt from scratch unless explicitly requested
- This is the critical design decision
- They do not consume context window unless the model calls them
- • Key files the subagent must read:
- This means SEPCC's integration must work *through* the hooks and tools it already controls, not by modifying Claude Code itself
## 2026-06-02
- Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it
- The design can be short (a few sentences for truly simple projects), but you MUST present it and get approval
- You MUST create a task for each of these items and complete them in order:
- ** Do NOT invoke frontend-design, mcp-builder, or any other implementation skill
- (User preferences for spec location override this default)
## 2026-06-02
- file counts, decision extraction from task 1 transcript
- The main session never knows it's being monitored
- user: Given your understanding of the project and of yourself as an agent, you’re in the best position to judge it and, in my opinion, you should choose the best strategy yourself
- I'll choose
- Both run in background — the user never waits
## 2026-06-02
- Runs in **git worktree isolation** so it never conflicts with the main agent's task 2
- The main agent continues with task 2, never having paused
## 2026-06-02
- The conservative default is "don't interrupt" — false negatives are acceptable (missed debug) where false positives are painful (unnecessary pipeline)
- The main agent is never blocked
- **Detection:** The fixer runs in a **git worktree**, so it never touches the main session's working directory
## 2026-06-02
- **Detection:** The `UserPromptSubmit` hook detects a cancellation intent in the prompt: keywords like "stop", "cancel", "skip", "never mind", "don't debug"
- | `test_fix_priority_ordering` | Array preserves order; finding IDs must match |
## 2026-06-02
- (User preferences for plan location override this default)
- **Every plan MUST start with this header:**
- Every step must contain the actual content an engineer needs
- These are **plan failures** — never write them:
- **If Subagent-Driven chosen:**
## 2026-06-02
- They should never inherit your session's context or history — you construct exactly what they need
- **Continuous execution:** Do not pause to check in with your human partner between tasks
- **Never** ignore an escalation or force the same model to retry without changes
- **Never:**
## 2026-06-02
- assistant: Now let me add the missing test the reviewer flagged — debugger must NOT have Write/Edit
## 2026-06-02
- ├─ Existing: extract Must Not Forget + Current State from handoff
- | **No communities detected** (Leiden skipped, graph too small) | Community queries return all entities in a single default community
- Never crash
- | `test_session_bootstrap_within_token_budget` | Under budget (default 600 tokens) |
- | `test_task_injection_within_budget` | Under budget (default 200 tokens) |
## 2026-06-02
- , invalid JSON, missing fields, non-dict nodes), the store's SQLite connection is never closed
- `_tasks_are_same` uses regex split for comparison but regex tokens are never cleaned**
- ### LIMITATIONS (not bugs, but must document)
- Each thread must create its own `GraphStore` instance
## 2026-06-02
- assistant: Reverting B4/B5 to inline-only (import boundary contract: `core/` must not import `cli/`):
## 2026-06-02
- Both claim to skip fenced blocks but they do it differently, and critically they have **different default `max_lines`** values (14 vs 12)
- DECISION EXTRACTION FALSE POSITIVES -- overly broad regex
- **Issue:** The decision regex is:
- r"\b(decided|decision|choose|chosen|must|default|owner|do not|never)\b"
- This matches many non-decision patterns:
