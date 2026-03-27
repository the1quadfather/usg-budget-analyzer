"""
storage/ingest_r1.py

ETL pipeline: loads parsed R-1 Parquet data into the SQLite schema.

Design:
  - One ProgramElement per unique (pe_number, agency). The same PE across
    multiple fiscal years shares a single ProgramElement row; its funding
    data across years is stored as separate FundingLine rows.
  - Classified PEs (pe_number == "") get a surrogate key combining agency
    + budget_activity + fiscal_year so they don't collapse into one record.
  - Each R-1 row produces up to 3 FundingLine rows (PY Actual, CY Request,
    BY Request), skipping nulls.
  - Re-running is safe: existing SourceDocuments and ProgramElements are
    looked up and reused; only new FundingLines are added.

Usage:
    # Ingest the combined parquet
    python storage/ingest_r1.py --parquet data/processed/r1_all_years.parquet

    # Wipe DB and rebuild from scratch
    python storage/ingest_r1.py --parquet data/processed/r1_all_years.parquet --reset
"""

import logging
import math
import sys
from pathlib import Path
from typing import Dict, Tuple

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from storage.db import (
    FundingLine,
    ProgramElement,
    SourceDocument,
    get_engine,
    get_session_factory,
    init_db,
    reset_db,
)

logger = logging.getLogger(__name__)

# Default DB path (relative to project root)
DEFAULT_DB_URI = "sqlite:///data/processed/usg_budgets.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    """Return float or None for null/NaN values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _classified_key(agency: str, act_code: str, fiscal_year: int) -> str:
    """
    Generate a surrogate PE number for classified rows so they don't all
    collapse into a single (pe_number="", agency) cache entry.
    e.g. "CLASSIFIED_Army_04_2025"
    """
    return f"CLASSIFIED_{agency}_{act_code}_{fiscal_year}"


# ── Main Ingestor ─────────────────────────────────────────────────────────────

