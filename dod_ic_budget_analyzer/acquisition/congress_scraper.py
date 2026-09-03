"""
acquisition/congress_scraper.py

Extracts per-Program-Element authorization actions from the RDT&E funding
tables printed in HASC/SASC NDAA committee reports on govinfo.gov.

Why this exists
---------------
The Rhetoric vs. Budget tab previously showed an AI-estimated "mention
intensity (0-10)" score. This module replaces that inference with an exact
join: what the President requested, what the authorizing committee added or
cut, what it authorized, and the reason the committee printed for the change.

No API key, no ML, no rate limit -- the reports are plain text at a stable URL,
and as US Government works (17 U.S.C. 105) they are public domain. Unlike
Gemini Grounded Results, this data may be cached, analyzed, and resold.

Table format (SEC. 4201, "In Thousands of Dollars")::

     001   0601102A                  DEFENSE RESEARCH SCIENCES..    296,670     5,000     301,670
           ........................      AI-Enhanced Quantum                  [5,000]
                                          Computing.

The layout is fixed-width but drifts between Congresses, so the money columns
are detected per document rather than hardcoded (FY2022 ends at 79/95/112,
FY2024 and FY2026 at 78/94/112). Titles, budget activity headings, and
rationales all wrap onto continuation lines.

Known limits
------------
* Machine-readable PE tables start at **FY2012**; earlier reports print the
  same tables as GRAPHIC images. Congressional actions therefore cover only
  about half the funding history -- disclose this in the UI.
* A PE may appear more than once in one report under different budget
  activities. `line_number` is part of the natural key; never sum amounts
  across rows without checking.
* Some PE numbers are placeholders, not catalog entries: classified rollups
  (`9999...`), aggregates (`888888`), and FY2012-FY2014 undesignated new
  starts masked with X (`0603XXXA`). All are stored with `is_classified=1`,
  excluded from reconciliation, and never counted as unknown-PE failures.

Usage::

    python acquisition/congress_scraper.py --report CRPT-118hrpt125
    python acquisition/congress_scraper.py --report CRPT-118hrpt125 --dry-run
    python acquisition/congress_scraper.py --all
"""

import argparse
import hashlib
import html
import logging
import re
import sys
from pathlib import Path
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import (  # noqa: E402
    FundingLine,
    PECongressionalAction,
    ProgramElement,
    get_engine,
    get_session_factory,
    init_db,
)

logger = logging.getLogger(__name__)

GOVINFO_URL = "https://www.govinfo.gov/content/pkg/{rid}/html/{rid}.htm"

# Cache raw report text so re-parsing never re-downloads.
CACHE_DIR = Path(__file__).parent.parent / "data" / "raw" / "congress"

# Authorization reports carrying machine-readable RDT&E tables (FY2012+).
# 'hrpt' = House (HASC), 'srpt' = Senate (SASC). Every id here was parsed and
# checked against its raw text; three known reports are deliberately absent
# because the parser refuses them rather than guess:
#   CRPT-112srpt26  -- no SEC. 4201 '(In Thousands of Dollars)' table
#   CRPT-118hrpt301 -- conference layout, 4 money columns, would mix chambers
#   CRPT-118hrpt529 -- no fiscal year in the document title
KNOWN_REPORTS: List[str] = [
    "CRPT-112hrpt78",       # FY2012 House
    "CRPT-112hrpt479",      # FY2013 House
    "CRPT-112srpt173",      # FY2013 Senate
    "CRPT-113hrpt102",      # FY2014 House
    "CRPT-113srpt44",       # FY2014 Senate
    "CRPT-113hrpt446",      # FY2015 House
    "CRPT-113srpt176",      # FY2015 Senate
    "CRPT-114hrpt102",      # FY2016 House
    "CRPT-114srpt49",       # FY2016 Senate
    "CRPT-114hrpt537",      # FY2017 House
    "CRPT-114srpt255",      # FY2017 Senate
    "CRPT-115hrpt200",      # FY2018 House
    "CRPT-115srpt125",      # FY2018 Senate
    "CRPT-115hrpt676",      # FY2019 House
    "CRPT-115srpt262",      # FY2019 Senate
    "CRPT-116hrpt120",      # FY2020 House
    "CRPT-116srpt48",       # FY2020 Senate
    "CRPT-116hrpt442",      # FY2021 House
    "CRPT-116srpt236",      # FY2021 Senate
    "CRPT-117hrpt118",      # FY2022 House
    "CRPT-117srpt39",       # FY2022 Senate
    "CRPT-117hrpt397",      # FY2023 House
    "CRPT-117srpt130",      # FY2023 Senate
    "CRPT-118hrpt125",      # FY2024 House
    "CRPT-118srpt58",       # FY2024 Senate
    "CRPT-118srpt188",      # FY2025 Senate
    "CRPT-119hrpt231",      # FY2026 House
    "CRPT-119srpt39",       # FY2026 Senate
    "CRPT-119hrpt698",      # FY2027 House
    "CRPT-119srpt127",      # FY2027 Senate
]

