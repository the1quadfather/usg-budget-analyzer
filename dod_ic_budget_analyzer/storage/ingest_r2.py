"""
storage/ingest_r2.py

Loads R-2 jbook narratives and accomplishments (from parsing/r2_parser.py)
into the pe_narratives / pe_accomplishments tables. Files already ingested
(by source_file) are skipped, so re-runs are safe.

Usage:
    python storage/ingest_r2.py --dir data/raw/comptroller/2027/rdtee/jbooks
"""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import PEAccomplishment, PENarrative

logger = logging.getLogger(__name__)


class R2Ingestor:
    def __init__(self, session: Session):
        self.session = session

    def _ingested_files(self) -> set[str]:
        rows = self.session.execute(select(PENarrative.source_file).distinct()).all()
        return {r.source_file for r in rows}

    def ingest_frames(self, narratives, accomplishments) -> dict[str, int]:
        """Insert parsed frames, skipping already-ingested source files."""
        done = self._ingested_files()
        counts = {"narratives": 0, "accomplishments": 0, "skipped_files": 0}

        if not narratives.empty:
            new_files = set(narratives["source_file"].unique()) - done
            counts["skipped_files"] = narratives["source_file"].nunique() - len(new_files)

            for df, model, key in (
                (narratives, PENarrative, "narratives"),
                (accomplishments, PEAccomplishment, "accomplishments"),
            ):
                if df.empty:
                    continue
                subset = df[df["source_file"].isin(new_files)]
                objs = [
                    model(**{k: (None if v != v else v)  # NaN -> None
                             for k, v in row.items()})
                    for row in subset.to_dict("records")
                ]
                if objs:
                    self.session.bulk_save_objects(objs)
                    counts[key] = len(objs)

            self.session.commit()

        logger.info(
            f"Ingested {counts['narratives']} narratives, "
            f"{counts['accomplishments']} accomplishments "
            f"({counts['skipped_files']} file(s) already present)"
        )
        return counts


if __name__ == "__main__":
    import argparse

    from parsing.r2_parser import R2Parser
    from storage.db import get_engine, get_session_factory, init_db

    logging.basicConfig(level="INFO",
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Ingest R-2 jbook XML into SQLite.")
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument(
        "--db",
        default=f"sqlite:///{(Path(__file__).parent.parent / 'data' / 'processed' / 'usg_budgets.db').as_posix()}",
    )
    args = ap.parse_args()

    frames = R2Parser().parse_directory(args.dir)
    engine = get_engine(args.db)
    init_db(engine)
    with get_session_factory(engine)() as session:
        R2Ingestor(session).ingest_frames(
            frames["narratives"], frames["accomplishments"]
        )
