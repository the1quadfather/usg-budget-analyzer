# CODEX_TASKS.md — remaining work, as atomic tasks

**Written 2026-09-09.** Companion to [ROADMAP.md](ROADMAP.md) (why, and the order) and
[CODEX_HANDOFF.md](CODEX_HANDOFF.md) (verified source facts, invariants, verification
playbook). `AGENTS.md` holds the working rules and is read automatically by Codex.

This file breaks the unfinished roadmap items (T8–T15) into tasks small enough that each
one is a single branch, a single review, and a single revert. Do them in the order listed
inside a phase. Do not start a task whose "Depends on" line names an unmerged task.

---

## 0. How to hand a task to Codex

Paste this, filling in the task id. One task per Codex run.

```
Read AGENTS.md, then CODEX_HANDOFF.md sections 1 and 2, then the task <TASK-ID> section of
CODEX_TASKS.md. Implement exactly that task and nothing else.

Before writing code: restate the definition of done in your own words, list the files you
will create or change, and name anything in the task that the code or data contradicts.
If a contradiction changes the files, the types, or the definition of done, stop there and
report it instead of improvising. If it only affects an explanatory sentence, choose the
reading that keeps the definition of done intact, say which you chose, and continue.

Work on a branch named codex/<task-id>. Follow the invariants in CODEX_HANDOFF.md section
2. Do not reformat files you touch, and do not change code outside the task's file list.

When finished: run every command under the task's "Verify" heading and paste the real
output. If the task touches app.py, also start the app, click through the affected tab in
a browser, and describe what you saw. Then commit with an imperative subject line and give
the final report in the format AGENTS.md specifies.
```

Why this shape: Codex does best with one bounded objective, an explicit stop condition,
and a required proof of work. Open-ended "implement the roadmap" runs are how the
tab-reordering bug reached `main` — it passed the smoke test and nobody clicked a tab.

---

## 1. Status

| Task | State | Evidence |
|---|---|---|
| T1 Permalinks | shipped | `st.query_params` sync helpers in `app.py`; commit `f3ff2bd` |
| T2 Export + provenance | shipped | `analysis/provenance.py`, `render_table_downloads()` |
| T3 Constant dollars | shipped | `analysis/deflators.py`, `data/processed/rdte_deflators_fy2025.csv` |
| T4 Vintage labeling | shipped | `funding_lines.pb_cycle`, "PB submission" column in tables |
| T5 DD 1416 ingest | shipped | `pe_execution` table, 79,677 rows, 381 source documents |
| T6 Execution UI | shipped | `execution_waterfall()` on the Funding profile tab |
| T7 Test suite | shipped | `tests/`, `.github/workflows/ci.yml` |
| Tab-selection bug | fixed 2026-09-09 | stable `st.tabs(default=, key=, on_change=)`; see `AGENTS.md` |
| T8a Reconciliation core | shipped | `analysis/reconcile.py`; commit `9bc1a9d` |
| T8b Reconciliation panel | shipped | "Does it tie?" on Data Coverage; commit `a305624`, merged `4a2ad55` |
| T9a Procurement schema | shipped | `ProcurementLine` in `storage/db.py`; commit `a7acdbf` |
| T9b P-1 parser | shipped | `parse_p1()` in `parsing/xlsx_ingest.py`; commit `f8a5482` |
| T9b2 P-1 row identity | shipped | eleven-column key; commit `922e9f3` |
| T9c P-1 ingest | shipped | `storage/ingest_p1.py`, 5,253 rows, archive rebuilt; commit `8251542` |
| T9d Procurement coverage | shipped | Data Coverage metric; commit `ce5ee0b` |
| T11a Lineage schema + BA renumbering | shipped | `PELineage`, `analysis/lineage.py::detect_ba_renumbering`; commit `9dcbc34`, merged `783d80e` |
| T11b Narrative transfer language | shipped | `analysis/lineage.py::detect_narrative_transfers`, 431 edges on the shipped database; commit `8eb6195`, merged `9eec75b` |
| T13a Change feed core | shipped | `analysis/changefeed.py`; PB2026 vs PB2027 yields 483 swings, 49 terminations, 44 new starts; commit `15edd75` + fixup `a656ca6`, merged `6722bc9` |
| T11c Lineage golden set, ingest, eval | shipped | `analysis/lineage_golden.json`, `analysis/lineage_eval.py` (recall 10/10, precision 10/11, 421 unlabelled), `storage/ingest_lineage.py`; `pe_lineage` 0 -> 433; commit `6228a7d` |
| T13b Change feed surface | shipped | "What changed" on Budget Trends, `scripts/export_changefeed.py` (576 events PB2026 -> PB2027, all fields validated); permalinks and selector edge cases clicked through; commit `fc91681` |
| T11d Lineage in the funding chart | shipped | `TrendTracker.get_pe_history_with_lineage()`, segments + seam rules + evidence expanders on Program Finder → Funding; clicked through on PE 0603216F and 0609345A; commit `af48a3f` |
| T11e Lineage PE validation | shipped | both detectors reject unknown endpoints (11 predecessor, 17 successor); `pe_lineage` 433 -> 405; dictionary and handoff updated. Codex commits `b1a3885` + `9ed1af8` (on `origin/codex/t11e`); landed on main as `6030a08` (squashed by a failed working-tree update) + archive restore `d374360` |
| T12a Data dictionary | shipped | `DATA_DICTIONARY.md`, 13 tables validated against archive PRAGMA with 0 mismatches; commit `e32d3d7` |
| T12b Release bundle script | shipped | `scripts/build_release.py` verifies the tracked archive and writes `release/usg-budgets-<date>/` (35 files, manifest matches the dictionary); commit `9fa7f1f` |
| T14a Local retrieval over narratives | shipped | `analysis/narrative_qa.py`, tracked 26,702-passage index (51 MB with text), eval 5/5 gated at ~14 ms/query; commit `bbfec92` |
| T14b Cited synthesis | shipped | `narrative_answer` task on the governed path, `validate_answer` enforces verbatim quotes, 6 governance checks (57/57); commit `3bb54cc` |
| T14c Ask-the-corpus UI | shipped | "Ask the justification books" expander on Program Finder; key-less path verified by AppTest and browser; cold/warm AI paths verified live (one call, $0.0135, 2,491 thinking tokens); commit `f1088cb` |
| T15a Structured-fact schema | shipped | `NarrativeFact` + `narrative_fact_hash()` in `storage/db.py`, compatibility test proves `create_all` adds the table to an existing DB; docs updated; commit `d15874f` |
| T15b Batch extraction job | shipped | `analysis/narrative_extract.py` + `narrative_extractions` ledger; 50 narratives -> 25 verbatim-verified facts for $0.0396 (thinking capped); archive 15 tables; commits `f23ad7f` + `5f32ac6`, merged as a merge commit after a failed fast-forward |
| T10b Transition candidates + golden set + eval | shipped | `analysis/transition.py` (NARRATIVE/FUZZY/SEMANTIC + research rule), 20-case golden set, recall@3 16/16, negatives 4/4, 55 ms/query; commit `38ae87a` |
| T10c Transition panel | shipped | "Did it transition to procurement? (inference)" on Program Finder → Funding, `procurement_sources()` provenance; AppTest covers F-15EX, a research PE, and an empty case; browser-verified; commit `b3d69ba` |
| T14d Thinking budget for cited answers | shipped | shared `_generate_with_thinking` helper; `narrative_answer` capped at 1,024 thinking / 2,048 output; live check 464 thinking tokens, $0.0057 vs $0.0135 baseline, 4 cited sentences; commit `1cbd764` |
| T15c Verified facts panel | shipped | "Verified facts (N) … (inference)" on Plans & Work with honest coverage (50 of 4,988), Data Coverage caption, three-state AppTest; browser-verified; commit `149c314` |
| T16a | **open** | Vocabulary, density, and theme pass (Phase H, spec written 2026-09-20). T16b (multipage restructure) to be specced after T16a ships. |

Database ground truth, queried 2026-09-09:

| Table | Rows | Key columns and units |
|---|---|---|
| `program_elements` | 2,131 | `pe_number`, `agency`, `program_name`, `budget_activity` |
| `funding_lines` | 55,652 | `fiscal_year`, `funding_type`, `amount_thousands`, `pb_cycle` (1998–2027) |
| `pe_execution` | 79,677 | `fy_start`, `report_date`, `request_k`, `enacted_k`, `above_threshold_reprog_k`, `below_threshold_reprog_k`, `net_k` |
| `pe_congressional_actions` | 26,544 | `chamber`, `fiscal_year`, `request_k`, `committee_delta_k`, `authorized_k`, `rationale` |
| `pe_narratives` | 18,268 | `fiscal_year`, `project_number`, `description`, `source_file` |
| `pe_accomplishments` | 101,219 | `year_label`, `accomplishment_fy`, `funding_millions`, `text` |
| `source_documents` | 410 | `document_type` ∈ {`R1`, `DD1416`}, `source_url`, `content_hash` |

`funding_type` has exactly six values: `PY Actual`, `CY Request`, `BY Request`, and the
`Mandatory` variant of each. Nothing else. Amounts are **thousands** unless the column
says `_m` or `_millions`.

---

## 2. Conventions every task inherits

- New tables are SQLAlchemy 2.0 declarative models in `storage/db.py`, with a
  `content_hash` column and an `ingested_at` default, matching `PEExecution`.
- New analysis modules expose plain functions or one class that takes a `Session`; no
  Streamlit imports outside `app.py`.
- New UI goes into the tab named in the task, appended after existing content, wrapped in
  `st.expander` or `st.subheader` so the tab's current layout is untouched.
- Every figure shown gets `render_provenance(...)` and every table gets
  `render_table_downloads(...)`. Both helpers already exist in `app.py`.
- Tests go in `tests/test_<module>.py`. A parser task ships a fixture under
  `tests/fixtures/` small enough to read by eye.
- Row counts before and after an ingest go in the commit message.
- Any task that rebuilds `data/processed/usg_budgets.db.gz` also updates
  `DATA_DICTIONARY.md` (T12a): the row-count table, every enumeration count that changed,
  and the archive blob hash and commit in its header. The dictionary must never disagree
  with the shipped archive. List it in the task's file list.

---

## Phase C — Trust layer

### T8a — Reconciliation core

**Files:** new `analysis/reconcile.py`, new `tests/test_reconcile.py`.
**Depends on:** nothing.
**Revised 2026-09-10** after Codex correctly stopped: the first version of this task
named a file that does not exist and a "Total" row the workbook does not print.

**Get the source files first.** Raw exhibits are gitignored, so a fresh clone has none.
Download the official R-1 workbooks (FY2012 onward exist; earlier years are PDF-only):

```bash
python acquisition/comptroller_scraper.py --xlsx --years 2027 2026 2025 2024 --exhibits rdtee
```

They land at `data/raw/comptroller/{FY}/rdtee/fy{FY}_r1.xlsx`. The `{FY}` in the path is
the **PB cycle** (the submission year), which is `funding_lines.pb_cycle`.

**Workbook structure [verified 2026-09-10 on fy2027_r1.xlsx]:**
- Sheet `Exhibit R-1` holds everything; the per-column sheets repeat it.
- Row 0 is a single **DoD-wide** total: cell G0 reads `Total of Displayed Rows` and each
  amount column carries the sum of every row below it. There are **no per-component
  total rows.**
- Row 1 is the header. Columns: `Account` (e.g. `2040A`), `Account Title`,
  `Organization`, `Budget Activity`, `Budget Activity Title`, `Line Number`, `PE/BLI`,
  `Program Element/Budget Line Item (BLI) Title`, `Include In TOA`, then the amount
  columns, then `Classification`.
- Amount columns name the year, the stream, and the basis, for example
  `FY 2025 Actuals` (discretionary), `FY 2025 Reconciliation` (mandatory),
  `FY 2026 Discretionary Enacted`, `FY 2026 PL 119-21 Spend Plan` (mandatory),
  `FY 2027 Discretionary Request`, `FY 2027 Mandatory Request`, and a `FY … Total` for
  each year. Map them **by header text**; older cycles use different wording for the
  mandatory column and some have none.
- Amounts are thousands of dollars, stored as strings; blank means no line, not zero.

**Reference figures.** Two, both read fresh from the workbook and never from memory:
1. **Grand total**: the printed `Total of Displayed Rows` value for the column
   (DoD-wide, per fiscal year, stream, and basis).
2. **Per-account sum**: your own sum of the rows in that column grouped by `Account`.
   Verified 2026-09-10 that the per-account sums add exactly to the printed grand total
   for `FY 2027 Discretionary Request` (219,868,448).

**Types:**

```python
from dataclasses import dataclass
from typing import Literal

Stream = Literal["discretionary", "mandatory"]
Basis = Literal["PY Actual", "CY Request", "BY Request"]
TieStatus = Literal["ties", "outside_tolerance", "no_reference"]

@dataclass(frozen=True)
class TieOutRow:
    pb_cycle: int               # workbook / funding_lines.pb_cycle
    fiscal_year: int            # the column's year
    scope: str                  # "DoD" for the grand total, else an Account code like "2040A"
    agency: str | None          # program_elements.agency for the six ingested accounts, else None
    stream: Stream
    basis: Basis
    ingested_k: float           # sum of funding_lines.amount_thousands for this key
    reference_k: float | None   # workbook figure; None when the workbook is absent
    residual_k: float | None    # ingested - reference
    residual_pct: float | None
    status: TieStatus
    explanation: str            # required when status != "ties"

def tie_out_r1(session, raw_dir: Path, *, tolerance_pct: float = 0.5) -> list[TieOutRow]: ...
def tie_out_dd1416(session, *, tolerance_pct: float = 0.5) -> list[TieOutRow]: ...
```

**Known residuals to model, not hide [verified 2026-09-10, PB2027 workbook vs. database]:**
- The ingest keeps only the six RDT&E appropriation accounts (`2040A`, `1319N`, `3600F`,
  `3620F`, `0400D`, `0460D`). The workbook also lists `0130D`, `0390D`, `3007D`, and
  `0107D`. For `FY 2027 Discretionary Request` those four sum to exactly the residual
  (1,474,811 of 219,868,448). Emit them as their own `scope` rows with
  `explanation="account not ingested (non-RDT&E appropriation)"` and exclude them from the
  DoD-scope comparison so that row can tie.
- `FY 2025 Actuals`: database 142,654,463 vs. workbook 145,106,561. Part is the four
  accounts above; the rest must be enumerated per account, not absorbed into tolerance.
- `FY 2026 PL 119-21 Spend Plan` (mandatory): database 44,365,621 vs. workbook
  65,462,721. This gap is too large to be the excluded accounts alone. **Report it with
  the per-account breakdown and stop**; do not change the ingest in this task.
- Classified lines. The workbook prints them as `PE/BLI = 9999999999`, title
  `Classified Programs`, one row per account. The ingest deliberately stores them with an
  **empty** `pe_number` and `program_name = "Classified Programs"` (see
  `parsing/xlsx_ingest.py`, the `startswith("999")` branch); the database holds five such
  `program_elements` rows, one per component, and their `funding_lines` are real money.
  Sum `funding_lines` by account/agency **without filtering on `pe_number`**, so these
  rows are included on both sides and tie naturally. Do not add a name-based lookup and
  do not touch the parser.

**`tie_out_dd1416()`**: for each (`fy_start`, `agency`), compare the sum of
`pe_execution.enacted_k` from the latest `report_date` against the R-1
`CY Request` figure for that year from PB `fy_start + 1`. These are different documents
describing the same enacted amount, so a residual here is informative rather than a parse
error; report it and explain what you can.

**Definition of done:**
- `tie_out_r1()` returns one `scope="DoD"` row per (pb_cycle, fiscal_year, stream, basis)
  in every downloaded workbook, plus one row per Account code in that column.
- Workbooks that are not on disk produce `no_reference` rows for their pb_cycle, with
  the download command in `explanation`.
- Every `outside_tolerance` row has a specific `explanation`; "unknown" is acceptable
  only with the per-account figures attached.
- Tests: an in-memory SQLite with five hand-entered lines and a tiny hand-built workbook
  (write it with openpyxl inside the test, two accounts, one column) assert `status`,
  `residual_k`, and the excluded-account handling exactly; a second test asserts
  `no_reference` when the workbook path is missing.
- No change to any ingest or parser. The mandatory-stream gap is reported, not fixed.

**Verify:**
```bash
python -m pytest -q tests/test_reconcile.py
python - <<'PY'
from pathlib import Path
from storage.db import get_engine, get_session_factory
from analysis.reconcile import tie_out_r1
uri = "sqlite:///" + Path("data/processed/usg_budgets.db").resolve().as_posix()
Session = get_session_factory(get_engine(uri))     # same pattern app.py uses
with Session() as session:
    rows = tie_out_r1(session, Path("data/raw/comptroller"))
for r in rows:
    if r.scope == "DoD":
        print(r.pb_cycle, r.fiscal_year, r.stream, r.basis, r.status, r.residual_k)
PY
```
There is no DB URI constant in `config.py`; `app.py` builds the URI from its own path.

### T8b — Reconciliation panel

**Files:** `app.py` (Data Coverage tab only), `tests/test_app_smoke.py` (one new
assertion).
**Depends on:** T8a merged (it is: commit `9bc1a9d`, on `main` since 2026-09-10).

**What T8a found, so the panel says it plainly [verified 2026-09-10]:** for PB2027 every
DoD-scope row ties to zero once the four non-RDT&E accounts (`0130D`, `0390D`, `3007D`,
`0107D`) are excluded; the `reference_k` on a DoD-scope row is therefore the printed
grand total *minus* those accounts, and the caption must say so. The DD 1416 comparison
shows large residuals for early years (for example Air Force FY2012). Show them; they are
a finding, not a bug in the panel.

**Do:** add a "Does it tie?" section at the bottom of Data Coverage: one `st.dataframe`
per source (R-1, DD 1416) with columns FY, Component, Stream, Basis, Ingested $K,
Published $K, Residual $K, Residual %, Status, Explanation. Colour nothing; use the
`Status` column text. A `st.caption` above the table states the tolerance in percent.

**Definition of done:**
- The panel renders with the shipped database and every row has a non-empty `Status`.
- Rows with `outside_tolerance` show their `Explanation`; none are filtered out.
- `render_table_downloads` is wired for each table with the R-1 or DD 1416 sources.
- `tie_out_r1()` needs the raw directory: pass
  `Path(__file__).parent / "data" / "raw" / "comptroller"`. On the hosted app that
  directory is empty, so every R-1 row is `no_reference`; the panel must still render and
  its caption must say the workbooks are not shipped with the app.
- Wrap both calls in `@st.cache_data(ttl=3600)` helpers like `fetch_coverage_stats()`;
  the R-1 tie-out opens workbooks and must not run on every rerun.
- `tests/test_app_smoke.py` still passes; add an assertion that the Data Coverage tab
  contains the text "Does it tie".
- Clicked through in a browser; the Data Coverage tab is still the fourth tab.

**Verify:**
```bash
python -m pytest -q
python -m streamlit run app.py --server.headless true --server.port 8501
```

---

## Phase D — P-1 procurement

### T9a — Procurement schema

**Files:** `storage/db.py`, `tests/test_regressions.py` (one new test).
**Depends on:** nothing.

**Do:** add the table. No ingest yet.

```python
class ProcurementLine(Base):
    __tablename__ = "procurement_lines"
    id: Mapped[int]                       # PK
    source_document_id: Mapped[int]       # FK source_documents.id
    bli: Mapped[str]                      # String(50)  Budget Line Item, e.g. "9670A00005"
    line_item_title: Mapped[str]          # String(500)
    agency: Mapped[str]                   # String(100) same vocabulary as program_elements.agency
    appropriation: Mapped[str]            # String(100) e.g. "Aircraft Procurement, Army"
    budget_activity: Mapped[int | None]
    fiscal_year: Mapped[int]
    funding_type: Mapped[str]             # String(50)  same six values as funding_lines
    amount_thousands: Mapped[float]
    quantity: Mapped[float | None]        # units; None when the exhibit prints none
    pb_cycle: Mapped[int]
    content_hash: Mapped[str]             # String(64) sha256 of the natural key + amount
    ingested_at: Mapped[datetime]
    __table_args__ = (UniqueConstraint("bli", "agency", "appropriation", "fiscal_year",
                                       "funding_type", "pb_cycle", "source_document_id"),)
```

