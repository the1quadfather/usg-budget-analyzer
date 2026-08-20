"""
analysis/trend_tracker.py

Calculates macro-level (agency) and granular (program element) funding trends 
across DoD/IC agencies over multiple fiscal years. Utilizes Polars for 
high-speed pivoting and Compound Annual Growth Rate (CAGR) calculations.
"""

import logging
import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from storage.db import FundingLine, ProgramElement

logger = logging.getLogger(__name__)

# A fiscal year appears in up to three publications: as BY Request in PB(Y),
# CY Request in PB(Y+1), and PY Actual in PB(Y+2). Summing them double- or
# triple-counts the year, so trends pick ONE per year by reliability.
FUNDING_TYPE_PRIORITY = {"PY Actual": 0, "CY Request": 1, "BY Request": 2}


class TrendTracker:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _prefer_funding_type(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
        """Keep one record per (keys, fiscal_year): actuals beat enacted/CY
        figures, which beat budget-year requests."""
        return (
            df.with_columns(
                pl.col("funding_type")
                .replace_strict(FUNDING_TYPE_PRIORITY, default=9)
                .alias("_prio")
            )
            .sort("_prio")
            .group_by(keys + ["fiscal_year"], maintain_order=True)
            .first()
            .drop("_prio", "funding_type")
        )

    def _sort_and_format_trends(self, df_wide: pl.DataFrame, start_year: int, end_year: int) -> pl.DataFrame:
        """Helper function to sort chronologically, calculate metrics, and add Sparkline placeholder."""
        str_start = str(start_year)
        str_end = str(end_year)
        
        # Defensively ensure boundary years exist
        for year in [str_start, str_end]:
            if year not in df_wide.columns:
                df_wide = df_wide.with_columns(pl.lit(0.0).alias(year))

        # Separate and sort columns chronologically
        id_cols = [c for c in df_wide.columns if not c.isdigit()]
        year_cols = sorted([c for c in df_wide.columns if c.isdigit()], key=int)
        
        # Reorder DataFrame
        df_sorted = df_wide.select(id_cols + year_cols)
        
        num_years = end_year - start_year
        
        # Calculate Delta, CAGR, and add empty Trend column for Excel Sparklines
        df_trends = df_sorted.with_columns(
            total_delta_pct=pl.when(pl.col(str_start) > 0)
            .then(((pl.col(str_end) - pl.col(str_start)) / pl.col(str_start)) * 100)
            .otherwise(0.0),
            
            cagr_pct=pl.when((pl.col(str_start) > 0) & (pl.col(str_end) > 0) & (num_years > 0))
            .then(((pl.col(str_end) / pl.col(str_start)) ** (1 / num_years) - 1) * 100)
            .otherwise(0.0),
            
            Trend=pl.lit("") # Placeholder for xlsxwriter sparklines
        )

        return df_trends.sort(str_end, descending=True)

    def get_agency_trends(self, start_year: int, end_year: int) -> pl.DataFrame:
        try:
            stmt = (
                select(
                    ProgramElement.agency,
                    FundingLine.fiscal_year,
                    FundingLine.funding_type,
                    func.sum(FundingLine.amount_thousands).label("total_funding")
                )
                .join(FundingLine, ProgramElement.id == FundingLine.program_element_id)
                .where(FundingLine.fiscal_year.between(start_year, end_year))
                .group_by(ProgramElement.agency, FundingLine.fiscal_year, FundingLine.funding_type)
            )

            results = self.session.execute(stmt).all()
            if not results: return pl.DataFrame()

            schema = {"agency": pl.Utf8, "fiscal_year": pl.Int64,
                      "funding_type": pl.Utf8, "total_funding": pl.Float64}
            df_raw = pl.DataFrame(results, schema=schema, orient="row")
            df_raw = self._prefer_funding_type(df_raw, keys=["agency"])

            df_wide = df_raw.pivot(
                index="agency", columns="fiscal_year", values="total_funding", aggregate_function="sum"
            ).fill_null(0.0)

            return self._sort_and_format_trends(df_wide, start_year, end_year)

        except Exception as e:
            logger.error(f"Failed to calculate agency trends: {e}")
            raise

    def get_pe_history(self, pe_number: str, agency: str) -> pl.DataFrame:
        """
        Full funding history for one PE: one row per fiscal year with the
        preferred figure and a `basis` label saying where it came from
        (Actual / Enacted-CY / Request) - the drill-down behind the linker's
        trend chart.
        """
        stmt = (
            select(
                FundingLine.fiscal_year,
                FundingLine.funding_type,
                FundingLine.amount_thousands,
            )
            .join(ProgramElement, ProgramElement.id == FundingLine.program_element_id)
            .where(
                ProgramElement.pe_number == pe_number,
                ProgramElement.agency == agency,
            )
        )
        results = self.session.execute(stmt).all()
        if not results:
            return pl.DataFrame()

        df = pl.DataFrame(
            results,
            schema={"fiscal_year": pl.Int64, "funding_type": pl.Utf8,
                    "amount_thousands": pl.Float64},
            orient="row",
        )
        basis_labels = {
            "PY Actual": "Actual",
            "CY Request": "Enacted/CY",
            "BY Request": "Request",
        }
        return (
            df.with_columns(
                pl.col("funding_type")
                .replace_strict(FUNDING_TYPE_PRIORITY, default=9)
                .alias("_prio")
            )
            .sort("_prio")
            .group_by("fiscal_year", maintain_order=True)
            .first()
            .with_columns(
                pl.col("funding_type")
                .replace_strict(basis_labels, default="Other")
                .alias("basis")
            )
            .drop("_prio", "funding_type")
            .sort("fiscal_year")
        )

    def get_pe_trends(self, start_year: int, end_year: int) -> pl.DataFrame:
        try:
            stmt = (
                select(
                    ProgramElement.pe_number,
                    ProgramElement.program_name,
                    ProgramElement.agency,
                    FundingLine.fiscal_year,
                    FundingLine.funding_type,
                    func.sum(FundingLine.amount_thousands).label("total_funding")
                )
                .join(FundingLine, ProgramElement.id == FundingLine.program_element_id)
                .where(FundingLine.fiscal_year.between(start_year, end_year))
                .group_by(ProgramElement.pe_number, ProgramElement.program_name, ProgramElement.agency, FundingLine.fiscal_year, FundingLine.funding_type)
            )

            results = self.session.execute(stmt).all()
            if not results: return pl.DataFrame()

            schema = {
                "pe_number": pl.Utf8, "program_name": pl.Utf8, "agency": pl.Utf8,
                "fiscal_year": pl.Int64, "funding_type": pl.Utf8, "total_funding": pl.Float64
            }
            df_raw = pl.DataFrame(results, schema=schema, orient="row")
            df_raw = self._prefer_funding_type(
                df_raw, keys=["pe_number", "program_name", "agency"]
            )

            df_wide = df_raw.pivot(
                index=["pe_number", "program_name", "agency"],
                columns="fiscal_year", values="total_funding", aggregate_function="sum"
            ).fill_null(0.0)

            return self._sort_and_format_trends(df_wide, start_year, end_year)

        except Exception as e:
            logger.error(f"Failed to calculate PE trends: {e}")
            raise