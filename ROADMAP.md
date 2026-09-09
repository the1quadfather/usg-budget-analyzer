# DoD Budget Explorer — roadmap

Written 2026-09-08 after a competitive scan of the defense-budget tooling landscape
(Gemini grounded search, three passes) plus direct verification of every data source
named here. Source facts, exact URLs, file structures, and per-task specs live in
[CODEX_HANDOFF.md](CODEX_HANDOFF.md) — this document is the *why* and the *order*.

Milestones 1 (AI cost control) and 2 (congressional actions + service R-2 corpus) are
shipped. This roadmap covers M3 onward.

---

## The strategic read

**The free tier of this market is siloed, and the paid tier sells joins plus plumbing.**

- Official sources are authoritative but disconnected: comptroller.war.gov publishes
  ground truth mostly as PDFs, USAspending has an excellent API but *no program-element
  linkage*, congress.gov has the bills but prints funding tables as unstructured text.
- Think-tank tools (CSIS Defense360, the CSIS/AEI Defense Futures Simulator, Stimson,
  Mitchell Institute) stop at service/title aggregates. None go down to the PE.
- The paid tier — Obviant, HigherGov, Bloomberg Government, Govini Ark, Deltek GovWin —
  sells almost exactly the joins this project already built, wrapped in product plumbing
  it does not yet have: **permalinks, exports, saved-search alerts, request-vs-enacted,
  and line-item tracing across budget cycles.**

So: this project is closer to Obviant's core proposition than to an abandoned GitHub
parser, and the gap is mostly *not* more AI. It is (a) three days of product plumbing,
(b) two official machine-readable sources nobody is using, and (c) a trust layer.

**The finding that reorders everything:** the DoD Comptroller publishes the **DD 1416
"Report of Programs" quarterly execution reports as XLSX, keyed on program element**,
with columns for President's Budget Request, Enacted Appropriation, statutory
adjustments, supplementals/rescissions/sequestration, **above-threshold reprogramming**,
**below-threshold reprogramming**, and **Net**. Per service, per appropriation,
quarterly, back to at least FY2013. No OCR. No PDF parsing. Key-free.

That single source collapses three separate roadmap items (enacted figures, reprogramming
actions, and execution truth) into one XLSX ingest that joins *exactly* to
`program_elements.pe_number`. It is the highest-value work in this document and it is
easier than what has already been done. See Phase B.

The files were parsed during this session to de-risk the estimate: the internal
reconciliation identity (`enacted + adjustments + reprogramming = net`) holds at **433/433
rows** across two components. One trap found and documented — column positions differ
between component files, so the parser must map by header text.

---

## Phases

| Phase | Theme | Tasks | Effort | Payoff |
|---|---|---|---|---|
| **A** | Product plumbing & correctness | T1–T4 | ~3 days | Turns a demo into a tool. T3 fixes a live correctness defect. |
| **B** | DD 1416 execution ingest | T5–T6 | ~4 days | **Highest.** Enacted + reprogramming + net, per PE, official, machine-readable. |
| **C** | Trust layer | T7–T8 | ~3 days | What separates this from every unmaintained parser repo. |
| **D** | P-1 procurement & transition tracing | T9–T10 | ~5 days | Answers the most-asked question in defense budgeting. |
| **E** | PE lineage graph | T11 | ~5 days | The flagship differentiator. Nothing free does this. |
| **F** | Distribution | T12–T13 | ~3 days | Bulk data + change feed. Alerting is the #1 paid feature. |
| **G** | AI that earns its cost | T14–T15 | ~4 days | RAG with citations; one-time structured extraction. |

Phases A→B→C are sequential and should ship in that order. D, E, F, and G are independent
of each other and can be reordered by appetite; each depends only on A, plus C's test
harness if it exists yet.

---

## Phase A — Product plumbing & correctness

Three of these are small. They come first because everything downstream is more valuable
once views are addressable, and because T3 is a correctness bug shipped to users today.

**T1 — Permalinks.** There is not one use of `st.query_params` in the codebase. Nobody can
share, cite, bookmark, or bug-report a view. Encode tab, PE, and FY range in the URL.

**T2 — Export on every table, plus a provenance block.** There is not one
`st.download_button` in the codebase. Every table gets CSV/XLSX; every figure gets its
source document, URL, and retrieval date. This is the loudest complaint about
open-source budget parsers: nobody can tell where a number came from.

**T3 — Constant-dollar toggle.** No deflator logic exists anywhere in the repo. Every
trend chart on the Budget Trends tab currently overstates real growth by roughly 2–3%/yr
compounded — across FY1996–FY2027 that is a materially misleading chart. Fix it with
DoD RDT&E-specific deflators, not CPI and not the GDP deflator: defense technology and
defense labor escalation decouple from consumer prices. Caveat verified 2026-09-08: the
Green Book links on the live Budget-Materials page (`fy27_Green_Book.pdf`, `.zip`) **both
return 404** — the page label even reads "FY FY2027". Wayback has working FY2024 and
FY2025 snapshots; route it through the Wayback client already built for the Air Force
books.

**T4 — Vintage labeling.** The same fiscal year appears in multiple PB cycles with
different values, and `funding_lines` already carries three types (`PY Actual`,
`CY Request`, `BY Request`) without recording which submission produced them. The
confusion is real and present in the source data: the FY2027 PDI JSON's own metadata
reads `"BudgetYear": "2026"`. Label the vintage on every figure.

## Phase B — DD 1416 execution ingest

