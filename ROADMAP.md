# DoD Budget Explorer — roadmap

Updated 2026-11-22 against the code and bundled database. This replaces the
2026-09-08 implementation plan, much of which has since shipped. Historical
specifications remain in `CODEX_TASKS.md` and `CODEX_HANDOFF.md`; their older
claims about missing features and test counts are not current product status.

The next objective is a dependable analyst workflow and a bounded management
pilot. Implemented functionality does not imply complete coverage, confirmed
inferences, or a verified hosted deployment.

## Implemented

| Capability | Implementation | Remaining limit |
|---|---|---|
| Shareable views | `app.py` query-state helpers | Links restore views; they do not share private collection notes |
| Saved portfolios and watchlists | `analysis/portfolios.py`, Programs, browser storage | Private to this browser; JSON backup/restore, no account sync or scheduled delivery |
| CSV/XLSX exports and provenance | `analysis/provenance.py`, table downloads | Tables export separately from the executive briefing |
| Executive briefing PDF | `analysis/executive_briefing.py`, saved collections | Annual discretionary request comparison; no editable PowerPoint, review approval, or scheduled delivery |
| Constant FY2025 dollars and PB vintage labels | `analysis/deflators.py`, funding views | RDT&E deflators apply to R-1 funding, not every monetary panel |
| DD 1416 ingest and execution views | downloader, parser, ingest, `analysis/execution_view.py` | Budget-authority status, not obligations or outlays; latest shipped report is 2026-03-31 |
| Regression tests and AI governance checks | `tests/`, `.github/workflows/ci.yml` | Prepare model weights before offline retrieval tests |
| Reconciliation core and Coverage panel | `analysis/reconcile.py`, `app.py` | R-1 needs unshipped source workbooks; DD 1416 uses next-cycle R-1 CY figures, not a comprehensive appropriations-act audit |
| P-1 procurement ingestion | `parsing/xlsx_ingest.py`, `storage/ingest_p1.py` | 5,253 observations from PB2026/PB2027, covering FY2024–FY2027 |
| Procurement-transition candidates | `analysis/transition.py`, Funding profile | Narrative/title/semantic inference; no official PE-to-BLI key join |
| PE lineage and chart seams | `analysis/lineage.py`, `storage/ingest_lineage.py`, funding charts | 405 stored links; inferred relationships and coverage need review |
| Data dictionary and release builder | `DATA_DICTIONARY.md`, `scripts/build_release.py` | Generates a local bundle; publishing releases is manual |
| PE change feed | `analysis/changefeed.py`, Trends, `scripts/export_changefeed.py` | UI/JSON export exists; no scheduled notifications or subscriptions |
| Narrative retrieval and cited AI answers | `analysis/narrative_qa.py`, Programs | Validates quoted source spans; interpretation still needs review |
| Resumable fact extraction and facts panel | `analysis/narrative_extract.py`, Justification | 25 facts from 50 completed extractions; full-corpus extraction is incomplete |
| Vocabulary, badges, light theme, readable captions | `app.py`, `.streamlit/config.toml` | Multipage restructure (historical T16b) remains unimplemented |
| Optional private-demo allowlist and AI spend controls | `app.py`, `analysis/ai_budget.py` | Deployment must configure access; public demos should omit AI keys |

Counts were read from the shipped data on 2026-11-21: 2,131 program records
(2,055 distinct PE numbers), 55,652 funding observations, narratives for 1,383
PEs, 26,544 congressional actions, and 79,677 DD 1416 rows from 381 workbooks.
Fiscal-year coverage varies by source.

## 1. Restore a repeatable demo and reliable checks

Recovery changes implemented: an explicit model-cache preparation command;
offline pytest execution after preparation; model weights baked into Docker;
the narrative index and deflator CSV included in the image; startup and Docker
healthchecks using the hosting platform's `PORT`; and a CI container smoke
check for packaged data, offline retrieval, and a non-default port. Direct
Linux/Windows installs also select the verified CPU torch build, so free hosts
do not pull several GB of unused CUDA dependencies.

The original failure reproduced as 2 failed / 94 passed with an empty model
cache. After preparation, the local run passed 96/96 tests, 64/64 AI governance
checks, and 5/5 gated narrative retrieval cases. Browser verification then caught
a constant-dollar chart crash caused by text-valued fiscal years; converting
them before applying deflators and adding a toggle/permalink regression test
brought the final local suite to 97/97. No tests were removed or
relaxed to obtain that result.

