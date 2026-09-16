"""Replace derived Program Element lineage rows in SQLite."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import config
from analysis.lineage import LineageEdge
from analysis.lineage import detect_ba_renumbering
from analysis.lineage import detect_narrative_transfers
from storage.db import PELineage, get_engine


DERIVED_METHODS = ("ba_renumber", "narrative")


def _model(edge: LineageEdge) -> PELineage:
    return PELineage(
        predecessor_pe=edge.predecessor_pe,
        predecessor_agency=edge.predecessor_agency,
        successor_pe=edge.successor_pe,
        successor_agency=edge.successor_agency,
        relation=edge.relation,
        first_fy_after=edge.first_fy_after,
        evidence_text=edge.evidence_text,
        evidence_source=edge.evidence_source,
        confidence=edge.confidence,
        method=edge.method,
        content_hash=edge.content_hash,
    )


def ingest_lineage(session: Session) -> dict[str, int]:
    """Replace rows produced by the two lineage detectors and commit them."""
    ba_edges = detect_ba_renumbering(session)
    narrative_edges = detect_narrative_transfers(session)
    edges = [*ba_edges, *narrative_edges]
    hashes = {edge.content_hash for edge in edges}
    if len(hashes) != len(edges):
        raise ValueError("lineage detectors produced duplicate content hashes")

    try:
        session.execute(
            delete(PELineage).where(PELineage.method.in_(DERIVED_METHODS))
        )
        session.add_all(_model(edge) for edge in edges)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "ba_renumber": len(ba_edges),
        "narrative": len(narrative_edges),
        "total": len(edges),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    args = parser.parse_args()

    database = args.database.resolve()
    engine = get_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        before = session.execute(
            select(func.count(PELineage.id))
        ).scalar_one()
        result = ingest_lineage(session)
        after = session.execute(
            select(func.count(PELineage.id))
        ).scalar_one()

    print(
        f"PE lineage rows: {before:,} before; replaced with "
        f"{result['ba_renumber']:,} ba_renumber + "
        f"{result['narrative']:,} narrative = {result['total']:,}; "
        f"{after:,} after."
    )


if __name__ == "__main__":
    main()
