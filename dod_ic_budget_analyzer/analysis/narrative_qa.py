"""Local passage retrieval over R-2 narrative text."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from storage.db import PENarrative

if TYPE_CHECKING:
    from analysis.oss_enricher import EnrichmentResult


MODEL_NAME = "multi-qa-MiniLM-L6-cos-v1"
INDEX_PATH = (
    config.PROCESSED_DIR
    / "narrative_index_multi-qa-MiniLM-L6-cos-v1.pt"
)
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Passage:
    pe_number: str
    agency: str
    fiscal_year: int
    project_number: str | None
    source_file: str
    text: str
    score: float


@dataclass(frozen=True)
class Citation:
    pe_number: str
    agency: str
    fiscal_year: int
    source_file: str
    quote: str


@dataclass(frozen=True)
class CitedAnswer:
    sentences: tuple[tuple[str, tuple[Citation, ...]], ...]
    refused: bool
    reason: str | None

    def to_dict(self) -> dict:
        return {
            "sentences": [
                {
                    "text": text,
                    "citations": [
                        {
                            "pe_number": citation.pe_number,
                            "agency": citation.agency,
                            "fiscal_year": citation.fiscal_year,
                            "source_file": citation.source_file,
                            "quote": citation.quote,
                        }
                        for citation in citations
                    ],
                }
                for text, citations in self.sentences
            ],
            "refused": self.refused,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "CitedAnswer":
        return cls(
            sentences=tuple(
                (
                    sentence["text"],
                    tuple(
                        Citation(**citation)
                        for citation in sentence["citations"]
                    ),
                )
                for sentence in payload["sentences"]
            ),
            refused=payload["refused"],
            reason=payload.get("reason"),
        )


def normalize_ws(text: str) -> str:
    """Collapse whitespace runs to one space and remove edge whitespace."""
    return " ".join(text.split())


def validate_answer(
    raw: dict,
    passages: Sequence[Passage],
) -> CitedAnswer:
    """Resolve and enforce passage citations in a model-produced answer."""
    if raw.get("refused"):
        return CitedAnswer(
            (),
            True,
            raw.get("reason") or "model_refused",
        )

    raw_sentences = raw.get("sentences") or []
    if not raw_sentences:
        return CitedAnswer((), True, "empty")

    sentences = []
    for sentence in raw_sentences:
        citations = []
        for raw_citation in sentence.get("citations", []):
            position = raw_citation.get("passage")
            quote = raw_citation.get("quote")
            if type(position) is not int or not isinstance(quote, str):
                continue
            if position < 1 or position > len(passages):
                continue
            normalized_quote = normalize_ws(quote)
            passage = passages[position - 1]
            if len(normalized_quote) < 20:
                continue
            if normalized_quote not in normalize_ws(passage.text):
                continue
            citations.append(Citation(
                pe_number=passage.pe_number,
                agency=passage.agency,
                fiscal_year=passage.fiscal_year,
                source_file=passage.source_file,
                quote=normalized_quote,
            ))
        if not citations:
            return CitedAnswer((), True, "uncited")
        sentences.append((sentence["text"], tuple(citations)))

    return CitedAnswer(tuple(sentences), False, None)


def answer(
    question: str,
    passages: Sequence[Passage],
    *,
    user_id: str,
    allow_fresh: bool,
    credits: int | None = None,
    force: bool = False,
    enricher=None,
) -> EnrichmentResult:
    """Answer from retrieved passages through the governed AI path."""
    from analysis import oss_enricher

    if not question.strip() or not passages:
        return oss_enricher.EnrichmentResult(
            payload=None,
            blocked=True,
            message="Nothing to answer from.",
        )
    if enricher is None:
        if not oss_enricher.available():
            return oss_enricher.EnrichmentResult(
                payload=None,
                blocked=True,
                message=oss_enricher.status()[1],
            )
        enricher = oss_enricher.GeminiEnricher()
    return enricher.narrative_answer(
        question,
        passages,
        user_id=user_id,
        allow_fresh=allow_fresh,
        credits=credits,
        force=force,
    )


def chunk_text(text: str, limit: int = 1500) -> list[str]:
    """Pack sentences into bounded chunks without splitting a sentence."""
    stripped = text.strip()
    if not stripped:
        return []

    chunks = []
    current = ""
    for sentence in SENTENCE_BOUNDARY_RE.split(stripped):
        if current and len(current) + 1 + len(sentence) <= limit:
            current = f"{current} {sentence}"
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def index_rows(
    session: Session,
) -> list[tuple[str, str, int, str, str, str]]:
    """Return deterministic, deduplicated narrative passage rows."""
    statement = select(
        PENarrative.pe_number,
        PENarrative.agency,
        PENarrative.fiscal_year,
        PENarrative.project_number,
        PENarrative.source_file,
        PENarrative.description,
    ).order_by(PENarrative.fiscal_year.desc(), PENarrative.id)

    rows = []
    seen = set()
    for pe_number, agency, fiscal_year, project, source, description in (
        session.execute(statement)
    ):
        for text in chunk_text(description):
            key = (pe_number, agency, text)
            if key in seen:
                continue
            seen.add(key)
            rows.append((
                pe_number,
                agency,
                fiscal_year,
                project or "",
                source,
                text,
            ))
    return rows


@lru_cache(maxsize=1)
def _load_index() -> dict:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"Narrative passage index is missing at {INDEX_PATH}. "
            "Build it with `python -m storage.build_narrative_index`."
        )
    import torch

    return torch.load(INDEX_PATH, map_location="cpu", weights_only=True)


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, local_files_only=True)


def retrieve(question: str, *, k: int = 8) -> list[Passage]:
    """Return the highest-scoring local narrative passages for a question."""
    question = question.strip()
    if not question or k <= 0:
        return []

    index = _load_index()
    import torch

    model = _load_model()
    query = model.encode(
        question,
        convert_to_tensor=True,
        normalize_embeddings=True,
    ).to(device="cpu", dtype=torch.float32)
    scores = index["embeddings"].to(dtype=torch.float32) @ query
    count = min(k, scores.shape[0])
    top_scores, top_indices = torch.topk(scores, k=count)

    passages = []
    for score, position in zip(top_scores.tolist(), top_indices.tolist()):
        project = index["project_number"][position]
        passages.append(Passage(
            pe_number=index["pe_number"][position],
            agency=index["agency"][position],
            fiscal_year=index["fiscal_year"][position],
            project_number=project or None,
            source_file=index["source_file"][position],
            text=index["text"][position],
            score=float(score),
        ))
    return passages


def index_status() -> dict:
    """Return identity and size metadata for the loaded passage index."""
    index = _load_index()
    return {
        "model": index["model"],
        "passages": len(index["text"]),
        "corpus_hash": index["corpus_hash"],
        "path": str(INDEX_PATH.resolve()),
    }
