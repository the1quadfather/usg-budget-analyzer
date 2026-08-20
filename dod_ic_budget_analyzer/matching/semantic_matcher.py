"""
matching/semantic_matcher.py

Implements dense vector semantic matching using SentenceTransformers.
Projects DoD Program Elements into a vector space to capture conceptual
alignment beyond pure lexical overlap.

Robustness measures:
  - Corpus documents are agency-contextualized ("Defense Research Sciences
    [Army]") so identical titles under different agencies embed apart.
  - Embeddings are cached to disk keyed by a corpus+model hash - the app no
    longer re-encodes ~2,000 names on every process start.
  - Classified aggregate rows are excluded from the corpus.
  - Top-k retrieval so the linker can detect ambiguous matches.
"""

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch
from sentence_transformers import SentenceTransformer, util
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.db import ProgramElement

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class SemanticMatcher:
    """
    In-memory semantic matching engine utilizing dense embeddings for
    high-fidelity mapping of unstructured text to Program Elements.
    """

    def __init__(
        self,
        session: Session,
        model_name: str = "multi-qa-MiniLM-L6-cos-v1",
        cache_dir: Path | None = None,
    ):
        self.session = session
        self.model_name = model_name
        self.cache_dir = Path(cache_dir) if cache_dir else config.PROCESSED_DIR

        self.device = (
            "cuda" if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available()
            else "cpu"
        )
        logger.info(f"Initializing SemanticMatcher on device: {self.device}")

        self.model = SentenceTransformer(model_name, device=self.device)

        self._pe_ids: List[int] = []
        self._pe_meta: Dict[int, dict] = {}
        self._corpus_docs: List[str] = []
        self._corpus_embeddings: Optional[torch.Tensor] = None

        self._build_vector_space()

    # ── Corpus construction ───────────────────────────────────────────────────

    def _load_narratives(self) -> dict:
        """(pe_number, agency) -> R-2 mission description, when ingested."""
        try:
            from storage.db import PENarrative
            rows = self.session.execute(
                select(PENarrative.pe_number, PENarrative.agency,
                       PENarrative.description)
                .where(PENarrative.project_number == "")
                .order_by(PENarrative.fiscal_year)   # latest year wins below
            ).all()
            return {(r.pe_number, r.agency): r.description for r in rows}
        except Exception as e:
            logger.info(f"No R-2 narratives available for corpus ({e})")
            return {}

    def _load_corpus(self) -> None:
        narratives = self._load_narratives()
        stmt = select(
            ProgramElement.id,
            ProgramElement.program_name,
            ProgramElement.pe_number,
            ProgramElement.agency,
        )
        for pe_id, name, pe_number, agency in self.session.execute(stmt).all():
            if not name or not (pe_number or "").strip():
                continue  # classified aggregates / placeholder rows
            self._pe_ids.append(pe_id)
            self._pe_meta[pe_id] = {
                "name": name, "pe_number": pe_number, "agency": agency,
            }
            # Mission-description snippet sharpens the embedding well beyond
            # what a bare title carries (the model truncates long docs, so a
            # bounded prefix is all it can use anyway).
            snippet = narratives.get((pe_number, agency), "")[:400]
            doc = f"{name} [{agency}]"
            if snippet:
                doc = f"{doc}. {snippet}"
            self._corpus_docs.append(doc)

    def _cache_path(self) -> Path:
        safe_model = self.model_name.replace("/", "_")
        return self.cache_dir / f"semantic_embeddings_{safe_model}.pt"

    def _corpus_hash(self) -> str:
        payload = self.model_name + "\n" + "\n".join(self._corpus_docs)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_vector_space(self) -> None:
        """
        Loads the corpus, then restores embeddings from the disk cache when the
        corpus is unchanged; otherwise encodes and refreshes the cache.
        """
        self._load_corpus()
        if not self._corpus_docs:
            logger.warning("Semantic corpus is empty - matcher disabled.")
            return

        corpus_hash = self._corpus_hash()
        cache_path = self._cache_path()

        if cache_path.exists():
            try:
                cached = torch.load(cache_path, map_location=self.device)
                if (cached.get("hash") == corpus_hash
                        and cached["embeddings"].shape[0] == len(self._corpus_docs)):
                    self._corpus_embeddings = cached["embeddings"]
                    logger.info(
                        f"Loaded {len(self._corpus_docs)} cached embeddings "
                        f"from {cache_path.name}"
                    )
                    return
                logger.info("Embedding cache stale (corpus changed) - re-encoding.")
            except Exception as e:
                logger.warning(f"Embedding cache unreadable ({e}) - re-encoding.")

        logger.info(f"Encoding {len(self._corpus_docs)} Program Elements...")
        self._corpus_embeddings = self.model.encode(
            self._corpus_docs,
            convert_to_tensor=True,
            normalize_embeddings=True,
        )
        try:
            torch.save(
                {"hash": corpus_hash, "embeddings": self._corpus_embeddings.cpu()},
                cache_path,
            )
            logger.info(f"Embedding cache written -> {cache_path}")
        except Exception as e:
            logger.warning(f"Could not write embedding cache: {e}")

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def find_matches(
        self, query: str, limit: int = 5, threshold: float = 0.40
    ) -> List[dict]:
        """
        Top-k semantic candidates above the cosine-similarity threshold.
        """
        if self._corpus_embeddings is None or not query.strip():
            return []

        query_embedding = self.model.encode(
            query, convert_to_tensor=True, normalize_embeddings=True
        )
        cos_scores = util.cos_sim(query_embedding, self._corpus_embeddings)[0]

        k = min(limit, cos_scores.shape[0])
        top_scores, top_idx = torch.topk(cos_scores, k=k)

        candidates = []
        for score, idx in zip(top_scores.tolist(), top_idx.tolist()):
            if score < threshold:
                continue
            pe_id = self._pe_ids[idx]
            meta = self._pe_meta[pe_id]
            candidates.append({
                "pe_id": pe_id,
                "name": meta["name"],
                "pe_number": meta["pe_number"],
                "agency": meta["agency"],
                "score": round(score, 4),
                "strategy": "SEMANTIC",
            })
        return candidates

    def find_best_match(
        self, query: str, threshold: float = 0.50
    ) -> Optional[Tuple[int, str, float]]:
        """
        Backward-compatible single-best lookup.
        Returns (pe_id, canonical_name, cosine_score) or None.
        """
        matches = self.find_matches(query, limit=1, threshold=threshold)
        if matches:
            m = matches[0]
            return (m["pe_id"], m["name"], m["score"])
        return None
