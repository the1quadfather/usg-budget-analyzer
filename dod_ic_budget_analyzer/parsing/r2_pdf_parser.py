"""
parsing/r2_pdf_parser.py

Parses RDT&E R-2 justification books published as PDF by the military
departments, so the service branches get the narrative coverage that until now
only Defense-Wide had.

Why this exists
---------------
`parsing/r2_parser.py` reads the DTIC-schema XML that Defense-Wide publishes.
The services (Army, Navy, Air Force, Space Force) publish PDF only, which left
`pe_narratives` covering 285 of 2,055 PEs -- 282 of them Defense-Wide, with
ZERO narrative text for Air Force (640 PEs), Army (435), Navy (396) or Space
Force (84).

Those PDFs turn out to be the best-linking source available: unlike GAO, CRS,
hearings, or appropriations reports -- all of which print program names and
must be fuzzy-matched -- an R-2 book prints the **PE number verbatim** in every
exhibit header and repeats it in every page footer. The join is exact.

Document structure
------------------
Two exhibit types, both parsed here::

    Exhibit R-2, RDT&E Budget Item Justification: PB 2027 Army
    Appropriation/Budget Activity          R-1 Program Element (Number/Name)
    2040: ... / BA 1: Basic Research       PE 0601102A / Defense Research Sciences
    A. Mission Description and Budget Item Justification    <- narrative

    Exhibit R-2A, RDT&E Project Justification: PB 2027 Army
    Appropriation/Budget Activity   R-1 Program Element (...)  Project (Number/Name)
    2040 / 1                        PE 0601102A / Defense ...  AA1 / ILIR - AMC
    B. Accomplishments/Planned Programs ($ in Millions)      <- accomplishments
    Title: ...
    Description: ...
    FY 2026 Plans: ...

The header is fixed-width with the column labels one line above the values, so
column offsets are read off the label row rather than guessed -- the PE and
project cells otherwise run together in `pdftotext -layout` output.

Input is the text from ``pdftotext -layout`` (poppler), which is already on the
system; pdfplumber is in requirements.txt but is frequently not installed.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Page header opening either exhibit type, e.g.
# 'Exhibit R-2A, RDT&E Project Justification: PB 2027 Army'
RE_EXHIBIT = re.compile(
    r"^Exhibit (R-2A?)\s*,\s*RDT&E [^:]*:\s*PB (\d{4})\s+(.+?)\s*$"
)

# Column label row of the header block.
RE_PE_LABEL = re.compile(r"R-1 Program Element \(Number/Name\)")
RE_PROJECT_LABEL = re.compile(r"Project \(Number/Name\)")

# 'PE 0601102A / Defense Research Sciences'
RE_PE_CELL = re.compile(r"PE\s+([0-9][0-9A-Z]{5,11})\s*/\s*(.*)")
# 'AA1 / ILIR - AMC'
RE_PROJECT_CELL = re.compile(r"([A-Z0-9]{2,6})\s*/\s*(.*)")

RE_SECTION_A = re.compile(r"^A\.\s+Mission Description and Budget Item Justification")
RE_SECTION_ACCOMP = re.compile(r"^B\.\s+Accomplishments/Planned Programs")
# Any other lettered section closes the one we are reading.
RE_SECTION_ANY = re.compile(r"^[A-Z]\.\s+[A-Z]")

RE_ACCOMP_TITLE = re.compile(r"^Title:\s*(.*)")
RE_ACCOMP_DESC = re.compile(r"^Description:\s*(.*)")
# 'FY 2026 Plans:', 'FY 2025 Accomplishments:', 'FY 2026 to FY 2027 Increase/Decrease Statement:'
RE_ACCOMP_YEAR = re.compile(
    r"^FY (\d{4})(?: to FY \d{4})? ([A-Za-z/ ]+?):\s*(.*)$"
)

# Page furniture that must never land in extracted prose.
RE_FURNITURE = re.compile(
    r"^\s*(UNCLASSIFIED\s*$"
    r"|PE [0-9][0-9A-Z]{5,11}:\s"
    r"|Page \d+ of \d+"
    r"|.*\bR-1 Line #\d+"
    r"|Volume \S+ - \S+\s*$"
    r"|Exhibit R-2)"
)

# Service name as printed in the exhibit header -> the agency string used
# throughout this codebase (program_elements.agency).
AGENCY_ALIASES = {
    "army": "Army",
    "navy": "Navy",
    "air force": "Air Force",
    "space force": "Space Force",
    "defense-wide": "Defense-Wide",
}


@dataclass
class Exhibit:
    """One R-2 or R-2A exhibit, assembled from its consecutive pages."""
    kind: str                      # 'R-2' or 'R-2A'
    fiscal_year: int
    agency: str
    pe_number: str
    pe_name: str
    project_number: str = ""
    project_title: str = ""
    lines: List[str] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.kind, self.pe_number, self.project_number)


def _normalize_agency(raw: str) -> str:
    """Map 'Army', 'Air Force', 'Space Force' as printed to our agency string."""
    cleaned = re.sub(r"\s+", " ", raw).strip().lower()
    cleaned = re.sub(r"\s*date\s*:.*$", "", cleaned).strip()
    for alias, agency in AGENCY_ALIASES.items():
        if cleaned.startswith(alias):
            return agency
    return raw.strip()[:100]


def _split_header_cells(label_line: str, value_line: str) -> Tuple[str, str]:
    """
    Slice the header value row at the column offsets named by the label row.

    In `pdftotext -layout` output the PE cell and the project cell abut, so
    'PE 0601102A / Defense Research Sciences AA1 / ILIR - AMC' is one string.
    The label row carries the real column starts.
    """
    pe_at = RE_PE_LABEL.search(label_line)
    proj_at = RE_PROJECT_LABEL.search(label_line)
    if not pe_at:
        return "", ""
    pe_start = pe_at.start()
    if proj_at:
        pe_cell = value_line[pe_start:proj_at.start()]
        project_cell = value_line[proj_at.start():]
    else:
        pe_cell = value_line[pe_start:]
        project_cell = ""
    return pe_cell.strip(), project_cell.strip()


def _clean(lines: List[str]) -> str:
    """Join wrapped prose, dropping page furniture and blank runs."""
    kept = [l.rstrip() for l in lines if l.strip() and not RE_FURNITURE.match(l)]
    text = " ".join(l.strip() for l in kept)
    return re.sub(r"\s{2,}", " ", text).strip()


def split_pages(text: str) -> List[List[str]]:
    """pdftotext separates pages with form feeds."""
    return [page.split("\n") for page in text.split("\f")]


def parse_exhibits(text: str,
                   diagnostics: Optional[dict] = None) -> List[Exhibit]:
    """
    Walk the book page by page, opening an exhibit on each header and appending
    continuation pages to the exhibit already open.

    A single exhibit routinely spans dozens of pages, and each page repeats the
    header, so pages are merged by (kind, pe_number, project_number) rather
    than treated as separate exhibits.
    """
    exhibits: List[Exhibit] = []
    current: Optional[Exhibit] = None
    # Every PE seen in a header cell, before pages are merged into exhibits.
    # Comparing this against the merged set is the check that merging did not
    # silently swallow an exhibit; a text-wide 'PE nnn /' regex cannot be used
    # because the front matter discusses PEs in prose.
    header_pes: set = set()

    for page in split_pages(text):
        header_at = None
        for index, line in enumerate(page[:6]):
            match = RE_EXHIBIT.match(line.strip())
            if match:
                header_at = (index, match)
                break
        if header_at is None:
            # Front matter, or a continuation page with no banner; keep it
            # attached to whatever exhibit is open.
            if current is not None:
                current.lines.extend(page)
            continue

        index, match = header_at
        kind, fiscal_year, agency_raw = match.groups()

        # Locate the label row and the value row beneath it.
        pe_cell = project_cell = ""
        for offset in range(index + 1, min(index + 5, len(page) - 1)):
            if RE_PE_LABEL.search(page[offset]):
                pe_cell, project_cell = _split_header_cells(
                    page[offset], page[offset + 1])
                break

        pe_match = RE_PE_CELL.search(pe_cell)
        if not pe_match:
            if current is not None:
                current.lines.extend(page)
            continue

        pe_number, pe_name = pe_match.group(1), pe_match.group(2).strip()
        header_pes.add(pe_number)
        project_number = project_title = ""
        if project_cell:
            project_match = RE_PROJECT_CELL.match(project_cell)
            if project_match:
                project_number = project_match.group(1)
                project_title = project_match.group(2).strip()

        candidate = Exhibit(
            kind=kind,
            fiscal_year=int(fiscal_year),
            agency=_normalize_agency(agency_raw),
            pe_number=pe_number,
            pe_name=pe_name,
            project_number=project_number,
            project_title=project_title,
        )
        if current is not None and current.key == candidate.key:
            current.lines.extend(page)
            continue
        current = candidate
        current.lines.extend(page)
        exhibits.append(current)

    if diagnostics is not None:
        diagnostics["header_pes"] = header_pes
    return exhibits


def _section(lines: List[str], opener: re.Pattern) -> List[str]:
    """Lines belonging to one lettered section, up to the next section header."""
    out: List[str] = []
    inside = False
    for line in lines:
        if opener.match(line.strip()):
            inside = True
            continue
        if inside and RE_SECTION_ANY.match(line.strip()):
            break
        if inside:
            out.append(line)
    return out


def extract_narratives(exhibits: List[Exhibit], source_file: str) -> List[dict]:
    """
    Section A of each exhibit -- the mission description -- as pe_narratives rows.

    Both R-2 and R-2A carry a section A; the R-2A one describes the project
    rather than the whole PE, which is why project_number/project_title are
    kept alongside.
    """
    rows: List[dict] = []
    for ex in exhibits:
        body = _clean(_section(ex.lines, RE_SECTION_A))
        if len(body) < 40:
            continue
        rows.append({
            "pe_number": ex.pe_number,
            "agency": ex.agency,
            "fiscal_year": ex.fiscal_year,
            "project_number": ex.project_number,
            "project_title": (ex.project_title or ex.pe_name)[:500],
            "description": body,
            "source_file": source_file,
        })
    return rows


def extract_accomplishments(exhibits: List[Exhibit],
                            source_file: str) -> List[dict]:
    """
    Section B of an R-2A -- the Title/Description/FY-plans blocks -- as
    pe_accomplishments rows, one per fiscal-year statement.
    """
    rows: List[dict] = []
    for ex in exhibits:
        lines = _section(ex.lines, RE_SECTION_ACCOMP)
        if not lines:
            continue

        title = ""
        buffer: List[str] = []
        year: Optional[int] = None
        label = ""

        def flush() -> None:
            nonlocal buffer
            body = _clean(buffer)
            buffer = []
            if not title or len(body) < 20:
                return
            rows.append({
                "pe_number": ex.pe_number,
                "agency": ex.agency,
                "fiscal_year": ex.fiscal_year,
                "project_number": ex.project_number,
                "title": title[:500],
                "year_label": (label or "Description")[:20],
                "accomplishment_fy": year,
                "funding_millions": None,
                "text": body,
                "source_file": source_file,
            })

        for raw in lines:
            line = raw.strip()
            if RE_FURNITURE.match(raw):
                continue

            title_match = RE_ACCOMP_TITLE.match(line)
            if title_match:
                flush()
                title = re.sub(r"\s{2,}.*$", "", title_match.group(1)).strip()
                year, label = None, ""
                continue

            year_match = RE_ACCOMP_YEAR.match(line)
            if year_match:
                flush()
                year = int(year_match.group(1))
                label = year_match.group(2).strip()
                if year_match.group(3).strip():
                    buffer.append(year_match.group(3))
                continue

            desc_match = RE_ACCOMP_DESC.match(line)
            if desc_match:
                flush()
                year, label = None, "Description"
                buffer.append(desc_match.group(1))
                continue

            if line:
                buffer.append(line)
        flush()
    return rows


def parse_book(text: str, source_file: str) -> Dict[str, object]:
    """
    Parse one justification book.

    Returns narratives, accomplishments, and diagnostics. The diagnostics
    matter: on this project the dangerous parser failure has always been rows
    that silently never appear, so callers should assert on `exhibits` and
    `distinct_pes` rather than trusting a non-empty result.
    """
    scan: dict = {}
    exhibits = parse_exhibits(text, diagnostics=scan)
    narratives = extract_narratives(exhibits, source_file)
    accomplishments = extract_accomplishments(exhibits, source_file)

    printed = scan.get("header_pes", set())
    parsed = {e.pe_number for e in exhibits}
    return {
        "narratives": narratives,
        "accomplishments": accomplishments,
        "diagnostics": {
            "exhibits": len(exhibits),
            "r2": sum(1 for e in exhibits if e.kind == "R-2"),
            "r2a": sum(1 for e in exhibits if e.kind == "R-2A"),
            "distinct_pes": len(parsed),
            "pes_printed_but_unparsed": sorted(printed - parsed),
            "agencies": sorted({e.agency for e in exhibits}),
            "fiscal_years": sorted({e.fiscal_year for e in exhibits}),
        },
    }
