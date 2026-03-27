"""
analysis/gap_analyzer.py

Identifies discrepancies between public project visibility (unstructured queries)
and actual DoD budget allocations. Calculates Year-over-Year (YoY) funding 
trajectories using Polars for memory-efficient aggregations.
"""

import logging
from typing import List

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.db import FundingLine, ProgramElement

logger = logging.getLogger(__name__)

class GapAnalyzer:
    """
    Analyzes funding trajectories for linked Program Elements to identify 
    potential budget gaps or misalignments.
    """

    def __init__(self, session: Session):
        self.session = session

    def _fetch_funding_data(self, pe_ids: List[int]) -> pl.DataFrame:
        """
        Retrieves raw funding data for the specified Program Elements.
        """
        if not pe_ids:
            return pl.DataFrame()

        try:
            stmt = (
                select(
                    ProgramElement.id.label("pe_id"),
                    FundingLine.fiscal_year,
                    FundingLine.amount_thousands
                )
                .join(FundingLine, ProgramElement.id == FundingLine.program_element_id)
                .where(ProgramElement.id.in_(pe_ids))
            )
            
            results = self.session.execute(stmt).all()
            
            if not results:
                return pl.DataFrame()
                
            # FIX: Enforce strict Polars datatypes at the I/O boundary
            schema = {
                "pe_id": pl.Int64,
                "fiscal_year": pl.Int64,
                "amount_thousands": pl.Float64
            }
            
            return pl.DataFrame(results, schema=schema, orient="row")
            
        except Exception as e:
            logger.error(f"Failed to fetch funding data: {e}")
            raise

    def analyze_gaps(self, df_linked: pl.DataFrame, base_year: int, budget_year: int) -> pl.DataFrame:
        """
        Merges linked queries with funding data, pivots to a wide format, 
        and calculates YoY trajectories to flag funding gaps.
        """
        # Extract valid, non-null PE IDs
        valid_pes = df_linked.filter(pl.col("matched_pe_id").is_not_null())["matched_pe_id"].to_list()
        
        if not valid_pes:
            logger.warning("No valid PE IDs provided for analysis.")
            return pl.DataFrame()

        df_funding = self._fetch_funding_data(valid_pes)
        
        if df_funding.is_empty():
            logger.warning("No funding data found for the provided PE IDs.")
            return pl.DataFrame()

        df_agg = (
            df_funding
            .group_by(["pe_id", "fiscal_year"])
            .agg(pl.sum("amount_thousands").alias("total_funding"))
        )

        df_wide = df_agg.pivot(
            index="pe_id",
            columns="fiscal_year",
            values="total_funding",
            aggregate_function="sum"
        ).fill_null(0.0)

        for year in [base_year, budget_year]:
            year_str = str(year)
            if year_str not in df_wide.columns:
                df_wide = df_wide.with_columns(pl.lit(0.0).alias(year_str))

        base_col = str(base_year)
        budget_col = str(budget_year)

        df_analysis = df_wide.with_columns(
            yoy_delta_pct=pl.when(pl.col(base_col) > 0)
            .then(((pl.col(budget_col) - pl.col(base_col)) / pl.col(base_col)) * 100)
            .otherwise(
                pl.when(pl.col(budget_col) > 0).then(pl.lit(100.0))
                .otherwise(pl.lit(0.0))
            )
        ).with_columns(
            funding_gap_flag=pl.when(pl.col("yoy_delta_pct") < 0.0).then(True).otherwise(False)
        )

        # FIX: Defensively cast pe_id to Int64 right before the join 
        # to ensure the pivot operation didn't alter the schema
        df_analysis = df_analysis.with_columns(pl.col("pe_id").cast(pl.Int64))

        df_final = df_linked.join(
            df_analysis,
            left_on="matched_pe_id",
            right_on="pe_id",
            how="left"
        ).fill_null(0.0)

        return df_final.select([
            "query",
            "matched_name",
            "match_strategy",
            "confidence_score",
            pl.col(base_col).alias(f"FY{base_year}_$K"),
            pl.col(budget_col).alias(f"FY{budget_year}_$K"),
            pl.col("yoy_delta_pct").round(2).alias("YoY_Change_%"),
            "funding_gap_flag"
        ])