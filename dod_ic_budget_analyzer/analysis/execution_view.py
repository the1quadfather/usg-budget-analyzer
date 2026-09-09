"""Read-side helpers for DD 1416 request-to-net execution data."""

from __future__ import annotations

import polars as pl
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from storage.db import PEExecution


VALUE_COLUMNS = (
    "request_k", "enacted_k", "statutory_adj_k", "suppl_resc_seq_k",
    "other_adj_k", "above_threshold_reprog_k",
    "below_threshold_reprog_k", "net_k",
)


def coverage_note() -> str:
    return (
        "DD 1416 reports budget-authority status, not obligations or outlays. "
        "Missing years are outside the ingested execution corpus, not zero."
    )


class ExecutionView:
    def __init__(self, session: Session):
        self.session = session

    def fiscal_year_bounds(self) -> tuple[int | None, int | None]:
        first, last = self.session.execute(
            select(func.min(PEExecution.fy_start), func.max(PEExecution.fy_start))
        ).one()
        return (
            int(first) if first is not None else None,
            int(last) if last is not None else None,
        )

    def latest_program_series(
        self,
        pe_numbers: list[str],
        agencies: list[str] | None = None,
    ) -> pl.DataFrame:
        if not pe_numbers:
            return pl.DataFrame()
        stmt = select(
            PEExecution.pe_number,
            PEExecution.agency,
            PEExecution.fy_start,
            PEExecution.fy_end,
            PEExecution.report_date,
            *[getattr(PEExecution, column) for column in VALUE_COLUMNS],
        )
        if agencies and len(agencies) == len(pe_numbers):
            stmt = stmt.where(
                tuple_(PEExecution.pe_number, PEExecution.agency).in_(
                    list(zip(pe_numbers, agencies))
                )
            )
        else:
            stmt = stmt.where(PEExecution.pe_number.in_(pe_numbers))
            if agencies:
                stmt = stmt.where(PEExecution.agency.in_(agencies))
        rows = self.session.execute(stmt).all()
        if not rows:
            return pl.DataFrame()

        schema = {
            "pe_number": pl.Utf8,
            "agency": pl.Utf8,
            "fy_start": pl.Int64,
            "fy_end": pl.Int64,
            "report_date": pl.Utf8,
            **{column: pl.Float64 for column in VALUE_COLUMNS},
        }
        frame = pl.DataFrame(rows, schema=schema, orient="row")
        # Keep every line from the most recent quarter for each PE/FY pair,
        # then aggregate selected PEs. This avoids mixing quarters.
        latest_dates = frame.group_by(
            ["pe_number", "agency", "fy_start", "fy_end"]
        ).agg(pl.col("report_date").max().alias("latest_report_date"))
        latest = frame.join(
            latest_dates,
            on=["pe_number", "agency", "fy_start", "fy_end"],
        ).filter(pl.col("report_date") == pl.col("latest_report_date"))
        return (
            latest.group_by(["fy_start", "fy_end", "report_date"])
            .agg([pl.col(column).sum().alias(column) for column in VALUE_COLUMNS])
            .sort("fy_start")
        )