**Definition of done:** `_ensure_schema_compatibility()` creates the table on an existing
database without touching other tables; a test opens an in-memory engine, creates the
schema, inserts one row, and reads it back.

**Verify:** `python -m pytest -q`

### T9b — P-1 parser

**Files:** `parsing/xlsx_ingest.py`, new `tests/fixtures/p1_fy2027_sample.xlsx`
(≤ 40 rows cut from the real file), new `tests/test_p1_parser.py`.
**Depends on:** nothing (can run parallel to T9a).

**Do:** a function that reads a `p1_display.xlsx` and yields typed records.

```python
@dataclass(frozen=True)
class P1Record:
    bli: str
    line_item_title: str
    agency: str
    appropriation: str
    budget_activity: int | None
    fiscal_year: int
    funding_type: str          # one of the six funding_type values
    amount_thousands: float
    quantity: float | None
    add_non_add: Literal["Add", "Non-Add"]

def parse_p1(path: Path, *, pb_cycle: int) -> Iterator[P1Record]: ...
```

Map columns **by header text**, never by position (the DD 1416 files taught this).

**Definition of done:**
- Fixture parses to the exact list of records written by hand in the test.
- `Non-Add` rows are yielded (the ingest filters them; the parser stays faithful).
- Mandatory-scenario columns become `*Mandatory` funding types, never summed into
  discretionary.
- A malformed header raises `ValueError` naming the missing header. No silent skip.
- `RDTEE_ACCOUNT_RE` is not reused for procurement account matching.

**Verify:** `python -m pytest -q tests/test_p1_parser.py`

### T9b2 — Carry P-1 cost type through the parser and schema

**Files:** `storage/db.py`, `parsing/xlsx_ingest.py`, `tests/test_p1_parser.py`,
`tests/test_regressions.py`, `tests/fixtures/p1_fy2027_sample.xlsx` (only if the sample
lacks a BLI with more than one Add cost type).
**Depends on:** T9a and T9b merged (they are: `a7acdbf`, `f8a5482`).

**Why this task exists [verified 2026-09-12 on fy2026_p1.xlsx and fy2027_p1.xlsx]:**
the T9a uniqueness key `(bli, agency, appropriation, fiscal_year, funding_type, pb_cycle,
source_document_id)` collides on real data: FY2026 has 2,589 Add records but 2,393
distinct keys (116 collide); FY2027 has 2,664 and 2,454 (123 collide). The colliding rows
differ only in the workbook's `Cost Type` / `Cost Type Title` columns, which the T9a schema
and the T9b `P1Record` both dropped. They are the components of full funding, not
duplicates:

| Code | Title | Meaning |
|---|---|---|
| `A` | Weapon System Cost | the line's main cost; carries the unit `Quantity` |
| `B` | Less: Advance Procurement (PY) | negative; money appropriated in an earlier year |
| `C` | Advance Procurement (CY) | this year's money for future-year units |
| `E` | Less: Subsequent Full Funding (FY) | negative; shipbuilding |
| `G` | Less: Future Completion of Shipbuilding (FY) | negative; shipbuilding |
| `L` | Subsequent Full Funding for FY *yyyy* | shipbuilding completion money |
| `N` | Completion PY Shipbuild for FY *yyyy* | shipbuilding completion money |
| blank | blank | 7 Add rows in FY2026 print no cost type |

The `Add` rows for one BLI sum to that BLI's appropriation, so summing is arithmetically
legal, but it hides advance procurement (the single most useful transition signal for T10)
and it is **not** legal for quantities: in FY2026, 42 colliding keys carry a quantity on
more than one cost-type row. Aggregating would double count ships. Keep the rows.

**Second finding, after Codex correctly stopped on the first revision of this task
[verified 2026-09-12]:** cost type alone leaves 34 (FY2026) and 40 (FY2027) colliding
Add records, and adding the title still leaves 22 and 28. None of those are duplicate
amounts. They are the **same BLI code printed under several budget activities and line
numbers within one account** — the P-1 analogue of the R-1 rule in `CODEX_HANDOFF.md`
invariant 4. Example, FY2026 account `3010F`, BLI `F015EX` (F-15EX), cost type `A`:

| Budget Activity | Line Number | BSA | BSA Title |
|---|---|---|---|
| 01 Combat aircraft | 7 | 03 | Tactical Forces |
| 05 Modification of inservice aircraft | 44 | 02 | Tactical Aircraft |
| 07 Aircraft support equipment and facilities | 112 | 02 | Post Production Support |
| 07 Aircraft support equipment and facilities | 134 | 05 | Other Production Charges |

Grouping Add rows by `(Account, BLI, Cost Type, Cost Type Title)` plus **`Line Number`**
gives **zero** collisions in both workbooks. Plus `(Budget Activity, BSA)` also gives zero.
`BSA` alone does not (4 left in each year). `Line Number` is the workbook's own row
identity within an account, exactly as it is for the R-1 and the committee reports, so it
goes in the unique key; `BSA` is the stable cross-cycle identity, so it is stored too.

**Do:**
- `ProcurementLine`: add
  `line_number: Mapped[str] = mapped_column(String(10))`,
  `bsa: Mapped[str] = mapped_column(String(10))`,
  `bsa_title: Mapped[str] = mapped_column(String(200))`,
  `cost_type: Mapped[str] = mapped_column(String(10))`, and
  `cost_type_title: Mapped[str] = mapped_column(String(200))`.
  Replace the `UniqueConstraint` with
  `("bli", "agency", "appropriation", "budget_activity", "line_number", "cost_type",
  "cost_type_title", "fiscal_year", "funding_type", "pb_cycle", "source_document_id")`.
  `cost_type_title` is load-bearing, not decorative: shipbuilding completion lines share
  cost type `N` under one line number and differ only by the year in the title
  (FY2026 account `1611N`, line 8: "Completion PY Shipbuild for FY 2015", "... FY 2016",
  "... FY 2017"). Without the title the key collides on 12 records in each workbook
  [verified 2026-09-12 by Codex, confirmed against the earlier grouping that included it].
  Store blanks as `""`, never `NULL`: SQLite treats every `NULL` as distinct inside a
  UNIQUE constraint, which would silently let duplicates in. `budget_activity` is already
  nullable; a row with no budget activity must therefore also be rejected by the parser
  with a `ValueError` naming the row, so the key never contains a `NULL`.
  `_ensure_schema_compatibility()` must add the five columns to an existing
  `procurement_lines` table (it is empty everywhere today, so no backfill is needed).
- `P1Record`: add `line_number: str`, `bsa: str`, `bsa_title: str`, `cost_type: str`,
  `cost_type_title: str`. `parse_p1()` reads them from the `Line Number`, `BSA`,
  `Budget SubActivity (BSA) Title`, `Cost Type`, and `Cost Type Title` headers, mapped by
  header text like the rest. A missing header raises `ValueError` naming it, matching T9b.
  Keep `line_number` as the printed string (`"7"`, not `7`), matching
  `PECongressionalAction.line_number`.
- `content_hash` for a procurement row must include `line_number`, `cost_type`, and
  `cost_type_title`.

**Definition of done:**
- Over both real workbooks, grouping Add records by the new key yields zero collisions.
  Put the check in `tests/test_p1_parser.py` against the fixture, and paste the two-workbook
  result in the report. This was verified to be zero on 2026-09-12 with the key above; if
  it is not zero for you, the parser is reading a column wrong — stop and report the rows.
- The existing T9b parser test still passes with the two new fields added to its expected
  records.
- The T9a round-trip regression test inserts three rows: two that differ only in
  `cost_type`, and one that differs from the first only in `line_number` (same BLI, a
  different budget activity). All three read back. A fourth insert that repeats a full key
  raises `IntegrityError`.
- The fixture contains at least one BLI that appears under two budget activities and one
  BLI with `A` and `B` cost-type rows; the parser test asserts both by hand-written
  expected records.
- No aggregation anywhere. No change to `storage/ingest_p1.py` (it does not exist yet).

**Verify:**
```bash
python -m pytest -q tests/test_p1_parser.py tests/test_regressions.py
python -m pytest -q
```

### T9c — P-1 ingest script

**Files:** new `storage/ingest_p1.py`.
**Depends on:** T9a, T9b, and T9b2 merged.

**Do:** mirror `storage/ingest_dd1416.py`: parse every workbook first, validate, then one
write transaction; idempotent per `source_document`; record `source_url`, `retrieved_at`,
`content_hash` in `source_documents` with `document_type="P1"`. CLI:
`python -m storage.ingest_p1 --years 2026 2027 [--download]`.

**Definition of done:**
- FY2026 and FY2027 ingested; `Add` rows only; one database row per workbook cost-type
  row (see T9b2), quantities preserved per row and never summed across cost types.
- A spot-check row named in the commit message ties to the spreadsheet cell, including
  its `cost_type`. Also name one BLI with an `A` and a `B` row and show that the sum of its
  Add rows equals the workbook's total for that BLI and column.
- `content_hash` is sha256 over the full eleven-column key plus `amount_thousands` and
  `quantity` (T9b2 deferred hash generation to this task because the ingest did not exist).
- Re-running the command inserts zero new rows.
- Row counts for `procurement_lines` and `source_documents` before/after in the commit
  message.
- `python -m storage.build_archive` run afterwards and the `.db.gz` committed.

**Verify:**
```bash
python -m storage.ingest_p1 --years 2026 2027 --download
python -m storage.ingest_p1 --years 2026 2027          # must report 0 inserted
python -m pytest -q
```

### T9d — Procurement coverage in the UI

**Files:** `app.py` (Data Coverage tab), `fetch_coverage_stats()`.
**Depends on:** T9c merged.

**Do:** add a "Procurement lines" metric and a one-line caption stating the fiscal years
covered. Nothing else in the UI yet.

**Definition of done:** metric shows the real count; caption reads from the database, not
a constant; smoke test still passes.

### T10a — Transition golden set

**Status: done by Claude on 2026-09-19; no Codex task.** The original plan was twenty
hand-researched transitions with web URLs. The corpus turned out to contain its own
evidence, verified by query against the shipped database, so the golden set is specified
in full under T10b and Codex commits it verbatim. Two evidence classes:

- **Explicit BLI citations.** R-2 accomplishment text sometimes names the procurement line
  by code ("reprogrammed to the Weapons Procurement, Navy (WPN) appropriation (BLI
  2280)"). Regex `\bBLI\s*#?\s*:?\s*([A-Z0-9]{2,12})\b` over `pe_accomplishments.text`
  finds 9 mentions; 8 resolve to a code present in `procurement_lines.bli`; 6 distinct
  `(pe_number, bli)` pairs across 5 Navy PEs. (SQLite `LIKE '%BLI%'` matches 5,142 rows
  only because LIKE is case-insensitive and matches "public"; do not use it.)
- **Identical titles.** 54 RDT&E program names normalise (`matching.normalizer.
  normalize_program_name`) to exactly one P-1 `line_item_title` in the same agency, after
  excluding the "Classified Programs" rows. These are the same programme by name: F-15EX,
  Collaborative Combat Aircraft, Compass Call, DDG-1000, Paladin PIM, PrSM, AMPV, GBSD,
  GPS III, JDAM, Next Generation Jammer, and so on.

Negatives are basic-research PEs (`0601…`) that never buy hardware.

### T10b — Transition candidate generator, golden set, and eval

**Files:** new `analysis/transition.py`, new `analysis/transition_golden.json`, new
`analysis/transition_eval.py`, new `tests/test_transition.py`. Do not touch
`matching/`, `app.py`, or the archive.
**Depends on:** T9c (P-1 ingest) and T14a (the shared embedding model loader) merged;
both are.
**Rewritten 2026-09-19** against the repo: the original spec assumed the program matchers
could be pointed at P-1 titles (they cannot; both are bound to `program_elements` in
their constructors) and had no golden set to evaluate against.

**Verified facts (shipped database, 2026-09-19):**

- `procurement_lines`: 5,253 rows, 933 distinct `bli`, 918 distinct `line_item_title`,
  agencies `Air Force`, `Army`, `Defense-Wide`, `Marine Corps`, `Navy`, `Space Force`;
  24 appropriations. **BLI codes are not unique across appropriations**: 15 of 933 codes
  appear under more than one (Navy 4-digit codes especially). A candidate's identity is
  `(bli, appropriation)`, never `bli` alone.
- Code shapes vary by service: 4-digit Navy (`2280`), 6-character Air Force (`F015EX`,
  `CCA000`), 10-character Army (`2073GZ0410`), 2-digit Defense-Wide (`09`, `14`). The
  regex above covers all of them; validate a captured code by membership, not shape.
- Cross-service procurement: Navy RDT&E can buy under Marine Corps procurement, Air Force
  under Space Force and back. Allowed P-1 agencies per RDT&E agency:
  `{"Navy": ("Navy", "Marine Corps"), "Air Force": ("Air Force", "Space Force"),
  "Space Force": ("Space Force", "Air Force"), "Army": ("Army",), "Defense-Wide":
  ("Defense-Wide",)}`.
- `matching.fuzzy_matcher.ProgramMatcher` and `matching.semantic_matcher.SemanticMatcher`
  take a session and index `program_elements`; they are not reusable for P-1 titles.
  Reuse their ingredients instead: `rapidfuzz.process.extract` with `fuzz.WRatio` plus a
  `fuzz.token_set_ratio` sanity floor (the program matcher uses 60), and the sentence
  transformer from `analysis.narrative_qa._load_model()` (already cached per process,
  `local_files_only`). Encoding 918 short titles takes about 3 s on CPU; cache the
  matrix in-process with `functools.lru_cache` keyed on nothing (the P-1 table changes
  only at ingest), never on disk.
- Evidence sentences: split text on `(?<=[.!?])\s+` (the T14a rule) and cite the sentence
  containing the match, with the row's `source_file`.

**API (`analysis/transition.py`):**

```python
@dataclass(frozen=True)
class TransitionCandidate:
    pe_number: str; agency: str
    bli: str; appropriation: str; line_item_title: str; p1_agency: str
    confidence: float           # 0-1
    strategy: str               # "NARRATIVE" | "FUZZY" | "SEMANTIC"
    evidence_text: str | None   # verbatim sentence for NARRATIVE; None otherwise
    evidence_source: str | None # source_file for NARRATIVE; None otherwise
    ambiguous: bool             # runner-up within 0.1 of this candidate

CONFIDENCE_FLOOR = 0.6
def bli_mentions(session, pe_number, agency) -> list[tuple[str, str, str]]: ...   # (code, sentence, source_file) from pe_narratives + pe_accomplishments for that PE, any FY
def propose_transitions(session, pe_number: str, agency: str, *, limit: int = 5) -> list[TransitionCandidate]: ...
```

**Rule 0 — research budget activities never transition directly.** Digits 3–4 of a PE
number encode its budget activity; `pe_number[2:4] in ("01", "02")` is basic or applied
research (BA 1 and BA 2), which by appropriation law cannot buy production units. Expose
`RESEARCH_BUDGET_ACTIVITIES = ("01", "02")` and `is_research_pe(pe_number) -> bool`, and
have `propose_transitions` return `[]` for such PEs before running any strategy (T10c
shows a caption naming the rule). **Added 2026-09-20 after Codex correctly stopped:** with
the thresholds below, `Defense Research Sciences` matched `Base Defense Systems (BDS)`
(WRatio 85.5, token_set_ratio 60.87) and `Tactical Technology` matched `Tactical Vehicles`
(cosine 0.766). Short titles collide; the thresholds stay where they are because the
identical-title positives need them, and the research rule is the honest exclusion. The
eval docstring must say the four negatives are satisfied by this rule, so what the
negatives test is the rule's coverage, not the matchers' precision.

Strategies, each producing candidates keyed by `(bli, appropriation)`:

1. **NARRATIVE** (0.95): each `bli_mentions` code that exists in `procurement_lines` for an
   allowed agency. One candidate per matching `(bli, appropriation)`; the evidence is the
   citing sentence and its `source_file`.
2. **FUZZY**: `process.extract(normalize_program_name(program_name), choices=<normalised
   distinct titles for allowed agencies>, scorer=fuzz.WRatio, score_cutoff=85, limit=10)`,
   dropping hits with `fuzz.token_set_ratio < 60`; confidence `min(score / 100, 0.99)`.
3. **SEMANTIC**: cosine between the program name and each title's embedding
   (`normalize_embeddings=True`); keep cosine ≥ 0.6 as confidence.

Merge by key taking the highest confidence and its strategy; drop anything under
`CONFIDENCE_FLOOR`; sort by confidence descending then `bli`; mark `ambiguous=True` on
the top candidate when the second is within 0.1, and on any adjacent pair within 0.1;
return `limit`. A PE whose `program_name` starts with "Classified" returns `[]`. Query
time after model load must be under 1 s (918 titles).

**Golden set (`analysis/transition_golden.json`)**, a list of
`{"pe_number", "agency", "program_name", "label": "transition" | "no_transition",
"acceptable": [{"bli", "appropriation"}], "evidence_class": "bli_citation" |
"same_title" | "basic_research", "evidence_quote", "evidence_source", "note"}`.
For `bli_citation` cases copy `evidence_quote` verbatim from the `pe_accomplishments`
row that contains `BLI <code>` (query it; do not retype) and `evidence_source` from that
row; for the others `evidence_quote` and `evidence_source` are `null`. Exactly these
twenty cases:

| # | PE | Agency | Program | Acceptable (bli @ appropriation) | Class |
|---|---|---|---|---|---|
| 1 | 0604366N | Navy | Standard Missile Improvements | 2356 @ Weapons Procurement, Navy; 2234 @ Weapons Procurement, Navy | bli_citation |
| 2 | 0604258N | Navy | Target Systems Development | 2280 @ Weapons Procurement, Navy | bli_citation |
| 3 | 0603596N | Navy | LCS Mission Modules | 1600 @ Other Procurement, Navy | bli_citation |
| 4 | 0604777N | Navy | Navigation/ID System | 0840 @ Other Procurement, Navy | bli_citation (NRE realigned between the lines; note it) |
| 5 | 0603563N | Navy | Ship Concept Advanced Design | 1445 @ Other Procurement, Navy | bli_citation (installation funded from the line; note it) |
| 6 | 0207146F | Air Force | F-15EX | F015EX @ Aircraft Procurement, Air Force | same_title |
| 7 | 0207147F | Air Force | Collaborative Combat Aircraft | CCA000 @ Aircraft Procurement, Air Force | same_title |
| 8 | 0207253F | Air Force | Compass Call | CALL00 @ Aircraft Procurement, Air Force | same_title |
| 9 | 0204202N | Navy | DDG-1000 | 2119 @ Shipbuilding and Conversion, Navy | same_title |
| 10 | 0210609A | Army | Paladin Integrated Management (PIM) | 2073GZ0410 @ Procurement of Weapons and Tracked Combat Vehicles, Army | same_title |
| 11 | 0604274N | Navy | Next Generation Jammer (NGJ) | 0591 @ Aircraft Procurement, Navy | same_title |
| 12 | 0605028A | Army | Armored Multi-Purpose Vehicle (AMPV) | 2944G80819 @ Procurement of Weapons and Tracked Combat Vehicles, Army | same_title |
| 13 | 0605231A | Army | Precision Strike Missile (PrSM) | 8540C29600 @ Missile Procurement, Army | same_title |
| 14 | 0605230F | Air Force | Ground Based Strategic Deterrent | MGBSD0 @ Missile Procurement, Air Force | same_title |
| 15 | 1203265SF | Space Force | GPS III Space Segment | GPSIII @ Procurement, Space Force | same_title |
| 16 | 0604618F | Air Force | Joint Direct Attack Munition | 353620 @ Procurement of Ammunition, Air Force | same_title |
| 17 | 0601102A | Army | Defense Research Sciences | (none) | basic_research |
| 18 | 0601103A | Army | University Research Initiatives | (none) | basic_research |
| 19 | 0602702E | Defense-Wide | Tactical Technology | (none) | basic_research |
| 20 | 0601153N | Navy | Defense Research Sciences | (none) | basic_research |

