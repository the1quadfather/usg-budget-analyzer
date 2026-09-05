"""
analysis/congressional_actions.py

Read side of `pe_congressional_actions`: what the authorizing committees did to
a program's budget request, year by year.

This is the exact-join answer to "did the money follow the talk?" -- requested
vs. authorized dollars with the committee's own stated reason -- and it needs
no API key, so it works on the free tier where the AI rhetoric signal cannot.

Two things callers must respect:

* **Coverage starts at FY2012.** Earlier committee reports print the same
  tables as GRAPHIC images, so a flat "no action" for FY2009 means "not
  ingested", not "no congressional action". Use `coverage_note()`.
* **A PE can hold several rows per report**, one per budget activity. Those are
  distinct funding lines for the same program, so summing them is correct for a
  program total -- but only after grouping by (fiscal_year, chamber). Summing
  across chambers would double-count the same dollars.
"""

import logging

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from analysis.text_render import escape_dollars
from storage.db import PECongressionalAction

logger = logging.getLogger(__name__)

# Machine-readable RDT&E tables begin with the FY2012 NDAA reports.
COVERAGE_FIRST_FY = 2012

_SCHEMA = {
    "pe_number": pl.Utf8,
    "agency": pl.Utf8,
    "fiscal_year": pl.Int64,
    "chamber": pl.Utf8,
    "report_citation": pl.Utf8,
    "line_number": pl.Utf8,
    "program_title": pl.Utf8,
    "budget_activity_title": pl.Utf8,
    "request_k": pl.Float64,
    "committee_delta_k": pl.Float64,
    "authorized_k": pl.Float64,
    "rationale": pl.Utf8,
}


def coverage_note() -> str:
    """One-line disclosure for any UI surfacing this data."""
    return (
        f"Congressional actions cover FY{COVERAGE_FIRST_FY} onward — earlier "
        "committee reports print their funding tables as images, so an absent "
        "year means 'not available', not 'no action taken'."
    )


class CongressionalActions:
    """Query helper over pe_congressional_actions."""

    def __init__(self, session: Session):
        self.session = session

    def fiscal_year_bounds(self) -> tuple[int, int]:
        """
        (first, last) fiscal year with any stored committee action, for sizing
        a year picker from the data rather than a hardcoded range. An empty
        table yields (COVERAGE_FIRST_FY, COVERAGE_FIRST_FY) so a caller never
        builds a slider whose maximum is below its minimum.
        """
        first, last = self.session.execute(
            select(func.min(PECongressionalAction.fiscal_year),
                   func.max(PECongressionalAction.fiscal_year))
        ).one()
        if first is None or last is None:
            return COVERAGE_FIRST_FY, COVERAGE_FIRST_FY
        return int(first), int(last)

    def get_actions(self, pe_numbers: list[str],
                    agencies: list[str] | None = None) -> pl.DataFrame:
        """
        Every stored committee action for the given PEs, newest fiscal year
        first. `agencies`, when given, is applied as a parallel filter to
        pe_numbers -- the codebase's usual (pe_number, agency) natural key.
        """
        if not pe_numbers:
            return pl.DataFrame(schema=_SCHEMA)

        stmt = select(
            PECongressionalAction.pe_number,
            PECongressionalAction.agency,
            PECongressionalAction.fiscal_year,
            PECongressionalAction.chamber,
            PECongressionalAction.report_citation,
            PECongressionalAction.line_number,
            PECongressionalAction.program_title,
            PECongressionalAction.budget_activity_title,
            PECongressionalAction.request_k,
            PECongressionalAction.committee_delta_k,
            PECongressionalAction.authorized_k,
            PECongressionalAction.rationale,
        ).where(PECongressionalAction.pe_number.in_(pe_numbers))

        if agencies:
            stmt = stmt.where(PECongressionalAction.agency.in_(agencies))

        rows = self.session.execute(stmt).all()
        if not rows:
            return pl.DataFrame(schema=_SCHEMA)

        return (
            pl.DataFrame(rows, schema=_SCHEMA, orient="row")
            .sort(["fiscal_year", "chamber", "line_number"], descending=[True, False, False])
        )

    def get_program_series(self, pe_numbers: list[str],
                           agencies: list[str] | None = None,
                           chamber: str | None = None) -> pl.DataFrame:
        """
        Per-fiscal-year totals across the selected PEs: requested, authorized,
        and the committee's net change, plus how many report lines fed each
        year so a caller can show its work.

        Grouped by (fiscal_year, chamber) because House and Senate score the
        same request separately -- pooling them would double the dollars.
        """
        actions = self.get_actions(pe_numbers, agencies)
        if actions.is_empty():
            return pl.DataFrame()

        if chamber:
            actions = actions.filter(pl.col("chamber") == chamber)
            if actions.is_empty():
                return pl.DataFrame()

        series = (
            actions.group_by(["fiscal_year", "chamber"])
            .agg(
                pl.col("request_k").sum().alias("request_k"),
                pl.col("committee_delta_k").sum().alias("delta_k"),
                pl.col("authorized_k").sum().alias("authorized_k"),
                pl.len().alias("line_count"),
                pl.col("rationale").drop_nulls().alias("rationales"),
            )
            .sort(["fiscal_year", "chamber"])
        )

        return series.with_columns(
            (pl.col("request_k") / 1e3).alias("request_m"),
            (pl.col("authorized_k") / 1e3).alias("authorized_m"),
            (pl.col("delta_k") / 1e3).alias("delta_m"),
            pl.when(pl.col("request_k") > 0)
            .then(pl.col("delta_k") / pl.col("request_k") * 100)
            .otherwise(None)
            .alias("delta_pct"),
            pl.col("rationales").list.join("; ").alias("rationale_text"),
        )


