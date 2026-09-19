# Codex handoff — DoD Budget Explorer, M3 onward

**Written 2026-09-08.** Companion to [ROADMAP.md](ROADMAP.md) (the *why* and the order).
This document is the *how*: verified source facts, invariants you must not break, and
per-task specs with acceptance criteria.

Assume zero prior knowledge of this repo. Read sections 1–3 before writing any code.

Every fact marked **[verified 2026-09-08]** was confirmed by direct HTTP request or by
querying the shipped database during the session that wrote this document — not inferred
from documentation, and not taken from a model's memory. Facts marked **[reported]** came
from grounded web search and were *not* independently confirmed; treat those as leads and
verify before building on them.

---

## 1. Orientation

Streamlit app. Traces US defense RDT&E programs from budget request → congressional action
→ contract awards → public statements.

```
C:\Users\lbsch\Documents\USG Budget Analyzer\
├── README.md, HANDOFF.md, ROADMAP.md, CODEX_HANDOFF.md
├── .streamlit/config.toml          # watcher off — see invariant 9
└── dod_ic_budget_analyzer/
    ├── app.py                      # 1305 lines, the entire UI
    ├── config.py                   # URLs, pricing, thresholds, budget knobs
    ├── acquisition/                # downloaders (comptroller, R-2, service R-2, congress, USAspending)
    ├── parsing/                     # R-1 XLSX/PDF, R-2 XML, R-2 PDF, statement parsers
    ├── storage/                    # SQLAlchemy 2.0 schema + ingest pipelines
    ├── matching/                   # normalizer, rapidfuzz matcher, sentence-transformers matcher
    ├── analysis/                   # trends, linker, awards, rhetoric, AI governance, evals
    └── data/
        ├── processed/              # usg_budgets.db (gitignored) + usg_budgets.db.gz (tracked)
        └── raw/                    # gitignored, rebuildable
```

Run it:

```bash
python -m streamlit run dod_ic_budget_analyzer/app.py --server.port 8501
```

`.claude/launch.json` has a `budget-analyzer` config on port 8501.

### Database ground truth [verified 2026-09-08]

Queried directly, because README and HANDOFF disagree with each other in places. **These
numbers are correct; the prose in README is not always.**

| Fact | Value |
|---|---|
| Tables | `ai_cache`, `ai_spend`, `ai_user_history`, `funding_lines`, `narrative_facts` (T15a; 0 rows, not in the archive until T15b), `pe_accomplishments`, `pe_congressional_actions`, `pe_execution`, `pe_lineage`, `pe_narratives`, `procurement_lines`, `program_elements`, `search_log`, `source_documents` |
| `program_elements` | 2,131 rows / **2,055 distinct** `pe_number` |
| `funding_lines` | 55,652 rows, **FY1996–FY2027** (README says FY1998 — wrong); `pb_cycle` 1998–2027 |
| `funding_lines.funding_type` | six values: `PY Actual`, `CY Request`, `BY Request`, and the `Mandatory` variant of each |
| `pe_narratives` | 1,383 distinct PEs (67% narrative coverage) |
| `pe_congressional_actions` | 26,544 rows, FY2012–FY2027 |
| `pe_execution` | 79,677 rows from 381 DD 1416 workbooks, report dates 2012-12-31 to 2026-03-31 **[verified 2026-09-10]** |
| `pe_lineage` | 405 rows: 2 `ba_renumber`, 403 `narrative`; 404 distinct predecessor/successor pairs **[verified 2026-09-18]** |
| `procurement_lines` | 5,253 rows (2,589 PB2026 + 2,664 PB2027), FY2024–FY2027, one row per workbook cost-type line; key is `(bli, agency, appropriation, budget_activity, line_number, cost_type, cost_type_title, fiscal_year, funding_type, pb_cycle, source_document_id)` **[verified 2026-09-12]** |
| `source_documents` | 412: 29 `R1`, 381 `DD1416`, 2 `P1` **[verified 2026-09-12]** |

**There is no enacted/appropriated figure anywhere in the database today.** That is what
task T5 adds, and it is why T5 is the highest-value work on the roadmap.

Amounts in `funding_lines` are **thousands of dollars** (`amount_thousands`).
`pe_accomplishments.funding_millions` is millions. Watch the unit at every boundary.

### UI anchors in `app.py`

| Line | Thing |
|---|---|
| 33 | `st.set_page_config` |
| 257 | `st.tabs(...)` — four tabs |
| 263 | Budget Trends |
| 339 | Program Finder (sub-tabs at 453: funding / plans / awards / news) |
| 821 | Rhetoric vs. Budget |
| 1255 | Data Coverage |

---

## 2. Invariants — do not "simplify" these