**Eval (`analysis/transition_eval.py`, pattern `analysis/linker_eval.py`):** for each
case call `propose_transitions(session, pe, agency, limit=5)`; a `transition` case
passes when any acceptable `(bli, appropriation)` is in the top 3 (print the rank, the
strategy, and the confidence); a `no_transition` case passes when no candidate is
returned at or above `CONFIDENCE_FLOOR` (print the top candidate and confidence if one
slipped through). Print recall@3 over the 16 positives, negatives passed of 4, and the
per-class breakdown. **Exit 1 if recall@3 < 0.6 or any negative fails; print the numbers
honestly whatever they are.** State the expected result in the docstring after running
it. (The citation cases are found by the same regex that built the golden set, so their
recall is by construction; the value of the eval is the title cases, the negatives, and
regression protection. Say so in the docstring.)

**Tests (`tests/test_transition.py`, in-memory session seeded with a `SourceDocument`,
a few `ProgramElement` rows, `ProcurementLine` rows, and one `PEAccomplishment`; no
model needed for the first three):** exact-title FUZZY hit ranks first with confidence
≥ 0.95; a `PEAccomplishment` citing `BLI 2280` yields a NARRATIVE candidate with the
verbatim sentence and `source_file`; a basic-research PE with no similar title returns
`[]`; two titles within 0.1 of each other mark the top candidate `ambiguous`; a
"Classified Programs" PE returns `[]`; a `0601…` PE whose title exactly equals a seeded P-1
title still returns `[]` (the research rule precedes the strategies). The SEMANTIC strategy is covered by the eval, not
by unit tests, so the suite stays model-free.

**Definition of done:** the golden file holds exactly the twenty cases above with
verbatim quotes on the five citation cases; `python analysis/transition_eval.py` exits 0
and its docstring states the measured numbers; every candidate carries a strategy and a
confidence, NARRATIVE candidates carry evidence text and source; ambiguity is flagged;
`is_research_pe` is exported and BA 1/2 PEs return `[]`;
`python analysis/linker_eval.py` still passes 11/11 (nothing under `matching/` changed);
`python -m pytest -q` passes; no UI.

**Verify:**
```bash
python -m pytest -q
python analysis/transition_eval.py
python analysis/linker_eval.py
python -c "import sys, time; sys.path.insert(0,'.'); from storage.db import get_engine, get_session_factory; import config; from analysis.transition import propose_transitions; S=get_session_factory(get_engine(f\"sqlite:///{(config.PROCESSED_DIR/'usg_budgets.db').as_posix()}\")); s=S(); propose_transitions(s,'0207146F','Air Force'); t=time.perf_counter(); c=propose_transitions(s,'0207146F','Air Force'); print(f'{(time.perf_counter()-t)*1000:.0f} ms', [(x.bli, x.strategy, round(x.confidence,2), x.ambiguous) for x in c])"
```

### T10c — Transition panel

**Files:** `app.py` (Program Finder → Funding sub-tab, a new expander after the
"Underlying funding table" expander and before the Plans & Work sub-tab begins),
`analysis/provenance.py` (new `procurement_sources()` helper), `tests/test_regressions.py`
(one test in `ProvenanceRegressionTests`), `tests/test_app_smoke.py` (one new test).
**Depends on:** T10b merged (it is: commit `38ae87a`).
**Amended 2026-09-19:** the first version said "plus the P-1 source documents" without
naming a helper; none exists. Specify it:

```python
def procurement_sources(session, *, blis: Iterable[str] | None = None,
                        appropriations: Iterable[str] | None = None) -> list[dict]: ...
```

Mirror `execution_sources`: join `SourceDocument` through `ProcurementLine.source_document_id`,
filter `ProcurementLine.bli.in_(...)` and `ProcurementLine.appropriation.in_(...)` when given,
`distinct()`, ordered by `publication_year, filename`, returning the same six-key dicts. On the
shipped database with no filters it returns the 2 `P1` documents. Regression test: an in-memory
session with one `P1` `SourceDocument` and one `ProcurementLine` yields one source whose
`document_type == "P1"`, and `csv_with_provenance` on a one-row frame names its filename.
In the panel, pass `include_deflator_source(fetch_funding_sources(...)) +
procurement_sources(session, blis=[c.bli ...], appropriations=[c.appropriation ...])` to
`render_table_downloads`.

**Do:** `with st.expander("Did it transition to procurement? (inference)"):` a caption
stating this is a lead generator with no key join between RDT&E and procurement; call
`propose_transitions` (wrap in a `@st.cache_data(ttl=3600)` accessor keyed on PE and
agency; it returns dataclasses, so convert to dicts inside the accessor); if `is_research_pe(pe)`,
`st.caption("Basic and applied research (budget activities 1–2) cannot fund procurement, so no
transition is inferred.")`; else if empty,
`st.caption("No procurement line resembles this program's title, and no narrative cites
a BLI.")`; otherwise a `st.dataframe` with columns Line item, Appropriation, BLI,
Confidence (two decimals), Strategy, Ambiguous ("ambiguous" or ""), Evidence source, and
under it one `st.expander(f"Evidence: {bli}")` per NARRATIVE candidate holding the
verbatim sentence via `escape_dollars`. `render_table_downloads` on the table with the
program's funding sources plus the P-1 source documents (`document_type == "P1"`).

**Test:** `test_transition_panel_renders_inference_label(monkeypatch)`: `HF_HUB_OFFLINE=1`,
`default_timeout=120`, query params `tab=finder`, `pe=0207146F`, `agency=Air Force`; run;
assert an expander label contains "inference"; assert "F015EX" appears in a dataframe
within the Funding sub-tab; then `pe=0601102A`, `agency=Army` asserting the research
caption ("Basic and applied research"); then `pe=0605018F`, `agency=Air Force` (Air Force
Integrated Military Human Resources, a BA 6 PE verified on 2026-09-19 to return no
candidates) asserting the "No procurement line" caption; main tab labels unchanged.
**Corrected 2026-09-19** after Codex correctly stopped: the earlier text asked the
research PE to show the empty-result caption, which Rule 0 makes unreachable for it.

**Definition of done:** every candidate shows confidence, strategy, and (for NARRATIVE)
its evidence sentence; the expander title contains "inference"; ambiguous candidates show
the word "ambiguous"; no candidate renders without a strategy and a score; the smoke
test passes; clicked through in a real browser on PE 0207146F, PE 0601102A, and PE 0605018F, and
the Program Finder tab stays selected.

---

## Phase E — PE lineage

### T11a — Lineage schema and budget-activity renumbering detector

