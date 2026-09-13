# Claude Code: read the shared agent rules

@AGENTS.md

The rules above are shared with Codex and are the single source of truth for working in
this repo. Do not duplicate them here; edit `AGENTS.md` instead so both agents stay in sync.

## Division of labor on this machine

- **Claude** (this file's reader): scoping, verifying source facts, writing and revising
  task specs in `CODEX_TASKS.md`, reviewing Codex branches, and direct work Logan asks for.
- **Codex**: implements one task per `codex/<task-id>` branch, following `AGENTS.md`.
- Handoff prompt template lives in `CODEX_TASKS.md` §0.

## Machine notes (Surface Laptop, set up 2026-09-10)

- Shell is Windows PowerShell 5.1: no `&&`, use `;` or `if ($?) { }`.
- Toolchain (installed 2026-09-11 via winget): Git 2.55, Node 24 LTS, Python 3.12, GitHub CLI.
- Python deps live in the repo-root venv `.venv` (gitignored). Run project commands as
  `.\.venv\Scripts\python.exe -m ...` from `dod_ic_budget_analyzer/`, or activate it first.
- `.claude/launch.json` (gitignored) has a `budget-analyzer` config on port 8501 using that venv.