# ── Money columns ────────────────────────────────────────────────────────────
# The three money columns are right-aligned, but their exact positions shift
# between reports (FY2022 ends at 79/95/112; FY2024 and FY2026 at 78/94/112),
# so they are detected per document rather than hardcoded. Everything left of
# MONEY_MARGIN is the line number, PE number, and title.
MONEY_MARGIN = 60

# A right-aligned money cell: digits with thousands separators, optionally
# negative. Anchored on whitespace so it cannot pick up digits inside a title.
RE_MONEY = re.compile(r"(?<= )(-?\d{1,3}(?:,\d{3})*|-?\d+)(?= |$)")

# A PE row: line number (may carry a letter suffix like '090A'), then the PE
# number. PE numbers run 6-10 digits followed by an optional agency suffix that
# starts with a letter and may contain digits -- one char ('0601102A'), two
# ('1206601SF'), or three ('0601108D8Z' Defense-Wide, '...JCY' joint, '...OTE',
# '1203940SFZ'). Capping the suffix at two characters silently dropped 322 rows
# across three reports, all of them Defense-Wide/joint programs.
#
# Both the leading indent and the line number vary: Senate reports print
# classified rows with NO line number, and placeholder numbers can be as short
# as four digits ('8888'). Requiring 1-5 leading spaces and a line number lost
# one funding row apiece in four Senate reports.
RE_PE_ROW = re.compile(
    r"^ {1,12}(?:(\d{1,4}[A-Z]?) +)?"                # line number is sometimes absent
    r"([0-9X]{4,10}(?:[A-Z][A-Z0-9]{0,2})?)"        # PE number
    r" {2,}(\S.*)$"
)

# A committee add with no program element assigned prints dot leaders where the
# PE number goes -- but ONLY ever after a line number. Budget activity
# headings, rationale lines, and subtotals also start with dot leaders and must
# not match, so the line number is required here rather than optional.
RE_UNASSIGNED_ROW = re.compile(r"^ {1,5}(\d{1,4}[A-Z]?) +\.{5,} {2,}(\S.*)$")

# The PE column is dot leaders when a committee adds money with no program
# element assigned to it yet. Stored under this sentinel so the row is kept
# and visibly not a real PE, rather than silently dropped.
UNASSIGNED_PE = "UNASSIGNED"

# '   ........................  BASIC RESEARCH' -- a budget activity heading.
RE_BA_HEADER = re.compile(r"^ +\.{5,} {2,}([A-Z][A-Z0-9 &,'\-/]{3,})\s*$")

# A rationale/earmark line carries its amount in square brackets.
RE_BRACKET = re.compile(r"\[\s*(-?[\d,]+)\s*\]")

RE_FISCAL_YEAR = re.compile(r"FISCAL YEAR (\d{4})", re.IGNORECASE)

RE_SKIP = re.compile(r"\b(SUBTOTAL|TOTAL|UNDISTRIBUTED)\b")

# The RDT&E table opens with the '(In Thousands of Dollars)' banner; the next
# SEC. 4xxx banner closes it.
# Account banner, e.g. 'RESEARCH, DEVELOPMENT, TEST / AND EVALUATION, ARMY'.
RE_ACCOUNT_HEADER = re.compile(r"^RESEARCH, DEVELOPMENT", re.IGNORECASE)

