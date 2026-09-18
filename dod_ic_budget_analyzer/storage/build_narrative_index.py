"""Build the tracked local passage index for R-2 narrative retrieval."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter

from sqlalchemy.orm import Session


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config
from analysis.narrative_qa import INDEX_PATH, MODEL_NAME, index_rows
from storage.db import get_engine


def _corpus_hash(rows: list[tuple[str, str, int, str, str, str]]) -> str:
    payload = "\n".join(
        "\t".join(str(field) for field in row)
        for row in rows
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("limit must be positive")
    return parsed


def build_index(
    database: Path,
    output: Path,
    *,
    limit: int | None = None,
) -> tuple[int, float, float]:
    """Build an index and return passage count, mean length, and seconds."""
    from sentence_transformers import SentenceTransformer
    import torch

    started = perf_counter()
    engine = get_engine(f"sqlite:///{database.resolve().as_posix()}")
    with Session(engine) as session:
        rows = index_rows(session)
    engine.dispose()
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError("narrative corpus is empty")

    model = SentenceTransformer(MODEL_NAME, local_files_only=True)
    embeddings = model.encode(
        [row[-1] for row in rows],
        batch_size=64,
        convert_to_tensor=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).detach().cpu().to(torch.float16).contiguous()
    index = {
        "model": MODEL_NAME,
        "corpus_hash": _corpus_hash(rows),
        "embeddings": embeddings,
        "pe_number": [row[0] for row in rows],
        "agency": [row[1] for row in rows],
        "fiscal_year": [row[2] for row in rows],
        "project_number": [row[3] for row in rows],
        "source_file": [row[4] for row in rows],
        "text": [row[5] for row in rows],
    }

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    os.close(handle)
    Path(temporary_name).unlink()
    try:
        torch.save(index, temporary_name)
        Path(temporary_name).replace(output)
    finally:
        Path(temporary_name).unlink(missing_ok=True)

    elapsed = perf_counter() - started
    mean_length = sum(len(row[-1]) for row in rows) / len(rows)
    return len(rows), mean_length, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    parser.add_argument("--output", type=Path, default=INDEX_PATH)
    parser.add_argument("--limit", type=_positive_int)
    args = parser.parse_args()

    count, mean_length, elapsed = build_index(
        args.database,
        args.output,
        limit=args.limit,
    )
    print(
        f"Built {count:,} passages (mean {mean_length:,.1f} characters) "
        f"in {elapsed:,.1f} seconds -> {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