Each of these encodes a bug already paid for, a legal constraint, or a data-honesty
commitment. Breaking one is worse than shipping nothing.

1. **Grounded AI results are per-user and never shared.** The Gemini API terms forbid
   caching, analyzing, reselling, or cross-user sharing of Grounded Results.
   `AICache.put()` routes `config.GROUNDED_TASKS` to `ai_user_history` keyed by `user_id`;
   everything else goes to the shared `ai_cache`. Non-grounded match adjudication *is*
   shared — that is where the cost savings come from. Compliance check must return 0:
   ```bash
   sqlite3 dod_ic_budget_analyzer/data/processed/usg_budgets.db \
     "SELECT COUNT(*) FROM ai_cache WHERE task IN ('find_open_source_hits','annual_signal');"
   ```
2. **Verify the search actually ran.** The model will answer a "find recent coverage"
   prompt from memory — `grounding_metadata` comes back `None` — inventing plausible
   outlets and dates. It does this especially when the prompt demands strict JSON.
   `find_open_source_hits` is therefore **two calls on purpose**: grounded research in
   prose, then a cheap ungrounded pass to structure it. **Do not merge these back into one
   JSON-demanding prompt.** If `grounding_metadata is None`, discard the output.
3. **Authorization is not appropriation.** `pe_congressional_actions` holds authorizing
   committee action (HASC/SASC), not enacted amounts. Never relabel it, and never let a UI
   string imply Congress *gave* the money.
4. **Never pool House and Senate**, and never blindly sum a PE's lines within one report.
   A PE can legitimately appear several times in one report under different budget
   activities, so `line_number` is part of the natural key. The chambers score the same
   request independently.
5. **Discretionary and mandatory/reconciliation funds are separate streams.** FY2026 has
   ~$839B discretionary (P.L. 119-75 Div. A) plus ~$113B mandatory from reconciliation
   (OBBBA, P.L. 119-21). Summing them silently doubles apparent growth.
   `MANDATORY_QUALIFIER_RE` in `parsing/xlsx_ingest.py` already matches `PL 119`.
6. **Machine-readable congressional tables start at FY2012.** Earlier reports print them
   as GRAPHIC images. An absent year means "not available," never "no action taken." Say
   so in the UI wherever the data is surfaced.
7. **Coverage gaps get disclosed, not hidden.** Narrative coverage is uneven by source
   design (Army published no FY2023 RDT&E books; the Internet Archive holds Air Force and
   Space Force books only through FY2024). The Data Coverage tab exists for this. Keep it
   truthful.
8. **Escape dollar signs in every dynamic markdown string.** Streamlit's markdown enables
   single-`$` LaTeX with no off switch, so `"$91.0M ... $1,654.9M"` renders as math. Route
   dynamic text through `analysis/text_render.py::escape_dollars()`. Regression fixed in
   3ab4932 — do not reintroduce it.
9. **Leave the source-file watcher off.** `.streamlit/config.toml` at the repo root
   disables it because with it on, Streamlit probes every imported module after each run,
   which makes transformers' lazy vision modules try to import torchvision and logs ~150
   harmless tracebacks per scan.
10. **No API key in the public deployment.** The app reads `GEMINI_API_KEY` /
    `GOOGLE_API_KEY` from the environment (or Community Cloud Secrets) and nowhere else.
    No key file, no config entry, no Docker build arg. `.env` is gitignored.
11. **Memory budget.** Community Cloud gives ~1 GB; the app settles at 550–600 MB once the
    matching model loads. Do not add a second ML model, a second dataframe engine, or
    anything that loads the whole DB into RAM.
12. **After any ingest, rebuild the shipped archive — and scrub runtime rows first.** The
    DB is published in a public repo, so a dev session's cached AI results, spend ledger,
    and search log must never ship:
    ```bash
    python -m analysis.ai_budget --reset-runtime
    gzip -9 -c data/processed/usg_budgets.db > data/processed/usg_budgets.db.gz
    ```
    The raw `.db` is gitignored; only the `.gz` is tracked.
13. **`comptroller.defense.gov` is dead for programmatic use** (403). Use
    **`comptroller.war.gov`** [verified 2026-09-08 — plain `curl` gets 200 from the
    comptroller subdomain; the Akamai 403 problem applies to the `war.gov` *news* site,
    which only exposes `RSS.ashx`].

---

## 3. Verified source facts

### 3.1 DD 1416 "Report of Programs" — RDT&E execution, XLSX [verified 2026-09-08]

**This is the single most valuable unexploited source available to this project.**

Index pages, one per fiscal year:

```
https://comptroller.war.gov/BudgetExecution/1416QrtlyRptsfy{FY}.aspx
```