**Files:** `storage/db.py`, new `analysis/lineage.py`, new `tests/test_lineage.py`.
**Depends on:** nothing.
**Spec re-verified against the shipped database 2026-09-14** (see "Verified facts" below;
the earlier draft's "7-character PE" wording was wrong).

```python
Relation = Literal["renumbered", "split", "merged", "transferred"]

class PELineage(Base):
    __tablename__ = "pe_lineage"
    id: Mapped[int]
    predecessor_pe: Mapped[str]; predecessor_agency: Mapped[str]
    successor_pe: Mapped[str];   successor_agency: Mapped[str]
    relation: Mapped[str]              # Relation
    first_fy_after: Mapped[int]        # first FY the successor carries money
    evidence_text: Mapped[str | None]  # verbatim sentence, or None for series-only evidence
    evidence_source: Mapped[str | None]# source_file, or "funding_series"
    confidence: Mapped[float]          # 0–1
    method: Mapped[str]                # "ba_renumber" | "narrative" | "title_series"
    content_hash: Mapped[str]; ingested_at: Mapped[datetime]

@dataclass(frozen=True)
class LineageEdge:  # same fields as the model, minus id/ingested_at

def detect_ba_renumbering(session) -> list[LineageEdge]: ...
```

Model conventions: copy `PEExecution` — `content_hash` is `String(64)`, `unique=True`,
indexed; `ingested_at` defaults to `_utcnow`. `content_hash` is sha256 over
`predecessor_pe | predecessor_agency | successor_pe | successor_agency | relation | method`
joined with `|`. `_ensure_schema_compatibility()` already calls
`Base.metadata.create_all`, so a new table needs no migration code. No ingest in this
task; the detector only returns edges.

**Verified facts (query the DB yourself if in doubt):**

- `program_elements.pe_number` is 8, 9, or 10 characters: seven digits followed by a 1–3
  character suffix (`0602115A`, `0601384BP`, `0603941D8Z`). Five rows have a blank
  `pe_number` (classified aggregates) and eight rows have `agency = "Unknown"`; exclude
  both. Digits 3–4 are the budget activity. "Same PE except the budget activity" means
  positions 1–2 and 5–end are identical, positions 3–4 differ, and `agency` is equal.
- `funding_lines` has no `pe_number`; join through `program_element_id`. Use only
  `funding_type IN ('PY Actual','CY Request','BY Request')` with a non-null, nonzero
  `amount_thousands` when deciding whether a PE "carries money" in a fiscal year.
- **The digit rule alone is noise.** With the 8–10 character rule it yields 704 directed pairs, 19 of which abut under
  the vintage rule, and only two of those are real (next-best title score 52.6). A title gate is mandatory:
  `rapidfuzz.fuzz.token_set_ratio(normalize_program_name(a), normalize_program_name(b))`
  (from `matching.normalizer`) scores the two real cases at 100 and every false pair
  seen at or below 40. Use a threshold of 85 and make it a named module constant.
- **Abutment must be vintage-aware.** The known case below carries FY2026 under *both*
  PE numbers: `0609345A` has FY2026 as `BY Request` in `pb_cycle=2026`, and `0605345A`
  has FY2026 as `CY Request` in `pb_cycle=2027`. Define `last_fy(pred)` as the greatest
  funded FY across all vintages and `first_fy(succ)` as the smallest. Accept
  `first_fy(succ) - last_fy(pred)` of 0 only when the predecessor's observation of that
  FY comes from an older `pb_cycle` than the successor's; accept 1 unconditionally;
  accept 2 at reduced confidence (the DB has every `pb_cycle` 2006–2027, so a two-year
  gap means a year genuinely went unreported). Reject anything else. The predecessor must
  carry no money in any FY after `first_fy(succ)`.
- Confidence: 1.0 for gap 0 or 1 with title score 100; subtract 0.1 for gap 2; scale
  down linearly toward 0.6 as the title score falls to 85. Document the formula in the
  docstring.
- `first_fy_after` = `first_fy(succ)`. `evidence_source = "funding_series"`,
  `evidence_text = None`, `method = "ba_renumber"`, `relation = "renumbered"`.

**Known cases the detector must find** (name both in the commit message):

| Predecessor | Successor | Agency | `first_fy_after` | Note |
|---|---|---|---|---|
| `0609345A` | `0605345A` | Army | 2026 | "Unmanned Aerial Systems Launched Effects": BA 9 software pilot → BA 5; gap 0 across vintages |
| `0308609V` | `0307609V` | Defense-Wide | 2023 | "National Industrial Security Systems (NISS)": gap 2, reduced confidence |

**Definition of done:** `detect_ba_renumbering(session)` on the shipped database returns
both cases above and **no more than five edges in total** (print the full list in the
report; if a third edge appears, say whether you believe it and why); a unit test on an
in-memory SQLite session (pattern: `tests/test_reconcile.py::setUp`) builds one synthetic
abutting pair with matching titles and asserts exactly one `renumbered` edge with
`method="ba_renumber"`; a second test builds a pair that abuts but whose titles score
below 85 and asserts zero edges; a third test builds a PE whose funding simply stops,
with no successor, and asserts zero edges — **no edge is ever inferred from a funding
drop alone**. `python -m pytest -q` passes. Do not touch `app.py`.

**Verify:**
```bash
python -m pytest -q
python - <<'PY'
from storage.db import get_engine, get_session_factory
from analysis.lineage import detect_ba_renumbering
session = get_session_factory(get_engine("sqlite:///data/processed/usg_budgets.db"))()
for edge in detect_ba_renumbering(session):
    print(edge)
PY
```
(Run from `dod_ic_budget_analyzer/`; `app.py` builds the same URI from its own path.)

### T11b — Narrative transfer language

**Files:** `analysis/lineage.py`, `tests/test_lineage.py`, new
`tests/fixtures/lineage_sentences.json`.
**Depends on:** T11a merged (it is: commit `9dcbc34`, merged `783d80e` on 2026-09-15).
**Spec verified against the narrative corpus 2026-09-15.**

**Do:** `detect_narrative_transfers(session) -> list[LineageEdge]` scanning
`pe_narratives.description` and `pe_accomplishments.text`. Every edge carries the
verbatim sentence in `evidence_text` and the row's `source_file` in `evidence_source`,
with `method="narrative"` and `relation="transferred"`. Reuse `LineageEdge` and
`_content_hash` from T11a unchanged.

**Verified facts (counts are `LIKE` hits on the shipped database):**

- Both tables carry `pe_number`, `agency`, `fiscal_year`, `source_file`. Neither has a
  `program_element_id`.
- The phrasing that actually occurs, most common first: `realigned to PE X` (444),
  `realigned from PE X` (325), `transferred to PE X` (260), `transferred from PE X`
  (134), `consolidated from PE X` / `consolidated under PE X` / `consolidated into PE X`,
  `moved to PE X` (50), `moved from PE X` (29), `transferred to new PE X`. The noun is
  `PE`, `Program Element`, or `program element`, sometimes followed by `/Title` or
  `(Title)`. `merged into`, `split from`, and `renumbered` occur zero times; do not
  bother matching them.
- PE numbers cited in text are 8 characters 10,160 times, 9 characters 645 times, 10
  characters 23 times. Match `\d{7}[A-Z0-9]{1,3}` exactly as T11a's `_is_valid_pe_number`
  does; `matching/fuzzy_matcher.py::PE_NUMBER_IN_TEXT_RE` is the same shape.
- **Self-references are the main false positive.** Army FY2027 books say "This effort
  was consolidated from PE 0602144A (Ground Technology) / Project DI7 …" *inside* PE
  0602144A: a project moved within one PE. A cited PE equal to the row's own `pe_number`
  must never produce an edge.
- Direction: `from X` / `consolidated from X` makes X the predecessor and the row's PE
  the successor; `to X` / `into X` / `under X` / `to new X` makes the row's PE the
  predecessor and X the successor. Both `predecessor_agency` and `successor_agency` are
  the row's `agency` unless the sentence names another component (leave that case for
  later; record the row's agency and say so in the docstring).
- `first_fy_after`: take the first `FY ?20\d\d` or `FY ?\d\d` in the sentence
  ("in FY 2025", "Beginning in FY 2025", "starting in FY 2026", "For FY2026", "FY27");
  two-digit years are 2000-based. If the sentence names no year, use the row's
  `fiscal_year` and set confidence lower.
- Confidence: 0.9 when verb, direction, PE, and a year are all present; 0.7 when the
  year came from the row instead of the sentence.
- The same sentence recurs across files (the Defense-Wide volume and the per-agency
  book carry identical text). Deduplicate on `content_hash`, keeping the first
  `evidence_source` seen in `(source_file, id)` order.
- Sentence splitting: split on `. ` and newlines; R-2 text extracted from PDF sometimes
  embeds exhibit-header boilerplate ("Appropriation/Budget Activity R-1 Program Element
  (Number/Name) …") mid-sentence. Keep the sentence verbatim anyway; do not clean it.

**Fixture** (`tests/fixtures/lineage_sentences.json`, a list of
`{"pe_number", "agency", "fiscal_year", "source_file", "text", "expect_edges"}`) with
six sentences, three positive and three negative, adapted from the corpus:

1. positive, row PE 0603176BR: "Funds in program element 0603176BR Project RR were
   realigned to Project RR in PE 0603160BR during FY 2025 …" → 0603176BR → 0603160BR,
   `first_fy_after=2025`.
2. positive, row PE 0602146A: "This effort was consolidated from PE 0602182A (C3I
   Applied Research) / Project CX3 …" (no year) → 0602182A → 0602146A, confidence 0.7.
3. positive, row PE 0604XXXN (any valid Navy PE): "SLCM funds were transferred to new
   PE 0105519N starting in FY 2026." → row PE → 0105519N, `first_fy_after=2026`.
4. negative: "This effort was consolidated from PE 0602144A (Ground Technology) /
   Project DI7 …" with row PE 0602144A (self-reference).
5. negative: "Funds were transferred to the contractor in FY 2025 to accelerate
   integration." (no PE).
6. negative: "Project 016, Close Combat Lethality, moved to the Soldier Lethality Cross
   Functional Team." (no PE).

**Definition of done:** the fixture yields exactly three edges with the directions and
years above; every edge's `evidence_text` is a verbatim substring of the fixture text
(assert `evidence_text in text`); the regex set is listed in the module docstring; on the
shipped database the detector runs in under 60 s and the report prints the edge count
plus the first ten edges; `python -m pytest -q` passes; T11a's tests still pass
unchanged. Do not touch `app.py` or `storage/`.

**Verify:**
```bash
python -m pytest -q
python - <<'PY'
import time
from storage.db import get_engine, get_session_factory
from analysis.lineage import detect_narrative_transfers
session = get_session_factory(get_engine("sqlite:///data/processed/usg_budgets.db"))()
t0 = time.time(); edges = detect_narrative_transfers(session)
print(len(edges), "edges in", round(time.time() - t0, 1), "s")
for edge in edges[:10]:
    print(edge.predecessor_pe, "->", edge.successor_pe, edge.first_fy_after, edge.confidence, edge.evidence_text[:120])
PY
```

### T11c — Lineage golden set, ingest, and eval

**Files:** new `analysis/lineage_golden.json`, new `analysis/lineage_eval.py`, new
`storage/ingest_lineage.py`, new `tests/test_ingest_lineage.py`,
`data/processed/usg_budgets.db.gz` (rebuilt), `CODEX_HANDOFF.md` §1 (row count).
**Depends on:** T11b merged (it is: commit `8eb6195`, merged `9eec75b` on 2026-09-15).
**Revised 2026-09-15** after Codex correctly stopped: the first version was a bare
definition of done. It named no file for the archive, no golden-set schema, and no
evaluation universe. All three are specified below. The ignored working `.db` is mutated
by the ingest, as every ingest task does; that is expected, not a contradiction.
**Revised again 2026-09-15** after a second correct stop: one golden pair is emitted by
both detectors, so the eval counts distinct pairs (421 unlabelled, not 422), the
fiscal-year check accepts any detected edge for the pair, and the two funding-series
cases carry `evidence_quote: null`.

**Verified facts (shipped database, 2026-09-15):**

- `pe_lineage` exists in `storage/db.py` (T11a) and has **0 rows**. The two detectors
  return 2 edges (`detect_ba_renumbering`, `method="ba_renumber"`,
  `evidence_source="funding_series"`, `evidence_text=None`) and 431 edges
  (`detect_narrative_transfers`, `method="narrative"`), all 431 with distinct
  `(predecessor_pe, successor_pe)` pairs; 338 at confidence 0.9, 93 at 0.7. **One pair
  is emitted by both detectors:** `0609345A -> 0605345A` as `ba_renumber` (FY2026, from
  the funding series, `evidence_text=None`) and as `narrative` (FY2027, Army FY2027
  Vol 3 BA 5D: "This effort was realigned from PE 0609345A/ Project A46 beginning FY
  2027"). The two edges have different `content_hash` values. So: 433 raw edges, 432
  distinct pairs. The year disagreement is real evidence, not an error; the golden set
  records the funding-series year and notes the narrative one.
- Narrative `evidence_source` is the R-2 book filename the row came from
  (`af_fy2019_..._Vol_II_FY19.pdf`, `PB_2026_RDTE_VOL_5.xml`, 173 distinct). **None of
  them is registered in `source_documents`** (0 of 431 match `filename`; that table
  holds only `R1`, `DD1416`, `P1`), so no URL is recoverable from the database for a
  narrative edge. The service budget sites were also unreachable from this machine on
  2026-09-15 (Air Force TLS failure, Army 403, Navy WAF reject), so the URLs could not
  be hand-verified either. Do not invent them: `evidence_url` is `null` for narrative
  cases, and the verbatim quote plus the book filename is the evidence. The two
  funding-series cases carry the R-1 `source_documents.source_url` that is in the
  database. Registering R-2 books in `source_documents` is a separate task, not T11c.
- Cross-component transfers record the row's agency on both sides (T11b docstring). The
  Air Force to Space Force edge below therefore has `successor_agency="Air Force"` in
  detector output even though the true successor is Space Force; the eval matches on PE
  numbers only, and the golden case records the true agency with a note.
- One confirmed false positive exists: in the PE 0603030F narrative (AF FY2021 Vol I),
  the sentence "the entirety of PE 0603112F ... will be transferred to PE 0603030F ...
  with the exception of the Pervasive and Affordable Metals Technologies effort which
  will be transferred to PE 0602102F" yields `0603030F -> 0602102F`, but the predecessor
  is 0603112F. The two true edges (`0603112F -> 0603030F`, `0603112F -> 0602102F`) are
  detected from PE 0603112F's own narrative. Fixing the detector is T11b follow-up, not
  T11c; the golden set records the false positive so the eval measures it.

**Golden set** (`analysis/lineage_golden.json`): a list of cases, each
`{"predecessor_pe", "predecessor_agency", "successor_pe", "successor_agency", "relation",
"first_fy_after", "label", "method", "evidence_quote", "evidence_source", "evidence_url",
"note"}`. `label` is `"edge"` or `"no_edge"`. `evidence_quote` is verbatim from the
database row for narrative cases (copy it from `detect_narrative_transfers` output; do
not retype it) and `null` for the two funding-series cases, whose evidence is the
funding series itself (`evidence_text` is `None` on those edges).
Ten positives and two negatives, all hand-verified 2026-09-15 against the row text:

| # | Predecessor | Successor | FY | Method | Source | Note |
|---|---|---|---|---|---|---|
| 1 | 0603216F (AF) | 0603032F (AF) | 2021 | narrative | `af_fy2021_FY21_Air_Force_Research_Development_Test_and_Evaluation_Vol_I.pdf` | Skyborg Vanguard, "consolidated and transferred in FY 2021 from ... to" |
| 2 | 0306250F (AF) | 0208099F (AF) | 2019 | narrative | `af_fy2019_Air_Force_Research_Development_Test_and_Evaluation_Vol_II_FY19.pdf` | Unified Platform "transferred from"; quote begins with exhibit-header boilerplate, keep it verbatim |
| 3 | 0603830F (AF) | 1206730F (AF) | 2018 | narrative | same Vol II FY19 book | Space Security and Defense Program, new Major Force Program for Space |
| 4 | 0602705A (Army) | 0602146A (Army) | 2020 | narrative | `army_fy2020_02_RDTE_-_Vol_1_-_Budget_Activity_2.pdf` | "realigned from PE 0602705A ... in FY20"; sentence names three source PEs, this is the first |
| 5 | 0602184A (Army) | 0602143A (Army) | 2027 | narrative | `army_fy2027_RDTE_-_Vol_1_-_Budget_Activity_2.pdf` | "Funding realigned from Program Element (PE) 0602184A" |
| 6 | 0603758N (Navy) | 0603382N (Navy) | 2027 | narrative | `navy_fy2027_RDTEN_BA4_Book.pdf` | TANG "moved from PE 0603758N ... to PE 0603382N ... effective FY 2027" |
| 7 | 1206601F (AF) | 1206601SF (**Space Force**) | 2021 | narrative | AF FY2021 Vol I | Appropriation 3600 to 3620; detector records Air Force on both sides |
| 8 | 0603112F (AF) | 0603030F (AF) | 2021 | narrative | AF FY2021 Vol I | Advanced Materials for Weapon Systems into AF Foundational Development/Demos |
| 9 | 0308609V (DW) | 0307609V (DW) | 2023 | ba_renumber | `funding_series`; `evidence_url` = `https://comptroller.war.gov/budgetmaterials/budget2023.aspx` | NISS Software Pilot Program, BA 8 to BA 7, confidence 0.9 |
| 10 | 0609345A (Army) | 0605345A (Army) | 2026 | ba_renumber | `funding_series`; `evidence_url` = `https://comptroller.war.gov/budgetmaterials/budget2026.aspx` | UAS Launched Effects, BA 9 to BA 5, confidence 1.0; also emitted as `narrative` with FY2027 (see verified facts), so the FY check passes on the funding-series edge |
| N1 | 0603030F (AF) | 0602102F (AF) | 2021 | narrative | AF FY2021 Vol I | **no_edge**: the false positive described above |
| N2 | 0602144A (Army) | 0602144A (Army) | 2027 | narrative | any | **no_edge**: self-reference; a detector must never emit X -> X |

`relation` is `"transferred"` for narrative cases and `"renumbered"` for the two
funding-series cases. Fill `first_fy_after` from the table.

**Eval** (`analysis/lineage_eval.py`, pattern `analysis/linker_eval.py`): run both
detectors against the live database, reduce their output to **distinct
`(predecessor_pe, successor_pe)` pairs** (a pair emitted by both detectors counts once),
match golden cases on that pair only, and print one line per golden case (PASS/FAIL,
and for positives whether `first_fy_after` matched; the year check passes if **any**
detected edge for the pair has the golden year), then:

- recall = positives detected / positives;
- precision = detected pairs labelled `edge` / detected pairs whose pair is in the golden
  universe (positives plus negatives). Pairs outside the universe are **unlabelled, not
  scored**; print their count so coverage is stated, never implied;
- exit code 1 if recall < 1.0, else 0. Precision is printed, not gated.

Expected on the shipped database: 433 raw edges, 432 distinct pairs, recall 10/10,
precision 10/11 (N1 is emitted, N2 is not), 421 unlabelled pairs, 10/10 year checks.
State these numbers in the module docstring.

**Ingest** (`storage/ingest_lineage.py`, pattern `storage/ingest_p1.py` for `main()`):
`ingest_lineage(session) -> dict[str, int]` deletes every `pe_lineage` row whose `method`
is `ba_renumber` or `narrative`, inserts the current detector output, commits, and returns
`{"ba_renumber": n, "narrative": n, "total": n}`. `pe_lineage` is fully derived from
other tables, so replace-by-method is the idempotency rule: two consecutive runs leave an
identical row set and identical counts. `main()` takes `--database` (default
`config.PROCESSED_DIR / "usg_budgets.db"`), prints row counts before and after, and does
not build the archive itself.

**Test** (`tests/test_ingest_lineage.py`, pattern `tests/test_reconcile.py::setUp` with
an in-memory session): load `tests/fixtures/lineage_sentences.json` rows as T11b's tests
do, run `ingest_lineage` twice, and assert the row count is 3 both times and the set of
`content_hash` values is unchanged.

**Definition of done:** the golden file holds exactly the twelve cases above, verbatim
quotes on the ten narrative cases and `null` on the two funding-series cases; `python analysis/lineage_eval.py` prints the expected numbers and exits
0; `ingest_lineage` is idempotent by test and by two real runs (433 rows after each);
`python -m analysis.ai_budget --reset-runtime` then `python -m storage.build_archive`
run, the `.db.gz` committed, and the commit message states `pe_lineage` 0 -> 433;
`CODEX_HANDOFF.md` §1 "Tables" row gains the `pe_lineage` row count;
`python -m pytest -q` passes. Do not touch `app.py` or `analysis/lineage.py`.

**Verify:**
```bash
python -m pytest -q
python analysis/lineage_eval.py
python -m storage.ingest_lineage
python -m storage.ingest_lineage            # second run: identical counts
sqlite3 data/processed/usg_budgets.db "SELECT method, COUNT(*) FROM pe_lineage GROUP BY 1;"
python -m analysis.ai_budget --reset-runtime
python -m storage.build_archive
```

### T11d — Lineage in the funding chart

**Files:** `app.py` (Program Finder → Funding), `analysis/trend_tracker.py` (a
`get_pe_history_with_lineage()` that returns the same frame plus a `segment` column).
**Depends on:** T11c merged (it is: commit `6228a7d`, merged 2026-09-16).

**Definition of done:** when a selected PE has an edge, the chart draws the predecessor
and successor series in distinct segments with a visible seam (a rule mark at the FY) and
a caption naming both PEs and the relation; edges with confidence < 0.6 are dotted and
off by default behind a checkbox labelled "Include possible lineage"; each edge has an
expander with its evidence sentence; a series is **never silently spliced**; clicked
through in a browser.

---

### T11e — Validate lineage PE numbers against the database

**Files:** `analysis/lineage.py` (both detectors plus one new helper), `tests/test_lineage.py`,
`tests/test_ingest_lineage.py`, `storage/ingest_lineage.py`, `analysis/lineage_eval.py`
(docstring numbers), `data/processed/usg_budgets.db.gz` (rebuilt), `CODEX_HANDOFF.md` §1
(`pe_lineage` row), **`DATA_DICTIONARY.md`** (row-count table line for `pe_lineage`, the
`relation`/`method` counts in its `pe_lineage` section, and the archive blob hash and
"last rebuilt in commit" line in its header).
**Depends on:** T11d and T12a merged (they are: `af48a3f`, `e32d3d7`).
**Revised 2026-09-17** after Codex correctly stopped: the first version omitted
`DATA_DICTIONARY.md`, which T12a had just pinned at 433 rows, and listed the unknown
endpoints as examples rather than in full.
**Revised 2026-09-18** after a third correct stop: `tests/test_ingest_lineage.py` and the
narrative tests in `tests/test_lineage.py` build in-memory databases with narratives but
no `program_elements` rows, so the membership rule would reject every fixture edge. Both
test files are now in scope, the rows each test must seed are listed, and the API for
carrying rejection counts is fixed below so the ingest test's exact-dict assertion is
deterministic.

**Verified facts (shipped archive, 2026-09-17):** of the 433 `pe_lineage` rows, 28 have an
endpoint absent from `program_elements.pe_number`: 11 edges with an unknown predecessor,
17 with an unknown successor, none with both. All 28 are `narrative`; both `ba_renumber`
edges survive. The complete lists (membership rule: `pe_number IN (SELECT pe_number FROM
program_elements)`):

- Unknown predecessors (11 distinct): `0270344A`, `030205208M`, `06005053A`,
  `0602115DHA`, `06022787A`, `06030216F`, `0603115DHA`, `0603456A`, `0605013DHA`,
  `0605145DHA`, `0622144A`.
- Unknown successors (16 distinct, 17 edges): `0204229A`, `0205471N`, `03031113F`,
  `06020147A`, `06020148A`, `0603017N`, `0603115DHA`, `0604110DHA`, `0605145DHA`,
  `0605346A`, `0622144A`, `0622145A`, `0655333A`, `1201240F`, `1204857F`, `1206402SF`.

Two classes, for the report only (the rule treats them the same): book typos the regex
accepts because `\d{7}[A-Z0-9]{1,3}` also matches eight or nine digits (`06030216F`,
`030205208M`, `03031113F`, ...), and real PEs outside the R-1 corpus (Defense Health
Program `DHA` suffixes, Space Force successors not yet in the funding series).

**Expected after the filter (computed from the archive, 2026-09-17):** `pe_lineage` 433 ->
**405** (2 `ba_renumber` + 403 `narrative`); 404 distinct pairs; eval recall 10/10 (every
golden PE exists in `program_elements`, checked), precision 10/11 (N1 `0603030F ->
0602102F` still emitted, both PEs exist), 393 unlabelled pairs, year checks 10/10.

**API (fixed, so callers and tests agree):**

- `analysis/lineage.py` gains `known_pe_numbers(session) -> frozenset[str]` (distinct
  `program_elements.pe_number`) and both detectors gain one keyword-only parameter,
  `rejections: dict[str, int] | None = None`. Each detector filters its edges through the
  known set before returning; when `rejections` is a dict, the detector adds its counts
  into it under the keys `unknown_predecessor` and `unknown_successor` (an edge whose
  predecessor is unknown counts once under `unknown_predecessor` even if the successor is
  also unknown; the archive has no such edge today). Signatures otherwise unchanged, so
  `app.py`, `trend_tracker.py`, and `lineage_eval.py` need no edits beyond the eval
  docstring.
- `storage/ingest_lineage.ingest_lineage(session)` passes one dict per detector and
  returns exactly `{"ba_renumber": n, "narrative": n, "total": n,
  "rejected_unknown_predecessor": n, "rejected_unknown_successor": n}` (the last two
  summed across both detectors). `main()` prints those two rejection counts on their own
  line after the existing before/after line.

**Tests.** `ProgramElement.source_document_id` and `SourceDocument.publication_year` are
`NOT NULL`, so each test class's `setUp` creates one `SourceDocument(filename=...,
document_type="R1", publication_year=2027)` and a helper `_add_program_element(pe_number,
agency)` that inserts a `ProgramElement` pointing at it (the `BudgetActivityRenumberTests`
class already seeds PEs through `_add_funded_pe`; leave it). Seed these before running
the detector:

- `NarrativeLineageTests.test_fixture_yields_three_directed_evidence_backed_edges`:
  `0603176BR`, `0603160BR` (Defense-Wide); `0602182A`, `0602146A`, `0602144A`,
  `0605001A`, `0605002A` (Army); `0604659N`, `0105519N` (Navy). Assertions unchanged.
- `test_two_digit_fiscal_year_is_2000_based`: `0605003A`, `0605004A`.
- `test_pe_suffix_must_use_uppercase_alphanumerics`: `0605005A`, `0605006A`, `0605008A`,
  so the empty result is still caused by the regex, not by membership.
- `test_duplicate_edge_keeps_first_source_file_and_row_id`: `0605010A`, `0605011A`.
- New `test_unknown_endpoint_is_rejected_and_counted`: seed `0605003A` only, add the
  two-digit-FY narrative, call with `rejections={}`; assert `edges == []` and
  `rejections == {"unknown_successor": 1}`.
- `tests/test_ingest_lineage.py`: seed the nine fixture PEs above in `setUp`; the existing
  test now asserts the five-key dict with both rejection counts 0 and still 3 rows with
  identical hashes across two runs. New `test_unseeded_successor_is_rejected`: seed all
  fixture PEs except `0105519N`; assert `{"ba_renumber": 0, "narrative": 2, "total": 2,
  "rejected_unknown_predecessor": 0, "rejected_unknown_successor": 1}` and 2 rows.

**Definition of done:** an edge is emitted only when **both** PE numbers exist in
`program_elements`; rejected edges are counted per method and reason
(`unknown_predecessor`, `unknown_successor`) and printed by `storage/ingest_lineage.py`
so coverage is stated. Do not "repair" typos by editing the captured number. The
self-reference guard stays. Tests as specified above. The eval docstring states the new expected
numbers above. Rebuild the archive (`--reset-runtime`, then `build_archive`); the commit
message states `pe_lineage` 433 -> 405. `CODEX_HANDOFF.md` §1 and `DATA_DICTIONARY.md`
are updated to 405 / 403 and to the new archive blob hash and commit. Do not touch
`app.py` or `trend_tracker.py`.

**Verify:**
```bash
python -m pytest -q
python analysis/lineage_eval.py
python -m storage.ingest_lineage
python -m storage.ingest_lineage            # second run: identical counts
python -m analysis.ai_budget --reset-runtime
python -m storage.build_archive
git rev-parse HEAD:dod_ic_budget_analyzer/data/processed/usg_budgets.db.gz   # after commit; paste into DATA_DICTIONARY.md
```

---

## Phase F — Distribution

### T12a — Data dictionary

**Files:** new `DATA_DICTIONARY.md` at the repo root. No other files.
**Depends on:** nothing.
**Revised 2026-09-16** after Codex correctly stopped: the first version said "the two
`document_type` values"; the archive has had three since T9c (`P1`). Every enumeration
and count below was queried from the shipped archive on 2026-09-16 (`git show
main:dod_ic_budget_analyzer/data/processed/usg_budgets.db.gz`, decompressed). Quote them;
do not re-derive them from the ignored working `.db`, which accumulates runtime rows
(`search_log` had 3 on one machine) and may lag the archive.

**Verified facts (shipped archive, 2026-09-16):** 13 tables, 43 indexes.

| Table | Rows | Source exhibit / origin |
|---|---|---|
| `source_documents` | 412 | registry of ingested files: `R1` 29, `DD1416` 381, `P1` 2 |
| `program_elements` | 2,131 | R-1 `r1_display.xlsx` (`parsing/xlsx_ingest.py`), plus pre-FY2012 PDF/OCR rows |
| `funding_lines` | 55,652 | R-1; `funding_type` six values (below); `pb_cycle` 1998–2027 |
| `procurement_lines` | 5,253 | P-1 `p1_display.xlsx` PB2026 and PB2027 (`storage/ingest_p1.py`) |
| `pe_execution` | 79,677 | DD 1416 quarterly execution workbooks (T5) |
| `pe_congressional_actions` | 26,544 | House and Senate committee/authorization tables, FY2012–FY2027 (M2a); see `CODEX_HANDOFF.md` §1 |
| `pe_narratives` | 18,268 | R-2 justification books, XML (PB2026+) and PDF (`parsing/r2_parser.py`); `project_number == ""` on 5,864 PE-level rows |
| `pe_accomplishments` | 101,219 | R-2 accomplishment / plans line items |
| `pe_lineage` | 433 | **derived** from `funding_lines` and `pe_narratives` by `analysis/lineage.py`; rebuilt by `storage/ingest_lineage.py` |
| `ai_cache`, `ai_spend`, `ai_user_history`, `search_log` | 0 each | runtime, reset on every archive build (`analysis/ai_budget.py --reset-runtime`) |

Enumerations (value: count):

- `source_documents.document_type`: `R1` 29, `DD1416` 381, `P1` 2. **Three values.**
- `funding_lines.funding_type`: `PY Actual` 20,692; `CY Request` 16,055; `BY Request`
  18,713; `PY Mandatory` 6; `CY Mandatory` 160; `BY Mandatory` 26. Six values.
- `procurement_lines.funding_type`: the same six names (`PY Actual` 1,763; `CY Request`
  1,658; `BY Request` 1,532; `PY Mandatory` 9; `CY Mandatory` 138; `BY Mandatory` 153).
- `procurement_lines.cost_type`: `A` 4,808; `B` 131; `C` 130; `E` 9; `G` 1; `L` 32;
  `N` 97; and **blank** 45 (lines with no cost-type split). Titles are in
  `cost_type_title`; see `CODEX_HANDOFF.md` §3 P-1 trap for what the letters mean.
- `pe_congressional_actions.chamber`: `House` 13,097; `Senate` 13,447. Never pooled.
- `pe_lineage.relation`: `transferred` 431; `renumbered` 2. `pe_lineage.method`:
  `narrative` 431; `ba_renumber` 2. (`split` and `merged` are allowed by the `Relation`
  type in `analysis/lineage.py` but no detector emits them yet.)
- `pe_accomplishments.year_label` is **not a clean enumeration**: 29 distinct values.
  The intended set is `Description`, `Plans`, `Accomplishments`, `Base Plans`, `OCO
  Plans`, `Increase/Decrease Statement` (stored truncated to 20 characters as
  `Increase/Decrease St`), `PY`, `CY`, `BY`, `New Start`; the remaining values are
  parser leakage from the PDF path. **Corrected 2026-09-17:** the spec first said
  "about 60 rows"; Codex measured 298, of which 246 are `OOC Plans` (a misspelling
  of OCO printed in the books themselves). Document the intended set, state the
  leakage count, and do not clean it in this task.

Column types come from the SQLAlchemy models in `storage/db.py` (the only source of
truth for names and types); confirm each table's column list against
`PRAGMA table_info` on the archive so the document matches what ships, not what the
model would create fresh. Units: `amount_thousands` and every `*_k` column are
thousands of dollars; `funding_millions` and `*_m` are millions; `quantity` is a unit
count; fiscal years are integers; `report_date`, `retrieved_at`, `ingested_at` are
ISO dates/timestamps.

**Definition of done:** `DATA_DICTIONARY.md` has one section per shipped table (nine)
with every column's name, SQL type, unit or meaning, allowed values where enumerated
(exactly the lists above), and the source exhibit; a row-count table matching the one
above with the date and archive commit it was taken from; a "Runtime tables, not
shipped" section listing the four runtime tables with their columns and stating they
are 0 rows in the archive; a "Derived tables" note for `pe_lineage`; and a one-paragraph
"Units and conventions" section. No code changes. `python -m pytest -q` still passes
(nothing should have changed).

**Verify:**
```bash
python -m pytest -q
python - <<'PY'
import sqlite3; c = sqlite3.connect("data/processed/usg_budgets.db")
for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1"):
    print(t, c.execute(f"select count(*) from {t}").fetchone()[0], [r[1] for r in c.execute(f"pragma table_info({t})")])
PY
```
Paste that output and state that every table and column in it appears in the document.

### T12b — Release bundle script

**Files:** new `scripts/build_release.py` (next to `scripts/export_changefeed.py`), new
`tests/test_build_release.py`, `README.md` (new `## Data releases` section inserted after
`## Updating the data`), root `.gitignore` (add `release/`).
**Depends on:** T12a and T11e merged (they are: `e32d3d7`, `9ed1af8`; archive blob
`f2aa7a54…` restored on main in `d374360`).
**Rewritten 2026-09-18** against the repo: the first version assumed a `sqlite3` binary
(neither machine has one), would have rebuilt the tracked archive on every run (gzip
embeds a timestamp, so the tracked blob would change each time), named no tests, and left
`release/` untracked but not ignored (T13b's export already writes there).

**Verified facts (2026-09-18):**

- `data/processed/` tracks: `usg_budgets.db.gz` (blob `f2aa7a54…`, 405 `pe_lineage`
  rows), **30** parquet files (`r1_1998.parquet` … `r1_2027.parquet`, no 1999, plus
  `r1_all_years.parquet`; 1.7 MB total), `rdte_deflators_fy2025.csv`, one
  `semantic_embeddings_*.pt` (regenerable, excluded from the bundle), and a legacy
  `DoD_Budget_Analysis.xlsx` (excluded).
- The runtime reset lives only in `analysis/ai_budget.py::main()` behind
  `--reset-runtime`; there is no importable function. Call it as
  `subprocess.run([sys.executable, "-m", "analysis.ai_budget", "--reset-runtime"],
  cwd=APP_DIR, check=True)`.
- `storage/build_archive.build_archive()` gzips with the current time in the header, so
  two builds of identical data produce different blobs. **The release script does not
  rebuild the archive.** It bundles the tracked one and verifies it independently.
- The compliance query from `CODEX_HANDOFF.md` invariant 1 is
  `SELECT COUNT(*) FROM ai_cache WHERE task IN ('find_open_source_hits','annual_signal')`.
  Run it with Python's `sqlite3` module.
- `storage.db.get_engine()` expands the `.db.gz` on first use, which is what "runs from a
  clean clone" relies on. `config.PROCESSED_DIR` is `dod_ic_budget_analyzer/data/processed`.
- Row counts the manifest must reproduce are the `DATA_DICTIONARY.md` table (nine data
  tables; `pe_lineage` 405; four runtime tables 0).

**Do (in this order, in `main()`):**

1. Expand the working database if needed (`get_engine()`), then run `--reset-runtime`
   on it via subprocess so a developer who rebuilds afterwards cannot leak runtime rows.
2. Decompress the **tracked** `usg_budgets.db.gz` to a temporary file (`tempfile`,
   `gzip`). Every check and count below runs against that copy, never the working `.db`.
3. Fail with exit code 1, printing which check failed, if any of the four runtime tables
   (`ai_cache`, `ai_spend`, `ai_user_history`, `search_log`) has rows, or if the
   compliance query returns nonzero. This is what "runtime tables are excluded by
   construction" means: the shipped artifact is proven clean, not assumed clean.
4. Create `<repo root>/release/usg-budgets-<YYYY-MM-DD>/` (`REPO_ROOT` as in
   `scripts/export_changefeed.py`; `--date` overrides for testing; refuse to overwrite an
   existing directory unless `--force`). Copy in: the `.db.gz`, the 30 parquet files,
   `rdte_deflators_fy2025.csv`, `DATA_DICTIONARY.md`.
5. Write `manifest.json`: `{"built_at": ISO-8601 UTC, "archive_sha256": hex of the .db.gz,
   "archive_bytes": int, "tables": {name: rows} for the nine data tables,
   "runtime_tables": {name: 0} for the four, "source_documents": [{"filename",
   "document_type", "source_url", "content_hash"}] sorted by filename}`.
6. Write `RELEASE_NOTES.md`: the date, the archive hash, a table of row counts, and a
   "Changes since <previous date>" table with `table: before -> after (delta)` for every
   table whose count changed, where "previous" is the newest other
   `release/usg-budgets-*/manifest.json` by directory name. With no previous manifest,
   write "First release; no previous manifest to compare."
7. Print the bundle path and total size. No GitHub release, no upload, no git commands.

Structure the script as pure functions so the tests below need no real archive:
`archive_checks(connection) -> list[str]` (failure messages, empty when clean),
`manifest_for(connection, archive_path) -> dict`, `release_notes(previous: dict | None,
current: dict, date: str) -> str`, plus `main()`.

**Tests (`tests/test_build_release.py`, in-memory SQLite via `storage.db.Base`):**
`archive_checks` returns `[]` on an empty runtime set and one message naming the table
when an `ai_cache` row with `task="annual_signal"` is present (the compliance query
fires) and when a `search_log` row is present; `manifest_for` on a DB with one
`SourceDocument` and one `ProgramElement` yields the exact key set above with
`tables["program_elements"] == 1` and one `source_documents` entry; `release_notes(None,
…)` contains the first-release sentence; `release_notes(prev, cur)` where `pe_lineage`
goes 433 -> 405 contains the line `pe_lineage: 433 -> 405 (-28)`.

**Definition of done:** `python scripts/build_release.py` from `dod_ic_budget_analyzer/`
on a clean clone exits 0 and produces the directory above with all six kinds of content;
its `manifest.json` counts equal the `DATA_DICTIONARY.md` table; a second run the same
day without `--force` exits 1 with a clear message; `git status --short` after a run is
empty (`release/` ignored); the README section says what a bundle contains, how to build
one, and that attaching it to a GitHub release is a manual step. Do not touch `app.py`,
`build_archive.py`, or the archive.

**Verify:**
```bash
python -m pytest -q
python scripts/build_release.py
python -c "import json,glob; m=json.load(open(sorted(glob.glob('../release/usg-budgets-*/manifest.json'))[-1])); print(m['tables']); print(m['runtime_tables']); print(len(m['source_documents']), 'source documents')"
python scripts/build_release.py            # same day, no --force: expect exit 1
git status --short                          # expect empty
```

### T13a — Change feed core

**Files:** new `analysis/changefeed.py`, new `tests/test_changefeed.py`.
**Depends on:** nothing (T4's `pb_cycle` already exists).
**Spec verified against the shipped database 2026-09-15.**
**Revised 2026-09-15** after Codex correctly stopped: the first version keyed
reprogramming rows on `(pe_number, agency, fy_start, line_number)`, which is not unique
per report date. The key and the collision policy below replace it.

```python
Kind = Literal["new_start", "termination", "swing", "committee_action", "reprogramming"]

@dataclass(frozen=True)
class ChangeEvent:
    pe_number: str; agency: str; program_name: str
    kind: Kind
    fiscal_year: int
    from_vintage: int | None     # pb_cycle or report FY the "before" came from
    to_vintage: int | None
    before_k: float | None
    after_k: float | None
    pct_change: float | None
    detail: str                  # e.g. the committee rationale, or "PB2027 vs PB2026 BY Request"
    permalink: str               # "?tab=finder&pe=...&agency=..."

def diff_vintages(session, older_pb: int, newer_pb: int, *, swing_pct: float = 20.0) -> list[ChangeEvent]: ...
def new_committee_actions(session, fiscal_year: int) -> list[ChangeEvent]: ...
def new_reprogramming(session, report_date: str) -> list[ChangeEvent]: ...
```

**Verified facts:**

- The vintage offsets are exact and have no exceptions in 55,652 rows: for every line,
  `fiscal_year - pb_cycle` is 0 for `BY Request`, −1 for `CY Request`, −2 for
  `PY Actual`, and the same for the three `Mandatory` variants. So the FY2025 figure for
  a PE is its `BY Request` in PB2025, its `CY Request` in PB2026, and its `PY Actual`
  in PB2027.
- **Compare like with like** therefore means: for one `fiscal_year`, compare the amount
  in `older_pb` against the amount in `newer_pb`, whatever the two `funding_type` labels
  are. Never compare two different fiscal years. Never mix a `Mandatory` type with a
  discretionary one (invariant 5); `diff_vintages` uses only `PY Actual`, `CY Request`,
  `BY Request`.
- `program_elements` is one row per `(pe_number, agency)` (2,131 rows, 2,131 distinct
  pairs), so `program_name` comes straight from it. `funding_lines` joins through
  `program_element_id`.
- `new_start`: the PE has a nonzero line for `fiscal_year == newer_pb` in `newer_pb` and
  **no line of any type in `older_pb`**. `termination`: the PE has a nonzero line in
  `older_pb` and **no line of any type in `newer_pb`**. Absence means the PE left the
  R-1, not that it went to zero; a zero amount in the newer vintage is a `swing`, not a
  termination. A budget-activity renumbering (T11) will show up as one termination plus
  one new start; that is correct for this task and T11d will later cross-reference
  `pe_lineage`. Say so in the docstring.
- `swing`: same PE, same `fiscal_year`, both vintages present, `before_k` nonzero, and
  `abs(after − before) / abs(before) × 100 ≥ swing_pct`. `pct_change` is that signed
  percentage. `swing_pct` defaults to 20.0 and the docstring states it.
- `pe_congressional_actions` columns: `pe_number`, `agency`, `fiscal_year`, `chamber`
  (`House` 13,097 rows FY2012–FY2027, `Senate` 13,447 rows FY2013–FY2027), `report_citation`,
  `request_k`, `committee_delta_k`, `authorized_k`, `rationale`. `new_committee_actions`
  emits one event per row with nonzero `committee_delta_k`: `before_k=request_k`,
  `after_k=authorized_k`, `from_vintage=to_vintage=None`, and `detail` **must begin with
  the chamber** ("House: Program Increase [+2,000]") because `ChangeEvent` has no chamber
  field and House and Senate are never pooled (invariant 4). The word "authorized" is
  acceptable in `detail`; "appropriated" and "enacted" are not (invariant 3).
- `pe_execution` has several rows per `(pe_number, agency, report_date)` because each
  appropriation year (`fy_start`), each `line_number`, and each `budget_activity` is its
  own row. **The row key is `(pe_number, agency, fy_start, line_number, budget_activity)`.**
  Without `budget_activity` the key collides on 113 `(key, report_date)` groups, because a
  PE can sit under two budget activities in the same quarter (`0604003F` under BA 4 and
  BA 7 on 2021-09-30; `0305164F` under BA 4 and BA 7 through FY2013). With
  `budget_activity` in the key, 16 groups still collide and none of them is a real PE
  line: `8998` "CLOSED ACCOUNT ADJ" (11 groups), the classified aggregates `9999999999`
  and `XXXXXXXXXX` (4 groups), and `0605027D8Z` on 2017-06-30, where the workbook carries
  the line twice. `line_number` is NULL on 11,158 rows; NULL is a legitimate key value
  and two NULLs are the same key.
- **Collision policy:** a key with more than one row on a given `report_date` is
  ambiguous. `new_reprogramming` emits nothing for that key on that call, whether the
  duplication is in the requested report or in the previous one, and never sums the rows
  or picks one of them. Say so in the docstring.
- `new_reprogramming(session, report_date)` finds the previous `report_date` for each
  key (the greatest one less than the argument; if none, the whole amount is new), and
  emits one event per column that changed: one for `above_threshold_reprog_k` and one for
  `below_threshold_reprog_k`, with `detail` naming which ("above-threshold reprogramming"
  or "below-threshold reprogramming"; they carry different oversight meaning and are
  never summed). `fiscal_year=fy_start`, `from_vintage`/`to_vintage` are the two report
  dates' fiscal years, `before_k`/`after_k` are the column values. Report dates are
  quarter-ends, latest `2026-03-31`.
- `permalink` is `f"?tab=finder&pe={pe_number}&agency={agency}"`; `app.py` reads exactly
  those three query-parameter names.

**Definition of done:** all three functions return lists sorted by
`(kind, agency, pe_number, fiscal_year)` and are deterministic for fixed inputs; the
threshold is a named parameter with its default documented; tests on an in-memory SQLite
session (pattern: `tests/test_reconcile.py::setUp`) cover one new start, one
termination, one swing above threshold, one below (not emitted), one nonzero-to-zero
case (emitted as `swing`, not `termination`), and the forbidden cross-FY comparison
(a PE whose `PY Actual` and `CY Request` differ in the same vintage yields nothing);
one committee test asserts the chamber leads `detail`; one reprogramming test asserts
above- and below-threshold changes are separate events, and one asserts that a key with
two rows on the same report date yields no event for that key. `python -m pytest -q` passes.
No UI, no export script (that is T13b).

**Verify:**
```bash
python -m pytest -q
python - <<'PY'
from storage.db import get_engine, get_session_factory
from analysis.changefeed import diff_vintages, new_committee_actions, new_reprogramming
from collections import Counter
session = get_session_factory(get_engine("sqlite:///data/processed/usg_budgets.db"))()
events = diff_vintages(session, 2026, 2027)
print("PB2026 vs PB2027:", Counter(e.kind for e in events))
print("committee FY2027:", len(new_committee_actions(session, 2027)))
print("reprogramming 2026-03-31:", len(new_reprogramming(session, "2026-03-31")))
for e in events[:5]: print(e)
PY
```

### T13b — Change feed surface

**Files:** `app.py` (Budget Trends tab, new section "What changed"), new
`scripts/export_changefeed.py` writing `release/changefeed.json`.
**Depends on:** T13a merged (it is: merged `6722bc9` on 2026-09-15).

**Definition of done:** the section takes two `pb_cycle` selectboxes and lists events with
working permalinks; the JSON export validates against the dataclass fields; clicked
through in a browser.

---

## Phase G — AI that earns its cost

### T14a — Local retrieval over narratives

**Files:** new `analysis/narrative_qa.py`, new `storage/build_narrative_index.py`, new
`analysis/narrative_qa_eval.py`, new `tests/test_narrative_qa.py`, new **tracked**
`data/processed/narrative_index_multi-qa-MiniLM-L6-cos-v1.pt`, `README.md` (one
paragraph plus the build command under `## Updating the data`, after the archive-rebuild
block). Do not touch `app.py`, `matching/semantic_matcher.py`, or
`scripts/build_release.py` (the index is regenerable and stays out of release bundles).
**Depends on:** T11e merged (it is). The index hash is tied to the shipped narratives.
**Rewritten 2026-09-18** against the repo: the first version said "uses the existing
embeddings file". That file (`semantic_embeddings_multi-qa-MiniLM-L6-cos-v1.pt`) is the
Program Finder's **program-level** index: 2,126 vectors, one per PE, built from the title
plus a 400-character snippet. It cannot answer passage-level questions. T14a builds a
separate passage index; the numbers below were measured on this machine.

**Verified facts (shipped database and model, 2026-09-18):**

- `pe_narratives`: 18,268 rows, mean 1,925 characters, 6,258 rows over 2,000 characters,
  14,737 distinct texts (the same narrative repeats across fiscal-year books). The
  model `multi-qa-MiniLM-L6-cos-v1` (already in `requirements.txt` via
  `sentence-transformers`; dimension 384; `max_seq_length` 512 tokens, roughly 2,000
  characters) truncates anything longer, so narratives must be chunked.
- Chunking rule (fixed, so the count is reproducible): strip, split on the regex
  `(?<=[.!?])\s+`, pack sentences greedily while
  `len(chunk) + 1 + len(sentence) <= 1500`; a single sentence longer than 1,500
  characters becomes its own chunk (never split mid-sentence). Read rows
  `ORDER BY fiscal_year DESC, id`; deduplicate on `(pe_number, agency, chunk_text)`
  keeping the first, so a repeated passage cites the latest book. Result on the shipped
  database: **26,702 passages, mean 1,065 characters**.
- Index size at float16: **20.5 MB** (26,702 x 384 x 2 bytes). Track it in git like the
  archive; GitHub's per-file limit is 100 MB.
- CPU encode rate here: about 23 passages/s at batch size 64, so a full build is about
  **19 minutes**. That is why the index ships prebuilt: Community Cloud cannot build it on
  a cold start. Query cost after model load: 30-130 ms per question (encode one string,
  one matmul over 26,702 rows).
- `pe_accomplishments` (101,219 rows, 74,849 distinct texts) is **excluded** from this
  task; it would quadruple the index. Note it as a follow-up in your report.
- Retrieval quality, measured against the full index (rank of the first passage from the
  named PE): Skyborg -> `0603032F` rank 1; counter-UAS laser -> `0602605F` rank 1; JTRS
  software-defined radio -> `0605042A` rank 1; EA-18G Next Generation Jammer ->
  `0604269N` rank 1 (`0604274N` rank 5); quantum sensing -> `0602182A` rank 2; launched
  effects -> `0605345A` rank 3. Known misses on proper nouns: "Dark Eagle" and
  "Sentinel ICBM" (the model returns an Army radar also named Sentinel). The eval records
  both kinds.

**Index file format** (`torch.save` of one dict): keys `model` (str), `corpus_hash`
(sha256 of the newline-joined, tab-separated `pe, agency, fy, project, source, text`
fields in index order), `embeddings` (float16 tensor of shape (N, 384), L2-normalised),
and the parallel lists `pe_number` (str), `agency` (str), `fiscal_year` (int),
`project_number` (str, empty string for PE-level rows), `source_file` (str), `text`
(str). One entry per passage in every list.

**API:**

```python
@dataclass(frozen=True)
class Passage:
    pe_number: str; agency: str; fiscal_year: int
    project_number: str | None        # None when the row's project_number is ""
    source_file: str
    text: str
    score: float                      # cosine similarity, float

def chunk_text(text: str, limit: int = 1500) -> list[str]: ...          # pure
def index_rows(session) -> list[tuple[str, str, int, str, str, str]]: ...  # pure: (pe, agency, fy, project, source, chunk) after chunking + dedup, no model
def retrieve(question: str, *, k: int = 8) -> list[Passage]: ...
def index_status() -> dict: ...      # {"model", "passages", "corpus_hash", "path"}
```

`retrieve` lazily loads the model and the index once per process (`functools.lru_cache`
on two private loaders), encodes the question with `normalize_embeddings=True`, scores
with one matmul against the float16 matrix cast to float32, and returns the top `k`
passages in descending score. Whitespace-only question -> `[]`. Missing index file ->
`FileNotFoundError` whose message names `python -m storage.build_narrative_index`. No
network access and no model API call anywhere in this task.

`storage/build_narrative_index.py`: `main()` with `--database` (default the working
`.db`; call `get_engine()` so a clean clone expands the archive), `--output` (default the
tracked path), `--limit N` (first N rows, for smoke runs to a temp path). Encodes with
`batch_size=64`, stores float16, prints passage count, mean length, and elapsed seconds.

**Eval (`analysis/narrative_qa_eval.py`, pattern `analysis/linker_eval.py`):** golden
cases as `(question, acceptable_pe_numbers: set[str], gated: bool)`:

| Question | Acceptable | Gated |
|---|---|---|
| `Skyborg autonomous aircraft vanguard program` | `{0603032F}` | yes |
| `counter-UAS directed energy laser for base defense` | `{0602605F}` | yes |
| `software defined radio for the Joint Tactical Radio System` | `{0605042A}` | yes |
| `Next Generation Jammer for the EA-18G Growler` | `{0604269N, 0604274N}` | yes |
| `What is the Army doing on launched effects for unmanned aircraft?` | `{0605345A, 0609345A}` | yes |
| `Long Range Hypersonic Weapon Dark Eagle` | `{0604182A}` | no (documented miss) |
| `Ground Based Strategic Deterrent Sentinel ICBM replacement` | `{0604858F, 0101125F}` | no (documented miss) |

For each case call `retrieve(question, k=8)`, print the rank of the first acceptable PE
(or "miss"), the top score, and the query time in ms; PASS if rank <= 3. Exit 1 if any
**gated** case fails; ungated cases are printed with their actual top PE so the
proper-noun weakness is stated, not hidden. Expected on the index built from the shipped
database: 5/5 gated pass (ranks 1, 1, 1, 1, 3), every query under 2 s.

**Tests (`tests/test_narrative_qa.py`):**

- `chunk_text`: three short sentences -> one chunk equal to the stripped input; four
  sentences of about 500 characters -> two chunks, each <= 1,500, each ending in `.`, and
  joining the chunks with a single space reproduces the input; one 2,000-character
  sentence -> one chunk of 2,000.
- `index_rows` on an in-memory session (`storage.db.Base`; `PENarrative` needs no
  `SourceDocument`) with two `PENarrative` rows for the same PE and agency carrying
  identical text in FY2026 and FY2027 -> exactly one row with `fiscal_year == 2027`; add
  a third row with different text -> two rows total.
- `retrieve` against the **shipped index** with the real model: `pytest.skip` if the
  index file is absent; otherwise `retrieve("Skyborg autonomous aircraft vanguard
  program", k=3)` returns 3 passages, scores non-increasing, and some passage has
  `pe_number == "0603032F"`; a second call to `retrieve` completes in under 2 s.
  (CI installs `sentence-transformers` and downloads the model today for the app smoke
  test, so this test runs there too.)

**Definition of done:** the index file is built from the shipped database and committed
(commit message states the passage count and build time); `python
analysis/narrative_qa_eval.py` prints 5/5 gated passes and exits 0; every `retrieve`
call in the eval is under 2 s after model load; `python -m pytest -q` passes; README
paragraph added; no code outside the file list changed; no model API call anywhere.

**Verify:**
```bash
python -m pytest -q
python -m storage.build_narrative_index --limit 200 --output nq_smoke.pt   # fast smoke run; delete the file afterwards
python -m storage.build_narrative_index                                     # full build, about 19 min on CPU
python analysis/narrative_qa_eval.py
git status --short        # expect only the new files; the tracked index is a new file, not a modification
```

### T14b — Cited synthesis through the governed AI path

**Files:** `analysis/narrative_qa.py` (types, validator, `answer()`), `analysis/oss_enricher.py`
(new `GeminiEnricher.narrative_answer()` method, `PROMPT_VERSIONS` entry, `ANSWER_SCHEMA`),
`config.py` (one `AI_CACHE_TTL_DAYS` entry), `analysis/ai_budget_eval.py` (governance
checks for the new task), `tests/test_narrative_qa.py` (validator tests). Do not touch
`app.py` (that is T14c), `analysis/ai_budget.py`, or `config.GROUNDED_TASKS`.
**Depends on:** T14a merged (it is: commit `bbfec92`).
**Rewritten 2026-09-18** against the repo: the first version returned an `AIResult` type
that does not exist, named no task string, no prompt, no schema, no cache-key params,
no validator rule, and used a `sqlite3` command-line check neither machine has.

**Verified facts (2026-09-18):**

- Every AI task goes through `GeminiEnricher._governed(task, params, user_id,
  allow_fresh, credits, call, empty, force)` in `analysis/oss_enricher.py`: cache read ->
  `budget_guard` -> `call()` -> `SpendLedger.record` -> `AICache.put`. It returns
  `EnrichmentResult` (`payload`, `cached`, `created_at`, `search_suggestions_html`,
  `blocked`, `cold`, `grounded`, `message`). `call()` must return `(payload, usage)`
  where `payload` is JSON-serialisable and `usage` comes from `_usage(resp)`. An empty
  payload (`None`, `[]`, `{}`) is never cached. **There is no `AIResult`; use
  `EnrichmentResult`.**
- Cache routing is decided by `config.GROUNDED_TASKS` (`find_open_source_hits`,
  `annual_signal`). Any other task name goes to the shared `ai_cache`. The new task
  therefore must simply not be added to that set.
- Prompt versions live in `oss_enricher.PROMPT_VERSIONS`; TTLs in
  `config.AI_CACHE_TTL_DAYS` (default 30 days when absent). `adjudicate` is the
  non-grounded template: `response_mime_type="application/json"`, a `response_schema`
  dict using Gemini's `OBJECT`/`ARRAY`/`STRING`/`INTEGER`/`NUMBER`/`BOOLEAN` type names,
  `temperature=0.0`, then `json.loads(resp.text)`.
- `oss_enricher.available()` is False without a key; `oss_enricher.status()` returns
  `(ok, message)` with the human-readable reason, which the app already shows.
- `analysis/ai_budget_eval.py` drives the governed path with a fake client
  (`GeminiEnricher.__new__`, `enricher.client = _FakeClient()`, `_FakeResp.text` holding
  the JSON) against a scratch database; no real API spend. Extend it the same way.
- `retrieve()` (T14a) returns `Passage(pe_number, agency, fiscal_year, project_number,
  source_file, text, score)`; `index_status()["corpus_hash"]` identifies the index.
- No test currently imports `oss_enricher`; the validator tests below are pure and need
  no key and no model.

**Task name:** `narrative_answer`. Register `PROMPT_VERSIONS["narrative_answer"] = 1` and
`config.AI_CACHE_TTL_DAYS["narrative_answer"] = 365` (temperature 0 over a fixed passage
set is stable, like `adjudicate`). It is **not** grounded and must not be added to
`GROUNDED_TASKS`.

**Types and validator (`analysis/narrative_qa.py`, no Streamlit, no network):**

```python
@dataclass(frozen=True)
class Citation:
    pe_number: str; agency: str; fiscal_year: int; source_file: str; quote: str

@dataclass(frozen=True)
class CitedAnswer:
    sentences: tuple[tuple[str, tuple[Citation, ...]], ...]   # every sentence has >= 1 citation
    refused: bool
    reason: str | None

    def to_dict(self) -> dict: ...                 # JSON-serialisable; this is what the cache stores
    @classmethod
    def from_dict(cls, payload: dict) -> "CitedAnswer": ...

def normalize_ws(text: str) -> str: ...            # collapse runs of whitespace to one space, strip
def validate_answer(raw: dict, passages: Sequence[Passage]) -> CitedAnswer: ...
def answer(question: str, passages: Sequence[Passage], *, user_id: str,
           allow_fresh: bool, credits: int | None = None, force: bool = False,
           enricher=None) -> EnrichmentResult: ...
```

`raw` is the model's JSON: `{"sentences": [{"text": str, "citations": [{"passage": int,
"quote": str}]}], "refused": bool, "reason": str}`. `validate_answer` is pure and is the
enforcement point:

- If `raw["refused"]` is true: return `CitedAnswer((), True, raw["reason"] or
  "model_refused")`.
- If there are no sentences: `CitedAnswer((), True, "empty")`.
- For each citation: `passage` must be a 1-based index into `passages`, and
  `normalize_ws(quote)` must be a substring of `normalize_ws(passage.text)` with
  `len(quote) >= 20`. A citation that fails is dropped. A sentence left with **zero**
  valid citations converts the **whole** answer to `CitedAnswer((), True, "uncited")`;
  never return a partially cited answer.
- Otherwise resolve each citation to `Citation(pe_number, agency, fiscal_year,
  source_file, quote)` from the passage and return `refused=False, reason=None`.

`answer()`:

- Whitespace-only question or empty `passages` -> `EnrichmentResult(payload=None,
  blocked=True, message="Nothing to answer from.")` without touching the enricher.
- `enricher=None` -> if `oss_enricher.available()` construct `GeminiEnricher()`, else
  return `EnrichmentResult(payload=None, blocked=True, message=oss_enricher.status()[1])`.
- Otherwise return `enricher.narrative_answer(question, passages, user_id=user_id,
  allow_fresh=allow_fresh, credits=credits, force=force)`. The returned
  `payload` is the `CitedAnswer.to_dict()` dict (or `None`); callers rebuild it with
  `CitedAnswer.from_dict`.

**Enricher method (`GeminiEnricher.narrative_answer`, pattern `adjudicate`):**

- `params = {"question": normalize_ws(question), "index": index_status()["corpus_hash"][:16],
  "passages": [sha256(passage.text)[:16] for each passage, in order]}`. Same question
  over the same retrieved passages hits the shared cache for every user.
- Prompt: state that the model is answering from the numbered passages only, must quote
  verbatim, and must set `refused=true` with a reason when the passages do not support
  an answer. List passages as `[n] PE <pe> [<agency>] FY<fy> <source_file>:` followed by
  the text. Ask for two to six sentences, each with at least one citation.
- `ANSWER_SCHEMA`: `OBJECT` with `sentences` (`ARRAY` of `OBJECT{text: STRING,
  citations: ARRAY of OBJECT{passage: INTEGER, quote: STRING}}`), `refused` (`BOOLEAN`),
  `reason` (`STRING`); all required. `temperature=0.0`.
- `call()` returns `(validate_answer(json.loads(resp.text), passages).to_dict(),
  _usage(resp))`. A refused answer is a non-empty dict and is cached like any other
  deterministic verdict.
- Return `self._governed("narrative_answer", params, user_id, allow_fresh, credits,
  call, empty=None, force=force)`.

**Governance checks to add to `analysis/ai_budget_eval.py`** (fake client, two fake
`Passage` objects with known text):

1. `"narrative_answer" not in config.GROUNDED_TASKS`.
2. A fresh call with a fake response whose quote is a real substring: exactly one API
   call, `payload["refused"] is False`, one sentence with one citation whose `pe_number`
   matches the cited passage.
3. The same call for a different `user_id`: zero additional API calls and `cached` is
   True (shared table).
4. A fake response whose quote is **not** in any passage: `payload["refused"] is True`
   and `payload["reason"] == "uncited"`.
5. The existing "shared table holds no grounded tasks" check still passes after these.
6. The ledger gained rows for the task and its cost is under one cent for the fake
   usage.

**Tests (`tests/test_narrative_qa.py`, pure, added to the existing file):** `validate_answer`
with two synthetic passages: exact quote resolves to the right `Citation`; a quote that
differs only in internal whitespace resolves; a quote shorter than 20 characters is
dropped and, being the only one, yields `uncited`; a `passage` index of 0 or 3 with two
passages yields `uncited`; `raw["refused"]=True` passes through with its reason; empty
`sentences` yields `empty`; `to_dict`/`from_dict` round-trip is equal.

**Definition of done:** the task is not in `GROUNDED_TASKS` and its results land in the
shared `ai_cache`; every sentence carries at least one citation whose quote is a
verbatim (whitespace-normalised) substring of a retrieved passage, verified in code,
otherwise the answer is `refused=True, reason="uncited"`; cost is metered in `ai_spend`;
`python analysis/ai_budget_eval.py` passes with the six new checks; `python -m pytest -q`
passes; no live API call is made by any test or eval.

**Verify:**
```bash
python -m pytest -q
python analysis/ai_budget_eval.py
python -c "import sqlite3; c=sqlite3.connect('data/processed/usg_budgets.db'); print(c.execute(\"SELECT COUNT(*) FROM ai_cache WHERE task IN ('find_open_source_hits','annual_signal')\").fetchone()[0])"   # must print 0
python -c "import config; from analysis.oss_enricher import PROMPT_VERSIONS; print('narrative_answer' in PROMPT_VERSIONS, 'narrative_answer' in config.GROUNDED_TASKS, config.AI_CACHE_TTL_DAYS['narrative_answer'])"   # True False 365
```

### T14c — Ask-the-corpus UI

**Files:** `app.py` (Program Finder tab, between `st.header("Find a program")` and the
program search `st.text_input`), `tests/test_app_smoke.py` (one lookup changed, one test
added). Nothing else: no change to `analysis/narrative_qa.py`, `analysis/oss_enricher.py`,
`config.py`, or any tab label or order.
**Depends on:** T14b merged (it is: commit `3bb54cc`).
**Rewritten 2026-09-18** against the repo. The first version said "cold cache shows a
button", "warm cache auto-renders", and "degrade to the same caption", without naming the
helpers that already do each of those things, and without noticing that inserting a text
input above the search box breaks the smoke test's `text_input[0]` lookup.

**Verified facts (2026-09-18):**

- `render_ai_result(res, render_fn, empty_msg)` in `app.py` already renders an
  `EnrichmentResult` honestly: `blocked` -> `st.info(res.message)`; `empty` ->
  `st.info(empty_msg)`; otherwise `render_fn(res.payload)`; and when `res.cached` it adds
  the caption `Saved analysis from YYYY-MM-DD. Re-run below for a fresh look.` **That is
  the "as of" caption; reuse it.** It also warns when `res.grounded` is False; the
  narrative task sets `grounded` from `_usage()`, which reads `grounding_metadata`, so a
  non-grounded answer arrives with `grounded=False`. Pass `dataclasses.replace(res,
  grounded=True)` to the renderer for this task (it is not a search-backed task and the
  warning text is about web search).
- `get_enricher()` (`@st.cache_resource`) returns `None` without a key or SDK. The "In
  the News" block (around `app.py:1788`) shows one of two captions, keyed on
  `oss_enricher.status()[1]` being `"package"` or anything else. T14c introduces
  `_ai_disabled_caption()` in `app.py` that returns those exact two strings, uses it in
  the new section, and replaces the two literal captions in the News block with the same
  call. No other change to the News block.
- `current_user_id()` gives the billing identity; other AI calls pass no `credits`
  (config default). The cache-only probe pattern is `allow_fresh=False` first; a `cold`
  result means "nothing saved, offer a button"; the button re-calls with
  `allow_fresh=True` inside `st.spinner`.
- `analysis.narrative_qa.retrieve()` loads the model with `local_files_only=True`. The
  weights reach the local cache only when `load_matching_models()` (the finder's
  `@st.cache_resource` loader, which constructs `SemanticMatcher` and downloads the
  model) has run at least once in that environment. On Community Cloud the first visitor
  who asks a question before anyone has searched would otherwise hit an `OSError`.
  **Rule:** the new section's own `@st.cache_resource` accessor `load_corpus_search()`
  calls `load_matching_models()` first, then `narrative_qa.retrieve("warm-up", k=1)`
  inside `try/except Exception`, and returns `True` on success or the exception's class
  name on failure; the section renders a caption naming the failure and stops when it is
  not `True`.
- `tests/test_app_smoke.py::test_program_finder_rerun_keeps_tab_content_mapped` finds the
  search box with `app.text_input[0]`. The new question box sits above it, so that lookup
  must become `app.text_input(key="program_query")` (the box already has that key).
  AppTest supports lookup by key.
- The model is in this machine's Hugging Face cache and CI downloads it during the app
  smoke test, so an AppTest that asks a question works in both places; give it
  `default_timeout=120` because the first model load takes about 30 s.
- Permalinks to a PE use the query string `?tab=finder&pe=<pe>&agency=<agency>` with
  `urllib.parse.quote(..., safe="?=&")`, as the T13b change feed does.

**Do (inside `with tab_finder:`, after the header, before the search box):**

```
with st.expander("Ask the justification books", expanded=False):
    st.caption("Searches the R-2 narrative text locally (free). The AI answer is optional and metered.")
    question = st.text_input("Question", key="corpus_question",
                             placeholder="e.g. what is the Army doing on launched effects?")
