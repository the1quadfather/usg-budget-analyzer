"""Build the distributable gzip archive for the packaged SQLite database."""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import time
from pathlib import Path

import config


def build_archive(database: Path, archive: Path) -> tuple[int, int]:
    """Compress *database* to *archive* atomically after path validation."""
    database = database.resolve()
    archive = archive.resolve()
    processed = config.PROCESSED_DIR.resolve()
    if database.parent != processed or archive.parent != processed:
        raise ValueError("Database and archive must be direct children of data/processed")
    if not database.is_file():
        raise FileNotFoundError(database)
    if archive == database:
        raise ValueError("Archive path must differ from database path")

    temporary = archive.with_suffix(archive.suffix + ".tmp")
    with database.open("rb") as source, gzip.open(temporary, "wb", compresslevel=9) as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    # Indexers, antivirus, and git status can briefly hold the tracked archive
    # open on Windows. Keep the atomic replace contract, but tolerate a short
    # sharing violation instead of leaving release packaging half-finished.
    for attempt in range(10):
        try:
            os.replace(temporary, archive)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5 * (attempt + 1))
    return database.stat().st_size, archive.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    parser.add_argument(
        "--archive", type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db.gz",
    )
    args = parser.parse_args()
    raw_size, archive_size = build_archive(args.database, args.archive)
    print(
        f"Archived {raw_size:,} bytes to {archive_size:,} bytes "
        f"({archive_size / raw_size:.1%})."
    )


if __name__ == "__main__":
    main()
