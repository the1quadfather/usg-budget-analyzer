# AGENTS.md — rules for coding agents in this repo

Codex reads this file automatically. Claude Code reads it when told to. Keep it short;
the long-form context lives in the files it points to.

## Read first, in this order

1. `CODEX_HANDOFF.md` §1–§2 — what the repo is, and the invariants you must not break.
2. `CODEX_TASKS.md` — the task you were assigned, and only that task.
3. `CODEX_HANDOFF.md` §5 — the verification playbook you run before you finish.

## Working rules

- **One task per branch, one branch per task.** Branch name `codex/<task-id>` (for
  example `codex/t8a`). Never commit directly to `main`; open a PR or hand the branch back.
- **Do exactly the task's scope.** If you notice something else worth fixing, write it
  in your final report; do not fix it in the same change.
- **If the code or data contradicts the task, stop and report.** Do not loosen a parser,
  widen a tolerance, or invent a fallback URL so that the task "passes".
- **Never reorder `st.tabs()` labels between reruns.** Streamlit keeps the selected tab
  by position in the browser, so reordering maps one tab's content under another's label.
  Select a tab with `st.tabs(labels, default=..., key=..., on_change=...)`
  (Streamlit ≥ 1.55, pinned in `requirements.txt`). This bug shipped once already.
- **Any UI change must be exercised in a real browser**, not only through
  `streamlit.testing.v1.AppTest`. AppTest cannot see which tab the browser has selected.
  Run `python -m streamlit run dod_ic_budget_analyzer/app.py --server.port 8501`,
  click through the tab you touched, and say in the report that you did.
- **Units at every boundary.** `funding_lines.amount_thousands` and every `*_k` column in
  `pe_execution` are thousands of dollars; `pe_accomplishments.funding_millions` is
  millions. Name new columns with the unit suffix (`_k`, `_m`).
- **Coverage is stated, never implied.** A missing year renders as absent, not zero.
- **Authorization is not appropriation; House and Senate are never pooled.**
- **Grounded AI results are per-user.** Do not change how `config.GROUNDED_TASKS` is
  classified or cached. This is a terms-of-service boundary.
- Do not commit `data/raw/`, the uncompressed `.db`, `.env`, API keys, or AI runtime rows.
- Do not reformat `app.py` wholesale. Match the surrounding style; no line-width sweeps.

## Verify before you finish

From `dod_ic_budget_analyzer/`:

```bash
python -m pytest -q
python analysis/ai_budget_eval.py        # after any change under analysis/ai_* or oss_enricher.py
python analysis/linker_eval.py           # after any change under matching/ or program_linker.py
```

Paste the output in your report. If a command cannot run (missing model cache, no
network), say so explicitly rather than skipping it silently.

## Final report format

1. What changed (files, one line each).
2. What you verified, with command output.
3. What you could not verify, and why.
4. Open questions or things you noticed but did not touch.
