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
