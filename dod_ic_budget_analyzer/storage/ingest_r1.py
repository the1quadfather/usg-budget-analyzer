"""
storage/ingest_r1.py

ETL pipeline to load parsed R-1 Parquet data into the SQLite SQLAlchemy schema.
Optimized for batch processing using in-memory ID caching.
"""

import logging
from typing import Dict, Tuple
import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session
from tqdm import tqdm

from storage.db import SourceDocument, ProgramElement, FundingLine

logger = logging.getLogger(__name__)

class R1Ingestor:
    def __init__(self, session: Session):
        self.session = session
        # Caches to prevent duplicate DB lookups during loops
        self._doc_cache: Dict[str, int] = {}
        self._pe_cache: Dict[Tuple[str, str], int] = {}

    def _preload_caches(self):
        """Preloads existing document and PE IDs to optimize upserts."""
        docs = self.session.execute(select(SourceDocument.id, SourceDocument.filename)).all()
        self._doc_cache = {doc.filename: doc.id for doc in docs}

        pes = self.session.execute(select(ProgramElement.id, ProgramElement.pe_number, ProgramElement.agency)).all()
        self._pe_cache = {(pe.pe_number, pe.agency): pe.id for pe in pes}

    def ingest_parquet(self, filepath: str) -> None:
        """Reads the R1 parquet file via Polars and loads it into the database."""
        logger.info(f"Loading data from {filepath}")
        
        # Use Polars for memory-efficient loading and strict typing
        df = pl.read_parquet(filepath)
        
        self._preload_caches()
        
        documents_to_add = {}
        pes_to_add = {}
        funding_lines = []

        # Iterate through records to build objects
        # Iter_rows with named=True is performant enough for < 100k rows
        for row in tqdm(df.iter_rows(named=True), total=df.height, desc="Processing rows"):
            
            # 1. Resolve Source Document
            filename = row["source_file"]
            if filename not in self._doc_cache and filename not in documents_to_add:
                doc = SourceDocument(
                    filename=filename,
                    document_type="R1",
                    publication_year=row["fiscal_year"]
                )
                self.session.add(doc)
                self.session.flush() # Flush to get the generated ID
                documents_to_add[filename] = doc.id
                self._doc_cache[filename] = doc.id
            
            doc_id = self._doc_cache.get(filename) or documents_to_add[filename]

            # 2. Resolve Program Element
            pe_num = row["pe_number"]
            agency = row["component"]
            cache_key = (pe_num, agency)

            if cache_key not in self._pe_cache and cache_key not in pes_to_add:
                # Handle act_code safely[cite: 2]
                try:
                    ba_int = int(row["act_code"])
                except (ValueError, TypeError):
                    ba_int = None

                pe = ProgramElement(
                    source_document_id=doc_id,
                    pe_number=pe_num,
                    line_item_number=str(row["line_no"]) if row["line_no"] is not None else None,
                    program_name=row["pe_title"],
                    agency=agency,
                    budget_activity=ba_int
                )
                self.session.add(pe)
                self.session.flush()
                pes_to_add[cache_key] = pe.id
                self._pe_cache[cache_key] = pe.id
            
            pe_id = self._pe_cache.get(cache_key) or pes_to_add[cache_key]

            # 3. Unpivot Funding Lines[cite: 2]
            pub_year = row["fiscal_year"]
            amounts = [
                (pub_year - 2, "PY Actual", row["py_amount"]),
                (pub_year - 1, "CY Request", row["cy_amount"]),
                (pub_year, "BY Request", row["by_amount"])
            ]

            for fy, f_type, amt in amounts:
                # Skip nulls and strict zero filtering (if zeros are not meaningful)
                if amt is not None and not pl.Series([amt]).is_nan()[0]:
                    funding_lines.append(
                        FundingLine(
                            program_element_id=pe_id,
                            fiscal_year=fy,
                            funding_type=f_type,
                            amount_thousands=float(amt)
                        )
                    )

        # Bulk insert funding lines for performance
        logger.info(f"Inserting {len(funding_lines)} funding records...")
        if funding_lines:
            self.session.bulk_save_objects(funding_lines)
            self.session.commit()
            
        logger.info("Ingestion complete.")