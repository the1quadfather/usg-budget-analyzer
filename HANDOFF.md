# DoD Budget Explorer — session handoff (2026-08-27)

Context for a follow-on Claude Code session. Assume zero prior knowledge.

## The project

Streamlit app at `C:\Users\lbsch\Documents\USG Budget Analyzer\dod_ic_budget_analyzer`.
Traces US defense RDT&E programs from budget request → congressional action → contract
awards → public statements. SQLite (`data/processed/usg_budgets.db`), Polars/pandas,
SQLAlchemy 2.0, sentence-transformers + rapidfuzz matching, optional Gemini enrichment.
Four tabs: Budget Trends, Program Finder, Rhetoric vs. Budget, Data Coverage.

Run it: `python -m streamlit run dod_ic_budget_analyzer/app.py` (`.claude/launch.json`
has a `budget-analyzer` config on port 8501).

**Goal:** monetize as a self-serve subscription — free DB-backed tier, ~$29/mo paid tier.
Breakeven is 1–2 subscribers. Hosting ~$7–25/mo is the only real fixed cost.

## State: Milestone 1 shipped, NOT COMMITTED

⚠️ **Do this first.** Everything below exists only in the working tree.

```
new:      analysis/ai_budget.py  analysis/ai_precompute.py  analysis/ai_budget_eval.py
modified: storage/db.py  config.py  app.py  analysis/oss_enricher.py  README.md
```

M1 = AI cost control + semi-automatic AI:

- **`analysis/ai_budget.py`** — `AICache` (shared cache), `SpendLedger` (measured token
  and search-query costs), `budget_guard` (monthly USD ceiling + per-user credits).
- **`analysis/ai_precompute.py`** — offline worker warming the cache, demand-driven from
  a new `search_log` table. Written but **nothing schedules it**.
- **`analysis/ai_budget_eval.py`** — 51 self-checks, all passing. Run after any change here.
- **`oss_enricher.py`** — every call goes through one governed path:
  `cache → guard → call → meter → cache`. Returns an `EnrichmentResult`
  (`payload, cached, created_at, search_suggestions_html, blocked, cold, grounded, message`).
- **UI rule:** warm cache auto-renders with an "as of" caption and no button; cold shows a
  button naming its source. `allow_fresh=False` is a cache-only probe that never spends;
  `force=True` skips the cache read but still obeys the ceiling.

### Two hard rules the code enforces — do not "simplify" these

