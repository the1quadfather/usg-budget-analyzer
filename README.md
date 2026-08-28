# DoD Budget Explorer

Trace a US defense program from **what was asked for**, to **what Congress
provided**, to **what the money did**, to **what officials said about it** —
in one local tool.

The explorer ingests official machine-readable budget data (R-1 exhibits,
R-2 justification books), links it to execution data (USAspending.gov), and
layers optional AI enrichment (Gemini with web grounding) for open-source
context. Everything runs locally against a SQLite database.

## What it does

| Tab | Question it answers |
|---|---|
| **Budget Trends** | How has RDT&E funding moved by component, FY1998–FY2027? Who got paid from each appropriation account? |
| **Program Finder** | Which budget program is this name / news quote / PE number? Then a full profile: funding history, official plans & reported work, contract awards, recent coverage |
| **Rhetoric vs. Budget** | Did the money follow the talk? What was requested vs. what the authorizing committees actually authorized, with the reason they printed — an exact join, no API key. Optionally overlaid with AI-characterized public emphasis and a lead-aware alignment coefficient |
| **Data Coverage** | What's ingested, what's live-queried, and the known blind spots |

Program matching is multi-stage: exact PE-number lookup, lexical matching
over titles/acronyms/project names, and semantic embeddings enriched with
official mission descriptions — with honest ambiguity flagging when several
programs share a name (joint programs usually do).

## Architecture

```mermaid
flowchart LR
    subgraph Sources
        A[comptroller.war.gov<br/>R-1 XLSX + R-2 XML]
        B[USAspending.gov API]
        C[Gemini + web search<br/>optional]
    end
    subgraph Pipeline
        D[acquisition/] --> E[parsing/]
        E --> F[(SQLite<br/>usg_budgets.db)]
    end
    subgraph App
        G[matching/<br/>fuzzy + semantic]
        H[analysis/<br/>trends, alignment, awards]
        I[Streamlit UI]
    end
    A --> D
    F --> G --> I
    F --> H --> I
    B --> H
    C --> H
```

## Quickstart (local)

Requires Python 3.12+.

```bash
cd dod_ic_budget_analyzer
pip install -r requirements.txt
streamlit run app.py
```

The repository ships with the processed database (FY1998–FY2027 R-1 funding,
PB2026–PB2027 Defense-Wide narratives, and FY2022/FY2024/FY2026 House
authorization actions), so the app is useful immediately.
The first Program Finder search downloads the sentence-transformer model
(one time, ~90MB).

### Optional: AI features

Set a Gemini API key to enable ambiguity resolution, "In the News," and the
optional open-source-emphasis layer on the Rhetoric vs. Budget tab. The
congressional requested-vs-authorized figures on that tab need **no key** and
cost nothing per user:

```bash
setx GEMINI_API_KEY "your-key"     # Windows; export on Linux/macOS
```

**Keys are per-user and never live in this repository.** The app reads
`GEMINI_API_KEY` (or `GOOGLE_API_KEY`) from the environment only — there is
no key file, config entry, or Docker build argument for it, and `.env` files
are gitignored as a guardrail. Don't commit credentials in any form.

### AI cost control

Every AI call is cached, metered, and capped. Results that have been fetched
before render as soon as you open the tab; only genuinely new lookups cost
anything, and a monthly ceiling stops fresh calls before a bill can run away.
Knobs live in `config.py` (`AI_MONTHLY_BUDGET_USD`, `AI_FREE_CREDITS_PER_MONTH`,
`AI_CACHE_TTL_DAYS`).

```bash
python -m analysis.ai_budget --report          # month-to-date spend by task
python -m analysis.ai_budget --prune           # drop expired cache rows
python -m analysis.ai_budget --reset-runtime   # clear ALL runtime rows (see below)
python analysis/ai_budget_eval.py              # self-check: cost math + caching rules
```

**Run `--reset-runtime` before committing.** The SQLite database is tracked in this
public repository, so a dev session's cached AI results, spend ledger, and search log
would otherwise be published — and grounded search results must never be. The command
clears those four tables and VACUUMs the file so deleted rows are not merely unlinked.

Warm the cache ahead of time so the app opens with analysis already in place.
It picks targets from real search demand first, then the largest programs:

```bash
python analysis/ai_precompute.py --limit 20 --dry-run   # show the worklist
python analysis/ai_precompute.py --limit 20             # warm it
```