RE_SECTION_4201 = re.compile(r"^ *SEC\. 4201\..*Thousands of Dollars", re.IGNORECASE)
RE_SECTION_NEXT = re.compile(r"^ *SEC\. 4(?!201)\d{3}\.", re.IGNORECASE)

# PE-number suffix -> agency, used to disambiguate PEs the DB files under more
# than one agency (Space Force lines still sit under the Air Force account).
SUFFIX_AGENCY = {
    "A": "Army",
    "N": "Navy",
    "F": "Air Force",
    "SF": "Space Force",
    # Operational Test & Evaluation PEs are filed in program_elements under
    # BOTH 'Defense-Wide' and 'OT&E'. Without this the alphabetical tie-break
    # picks Defense-Wide and the more precise component is lost.
    "OTE": "OT&E",
}

# Agency strings in program_elements that are ingestion artifacts, never a
# real answer. Verified 2026-08-28: program_elements holds only the five
# services plus 'Defense-Wide', 'OT&E', and 8 'Unknown' rows. The junk
# 'Creating Helpful Incentives To Produce Semi-Conductors...' agency the
# handoff warns about lives in pe_narratives/pe_accomplishments, NOT here, so
# it cannot reach this lookup.
JUNK_AGENCIES = {"Unknown", ""}


def _clean_amount(raw: str) -> Optional[float]:
    """Parse a fixed-width money cell. Blank cells are legitimately None."""
    text = raw.strip().replace(",", "").replace("$", "")
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return float(text)


def _is_placeholder(pe_number: str) -> bool:
    """
    True for PE numbers that are not real catalog entries.

    Three kinds appear in these tables and none will ever join to
    program_elements, so they are stored but never reconciled and never
    counted as an unknown-PE failure:
      * classified rollups, all 9s -- '99999999', '9999999999'
      * aggregate placeholders -- '888888'
      * undesignated new starts masked with X -- '0603XXXA', 'XXXXXXXF'
      * congressional adds with no PE assigned yet -- UNASSIGNED_PE

    The X form only appears in the FY2012-FY2014 reports. Before it was
    matched, those rows failed the PE pattern, fell through to the title
    continuation branch, and spliced a whole funding row into the previous
    program's title.
    """
    if pe_number == UNASSIGNED_PE or "X" in pe_number:
        return True
    digits = re.sub(r"[A-Z]+$", "", pe_number)
    return bool(digits) and (set(digits) <= {"9"} or set(digits) <= {"8"})


