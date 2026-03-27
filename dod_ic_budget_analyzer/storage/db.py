"""
storage/db.py

SQLAlchemy 2.0 declarative schema and database connection utilities for the
DoD/IC Budget Analyzer.

Schema overview:
  SourceDocument  -- one row per source PDF file
  ProgramElement  -- one row per unique (pe_number, agency) pair
  FundingLine     -- one row per (PE, fiscal_year, funding_type) amount

Amounts are stored in thousands of dollars ($K) throughout.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy 2.0 models."""
    pass


class SourceDocument(Base):
    """
    Tracks origin files to ensure data provenance and traceability.
    One row per source PDF (e.g. FY2025_r1.pdf).
    """
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    document_type: Mapped[str] = mapped_column(String(50))       # e.g. "R1"
    publication_year: Mapped[int] = mapped_column(Integer, index=True)
    processed_date: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    program_elements: Mapped[List["ProgramElement"]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )


class ProgramElement(Base):
    """
    Core entity representing a unique DoD Program Element (PE).
    One row per (pe_number, agency) pair — the same PE across multiple
    fiscal years is a single ProgramElement with multiple FundingLines.

    Classified PEs (pe_number == "") are stored with a generated surrogate
    key incorporating their agency and budget_activity to avoid collapsing.
    """
    __tablename__ = "program_elements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))

    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    line_item_number: Mapped[Optional[str]] = mapped_column(String(50))
    program_name: Mapped[str] = mapped_column(String(500))
    agency: Mapped[str] = mapped_column(String(100), index=True)
    appropriation: Mapped[Optional[str]] = mapped_column(String(255))

    # Full label e.g. "BA3 - Advanced Technology Development"
    budget_activity: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    act_code: Mapped[Optional[str]] = mapped_column(String(10))  # raw "03"

    is_classified: Mapped[bool] = mapped_column(Boolean, default=False)

    source_document: Mapped["SourceDocument"] = relationship(back_populates="program_elements")
    funding_lines: Mapped[List["FundingLine"]] = relationship(
        back_populates="program_element", cascade="all, delete-orphan"
    )


class FundingLine(Base):
    """
    One row per (PE, fiscal_year, funding_type) funding amount.
    Amounts in $thousands.

    funding_type values:
      "PY Actual"  -- prior year actuals
      "CY Request" -- current year enacted/request
      "BY Request" -- budget year (the submission year) request
    """
    __tablename__ = "funding_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    program_element_id: Mapped[int] = mapped_column(
        ForeignKey("program_elements.id"), index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    funding_type: Mapped[str] = mapped_column(String(50))
    amount_thousands: Mapped[float] = mapped_column(Float)

    program_element: Mapped["ProgramElement"] = relationship(back_populates="funding_lines")


class PolicyDocument(Base):
    """
    A policy document (NDAA, NDS, NSS) stored as a parsed source.
    One row per PDF file.
    """
    __tablename__ = "policy_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(20), index=True)  # "NDAA"|"NDS"|"NSS"
    year: Mapped[int] = mapped_column(Integer, index=True)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, index=True)  # NDAA only
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    processed_date: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    chunks: Mapped[List["PolicyChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class PolicyChunk(Base):
    """
    A semantic chunk from a policy document.
    One row per chunk — typically a section (NDAA) or paragraph group (NDS/NSS).

    The 'text' field is the raw extracted text.
    Embeddings are stored externally as numpy arrays (see policy_linker.py).
    """
    __tablename__ = "policy_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("policy_documents.id"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)       # order within document
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section_id: Mapped[Optional[str]] = mapped_column(String(50))   # e.g. "SEC. 215"
    section_title: Mapped[Optional[str]] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[Optional[int]] = mapped_column(Integer)

    document: Mapped["PolicyDocument"] = relationship(back_populates="chunks")


# ── Connection helpers ────────────────────────────────────────────────────────

def get_engine(db_uri: str) -> Engine:
    """
    Creates and returns a SQLAlchemy Engine.

    Args:
        db_uri: Connection string e.g. 'sqlite:///data/processed/usg_budgets.db'
    """
    engine = create_engine(db_uri, echo=False)

    # WAL mode: allows concurrent readers with one writer.
    # Prevents DB corruption when Docker and CLI write simultaneously.
    # PRAGMA busy_timeout gives waiting writers up to 10s before failing.
    if db_uri.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    """
    Initialises the database schema. Safe to call multiple times —
    will not drop or modify existing tables.
    """
    Base.metadata.create_all(engine)


def reset_db(engine: Engine) -> None:
    """
    Drops all tables and recreates them from scratch.
    USE WITH CAUTION — destroys all existing data.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def get_session_factory(engine: Engine) -> sessionmaker:
    """Returns a configured sessionmaker bound to the provided engine."""
    return sessionmaker(bind=engine)