```

When `question.strip()` is non-empty:

1. `ready = load_corpus_search()`; if not `True`, `st.caption(f"Local passage search is unavailable ({ready}).")` and stop.
2. `passages = narrative_qa.retrieve(question, k=8)` under `st.spinner("Searching narratives...")`.
   If empty, `st.info("No narrative passages matched.")` and stop.
3. Render `with st.expander(f"Passages considered ({len(passages)})")`: one block per
   passage with a markdown line `**PE <pe>** [<agency>] · FY<fy> · <source_file> · score <score:.2f>`
   where the PE is a link to its finder permalink, followed by the passage text via
   `st.write(escape_dollars(text))`. This is local and free; it always renders.
4. `enricher = get_enricher()`. If `None`: `st.caption(_ai_disabled_caption())` and stop.
5. `res = narrative_qa.answer(question, passages, user_id=current_user_id(), allow_fresh=False, enricher=enricher)`.
   If `res.cold`: `st.caption("No saved answer for this question yet.")` and a button
   labelled **"Answer from R-2 narratives (AI)"**; on click, re-call with
   `allow_fresh=True` inside `st.spinner("Reading the passages...")` and render.
   Otherwise render immediately (this is the warm path; the renderer adds the "Saved
   analysis from" caption) and offer a **"Re-answer (AI)"** button that calls with
   `allow_fresh=True, force=True`.
6. Rendering, via `render_ai_result(dataclasses.replace(res, grounded=True), _render_cited_answer, "No answer produced.")`
   where `_render_cited_answer(payload)` rebuilds `CitedAnswer.from_dict(payload)`; if
   `refused`, `st.info(f"No cited answer: {reason}")`; else for each sentence
   `st.markdown(escape_dollars(text))` followed by one caption line per citation in the
   form `PE <pe_number> · FY<fiscal_year> · <source_file>` with the PE linked to its
   permalink, and the quote in an `st.expander("Quoted text")` under it via `st.write`.

Keys: `corpus_question`, buttons keyed `corpus_answer::<sha256(question)[:12]>` and
`corpus_reanswer::<same>` so two questions never share a button state. Do not add a
query parameter for the question. Do not reorder or relabel any `st.tabs()` call.

**Tests (`tests/test_app_smoke.py`):**

- Change the existing `app.text_input[0]` lookup to `app.text_input(key="program_query")`.
- New `test_ask_the_corpus_renders_passages_without_a_key(monkeypatch)`: set
  `HF_HUB_OFFLINE=1`, `monkeypatch.delenv` both `GEMINI_API_KEY` and `GOOGLE_API_KEY`
  (`raising=False`), `AppTest.from_file(..., default_timeout=120)`, query param
  `tab=finder`, run, then `app.text_input(key="corpus_question").input("Skyborg autonomous aircraft vanguard program").run()`;
  assert `not app.exception`; assert some expander label starts with `"Passages considered ("`;
  assert `"0603032F"` appears in the markdown of that expander; assert no button is
  labelled `"Answer from R-2 narratives (AI)"`; assert the main tab labels are unchanged
  and `app.session_state["main_tab"] == "Program Finder"`.

**Definition of done:** with no key, the section retrieves and lists passages and shows
the same disabled-AI caption the News tab shows; with a key, a cold question shows the
"Answer from R-2 narratives (AI)" button and a warm one auto-renders with the "Saved
analysis from" caption; every rendered sentence lists its citations as `PE … · FY… ·
file` with the PE linked; a refusal renders as `st.info` with the reason; the smoke
tests pass; **clicked through in a real browser with AI disabled** (run with
`GEMINI_API_KEY` and `GOOGLE_API_KEY` unset): expander opens, a question lists passages,
the caption appears, the program search box below still works, and the Program Finder
tab stays selected across the rerun.

**Verify:**
```bash
python -m pytest -q
python analysis/ai_budget_eval.py
python -m streamlit run app.py --server.port 8501     # then click through as described above and describe what you saw
```

### T14d — Thinking budget for cited answers

**Files:** `analysis/oss_enricher.py` (a private helper shared by `extract_facts` and
`narrative_answer`, and the `narrative_answer` request config), `analysis/ai_budget_eval.py`
(two checks). Nothing else: no change to `PROMPT_VERSIONS` (the prompt and output shape
are unchanged, so cached v1 answers stay valid), no change to `app.py`, `config.py`, or
`analysis/narrative_qa.py`.
**Depends on:** T14c and T15b merged (they are).
**Written 2026-09-19.**

**Verified facts:**

- The only live `narrative_answer` call so far (T14c browser check, 2026-09-19,
  gemini-3.6-flash, 8 passages) billed 2,828 input, 555 output, and **2,491 thinking
  tokens** for $0.0135. Thinking is billed at the output rate, so it was about 70% of
  the cost. The request config sets `response_mime_type`, `response_schema`, and
  `temperature=0.0` only; no `thinking_config`, no `max_output_tokens`.
- `extract_facts` (T15b) already caps thinking with
  `types.ThinkingConfig(thinking_budget=512)` and, on a `google.genai.errors.ClientError`
  with `code == 400`, retries once with `types.ThinkingConfig(thinking_level="low")`.
  Over 50 live calls the largest observed thinking count was 571 (the budget is
  approximate, not a hard ceiling), and no fallback fired.
- `google-genai` 2.19.0: `types.ThinkingConfig` has `include_thoughts`,
  `thinking_budget`, `thinking_level`; `types.GenerateContentConfig` accepts
  `thinking_config` and `max_output_tokens`.
- `analysis/ai_budget_eval.py` drives the enricher with a fake client whose
  `generate_content(self, **kw)` receives the `config` object; a check can capture
  `kw["config"]` and inspect `.thinking_config.thinking_budget`.

**Do:**

1. Extract the try/except-400 fallback in `extract_facts` into a private method
   `_generate_with_thinking(self, *, contents, base_config: dict, thinking_budget: int)`
   that builds `types.GenerateContentConfig(**base_config,
   thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget))`, calls
   `self.client.models.generate_content(model=self.model, contents=contents, config=…)`,
   and on `errors.ClientError` with `code == 400` logs a warning and retries once with
   `thinking_level="low"`. `extract_facts` calls it with `thinking_budget=512` and its
   existing base config (behaviour unchanged).
2. `narrative_answer` calls it with `thinking_budget=1024` and base config
   `{"response_mime_type": "application/json", "response_schema": ANSWER_SCHEMA,
   "temperature": 0.0, "max_output_tokens": 2048}`. Rationale in a comment: synthesis
   with verbatim quotes needs some reasoning, so twice the extraction budget; 2,048 output
   tokens comfortably holds six sentences with quotes.
3. Eval checks: install a capturing fake `generate_content` for one `narrative_answer`
   call with `force=True` and assert the captured config has
   `thinking_config.thinking_budget == 1024` and `max_output_tokens == 2048`; do the same
   for one `extract_facts` call asserting `thinking_budget == 512`. Keep every existing
   check passing (the capturing fake must still return the same fake response objects).

**Definition of done:** both methods go through the shared helper; the two eval checks
pass and the eval stays at 100%; `python -m pytest -q` passes; one live `narrative_answer`
call made with `force=True` on the Skyborg golden question (this machine has a key)
returns a non-refused answer with at least two cited sentences, and its `ai_spend` row
shows `thought_tokens <= 1200` and `est_cost_usd < 0.01`. Paste that row. Expected: about
$0.008 against the $0.0135 baseline. If the live answer comes back refused or uncited,
report it and stop; do not raise the budget to make it pass.

**Verify:**
```bash
python -m pytest -q
python analysis/ai_budget_eval.py
python - <<'PY'
import sys; sys.path.insert(0, '.')
from analysis.narrative_qa import retrieve, answer, CitedAnswer
from analysis.ai_budget import session_factory, AISpend
from sqlalchemy import select
q = "Skyborg autonomous aircraft vanguard program"
res = answer(q, retrieve(q, k=8), user_id="t14d-check", allow_fresh=True, force=True)
a = CitedAnswer.from_dict(res.payload) if res.payload else None
print("blocked", res.blocked, "| refused", a.refused if a else None, "| sentences", len(a.sentences) if a else 0)
with session_factory()() as s:
    row = s.execute(select(AISpend).where(AISpend.task == "narrative_answer").order_by(AISpend.id.desc())).scalars().first()
    print("input", row.input_tokens, "output", row.output_tokens, "thought", row.thought_tokens, "usd", round(row.est_cost_usd, 4))
