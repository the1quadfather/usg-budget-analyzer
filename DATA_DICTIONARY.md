# USG Budget Analyzer data dictionary

This document describes the SQLite database shipped with the repository at
`dod_ic_budget_analyzer/data/processed/usg_budgets.db.gz`. The snapshot was checked on
2026-09-18 at repository commit `b1a3885e4bec042db6ad5709c6f862844fc5bdd8`
(`codex/t11e` when inspected). The archive blob is
`f2aa7a54e64453e05351a4a8f928d961a85295ce`; it was last rebuilt in commit
`b1a3885e4bec042db6ad5709c6f862844fc5bdd8`. The archive contains 13 tables and 43
indexes.

The nine data tables below ship with records. Four additional runtime table schemas ship
empty and are documented separately under [Runtime tables, not shipped](#runtime-tables-not-shipped).

## Row counts and origins

These counts come from the compressed archive, not from a developer's ignored working
database. Runtime activity can add rows to a working database after it is expanded.

| Table | Rows | Source exhibit or origin |
|---|---:|---|
| `source_documents` | 412 | Registry of ingested files: 29 R-1, 381 DD 1416, and 2 P-1 documents |
| `program_elements` | 2,131 | R-1 `r1_display.xlsx`, plus pre-FY2012 R-1 PDF/OCR rows |
| `funding_lines` | 55,652 | R-1 funding observations; PB cycles 1998–2027 |
| `procurement_lines` | 5,253 | P-1 `p1_display.xlsx` for PB2026 and PB2027 |
| `pe_execution` | 79,677 | DD 1416 quarterly execution workbooks |
| `pe_congressional_actions` | 26,544 | House and Senate NDAA committee-report authorization tables, FY2012–FY2027 |
| `pe_narratives` | 18,268 | R-2 justification books in XML and PDF |
| `pe_accomplishments` | 101,219 | R-2 accomplishment and planned-program line items |
| `pe_lineage` | 405 | Derived from R-1 funding and R-2 narratives |
| `ai_cache` | 0 | Runtime only; reset before every archive build |
| `ai_spend` | 0 | Runtime only; reset before every archive build |
| `ai_user_history` | 0 | Runtime only; reset before every archive build |
| `search_log` | 0 | Runtime only; reset before every archive build |

## Units and conventions

`funding_lines.amount_thousands`, `procurement_lines.amount_thousands`, and every column
ending in `_k` are thousands of then-year dollars. `pe_accomplishments.funding_millions`
is millions of then-year dollars, and `procurement_lines.quantity` is a unit count.
Columns ending in `_fy`, columns named `fiscal_year`, and `pb_cycle` are integer fiscal
years; a PB cycle identifies the President's Budget submission, not necessarily the
fiscal year of an observation. `report_date` is an ISO date string, while `retrieved_at`,
`processed_date`, `ingested_at`, `created_at`, `expires_at`, and `ts` are ISO-compatible
SQLite timestamps. Text identifiers such as PE numbers and line numbers are strings so
leading zeroes are preserved. Missing coverage is absent or `NULL`, never an implied
zero. Discretionary and mandatory funding are separate streams. House and Senate actions
are separate authorization positions and must never be pooled or described as
appropriations.

## `source_documents`

Provenance registry for the government source files used by the database. It contains
three `document_type` values: `R1` (29 rows), `DD1416` (381), and `P1` (2).

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `filename` | `VARCHAR(255)` | No | Unique source filename |
| `document_type` | `VARCHAR(50)` | No | Source family: `R1`, `DD1416`, or `P1` |
| `publication_year` | `INTEGER` | No | Fiscal year/PB cycle under which the source was published |
| `processed_date` | `DATETIME` | No | UTC ingestion-processing timestamp |
| `source_url` | `VARCHAR(2048)` | Yes | Official or archival source URL |
| `retrieved_at` | `DATETIME` | Yes | Source retrieval timestamp |
| `content_hash` | `VARCHAR(64)` | Yes | Content hash used to identify the retrieved file |

## `program_elements`

Canonical RDT&E Program Element records from R-1 `r1_display.xlsx`, parsed by
`parsing/xlsx_ingest.py`, plus pre-FY2012 R-1 PDF/OCR rows. A PE is identified by the
pair `(pe_number, agency)`; the same PE number can occur under more than one component.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `source_document_id` | `INTEGER` | No | Foreign key to the originating `source_documents` row |
| `pe_number` | `VARCHAR(50)` | No | Program Element identifier, retained as text |
| `line_item_number` | `VARCHAR(50)` | Yes | R-1 line-item number printed for the PE |
| `program_name` | `VARCHAR(500)` | No | R-1 program title |
| `agency` | `VARCHAR(100)` | No | DoD component or agency |
| `budget_activity` | `INTEGER` | Yes | R-1 budget-activity number |

## `funding_lines`

Versioned R-1 funding observations joined to `program_elements`. A fiscal year can appear
in as many as three PB submissions: budget-year request, later current-year request, and
later prior-year actual. Mandatory/reconciliation observations remain a separate stream.

`funding_type` has exactly six values in the archive:

| Value | Rows |
|---|---:|
| `PY Actual` | 20,692 |
| `CY Request` | 16,055 |
| `BY Request` | 18,713 |
| `PY Mandatory` | 6 |
| `CY Mandatory` | 160 |
| `BY Mandatory` | 26 |

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `program_element_id` | `INTEGER` | No | Foreign key to `program_elements` |
| `fiscal_year` | `INTEGER` | No | Fiscal year represented by the amount |
| `funding_type` | `VARCHAR(50)` | No | One of the six basis/stream values listed above |
| `amount_thousands` | `FLOAT` | No | Thousands of then-year dollars |
| `source_document_id` | `INTEGER` | Yes | Foreign key to the R-1 source carrying this observation |
| `pb_cycle` | `INTEGER` | Yes | President's Budget submission cycle; 1998–2027 in the archive |

## `procurement_lines`

P-1 procurement observations from `p1_display.xlsx` for PB2026 and PB2027, ingested by
`storage/ingest_p1.py`. A BLI is not a Program Element and has no direct key join to RDT&E.
Rows are cost-type lines; neither amounts nor quantities should be blindly summed across
cost types. The natural identity includes BLI, agency, appropriation, budget activity,
line number, cost type and title, fiscal year, funding type, PB cycle, and source.

`funding_type` uses the same six names as R-1:

| Value | Rows |
|---|---:|
| `PY Actual` | 1,763 |
| `CY Request` | 1,658 |
| `BY Request` | 1,532 |
| `PY Mandatory` | 9 |
| `CY Mandatory` | 138 |
| `BY Mandatory` | 153 |

Observed `cost_type` values are:

| Value | Rows | Meaning |
|---|---:|---|
| `A` | 4,808 | Weapon System Cost |
| `B` | 131 | Less: Advance Procurement (PY) |
| `C` | 130 | Advance Procurement (CY) |
| `E` | 9 | Shipbuilding completion line; use `cost_type_title` for the printed meaning |
| `G` | 1 | Shipbuilding completion line; use `cost_type_title` for the printed meaning |
| `L` | 32 | Shipbuilding completion line; use `cost_type_title` for the printed meaning |
| `N` | 97 | Shipbuilding completion line; use `cost_type_title` for the printed year/meaning |
| blank string | 45 | No cost-type split printed |

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `source_document_id` | `INTEGER` | No | Foreign key to the P-1 `source_documents` row |
| `bli` | `VARCHAR(50)` | No | Budget Line Item code; not a PE number |
| `line_item_title` | `VARCHAR(500)` | No | Printed BLI title |
| `agency` | `VARCHAR(100)` | No | DoD component or organization |
| `appropriation` | `VARCHAR(100)` | No | Procurement account/appropriation code |
| `budget_activity` | `INTEGER` | Yes | P-1 budget-activity number |
| `line_number` | `VARCHAR(10)` | No | Printed P-1 line number; part of row identity |
| `bsa` | `VARCHAR(10)` | No | Budget SubActivity code |
| `bsa_title` | `VARCHAR(200)` | No | Budget SubActivity title |
| `cost_type` | `VARCHAR(10)` | No | Cost-type code listed above; may be a blank string |
| `cost_type_title` | `VARCHAR(200)` | No | Printed cost-type title; part of row identity |
| `fiscal_year` | `INTEGER` | No | Fiscal year represented by the amount or quantity |
| `funding_type` | `VARCHAR(50)` | No | One of the six basis/stream values listed above |
| `amount_thousands` | `FLOAT` | No | Thousands of then-year dollars |
| `quantity` | `FLOAT` | Yes | Unit count; do not sum across cost types |
| `pb_cycle` | `INTEGER` | No | President's Budget submission cycle |
| `content_hash` | `VARCHAR(64)` | No | Stable row-content identity hash |
| `ingested_at` | `DATETIME` | No | UTC ingestion timestamp |

## `pe_execution`

Quarterly budget-authority status for RDT&E PE lines from DD 1416 workbooks. Multiple rows
for one PE can be legitimate because appropriation year, line number, and budget activity
are part of the row identity. DD 1416 amounts are budget authority, not obligations or
outlays.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `source_document_id` | `INTEGER` | Yes | Foreign key to the DD 1416 source document |
| `pe_number` | `VARCHAR(50)` | No | Program Element identifier |
| `agency` | `VARCHAR(100)` | No | DoD component or agency |
| `appropriation` | `VARCHAR(50)` | No | Appropriation/account identifier |
| `fy_start` | `INTEGER` | No | First fiscal year of the appropriation period |
| `fy_end` | `INTEGER` | No | Last fiscal year of the appropriation period |
| `report_date` | `VARCHAR(10)` | No | DD 1416 quarter-end date in ISO `YYYY-MM-DD` form |
| `line_number` | `VARCHAR(50)` | Yes | DD 1416 line number; part of row identity when present |
| `program_title` | `VARCHAR(500)` | No | Program title printed in the workbook |
| `budget_activity` | `INTEGER` | Yes | Budget-activity number; part of row identity |
| `request_k` | `FLOAT` | Yes | President's Budget request, thousands of dollars |
| `enacted_k` | `FLOAT` | Yes | Enacted budget-authority baseline, thousands of dollars |
| `statutory_adj_k` | `FLOAT` | Yes | Statutory adjustment, thousands of dollars |
| `suppl_resc_seq_k` | `FLOAT` | Yes | Supplemental, rescission, or sequestration adjustment, thousands of dollars |
| `other_adj_k` | `FLOAT` | Yes | Other adjustment, thousands of dollars |
| `above_threshold_reprog_k` | `FLOAT` | Yes | Above-threshold reprogramming, thousands of dollars |
| `below_threshold_reprog_k` | `FLOAT` | Yes | Below-threshold reprogramming, thousands of dollars |
| `net_k` | `FLOAT` | Yes | Net current program, thousands of dollars |
| `source_file` | `VARCHAR(255)` | No | Source workbook filename |
| `content_hash` | `VARCHAR(64)` | No | Stable row-content identity hash |
| `ingested_at` | `DATETIME` | No | UTC ingestion timestamp |

## `pe_congressional_actions`

Authorization-committee positions parsed from RDT&E funding tables in House and Senate
NDAA committee reports, with machine-readable coverage from FY2012 through FY2027. These
are authorization actions, not appropriations or enacted funding. `chamber` has exactly
two values: `House` (13,097 rows) and `Senate` (13,447). The chambers independently score
the request and must never be pooled.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `pe_number` | `VARCHAR(50)` | No | Program Element identifier or classified placeholder |
| `agency` | `VARCHAR(100)` | No | DoD component or agency |
| `fiscal_year` | `INTEGER` | No | Fiscal year addressed by the committee table |
| `chamber` | `VARCHAR(16)` | No | `House` or `Senate` |
| `report_citation` | `VARCHAR(64)` | No | Committee-report citation |
| `line_number` | `VARCHAR(10)` | No | Printed report line number; part of the natural key |
| `program_title` | `VARCHAR(500)` | No | Program title printed in the report |
| `budget_activity_title` | `VARCHAR(200)` | Yes | Printed budget-activity title |
| `request_k` | `FLOAT` | Yes | Administration request, thousands of dollars |
| `committee_delta_k` | `FLOAT` | Yes | Committee increase or decrease, thousands of dollars |
| `authorized_k` | `FLOAT` | Yes | Committee authorization position, thousands of dollars; not an appropriation |
| `rationale` | `TEXT` | Yes | Printed committee rationale or program-increase text |
| `is_classified` | `INTEGER` | No | Boolean `0`/`1`; `1` marks a classified placeholder rather than a real PE |
| `reconciled` | `INTEGER` | No | Boolean `0`/`1`; `1` means `request_k` matched that FY's `CY Request` line |
| `content_hash` | `VARCHAR(64)` | No | Stable row-content identity hash |
| `ingested_at` | `DATETIME` | No | UTC ingestion timestamp |

## `pe_narratives`

Program- and project-level mission narratives from R-2 justification books. PB2026 and
later Defense-Wide material uses XML; service books and earlier coverage use the PDF path
in `parsing/r2_parser.py` and `parsing/r2_pdf_parser.py`. An empty `project_number` marks a
PE-level narrative; 5,864 archived rows have that form.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `pe_number` | `VARCHAR(50)` | No | Program Element identifier |
| `agency` | `VARCHAR(100)` | No | DoD component or agency |
| `fiscal_year` | `INTEGER` | No | Fiscal year/PB context of the source R-2 book |
| `project_number` | `VARCHAR(50)` | No | R-2 project identifier; blank for a PE-level mission narrative |
| `project_title` | `VARCHAR(500)` | Yes | Printed R-2 project title |
| `description` | `TEXT` | No | Mission or project narrative text |
| `source_file` | `VARCHAR(255)` | No | Source R-2 XML or PDF filename |

## `pe_accomplishments`

R-2 accomplishment and planned-program entries, including narrative text and the funding
printed for a prior-, current-, or budget-year bucket. `fiscal_year` identifies the source
book's budget cycle; `accomplishment_fy` identifies the year discussed by the entry.

`year_label` is not a clean database enumeration. The intended labels are
`Description`, `Plans`, `Accomplishments`, `Base Plans`, `OCO Plans`,
`Increase/Decrease St` (the 20-character stored form of “Increase/Decrease Statement”),
`PY`, `CY`, `BY`, and `New Start`. The archive has 29 distinct values and 298 rows outside
that intended set. Per the task's classification, those other labels are PDF-parser
leakage and remain unmodified. The observed leakage values and counts are:

| Observed value | Rows | Observed value | Rows |
|---|---:|---|---:|
| `BASE PLANS WEAPONS A` | 3 | `Base funds will prov` | 1 |
| `Continued testing of` | 2 | `Funding increase` | 1 |
| `New Start Efforts` | 1 | `New start` | 3 |
| `OMA Plans` | 10 | `OOC Plans` | 246 |
| `OPA Plans` | 5 | `Plan` | 2 |
| `RDTE Plans` | 12 | `activities include` | 1 |
| `efforts include` | 3 | `funding supports ass` | 1 |
| `funding supports pro` | 1 | `funds supports but i` | 1 |
| `funds will support` | 1 | `funds will support b` | 1 |
| `plans are to` | 3 |  |  |

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `pe_number` | `VARCHAR(50)` | No | Program Element identifier |
| `agency` | `VARCHAR(100)` | No | DoD component or agency |
| `fiscal_year` | `INTEGER` | No | Fiscal year/PB context of the source R-2 book |
| `project_number` | `VARCHAR(50)` | No | R-2 project identifier; blank when no project is specified |
| `title` | `VARCHAR(500)` | Yes | Accomplishment or planned-program title |
| `year_label` | `VARCHAR(20)` | No | Intended bucket or observed parser label described above |
| `accomplishment_fy` | `INTEGER` | Yes | Fiscal year to which the narrative/funding entry applies |
| `funding_millions` | `FLOAT` | Yes | Millions of then-year dollars printed for the entry |
| `text` | `TEXT` | No | Accomplishment or plan narrative |
| `source_file` | `VARCHAR(255)` | No | Source R-2 XML or PDF filename |

## `pe_lineage`

Evidence-backed predecessor/successor relationships between Program Elements. This is a
derived table, not a source exhibit: `analysis/lineage.py` derives it from
`funding_lines` and `pe_narratives`, and `storage/ingest_lineage.py` rebuilds it.

`relation` contains `transferred` (403 rows) and `renumbered` (2). The analysis-layer
`Relation` type also permits `split` and `merged`, but no current detector emits them.
`method` contains `narrative` (403 rows) and `ba_renumber` (2).

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `predecessor_pe` | `VARCHAR(50)` | No | Pre-transition PE identifier |
| `predecessor_agency` | `VARCHAR(100)` | No | Predecessor component or agency |
| `successor_pe` | `VARCHAR(50)` | No | Post-transition PE identifier |
| `successor_agency` | `VARCHAR(100)` | No | Successor component or agency |
| `relation` | `VARCHAR(50)` | No | Observed `transferred` or `renumbered`; analysis also permits `split`/`merged` |
| `first_fy_after` | `INTEGER` | No | First fiscal year after the detected transition |
| `evidence_text` | `TEXT` | Yes | Supporting R-2 sentence; `NULL` for funding-series-only evidence |
| `evidence_source` | `VARCHAR(255)` | Yes | Source filename or `funding_series` marker |
| `confidence` | `FLOAT` | No | Detector confidence score on a zero-to-one scale |
| `method` | `VARCHAR(50)` | No | `narrative` or `ba_renumber` |
| `content_hash` | `VARCHAR(64)` | No | Stable edge-content identity hash |
| `ingested_at` | `DATETIME` | No | UTC ingestion timestamp |

## Derived tables

`pe_lineage` is the only shipped data table whose rows are analytical output rather than
direct source observations. Its evidence remains traceable to R-1 funding series or R-2
narratives through `method`, `evidence_source`, and `evidence_text`. Rebuilding it replaces
the detector-produced rows; it does not alter the underlying R-1 or R-2 tables.

## Runtime tables, not shipped

The following schemas are present so a cloned application can run immediately, but their
contents are not part of the public data product. All four tables have zero rows in the
archive. `python -m analysis.ai_budget --reset-runtime` clears them before each archive
build. In particular, grounded AI results are per-user and never enter the shared cache.

### `ai_cache`

Shared runtime cache for non-grounded AI results only. Grounded-search results belong in
`ai_user_history`, never here.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `cache_key` | `VARCHAR(64)` | No | Unique normalized request/cache hash |
| `task` | `VARCHAR(50)` | No | AI task identifier |
| `params_json` | `TEXT` | No | JSON-encoded task parameters |
| `model` | `VARCHAR(100)` | No | Model identifier |
| `prompt_version` | `INTEGER` | No | Prompt/schema version used for the result |
| `payload_json` | `TEXT` | No | JSON-encoded cached result |
| `created_at` | `DATETIME` | No | UTC creation timestamp |
| `expires_at` | `DATETIME` | No | UTC expiration timestamp |

### `ai_spend`

Runtime ledger with one row per AI call attempt, including cache hits and failed calls.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `ts` | `DATETIME` | No | UTC call timestamp |
| `user_id` | `VARCHAR(128)` | No | Local or authenticated user identifier |
| `task` | `VARCHAR(50)` | No | AI task identifier |
| `model` | `VARCHAR(100)` | No | Model identifier |
| `input_tokens` | `INTEGER` | No | Input-token count |
| `output_tokens` | `INTEGER` | No | Output-token count |
| `thought_tokens` | `INTEGER` | No | Reasoning-token count |
| `search_queries` | `INTEGER` | No | Grounded-search query count |
| `est_cost_usd` | `FLOAT` | No | Estimated cost in US dollars |
| `cache_hit` | `INTEGER` | No | Boolean `0`/`1`; `1` means no paid model call was needed |
| `ok` | `INTEGER` | No | Boolean `0`/`1`; `0` marks a failed call |

### `ai_user_history`

Per-user runtime history for grounded AI results. Rows are keyed to a user, are never
served to another user, and are retained only for the configured grounded-history period.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `user_id` | `VARCHAR(128)` | No | User-scoped identifier |
| `cache_key` | `VARCHAR(64)` | No | Normalized request/cache hash |
| `task` | `VARCHAR(50)` | No | Grounded AI task identifier |
| `params_json` | `TEXT` | No | JSON-encoded task parameters |
| `model` | `VARCHAR(100)` | No | Model identifier |
| `payload_json` | `TEXT` | No | JSON-encoded result shown to that user |
| `search_suggestions_html` | `TEXT` | Yes | Provider-supplied grounded-search suggestion markup |
| `created_at` | `DATETIME` | No | UTC creation timestamp |
| `expires_at` | `DATETIME` | No | UTC expiration timestamp |

### `search_log`

Runtime log of Program Finder searches, used to prioritize precomputation and expand the
linker evaluation set.

| Column | SQL type | Nullable | Unit or meaning |
|---|---|:---:|---|
| `id` | `INTEGER` | No | Primary-key row identifier |
| `ts` | `DATETIME` | No | UTC search timestamp |
| `user_id` | `VARCHAR(128)` | No | Local or authenticated user identifier |
| `query` | `VARCHAR(500)` | No | User-entered search text |
| `matched_pe` | `VARCHAR(50)` | Yes | PE selected as the search result, if any |
| `agency` | `VARCHAR(100)` | Yes | Component paired with `matched_pe`, if any |
| `needs_review` | `INTEGER` | No | Boolean `0`/`1`; `1` flags the match for review |
