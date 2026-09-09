"""Rebuild R-1 funding observations with submission-level provenance.

The legacy schema attached a source document to a canonical ProgramElement,
which loses the President's Budget vintage for every later observation. This
command reconstructs only ``funding_lines`` from the tracked parquet corpus;
all narrative, congressional, search, and AI tables are left untouched.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import polars as pl
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import config
from storage.db import (
    FundingLine,
    ProgramElement,
    SourceDocument,
    get_engine,
)


AMOUNT_FIELDS = (
    ("py_amount", -2, "PY Actual"),
    ("cy_amount", -1, "CY Request"),
    ("by_amount", 0, "BY Request"),
    ("py_mandatory_amount", -2, "PY Mandatory"),
    ("cy_mandatory_amount", -1, "CY Mandatory"),
    ("by_mandatory_amount", 0, "BY Mandatory"),
)


def _source_url(pb_cycle: int, extraction_method: str) -> str:
    if extraction_method == "xlsx":
        return config.COMPTROLLER_XLSX_URL.format(
            year=pb_cycle, stem=config.XLSX_EXHIBIT_STEMS["rdtee"]
        )
    return config.COMPTROLLER_BUDGET_URL.format(year=pb_cycle)


def _is_amount(value: object) -> bool:
    return value is not None and not (
        isinstance(value, float) and math.isnan(value)
    )


def rebuild_funding(database: Path, parquet: Path) -> dict[str, int]:
    """Replace R-1 funding rows atomically and return validation counts."""
    database = database.resolve()
    parquet = parquet.resolve()
    expected_root = config.PROCESSED_DIR.resolve()
    if database.parent != expected_root or parquet.parent != expected_root:
        raise ValueError(
            "Database and parquet must be direct children of data/processed"
        )
    if not parquet.exists():
        raise FileNotFoundError(parquet)

    frame = pl.read_parquet(parquet)
    required = {
        "fiscal_year", "component", "pe_number", "pe_title", "line_no",
        "act_code", "source_file", "extraction_method",
        *(field for field, _, _ in AMOUNT_FIELDS),
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Parquet is missing required fields: {sorted(missing)}")

    engine = get_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session, session.begin():
        documents = {
            row.filename: row
            for row in session.execute(select(SourceDocument)).scalars()
        }
        programs = {
            (row.pe_number, row.agency): row
            for row in session.execute(select(ProgramElement)).scalars()
        }

        document_ids: dict[str, int] = {}
        program_ids: dict[tuple[str, str], int] = {}
        for row in frame.iter_rows(named=True):
            filename = str(row["source_file"])
            pb_cycle = int(row["fiscal_year"])
            document = documents.get(filename)
            if document is None:
                document = SourceDocument(
                    filename=filename,
                    document_type="R1",
                    publication_year=pb_cycle,
                    source_url=_source_url(pb_cycle, row["extraction_method"]),
                )
                session.add(document)
                session.flush()
                documents[filename] = document
            elif not document.source_url:
                document.source_url = _source_url(
                    pb_cycle, row["extraction_method"]
                )
            document_ids[filename] = document.id

            key = (str(row["pe_number"]), str(row["component"]))
            program = programs.get(key)
            if program is None:
                try:
                    budget_activity = int(row["act_code"])
                except (TypeError, ValueError):
                    budget_activity = None
                program = ProgramElement(
                    source_document_id=document.id,
                    pe_number=key[0],
                    program_name=str(row["pe_title"]),
                    agency=key[1],
                    line_item_number=(
                        str(row["line_no"])
                        if row["line_no"] is not None else None
                    ),
                    budget_activity=budget_activity,
                )
                session.add(program)
                session.flush()
                programs[key] = program
            program_ids[key] = program.id

        new_lines: list[FundingLine] = []
        mandatory_count = 0
        for row in frame.iter_rows(named=True):
            pb_cycle = int(row["fiscal_year"])
            filename = str(row["source_file"])
            pe_key = (str(row["pe_number"]), str(row["component"]))
            for field, year_offset, funding_type in AMOUNT_FIELDS:
                value = row[field]
                if not _is_amount(value):
                    continue
                if funding_type.endswith("Mandatory"):
                    mandatory_count += 1
                new_lines.append(FundingLine(
                    program_element_id=program_ids[pe_key],
                    source_document_id=document_ids[filename],
                    pb_cycle=pb_cycle,
                    fiscal_year=pb_cycle + year_offset,
                    funding_type=funding_type,
                    amount_thousands=float(value),
                ))

        if not new_lines or mandatory_count == 0:
            raise ValueError("Refusing to replace funding data with an empty corpus")

        session.execute(delete(FundingLine))
        session.bulk_save_objects(new_lines)

    with Session(engine) as session:
        total = len(session.execute(select(FundingLine.id)).scalars().all())
        missing_provenance = len(session.execute(
            select(FundingLine.id).where(
                (FundingLine.source_document_id.is_(None))
                | (FundingLine.pb_cycle.is_(None))
            )
        ).scalars().all())
        stored_mandatory = len(session.execute(
            select(FundingLine.id).where(FundingLine.funding_type.like("% Mandatory"))
        ).scalars().all())

    if total != len(new_lines) or missing_provenance or stored_mandatory != mandatory_count:
        raise RuntimeError(
            "Funding rebuild validation failed: "
            f"total={total}/{len(new_lines)}, "
            f"missing_provenance={missing_provenance}, "
            f"mandatory={stored_mandatory}/{mandatory_count}"
        )
    return {
        "funding_lines": total,
        "mandatory_lines": stored_mandatory,
        "pb_cycles": frame["fiscal_year"].n_unique(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    parser.add_argument(
        "--parquet",
        type=Path,
        default=config.PROCESSED_DIR / "r1_all_years.parquet",
    )
    args = parser.parse_args()
    result = rebuild_funding(args.database, args.parquet)
    print(
        "Rebuilt {funding_lines:,} funding lines across {pb_cycles} PB cycles; "
        "{mandatory_lines:,} mandatory/reconciliation observations retained."
        .format(**result)
    )


if __name__ == "__main__":
    main()