PY
```

### T15a — Structured-fact schema

**Files:** `storage/db.py` (the model, a `FactType` alias, and a `FACT_TYPES` tuple),
`tests/test_regressions.py` (one new test class), `DATA_DICTIONARY.md` (one new table
section, one row in the row-count table, one sentence in the header), `CODEX_HANDOFF.md`
§1 (the "Tables" row). **Not** `scripts/build_release.py` and **not** the archive: the
release script counts every table in its `DATA_TABLES` tuple against the decompressed
tracked archive, and this task does not rebuild the archive, so adding the table there
would make the release script fail on a table the archive does not have. T15b, which
writes rows and rebuilds the archive, adds it to `DATA_TABLES` and to the release
manifest.
**Depends on:** nothing.
**Rewritten 2026-09-19** against the repo: the first version was a field list with a
two-line definition of done. It implied a foreign key to two tables (impossible), named
no hash rule (so T15b's idempotency would have been improvised), and did not say how the
new table reaches an existing database or the documentation.

**Verified facts (2026-09-19):**

- `storage/db.get_engine()` calls `_ensure_schema_compatibility`, which starts with
  `Base.metadata.create_all(engine)`. A new model therefore appears in any existing
  database the first time the app or a script opens it. No migration code is needed for
  a new table; the additive-column logic in that function is for existing tables only.
- The shipped archive (`f2aa7a54…`, 13 tables) is not rebuilt by this task. A freshly
  opened database has 14 tables; the archive keeps 13 until T15b rebuilds it. Say
  exactly that in `DATA_DICTIONARY.md`.
- Model conventions (`PELineage` is the template): `id` autoincrement primary key,
  `content_hash: String(64), unique=True, index=True`, a UTC timestamp column with
  `default=_utcnow`. `storage/db.py` imports `Float, ForeignKey, Integer, String, Text,
  UniqueConstraint` from SQLAlchemy and `List, Optional` from `typing`; add `Index` and
  `Literal` as needed.
- `tests/test_regressions.py` is `unittest`-style with one class per concern;
  `ProcurementSchemaRegressionTests.test_compatibility_migrates_and_enforces_row_identity`
  already shows the pattern of building a database that lacks something, then opening it
  through `get_engine()` to prove the compatibility step fixes it. Mirror it.
- `pe_narratives.id` and `pe_accomplishments.id` are both integer primary keys; a fact
  may come from either, so the reference is a `(narrative_table, narrative_id)` pair, not
  a foreign key.

**Model (in `storage/db.py`, after `PELineage`):**

```python
FactType = Literal["contractor", "transition", "test_event", "location"]
FACT_TYPES: tuple[str, ...] = ("contractor", "transition", "test_event", "location")

