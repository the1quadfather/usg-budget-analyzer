"""
matching/program_linker.py

Orchestrates the 4-stage matching waterfall pipeline:

  Stage 0 — PE Number Exact Match
    If the query looks like a PE number (e.g. "0604114A"), look it up
    directly in the DB. Instant, perfect match.

  Stage 1 — Acronym Index Match
    Check the pre-built acronym index (parenthetical acronyms from PE titles).
    Highest precision for short names: "LTAMDS", "FTUAS", "M-SHORAD".

  Stage 2 — Fuzzy Match
    RapidFuzz WRatio + token_set_ratio against normalized PE titles.
    Good for partial names and informal variants.

  Stage 3 — Semantic Match
    SentenceTransformer cosine similarity. Best for conceptual queries
    and cases where lexical overlap is low.

  Stage 4 — Manual Review Flag
    Nothing met threshold. Return unmatched for human review.

All stages return top-N candidates, not just the single best match.
The caller (app.py) presents the ranked list for user confirmation.

Usage:
    linker = ProgramLinker(session)

    # Single query - returns ranked candidates
    result = linker.link("LTAMDS")
    for candidate in result.candidates:
        print(candidate.score, candidate.pe_number, candidate.program_name)

    # Batch - returns DataFrame
    df = linker.link_batch(["LTAMDS", "hypersonic glide vehicle", "0604114A"])
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

from matching.acronym_index import AcronymIndex, AcronymMatch
from matching.fuzzy_matcher import FuzzyMatch, ProgramMatcher
from matching.preprocessor import QueryPreprocessor
from matching.semantic_matcher import SemanticMatch, SemanticMatcher
from storage.db import ProgramElement

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class MatchCandidate:
    """A single ranked candidate from any matching stage."""
    pe_id: int
    pe_number: str
    program_name: str
    agency: str
    budget_activity: Optional[str]
    score: float            # normalized 0.0-1.0
    match_stage: str        # "PE_NUMBER" | "ACRONYM" | "FUZZY" | "SEMANTIC"
    match_detail: str       # human-readable explanation


@dataclass
class LinkResult:
    """Result of linking a single query through the pipeline."""
    query: str
    matched: bool
    match_stage: str        # stage that produced the top result
    candidates: list[MatchCandidate] = field(default_factory=list)

    @property
    def top(self) -> Optional[MatchCandidate]:
        return self.candidates[0] if self.candidates else None


# ── Linker ────────────────────────────────────────────────────────────────────

class ProgramLinker:
    """
    Multi-stage matching pipeline linking free-text queries to PE records.

    Lazy-loads the semantic matcher (heavy) only when first needed,
    so short-name / acronym queries are fast.

    Example:
        engine = get_engine(DB_URI)
        SessionFactory = get_session_factory(engine)

        with SessionFactory() as session:
            linker = ProgramLinker(session)
            result = linker.link("LTAMDS")
            print(result.top.program_name)   # "Lower Tier Air Missile Defense..."
            print(result.match_stage)        # "ACRONYM"
    """

    def __init__(
        self,
        session: Session,
        fuzzy_threshold: float = 60.0,
        semantic_threshold: float = 0.35,
        top_n: int = 5,
        load_semantic: bool = True,
    ):
        """
        Args:
            session:            SQLAlchemy session (read-only usage)
            fuzzy_threshold:    minimum fuzzy score 0-100 to include candidates
            semantic_threshold: minimum cosine similarity 0.0-1.0
            top_n:              number of candidates to return per stage
            load_semantic:      if False, skip loading the embedding model
                                (useful for CLI tools that don't need it)
        """
        self.session = session
        self.fuzzy_threshold = fuzzy_threshold
        self.semantic_threshold = semantic_threshold
        self.top_n = top_n

        self.preprocessor = QueryPreprocessor()
        self.acronym_index = AcronymIndex(session)
        self.fuzzy = ProgramMatcher(session)
        self.semantic: Optional[SemanticMatcher] = (
            SemanticMatcher(session) if load_semantic else None
        )

        logger.info(
            f"ProgramLinker ready — "
            f"acronym index: {self.acronym_index.size} entries, "
            f"fuzzy corpus: {len(self.fuzzy._corpus):,} PEs, "
            f"semantic: {'enabled' if self.semantic else 'disabled'}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def link(self, query: str) -> LinkResult:
        """
        Run a single query through the full pipeline.

        Returns a LinkResult with ranked candidates from whichever stage
        first produces results above threshold.
        """
        query = query.strip()
        if not query:
            return LinkResult(query=query, matched=False, match_stage="NONE")

        processed = self.preprocessor.process(query)

        # ── Stage 0: PE number direct lookup ──────────────────────────────
        if processed.pe_number_detected:
            candidates = self._lookup_pe_number(processed.pe_number_detected)
            if candidates:
                return LinkResult(
                    query=query,
                    matched=True,
                    match_stage="PE_NUMBER",
                    candidates=candidates,
                )

        # ── Stage 1: Acronym index ─────────────────────────────────────────
        # Try both the raw acronyms extracted from query AND the query itself
        acr_queries = list(dict.fromkeys(processed.acronyms + [query.strip()]))
        acronym_hits = self.acronym_index.lookup_many(acr_queries)
        if acronym_hits:
            candidates = [self._acronym_to_candidate(m) for m in acronym_hits[:self.top_n]]
            return LinkResult(
                query=query,
                matched=True,
                match_stage="ACRONYM",
                candidates=candidates,
            )

        # ── Stage 2: Fuzzy match ───────────────────────────────────────────
        fuzzy_hits = self.fuzzy.find_top_matches(
            query,
            top_n=self.top_n,
            score_cutoff=self.fuzzy_threshold,
        )
        if fuzzy_hits:
            candidates = [self._fuzzy_to_candidate(m) for m in fuzzy_hits]
            return LinkResult(
                query=query,
                matched=True,
                match_stage="FUZZY",
                candidates=candidates,
            )

        # ── Stage 3: Semantic match ────────────────────────────────────────
        if self.semantic:
            semantic_hits = self.semantic.find_top_matches(
                query,
                top_n=self.top_n,
                threshold=self.semantic_threshold,
            )
            if semantic_hits:
                candidates = [self._semantic_to_candidate(m) for m in semantic_hits]
                return LinkResult(
                    query=query,
                    matched=True,
                    match_stage="SEMANTIC",
                    candidates=candidates,
                )

        # ── Stage 4: No match ──────────────────────────────────────────────
        return LinkResult(query=query, matched=False, match_stage="NONE")

    def link_batch(self, queries: list[str]) -> pl.DataFrame:
        """
        Link a batch of queries and return a flat Polars DataFrame.

        Each row represents one candidate for one query. Queries with
        multiple candidates appear as multiple rows (top candidate first).

        Returns DataFrame with columns:
            query, matched, match_stage, rank,
            pe_id, pe_number, program_name, agency, budget_activity,
            score, match_detail
        """
        rows = []
        for query in tqdm(queries, desc="Linking", unit="query"):
            result = self.link(query)
            if result.candidates:
                for rank, candidate in enumerate(result.candidates, start=1):
                    rows.append({
                        "query":          result.query,
                        "matched":        result.matched,
                        "match_stage":    result.match_stage,
                        "rank":           rank,
                        "pe_id":          candidate.pe_id,
                        "pe_number":      candidate.pe_number,
                        "program_name":   candidate.program_name,
                        "agency":         candidate.agency,
                        "budget_activity": candidate.budget_activity or "",
                        "score":          candidate.score,
                        "match_detail":   candidate.match_detail,
                    })
            else:
                rows.append({
                    "query":          result.query,
                    "matched":        False,
                    "match_stage":    "NONE",
                    "rank":           0,
                    "pe_id":          None,
                    "pe_number":      "",
                    "program_name":   "MANUAL_REVIEW",
                    "agency":         "",
                    "budget_activity": "",
                    "score":          0.0,
                    "match_detail":   "No match found above threshold",
                })

        if not rows:
            return pl.DataFrame()

        return pl.DataFrame(rows, schema={
            "query":           pl.Utf8,
            "matched":         pl.Boolean,
            "match_stage":     pl.Utf8,
            "rank":            pl.Int64,
            "pe_id":           pl.Int64,
            "pe_number":       pl.Utf8,
            "program_name":    pl.Utf8,
            "agency":          pl.Utf8,
            "budget_activity": pl.Utf8,
            "score":           pl.Float64,
            "match_detail":    pl.Utf8,
        })

    # ── Stage helpers ─────────────────────────────────────────────────────────

    def _lookup_pe_number(self, pe_number: str) -> list[MatchCandidate]:
        """Direct DB lookup by PE number."""
        stmt = select(
            ProgramElement.id,
            ProgramElement.pe_number,
            ProgramElement.program_name,
            ProgramElement.agency,
            ProgramElement.budget_activity,
        ).where(ProgramElement.pe_number == pe_number)
        rows = self.session.execute(stmt).all()
        return [
            MatchCandidate(
                pe_id=r.id,
                pe_number=r.pe_number,
                program_name=r.program_name,
                agency=r.agency or "",
                budget_activity=r.budget_activity,
                score=1.0,
                match_stage="PE_NUMBER",
                match_detail=f"Exact PE number match: {pe_number}",
            )
            for r in rows
        ]

    def _acronym_to_candidate(self, m: AcronymMatch) -> MatchCandidate:
        return MatchCandidate(
            pe_id=m.pe_id,
            pe_number=m.pe_number,
            program_name=m.program_name,
            agency=m.agency,
            budget_activity=m.budget_activity,
            score=m.score,
            match_stage="ACRONYM",
            match_detail=f"Acronym match: '{m.acronym}' found in title",
        )

    def _fuzzy_to_candidate(self, m: FuzzyMatch) -> MatchCandidate:
        return MatchCandidate(
            pe_id=m.pe_id,
            pe_number=m.pe_number,
            program_name=m.program_name,
            agency=m.agency,
            budget_activity=m.budget_activity,
            score=round(m.score / 100.0, 4),  # normalize to 0-1
            match_stage="FUZZY",
            match_detail=f"Fuzzy score: {m.score:.0f}/100 (matched on {m.match_on})",
        )

    def _semantic_to_candidate(self, m: SemanticMatch) -> MatchCandidate:
        return MatchCandidate(
            pe_id=m.pe_id,
            pe_number=m.pe_number,
            program_name=m.program_name,
            agency=m.agency,
            budget_activity=m.budget_activity,
            score=m.score,
            match_stage="SEMANTIC",
            match_detail=f"Semantic similarity: {m.score:.3f}",
        )
