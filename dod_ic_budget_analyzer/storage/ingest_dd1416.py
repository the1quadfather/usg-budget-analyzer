"""Ingest parsed DD 1416 RDT&E execution workbooks into SQLite."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import config
from acquisition.dd1416_downloader import download_reports, local_manifest
from parsing.dd1416_parser import DD1416ParseError, parse_workbook
from storage.db import PEExecution, ProgramElement, SourceDocument, get_engine


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_hash(file_hash: str, row: dict) -> str:
    identity = {**row, "file_hash": file_hash}
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def ingest_manifest(database: Path, manifest: list[dict]) -> dict[str, float | int]:
    """Replace rows from each manifest workbook and validate the PE join rate."""
    if not manifest:
        raise ValueError("No DD 1416 workbooks supplied")
    database = database.resolve()
    if database.parent != config.PROCESSED_DIR.resolve():
        raise ValueError("Database must be a direct child of data/processed")

    parsed_files: list[tuple[dict, str, list[dict]]] = []
    for item in manifest:
        path = Path(item["local_path"]).resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        file_hash = _sha256(path)
        try:
            rows = parse_workbook(path, item)
        except DD1416ParseError as exc:
            raise DD1416ParseError(f"{path.name}: {exc}") from exc
        parsed_files.append((item, file_hash, rows))

    parsed_keys = {
        (row["pe_number"].strip().upper(), row["agency"])
        for _, _, rows in parsed_files for row in rows
    }
    engine = get_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        known_keys = {
            (pe_number.strip().upper(), agency)
            for pe_number, agency in session.execute(
                select(ProgramElement.pe_number, ProgramElement.agency).distinct()
            )
        }
    join_rate = len(parsed_keys & known_keys) / len(parsed_keys)
    if join_rate < 0.90:
        raise ValueError(
            f"DD 1416 PE/component join rate {join_rate:.1%} is below the "
            "90% guardrail"
        )

    inserted = 0
    with Session(engine) as session, session.begin():
        documents = {
            doc.filename: doc
            for doc in session.execute(select(SourceDocument)).scalars()
        }
        for item, file_hash, rows in parsed_files:
            filename = item["filename"]
            document = documents.get(filename)
            retrieved = datetime.fromtimestamp(
                Path(item["local_path"]).stat().st_mtime, tz=timezone.utc
            ).replace(tzinfo=None)
            if document is None:
                document = SourceDocument(
                    filename=filename,
                    document_type="DD1416",
                    publication_year=int(item["report_date"][:4]),
                )
                session.add(document)
                session.flush()
                documents[filename] = document
            # Offline re-ingestion from older raw caches may not have the
            # original href. Never erase provenance already in the database.
            if item.get("url"):
                document.source_url = item["url"]
            document.retrieved_at = retrieved
            document.content_hash = file_hash

            session.execute(
                delete(PEExecution).where(
                    PEExecution.source_document_id == document.id
                )
            )
            for row in rows:
                payload = {k: v for k, v in row.items() if k != "source_row"}
                session.add(PEExecution(
                    source_document_id=document.id,
                    content_hash=_row_hash(file_hash, row),
                    **payload,
                ))
                inserted += 1

    with Session(engine) as session:
        total = session.execute(select(func.count(PEExecution.id))).scalar_one()
    return {
        "files": len(parsed_files),
        "inserted": inserted,
        "total": int(total),
        "join_rate": join_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--pause", type=float, default=3.0)
    parser.add_argument(
        "--database", type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    args = parser.parse_args()
    manifest = (
        download_reports(args.years, pause_seconds=args.pause)
        if args.download else local_manifest(years=args.years)
    )
    result = ingest_manifest(args.database, manifest)
    print(
        "Ingested {inserted:,} rows from {files} files; "
        "{total:,} total execution rows; PE/component join {join_rate:.1%}."
        .format(**result)
    )


if __name__ == "__main__":
    main()
