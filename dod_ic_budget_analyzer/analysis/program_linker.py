"""
matching/program_linker.py

Orchestrates the matching pipeline using a waterfall architecture:
1. Lexical Fuzzy Match (Fast, High Precision)
2. Dense Semantic Match (Compute-Heavy, High Recall Fallback)
3. Manual Review Flag
"""

import logging
from typing import Dict, List, Optional, Union

import polars as pl
from tqdm import tqdm

from matching.fuzzy_matcher import ProgramMatcher
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
        semantic_matcher: SemanticMatcher,
        fuzzy_threshold: float = 80.0,
        semantic_threshold: float = 0.45,
    ):
        """
        Initializes the linker with pre-instantiated matchers via dependency injection 
        to prevent redundant model loading and memory leaks.

        Args:
            fuzzy_matcher (ProgramMatcher): Instantiated RapidFuzz matcher.
            semantic_matcher (SemanticMatcher): Instantiated SentenceTransformer matcher.
            fuzzy_threshold (float): Minimum WRatio score for a fuzzy match (0-100).
            semantic_threshold (float): Minimum cosine similarity for a semantic match (0.0-1.0).
        """
        self.fuzzy = fuzzy_matcher
        self.semantic = semantic_matcher
        self.fuzzy_threshold = fuzzy_threshold
        self.semantic_threshold = semantic_threshold

    def link_query(self, query: str) -> Dict[str, Union[str, float, int, None]]:
        """
        Processes a single query through the waterfall pipeline.

        Args:
            query (str): The unstructured program string.

        Returns:
            Dict: Structured linking result including the match strategy utilized.
        """
        base_result = {
            "query": query,
            "matched_pe_id": None,
            "matched_name": "MANUAL_REVIEW",
            "match_strategy": "NONE",
            "confidence_score": 0.0,
        }

        if not query or not isinstance(query, str) or not query.strip():
            base_result["matched_name"] = "INVALID_INPUT"
            return base_result

        cleaned_query = query.strip()

        # Stage 1: Lexical Fuzzy Match
        try:
            f_match = self.fuzzy.find_best_match(cleaned_query, score_cutoff=self.fuzzy_threshold)
            if f_match:
                base_result.update({
                    "matched_pe_id": f_match[0],
                    "matched_name": f_match[1],
                    "match_strategy": "FUZZY",
                    "confidence_score": round(f_match[2], 2),
                })
                return base_result
        except Exception as e:
            logger.warning(f"Fuzzy match failed for '{cleaned_query}': {e}")

        # Stage 2: Dense Semantic Match (Fallback)
        try:
            s_match = self.semantic.find_best_match(cleaned_query, threshold=self.semantic_threshold)
            if s_match:
                base_result.update({
                    "matched_pe_id": s_match[0],
                    "matched_name": s_match[1],
                    "match_strategy": "SEMANTIC",
                    "confidence_score": round(s_match[2], 3),
                })
                return base_result
        except Exception as e:
            logger.warning(f"Semantic match failed for '{cleaned_query}': {e}")

        # Stage 3: Flag for Manual Review (Default state maintained)
        return base_result

    def link_batch(self, queries: List[str]) -> pl.DataFrame:
        """
        Processes a batch of queries and returns a structured Polars DataFrame.

        Args:
            queries (List[str]): List of unstructured program strings.

        Returns:
            pl.DataFrame: DataFrame containing all link results.
        """
        results = []
        for query in tqdm(queries, desc="Linking Programs", unit="query"):
            results.append(self.link_query(query))
            
        # Enforce strict schema for downstream database insertion or analysis
        schema = {
            "query": pl.Utf8,
            "matched_pe_id": pl.Int64,
            "matched_name": pl.Utf8,
            "match_strategy": pl.Categorical,
            "confidence_score": pl.Float64,
        }
        
        return pl.DataFrame(results, schema=schema)