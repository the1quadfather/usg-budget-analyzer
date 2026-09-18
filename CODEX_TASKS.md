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
| T12a Data dictionary | shipped | `DATA_DICTIONARY.md`, 13 tables validated against archive PRAGMA with 0 mismatches; commit `e32d3d7` |
| T10, T11e, T12b, T14–T15 | **open** | this document. Next: T11e, then T12b; T10a is research, not a Codex task |

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

**Files:** new `analysis/transition_golden.json`, new `analysis/transition_eval.py`.
**Depends on:** T9c merged.

**Do:** hand-check twenty RDT&E-to-procurement transitions from public sources and record
them:

```json
[{"pe_number": "0604...", "agency": "Army", "bli": "...", "appropriation": "...",
  "first_procurement_fy": 2024, "evidence_url": "https://...", "note": "..."}]
```

`transition_eval.py` mirrors `analysis/linker_eval.py`: loads the golden set, runs
whatever `analysis/transition.py` exposes (T10b), prints precision/recall at the top-3.
Until T10b exists it exits with a clear message.

**Definition of done:** twenty entries, each with an official or reputable URL; the file
loads; the eval script runs and reports "no transition module yet".

### T10b — Transition candidate generator

**Files:** new `analysis/transition.py`, new `tests/test_transition.py`.
**Depends on:** T10a merged.

**Do:** propose procurement BLIs for a PE using the existing fuzzy and semantic matchers
over titles, then corroborate with narrative text.

```python
@dataclass(frozen=True)
class TransitionCandidate:
    pe_number: str
    agency: str
    bli: str
    appropriation: str
    line_item_title: str
    confidence: float           # 0–1; combine title similarity and narrative evidence
    strategy: str               # "FUZZY" | "SEMANTIC" | "NARRATIVE"
    evidence_text: str | None   # verbatim sentence from pe_narratives / pe_accomplishments
    evidence_source: str | None # source_file of that sentence
    ambiguous: bool             # True when the runner-up is within 0.1 confidence

def propose_transitions(session, pe_number: str, agency: str, *, limit: int = 5) -> list[TransitionCandidate]: ...
```

**Definition of done:** eval script reports recall@3 ≥ 0.6 on the golden set, printed
honestly whatever the number is; ambiguous cases carry `ambiguous=True`; a unit test
covers one exact-title match and one no-match. No UI.

**Verify:**
```bash
python analysis/transition_eval.py
python analysis/linker_eval.py        # matchers were touched only if this still passes 11/11
python -m pytest -q
```

### T10c — Transition panel

**Files:** `app.py` (Program Finder → Funding profile tab, new expander at the bottom
titled "Did it transition to procurement? (inference)").
**Depends on:** T10b merged.

**Definition of done:** every candidate shows confidence, strategy, and its evidence
sentence; the expander title contains the word "inference"; ambiguous candidates render
with the text "ambiguous"; no candidate is shown without evidence or a similarity score;
clicked through in a browser.

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

**Files:** new `analysis/narrative_qa.py`, new `tests/test_narrative_qa.py`.
**Depends on:** nothing. Uses the existing embeddings file under `data/processed/`.

```python
@dataclass(frozen=True)
class Passage:
    pe_number: str; agency: str; fiscal_year: int
    project_number: str | None
    source_file: str
    text: str
    score: float

def retrieve(question: str, *, k: int = 8) -> list[Passage]: ...
```

**Definition of done:** retrieval is fully local and free; a test asserts that a question
naming a known program returns a passage from that PE in the top-3; runtime under 2 s on
the shipped corpus after model load. No model call in this task.

### T14b — Cited synthesis through the governed AI path

**Files:** `analysis/narrative_qa.py`, `analysis/oss_enricher.py` (register the task),
`analysis/ai_budget_eval.py` (add the task to the governance checks).
**Depends on:** T14a merged.

