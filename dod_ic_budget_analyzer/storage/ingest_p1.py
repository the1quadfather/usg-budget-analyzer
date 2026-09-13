"""Ingest official Comptroller P-1 workbooks into SQLite."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import config
from acquisition.comptroller_scraper import XlsxExhibitDownloader
from parsing.xlsx_ingest import P1Record, parse_p1
from storage.db import ProcurementLine, SourceDocument, get_engine


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedWorkbook:
    pb_cycle: int
    path: Path
    filename: str
    source_url: str
    retrieved_at: datetime
    file_hash: str
    records: tuple[P1Record, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_url(pb_cycle: int) -> str:
    return config.COMPTROLLER_XLSX_URL.format(
        year=pb_cycle,
        stem=config.XLSX_EXHIBIT_STEMS["procurement"],
    )


def _manifest_item(pb_cycle: int, path: Path) -> dict:
    return {
        "pb_cycle": pb_cycle,
        "local_path": path,
        "filename": path.name,
        "url": _source_url(pb_cycle),
    }


def local_manifest(years: list[int]) -> list[dict]:
    """Return the canonical local P-1 workbook manifest for *years*."""
    return [
        _manifest_item(
            year,
            config.COMPTROLLER_DIR
            / str(year)
            / "procurement"
            / f"fy{year}_p1.xlsx",
        )
        for year in years
    ]


def download_manifest(years: list[int]) -> list[dict]:
    """Download missing P-1 workbooks and return their canonical manifest."""
    downloader = XlsxExhibitDownloader()
    manifest = []
    try:
        for year in years:
            path = downloader.download(year, "procurement")
            if path is None:
                expected = (
                    config.COMPTROLLER_DIR
                    / str(year)
                    / "procurement"
                    / f"fy{year}_p1.xlsx"
                )
                raise FileNotFoundError(expected)
            manifest.append(_manifest_item(year, path))
    finally:
        downloader.client.close()
    return manifest


def _pre_source_key(record: P1Record, pb_cycle: int) -> tuple:
    return (
        record.bli,
        record.agency,
        record.appropriation,
        record.budget_activity,
        record.line_number,
        record.cost_type,
        record.cost_type_title,
        record.fiscal_year,
        record.funding_type,
        pb_cycle,
    )


def _validated_add_records(
    path: Path, pb_cycle: int, records: tuple[P1Record, ...]
) -> tuple[P1Record, ...]:
    add_records = tuple(
        record for record in records if record.add_non_add == "Add"
    )
    if not add_records:
        raise ValueError(f"{path.name}: no Add P-1 records parsed")

    seen = set()
    for record in add_records:
        if record.budget_activity is None:
            raise ValueError(
                f"{path.name}: missing Budget Activity for {record.bli}"
            )
        for field, value in (
            ("amount_thousands", record.amount_thousands),
            ("quantity", record.quantity),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(
                    f"{path.name}: non-finite {field} for {record.bli}"
                )
        key = _pre_source_key(record, pb_cycle)
        if key in seen:
            raise ValueError(
                f"{path.name}: duplicate P-1 row identity {key!r}"
            )
        seen.add(key)
    return add_records


def _parse_manifest(manifest: list[dict]) -> tuple[_ParsedWorkbook, ...]:
    if not manifest:
        raise ValueError("No P-1 workbooks supplied")

    parsed_files = []
    filenames = set()
    for item in manifest:
        pb_cycle = int(item["pb_cycle"])
        path = Path(item["local_path"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        filename = str(item.get("filename") or path.name)
        if filename in filenames:
            raise ValueError(f"Duplicate P-1 source document: {filename}")
        filenames.add(filename)

        file_hash = _sha256(path)
        all_records = tuple(parse_p1(path, pb_cycle=pb_cycle))
        add_records = _validated_add_records(
            path, pb_cycle, all_records
        )
        retrieved_at = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).replace(tzinfo=None)
        parsed_files.append(_ParsedWorkbook(
            pb_cycle=pb_cycle,
            path=path,
            filename=filename,
            source_url=str(item.get("url") or _source_url(pb_cycle)),
            retrieved_at=retrieved_at,
            file_hash=file_hash,
            records=add_records,
        ))
    return tuple(parsed_files)


def _row_hash(
    record: P1Record, pb_cycle: int, source_document_id: int
) -> str:
    values = (
        record.bli,
        record.agency,
        record.appropriation,
        record.budget_activity,
        record.line_number,
        record.cost_type,
        record.cost_type_title,
        record.fiscal_year,
        record.funding_type,
        pb_cycle,
        source_document_id,
        record.amount_thousands,
        record.quantity,
    )
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _procurement_line(
    record: P1Record, pb_cycle: int, source_document_id: int
) -> ProcurementLine:
    return ProcurementLine(
        source_document_id=source_document_id,
        bli=record.bli,
        line_item_title=record.line_item_title,
        agency=record.agency,
        appropriation=record.appropriation,
        budget_activity=record.budget_activity,
        line_number=record.line_number,
        bsa=record.bsa,
        bsa_title=record.bsa_title,
        cost_type=record.cost_type,
        cost_type_title=record.cost_type_title,
        fiscal_year=record.fiscal_year,
        funding_type=record.funding_type,
        amount_thousands=record.amount_thousands,
        quantity=record.quantity,
        pb_cycle=pb_cycle,
        content_hash=_row_hash(record, pb_cycle, source_document_id),
    )


def ingest_manifest(database: Path, manifest: list[dict]) -> dict[str, int]:
    """Parse all P-1 workbooks, then ingest them in one transaction."""
    database = database.resolve()
    if database.parent != config.PROCESSED_DIR.resolve():
        raise ValueError("Database must be a direct child of data/processed")

    parsed_files = _parse_manifest(manifest)
    engine = get_engine(f"sqlite:///{database.as_posix()}")
    inserted = 0
    skipped_files = 0

    with Session(engine) as session, session.begin():
        documents = {
            document.filename: document
            for document in session.execute(
                select(SourceDocument).where(
                    SourceDocument.filename.in_(
                        item.filename for item in parsed_files
                    )
                )
            ).scalars()
        }
        for item in parsed_files:
            document = documents.get(item.filename)
            if document is not None and document.document_type != "P1":
                raise ValueError(
                    f"Source document {item.filename} is already recorded "
                    f"as {document.document_type}, not P1"
                )
            if document is not None and document.content_hash == item.file_hash:
                document.source_url = item.source_url
                document.retrieved_at = item.retrieved_at
                document.publication_year = item.pb_cycle
                skipped_files += 1
                continue

            if document is None:
                document = SourceDocument(
                    filename=item.filename,
                    document_type="P1",
                    publication_year=item.pb_cycle,
                )
                session.add(document)
                session.flush()
                documents[item.filename] = document
            else:
                session.execute(
                    delete(ProcurementLine).where(
                        ProcurementLine.source_document_id == document.id
                    )
                )

            document.source_url = item.source_url
            document.retrieved_at = item.retrieved_at
            document.content_hash = item.file_hash
            session.add_all(
                _procurement_line(record, item.pb_cycle, document.id)
                for record in item.records
            )
            inserted += len(item.records)

    with Session(engine) as session:
        total = session.execute(
            select(func.count(ProcurementLine.id))
        ).scalar_one()
        source_documents = session.execute(
            select(func.count(SourceDocument.id))
        ).scalar_one()
    return {
        "files": len(parsed_files),
        "inserted": inserted,
        "skipped_files": skipped_files,
        "total": int(total),
        "source_documents": int(source_documents),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--database", type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    manifest = (
        download_manifest(args.years)
        if args.download else local_manifest(args.years)
    )
    result = ingest_manifest(args.database, manifest)
    print(
        "Inserted {inserted:,} procurement rows from {files} P-1 files; "
        "{skipped_files} unchanged files skipped; {total:,} total "
        "procurement rows; {source_documents:,} source documents."
        .format(**result)
    )


if __name__ == "__main__":
    main()