**T5 — Ingest the DD 1416 RDT&E quarterly reports.** The crown jewel described above.
It delivers, per PE, per fiscal year: request → **enacted** → statutory adjustments →
supplementals/rescissions/sequestration → **above-threshold reprogramming** →
**below-threshold reprogramming** → **net current program**.

What this changes for the product:

- The Rhetoric vs. Budget tab currently has to disclose "authorization is not
  appropriation." After T5 it can show the whole chain: requested → authorized (House and
  Senate, separately) → **appropriated** → **reprogrammed** → net.
- "What the money did" stops depending on USAspending keyword approximation for the
  *amount* question. USAspending remains the right source for *who got paid* and stays
  labeled "leads, not a ledger" — but the dollars now come from the official ledger.
- Reprogramming is where money actually moves mid-year, and no free tool surfaces it.

**T6 — Surface it.** A new execution section on the program profile and a
request→enacted→net waterfall. Above- and below-threshold reprogramming deserve separate
visual treatment: above-threshold required congressional prior approval, below-threshold
did not, and conflating them misrepresents the oversight story.

## Phase C — Trust layer

**T7 — A real test suite.** There is no `tests/` directory and no pytest — only two
ad-hoc eval scripts (`analysis/linker_eval.py`, `analysis/ai_budget_eval.py`). Every
phase after this one adds a parser, and parsers without regression tests rot silently.
That is precisely how the open-source competition became untrustworthy.

**T8 — Reconciliation panel.** Sum ingested R-1 lines per appropriation per fiscal year
and assert against the published topline; do the same for DD 1416 enacted against the
appropriations act. Surface the result in Data Coverage as a "does it tie?" table showing
the residual. One panel, and the tool's numbers become checkable by a stranger.

## Phase D — P-1 procurement & transition tracing

**T9 — Ingest P-1.** Verified 2026-09-08: `p1_display.xlsx`, `o1_display.xlsx`, and
`m1_display.xlsx` all return HTTP 200 at the exact URL pattern
`config.XLSX_EXHIBIT_STEMS` already maps, for both FY2026 and FY2027; `xlsx_ingest.py`
already has an `include_non_rdtee` flag and a generic header finder. Much of the plumbing
exists.

**T10 — Transition tracing.** The most-asked question in defense budgeting, and one this
tool cannot currently answer at all: *did this R&D line ever become a program of record?*

**Scope this honestly.** P-1's identifier is a Budget Line Item (e.g. `9670A00005`),
**not** a program element — verified by inspecting the file. There is no key join from
RDT&E to procurement. The link must be title/semantic matching plus narrative evidence,
and it must carry the same ambiguity flagging the program matcher already uses. Do not
ship it as an exact linkage.

## Phase E — PE lineage graph

**T11.** Every source consulted named the same hardest problem in longitudinal defense
analysis: program elements get renumbered, split, and merged. Moving from Budget Activity
2 to 3 changes the PE number itself. The result is a funding series that drops to zero —
a fake cancellation — while successor PEs appear as fake new starts.

This project is unusually well-positioned to solve it, holding both the FY1996–FY2027 R-1
series *and* narrative text that prints transfer language verbatim ("in FY2025, Project
123 was transferred from PE 0602115A"). Build a lineage table with predecessor/successor,
the evidence snippet, and a confidence score; thread the funding charts through it, always
showing the seam rather than silently splicing.

Nothing free does this, and even the paid tools do it inconsistently. If one thing on this
roadmap is worth writing a blog post about, it is this.

## Phase F — Distribution

**T12 — Bulk data and versioned releases.** Tag the parquet/SQLite as GitHub releases with
a data dictionary and a changelog. The legal position is already confirmed (17 U.S.C. 105;
GPO has stated no restrictions on derived datasets), which makes this a public good the
paywalled tools cannot match.

**T13 — Change feed.** Diff each PB cycle and each new committee report per PE; publish as
RSS/JSON, optionally email. Saved-search alerting is the top paid feature across GovWin,
HigherGov, and Bloomberg Government — and it is nearly free here, because the vintages are
already stored.

## Phase G — AI that earns its cost

**T14 — RAG over the narrative corpus with strictly extractive citations.** The embeddings
already exist. Natural-language search across justification text is Obviant's core pitch.
Every claim must carry a PE, a fiscal year, and a source document, and the answer must
refuse rather than paraphrase when it cannot cite.

**T15 — One-time structured extraction** from narratives into fields (contractors,
transition language, test events, locations), cached forever rather than re-queried per
user. A better cost profile than anything grounded, and it feeds T10 and T11.

---

## Deliberately not doing

- **Expanding the media-emphasis / rhetoric AI scoring.** It is the least defensible
  output the tool produces and it carries per-user grounded-search cost.
- **A chatbot without citations.** Every AI surface must cite or stay silent; that
  discipline is the product's main credibility asset.
- **Chasing service-level R-2 XML.** Verified: Army, Navy, Air Force, and Space Force
  publish RDT&E justification books as **PDF only**. The EAS/DTIC XML route — and the
  newer JSON — is Defense-Wide only. The PDF pipeline in this repo is not a workaround
  for something easier that exists; it *is* the road.
- **FYDP out-year projections.** DoD transmits the unclassified FYDP to Congress, not to
  the public. Do not build a feature that depends on obtaining it.

## Watch item

DoD has begun publishing select justification books as structured JSON generated from EAS
— `FY2027_Pacific_Deterrence_Initiative.json` and
`FY2027_Drug_Interdiction_and_Counter-Drug_Activities.json` are live now. If the RDT&E
books follow, the PDF parsers become legacy overnight. Nothing to do today except re-check
each budget cycle.
