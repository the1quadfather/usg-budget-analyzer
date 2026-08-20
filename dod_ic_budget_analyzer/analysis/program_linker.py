"""
analysis/program_linker.py

Orchestrates the matching pipeline:
  0. Direct PE-number lookup (exact - a PE number in the text wins outright)
  1. Lexical fuzzy match over title/acronym aliases (fast, high precision)
  2. Dense semantic match (high recall fallback; optional - the linker runs
     fuzzy-only when no semantic matcher is available)
  3. Ambiguity check: when the top two candidates from different PE numbers
     score within `ambiguity_margin`, the result is flagged `needs_review`
     and all candidates are returned instead of silently picking a winner.

All confidences are normalized to 0-1 regardless of strategy so results are
comparable across FUZZY / SEMANTIC / PE_NUMBER matches.
"""

import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Union

import polars as pl
from tqdm import tqdm

from matching.fuzzy_matcher import ProgramMatcher

if TYPE_CHECKING:  # keep torch/sentence-transformers out of import time
    from matching.semantic_matcher import SemanticMatcher

logger = logging.getLogger(__name__)


class ProgramLinker:
    """
    Executes a multi-stage matching pipeline to link unstructured project
    names to normalized DoD Program Elements.
    """

    def __init__(
        self,
        fuzzy_matcher: ProgramMatcher,
        semantic_matcher: Optional["SemanticMatcher"] = None,
        fuzzy_threshold: float = 80.0,
        semantic_threshold: float = 0.45,
        fuzzy_accept: float = 0.95,
        ambiguity_margin: float = 0.05,
        candidate_limit: int = 5,
    ):
        """
        Args:
            fuzzy_matcher: Instantiated RapidFuzz matcher.
            semantic_matcher: Instantiated SentenceTransformer matcher, or
                None to run lexical-only (e.g. torch unavailable).
            fuzzy_threshold: Minimum WRatio score (0-100) for a fuzzy candidate.
            semantic_threshold: Minimum cosine similarity for a semantic candidate.
            fuzzy_accept: Normalized fuzzy score (0-1) accepted outright
                without consulting the semantic stage.
            ambiguity_margin: If the top two candidates (different PE numbers)
                are closer than this, flag the result for review.
            candidate_limit: Max candidates carried in the result.
        """
        self.fuzzy = fuzzy_matcher
        self.semantic = semantic_matcher
        self.fuzzy_threshold = fuzzy_threshold
        self.semantic_threshold = semantic_threshold
        self.fuzzy_accept = fuzzy_accept
        self.ambiguity_margin = ambiguity_margin
        self.candidate_limit = candidate_limit

    # ── Single query ──────────────────────────────────────────────────────────

    def link_query(self, query: str) -> Dict[str, Union[str, float, int, bool, list, None]]:
        base_result = {
            "query": query,
            "matched_pe_id": None,
            "matched_name": "MANUAL_REVIEW",
            "pe_number": None,
            "agency": None,
            "match_strategy": "NONE",
            "confidence_score": 0.0,
            "needs_review": True,
            "candidates": [],
        }

        if not query or not isinstance(query, str) or not query.strip():
            base_result["matched_name"] = "INVALID_INPUT"
            return base_result

        cleaned_query = query.strip()
        candidates = self._gather_candidates(cleaned_query)
        if not candidates:
            return base_result

        top = candidates[0]
        runner_up = next(
            (c for c in candidates[1:] if c["pe_number"] != top["pe_number"]),
            None,
        )
        ambiguous = (
            top["strategy"] != "PE_NUMBER"
            and runner_up is not None
            and (top["score"] - runner_up["score"]) < self.ambiguity_margin
        )

        base_result.update({
            "matched_pe_id": top["pe_id"],
            "matched_name": top["name"],
            "pe_number": top["pe_number"],
            "agency": top["agency"],
            "match_strategy": "AMBIGUOUS" if ambiguous else top["strategy"],
            "confidence_score": round(top["score"], 3),
            "needs_review": ambiguous,
            "candidates": candidates[: self.candidate_limit],
        })
        return base_result

    def _gather_candidates(self, query: str) -> List[dict]:
        """
        Runs the stages and merges candidates per PE (best score wins).
        Returns candidates sorted by normalized score, descending.
        """
        # Stage 0: exact PE-number hit ends the search
        try:
            pe_hits = self.fuzzy.lookup_pe_number(query)
            if pe_hits:
                return pe_hits
        except Exception as e:
            logger.warning(f"PE-number lookup failed for '{query}': {e}")

        merged: Dict[int, dict] = {}

        # Stage 1: lexical
        fuzzy_hits: List[dict] = []
        try:
            fuzzy_hits = self.fuzzy.find_matches(
                query, limit=self.candidate_limit, score_cutoff=self.fuzzy_threshold
            )
            for c in fuzzy_hits:
                merged[c["pe_id"]] = c
        except Exception as e:
            logger.warning(f"Fuzzy match failed for '{query}': {e}")

        # Stage 2: semantic - skipped when lexical already found a
        # near-perfect hit, or when no semantic matcher is available
        strong_fuzzy = fuzzy_hits and fuzzy_hits[0]["score"] >= self.fuzzy_accept
        if self.semantic is not None and not strong_fuzzy:
            try:
                for c in self.semantic.find_matches(
                    query, limit=self.candidate_limit, threshold=self.semantic_threshold
                ):
                    existing = merged.get(c["pe_id"])
                    if existing is None or c["score"] > existing["score"]:
                        merged[c["pe_id"]] = c
            except Exception as e:
                logger.warning(f"Semantic match failed for '{query}': {e}")

        return sorted(merged.values(), key=lambda c: c["score"], reverse=True)

    # ── Batch ─────────────────────────────────────────────────────────────────

    def link_batch(self, queries: List[str]) -> pl.DataFrame:
        """
        Processes a batch of queries and returns a structured Polars DataFrame.
        """
        results = []
        for query in tqdm(queries, desc="Linking Programs", unit="query"):
            r = self.link_query(query)
            r.pop("candidates", None)  # nested lists don't belong in the frame
            results.append(r)

        schema = {
            "query": pl.Utf8,
            "matched_pe_id": pl.Int64,
            "matched_name": pl.Utf8,
            "pe_number": pl.Utf8,
            "agency": pl.Utf8,
            "match_strategy": pl.Categorical,
            "confidence_score": pl.Float64,
            "needs_review": pl.Boolean,
        }
        return pl.DataFrame(results, schema=schema)