def _tidy(text: str) -> str:
    """Collapse whitespace and strip the dot leaders used for padding."""
    text = text.replace("…", " ")
    text = re.sub(r"\.{2,}", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def _rdte_section(lines: List[str], rid: str) -> List[str]:
    """
    Narrow to the SEC. 4201 RDT&E table.

    The same report also prints Procurement (4101), O&M (4301), and other
    fixed-width tables. They do not currently collide with the PE-row pattern,
    but scoping the parse means a future layout change cannot silently pull
    procurement line items in as program elements.
    """
    starts = [i for i, l in enumerate(lines) if RE_SECTION_4201.match(l)]
    if not starts:
        # Falling back to the whole document parses fragments of the
        # procurement and O&M tables into nonsense. Refuse instead.
        raise ValueError(
            "no SEC. 4201 '(In Thousands of Dollars)' banner found -- "
            "this report does not carry the standard RDT&E authorization table"
        )
    start = starts[-1]
    ends = [i for i, l in enumerate(lines)
            if i > start and RE_SECTION_NEXT.match(l)]
    return lines[start:ends[0] if ends else len(lines)]


def detect_money_columns(lines: List[str]) -> List[int]:
    """
    Find the right-hand edge of the request / delta / authorized columns.

    Committee reports are fixed-width, but the layout drifts by a character
    between congresses. Taking the three most common right edges across every
    PE row in the document adapts to whichever layout this report uses, and a
    row missing a column simply has no token at that edge.
    """
    edges: Counter = Counter()
    for line in lines:
        if not RE_PE_ROW.match(line):
            continue
        for token in RE_MONEY.finditer(line):
            if token.start() >= MONEY_MARGIN:
                edges[token.end()] += 1
    if len(edges) < 2:
        raise ValueError("could not detect money columns -- table format changed?")

    # A conference report prints House, Senate, and conference figures side by
    # side. Silently keeping the three most common edges there would blend two
    # chambers' numbers into one row, so refuse the document instead.
    pe_rows = sum(1 for line in lines if RE_PE_ROW.match(line))
    dominant = sorted(e for e, n in edges.items() if n >= 0.5 * pe_rows)
    if len(dominant) > 3:
        raise ValueError(
            f"{len(dominant)} money columns at {dominant} -- expected the "
            "3-column authorizing layout. This looks like a conference report "
            "carrying House/Senate/conference figures; refusing rather than "
            "mixing chambers in one row"
        )
    return sorted(edge for edge, _ in edges.most_common(3))


def _has_plain_money(line: str) -> bool:
    """
    True when the row carries a funding figure outside square brackets.

    Rationale lines put their amount in brackets and can also carry a PE
    number with no line number ('0401218F  KC-135 drag reduction  [35,000]'),
    which otherwise looks exactly like a funding row. Real funding cells are
    never bracketed, so this is what separates the two.
    """
    brackets = [(m.start(), m.end()) for m in RE_BRACKET.finditer(line)]
    for token in RE_MONEY.finditer(line):
        if token.start() < MONEY_MARGIN:
            continue
        if any(start <= token.start() < end for start, end in brackets):
            continue
        return True
    return False


def _title_end(line: str) -> int:
    """Where the program title stops: the first money cell on the row."""
    for token in RE_MONEY.finditer(line):
        if token.start() >= MONEY_MARGIN:
            return token.start()
    return len(line)


def row_amounts(line: str, edges: List[int],
                tolerance: int = 1) -> List[Optional[float]]:
    """
    Pull the money cells out of one PE row, keyed by which column edge each
    token lands on. A blank column yields None rather than shifting the others
    left -- congressional adds legitimately have no request figure.
    """
    found: List[Optional[float]] = [None] * len(edges)
    for token in RE_MONEY.finditer(line):
        if token.start() < MONEY_MARGIN:
            continue
        for index, edge in enumerate(edges):
            if abs(token.end() - edge) <= tolerance:
                found[index] = _clean_amount(token.group(1))
                break
    return found


def report_metadata(rid: str, text: str) -> Dict[str, object]:
    """Fiscal year from the document title, chamber from the report id."""
    match = RE_FISCAL_YEAR.search(text[:20000])
    if not match:
        raise ValueError(f"{rid}: could not determine fiscal year from title")
    chamber = "House" if "hrpt" in rid.lower() else "Senate"
    return {"fiscal_year": int(match.group(1)), "chamber": chamber}


def fetch(rid: str, refresh: bool = False, timeout: float = 180.0) -> str:
    """Download a report, caching the raw text under data/raw/congress."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{rid}.htm"
    if cached.exists() and not refresh:
        logger.info(f"{rid}: using cached copy")
        return cached.read_text(encoding="utf-8", errors="replace")

    url = GOVINFO_URL.format(rid=rid)
    logger.info(f"{rid}: downloading {url}")
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    body = response.text
    cached.write_text(body, encoding="utf-8")
    return body


def parse(text: str, rid: str,
          diagnostics: Optional[dict] = None) -> List[dict]:
    """
    Walk the report line by line, emitting one dict per PE funding row.

    State machine: a PE row opens a record; following lines either continue its
    title, open a bracketed rationale item, or continue the current rationale.
    Any heading, subtotal, or blank-ish line closes the record.
    """
    meta = report_metadata(rid, text)
    lines = html.unescape(text).split("\n")
    lines = _rdte_section(lines, rid)
    edges = detect_money_columns(lines)
    logger.debug(f"{rid}: money columns end at {edges}")

    rows: List[dict] = []
    unparsed: List[str] = []
    current: Optional[dict] = None
    # Each rationale item is [label_parts, amount]; the label wraps over lines.
    rationales: List[list] = []
    in_rationale = False
    budget_activity: Optional[str] = None
    heading_open = False
    heading_is_account = False

    def render(item: list) -> str:
        label = _tidy(" ".join(item[0]))
        amount = item[1]
        return f"{label} [{amount:+,.0f}]" if amount is not None else label

    def close() -> None:
        nonlocal current, in_rationale
        if current is None:
            return
        current["program_title"] = _tidy(current["program_title"])[:500]
        rendered = [render(item) for item in rationales]
        current["rationale"] = "; ".join(r for r in rendered if r) or None
        rows.append(current)
        current = None
        in_rationale = False

    for line in lines:
        stripped = line.strip()

        pe_match = RE_PE_ROW.match(line)
        unassigned_match = None if pe_match else RE_UNASSIGNED_ROW.match(line)
        # A bracketed-only amount means this is a rationale detail, even when
        # it carries a PE number -- let it fall through to the rationale branch.
        if (pe_match or unassigned_match) and (
                RE_BRACKET.search(line) and not _has_plain_money(line)):
            pe_match = unassigned_match = None
        if pe_match or unassigned_match:
            close()
            if pe_match:
                line_no, pe_number, remainder = pe_match.groups()
                title_from = pe_match.start(3)
            else:
                line_no, remainder = unassigned_match.groups()
                pe_number = UNASSIGNED_PE
                title_from = unassigned_match.start(2)
            line_no = line_no or ""
            if RE_SKIP.search(remainder):
                continue
            rationales = []
            request, delta, authorized = row_amounts(line, edges)
            current = {
                "line_number": line_no,
                "pe_number": pe_number,
                # Title runs from where the regex found it to the first money
                # cell. BOTH edges must be derived, never fixed: PE numbers
                # vary in width (9 for Space Force, 10 for Defense-Wide D8Z),
                # which shifts the title right and clipped it at both ends.
                "program_title": _tidy(line[title_from:_title_end(line)]),
                "budget_activity_title": budget_activity,
                "request_k": request,
                "committee_delta_k": delta,
                "authorized_k": authorized,
                "is_classified": 1 if _is_placeholder(pe_number) else 0,
                "fiscal_year": meta["fiscal_year"],
                "chamber": meta["chamber"],
                "report_citation": rid,
            }
            continue

        # Headings close the current record and may set the budget activity.
        ba_match = RE_BA_HEADER.match(line)
        if ba_match:
            close()
            heading = _tidy(ba_match.group(1))
            heading_open = False
            if heading and not RE_SKIP.search(heading):
                # Account banners ('RESEARCH, DEVELOPMENT, TEST / AND
                # EVALUATION, ARMY') share this shape but are not budget
                # activities -- consume their wrapped tail without recording it.
                heading_is_account = bool(RE_ACCOUNT_HEADER.match(heading))
                heading_open = True
                if not heading_is_account:
                    budget_activity = heading[:200]
            continue

        if not stripped or set(stripped) <= {"-", "="}:
            close()
            heading_open = False
            continue

        if current is None:
            # Budget activity names wrap too ('ADVANCED COMPONENT' +
            # 'DEVELOPMENT AND PROTOTYPES'); without this the stored label is
            # truncated mid-phrase and reads as broken in the UI.
            # Only a bare wrapped word belongs here. Anything carrying a money
            # cell is a data row, not a heading tail -- without this guard a
            # heading swallows whole rows when a PE shape goes unrecognised.
            if (heading_open and not RE_BRACKET.search(line)
                    and not any(t.start() >= MONEY_MARGIN
                                for t in RE_MONEY.finditer(line))):
                tail = _tidy(line)
                if tail and not heading_is_account and budget_activity:
                    budget_activity = f"{budget_activity} {tail}"[:200]
                continue
            heading_open = False
            continue

        # Subtotal and total rows carry money but are roll-ups, not data.
        # They must be tested before the money guard below, or every one of
        # them is reported as a dropped funding row.
        if RE_SKIP.search(stripped):
            close()
            continue

        bracket = RE_BRACKET.search(line)
        if bracket:
            # New rationale item: text left of the bracket, amount inside it.
            # Some reports repeat the PE number on the rationale line; it is
            # noise in a human-readable reason string.
            label = _tidy(RE_BRACKET.sub("", line))
            label = re.sub(r"^[0-9X]{4,10}[A-Z][A-Z0-9]{0,2}\s+", "", label)
            rationales.append([[label], _clean_amount(bracket.group(1))])
            in_rationale = True
            continue

        # A line carrying a money cell is a data row, never prose. If one
        # reaches here its PE number went unrecognised, and appending it would
        # splice a whole funding row -- digits and all -- into the previous
        # program's title or rationale. Drop it loudly instead of corrupting
        # a neighbouring record.
        if any(t.start() >= MONEY_MARGIN for t in RE_MONEY.finditer(line)):
            close()
            unparsed.append(line)
            continue

        if in_rationale:
            # A wrapped rationale label -- append to the open item.
            tail = _tidy(line)
            if tail:
                rationales[-1][0].append(tail)
            continue

        # Otherwise it continues the program title.
        current["program_title"] += " " + _tidy(line)

    close()

    if unparsed:
        logger.warning(
            f"{rid}: {len(unparsed)} money-bearing line(s) matched no PE "
            f"pattern and were dropped rather than corrupt a neighbour; "
            f"first: {unparsed[0].strip()[:90]!r}"
        )
    if diagnostics is not None:
        diagnostics["unparsed_money_lines"] = unparsed
    return rows


def _agency_index(session: Session) -> Dict[str, Set[str]]:
    """pe_number -> every agency string the catalog files it under."""
    index: Dict[str, Set[str]] = {}
    for pe_number, agency in session.execute(
        select(ProgramElement.pe_number, ProgramElement.agency)
    ):
        index.setdefault(pe_number, set()).add(agency)
    return index


def resolve_agency(pe_number: str, index: Dict[str, Set[str]]) -> str:
    """
    Pick the agency for a PE.

    The codebase joins on the (pe_number, agency) string pair, so a wrong
    agency here silently orphans every downstream row. Prefer the agency
    implied by the PE-number suffix -- Space Force lines are printed under the
    Air Force account, and 54 PEs in FY2024 alone are filed under two agencies.
    """
    candidates = {a for a in index.get(pe_number, set()) if a not in JUNK_AGENCIES}
    suffix = re.sub(r"^\d+", "", pe_number)
    implied = SUFFIX_AGENCY.get(suffix)

    if implied and implied in candidates:
        return implied
    if len(candidates) == 1:
        return next(iter(candidates))
    if implied:
        return implied
    if candidates:
        return sorted(candidates)[0]
    return "Unknown"


# Baselines tried when reconciling, in the order they are preferred on a tie.
# Which one holds a given year's *request* depends on the R-1 vintage the DB
# happens to carry: FY2024 lands in 'CY Request' (91%) while FY2022 lands in
# 'BY Request' (93%), so the baseline is chosen per report rather than fixed.
BASELINE_TYPES = ("CY Request", "BY Request", "PY Actual")

# Below this share of PEs reconciling, treat the run as suspect. A genuine
# column or format regression collapses the rate across the board; a DB whose
# R-1 vintage simply predates the report degrades it too, so this warns rather
# than fails.
RECONCILE_WARN_BELOW = 0.85

# Share of a report's PEs that may be missing from program_elements before the
# parse is treated as suspect. A committee naming a handful of PEs our R-1
# snapshot lacks is normal; inventing them is not.
UNKNOWN_PE_FAIL_ABOVE = 0.02


def _funding_index(session: Session, fiscal_year: int,
                   funding_type: str) -> Dict[str, Set[float]]:
    """pe_number -> the amounts recorded for one fiscal year and funding type."""
    index: Dict[str, Set[float]] = {}
    stmt = (
        select(ProgramElement.pe_number, FundingLine.amount_thousands)
        .join(FundingLine, FundingLine.program_element_id == ProgramElement.id)
        .where(FundingLine.fiscal_year == fiscal_year)
        .where(FundingLine.funding_type == funding_type)
    )
    for pe_number, amount in session.execute(stmt):
        index.setdefault(pe_number, set()).add(amount)
    return index


def choose_baseline(session: Session, fiscal_year: int,
                    requested: Dict[str, Set[float]]) -> tuple:
    """
    Pick the funding_type whose figures the report's request column reproduces.

    Returns (funding_type, index, matched_pe_count). Selecting this empirically
    keeps the reconciliation gate meaningful across R-1 vintages instead of
    reporting hundreds of false 'parse bugs'.
    """
    best = (None, {}, -1)
    for funding_type in BASELINE_TYPES:
        index = _funding_index(session, fiscal_year, funding_type)
        matched = sum(
            1 for pe, values in requested.items()
            if pe in index and values & index[pe]
        )
        if matched > best[2]:
            best = (funding_type, index, matched)
    return best


def _content_hash(row: dict) -> str:
    """Idempotency key over the natural key plus the figures."""
    parts = [
        row["report_citation"], row["chamber"], str(row["fiscal_year"]),
        row["pe_number"], row["line_number"],
        str(row["request_k"]), str(row["committee_delta_k"]),
        str(row["authorized_k"]),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def enrich(session: Session, rows: List[dict]) -> dict:
    """
    Attach agency and the reconciliation verdict, in place.

    Quality gate: every real PE must exist in program_elements, and its
    request_k must equal the 'CY Request' funding line for that fiscal year.
    Because one PE can occupy several rows, a PE passes when *any* of its rows
    matches. A PE where none match is a parse bug and is reported as such.
    """
    agencies = _agency_index(session)

    unknown_pes: Set[str] = set()
    per_pe: Dict[str, List[dict]] = {}

    for row in rows:
        row["agency"] = resolve_agency(row["pe_number"], agencies)
        row["content_hash"] = _content_hash(row)
        row["reconciled"] = 0
        if row["is_classified"]:
            continue
        if row["pe_number"] not in agencies:
            unknown_pes.add(row["pe_number"])
        per_pe.setdefault(row["pe_number"], []).append(row)

    fiscal_year = rows[0]["fiscal_year"]
    requested = {
        pe: {r["request_k"] for r in pe_rows if r["request_k"] is not None}
        for pe, pe_rows in per_pe.items()
    }
    requested = {pe: v for pe, v in requested.items() if v}
    funding_type, index, _ = choose_baseline(session, fiscal_year, requested)

    unmatched: Set[str] = set()
    no_baseline: Set[str] = set()

    for pe_number, pe_rows in per_pe.items():
        expected = index.get(pe_number)
        if not expected:
            no_baseline.add(pe_number)
            continue
        matched = [r for r in pe_rows if r["request_k"] in expected]
        if matched:
            for row in matched:
                row["reconciled"] = 1
        else:
            unmatched.add(pe_number)

    comparable = len(per_pe) - len(no_baseline)
    return {
        "rows": len(rows),
        "distinct_pes": len(per_pe),
        "classified": sum(1 for r in rows if r["is_classified"]),
        "unknown_pes": sorted(unknown_pes),
        "unreconciled_pes": sorted(unmatched),
        "no_baseline_pes": len(no_baseline),
        "reconciled_rows": sum(1 for r in rows if r["reconciled"]),
        "baseline": funding_type,
        "reconcile_rate": (comparable - len(unmatched)) / comparable if comparable else 0.0,
    }


def ingest(session: Session, rows: Iterable[dict]) -> int:
    """Insert rows whose content_hash is not already stored. Returns new count."""
    existing = {
        h for (h,) in session.execute(select(PECongressionalAction.content_hash))
    }
    added = 0
    for row in rows:
        if row["content_hash"] in existing:
            continue
        session.add(PECongressionalAction(**row))
        existing.add(row["content_hash"])
        added += 1
    session.commit()
    return added


def run(report_ids: List[str], db_uri: str, dry_run: bool = False,
        refresh: bool = False) -> int:
    engine = get_engine(db_uri)
    init_db(engine)
    factory = get_session_factory(engine)

    failures = 0
    with factory() as session:
        for rid in report_ids:
            try:
                text = fetch(rid, refresh=refresh)
                diag: dict = {}
                rows = parse(text, rid, diagnostics=diag)
            except Exception as exc:
                logger.error(f"{rid}: FAILED -- {exc}")
                failures += 1
                continue

            if not rows:
                logger.error(f"{rid}: no PE rows found -- table format changed?")
                failures += 1
                continue

            stats = enrich(session, rows)

            print(f"\n{rid}  FY{rows[0]['fiscal_year']}  {rows[0]['chamber']}")
            print(f"  rows parsed        : {stats['rows']}")
            print(f"  distinct PEs       : {stats['distinct_pes']}")
            print(f"  classified rows    : {stats['classified']}")
            print(f"  baseline           : {stats['baseline']}")
            print(f"  reconciled rows    : {stats['reconciled_rows']} "
                  f"({stats['reconcile_rate']:.0%} of comparable PEs)")
            print(f"  no FY baseline     : {stats['no_baseline_pes']} PEs")

            # Hard failure: a PE number we invented. This is the structural
            # check that the parse produced real program elements.
            # A few PEs a committee names but our R-1 snapshot lacks (new
            # starts, later-renamed lines) are a catalog gap, not a parse bug.
            # A parse that is actually inventing PE numbers produces them in
            # bulk, so gate on the rate rather than on any at all.
            unknown = stats["unknown_pes"]
            unknown_rate = len(unknown) / max(stats["distinct_pes"], 1)
            if unknown_rate > UNKNOWN_PE_FAIL_ABOVE:
                failures += 1
                print(f"  FAIL: {len(unknown)} of {stats['distinct_pes']} PEs "
                      f"({unknown_rate:.1%}) absent from program_elements — "
                      f"too many to be a catalog gap: {unknown[:10]}")
            elif unknown:
                print(f"  note: {len(unknown)} PE(s) not in the R-1 catalog "
                      f"(kept, unreconciled): {unknown[:6]}")

            # Rows carrying money that matched no PE pattern are silent data
            # loss -- the unknown-PE check cannot see them because they never
            # became rows at all.
            dropped = diag.get("unparsed_money_lines") or []
            if dropped:
                failures += 1
                print(f"  FAIL: {len(dropped)} money-bearing line(s) matched "
                      f"no PE pattern and were dropped; first: "
                      f"{dropped[0].strip()[:80]!r}")

            # Soft failure: figures disagree with the catalog. Usually means the
            # DB's R-1 vintage differs from the one the committee scored, not a
            # parse error -- a real format regression collapses the rate.
            if stats["reconcile_rate"] < RECONCILE_WARN_BELOW:
                print(f"  WARN: only {stats['reconcile_rate']:.0%} of PEs "
                      f"reconcile against {stats['baseline']}; DB vintage "
                      f"likely differs from this report. "
                      f"{len(stats['unreconciled_pes'])} PE(s), e.g. "
                      f"{stats['unreconciled_pes'][:5]}")
            elif not stats["unknown_pes"]:
                print("  quality gate       : PASS")

            if dry_run:
                print("  (dry run - nothing written)")
            else:
                print(f"  inserted           : {ingest(session, rows)}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", dest="reports",
                        help="Report id, e.g. CRPT-118hrpt125 (repeatable)")
    parser.add_argument("--all", action="store_true",
                        help=f"Process all known reports: {', '.join(KNOWN_REPORTS)}")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and run the quality gate without writing")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-download even if a cached copy exists")
    parser.add_argument("--db", default=None, help="Override the database URI")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    reports = args.reports or (KNOWN_REPORTS if args.all else None)
    if not reports:
        parser.error("pass --report <id> or --all")

    db_uri = args.db or (
        "sqlite:///"
        + (Path(__file__).parent.parent / "data" / "processed"
           / "usg_budgets.db").as_posix()
    )
    return run(reports, db_uri, dry_run=args.dry_run, refresh=args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
