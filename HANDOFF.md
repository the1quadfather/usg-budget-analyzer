# DoD Budget Explorer — engineering handoff (2026-09-08)

## Current release state

The roadmap implementation is complete in the working tree. The app now traces
RDT&E from President's Budget submission, through separate House/Senate
authorization actions and enacted funding, into DD 1416 execution adjustments
and the net current program. It also exposes official-source provenance,
downloadable CSV/XLSX tables, shareable query-state URLs, and then-year versus
constant-FY2025 views.

Run from `dod_ic_budget_analyzer/`:

```bash
python -m pytest -q
python -m analysis.ai_budget_eval
python -m analysis.linker_eval
python -m streamlit run app.py
```

Latest verification: 19 pytest checks passed, AI governance 51/51, and linker
golden set 11/11. The semantic matcher may fall back to lexical matching when
the Hugging Face model is not already cached and network access is unavailable.

## Shipped data

- 2,131 program records / 2,055 distinct PE numbers.
- 55,652 funding observations, FY1996–FY2027, with source PB cycle and document.
- 192 mandatory/reconciliation observations retained as separate funding types.
- 1,383 distinct PEs with R-2 narratives.
- 26,544 congressional action rows, FY2012–FY2027.
- 79,677 DD 1416 rows from 381 official RDT&E workbooks, report dates
  2012-12-31 through 2026-03-31; 97.1% distinct PE/component join rate.
- All 381 DD 1416 documents have stored official source URLs and content hashes;
  all 29 R-1 source documents have stored official source URLs.

The DD 1416 source index has eight FY2021 links containing a nonexistent `6_31`
directory; the official server returns 404. The downloader records the warning
and never invents replacement URLs.

## Reproducible data shipment

The raw SQLite file is gitignored. The tracked artifact is
`data/processed/usg_budgets.db.gz`; `storage.db.get_engine()` expands it on first
use. Rebuild funding from the tracked parquet and package the database with:

```bash
python -m storage.rebuild_funding
python -m storage.ingest_dd1416 --years 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026 --download
python -m analysis.ai_budget --reset-runtime
python -m storage.build_archive
```

`rebuild_funding` and `build_archive` validate that their targets are direct
children of `data/processed`; the archive replacement is atomic. DD 1416
ingestion parses and reconciles every workbook before opening the write
transaction, enforces a 90% PE join guardrail, hashes documents and rows, and is
idempotent per source document.

## Gemini demo isolation

For a local personal-key demo, inject `GEMINI_API_KEY` only into the current
PowerShell process and bind Streamlit to `127.0.0.1`. For a hosted private demo,
configure Streamlit OIDC and `demo_allowed_emails` in Secrets. The allowlist gate
runs before database/model initialization and fails closed for anonymous or
unapproved identities. Leave the key out entirely for a public deployment.

Grounded Gemini results remain per-user, never enter the shared cache, retain
required Search Suggestions, and expire within the configured two-year maximum.
The monthly global dollar ceiling and per-user fresh-call credits remain active.
Always run `analysis.ai_budget --reset-runtime` immediately before packaging a
public database.

## High-value next work

1. Reconcile R-1 and DD 1416 account totals against published appropriation
   toplines and display automated exception reports.
2. Add procurement P-1 ingestion and evidence-backed RDT&E transition leads.
3. Model PE renumbering, splits, merges, and transfers across PB cycles.
4. Publish versioned bulk-data releases and a PE-level change feed.

Do not describe DD 1416 as obligations or outlays, combine House and Senate
authorization figures, merge mandatory and discretionary funding streams, or
publish grounded Gemini results across users.
