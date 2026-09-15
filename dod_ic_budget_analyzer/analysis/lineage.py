r"""Detect evidence-backed lineage relationships between program elements.

Narrative detection composes this regex set. Prose matching is case-insensitive;
captured PE numbers are revalidated case-sensitively against the listed shape:

* Sentence split: ``(?<=\.)[ \t]+|[\r\n]+``.
* PE reference: ``(?:\bPE\b|\bProgram\s+Element(?:\s*\(\s*PE\s*\))?)``
  followed by ``\s*[:#,-]?\s*\(?\s*(?P<pe>\d{7}[A-Z0-9]{1,3})\b``.
* Verb gap: ``(?:(?!\b(?:realigned|transferred|moved|consolidated)\b).)*?``.
* Reference gap: ``(?:(?!\b(?:from|to|into|under)\b).)*?``.
* From direction: ``\b(?:realigned|transferred|moved|consolidated)\b``, verb
  gap, ``\bfrom\b``, reference gap, then a PE reference.
* To direction: ``\b(?:realigned|transferred|moved)\b``, verb gap,
  ``\b(?:to|into)\b``, reference gap, then a PE reference.
* Consolidation destination: ``\bconsolidated\b``, verb gap,
  ``\b(?:into|under)\b``, reference gap, then a PE reference.
* Fiscal year: ``\bFY\s?(?P<year>20\d{2}|\d{2})\b``.
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import permutations
import re
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import literal, select, union_all
from sqlalchemy.orm import Session

from matching.normalizer import normalize_program_name
from storage.db import FundingLine, PEAccomplishment, PENarrative, ProgramElement


Relation = Literal["renumbered", "split", "merged", "transferred"]

TITLE_SIMILARITY_THRESHOLD = 85.0
_ELIGIBLE_FUNDING_TYPES = ("PY Actual", "CY Request", "BY Request")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=\.)[ \t]+|[\r\n]+")
_PE_NUMBER_PATTERN = r"\d{7}[A-Z0-9]{1,3}"
_PE_NUMBER_RE = re.compile(rf"{_PE_NUMBER_PATTERN}")
_PE_REFERENCE_PATTERN = (
    r"(?:\bPE\b|\bProgram\s+Element(?:\s*\(\s*PE\s*\))?)"
    rf"\s*[:#,-]?\s*\(?\s*(?P<pe>{_PE_NUMBER_PATTERN})\b"
)
_VERB_GAP_PATTERN = (
    r"(?:(?!\b(?:realigned|transferred|moved|consolidated)\b).)*?"
)
_REFERENCE_GAP_PATTERN = r"(?:(?!\b(?:from|to|into|under)\b).)*?"
_DIRECTION_PATTERNS = (
    (
        "from",
        re.compile(
            rf"\b(?:realigned|transferred|moved|consolidated)\b"
            rf"{_VERB_GAP_PATTERN}\bfrom\b"
            rf"{_REFERENCE_GAP_PATTERN}{_PE_REFERENCE_PATTERN}",
            re.IGNORECASE,
        ),
    ),
    (
        "to",
        re.compile(
            rf"\b(?:realigned|transferred|moved)\b"
            rf"{_VERB_GAP_PATTERN}\b(?:to|into)\b"
            rf"{_REFERENCE_GAP_PATTERN}{_PE_REFERENCE_PATTERN}",
            re.IGNORECASE,
        ),
    ),
    (
        "to",
        re.compile(
            rf"\bconsolidated\b{_VERB_GAP_PATTERN}\b(?:into|under)\b"
            rf"{_REFERENCE_GAP_PATTERN}{_PE_REFERENCE_PATTERN}",
            re.IGNORECASE,
        ),
    ),
)
_FISCAL_YEAR_RE = re.compile(
    r"\bFY\s?(?P<year>20\d{2}|\d{2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LineageEdge:
    """A proposed lineage relationship and the evidence supporting it."""

    predecessor_pe: str
    predecessor_agency: str
    successor_pe: str
    successor_agency: str
    relation: Relation
    first_fy_after: int
    evidence_text: str | None
    evidence_source: str | None
    confidence: float
    method: str
    content_hash: str


@dataclass
class _FundingSeries:
    titles: set[str] = field(default_factory=set)
    cycles_by_fy: dict[int, set[int | None]] = field(
        default_factory=lambda: defaultdict(set)
    )


def _is_valid_pe_number(pe_number: str) -> bool:
    """Return whether a PE has seven digits followed by a 1–3 character suffix."""
    return 8 <= len(pe_number) <= 10 and pe_number[:7].isdigit()


def _title_score(predecessor: _FundingSeries, successor: _FundingSeries) -> float:
    predecessor_titles = {
        normalize_program_name(title) for title in predecessor.titles
    }
    successor_titles = {
        normalize_program_name(title) for title in successor.titles
    }
    return max(
        fuzz.token_set_ratio(predecessor_title, successor_title)
        for predecessor_title in predecessor_titles
        for successor_title in successor_titles
    )


def _confidence(title_score: float, gap: int) -> float:
    """Map title score 85→0.6 and 100→1.0, then deduct 0.1 for gap 2."""
    confidence = 0.6 + (
        (title_score - TITLE_SIMILARITY_THRESHOLD)
        * 0.4
        / (100.0 - TITLE_SIMILARITY_THRESHOLD)
    )
    if gap == 2:
        confidence -= 0.1
    return confidence


def _content_hash(
    predecessor_pe: str,
    predecessor_agency: str,
    successor_pe: str,
    successor_agency: str,
    relation: Relation,
    method: str,
) -> str:
    identity = "|".join((
        predecessor_pe,
        predecessor_agency,
        successor_pe,
        successor_agency,
        relation,
        method,
    ))
    return sha256(identity.encode("utf-8")).hexdigest()


def _load_funding_series(
    session: Session,
) -> dict[tuple[str, str], _FundingSeries]:
    statement = (
        select(
            ProgramElement.pe_number,
            ProgramElement.agency,
            ProgramElement.program_name,
            FundingLine.fiscal_year,
            FundingLine.pb_cycle,
        )
        .join(
            FundingLine,
            FundingLine.program_element_id == ProgramElement.id,
        )
        .where(
            ProgramElement.pe_number != "",
            ProgramElement.agency != "Unknown",
            FundingLine.funding_type.in_(_ELIGIBLE_FUNDING_TYPES),
            FundingLine.amount_thousands.is_not(None),
            FundingLine.amount_thousands != 0,
        )
    )

    series: dict[tuple[str, str], _FundingSeries] = {}
    for pe_number, agency, title, fiscal_year, pb_cycle in session.execute(statement):
        if not _is_valid_pe_number(pe_number):
            continue
        key = (pe_number, agency)
        item = series.setdefault(key, _FundingSeries())
        item.titles.add(title)
        item.cycles_by_fy[fiscal_year].add(pb_cycle)
    return series


def _gap_is_eligible(
    predecessor: _FundingSeries,
    successor: _FundingSeries,
) -> tuple[int, int] | None:
    predecessor_last_fy = max(predecessor.cycles_by_fy)
    successor_first_fy = min(successor.cycles_by_fy)
    gap = successor_first_fy - predecessor_last_fy
    if gap not in (0, 1, 2):
        return None
    if any(fiscal_year > successor_first_fy for fiscal_year in predecessor.cycles_by_fy):
        return None
    if gap == 0:
        predecessor_cycles = predecessor.cycles_by_fy[predecessor_last_fy]
        successor_cycles = successor.cycles_by_fy[successor_first_fy]
        if None in predecessor_cycles or None in successor_cycles:
            return None
        if max(predecessor_cycles) >= min(successor_cycles):
            return None
    return successor_first_fy, gap


def detect_ba_renumbering(session: Session) -> list[LineageEdge]:
    """Find PEs whose budget-activity digits changed at a funding boundary.

    Candidate PEs must share an agency and every PE character except positions
    3–4. Their normalized titles must score at least 85. Funding series may
    overlap in their boundary FY only when every predecessor observation is
    from an older PB cycle than every successor observation. One- and two-year
    gaps are also accepted, with a 0.1 confidence deduction for a two-year gap.

    Confidence maps the title score linearly from 0.6 at 85 to 1.0 at 100,
    before applying the gap-2 deduction.
    """
    series = _load_funding_series(session)
    by_signature: dict[
        tuple[str, str, str], list[tuple[str, str]]
    ] = defaultdict(list)
    for pe_number, agency in series:
        by_signature[(agency, pe_number[:2], pe_number[4:])].append(
            (pe_number, agency)
        )

    edges: list[LineageEdge] = []
    for candidates in by_signature.values():
        for predecessor_key, successor_key in permutations(sorted(candidates), 2):
            predecessor = series[predecessor_key]
            successor = series[successor_key]
            boundary = _gap_is_eligible(predecessor, successor)
            if boundary is None:
                continue
            first_fy_after, gap = boundary
            title_score = _title_score(predecessor, successor)
            if title_score < TITLE_SIMILARITY_THRESHOLD:
                continue

            predecessor_pe, predecessor_agency = predecessor_key
            successor_pe, successor_agency = successor_key
            relation: Relation = "renumbered"
            method = "ba_renumber"
            edges.append(LineageEdge(
                predecessor_pe=predecessor_pe,
                predecessor_agency=predecessor_agency,
                successor_pe=successor_pe,
                successor_agency=successor_agency,
                relation=relation,
                first_fy_after=first_fy_after,
                evidence_text=None,
                evidence_source="funding_series",
                confidence=_confidence(title_score, gap),
                method=method,
                content_hash=_content_hash(
                    predecessor_pe,
                    predecessor_agency,
                    successor_pe,
                    successor_agency,
                    relation,
                    method,
                ),
            ))

    return sorted(
        edges,
        key=lambda edge: (
            edge.predecessor_pe,
            edge.predecessor_agency,
            edge.successor_pe,
            edge.successor_agency,
        ),
    )


def _iter_narrative_rows(
    session: Session,
) -> Iterator[tuple[str, int, str, str, int, str]]:
    narrative_rows = select(
        PENarrative.source_file.label("source_file"),
        PENarrative.id.label("row_id"),
        literal(0).label("table_order"),
        PENarrative.pe_number.label("pe_number"),
        PENarrative.agency.label("agency"),
        PENarrative.fiscal_year.label("fiscal_year"),
        PENarrative.description.label("body"),
    )
    accomplishment_rows = select(
        PEAccomplishment.source_file.label("source_file"),
        PEAccomplishment.id.label("row_id"),
        literal(1).label("table_order"),
        PEAccomplishment.pe_number.label("pe_number"),
        PEAccomplishment.agency.label("agency"),
        PEAccomplishment.fiscal_year.label("fiscal_year"),
        PEAccomplishment.text.label("body"),
    )
    rows = union_all(narrative_rows, accomplishment_rows).subquery()
    statement = select(
        rows.c.source_file,
        rows.c.row_id,
        rows.c.pe_number,
        rows.c.agency,
        rows.c.fiscal_year,
        rows.c.body,
    ).order_by(rows.c.source_file, rows.c.row_id, rows.c.table_order)

    for row in session.execute(statement).yield_per(1000):
        yield tuple(row)


def _iter_sentences(text: str) -> Iterator[str]:
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if sentence:
            yield sentence


def _iter_directional_references(sentence: str) -> Iterator[tuple[str, str]]:
    matches: list[tuple[int, int, str, str]] = []
    for pattern_index, (direction, pattern) in enumerate(_DIRECTION_PATTERNS):
        for match in pattern.finditer(sentence):
            pe_number = match.group("pe")
            if _PE_NUMBER_RE.fullmatch(pe_number) is None:
                continue
            matches.append((
                match.start(),
                pattern_index,
                direction,
                pe_number,
            ))
    for _, _, direction, pe_number in sorted(matches):
        yield direction, pe_number


def _first_fiscal_year(sentence: str, row_fiscal_year: int) -> tuple[int, float]:
    match = _FISCAL_YEAR_RE.search(sentence)
    if match is None:
        return row_fiscal_year, 0.7
    year = match.group("year")
    if len(year) == 2:
        return 2000 + int(year), 0.9
    return int(year), 0.9


def detect_narrative_transfers(session: Session) -> list[LineageEdge]:
    """Find PE transfers stated explicitly in R-2 narrative sentences.

    ``from`` references make the cited PE the predecessor; ``to``, ``into``,
    and ``under`` references make the row PE the predecessor. A component name
    in prose does not override the stored row agency: both endpoints retain the
    row's agency until cross-component attribution is implemented separately.
    Evidence is deduplicated by T11a's lineage identity hash in ``source_file``,
    row-id order.
    """
    edges_by_hash: dict[str, LineageEdge] = {}
    for source_file, _, row_pe, agency, row_fiscal_year, body in (
        _iter_narrative_rows(session)
    ):
        if _PE_NUMBER_RE.fullmatch(row_pe) is None:
            continue
        for sentence in _iter_sentences(body):
            first_fy_after, confidence = _first_fiscal_year(
                sentence,
                row_fiscal_year,
            )
            for direction, cited_pe in _iter_directional_references(sentence):
                if cited_pe == row_pe:
                    continue
                if direction == "from":
                    predecessor_pe, successor_pe = cited_pe, row_pe
                else:
                    predecessor_pe, successor_pe = row_pe, cited_pe

                relation: Relation = "transferred"
                method = "narrative"
                content_hash = _content_hash(
                    predecessor_pe,
                    agency,
                    successor_pe,
                    agency,
                    relation,
                    method,
                )
                if content_hash in edges_by_hash:
                    continue
                edges_by_hash[content_hash] = LineageEdge(
                    predecessor_pe=predecessor_pe,
                    predecessor_agency=agency,
                    successor_pe=successor_pe,
                    successor_agency=agency,
                    relation=relation,
                    first_fy_after=first_fy_after,
                    evidence_text=sentence,
                    evidence_source=source_file,
                    confidence=confidence,
                    method=method,
                    content_hash=content_hash,
                )

    return list(edges_by_hash.values())