class NarrativeFact(Base):
    """One structured fact extracted from a narrative sentence (T15b fills it)."""
    __tablename__ = "narrative_facts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    narrative_table: Mapped[str] = mapped_column(String(30))     # "pe_narratives" | "pe_accomplishments"
    narrative_id: Mapped[int] = mapped_column(Integer)           # that table's id; no FK, see docstring
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fact_type: Mapped[str] = mapped_column(String(20))           # one of FACT_TYPES
    value: Mapped[str] = mapped_column(String(500))              # normalised, e.g. "Lockheed Martin"
    sentence: Mapped[str] = mapped_column(Text)                  # verbatim sentence the fact came from
    char_start: Mapped[int] = mapped_column(Integer)             # offsets of `sentence` in the source text
    char_end: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))              # config.GEMINI_MODEL at extraction time
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    extracted_at: Mapped[datetime] = mapped_column(default=_utcnow)

    __table_args__ = (
        Index("ix_narrative_facts_source", "narrative_table", "narrative_id"),
    )
```

Add a module-level helper next to the model so T15b and the test agree on the hash:

```python
def narrative_fact_hash(narrative_table: str, narrative_id: int, fact_type: str,
                        value: str, char_start: int, char_end: int) -> str:
    """sha256 over the tab-joined identity fields; the idempotency key for T15b."""
```

(`"\t".join([narrative_table, str(narrative_id), fact_type, value, str(char_start),
str(char_end)])`, UTF-8, hex digest.)

**Test (`tests/test_regressions.py`, new class `NarrativeFactSchemaRegressionTests`):**

1. In a temporary directory, create a SQLite file with every model **except**
   `narrative_facts` (`Base.metadata.create_all(engine, tables=[t for t in
   Base.metadata.sorted_tables if t.name != "narrative_facts"])`), dispose, then open
   it with `get_engine(f"sqlite:///{path}")` and assert
   `inspect(engine).has_table("narrative_facts")`. This is "schema creates on an
   existing DB".
2. Round trip on an in-memory database: insert one `PENarrative` (with a `description`
   of two sentences), then one `NarrativeFact` whose `narrative_table` is
   `"pe_narratives"`, `narrative_id` is that row's id, `sentence` equals
   `description[char_start:char_end]`, `fact_type` is `"contractor"`, and
   `content_hash` comes from `narrative_fact_hash(...)`. Read it back and assert every
   field, and assert `description[char_start:char_end] == fact.sentence`.
3. Inserting a second fact with the same `content_hash` raises `IntegrityError`.
4. `set(FACT_TYPES) == {"contractor", "transition", "test_event", "location"}`.

**Docs:** `DATA_DICTIONARY.md` gains a `## narrative_facts` section after `pe_lineage`
with the column table in the same format, a first paragraph saying it is created by
`create_all` on first open, has 0 rows, and is absent from the tracked archive until
T15b rebuilds it; one row in the row-count table (`narrative_facts | 0 (not yet in the
archive) | Derived by T15b extraction`); and the header sentence "The archive contains 13
tables and 43 indexes." extended with "A freshly opened database also creates the empty
`narrative_facts` table (14)." `CODEX_HANDOFF.md` §1 "Tables" row gains
`narrative_facts` (T15a; 0 rows, not in the archive until T15b).

**Definition of done:** the model and helper exist as specified; the four test cases
pass; `python -m pytest -q` passes; opening the working database prints `True` for the
table (verify command below); the two documents are updated; `git status --short` after
the commit lists nothing; the archive blob and `scripts/build_release.py` are unchanged.

**Verify:**
```bash
python -m pytest -q
python -c "import sys; sys.path.insert(0,'.'); from sqlalchemy import inspect; from storage.db import get_engine; import config; e=get_engine(f\"sqlite:///{(config.PROCESSED_DIR/'usg_budgets.db').as_posix()}\"); print(inspect(e).has_table('narrative_facts'))"   # True
git diff --stat HEAD~1 -- dod_ic_budget_analyzer/data/processed/usg_budgets.db.gz dod_ic_budget_analyzer/scripts/build_release.py   # expect no output
git status --short
```

### T15b — Batch extraction job

**Files:** new `analysis/narrative_extract.py`, new `tests/test_narrative_extract.py`,
`storage/db.py` (one new model, `NarrativeExtraction`), `analysis/oss_enricher.py` (new
`GeminiEnricher.extract_facts()` method, `EXTRACTION_SCHEMA`, `PROMPT_VERSIONS` entry),
`config.py` (one `AI_CACHE_TTL_DAYS` entry), `analysis/ai_budget_eval.py` (governance
checks), `scripts/build_release.py` (`DATA_TABLES` gains `narrative_facts` and
`narrative_extractions`), `data/processed/usg_budgets.db.gz` (rebuilt after the real
run), `DATA_DICTIONARY.md`, `CODEX_HANDOFF.md` §1, `README.md` (one paragraph under
`## Updating the data`). Do not touch `app.py` or `analysis/ai_budget.py`.
**Depends on:** T15a merged (it is: commit `d15874f`).
**Rewritten 2026-09-19** against the repo and against a measured live call. The first
version said "mirror `ai_precompute.py`" and "re-running skips already-extracted
narratives" without saying how, and its cost estimate ignored that thinking tokens were
70% of the only real call made so far.

**Verified facts (2026-09-19):**

- Corpus: `pe_narratives` has 18,268 rows, 14,737 distinct texts, 31.0 M characters
  (about 7.7 M input tokens at 4 characters per token). PE-level rows
  (`project_number == ""`) alone: 4,988 distinct texts, 14.9 M characters (about 3.7 M
  tokens). `pe_accomplishments` has 74,849 distinct texts, 37.5 M characters, and is
  **out of scope** for this task (report it as the follow-up).
- Measured cost anchor (T14c live check, gemini-3.6-flash): one call with 2,828 input,
  555 output, and **2,491 thinking tokens** cost $0.0135; thinking was ~70% of it.
  `analysis.ai_budget.token_cost(model, input_tokens, output_tokens, thought_tokens=…)`
  already bills thinking at the output rate. Use it for the estimate; do not re-derive
  prices.
- `google-genai` 2.19.0 is installed. `types.GenerateContentConfig` accepts
  `thinking_config=types.ThinkingConfig(thinking_budget=<int>)` and `max_output_tokens`.
  Extraction is structured recall, not reasoning; cap thinking. If the API rejects
  `thinking_budget` for this model, fall back to `thinking_level="low"` and say so in
  the report; if it rejects both, stop and report.
- The governed path (`GeminiEnricher._governed`) never caches an empty payload, and
  `analysis.ai_budget --reset-runtime` clears `ai_cache` before every archive build.
  **Therefore the AI cache cannot be the resumability record.** A narrative that yields
  zero facts must still be marked done somewhere durable, or every rerun re-pays for it.
  That is what the new `narrative_extractions` table is for.
- `config.AI_MONTHLY_BUDGET_USD` is 25.0 and `budget_guard` refuses fresh calls at the
  ceiling; `ai_precompute.run()` shows the pattern: check the guard once before starting,
  pass `credits=len(work) + 1`, and stop on the first `blocked` result.
- `narrative_facts` (T15a) is created by `create_all` on open, has 0 rows, and is not in
  the archive; `scripts/build_release.py::DATA_TABLES` does not list it yet (adding it
  before the archive is rebuilt would break the release script).

**New model (`storage/db.py`, after `NarrativeFact`, same style):**

```python
class NarrativeExtraction(Base):
    """One completed extraction call per narrative text, whether or not it yielded facts."""
    __tablename__ = "narrative_extractions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    narrative_table: Mapped[str] = mapped_column(String(30))
    narrative_id: Mapped[int] = mapped_column(Integer)
    text_hash: Mapped[str] = mapped_column(String(64))       # sha256 of the source text
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int] = mapped_column(Integer)
    fact_count: Mapped[int] = mapped_column(Integer)
    dropped_count: Mapped[int] = mapped_column(Integer)      # facts whose sentence was not verbatim
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    thought_tokens: Mapped[int] = mapped_column(Integer)
    est_cost_usd: Mapped[float] = mapped_column(Float)
    extracted_at: Mapped[datetime] = mapped_column(default=_utcnow)
    __table_args__ = (UniqueConstraint("narrative_table", "narrative_id", "model", "prompt_version"),)
```

**Task:** `extract_facts`, `PROMPT_VERSIONS["extract_facts"] = 1`,
`config.AI_CACHE_TTL_DAYS["extract_facts"] = 365`, not in `GROUNDED_TASKS`.

`GeminiEnricher.extract_facts(narrative_table, narrative_id, text, *, user_id="extract",
allow_fresh=True, credits=None)` (pattern `adjudicate`): `params = {"table":
narrative_table, "id": narrative_id, "text": sha256(text)[:16]}`. Prompt: the model is
given one narrative and must return facts of the four types in `storage.db.FACT_TYPES`,
each with a `value` (normalised: organisation name for `contractor`, the receiving
programme or organisation for `transition`, the event name for `test_event`, the place
for `location`) and the **verbatim sentence** the fact came from; return an empty list
when there are none; never invent. `EXTRACTION_SCHEMA`: `OBJECT{facts: ARRAY of
OBJECT{fact_type: STRING, value: STRING, sentence: STRING}}`, `facts` required.
`GenerateContentConfig(response_mime_type="application/json",
response_schema=EXTRACTION_SCHEMA, temperature=0.0, max_output_tokens=1024,
thinking_config=types.ThinkingConfig(thinking_budget=512))`. `call()` returns
`({"facts": <the parsed list, unfiltered>}, _usage(resp))` — a dict, so it is non-empty
and cacheable even when the list is empty. Verification of sentences happens in the
batch job, not in the enricher, so the raw model output stays inspectable.

**Batch job (`analysis/narrative_extract.py`), pure functions plus `main()`:**

- `text_hash(text) -> str` (sha256 hex).
- `locate_sentence(text, sentence) -> tuple[int, int] | None`: `text.find(sentence)`;
  if `-1`, retry with both sides whitespace-normalised by mapping the match back to the
  original offsets (or return `None` if you cannot map exactly). The returned span must
  satisfy `text[start:end] == sentence_as_stored`. No fuzzy matching.
- `verify_facts(raw_facts, text) -> tuple[list[dict], int]`: keeps facts whose
  `fact_type` is in `FACT_TYPES`, whose `value` is non-empty after strip, and whose
  sentence locates; returns `(kept, dropped_count)`; each kept fact carries
  `char_start`, `char_end`, and the `sentence` exactly as it appears in `text`.
- `build_worklist(session, *, limit, fiscal_year=None) -> list[dict]`: PE-level
  narratives (`project_number == ""`) ordered `fiscal_year DESC, pe_number, agency, id`,
  one per distinct `(pe_number, agency, text_hash)` keeping the first (latest book),
  **excluding** any whose `(narrative_table, narrative_id)` or, more usefully, whose
  `text_hash` already appears in `narrative_extractions` for the current model and
  prompt version. Each item: `{"narrative_table": "pe_narratives", "narrative_id",
  "pe_number", "agency", "fiscal_year", "text"}`.
- `estimate_cost(work, model=config.GEMINI_MODEL) -> dict`: per item `input =
  len(text) // 4 + 300` (prompt overhead), `output = 200`, `thought = 512` (the budget
  cap, i.e. the worst case), summed through `token_cost`; returns
  `{"items", "input_tokens", "output_tokens", "thought_tokens", "usd"}`. Print all five
  and the assumptions on a dry run.
- `write_results(session, item, kept, dropped, usage, cost) -> int`: inserts one
  `NarrativeFact` per kept fact (skip any whose `narrative_fact_hash` already exists)
  and one `NarrativeExtraction` row; commits; returns the number of facts inserted.
- `run(limit, dry_run, fiscal_year) -> int`: build the worklist; print its size and the
  estimate; on `--dry-run` stop there with **zero API calls and zero writes**. Otherwise
  require `oss_enricher.available()`, check `budget_guard("extract_facts",
  user_id="extract")` once, then loop: call `extract_facts`, `verify_facts`,
  `write_results`; print one line per narrative (`fresh|cached`, facts kept, dropped,
  running spend); stop on the first `blocked` result; finish by printing the totals and
  `ai_budget.report()`.
- CLI: `python -m analysis.narrative_extract --dry-run [--limit N] [--fiscal-year YYYY]`
  and `python -m analysis.narrative_extract --run --limit N [--fiscal-year YYYY]`.
  Default limit 50. `--run` without `--limit` refuses: "Pass --limit; the whole corpus
  is about 3.7 M input tokens and would exceed the monthly ceiling."

**Governance checks (`analysis/ai_budget_eval.py`, fake client, scratch DB):**
`"extract_facts" not in config.GROUNDED_TASKS`; a fake response with one verbatim
sentence and one non-verbatim sentence, driven through `run`-level helpers
(`verify_facts` + `write_results` on the scratch session): one `NarrativeFact` row, one
`NarrativeExtraction` row with `fact_count=1, dropped_count=1`; a second
`build_worklist` on the same session excludes that narrative (zero calls); the ledger
holds one `extract_facts` row with `thought_tokens` recorded; the shared table still has
no grounded tasks.

**Tests (`tests/test_narrative_extract.py`, pure, no key):** `locate_sentence` exact
hit, whitespace-normalised hit mapped to exact offsets, miss -> `None`; `verify_facts`
drops an unknown `fact_type`, an empty value, and an unlocatable sentence, keeps the
rest with correct offsets; `estimate_cost` on two known texts equals the hand-computed
`token_cost` sum; `build_worklist` on an in-memory session with two PE-level narratives
sharing one text and one project-level narrative returns one item, and returns zero
after a `NarrativeExtraction` row for that `text_hash` is inserted; `write_results` twice
with the same facts inserts once.

