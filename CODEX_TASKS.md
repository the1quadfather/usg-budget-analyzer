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
| T8–T15 | **open** | this document |

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

**Files:** `app.py` (Data Coverage tab only).
**Depends on:** T8a merged.

**Do:** add a "Does it tie?" section at the bottom of Data Coverage: one `st.dataframe`
per source (R-1, DD 1416) with columns FY, Component, Stream, Basis, Ingested $K,
Published $K, Residual $K, Residual %, Status, Explanation. Colour nothing; use the
`Status` column text. A `st.caption` above the table states the tolerance in percent.

**Definition of done:**
- The panel renders with the shipped database and every row has a non-empty `Status`.
- Rows with `outside_tolerance` show their `Explanation`; none are filtered out.
- `render_table_downloads` is wired for each table with the R-1 or DD 1416 sources.
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

### T9c — P-1 ingest script

**Files:** new `storage/ingest_p1.py`.
**Depends on:** T9a and T9b merged.

**Do:** mirror `storage/ingest_dd1416.py`: parse every workbook first, validate, then one
write transaction; idempotent per `source_document`; record `source_url`, `retrieved_at`,
`content_hash` in `source_documents` with `document_type="P1"`. CLI:
`python -m storage.ingest_p1 --years 2026 2027 [--download]`.

**Definition of done:**
- FY2026 and FY2027 ingested; `Add` rows only; quantities preserved.
- A spot-check row named in the commit message ties to the spreadsheet cell.
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

Start with the most common and most detectable case: the same 7-character PE with digits
3–4 changed (a budget-activity move), same agency, same or near-identical title, where one
series ends the year before the other begins.

**Definition of done:** the detector finds at least one known case (name it in the commit
message with both PE numbers and the FY); a unit test builds a synthetic pair and asserts
one `renumbered` edge with `method="ba_renumber"`; **no edge is inferred from a funding
drop alone**.

### T11b — Narrative transfer language

**Files:** `analysis/lineage.py`, `tests/test_lineage.py`.
**Depends on:** T11a merged.

**Do:** `detect_narrative_transfers(session) -> list[LineageEdge]` scanning
`pe_narratives.description` and `pe_accomplishments.text` for patterns such as
"transferred from PE 0602115A", "realigned to PE …", "moved to Program Element …".
Every edge carries the verbatim sentence and its `source_file`.

**Definition of done:** a fixture of six sentences (three positive, three negative such as
"funds were transferred to the contractor") yields exactly three edges; the regex set is
listed in the module docstring.

### T11c — Lineage golden set, ingest, and eval

**Files:** new `analysis/lineage_golden.json`, new `analysis/lineage_eval.py`, new
`storage/ingest_lineage.py`.
**Depends on:** T11b merged.

**Definition of done:** ten hand-verified cases with evidence URLs; ingest writes edges
from both detectors idempotently; eval prints precision and recall against the golden set;
`.db.gz` rebuilt and committed with row counts in the message.

### T11d — Lineage in the funding chart

**Files:** `app.py` (Program Finder → Funding), `analysis/trend_tracker.py` (a
`get_pe_history_with_lineage()` that returns the same frame plus a `segment` column).
**Depends on:** T11c merged.

**Definition of done:** when a selected PE has an edge, the chart draws the predecessor
and successor series in distinct segments with a visible seam (a rule mark at the FY) and
a caption naming both PEs and the relation; edges with confidence < 0.6 are dotted and
off by default behind a checkbox labelled "Include possible lineage"; each edge has an
expander with its evidence sentence; a series is **never silently spliced**; clicked
through in a browser.

---

## Phase F — Distribution

### T12a — Data dictionary

**Files:** new `DATA_DICTIONARY.md`.
**Depends on:** nothing.

**Definition of done:** every table in the shipped database and every column, with type,
unit, allowed values where enumerated (the six `funding_type` values, the two
`document_type` values, `chamber`), and the source exhibit it comes from; row counts as of
the current archive; a "runtime tables, not shipped" section listing `ai_cache`,
`ai_spend`, `ai_user_history`, `search_log`.

### T12b — Release bundle script

**Files:** new `scripts/build_release.py`, `README.md` (a "Data releases" section).
**Depends on:** T12a merged.

**Do:** produce `release/usg-budgets-<YYYY-MM-DD>/` containing the `.db.gz`, the parquet
files, `DATA_DICTIONARY.md`, a `manifest.json` (`{table: row_count}` plus
`source_documents` as a list of `{filename, document_type, source_url, content_hash}`),
and `RELEASE_NOTES.md` with row-count deltas against the previous manifest if one exists.

**Definition of done:** the script calls `analysis.ai_budget --reset-runtime` itself; it
**fails with a non-zero exit** if the grounded-results compliance query in
`CODEX_HANDOFF.md` invariant 1 returns nonzero; it runs from a clean clone; runtime tables
are excluded by construction. No GitHub release is created by the script — that stays a
human action.

### T13a — Change feed core

**Files:** new `analysis/changefeed.py`, new `tests/test_changefeed.py`.
**Depends on:** nothing (T4's `pb_cycle` already exists).

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

Compare like with like only: `BY Request` in PB N against `CY Request` for the same FY in
PB N+1 is a legitimate vintage diff; `PY Actual` against `CY Request` is not a change and
must not be emitted.

**Definition of done:** output is deterministic and sorted for a fixed pair of vintages;
the threshold is a named parameter with its default documented; tests cover one new
start, one termination, one swing above threshold, one below (not emitted), and the
forbidden PY-vs-CY comparison (not emitted).

### T13b — Change feed surface

**Files:** `app.py` (Budget Trends tab, new section "What changed"), new
`scripts/export_changefeed.py` writing `release/changefeed.json`.
**Depends on:** T13a merged.

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