Confirmed HTTP 200 for fy2013, fy2016, fy2018, fy2024, fy2026. fy2025 is linked from the
live Budget Execution page. Several probes returned no status at all — **the site throttles
concurrent requests**, so pace them (reuse `config.HTTP_RETRY_ATTEMPTS` and the existing
backoff helper; ~3s between requests was reliable).

Each year page links, per quarter, per appropriation (`RDTE`, `Proc`, `OM`, `Milpers`), per
component (`Air_Force`, `Army`, `Navy`, `Space_Force`, `Defense_Wide`):

```
/Portals/45/documents/1416_Quarterly_Reports/fy2026/1416_Qtrly_Rpt_3_31_2026/
  DD_1416_RDTE_Rpt_3_31_2026/Defense_Wide_RDTE_FY_2026_2027_DD_1416_Qtrly_Rpt_03_31_2026.xlsx
```

**Trap:** zero-padding is inconsistent between the folder (`1416_Qtrly_Rpt_3_31_2026`) and
the filename (`..._03_31_2026.xlsx`). **Do not construct these URLs — scrape the year
page's `href`s.** The repo already has BeautifulSoup and an `httpx` client factory.

**Trap:** the `FY_2026_2027` in the filename is the appropriation's **two-year availability
window** (RDT&E is 2-year money), not a range of report years. One quarterly report
therefore ships separate files for FY2025-2026 and FY2026-2027 money. Treat the pair as
part of the record's identity or you will double count.

File structure, verified against
`Defense_Wide_RDTE_FY_2026_2027_DD_1416_Qtrly_Rpt_03_31_2026.xlsx`:

- Single sheet, named `ORG-BA-BLI`.
- The first ~11 rows are report furniture ("Report of Programs", "UNCLASSIFIED",
  "(In Dollars)", `Account: Research, Dev...`), then organization and
  `BA 01: BASIC RESEARCH` block headers.
- **The header row repeats inside every budget-activity block.** Parse block by block; do
  not assume one header.
- Data rows carry the FY pair in column 0 (e.g. `2026-2027`).
- Subtotal rows start with `TOTAL BA ` in column 0 — **skip them**.

**Trap, and the most important line in this document: column positions are NOT stable
across components. Map columns by header text, never by index.** Verified by comparing two
files from the same quarter:

| Field (header text) | Defense-Wide col | Army col |
|---|---|---|
| `BLI#` | 3 | 3 |
| `BLI` — the **program element number**, joins to `program_elements.pe_number` | 4 | 4 |
| `BLI TITLE` | 5 | **7** |
| `President's Budget Request` | 7 | **10** |
| `Enacted Appropriation (Includes Distribution of Congressional Adjustments/1)` | 9 | **12** |
| `Adjustments Required by Statute /2` | 11 | **14** |
| `Suppls/Collections/Rescissions/ Sequestration /3` | 13 | **16** |
| `Other: Cancelled, Claims, Judgments /4` | 15 | **19** |
| `Above Threshold Reprog` — required congressional prior approval | 17 | **23** |
| `Below Threshold Reprog` — did not | 19 | **27** |
| `Net` — current program | 21 | **29** |

The header row itself also sits at a different row (16 in the Defense-Wide file, 14 in the
Army file). Within a single file the layout was consistent. Find the row whose cells
contain the literal `BLI`, build a `{field: column}` map from that row's header strings,
and rebuild it at every repeated header. A positional parser will silently mis-read four of
the five components.

**Trap:** amounts are **in dollars**, not thousands (the sheet says so in its header
furniture). The database stores `amount_thousands`. Divide by 1000 at the boundary and
assert the magnitude — a missed conversion here is a 1000× error that will look plausible
in a chart.

**Trap:** value types are mixed within one column — plain numeric strings
(`310191000`), comma-formatted negatives (`-3,988,648`), floats with cents
(`290464302.07`), and empty cells meaning zero. Normalize before arithmetic.

**The reconciliation identity holds exactly**, and this is verified, not assumed:

```
enacted + statutory_adj + suppl_resc_seq + other_adj + above_threshold + below_threshold = net
```

Checked across 433 data rows in two component files (Defense-Wide FY2026-2027 and Army
FY2025-2026, quarter ending 2026-03-31): **433/433 reconcile to within a dollar**, once
columns are header-mapped. Use it as the parser's self-check per T5.

Sample verified rows:

| PE | Request | Enacted | Statutory | Other | Above | Below | Net |
|---|---|---|---|---|---|---|---|
| `0601384BP` | 36,582,000 | 28,232,000 | — | — | — | — | 28,232,000 |
| `0601102A` | 310,191,000 | 297,680,000 | −3,988,648 | −31,050 | — | −3,196,000 | 290,464,302.07 |
| `0601104A` | 109,726,000 | 113,476,000 | −3,747,930 | — | −7,000,000 | — | 102,728,070 |