**Real run and archive (the part that spends money):** `--dry-run --limit 50` first and
paste the estimate. Then `--run --limit 50`. Expected spend: the estimate's worst case
is about 50 × (input ~800 + output 200 + thinking 512 tokens) ≈ **$0.06 to $0.10**; the
actual figure prints from the ledger. Then, in this order: `python -m analysis.ai_budget
--reset-runtime`, `python -m storage.build_archive`, update `DATA_DICTIONARY.md` (new
`narrative_extractions` section, both tables' row counts, "15 tables", the new archive
blob hash and commit in the header, and remove the "not yet in the archive" wording),
`CODEX_HANDOFF.md` §1, and add both tables to `DATA_TABLES` in
`scripts/build_release.py`. Commit message states `narrative_facts 0 -> N`,
`narrative_extractions 0 -> 50`, and the spend.

**Definition of done:** dry run makes zero API calls and prints the estimate with its
assumptions; the real run of 50 writes facts whose `sentence` equals
`text[char_start:char_end]` (asserted in `write_results` before insert); every call is
in `ai_spend` with thinking tokens recorded; a second `--dry-run --limit 50` after the
run lists 50 **different** narratives (the first 50 are skipped via
`narrative_extractions`); the task is not grounded; `python analysis/ai_budget_eval.py`
and `python -m pytest -q` pass; the archive is rebuilt and both docs and the release
script reflect it; `python scripts/build_release.py --date 2099-01-01` succeeds against
the new archive (then delete that bundle directory).

**Verify:**
```bash
python -m pytest -q
python analysis/ai_budget_eval.py
python -m analysis.narrative_extract --dry-run --limit 50
python -m analysis.narrative_extract --run --limit 50
python -m analysis.narrative_extract --dry-run --limit 50        # different 50; zero already-done
python -c "import sqlite3; c=sqlite3.connect('data/processed/usg_budgets.db'); print(c.execute('select count(*) from narrative_facts').fetchone()[0], c.execute('select count(*) from narrative_extractions').fetchone()[0], c.execute(\"select count(*) from ai_cache where task in ('find_open_source_hits','annual_signal')\").fetchone()[0])"
python -m analysis.ai_budget --reset-runtime
python -m storage.build_archive
python scripts/build_release.py --date 2099-01-01 && python -c "import shutil; shutil.rmtree('../release/usg-budgets-2099-01-01')"
git status --short
```

---

### T15c — Verified facts panel

**Files:** `app.py` (Program Finder → Plans & Work sub-tab, one new expander; Data
Coverage tab, one caption line and one cached query), `tests/test_app_smoke.py` (one new
test). Nothing else: no schema, no extraction, no new tabs.
**Depends on:** T15b merged (it is: archive blob `8b89d309…`, 25 facts, 50 extractions).
**Written 2026-09-19.**

**Verified facts (shipped archive, 2026-09-19):**

- `narrative_facts` has 25 rows over 9 PEs: `0101226N` Navy 9 (Submarine Acoustic
  Warfare Development; 66 funding lines, 10 narratives), `0203752A` Army 4, and seven
  PEs with 1–2. Types: `test_event` 12, `contractor` 6, `transition` 5, `location` 2.
  Every row has `fiscal_year` 2027, `narrative_table == "pe_narratives"`, and
  `sentence == description[char_start:char_end]` (verified 25/25 at T15b review).
- `narrative_extractions` has 50 rows, one per PE-level FY2027 narrative, out of **4,988**
  distinct PE-level narrative texts (`SELECT COUNT(DISTINCT description) FROM
  pe_narratives WHERE project_number = ''`). Coverage is therefore about 1%, and the
  panel must say so rather than let an empty panel read as "no facts exist".
- The Plans & Work block (`with sub_plans:` in `app.py`) first shows `st.info` when a PE
  has neither narratives nor accomplishments, else the mission description expander, a
  projects expander, and the accomplishments picker. Facts derive from narratives, so
  the new expander goes at the **end of the `else:` branch**, after the accomplishments
  section and before the `# --- Contracts & Awards ---` comment.
- `render_table_downloads(df, name=, key=, sources=)` and `fetch_funding_sources(...)`
  exist; R-2 books are not registered in `source_documents` (T11c finding), so the
  book filename is shown as a column and the provenance block lists the program's R-1
  sources plus a note.
- The Data Coverage tab computes `fetch_coverage_stats()` (a dict of scalar SQL counts)
  and prints a procurement coverage caption after the five metrics. Add the facts
  counts to that dict and one caption after the procurement one.
- `0603032F` Air Force has narratives (Skyborg) and **no** facts: the "not yet
  extracted" case. `0101226N` Navy is the "has facts" case.

**Do (Plans & Work):**

```
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_narrative_facts(pe_number: str, agency: str) -> list[dict]:
    # rows of narrative_facts for the PE joined to pe_narratives on narrative_id for source_file,
    # ordered by fact_type, fiscal_year desc, value; keys: fact_type, value, fiscal_year,
    # sentence, source_file, char_start, char_end
```

Then, inside the `else:` branch after the accomplishments section:

- `facts = fetch_narrative_facts(...)`; `coverage = fetch_coverage_stats()`.
- If `facts` is empty: `st.caption(f"Structured facts have not yet been extracted for this program. Extraction has covered {coverage['fact_extractions']:,} of {coverage['pe_level_narratives']:,} program-level narratives so far.")`.
- Otherwise `with st.expander(f"Verified facts ({len(facts)}) — extracted from the justification text (inference)")`:
  a caption: "Each fact was pulled by the AI extraction job and kept only when its
  sentence is a verbatim span of the source narrative. Extraction has covered N of M
  program-level narratives so far."; a `st.dataframe` with columns Type (map
  `contractor`→"Contractor", `transition`→"Transition", `test_event`→"Test event",
  `location`→"Location"), Value, FY, Source book (`source_file`); then
  `with st.expander("Source sentences")`: for each fact `st.markdown(f"**{value}** · {Type} · FY{fy}")`
  and `st.caption(escape_dollars(sentence))`; then `render_table_downloads(table,
  name=f"{pe}_facts", key=f"facts::{pe}::{agency}", sources=include_deflator_source(
  fetch_funding_sources(pe_numbers=(pe,), agencies=(agency,))))` and a caption "Source
  books are named in the table; they are not yet registered as source documents."

**Do (Data Coverage):** add to `fetch_coverage_stats()` the keys `narrative_facts`
(`COUNT(*) FROM narrative_facts`), `fact_extractions` (`COUNT(*) FROM
narrative_extractions`), `fact_pes` (`COUNT(DISTINCT pe_number || agency) FROM
narrative_facts`), and `pe_level_narratives` (the distinct-description count above; it
takes about 50 ms on the shipped database, acceptable under the existing 1-hour cache).
After the procurement caption: `st.caption(f"Verified facts: {narrative_facts:,} facts on
{fact_pes:,} programs, from {fact_extractions:,} of {pe_level_narratives:,} program-level
narratives extracted so far.")`. Use these same keys in the Plans & Work captions so the
numbers cannot drift apart.

**Test (`tests/test_app_smoke.py`, `test_verified_facts_panel_states(monkeypatch)`):**
`HF_HUB_OFFLINE=1`, `default_timeout=120`; render with query params `tab=finder`,
`pe=0101226N`, `agency=Navy`, `view=plans`; assert no exception, main and profile tab
labels unchanged, `session_state["main_tab"] == "Program Finder"`; assert some expander
label starts with `"Verified facts ("`; assert a dataframe inside the Plans & Work tab
contains `"Developmental Testing"`. Render again with `pe=0603032F`, `agency=Air Force`,
`view=plans`; assert a caption in that tab contains `"not yet been extracted"`. Render
`tab=coverage` and assert a caption contains `"Verified facts:"`.

**Definition of done:** the two Plans & Work states and the coverage caption render as
specified from the shipped archive; the same coverage keys feed both places; no tab
label or order changes; `python -m pytest -q` passes; clicked through in a real browser
on PE 0101226N (Navy) and PE 0603032F (Air Force) under Plans & Work, plus the Data
Coverage tab, with the Program Finder tab staying selected across the reruns.

**Verify:**
```bash
python -m pytest -q
python -c "import sys; sys.path.insert(0,'.'); import sqlite3, config; c=sqlite3.connect(str(config.PROCESSED_DIR/'usg_budgets.db')); print(c.execute('select count(*) from narrative_facts').fetchone()[0], c.execute('select count(*) from narrative_extractions').fetchone()[0], c.execute(\"select count(distinct description) from pe_narratives where project_number=''\").fetchone()[0])"   # 25 50 4988
python -m streamlit run app.py --server.port 8501     # click through as described
```

---

## Phase H — Product polish

### T16a — Vocabulary, density, and theme pass

**Files:** `app.py` (labels, captions, one badge helper, CSS additions, title),
`tests/test_app_smoke.py` (label constants and assertions listed below), root
`.streamlit/config.toml` (a `[theme]` section), `README.md` (the "What it does" table
rows use the new tab names). **Not** `analysis/primer.py` (bodies stay; only the titles
in `app.py` change), not `AGENTS.md`, not any `st.tabs()` key, query-parameter value,
session-state key, or tab **order**. Labels change; mechanics do not.
**Depends on:** T15c merged (it is: commit `149c314`).
**Written 2026-09-20** from a full inventory of `app.py` (2,930 lines; 4 tabs + 4
sub-tabs; 28 section titles; 6 primer titles; 10 buttons; 46 captions; 18 info boxes).

**Why:** the app reads as a notebook. Section titles are questions or sentences,
qualifiers like "(AI)" and "(inference)" sit inside titles, and about 500 words of
captions plus 1,350 words of primers compete with the data. This task changes words and
density only. Structure (tabs within tabs) is T16b.

**Rules the whole task follows:**

1. **Titles are noun phrases**, two to four words, no question marks, no parentheses,
   no arrows. Counts stay in the title (`Projects (3)`).
2. **Qualifiers become badges.** Add `render_badge(text: str)` in `app.py`: one
   `st.markdown(f'<span class="badge">{text}</span>', unsafe_allow_html=True)` styled by
   a `.badge` rule added to the existing `<style>` block (inline-block, 0.72rem,
   uppercase, letter-spacing 0.04em, 2px 8px padding, 999px radius, background
   `var(--secondary-background-color)`, 1px border `rgba(0,0,0,0.12)`). Badge texts used:
   `Inference`, `AI estimate`, `AI-extracted`, `Live query` (four uses). A badge renders on
   the line directly under the section title, never inside it. The honesty content is
   unchanged; only its placement.
3. **Captions are one sentence, at most 20 words.** Anything longer either becomes the
   first sentence plus a `help=` tooltip, or moves into the nearest primer body, per the
   table below. Primers keep their bodies.
4. **Buttons name their source without parentheses.** This keeps the repo rule that a
   billable or external call is behind a button naming its source.
5. Permalinks, `st.tabs` keys (`trends`, `finder`, `rhetoric`, `coverage`; `funding`,
   `plans`, `awards`, `news`), state keys, and tab order are untouched. Only the label
   strings in `tab_definitions` and `profile_definitions` change.

**Tab labels** (`tab_definitions` at `app.py` ~L835, `profile_definitions` ~L1336):

| Key | Before | After |
|---|---|---|
| trends | Budget Trends | Trends |
| finder | Program Finder | Programs |
| rhetoric | Rhetoric vs. Budget | Rhetoric vs. Budget (unchanged) |
| coverage | Data Coverage | Coverage |
| funding | Funding | Funding (unchanged) |
| plans | Plans & Work | Justification |
| awards | Contracts & Awards | Awards |
| news | In the News | News |

**Section titles** (line numbers as of `149c314`; match by text, not line):

| Line | Before | After | Badge under it |
|---|---|---|---|
| 811 | `st.title("🇺🇸 DoD Budget Explorer")` | `st.title("DoD Budget Explorer")` + `st.caption("Official DoD budget data, FY1996–FY2027.")` | — |
| 866 | RDT&E topline by component | RDT&E topline by component | — |
| 952 | Who got paid — account-level obligations | Obligations by recipient | Live query |
| 999 | What changed | Changes between submissions | — |
| 1088 | Find a program (header) | remove the header; the search box is the section | — |
| 1089 | Ask the justification books | Ask the justification books | — |
| 1113 | Passages considered (n) | Passages (n) | — |
| 1619 | Lineage evidence: A → B (relation, FYyyyy) | Evidence: A → B | — |
| 1675 | Underlying funding table | Funding table | — |
| 1696 | Did it transition to procurement? (inference) | Procurement transition | Inference |
| 1776 | Execution: request to net current program | Execution | — |
| 1834 | Execution data table | Execution table | — |
| 1880 | Program mission description (PBxxxx) | Mission description (PBxxxx) | — |
| 1888 | Projects under this program (n) | Projects (n) | — |
| 1955 | Verified facts (n) — extracted from the justification text (inference) | Extracted facts (n) | AI-extracted |
| 2286 | What Congress authorized | Authorization | — |
| 2410 | Line-by-line committee actions | Committee actions | — |
| 2468 | Request → authorization → execution | Funding chain | — |
| 2567 | Open-source emphasis (AI) | Public emphasis | AI estimate |
| 2814 | What this tool covers | Coverage | — |
| 2898 | Does it tie? | Reconciliation | — |

Unchanged: `Quoted text`, `Source documents`, `Data table`, the change-feed kind
expanders, `Evidence: {bli}`, `Source sentences`, `Rhetoric vs. budget`, `Methodology &
caveats`.

**Primer titles** (`render_primer(...)` calls):

| Before | After |
|---|---|
| How to read this program's funding | Reading this chart |
| What each step means, and why the numbers differ | About execution figures |
| Why awards never tie to the budget figures | About award data |
| Authorization versus appropriation | Authorization versus appropriation |
| What each stage means | About the funding chain |
| How the numbers relate: program elements, projects, request, authorization, appropriation, execution, and awards | How the numbers relate |

**Buttons:**

| Before | After |
|---|---|
| Look up obligations (USAspending.gov) | Load USAspending obligations |
| Answer from R-2 narratives (AI) | Answer with AI |
| Re-answer (AI) | Regenerate with AI |
| Resolve ambiguous match (AI) | Resolve with AI |
| Search awards (USAspending.gov) | Search USAspending awards |
| Search subawards (umbrella vehicles) | Search USAspending subawards |
| Search recent coverage (AI + Google Search) | Search the web with AI |
| Refresh coverage (AI + Google Search) | Refresh web search |

`Sign in` / `Sign out` unchanged. Where a button's old label carried information the new
one drops (subawards = umbrella vehicles; web search = Google Search, results are
per-user), that sentence becomes the caption directly under the button, within the
20-word rule.

**Captions and info boxes over 20 words** (word counts from the inventory):

| Line | Words | Action |
|---|---|---|
| 923, 1583 | 23, 25 | Keep "Each year shows its most reliable figure." Move the precedence rule into `help=` on the chart's primer title, or into the "Reading this chart" primer body. |
| 977 | 22 | Keep; trim the 90-day sentence to "DoD awards post with about a 90-day delay." |
| 1000 | 25 | "Discretionary R-1 lines from two PB submissions; swings of 20% or more are material." |
| 1699 | 19 | Keep as is (already under 20). |
| 1820 | 29 | Move whole text into the "About execution figures" primer body; replace with "Above-threshold moves needed congressional approval; below-threshold did not." |
| 1959 | 33 | "Each fact's sentence is a verbatim span of the source narrative. Coverage: {n} of {m} program-level narratives." |
| 2032 (info) | 56 | Replace the info box with `st.info("No prime awards matched this program's keywords in FY{fy}.")` followed by `with st.expander("Why awards can be missing"):` holding the rest verbatim. |
| 2073 | 22 | "Keyword-matched DoD prime awards. Treat as leads, not a ledger." |
| 2550 | 35 | Move into the "About the funding chain" primer body; replace with "House and Senate are shown separately; enacted and net figures come from DD 1416." |
| 2570 | 51 | Replace with `_ai_disabled_caption()` (it exists; same text the News tab shows). |
| 2846 | 23 | "AI features are off in this instance; everything shown comes from the local database and USAspending.gov." |
| 2901 | 47 | Keep "Tolerance ±0.5%." and move the account-exclusion detail into `with st.expander("Reconciliation notes"):` verbatim. |
| 2918 | 22 | "Tolerance ±0.5%. The latest DD 1416 enacted total is compared with the next-cycle R-1 request." |
| 1867 (info) | 22 | "No justification narrative for this program; R-2 coverage varies by component and year." |

Every other caption stays. Do not delete any caption that states coverage or a
limitation; shorten it.

**Theme** (`.streamlit/config.toml` at the repository root, which Community Cloud reads;
keep the existing `[server]` block):

```toml
[theme]
base = "light"
primaryColor = "#1f4e79"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f3f5f8"
textColor = "#1b1f24"
font = "sans serif"
```

Streamlit 1.55 (pinned minimum) accepts exactly these keys. Do not use newer keys such
as `headingFont` or `baseRadius`.

**Tests (`tests/test_app_smoke.py`), every change listed:**

- `MAIN_TAB_LABELS = ["Trends", "Programs", "Rhetoric vs. Budget", "Coverage"]`;
  `PROFILE_TAB_LABELS = ["Funding", "Justification", "Awards", "News"]`.
- `test_default_page_renders_data_not_just_imports`: tab label `"Coverage"`; the
  subheader check becomes `"Reconciliation" in header.value`.
- `test_program_finder_rerun_keeps_tab_content_mapped`: `session_state["main_tab"] ==
  "Programs"`; `session_state["profile_tab::0601102A::Army"] == "Justification"`.
- `test_ask_the_corpus_renders_passages_without_a_key`: expander prefix `"Passages ("`;
  absent button label `"Answer with AI"`; `main_tab == "Programs"`.
- `test_transition_panel_renders_inference_label`: expander label `== "Procurement
  transition"`; assert some `app.markdown` value contains `>Inference<` (the badge);
  Funding tab label unchanged; `main_tab == "Programs"`.
- `test_verified_facts_panel_states`: tab label `"Justification"`; expander prefix
  `"Extracted facts ("`; coverage tab label `"Coverage"`; coverage caption contains
  `"Extracted facts:"` (rename that caption's leading words accordingly in `app.py`).
- Add `test_no_parenthetical_qualifiers_in_labels`: read `app.py` and assert the
  strings `"(AI)"` and `"(inference)"` do not appear anywhere in the file (adjust any
  comment that still says them).

**README:** the "What it does" table's first column uses the new tab names; the row
text is otherwise unchanged.

**Definition of done:** every row in the four tables above is applied; the badge helper
exists and is used exactly where the tables say; no user-visible string contains "(AI)"
or "(inference)"; every static caption is 20 words or fewer except those the table
explicitly keeps; the theme renders (primary colour visible on the selected tab and
buttons); `python -m pytest -q` passes with the updated assertions; permalinks with
`?tab=finder&pe=…&view=plans` still open the right tab and sub-tab; clicked through in
a real browser on all four tabs and all four profile sub-tabs for PE 0604274N (Navy),
with a screenshot description of the badge under "Procurement transition".

**Verify:**
```bash
python -m pytest -q
grep -n "(AI)\|(inference)" app.py            # expect no output
grep -c "render_badge(" app.py                # expect 5 (1 definition + 4 uses)
python -m streamlit run app.py --server.port 8501   # click through as described
```

---

## 3. Escalate instead of guessing

Same list as `CODEX_HANDOFF.md` §7, plus:

- Any change to the order, labels, or keys of `st.tabs()` calls in `app.py`.
- Any new dependency, or any bump to `streamlit` beyond `>=1.55.0`.
- Any DD 1416 or R-1 arithmetic that does not tie in T8a. The identity held 433/433 during
  scoping; a failure means a column map is wrong, not that the tolerance is too tight.