**Two rules the code enforces, both from the
[Gemini API terms](https://ai.google.dev/gemini-api/terms):**

- Results grounded in Google Search are stored **per user and never shared**,
  and always render with Google's Search Suggestions. Match resolution, which
  doesn't use search, is shared across everyone — so a program someone else
  already resolved costs you nothing.
- Web-grounded features **verify that the search actually ran**. This model
  will happily answer a "find recent coverage" prompt from memory, producing
  invented outlets and dates that look identical to real ones. When no search
  happened, the app shows nothing and says why rather than presenting
  recollection as sourced reporting.

## Quickstart (Docker)

```bash
cd dod_ic_budget_analyzer
docker compose up --build
```

Then open http://localhost:8501. The compose file mounts `./data` (database
persists outside the container), passes `GEMINI_API_KEY` through from your
environment, and caches the embedding model in a named volume.

## Updating the data

New budget cycle? Three commands:

```bash
# 1. Official R-1 spreadsheet (machine-readable, FY2012+)
python acquisition/comptroller_scraper.py --xlsx --years 2028 --exhibits rdtee

# 2. Parse and save
python parsing/xlsx_ingest.py --file data/raw/comptroller/2028/rdtee/fy2028_r1.xlsx --save

# 3. R-2 justification books (Defense-Wide XML) + ingest
python acquisition/r2_downloader.py --years 2028 --ingest
```

Then ingest the new parquet into SQLite with `storage/ingest_r1.py` (see the
notebook in `notebooks/` for the pattern). Matching quality is guarded by a
golden-set eval — run it after any matcher change:

```bash
python analysis/linker_eval.py
```

`data/raw/` is not tracked (≈55MB of re-downloadable PDFs/XLSX/XML); the
pipeline above rebuilds it. Pre-FY2012 years came from parsed PDFs and are
already in the shipped database.

## Data sources & honesty notes

- **R-1 exhibits** (comptroller.war.gov): official XLSX for FY2012–FY2027,
  parsed PDFs for FY1998–FY2011. Discretionary and reconciliation/mandatory
  funds are kept as separate streams.
- **R-2 justification books**: official DTIC-schema XML, published from the
  PB2026 cycle onward, Defense-Wide components only (the services publish
  PDF-only). Mission descriptions, projects, and per-year accomplishment
  line items with funding.
- **NDAA authorization committee reports** (govinfo.gov): the RDT&E funding
  tables printed in HASC/SASC reports, parsed to per-program-element
  requested / committee change / authorized figures plus the committee's own
  stated reason. Key-free and, as US Government works (17 U.S.C. 105), public
  domain. **Machine-readable tables begin at FY2012** — earlier reports print
  them as GRAPHIC images, so an absent year means "not available," not "no
  action taken." A program element can hold several lines in one report (one
  per budget activity); those are summed per fiscal year, while House and
  Senate are never pooled because they score the same request separately.
  Authorization is not appropriation.
- **USAspending.gov**: live queries. Public award records carry **no
  program-element linkage**, so program-level award search is keyword
  matching — the UI labels it "leads, not a ledger." Other Transactions
  aren't a searchable instrument group; DoD awards post with a ~90-day
  delay; umbrella vehicles (PIAs, IDIQs) hide task detail in generic prime
  descriptions (a subaward search partially compensates).
- **AI enrichment**: clearly labeled as AI estimates. The Rhetoric vs.
  Budget signal is an LLM characterization grounded in web search, not a
  media-analytics count; its alignment coefficient is a Spearman rank
  correlation at 0–2-year funding leads and refuses to compute on fewer
  than 4 overlapping years. Both web-grounded features discard output the
  model produced without actually searching, so an empty panel means "nothing
  retrieved," never "here's what I vaguely recall."

## Project layout

```
dod_ic_budget_analyzer/
├── acquisition/     # downloaders: comptroller XLSX/PDF, R-2 XML, USAspending
├── parsing/         # R-1 XLSX/PDF parsers, R-2 jbook XML parser
├── storage/         # SQLAlchemy schema + ingest pipelines
├── matching/        # normalizer, fuzzy matcher, semantic matcher
├── analysis/        # trends, program linker, awards, rhetoric alignment, eval
├── data/processed/  # SQLite DB, parquet, embedding cache (tracked)
├── data/raw/        # source documents (not tracked; rebuildable)
└── app.py           # Streamlit UI
```

## Roadmap

- Service R-2 narratives (Army/Navy/AF publish PDF-only — needs extraction)
- Re-base FY2012–FY2026 funding on official XLSX end to end
- Enacted-vs-request deltas from appropriations Joint Explanatory Statements
- IC topline (NIP/MIP) tracking
- UI polish pass