Note `0601104A`: enacted came in *above* the request, then $7M was reprogrammed out above
threshold. That is exactly the story no free tool tells today.

**Prefer this over the alternatives.** DD 1414 (PDF) and the appropriations Joint
Explanatory Statement (text/graphic tables) were the previously planned routes to enacted
figures; DD 1416 supersedes both for RDT&E because it is already tabular.

### 3.2 Comptroller summary exhibits, XLSX [verified 2026-09-08]

```
https://comptroller.war.gov/Portals/45/Documents/defbudget/FY{YYYY}/{stem}.xlsx
```

`config.XLSX_EXHIBIT_STEMS` already maps `rdtee→r1_display`, `procurement→p1_display`,
`om→o1_display`. HTTP 200 confirmed for `r1_display`, `p1_display`, `o1_display`,
`m1_display` at FY2026 and FY2027; `c1_display` FY2027 only (FY2026 404s). Also present on
the page: `p1r_display.xlsx`, `p1r_display_ooc.xlsx`, `rf1_display.xlsx`.

P-1 structure, verified against FY2027 `p1_display.xlsx` (926 KB):

- Sheets: `Exhibit P-1` (everything), then per-scenario duplicates — `FY 2025 Actuals`,
  `FY 2025 Reconciliation`, `FY 2025 Total`, `FY 2026 Discretionary Enacted`,
  `FY 2026 PL 119-21 Spend Plan`, `FY 2026 Total`, `FY 2027 Discretionary Request`,
  `FY 2027 Mandatory Request`, `FY 2027 Total`. Same discretionary/mandatory split R-1 has.
- Header on **row 2** (row 1 holds `SUBTOTAL` formulas); data from row 3.
- Columns: `Account`, `Account Title`, `Organization`, `Budget Activity`,
  `Budget Activity Title`, `Line Number`, `BSA`, `Budget SubActivity (BSA) Title`,
  `Budget Line Item`, `Budget Line Item (BLI) Title`, `Cost Type`, `Cost Type Title`,
  `Add/Non-Add`, then repeating `FY {year} {qualifier} Quantity` / `... Amount` pairs.
- **Trap:** filter to `Add/Non-Add == "Add"` or you double count.
- **Trap:** P-1's `Budget Line Item` is a 10-character BLI code (`9670A00005`), **not a
  program element**. There is no key join from RDT&E to procurement. See T10.
- **Trap [verified 2026-09-12]:** a BLI is **not unique within an account**. The same
  code prints once per budget activity it draws from (FY2026 `3010F` lists `F015EX`
  under BA01 line 7, BA05 line 44, BA07 lines 112 and 134), and each of those splits
  again by `Cost Type` (`A` Weapon System Cost, `B` Less: Advance Procurement (PY),
  `C` Advance Procurement (CY), shipbuilding completion lines `E`/`G`/`L`/`N`). Cost
  type `N` repeats under one line number with a different year in its title
  ("Completion PY Shipbuild for FY 2015", "... FY 2016", ...), so the title is part of
  the identity. The row identity is `(Account, Line Number, Cost Type, Cost Type
  Title)`; `(Account, BLI, Budget Activity, BSA, Cost Type, Cost Type Title)` is the
  equivalent cross-cycle identity. Same lesson as invariant 4: never
  sum a BLI's lines blindly, and never sum quantities across cost types.
- P-1 has a `Quantity` column R-1 has no analogue for — unit counts. Keep them; "how many
  did they buy" is a question no free tool answers well.

### 3.3 Green Book deflators [verified 2026-09-08 — currently broken]

The FY2027 Budget-Materials page links `fy27_Green_Book.pdf` and `fy27_Green_Book.zip`
(label reads "FY FY2027"); **both return 404**. Working Wayback snapshots exist:

```
http://web.archive.org/web/20251004164717/https://comptroller.defense.gov/Portals/45/Documents/defbudget/FY2025/fy25_Green_Book.pdf
http://web.archive.org/web/20251004190845/https://comptroller.defense.gov/Portals/45/Documents/defbudget/FY2024/FY24_Green_Book.pdf
```

Deflator tables are in Chapter 5 (Tables 5-4 / 5-5) **[reported]** — confirm the table
numbers against the PDF you actually fetch. Use the **RDT&E-specific** index, not GDP or
CPI. Any scraper here must tolerate officially-listed links that 404.

### 3.4 Reprogramming source documents [verified 2026-09-08]

- DD 1414 base for reprogramming: `/BudgetExecution/DD1414_Base_for_Reprogramming_Actions/`
  — PDFs, `FY_{YYYY}_DD_1414_Base_for_Reprogramming_Actions.pdf`, FY2008 onward observed.
