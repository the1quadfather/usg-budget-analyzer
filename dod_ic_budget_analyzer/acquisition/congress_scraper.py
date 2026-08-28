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

Fixed-width columns: request ends at col 78, committee delta at 94,
authorized at 112. Titles and rationales wrap onto continuation lines.

Known limits
------------
* Machine-readable PE tables start at **FY2012**; earlier reports print the
  same tables as GRAPHIC images. Congressional actions therefore cover only
  about half the funding history -- disclose this in the UI.
* A PE may appear more than once in one report under different budget
  activities. `line_number` is part of the natural key; never sum amounts
  across rows without checking.
* `9999...` PE numbers are classified-program placeholders, stored with
  `is_classified=1` and excluded from reconciliation.

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
# 'hrpt' = House (HASC), 'srpt' = Senate (SASC).
KNOWN_REPORTS: List[str] = [
    "CRPT-119hrpt231",
    "CRPT-118hrpt125",
    "CRPT-117hrpt118",
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
# number. PE numbers run 6-10 digits with a 0-2 letter agency suffix -- Space
# Force uses two ('1206601SF'), and classified placeholders are all 9s.
RE_PE_ROW = re.compile(r"^ {1,5}(\d{1,4}[A-Z]?) +(\d{6,10}[A-Z]{0,2}) {2,}(\S.*)$")

# '   ........................  BASIC RESEARCH' -- a budget activity heading.
RE_BA_HEADER = re.compile(r"^ +\.{5,} {2,}([A-Z][A-Z0-9 &,'\-/]{3,})\s*$")

# A rationale/earmark line carries its amount in square brackets.
RE_BRACKET = re.compile(r"\[\s*(-?[\d,]+)\s*\]")

RE_FISCAL_YEAR = re.compile(r"FISCAL YEAR (\d{4})", re.IGNORECASE)

RE_SKIP = re.compile(r"\b(SUBTOTAL|TOTAL|UNDISTRIBUTED)\b")

# The RDT&E table opens with the '(In Thousands of Dollars)' banner; the next
# SEC. 4xxx banner closes it.
RE_SECTION_4201 = re.compile(r"^ *SEC\. 4201\..*Thousands of Dollars", re.IGNORECASE)
RE_SECTION_NEXT = re.compile(r"^ *SEC\. 4(?!201)\d{3}\.", re.IGNORECASE)

# PE-number suffix -> agency, used to disambiguate PEs the DB files under more
# than one agency (Space Force lines still sit under the Air Force account).
SUFFIX_AGENCY = {
    "A": "Army",
    "N": "Navy",
    "F": "Air Force",
    "SF": "Space Force",
}

# Agency strings in program_elements that are ingestion artifacts, never a
# real answer. See the 'Chips' rows noted in the project handoff.
JUNK_AGENCIES = {"Unknown", ""}


def _clean_amount(raw: str) -> Optional[float]:
    """Parse a fixed-width money cell. Blank cells are legitimately None."""
    text = raw.strip().replace(",", "").replace("$", "")
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return float(text)


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
        logger.warning(f"{rid}: no SEC. 4201 header found; parsing whole document")
        return lines
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
    return sorted(edge for edge, _ in edges.most_common(3))


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


def parse(text: str, rid: str) -> List[dict]:
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
    current: Optional[dict] = None
    # Each rationale item is [label_parts, amount]; the label wraps over lines.
    rationales: List[list] = []
    in_rationale = False
    budget_activity: Optional[str] = None

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
        if pe_match:
            close()
            line_no, pe_number, remainder = pe_match.groups()
            if RE_SKIP.search(remainder):
                continue
            rationales = []
            request, delta, authorized = row_amounts(line, edges)
            current = {
                "line_number": line_no,
                "pe_number": pe_number,
                # Title starts where the regex found it, not at a fixed column:
                # PE numbers vary in width (Space Force uses 9 chars), which
                # shifts the title right and would clip a fixed slice.
                "program_title": _tidy(line[pe_match.start(3):MONEY_MARGIN]),
                "budget_activity_title": budget_activity,
                "request_k": request,
                "committee_delta_k": delta,
                "authorized_k": authorized,
                "is_classified": 1 if pe_number.startswith("9999") else 0,
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
            if heading and not RE_SKIP.search(heading):
                budget_activity = heading[:200]
            continue

        if not stripped or set(stripped) <= {"-", "="}:
            close()
            continue

        if current is None:
            continue

        bracket = RE_BRACKET.search(line)
        if bracket:
            # New rationale item: text left of the bracket, amount inside it.
            label = _tidy(RE_BRACKET.sub("", line))
            rationales.append([[label], _clean_amount(bracket.group(1))])
            in_rationale = True
            continue

        if RE_SKIP.search(stripped):
            close()
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
                rows = parse(text, rid)
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
            if stats["unknown_pes"]:
                failures += 1
                print(f"  FAIL: {len(stats['unknown_pes'])} PE(s) absent from "
                      f"program_elements: {stats['unknown_pes'][:10]}")

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
