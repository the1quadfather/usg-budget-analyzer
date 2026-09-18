"""Local passage retrieval over R-2 narrative text."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from storage.db import PENarrative


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