1. **Grounded results are per-user, never shared.** The Gemini API terms forbid caching,
   analyzing, reselling, or cross-user sharing of Grounded Results (narrow carve-out:
   that user's own history, ≤2 years). `AICache.put()` routes `config.GROUNDED_TASKS` to
   `ai_user_history` keyed by `user_id`; everything else goes to the shared `ai_cache`.
   Non-grounded adjudication IS shared — that's where the cost savings come from.
   Compliance check: `SELECT COUNT(*) FROM ai_cache WHERE task IN
   ('find_open_source_hits','annual_signal')` must return **0**.
2. **Verify the search actually ran.** `gemini-3.6-flash` will answer a "find recent
   coverage" prompt *from memory* — `grounding_metadata` comes back `None` — inventing
   plausible outlets and dates. It does this especially when the prompt demands strict
   JSON. `find_open_source_hits` is therefore **two calls on purpose**: grounded research
   in prose (reliably searches), then a cheap ungrounded pass to structure it. If
   `grounding_metadata is None`, output is discarded and `grounded=False`. **Do not merge
   these back into one JSON-demanding prompt.**

### Measured AI costs (real calls, not estimates)

- `adjudicate`: **$0.0041** — 267 in / 144 out / **908 thinking tokens**.
- `find_open_source_hits`: ~$0.023 tokens + 6 search queries (~$0.107 past the 5,000
  free queries/month).
- **Thinking tokens dominate** (often 5–6× visible output) — always bill
  `thoughts_token_count` at the output rate. Both original estimates were ~2× low because
  they ignored it.
- Grounding bills **per query executed** (Gemini 3.x), several per prompt.
- Token prices **double 2027-01-01** ($0.75/$3.75 → $1.50/$7.50); encoded in
  `config.GEMINI_PRICING` with a `step_up_date`.

## Verified 2026-08-27 — the finding that reorders the roadmap

**HASC/SASC NDAA authorization committee reports print full RDT&E funding tables as
plain text.** Key-free at `https://www.govinfo.gov/content/pkg/{ID}/html/{ID}.htm`:

```
196   0605864N   TEST AND EVALUATION SUPPORT    463,725    -15,801    447,924
      ....................   Program decrease.......         [-15,801]
```

Line # · PE number · title · request · committee delta · authorized · **plus the stated
reason**. Independently spot-checked: **770/770, 756/756, 727/727** PE numbers joined
exactly against the shipped DB (`CRPT-118hrpt125`, `CRPT-117hrpt118`, `CRPT-119hrpt231`).
~30 documents cover the 112th–119th Congress. One regex, no API key, no ML.

Caveats: titles wrap onto continuation lines (parser must handle them). **Machine-readable
PE tables start at FY2012** — earlier reports are GRAPHIC images, so congressional actions
cover only about half the funding history. Disclose that in the UI.

### Plan assumptions that were disproven

| Assumed | Reality |
|---|---|
| Reuse `ProgramLinker` for document→PE linking | **0/12 hit@1** on hearing-length passages (20/20 on bare titles, 5/20 on a full narrative). Stage 0 returns only the *first* PE found at confidence 1.0 with `needs_review=False` and is exempt from the ambiguity check. Acronyms like "space" score 0.98, clearing `fuzzy_accept` and skipping the semantic stage. Encoder truncates ~2,000 chars. Windowing at 1,200 chars / 200 overlap recovers 9/12. |
| Fine-tune the embedding model | 270 deduped pairs, **Defense-Wide only** — zero narratives for Air Force (640 PEs), Army (435), Navy (396), Space Force (84). Wrong task shape, and the eval is pinned at 100% so there's no headroom to show a gain. **Dropped, not deferred.** |
| war.gov press releases | Akamai 403s every programmatic client including `robots.txt`. RSS gives 174-char summaries, 500-item cap, back only to Dec 2024. **Deleted from the plan.** DVIDS is tier-3. |
| Congressional Record (CREC) | 406k-char FY2025 NDAA floor debate names **zero** of Sentinel, B-21, Golden Dome, NGI, CCA. **Dropped.** |
| Appropriations (HAC-D/SAC-D) tables | Funding tables are **images** — the README's "enacted-vs-request deltas" item is OCR-gated, not parse-gated. |

### Corrected facts (docs and prior notes are wrong)

- DB holds **2,131 `program_elements` / 2,055 distinct PE numbers**, not 1,129.
- `funding_lines` spans **FY1996–FY2027**, not FY1998 (3 stray FY1996 rows).
- Full-catalog adjudication precompute ≈ **$8.40**, not $4.70.
- **GAO is UNVERIFIED** — that probe failed. `config.GAO_REPORTS_API` may be stale.
  Treat as unknown, not available.
- Legal posture confirmed good: 17 U.S.C. 105 public domain; GPO stated (usgpo/api #192)
  no restrictions on derived datasets. Cacheable and resellable — the inverse of Gemini
  Grounded Results.

## Next: M2a (start here after committing)

New `pe_congressional_actions` table: `pe_number, fiscal_year, chamber, report_citation,
request_k, committee_delta_k, authorized_k, rationale`. Write it into the **empty,
already-git-tracked** `acquisition/congress_scraper.py`.

Follow `storage/db.py` conventions exactly: SQLAlchemy 2.0 `Mapped[]`, surrogate `id` PK,
denormalized `(pe_number, agency)` strings rather than an FK, naive UTC datetimes, ints
for booleans, a `String(64)` sha256 `content_hash` as the idempotency key. `create_all`
picks up new tables — no migration tooling needed.

Then replace the Rhetoric tab's synthetic "mention intensity (AI, 0–10)" chart with real
requested-vs-authorized dollars.

**Quality gate for M2a:** every extracted `pe_number` must exist in `program_elements`,
and every extracted `request_k` must reconcile against the matching `funding_lines`
request figure for that fiscal year. A row that doesn't reconcile is a parse bug.

**Then:** alias dictionary + rewritten eval → M3 (auth/Stripe) → M4 (hosting) → M2b
(linker rebuild, then corpus). Full detail in
`C:\Users\lbsch\.claude\plans\we-ve-put-in-a-optimized-newt.md`.

**Biggest risk to avoid:** shipping an inferred "mention count" that is silently and
confidently wrong, and charging for it. A count reads as fact where a hedged "AI, 0–10"
estimate does not, so it would be *worse* than what it replaces. Ship the exact join
first; surface no inferred count until it's measured against true negatives.

## Quick wins (small, independent)

1. Commit M1.
2. `pip install xlsxwriter`, then wire `analysis/report_generator.py` +
   `analysis/gap_analyzer.py` — both complete, both have **zero callers**, and
   GapAnalyzer's output frame is exactly the sheet the report writer emits. A finished
   paid-tier export one pip install away. `import xlsxwriter` currently fails.
3. Fix `gap_analyzer.analyze_gaps()` — polars renamed `pivot(columns=)` to `on=` in 1.0;
   installed is 1.39.3, warning now.
4. Register free keys: govinfo.gov/api-signup, api.congress.gov/sign-up. Instant, only
   the owner can submit, nothing blocks on them yet. `DEMO_KEY` is useless.
5. Clean `pe_narratives.agency` artifacts (3 PEs filed under "Creating Helpful Incentives
   To Produce Semi-Conductors…"). The codebase joins on `(pe_number, agency)` strings, so
   a bad agency silently orphans rows — and the new table uses the same natural key.
6. Delete `parsing/pdf_extractor.py` and `parsing/rdtee_parser.py` (0 bytes, tracked,
   superseded). **Keep** `acquisition/congress_scraper.py` and `gao_scraper.py` — those
   are the M2a/M2b slots.
7. Schedule `analysis/ai_precompute.py` in Task Scheduler — two minutes, and it's what
   makes M1's warm-cache design actually function.
8. Fix README counts (1,129 → 2,055; FY1998 → FY1996).

## Commands

```bash
python analysis/linker_eval.py           # matcher golden set — 11/11, run after ANY matcher change
python analysis/ai_budget_eval.py        # AI cost + compliance self-check — 51/51
python -m analysis.ai_budget --report    # month-to-date spend by task
python -m analysis.ai_budget --prune     # drop expired cache rows
python analysis/ai_precompute.py --limit 20 --dry-run
```

## Traps

- **Streamlit's websocket drops constantly in the browser pane.** Use
  `streamlit.testing.v1.AppTest` to verify UI behavior — far more reliable, and it
  actually exercises the app code.
- **Bash heredocs mangle `\n` escapes** in this environment. Build literal backslash
  sequences via `chr(92)` or use the Write tool for files containing them.
- `st.tabs` resets to the first tab on every rerun.
- `datetime.utcnow()` is deprecated; `ai_budget.py` uses a local `_utcnow()` helper that
  returns naive UTC to match the schema.
- Never cache an empty AI answer — a transient failure would be served as settled fact
  for the whole TTL. `_governed` already guards this.
