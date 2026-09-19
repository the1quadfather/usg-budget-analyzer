"""Table export and source-provenance helpers."""

from __future__ import annotations

from io import BytesIO, StringIO
from typing import Iterable

import pandas as pd
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from storage.db import (
    FundingLine,
    PEExecution,
    ProcurementLine,
    ProgramElement,
    SourceDocument,
)


def funding_sources(
    session: Session,
    *,
    pe_numbers: Iterable[str] | None = None,
    agencies: Iterable[str] | None = None,
    fiscal_years: tuple[int, int] | None = None,
) -> list[dict]:
    """Return distinct source records supporting a funding selection."""
    stmt = (
        select(
            SourceDocument.filename,
            SourceDocument.document_type,
            SourceDocument.publication_year,
            SourceDocument.source_url,
            SourceDocument.retrieved_at,
            SourceDocument.processed_date,
        )
        .join(FundingLine, FundingLine.source_document_id == SourceDocument.id)
        .join(ProgramElement, ProgramElement.id == FundingLine.program_element_id)
        .distinct()
        .order_by(SourceDocument.publication_year, SourceDocument.filename)
    )
    if pe_numbers:
        stmt = stmt.where(ProgramElement.pe_number.in_(list(pe_numbers)))
    if agencies:
        stmt = stmt.where(ProgramElement.agency.in_(list(agencies)))
    if fiscal_years:
        stmt = stmt.where(FundingLine.fiscal_year.between(*fiscal_years))

    return [
        {
            "filename": row.filename,
            "document_type": row.document_type,
            "publication_year": row.publication_year,
            "source_url": row.source_url,
            "retrieved_at": row.retrieved_at,
            "processed_date": row.processed_date,
        }
        for row in session.execute(stmt)
    ]


def execution_sources(
    session: Session,
    *,
    pe_numbers: Iterable[str] | None = None,
    agencies: Iterable[str] | None = None,
) -> list[dict]:
    """Return official DD 1416 workbooks supporting an execution view."""
    stmt = (
        select(
            SourceDocument.filename,
            SourceDocument.document_type,
            SourceDocument.publication_year,
            SourceDocument.source_url,
            SourceDocument.retrieved_at,
            SourceDocument.processed_date,
        )
        .join(PEExecution, PEExecution.source_document_id == SourceDocument.id)
        .distinct()
        .order_by(SourceDocument.publication_year, SourceDocument.filename)
    )
    pe_values = list(pe_numbers or [])
    agency_values = list(agencies or [])
    if pe_values and agency_values and len(pe_values) == len(agency_values):
        stmt = stmt.where(
            tuple_(PEExecution.pe_number, PEExecution.agency).in_(
                list(zip(pe_values, agency_values))
            )
        )
    else:
        if pe_values:
            stmt = stmt.where(PEExecution.pe_number.in_(pe_values))
        if agency_values:
            stmt = stmt.where(PEExecution.agency.in_(agency_values))
    return [
        {
            "filename": row.filename,
            "document_type": row.document_type,
            "publication_year": row.publication_year,
            "source_url": row.source_url,
            "retrieved_at": row.retrieved_at,
            "processed_date": row.processed_date,
        }
        for row in session.execute(stmt)
    ]


def procurement_sources(
    session: Session,
    *,
    blis: Iterable[str] | None = None,
    appropriations: Iterable[str] | None = None,
) -> list[dict]:
    """Return official P-1 workbooks supporting procurement candidates."""
    stmt = (
        select(
            SourceDocument.filename,
            SourceDocument.document_type,
            SourceDocument.publication_year,
            SourceDocument.source_url,
            SourceDocument.retrieved_at,
            SourceDocument.processed_date,
        )
        .join(
            ProcurementLine,
            ProcurementLine.source_document_id == SourceDocument.id,
        )
        .distinct()
        .order_by(SourceDocument.publication_year, SourceDocument.filename)
    )
    bli_values = list(blis or [])
    appropriation_values = list(appropriations or [])
    if bli_values:
        stmt = stmt.where(ProcurementLine.bli.in_(bli_values))
    if appropriation_values:
        stmt = stmt.where(
            ProcurementLine.appropriation.in_(appropriation_values)
        )
    return [
        {
            "filename": row.filename,
            "document_type": row.document_type,
            "publication_year": row.publication_year,
            "source_url": row.source_url,
            "retrieved_at": row.retrieved_at,
            "processed_date": row.processed_date,
        }
        for row in session.execute(stmt)
    ]


def source_summary(sources: list[dict], *, max_items: int = 4) -> str:
    """Compact, honest text for a figure's provenance caption."""
    if not sources:
        return "Source provenance is not recorded for this result."
    labels = []
    for source in sources[:max_items]:
        year = source.get("publication_year")
        kind = source.get("document_type", "source")
        vintage = f"PB{year}" if kind == "R1" else f"{kind}, {year}"
        labels.append(f"{source['filename']} ({vintage})")
    if len(sources) > max_items:
        labels.append(f"and {len(sources) - max_items} more")
    return "Sources: " + "; ".join(labels) + "."


def _provenance_frame(sources: list[dict]) -> pd.DataFrame:
    if not sources:
        return pd.DataFrame([{
            "filename": "Not recorded",
            "document_type": "",
            "publication_year": "",
            "source_url": "",
            "retrieved_at": "",
            "processed_date": "",
        }])
    frame = pd.DataFrame(sources)
    for column in ("retrieved_at", "processed_date"):
        if column in frame:
            frame[column] = frame[column].apply(
                lambda value: value.isoformat() if pd.notna(value) else ""
            )
    return frame


def csv_with_provenance(data: pd.DataFrame, sources: list[dict]) -> bytes:
    """Encode a CSV with comment-prefixed source metadata."""
    stream = StringIO()
    for row in _provenance_frame(sources).to_dict(orient="records"):
        stream.write(
            "# Source: {filename}; PB{publication_year}; {source_url}\n".format(
                **row
            )
        )
    data.to_csv(stream, index=False)
    return stream.getvalue().encode("utf-8-sig")


def xlsx_with_provenance(data: pd.DataFrame, sources: list[dict]) -> bytes:
    """Encode data and provenance as separate workbook sheets."""
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        data.to_excel(writer, sheet_name="Data", index=False)
        _provenance_frame(sources).to_excel(
            writer, sheet_name="Provenance", index=False
        )
    return stream.getvalue()