```python
@dataclass(frozen=True)
class Citation:
    pe_number: str; agency: str; fiscal_year: int; source_file: str; quote: str

@dataclass(frozen=True)
class CitedAnswer:
    sentences: list[tuple[str, list[Citation]]]   # every sentence has ≥ 1 citation
    refused: bool
    reason: str | None

def answer(question: str, passages: list[Passage], *, user_id: str, allow_fresh: bool) -> AIResult: ...
```

**Definition of done:** the task name is **not** in `config.GROUNDED_TASKS` and results
go to the shared `ai_cache`; every sentence carries at least one citation whose `quote` is
a verbatim substring of a retrieved passage, verified in code, otherwise the answer is
converted to `refused=True` with reason "uncited"; cost is metered in `ai_spend`;
`ai_budget_eval.py` still passes with the new task included.

**Verify:**
```bash
python analysis/ai_budget_eval.py
sqlite3 data/processed/usg_budgets.db "SELECT COUNT(*) FROM ai_cache WHERE task IN ('find_open_source_hits','annual_signal');"   # must be 0
python -m pytest -q
```

### T14c — Ask-the-corpus UI

**Files:** `app.py` (Program Finder tab, above the search box, an expander "Ask the
justification books").
**Depends on:** T14b merged.

**Definition of done:** cold cache shows a button naming the source ("Answer from R-2
narratives (AI)"); warm cache auto-renders with an "as of" caption; each sentence renders
its citations as `PE … · FY… · file`; a refusal renders as an `st.info` with the reason;
clicked through in a browser with AI disabled (the section must degrade to the same
caption the "In the News" tab uses).

### T15a — Structured-fact schema

**Files:** `storage/db.py`, `tests/test_regressions.py`.
**Depends on:** nothing.

```python
FactType = Literal["contractor", "transition", "test_event", "location"]

class NarrativeFact(Base):
    __tablename__ = "narrative_facts"
    id: Mapped[int]
    narrative_id: Mapped[int]          # FK pe_narratives.id or pe_accomplishments.id
    narrative_table: Mapped[str]       # "pe_narratives" | "pe_accomplishments"
    pe_number: Mapped[str]; agency: Mapped[str]; fiscal_year: Mapped[int]
    fact_type: Mapped[str]             # FactType
    value: Mapped[str]                 # normalised string, e.g. "Lockheed Martin"
    sentence: Mapped[str]              # verbatim sentence the fact came from
    char_start: Mapped[int]; char_end: Mapped[int]   # offsets of `sentence` in the source text
    model: Mapped[str]                 # config.GEMINI_MODEL at extraction time
    content_hash: Mapped[str]; extracted_at: Mapped[datetime]
```

**Definition of done:** schema creates on an existing DB; a round-trip test.

### T15b — Batch extraction job

**Files:** new `analysis/narrative_extract.py`.
**Depends on:** T15a merged.

**Do:** mirror `analysis/ai_precompute.py`: a resumable worklist over narratives, a dry
run that prints the estimated cost **before** any call (input tokens × price, plus output
at the output rate, plus `thoughts_token_count` billed at the output rate), and a
`--limit N` flag. CLI: `python -m analysis.narrative_extract --dry-run | --run --limit 50`.

**Definition of done:** dry run makes zero API calls and prints the estimate; a real run
of 50 narratives writes rows whose `sentence` is a verbatim substring at
`[char_start:char_end]` of the source text (asserted in code); spend appears in
`ai_spend`; re-running skips already-extracted narratives; the task is not in
`GROUNDED_TASKS`.

---

## 3. Escalate instead of guessing

Same list as `CODEX_HANDOFF.md` §7, plus:

- Any change to the order, labels, or keys of `st.tabs()` calls in `app.py`.
- Any new dependency, or any bump to `streamlit` beyond `>=1.55.0`.
- Any DD 1416 or R-1 arithmetic that does not tie in T8a. The identity held 433/433 during
  scoping; a failure means a column map is wrong, not that the tolerance is too tight.