- DD 1415 actions: `/BudgetExecution/ReprogrammingFY{YYYY}.aspx` →
  `/Portals/45/Documents/execution/reprogramming/fy2026/ir1415s/26-01_IR_ER_1.pdf` etc.
- Also on those pages: `/Portals/45/Documents/news/OBBBA_Dash_1_Unclass_for Congress.xlsx`
  (note the literal space in the filename) and `FY2026_Mandatory_Funding_Allocation_Plan.pdf`
  — relevant to invariant 5.

DD 1416 already gives the *aggregate* above/below-threshold reprogramming per PE. The 1415
PDFs add the stated *reason* per action. Treat them as a Phase B stretch goal, not a
prerequisite.

### 3.5 Things confirmed *not* to exist — do not go looking

- **No service-level R-2 XML or JSON.** Army, Navy, Air Force, Space Force publish RDT&E
  justification books as PDF only. EAS/DTIC XML is Defense-Wide only. **[reported,
  consistent with this repo's own experience]**
- **No public FYDP dataset.** DoD transmits the unclassified FYDP to the congressional
  defense committees; the FY2021–FY2025 NDAAs did not mandate public release. **[reported]**
- **No official PE→contract crosswalk.** USAspending carries no program-element field.
  The only official route is extracting contractor and contract data from R-3 (RDT&E
  project cost analysis) and P-5 exhibits, which print performing activity, contract
  method/type, award date, and target contract value per cost line. **[reported — verify
  against a real R-3 before building T10's evidence layer]**
- **No GAO Excel/CSV supplement** for the Weapon Systems Annual Assessment; data must come
  from the report's "Accessible Version" HTML tables. **[reported]**
- `api.congress.gov` returns 403 and `api.govinfo.gov` 401 without a key [verified]. Keys
  are free and instant, but the NDAA committee-report slice this project uses needs no key.

---

## 4. Task specs

One task per PR. Each lists files, approach, acceptance criteria, and the pitfalls that
will actually bite. Where a task says *do not*, that is load-bearing.

### T1 — Permalinks

**Files:** `app.py`.
**Do:** read `st.query_params` on startup to restore active tab, selected PE, and FY range;
write it on every state change. Prefer short keys (`?tab=finder&pe=0604201F&fy=2018-2027`).
**Accept:** pasting a URL into a fresh browser reproduces the exact view, including the
Program Finder profile and its active sub-tab. No `st.rerun()` loop (writing a param must
not retrigger a read that rewrites it).
**Pitfall:** Streamlit tabs are not natively addressable. Either drive the tab from a
`st.radio`/segmented control bound to the param, or accept restoring everything *but* the
tab and say so — do not fake it with JS.

### T2 — Export + provenance

**Files:** `app.py`, new `analysis/provenance.py`.
**Do:** a `download_button` on every dataframe (CSV always; XLSX where `xlsxwriter` is
already a dependency). Add a provenance block under each figure: source document title,
URL, exhibit, and retrieval date, read from `source_documents`.
**Accept:** every table on all four tabs exports; every exported file has a companion
header comment or sidecar naming the source rows' provenance; no figure in the app lacks a
traceable source.
**Pitfall:** run any dynamic provenance string through `escape_dollars()` (invariant 8).

### T3 — Constant dollars

**Files:** new `acquisition/greenbook_downloader.py`, new `analysis/deflators.py`,
`app.py`, `config.py`.
**Do:** fetch a Green Book (Wayback per §3.3), parse the RDT&E deflator series, store it as
a small tracked CSV under `data/processed/` (it is a few dozen numbers — do not add a DB
table), and add a "then-year / constant FY20XX dollars" toggle to Budget Trends.
**Accept:** toggling changes the series; a known spot-check ties to the Green Book table to
the cent; the base year is labeled on the axis; the toggle's state is in the permalink.
**Pitfall:** the constant-dollar formula is `current / index * 100`. Do not apply an
RDT&E index to procurement or O&M lines when T9 lands — carry the index per appropriation.

### T4 — Vintage labeling

**Files:** `storage/db.py`, `storage/ingest_r1.py`, `app.py`.
**Do:** `funding_lines` records `PY Actual` / `CY Request` / `BY Request` but not which
submission produced them. Add a `pb_cycle` column (the FY of the President's Budget the row
came from), backfill from `source_documents`, and show it wherever a figure appears.
**Accept:** a migration that backfills without data loss; the UI states, for any figure,
which PB cycle it came from; the same FY sourced from two cycles renders as two labeled
series rather than one averaged line.
**Pitfall:** this is a schema change to the largest table (55,460 rows). Write the
migration as an idempotent script under `storage/`, not an ad-hoc `ALTER`.

### T5 — DD 1416 ingest (highest priority)

**Files:** new `acquisition/dd1416_downloader.py`, new `parsing/dd1416_parser.py`, new
`storage/ingest_dd1416.py`, `storage/db.py`, `config.py`.

**Do:** scrape year index pages, download RDT&E XLSX files, parse per §3.1, ingest into a
new table. Suggested schema, mirroring the conventions in `PECongressionalAction`:

```python
class PEExecution(Base):
    """
    DD 1416 "Report of Programs" quarterly execution status for one PE.
    Official, machine-readable, key-free. Amounts converted from dollars ($ in
    the source) to thousands to match funding_lines.
    """
    __tablename__ = "pe_execution"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100), index=True)
    appropriation: Mapped[str] = mapped_column(String(50))        # 'RDTE'
    fy_start: Mapped[int] = mapped_column(Integer, index=True)    # 2026 of "2026-2027"
    fy_end: Mapped[int] = mapped_column(Integer)                  # 2027
    report_date: Mapped[str] = mapped_column(String(10), index=True)  # '2026-03-31'
    line_number: Mapped[Optional[str]] = mapped_column(String(10))
    program_title: Mapped[str] = mapped_column(String(500))
    budget_activity: Mapped[Optional[int]] = mapped_column(Integer)
    request_k: Mapped[Optional[float]] = mapped_column(Float)
    enacted_k: Mapped[Optional[float]] = mapped_column(Float)
    statutory_adj_k: Mapped[Optional[float]] = mapped_column(Float)
    suppl_resc_seq_k: Mapped[Optional[float]] = mapped_column(Float)
    other_adj_k: Mapped[Optional[float]] = mapped_column(Float)
    above_threshold_reprog_k: Mapped[Optional[float]] = mapped_column(Float)
    below_threshold_reprog_k: Mapped[Optional[float]] = mapped_column(Float)
    net_k: Mapped[Optional[float]] = mapped_column(Float)
    source_file: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

**Accept:**
- Parser unit-tested against one committed fixture file (a single sheet is small; commit it
  under `tests/fixtures/`).
- Ingest is idempotent — rerunning changes no row count (that is what `content_hash` is for).
- **Columns mapped by header text, not by index** (§3.1). Add a test asserting that the
  Defense-Wide and Army fixtures — which have *different* column positions — both parse to
  identical field semantics. This is the single most likely place for this task to go
  quietly wrong.
- **Arithmetic self-check:** for every row, `enacted + statutory_adj + suppl_resc_seq +
  other_adj + above_threshold + below_threshold` must reconcile to `net` within a dollar.
  This identity was verified at 433/433 rows across two components, so a failure means the
  parser is wrong, not the data. Report failures; never silently accept them.
- **Join check:** ≥90% of ingested PE numbers match an existing `program_elements.pe_number`.
  Below that, stop and report — it means the PE format needs normalizing through
  `matching/normalizer.py`, not that the data is bad.
- Unit assertion: no `enacted_k` above 1e8 (would indicate a missed dollars→thousands
  conversion).
- `TOTAL BA` rows absent from the table.
- Latest quarter per (PE, fy_start, appropriation) is identifiable — keep all quarters;
  the *history* of reprogramming across quarters is itself a feature.

**Pitfalls:** every trap in §3.1 — repeated header rows, merged-cell column offsets,
dollars vs. thousands, the FY-pair meaning, inconsistent zero-padding in URLs, and site
throttling. Pace requests and cache downloads under `data/raw/comptroller/execution/`.

### T6 — Surface execution in the UI

**Files:** `app.py`, new `analysis/execution_view.py`.
**Do:** an execution section on the Program Finder profile and, on Rhetoric vs. Budget, the
full chain: requested → authorized (House / Senate, separately) → appropriated →
reprogrammed → net. A waterfall reads better than grouped bars here.
**Accept:** above- and below-threshold reprogramming are visually and textually distinct,
with a one-line explanation that above-threshold required congressional prior approval;
years with no DD 1416 coverage render as absent, not zero; the Data Coverage tab gains a
row for the new source.
**Pitfall:** do not let this section imply the tool tracks outlays. DD 1416 is budget
authority status, not disbursement.

### T7 — Test suite

**Files:** new `tests/`, `requirements-dev.txt`, optionally `.github/workflows/ci.yml`.
**Do:** pytest. Cover the parsers with committed fixtures (R-1 XLSX slice, R-2 XML slice,
one committee-report HTML slice, one DD 1416 sheet), the normalizer, and the unit-conversion
boundaries. Wire `analysis/linker_eval.py` and `analysis/ai_budget_eval.py` in as tests so
they run automatically.
**Accept:** `pytest` green from a clean clone; fixtures small enough to commit (trim
workbooks, do not commit 900 KB files); no test requires network or an API key.
**Pitfall:** do not refactor the parsers to make them testable in the same PR. Add tests
around current behavior first; refactor later with the tests as the safety net.

### T8 — Reconciliation panel

**Files:** new `analysis/reconcile.py`, `app.py` (Data Coverage tab).
**Do:** per fiscal year per appropriation, sum ingested R-1 lines and compare to the
published topline; same for DD 1416 enacted vs. the appropriations act. Show the residual
in dollars and percent.
**Accept:** the panel shows a per-year residual with a pass/fail marker and a stated
tolerance; any year outside tolerance is explained in the UI (classified aggregates,
mandatory-stream splits, or a known parse gap) rather than hidden.
**Pitfall:** classified `9999...` placeholder PEs and the discretionary/mandatory split are
legitimate reasons a sum will not tie. Model them explicitly instead of widening the
tolerance until everything passes.

### T9 — P-1 ingest

**Files:** `parsing/xlsx_ingest.py`, new `storage/ingest_p1.py`, `storage/db.py`,
`acquisition/comptroller_scraper.py` (already supports `--exhibits procurement`).
**Do:** extend the existing XLSX parser per §3.2. Procurement needs its own table (BLI, not
PE, plus quantities) rather than being forced into `program_elements`.
**Accept:** FY2026 and FY2027 P-1 ingested; `Add/Non-Add` filtered to `Add`; quantities
preserved; discretionary and mandatory scenarios kept as separate streams; a spot-check row
ties to the spreadsheet.
**Pitfall:** do not reuse `RDTEE_ACCOUNT_RE`'s filter logic unmodified — procurement
accounts have entirely different titles.

### T10 — Transition tracing (RDT&E → procurement)

**Files:** new `analysis/transition.py`, `app.py`.
**Do:** propose candidate RDT&E→procurement links using the existing fuzzy + semantic
matchers over titles, corroborated by narrative language. Store candidates with a
confidence and the evidence snippet.
**Accept:** every proposed link renders with its confidence and evidence and is labeled an
inference; a golden set of ~20 hand-checked transitions is committed and evaluated the way
`analysis/linker_eval.py` does it; ambiguous cases surface as ambiguous.
**Pitfall:** **there is no key join** (§3.2). If this ships looking authoritative, it
undermines the credibility the rest of the tool earns. It is a *lead generator*, phrased
the way the awards search is phrased.

### T11 — PE lineage graph

**Files:** new `analysis/lineage.py`, new `storage/ingest_lineage.py`, `storage/db.py`,
`app.py`.
**Do:** detect renumbering, splits, and merges from (a) funding discontinuities in the
FY1996–FY2027 series, (b) title similarity across PEs whose series abut, and (c) transfer
language in `pe_narratives` / `pe_accomplishments` ("transferred from PE 0602115A",
"realigned to"). Store `predecessor_pe`, `successor_pe`, `relation`
(`renumbered|split|merged|transferred`), `evidence_text`, `evidence_source`, `confidence`.
Then thread the Program Finder funding chart through lineage.
**Accept:** a hand-verified golden set of at least 10 known cases; the chart marks the seam
visibly rather than splicing silently; every lineage edge is clickable to its evidence; low
confidence edges are shown as dotted/possible, never merged into the series by default.
**Pitfall:** a PE moving between budget activities changes digits 3–4 of its own number —
that is the single most common case and the easiest to detect. Start there. Do not infer a
merge from a funding drop alone; funding can drop because a program ended.

### T12 — Bulk data + versioned releases

**Files:** new `scripts/build_release.py`, `README.md`, new `DATA_DICTIONARY.md`.
**Do:** a script producing a versioned bundle (compressed SQLite + parquet + data
dictionary + row counts + source manifest) plus release notes describing what changed.
**Accept:** the script runs from a clean clone; the bundle documents every table and
column, its units, and its source; runtime AI tables are excluded by construction
(invariant 12), not by remembering to run a command.
**Pitfall:** `--reset-runtime` must be inside the release script, and the release script
must fail loudly if the compliance query in invariant 1 returns nonzero.

### T13 — Change feed

**Files:** new `analysis/changefeed.py`, `app.py`, optionally a static feed artifact.
**Do:** diff per PE across PB cycles and across committee reports; emit a feed of material
changes (new start, termination, ±X% swing, new committee action, new reprogramming).
**Accept:** deterministic output for a fixed pair of vintages; a documented threshold for
"material"; the feed links to permalinks from T1.
**Pitfall:** T4's `pb_cycle` is a prerequisite for honest diffs. Do not diff `PY Actual`
against `CY Request` and call it a change.

### T14 — RAG over narratives, extractive citations only

**Files:** `analysis/oss_enricher.py` (governed AI path), new `analysis/narrative_qa.py`,
`app.py`.
**Do:** natural-language question answering over `pe_narratives` /
`pe_accomplishments` using the existing embeddings. Retrieval is local and free; only the
synthesis step calls the model, and it goes through the existing
`cache → guard → call → meter → cache` path.
**Accept:** every sentence in an answer carries PE + fiscal year + source document; the
feature refuses ("nothing in the corpus supports an answer") rather than paraphrasing from
model memory; token and cost accounting appears in `ai_spend`; a cold cache shows a button
naming its source, a warm cache auto-renders with an "as of" caption.
**Pitfall:** this task is not grounded search — it must **not** be added to
`config.GROUNDED_TASKS`, and its results *are* shareable across users (they derive from
public-domain documents, not Google Search). Getting that classification backwards either
breaks the terms or throws away the cost savings.

### T15 — One-time structured extraction

**Files:** new `analysis/narrative_extract.py`, `storage/db.py`.
**Do:** extract contractors, transition language, test events, and locations from
narratives into typed rows, once, cached forever. Feeds T10 and T11.
**Accept:** extraction is a batch job with a resumable worklist (mirror
`analysis/ai_precompute.py`); every extracted field keeps a pointer to the sentence it came
from; cost per run is reported before the run starts.
**Pitfall:** bill `thoughts_token_count` at the output rate — thinking tokens are often
5–6× visible output and both of this project's original cost estimates were ~2× low for
exactly that reason.

---

## 5. Verification playbook

Run the relevant subset before every commit; all of it before any PR that touches data.

```bash
cd dod_ic_budget_analyzer

# Matcher quality — required after ANY change under matching/ or analysis/program_linker.py
python analysis/linker_eval.py

# AI cost math + caching rules — required after ANY change under analysis/ai_*.py or oss_enricher.py
python analysis/ai_budget_eval.py

# Grounded-results compliance — MUST return 0
sqlite3 data/processed/usg_budgets.db \
  "SELECT COUNT(*) FROM ai_cache WHERE task IN ('find_open_source_hits','annual_signal');"

# Tests (once T7 lands)
pytest -q

# App smoke test — load every tab, watch the console for tracebacks
python -m streamlit run app.py --server.headless true --server.port 8501

# AI spend to date
python -m analysis.ai_budget --report

# After any ingest, before committing the archive
python -m analysis.ai_budget --reset-runtime
gzip -9 -c data/processed/usg_budgets.db > data/processed/usg_budgets.db.gz
```

Row-count sanity after an ingest — compare against §1's table before and after, and state
the delta in the commit message.

---

## 6. Working conventions

- **One task per PR**, in roadmap order within a phase. A PR that touches two tasks is a
  PR that cannot be reverted cleanly.
- **Commit subjects are imperative and describe the outcome**, matching existing history:
  "Ship the database compressed and expand it on first use", "Make the app installable and
  deployable off this machine". Not "fix stuff", not "T5".
- **Never commit** `data/raw/`, the uncompressed `.db`, API keys, `.env`, or AI runtime
  rows.
- **State coverage honestly in the UI.** If a source covers FY2013–FY2026, the UI says so;
  absent years render as absent, never as zero.
- **Do not** reformat `app.py` wholesale, restructure the matching package, or "clean up"
  the two-call AI pattern (invariant 2) as a side effect of another task.
- If a source has moved or changed shape, **stop and report** rather than loosening a
  parser until it accepts whatever it finds. Silent acceptance of malformed data is the
  failure mode that killed every competing open-source parser.

## 7. Do not guess — escalate these

1. **Any DD 1416 arithmetic self-check failure at all** (T5). The identity was verified at
   433/433 rows, so failures mean the column map is wrong or the source changed shape. Both
   need a human look. Do not widen the tolerance.
2. **PE join rate below 90%** on DD 1416 ingest (T5). Could be a normalization gap or a
   component-naming mismatch — do not paper over it with fuzzy matching.
3. **Which Green Book table is the RDT&E deflator** (T3). §3.3 is `[reported]`, not
   verified. Read the actual PDF and confirm before wiring numbers into charts.
4. **Whether R-3 exhibits print usable contract numbers** (T10). `[reported]`. Verify
   against a real R-3 before designing the evidence layer around it.
5. **Anything that would raise steady-state memory** above ~700 MB (invariant 11), or add a
   dependency heavier than what is already in `requirements.txt`.
6. **Any change to how grounded vs. shared AI results are classified** (invariants 1–2).
   This is a terms-of-service boundary, not an engineering preference.
