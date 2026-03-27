"""
matching/fuzzy_matcher.py

RapidFuzz-based lexical matcher for DoD Program Elements.

Key improvements over original:
  - Returns top-N candidates (not just the single best match)
  - Matches against both normalized title AND original title for better recall
  - Includes agency and PE number in results for disambiguation
  - Uses token_set_ratio in addition to WRatio for better partial matches
"""

import logging
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from matching.preprocessor import QueryPreprocessor
from storage.db import ProgramElement

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class FuzzyMatch:
    pe_id: int
    pe_number: str
    program_name: str
    agency: str
    budget_activity: Optional[str]
    score: float            # 0-100 WRatio score
    match_on: str           # "normalized" or "original" — which form matched


# ── Matcher ───────────────────────────────────────────────────────────────────

class ProgramMatcher:
    """
    In-memory fuzzy matching engine for DoD Program Elements.

    Loads all PE titles at init time and matches queries using RapidFuzz.
    Returns ranked top-N candidates so the caller can present options.

    Example:
        with SessionFactory() as session:
            matcher = ProgramMatcher(session)
            results = matcher.find_top_matches("future vertical lift", top_n=5)
            for r in results:
                print(r.score, r.pe_number, r.program_name, r.agency)
    """

    def __init__(self, session: Session):
        self.session = session
        self.preprocessor = QueryPreprocessor()

        # pe_id -> (pe_number, original_name, normalized_name, agency, ba)
        self._corpus: dict[int, tuple[str, str, str, str, str]] = {}
        self._load()

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load all non-classified PEs from DB into memory."""
        stmt = select(
            ProgramElement.id,
            ProgramElement.pe_number,
            ProgramElement.program_name,
            ProgramElement.agency,
            ProgramElement.budget_activity,
        ).where(ProgramElement.is_classified == False)  # noqa: E712

        rows = self.session.execute(stmt).all()

        for pe_id, pe_num, name, agency, ba in rows:
            if not name:
                continue
            processed = self.preprocessor.process(name)
            self._corpus[pe_id] = (
                pe_num or "",
                name,
                processed.expanded,   # normalized + abbreviations expanded
                agency or "",
                ba or "",
            )

        logger.info(f"Fuzzy matcher loaded {len(self._corpus):,} program elements")

    # ── Match ─────────────────────────────────────────────────────────────────

    def find_top_matches(
        self,
        query: str,
        top_n: int = 5,
        score_cutoff: float = 55.0,
    ) -> list[FuzzyMatch]:
        """
        Find the top-N fuzzy matches for a query.

        Searches against both the normalized (expanded) corpus and the
        original PE titles, taking the best score per PE.

        Args:
            query:        raw or preprocessed query string
            top_n:        number of candidates to return
            score_cutoff: minimum WRatio score to include (0-100)

        Returns:
            List of FuzzyMatch sorted by score descending.
        """
        processed = self.preprocessor.process(query)
        search_query = processed.expanded or processed.normalized or query.lower()

        if not search_query.strip():
            return []

        # Build two search corpora: normalized titles and original titles
        norm_choices = {pid: data[2] for pid, data in self._corpus.items()}
        orig_choices = {pid: data[1] for pid, data in self._corpus.items()}

        # Score against normalized titles (primary)
        norm_results = process.extract(
            query=search_query,
            choices=norm_choices,
            scorer=fuzz.WRatio,
            limit=top_n * 3,    # over-fetch then merge
            score_cutoff=score_cutoff,
        )

        # Score against original titles (catches cases expansion hurts)
        orig_results = process.extract(
            query=query,
            choices=orig_choices,
            scorer=fuzz.token_set_ratio,
            limit=top_n * 3,
            score_cutoff=score_cutoff,
        )

        # Merge: best score per PE across both searches
        best_per_pe: dict[int, tuple[float, str]] = {}
        for _text, score, pe_id in norm_results:
            if pe_id not in best_per_pe or score > best_per_pe[pe_id][0]:
                best_per_pe[pe_id] = (score, "normalized")
        for _text, score, pe_id in orig_results:
            if pe_id not in best_per_pe or score > best_per_pe[pe_id][0]:
                best_per_pe[pe_id] = (score, "original")

        # Build result objects
        matches: list[FuzzyMatch] = []
        for pe_id, (score, match_on) in best_per_pe.items():
            pe_num, name, _norm, agency, ba = self._corpus[pe_id]
            matches.append(FuzzyMatch(
                pe_id=pe_id,
                pe_number=pe_num,
                program_name=name,
                agency=agency,
                budget_activity=ba,
                score=round(score, 1),
                match_on=match_on,
            ))

        matches.sort(key=lambda x: -x.score)
        return matches[:top_n]

    def find_best_match(
        self,
        query: str,
        score_cutoff: float = 75.0,
    ) -> Optional[tuple[int, str, float]]:
        """
        Compatibility shim returning (pe_id, name, score) for the top match.
        Used by program_linker waterfall pipeline.
        """
        results = self.find_top_matches(query, top_n=1, score_cutoff=score_cutoff)
        if results:
            r = results[0]
            return (r.pe_id, r.program_name, r.score)
        return None