Linux tests and container checks passed for the merged recovery and CPU-install
revisions. The existing free **[Streamlit Community Cloud demo](https://usg-budget-analyzer-mlwcj2nxr2lsg7ppbggg9p.streamlit.app/)**
was woken, configured for Python 3.12, and rebooted from `main`. Verification on
2026-11-21 confirmed `200 ok` from its app health endpoint, constant-dollar
charts, PE 0601102A funding/execution, and cited Skyborg passages from a corpus
question before any program search. The News panel confirms no Gemini API key
is configured, so paid AI features are disabled. The program-linker evaluation
also passed 11/11 locally.

Recovery changes are merged in PRs #1 and #3. The demo follows `main`; those
merge revisions are `8d02192` (recovery) and `a48f1c5` (CPU install). Railway
remains an optional deployment target and is not required for the free demo.

Remaining operations work:

- Name an ongoing deployment owner and document the rollback procedure.
- Rehearse a program search and corpus query before presentations; free apps
  sleep after inactivity and model loading adds startup time.
- Keep paid AI keys out of public deployments. Configure identity and retain
  existing spend limits for any private AI demonstrations.

## 2. Strengthen interpretation before management use

1. Cross-reference changes with lineage and coverage. Distinguish newly/no-longer
   observed PEs from confirmed starts or cancellations. The feed currently uses
   absence from a newer submission to label a termination; a renumbering can
   appear as both a termination and a new start.
2. Keep funding stages and PB vintages explicit. Separate revised requests,
   enacted amounts, and actuals in change summaries.
3. Present fuzzy/semantic values as match scores rather than calibrated
   probabilities. Distinguish exact identifiers, inferred links, and reviewed
   findings.
4. Add analyst review state and source-linked notes. A valid quotation proves
   that text exists in a source, not that an AI interpretation follows from it.
5. Expose source freshness, missing references, and partial narrative/fact
   coverage beside management-facing summaries.

Acceptance: a reviewer can tell what changed, which figures are comparable,
what supports a conclusion, and what still needs confirmation.

## 3. Build a recurring portfolio workflow

Implemented: named portfolios and watchlists with exact PE/component membership,
analyst notes, saved PB cycles and dollar basis, and JSON backup/restore. Annual
discretionary BY requests are compared on the same basis. A comparable movement
must meet both dollar and percentage limits; presence changes have a separate
setting. Missing observations stay absent and do not establish cancellation.
Saving stays in the browser, outside the shared budget database; an older tab
cannot overwrite a newer save without an explicit restore.

Remaining work:

- Account-based sharing and cross-device sync when an access model is agreed.
- Reviewed changes since the last briefing. Scheduled delivery is separate from
  the existing JSON exporter.
- Versioned snapshots preserving the data and selections behind a briefing.

Acceptance: an analyst can reopen a portfolio, review relevant changes, record
findings, and reproduce the prior briefing without rebuilding searches.

## 4. Deliver briefing outputs and run a management pilot

Implemented: a PDF export of a saved portfolio or watchlist, with an executive
overview, component chart, complete paginated program table, analyst commentary,
UTC generation timestamp, bundled archive identifier, source URLs and method.
Covered totals disclose their observation counts; comparable-cohort changes
exclude missing pairs. Requests remain distinct from enacted appropriations,
obligations and outlays. The download is per-session and uses no AI calls or new
dependencies. Unsupported font characters produce a visible error rather than
silently dropping text.

Remaining: editable PowerPoint, analyst approval/review history, scheduled
delivery, and versioned underlying data snapshots that can recreate a previous
briefing. A downloaded PDF fixes the displayed figures; a collection JSON backup
alone does not preserve an older database.

Proposed pilot: 30 days, 3–5 analysts, and 10–20 organization-relevant programs.
Agree on representative questions and a manual baseline before measuring time
to answer, sampled figure accuracy, briefing usefulness, and repeat usage.
These are proposed criteria, not demonstrated savings.

Before broader use, name the business sponsor, technical owner, backup
maintainer, and data-refresh owner. Document hosting, access, refresh cadence,
support, operating cost, and release/rollback procedures.

## Coverage and distribution work that remains

- Refresh/backfill source-specific R-2 gaps and extend P-1 coverage when official
  documents are available. Missing years remain absent, never zero.
- Review more lineage/transition cases and grow evaluation sets before treating
  inferred links as broadly reliable.
- Expand fact extraction beyond the sample through the existing resumable,
  cost-estimated batch job.
- Publish and maintain versioned data releases with the implemented builder;
  generation and distribution are separate completion criteria.
- Consider multipage navigation after observing the four-tab workflow with
  pilot users. A framework rewrite is not a prerequisite.

## Constraints retained

Authorization is not appropriation; House and Senate are never pooled.
Discretionary and mandatory streams remain separate. DD 1416 does not report
outlays. Award searches and procurement transitions are leads, not exact public
crosswalks. Grounded AI results stay per-user. Coverage gaps stay visible.

No uncited chatbot, expanded public-emphasis scoring, unavailable public FYDP
dependency, or framework migration is required for recovery or the pilot.