class R1Ingestor:
    """
    Loads r1_all_years.parquet (or any per-FY parquet) into the SQLite DB.

    Example:
        engine = get_engine("sqlite:///data/processed/usg_budgets.db")
        init_db(engine)
        with get_session_factory(engine)() as session:
            ingestor = R1Ingestor(session)
            ingestor.ingest_parquet("data/processed/r1_all_years.parquet")
    """

    def __init__(self, session: Session):
        self.session = session
        self._doc_cache: Dict[str, int] = {}          # filename -> doc.id
        self._pe_cache: Dict[Tuple[str, str], int] = {} # (pe_key, agency) -> pe.id

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _preload_caches(self) -> None:
        """Load existing DB IDs into memory to avoid redundant queries."""
        docs = self.session.execute(
            select(SourceDocument.id, SourceDocument.filename)
        ).all()
        self._doc_cache = {d.filename: d.id for d in docs}

        pes = self.session.execute(
            select(ProgramElement.id, ProgramElement.pe_number, ProgramElement.agency)
        ).all()
        self._pe_cache = {(pe.pe_number, pe.agency): pe.id for pe in pes}

        logger.info(
            f"Cache loaded: {len(self._doc_cache)} documents, "
            f"{len(self._pe_cache)} program elements"
        )

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def ingest_parquet(self, filepath: str | Path) -> None:
        """
        Read a parquet file and load it into the DB.

        Parquet schema expected (from r1_parser.py output):
            fiscal_year, component, appropriation, budget_activity,
            pe_number, pe_title, line_no, act_code, is_classified,
            py_amount, cy_amount, by_amount, source_file, extraction_method
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(filepath)

        logger.info(f"Reading {filepath.name} ...")
        df = pl.read_parquet(filepath)
        logger.info(f"  {df.height:,} rows loaded")

        self._preload_caches()

        funding_lines: list[FundingLine] = []
        skipped = 0

        for row in tqdm(df.iter_rows(named=True), total=df.height, desc="Ingesting"):

            fiscal_year = row["fiscal_year"]
            if fiscal_year is None:
                skipped += 1
                continue

            # ── 1. Source Document ─────────────────────────────────────────
            filename = row["source_file"] or "unknown"
            if filename not in self._doc_cache:
                doc = SourceDocument(
                    filename=filename,
                    document_type="R1",
                    publication_year=int(fiscal_year),
                )
                self.session.add(doc)
                self.session.flush()
                self._doc_cache[filename] = doc.id

            doc_id = self._doc_cache[filename]

            # ── 2. Program Element ─────────────────────────────────────────
            pe_number_raw = (row["pe_number"] or "").strip()
            agency = (row["component"] or "Unknown").strip()
            is_classified = bool(row.get("is_classified", False))
            act_code = (row["act_code"] or "").strip()

            # Classified rows: generate surrogate key per (agency, BA, FY)
            # so they don't all collapse into one ("", agency) record.
            if is_classified or not pe_number_raw:
                pe_key = _classified_key(agency, act_code, int(fiscal_year))
            else:
                pe_key = pe_number_raw

            cache_key = (pe_key, agency)

            if cache_key not in self._pe_cache:
                pe = ProgramElement(
                    source_document_id=doc_id,
                    pe_number=pe_key,
                    line_item_number=str(row["line_no"]) if row.get("line_no") is not None else None,
                    program_name=(row["pe_title"] or "Unknown").strip(),
                    agency=agency,
                    appropriation=(row["appropriation"] or "").strip() or None,
                    budget_activity=(row["budget_activity"] or "").strip() or None,
                    act_code=act_code or None,
                    is_classified=is_classified,
                )
                self.session.add(pe)
                self.session.flush()
                self._pe_cache[cache_key] = pe.id

            pe_id = self._pe_cache[cache_key]

            # ── 3. Funding Lines ───────────────────────────────────────────
            # Each R-1 row has three amount columns representing:
            #   py_amount: prior year actuals        (fiscal_year - 2)
            #   cy_amount: current year enacted/req  (fiscal_year - 1)
            #   by_amount: budget year request       (fiscal_year)
            fy = int(fiscal_year)
            amounts = [
                (fy - 2, "PY Actual",   _safe_float(row["py_amount"])),
                (fy - 1, "CY Request",  _safe_float(row["cy_amount"])),
                (fy,     "BY Request",  _safe_float(row["by_amount"])),
            ]

            for amt_fy, f_type, amt in amounts:
                if amt is not None:
                    funding_lines.append(
                        FundingLine(
                            program_element_id=pe_id,
                            fiscal_year=amt_fy,
                            funding_type=f_type,
                            amount_thousands=amt,
                        )
                    )

        # ── Bulk insert funding lines ───────────────────────────────────────
        logger.info(f"Inserting {len(funding_lines):,} funding line records ...")
        if funding_lines:
            self.session.bulk_save_objects(funding_lines)
            self.session.commit()

        logger.info(
            f"Ingestion complete. "
            f"Documents: {len(self._doc_cache)}, "
            f"PEs: {len(self._pe_cache)}, "
            f"FundingLines: {len(funding_lines)}, "
            f"Skipped: {skipped}"
        )

    def print_summary(self) -> None:
        """Print a quick row-count summary of what's in the DB."""
        from sqlalchemy import func

        doc_count = self.session.execute(
            select(func.count(SourceDocument.id))
        ).scalar()
        pe_count = self.session.execute(
            select(func.count(ProgramElement.id))
        ).scalar()
        fl_count = self.session.execute(
            select(func.count(FundingLine.id))
        ).scalar()

        # Agency breakdown
        agency_rows = self.session.execute(
            select(ProgramElement.agency, func.count(ProgramElement.id))
            .group_by(ProgramElement.agency)
            .order_by(func.count(ProgramElement.id).desc())
        ).all()

        print(f"\n{'='*50}")
        print(f"DB Summary")
        print(f"{'='*50}")
        print(f"  Source documents : {doc_count:,}")
        print(f"  Program elements : {pe_count:,}")
        print(f"  Funding lines    : {fl_count:,}")
        print(f"\n  PEs by agency:")
        for agency, count in agency_rows:
            print(f"    {agency:<20} {count:>5}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Ingest R-1 parquet data into SQLite DB"
    )
    parser.add_argument(
        "--parquet",
        type=Path,
        default=Path("data/processed/r1_all_years.parquet"),
        help="Path to the combined parquet file",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_URI,
        help="SQLAlchemy DB URI (default: sqlite:///data/processed/usg_budgets.db)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate DB tables before ingesting (WARNING: destroys existing data)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print DB summary after ingestion",
    )
    args = parser.parse_args()

    # Ensure the data/processed directory exists before SQLite tries to open it
    if args.db.startswith("sqlite:///"):
        db_path = Path(args.db.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = get_engine(args.db)

    if args.reset:
        logger.warning("--reset specified: dropping and recreating all tables")
        reset_db(engine)
        logger.info("Schema recreated.")
    else:
        init_db(engine)

    SessionFactory = get_session_factory(engine)
    with SessionFactory() as session:
        ingestor = R1Ingestor(session)
        ingestor.ingest_parquet(args.parquet)
        if args.summary:
            ingestor.print_summary()