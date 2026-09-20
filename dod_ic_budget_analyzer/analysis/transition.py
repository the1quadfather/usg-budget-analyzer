"""Generate procurement-transition candidates for an RDT&E Program Element."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import re

from rapidfuzz import fuzz, process
from sqlalchemy import select

import config
from analysis.narrative_qa import SENTENCE_BOUNDARY_RE, _load_model
from matching.normalizer import normalize_program_name
from storage.db import (
    PEAccomplishment,
    PENarrative,
    ProcurementLine,
    ProgramElement,
    get_engine,
    get_session_factory,
)


CONFIDENCE_FLOOR = 0.6
RESEARCH_BUDGET_ACTIVITIES = ("01", "02")
BLI_RE = re.compile(r"\bBLI\s*#?\s*:?\s*([A-Z0-9]{2,12})\b")
DB_URI = f"sqlite:///{(config.PROCESSED_DIR / 'usg_budgets.db').as_posix()}"

ALLOWED_P1_AGENCIES = {
    "Navy": ("Navy", "Marine Corps"),
    "Air Force": ("Air Force", "Space Force"),
    "Space Force": ("Space Force", "Air Force"),
    "Army": ("Army",),
    "Defense-Wide": ("Defense-Wide",),
}


@dataclass(frozen=True)
class TransitionCandidate:
    pe_number: str
    agency: str
    bli: str
    appropriation: str
    line_item_title: str
    p1_agency: str
    confidence: float
    strategy: str
    evidence_text: str | None
    evidence_source: str | None
    ambiguous: bool


def is_research_pe(pe_number: str) -> bool:
    """Return whether a PE belongs to research budget activity 1 or 2."""
    return pe_number[2:4] in RESEARCH_BUDGET_ACTIVITIES


def _sentences(text: str) -> list[str]:
    return SENTENCE_BOUNDARY_RE.split(text)


def bli_mentions(session, pe_number, agency) -> list[tuple[str, str, str]]:
    """Return BLI codes with their verbatim source sentence and filename."""
    found: list[tuple[int, int, str, str, str]] = []
    narratives = session.execute(
        select(PENarrative).where(
            PENarrative.pe_number == pe_number,
            PENarrative.agency == agency,
        ).order_by(PENarrative.fiscal_year.desc(), PENarrative.id.desc())
    ).scalars()
    for row in narratives:
        for sentence in _sentences(row.description):
            for match in BLI_RE.finditer(sentence):
                found.append((
                    row.fiscal_year,
                    row.id,
                    match.group(1),
                    sentence,
                    row.source_file,
                ))

    accomplishments = session.execute(
        select(PEAccomplishment).where(
            PEAccomplishment.pe_number == pe_number,
            PEAccomplishment.agency == agency,
        ).order_by(
            PEAccomplishment.fiscal_year.desc(),
            PEAccomplishment.id.desc(),
        )
    ).scalars()
    for row in accomplishments:
        for sentence in _sentences(row.text):
            for match in BLI_RE.finditer(sentence):
                found.append((
                    row.fiscal_year,
                    row.id,
                    match.group(1),
                    sentence,
                    row.source_file,
                ))

    mentions: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, _, code, sentence, source in sorted(
        found, key=lambda item: (-item[0], -item[1], item[2])
    ):
        mention = (code, sentence, source)
        if mention not in seen:
            seen.add(mention)
            mentions.append(mention)
    return mentions


def _program_name(session, pe_number: str, agency: str) -> str | None:
    return session.execute(
        select(ProgramElement.program_name).where(
            ProgramElement.pe_number == pe_number,
            ProgramElement.agency == agency,
        ).order_by(ProgramElement.id.desc())
    ).scalars().first()


def _procurement_rows(session, agencies: tuple[str, ...]):
    if not agencies:
        return []
    return session.execute(
        select(
            ProcurementLine.bli,
            ProcurementLine.appropriation,
            ProcurementLine.line_item_title,
            ProcurementLine.agency,
        ).where(ProcurementLine.agency.in_(agencies)).distinct().order_by(
            ProcurementLine.line_item_title,
            ProcurementLine.bli,
            ProcurementLine.appropriation,
            ProcurementLine.agency,
        )
    ).all()


def _candidate(pe_number: str, agency: str, row, confidence: float,
               strategy: str, evidence_text: str | None = None,
               evidence_source: str | None = None) -> TransitionCandidate:
    return TransitionCandidate(
        pe_number=pe_number,
        agency=agency,
        bli=row.bli,
        appropriation=row.appropriation,
        line_item_title=row.line_item_title,
        p1_agency=row.agency,
        confidence=confidence,
        strategy=strategy,
        evidence_text=evidence_text,
        evidence_source=evidence_source,
        ambiguous=False,
    )


def _narrative_candidates(session, pe_number: str, agency: str,
                          agencies: tuple[str, ...]) -> list[TransitionCandidate]:
    rows = _procurement_rows(session, agencies)
    by_code: dict[str, list] = {}
    for row in rows:
        by_code.setdefault(row.bli, []).append(row)

    candidates: list[TransitionCandidate] = []
    seen: set[tuple[str, str]] = set()
    for code, sentence, source in bli_mentions(session, pe_number, agency):
        for row in by_code.get(code, []):
            key = (row.bli, row.appropriation)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(_candidate(
                pe_number,
                agency,
                row,
                0.95,
                "NARRATIVE",
                sentence,
                source,
            ))
    return candidates


def _fuzzy_candidates(session, pe_number: str, agency: str,
                      program_name: str,
                      agencies: tuple[str, ...]) -> list[TransitionCandidate]:
    query = normalize_program_name(program_name)
    if not query:
        return []
    rows = _procurement_rows(session, agencies)
    by_title: dict[str, list] = {}
    for row in rows:
        title = normalize_program_name(row.line_item_title)
        if title:
            by_title.setdefault(title, []).append(row)

    candidates: list[TransitionCandidate] = []
    matches = process.extract(
        query,
        list(by_title),
        scorer=fuzz.WRatio,
        score_cutoff=85,
        limit=10,
    )
    for title, score, _ in matches:
        if fuzz.token_set_ratio(query, title) < 60:
            continue
        confidence = min(float(score) / 100.0, 0.99)
        for row in by_title[title]:
            candidates.append(_candidate(
                pe_number, agency, row, confidence, "FUZZY"
            ))
    return candidates


@lru_cache(maxsize=1)
def _semantic_title_index():
    """Encode the tracked P-1 title vocabulary once per process."""
    Session = get_session_factory(get_engine(DB_URI))
    with Session() as session:
        rows = session.execute(
            select(
                ProcurementLine.line_item_title,
                ProcurementLine.bli,
                ProcurementLine.appropriation,
                ProcurementLine.agency,
            ).distinct().order_by(
                ProcurementLine.line_item_title,
                ProcurementLine.bli,
                ProcurementLine.appropriation,
                ProcurementLine.agency,
            )
        ).all()

    titles: list[str] = []
    by_title: dict[str, list[tuple[str, str, str]]] = {}
    for title, bli, appropriation, agency in rows:
        if title not in by_title:
            titles.append(title)
            by_title[title] = []
        by_title[title].append((bli, appropriation, agency))

    model = _load_model()
    embeddings = model.encode(
        titles,
        convert_to_tensor=True,
        normalize_embeddings=True,
    ).to(device="cpu")
    return tuple(titles), by_title, embeddings


def _semantic_candidates(pe_number: str, agency: str, program_name: str,
                         agencies: tuple[str, ...]) -> list[TransitionCandidate]:
    titles, by_title, embeddings = _semantic_title_index()
    model = _load_model()
    query = model.encode(
        program_name,
        convert_to_tensor=True,
        normalize_embeddings=True,
    ).to(device="cpu")
    scores = (embeddings @ query).tolist()

    candidates: list[TransitionCandidate] = []
    allowed = set(agencies)
    for title, score in zip(titles, scores):
        confidence = min(max(float(score), 0.0), 1.0)
        if confidence < CONFIDENCE_FLOOR:
            continue
        for bli, appropriation, p1_agency in by_title[title]:
            if p1_agency not in allowed:
                continue
            candidates.append(TransitionCandidate(
                pe_number=pe_number,
                agency=agency,
                bli=bli,
                appropriation=appropriation,
                line_item_title=title,
                p1_agency=p1_agency,
                confidence=confidence,
                strategy="SEMANTIC",
                evidence_text=None,
                evidence_source=None,
                ambiguous=False,
            ))
    return candidates


def _mark_ambiguity(candidates: list[TransitionCandidate]) -> list[TransitionCandidate]:
    ambiguous: set[int] = set()
    for index in range(len(candidates) - 1):
        if candidates[index].confidence - candidates[index + 1].confidence <= 0.1:
            ambiguous.update((index, index + 1))
    return [
        replace(candidate, ambiguous=index in ambiguous)
        for index, candidate in enumerate(candidates)
    ]


def propose_transitions_with_status(
    session, pe_number: str, agency: str, *, limit: int = 5
) -> tuple[list[TransitionCandidate], bool]:
    """Return candidates and whether semantic title matching was available."""
    if limit <= 0 or is_research_pe(pe_number):
        return [], True
    program_name = _program_name(session, pe_number, agency)
    if not program_name or program_name.startswith("Classified"):
        return [], True
    agencies = ALLOWED_P1_AGENCIES.get(agency, ())
    if not agencies:
        return [], True

    proposed = _narrative_candidates(session, pe_number, agency, agencies)
    proposed.extend(_fuzzy_candidates(
        session, pe_number, agency, program_name, agencies
    ))
    semantic_available = True
    try:
        proposed.extend(_semantic_candidates(
            pe_number, agency, program_name, agencies
        ))
    except (ImportError, OSError):
        semantic_available = False

    merged: dict[tuple[str, str], TransitionCandidate] = {}
    for candidate in proposed:
        if candidate.confidence < CONFIDENCE_FLOOR:
            continue
        key = (candidate.bli, candidate.appropriation)
        current = merged.get(key)
        if current is None or candidate.confidence > current.confidence:
            merged[key] = candidate

    ranked = sorted(
        merged.values(), key=lambda candidate: (-candidate.confidence, candidate.bli)
    )
    return _mark_ambiguity(ranked)[:limit], semantic_available


def propose_transitions(session, pe_number: str, agency: str, *,
                        limit: int = 5) -> list[TransitionCandidate]:
    """Return ranked procurement-transition candidates for one PE."""
    candidates, _ = propose_transitions_with_status(
        session, pe_number, agency, limit=limit
    )
    return candidates
