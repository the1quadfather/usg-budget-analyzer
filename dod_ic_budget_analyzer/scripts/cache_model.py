"""Download the embedding model before starting offline tests or a demo."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.narrative_qa import MODEL_NAME, _load_model


def main() -> None:
    from sentence_transformers import SentenceTransformer

    # This is the only network-enabled step. Runtime retrieval deliberately
    # uses local_files_only=True, including when the first visitor asks a question.
    SentenceTransformer(MODEL_NAME, device="cpu")
    model = _load_model()
    embedding = model.encode("Budget Explorer model readiness check")
    if embedding.shape != (384,):
        raise RuntimeError(f"Unexpected embedding shape: {embedding.shape}")
    print(f"Cached {MODEL_NAME}; offline encoding verified (384 dimensions).")


if __name__ == "__main__":
    main()
