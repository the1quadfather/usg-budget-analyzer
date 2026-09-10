"""
primer.py

Plain-language explanations of how the numbers in the app relate to each
other: what a program element is, why one fiscal year carries three
different figures, what happens between the President's request and the
money a program can actually spend, and why award records never tie to any
of it.

Markdown constants only -- no Streamlit here. app.py decides where each
block appears. Keep every claim here consistent with the UI strings and the
invariants in CODEX_HANDOFF.md section 2 (authorization is not
appropriation; House and Senate are never pooled; discretionary and
mandatory funds are separate streams).

Avoid literal dollar signs in these strings: markdown treats a pair of them
as LaTeX. Write "10 million dollars" or use the escape helper at render time.
"""

PROGRAM_STRUCTURE = """
**Program element (PE).** The unit Congress funds and this tool tracks. Each
PE has a number like `0602702E`:

| Digits | Meaning | Example |
|---|---|---|
| 1–2 | Major force program; `06` is RDT&E | `06` |
| 3–4 | Budget activity: 01 basic research, 02 applied research, 03 advanced technology development, 04 advanced component development and prototypes, 05 system development and demonstration, 06 management support, 07 operational systems development, 08 software and digital pilot programs | `02` |
| 5–7 | Serial number within that budget activity | `702` |
| suffix | Component: A Army, N Navy and Marine Corps, F Air Force, E DARPA, C Missile Defense Agency, and other Defense-Wide suffixes | `E` |

A PE that moves between budget activities gets a new number. Its funding
series appears to stop and a "new" PE appears to start; this is renumbering,
not cancellation, and it is the reason a long series can drop to zero.

**Projects.** Inside a PE, the R-2 justification book breaks the money into
projects (for example a DARPA PE may carry several projects with their own
titles). The Funding chart is the PE total from the R-1 exhibit. The
Plans & Work tab shows the projects and their planned work from the R-2, in
millions. Projects sum to the PE; the tool never adds them again.
"""

FUNDING_BASES = """
**Why one fiscal year has three figures.** Every President's Budget (PB)
prints three columns for the same program: the prior year as actually
executed, the current year as enacted (or as a continuing resolution left
it), and the budget year being requested. So FY2026 appears first as a
*request* in PB2026, then as *enacted* in PB2027, then as an *actual* in
PB2028. Each figure is legitimate; they are the same year seen at three
moments.

The chart shows one point per fiscal year using this precedence: a reported
**actual** beats an **enacted/current-year** figure, which beats a
**request**. Hover a point to see which PB submission supplied it, and
expand the table beneath to see every observation. Two vintages of the same
year can differ because Congress changed the request, because money moved
after enactment, or because the program under-executed.

Amounts in the R-1 and in this tool's tables are **thousands of dollars**
unless a column header says millions. Discretionary funds and the separate
mandatory/reconciliation stream are never combined.
"""

EXECUTION_STEPS = """
**From the request to the money a program can actually spend.** The
DD 1416 "Report of Programs" is the Comptroller's quarterly ledger of what
happened to each PE after the request left the building. Its columns, in
order:

| Step | What it is | Why it differs from the step before |
|---|---|---|
| **President's request** | The R-1 figure sent to Congress in February | The starting point |
| **Enacted** | What the appropriations act actually provided | Committees add ("program increase") or cut ("unjustified growth", "excess to need", "early to need", "under-execution"); a continuing resolution freezes the prior year's level |
| **Statutory adjustments** | Across-the-board reductions written into the act itself, applied pro rata to every line | Congress sets the total; the Comptroller distributes it |
| **Supplementals / rescissions / sequestration** | Money added by a later act, cancelled by a later act, or cut by a sequester | Separate legislation after the base act |
| **Other adjustments** | Transfers under the act's general provisions and similar accounting moves | Housekeeping the act allows |
| **Above-threshold reprogramming** | Money moved into or out of this PE with congressional prior approval, on a DD 1415 form | Needs sign-off from all four defense committees; the threshold is a dollar amount set in the act, currently on the order of 10 million dollars for an RDT&E line |
| **Below-threshold reprogramming** | Smaller moves the Department may make on its own and report afterward | Same mechanism, no prior approval required |
| **Net current program** | Enacted plus every adjustment above: what the PE really has to spend that year | The bottom line |

Reprogramming is where money moves mid-year, and it is the part of the story
no request or appropriation document shows. A large negative reprogramming
usually means the program under-executed and its money was used to cover a
shortfall elsewhere; a large positive one usually means a new need the
budget did not anticipate.

DD 1416 reports **budget authority** (permission to obligate), not
obligations or outlays. RDT&E money stays available for obligation for two
fiscal years, so contract awards for a given year's money keep appearing
well into the following year.
"""

AUTHORIZATION_VS_APPROPRIATION = """
**Authorization is not money.** Two separate bills act on the same request
every year:

- The **National Defense Authorization Act (NDAA)**, written by the House and
  Senate Armed Services Committees, sets policy and an authorized *ceiling*
  for each PE. This is what the "What Congress authorized" figures show,
  parsed from the funding tables printed in the committee reports.
- The **Defense Appropriations Act**, written by the two Appropriations
  Committees, provides the actual budget authority. That is the "Enacted"
  figure in the execution section, from the DD 1416.

A committee can authorize money that is never appropriated, and the two
acts often carry different numbers for the same PE. The House and Senate
committees each score the request independently before conference, so
this tool shows one chamber at a time and never adds them together.
"""

AWARDS_VS_BUDGET = """
**Why contract awards never tie to the budget.** USAspending.gov records
obligations (signed contracts and grants), while the R-1 and DD 1416 record
budget authority. Award records carry no program-element field, awards can
draw on money from more than one year, and a single umbrella contract can
serve many programs. Treat awards as evidence of who was paid, not as a
ledger of a PE's money.
"""

PROJECTS_NOTE = (
    "Projects are the R-2 breakdown of this program element. Their planned "
    "work and dollar figures (in millions) sum to the PE total shown on the "
    "Funding tab; they are not additional money."
)

GLOSSARY = (
    PROGRAM_STRUCTURE
    + "\n---\n"
    + FUNDING_BASES
    + "\n---\n"
    + AUTHORIZATION_VS_APPROPRIATION
    + "\n---\n"
    + EXECUTION_STEPS
    + "\n---\n"
    + AWARDS_VS_BUDGET
)

# Short help strings for st.metric(help=...). One sentence each.
HELP = {
    "latest": (
        "Most recent fiscal year on record, showing its most reliable figure: "
        "a reported actual, else the enacted/current-year figure, else the "
        "request. The label in parentheses says which."
    ),
    "peak": "Largest single-year figure in the series, same precedence rule.",
    "history": "Fiscal years with at least one figure; the range is shown beneath.",
    "cagr": (
        "Compound annual growth rate from the first year on record to the "
        "latest, in the selected dollar basis."
    ),
    "request": (
        "What the President's Budget asked Congress to provide this program "
        "element for this fiscal year (the R-1 figure)."
    ),
    "enacted": (
        "What the appropriations act actually provided. It differs from the "
        "request wherever Congress added or cut."
    ),
    "reprogramming": (
        "Money moved into (+) or out of (−) this program after enactment. "
        "Above-threshold moves needed congressional prior approval; "
        "below-threshold moves did not."
    ),
    "net": (
        "Enacted plus every statutory, supplemental, and reprogramming "
        "adjustment: what the program actually had available to spend."
    ),
}