def summarize(series: pl.DataFrame) -> dict:
    """
    Headline numbers over a program series from `get_program_series`.

    Returns years_covered, totals in $M, the net committee change, and the
    single largest add and cut with their fiscal years -- enough for a
    one-sentence verdict without the caller re-deriving anything.
    """
    empty = {
        "years_covered": 0, "first_year": None, "last_year": None,
        "total_requested_m": 0.0, "total_authorized_m": 0.0,
        "net_delta_m": 0.0, "net_delta_pct": None,
        "years_cut": 0, "years_added": 0,
        "largest_add": None, "largest_cut": None,
    }
    if series is None or series.is_empty():
        return empty

    requested = float(series["request_k"].sum() or 0.0)
    authorized = float(series["authorized_k"].sum() or 0.0)
    delta = float(series["delta_k"].sum() or 0.0)

    def extreme(descending: bool) -> dict | None:
        # An "add" must actually be positive: a program that was only ever cut
        # has no largest add, and reporting its smallest cut as one is a lie.
        sign = (pl.col("delta_k") > 0) if descending else (pl.col("delta_k") < 0)
        rows = series.filter(pl.col("delta_k").is_not_null() & sign)
        if rows.is_empty():
            return None
        row = rows.sort("delta_k", descending=descending).row(0, named=True)
        return {
            "fiscal_year": row["fiscal_year"],
            "amount_m": row["delta_k"] / 1e3,
            "rationale": row.get("rationale_text") or None,
        }

    return {
        "years_covered": series["fiscal_year"].n_unique(),
        "first_year": int(series["fiscal_year"].min()),
        "last_year": int(series["fiscal_year"].max()),
        "total_requested_m": requested / 1e3,
        "total_authorized_m": authorized / 1e3,
        "net_delta_m": delta / 1e3,
        "net_delta_pct": (delta / requested * 100) if requested else None,
        "years_cut": int(series.filter(pl.col("delta_k") < 0).height),
        "years_added": int(series.filter(pl.col("delta_k") > 0).height),
        "largest_add": extreme(descending=True),
        "largest_cut": extreme(descending=False),
    }


def headline(program_name: str, summary: dict) -> str:
    """A plain-language verdict, or an honest note when there is no coverage."""
    if not summary["years_covered"]:
        return (
            f"**No congressional action on record for {program_name}.** "
            + coverage_note()
        )

    span = (f"FY{summary['first_year']}"
            if summary["first_year"] == summary["last_year"]
            else f"FY{summary['first_year']}–FY{summary['last_year']}")
    delta = summary["net_delta_m"]

    if abs(delta) < 0.05:
        verdict = "authorized the request essentially unchanged"
    elif delta > 0:
        verdict = (f"**added ${delta:,.1f}M** to the request "
                   f"({summary['net_delta_pct']:+.1f}%)")
    else:
        verdict = (f"**cut ${abs(delta):,.1f}M** from the request "
                   f"({summary['net_delta_pct']:+.1f}%)")

    # Rendered through st.markdown, where two dollar amounts in one string
    # would otherwise be parsed as an inline LaTeX span (see text_render).
    return escape_dollars(
        f"Across {span}, authorizing committees {verdict} for "
        f"**{program_name}** — ${summary['total_requested_m']:,.1f}M requested, "
        f"${summary['total_authorized_m']:,.1f}M authorized."
    )
