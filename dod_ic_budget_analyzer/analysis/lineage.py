"""Detect evidence-backed lineage relationships between program elements."""

from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import permutations
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from matching.normalizer import normalize_program_name
from storage.db import FundingLine, ProgramElement


Relation = Literal["renumbered", "split", "merged", "transferred"]

TITLE_SIMILARITY_THRESHOLD = 85.0
_ELIGIBLE_FUNDING_TYPES = ("PY Actual", "CY Request", "BY Request")


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
