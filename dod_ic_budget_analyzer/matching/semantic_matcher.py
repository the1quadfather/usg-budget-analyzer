"""
matching/semantic_matcher.py

Dense vector semantic matcher for DoD Program Elements.

Key improvements over original:
  - Returns top-N candidates (not just the single best match)
  - Includes PE number and agency in results for disambiguation
  - Skips classified PEs (no meaningful title to embed)
  - Preprocesses both corpus and queries for better embedding alignment
"""

import logging
from dataclasses import dataclass
from typing import Optional

import torch
from sentence_transformers import SentenceTransformer, util
from sqlalchemy import select
from sqlalchemy.orm import Session

from matching.preprocessor import QueryPreprocessor
from storage.db import ProgramElement

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class SemanticMatch:
    pe_id: int
    pe_number: str
    program_name: str
    agency: str
    budget_activity: Optional[str]
    score: float        # cosine similarity 0.0-1.0


# ── Matcher ───────────────────────────────────────────────────────────────────

class SemanticMatcher:
    """
    Dense embedding semantic matcher using SentenceTransformers.

    Encodes all PE titles at init time into a normalized tensor matrix.
    At query time encodes the query and performs cosine similarity search.

    Example:
        with SessionFactory() as session:
            matcher = SemanticMatcher(session)
            results = matcher.find_top_matches("hypersonic glide vehicle", top_n=5)
    """

    DEFAULT_MODEL = "multi-qa-MiniLM-L6-cos-v1"

    def __init__(self, session: Session, model_name: str = DEFAULT_MODEL):
        self.session = session
        self.preprocessor = QueryPreprocessor()

        self.device = (
            "cuda" if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available()
            else "cpu"
        )
        logger.info(f"SemanticMatcher device: {self.device}")

        self.model = SentenceTransformer(model_name, device=self.device)

        self._pe_ids: list[int] = []
        self._pe_numbers: list[str] = []
        self._pe_names: list[str] = []
        self._pe_agencies: list[str] = []
        self._pe_bas: list[str] = []
        self._corpus_embeddings: Optional[torch.Tensor] = None

        self._build_vector_space()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_vector_space(self) -> None:
        """Load PEs and compute the corpus embedding matrix."""
        stmt = select(
            ProgramElement.id,
            ProgramElement.pe_number,
            ProgramElement.program_name,
            ProgramElement.agency,
            ProgramElement.budget_activity,
        ).where(ProgramElement.is_classified == False)  # noqa: E712

        rows = self.session.execute(stmt).all()

        texts_to_encode: list[str] = []
        for pe_id, pe_num, name, agency, ba in rows:
            if not name:
                continue
            # Preprocess titles for better embedding quality
            processed = self.preprocessor.process(name)
            embed_text = processed.expanded or name

            self._pe_ids.append(pe_id)
            self._pe_numbers.append(pe_num or "")
            self._pe_names.append(name)
            self._pe_agencies.append(agency or "")
            self._pe_bas.append(ba or "")
            texts_to_encode.append(embed_text)

        logger.info(f"Encoding {len(texts_to_encode):,} PE titles ...")
        self._corpus_embeddings = self.model.encode(
            texts_to_encode,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=len(texts_to_encode) > 500,
        )
        logger.info("Semantic vector space ready.")

    # ── Match ─────────────────────────────────────────────────────────────────

    def find_top_matches(
        self,
        query: str,
        top_n: int = 5,
        threshold: float = 0.35,
    ) -> list[SemanticMatch]:
        """
        Find the top-N semantically similar PEs for a query.

        Args:
            query:     raw query string
            top_n:     number of candidates to return
            threshold: minimum cosine similarity to include (0.0-1.0)

        Returns:
            List of SemanticMatch sorted by score descending.
        """
        if self._corpus_embeddings is None or not query.strip():
            return []

        processed = self.preprocessor.process(query)
        embed_query = processed.expanded or processed.normalized or query

        query_embedding = self.model.encode(
            embed_query,
            convert_to_tensor=True,
            normalize_embeddings=True,
        )

        cos_scores = util.cos_sim(query_embedding, self._corpus_embeddings)[0]

        # Get top-N indices above threshold
        top_results = torch.topk(cos_scores, k=min(top_n, len(self._pe_ids)))

        matches: list[SemanticMatch] = []
        for score_tensor, idx_tensor in zip(top_results.values, top_results.indices):
            score = score_tensor.item()
            idx = idx_tensor.item()
            if score < threshold:
                break
            matches.append(SemanticMatch(
                pe_id=self._pe_ids[idx],
                pe_number=self._pe_numbers[idx],
                program_name=self._pe_names[idx],
                agency=self._pe_agencies[idx],
                budget_activity=self._pe_bas[idx],
                score=round(score, 4),
            ))

        return matches

    def find_best_match(
        self,
        query: str,
        threshold: float = 0.45,
    ) -> Optional[tuple[int, str, float]]:
        """
        Compatibility shim returning (pe_id, name, score) for the top match.
        Used by program_linker waterfall pipeline.
        """
        results = self.find_top_matches(query, top_n=1, threshold=threshold)
        if results:
            r = results[0]
            return (r.pe_id, r.program_name, r.score)
        return None
