"""
storage/db.py

SQLAlchemy 2.0 declarative schema and database connection utilities for the
DoD/IC Budget Analyzer.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text, create_engine
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
    """
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    document_type: Mapped[str] = mapped_column(String(50))
    publication_year: Mapped[int] = mapped_column(Integer, index=True)
    processed_date: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    program_elements: Mapped[List["ProgramElement"]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )


class ProgramElement(Base):
    """
    Core entity for RDT&E budgets representing a specific Program Element (PE).
    """
    __tablename__ = "program_elements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    line_item_number: Mapped[Optional[str]] = mapped_column(String(50))
    program_name: Mapped[str] = mapped_column(String(500))
    agency: Mapped[str] = mapped_column(String(100), index=True)
    budget_activity: Mapped[Optional[int]] = mapped_column(Integer)

    source_document: Mapped["SourceDocument"] = relationship(back_populates="program_elements")
    funding_lines: Mapped[List["FundingLine"]] = relationship(
        back_populates="program_element", cascade="all, delete-orphan"
    )


class FundingLine(Base):
    """
    Represents a specific fiscal year's funding request/enactment for a given PE.
    Standard denomination is in thousands of dollars ($K).
    """
    __tablename__ = "funding_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    program_element_id: Mapped[int] = mapped_column(ForeignKey("program_elements.id"))
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    funding_type: Mapped[str] = mapped_column(String(50))  # e.g., 'PY Actual', 'CY Request'
    amount_thousands: Mapped[float] = mapped_column(Float)

    program_element: Mapped["ProgramElement"] = relationship(back_populates="funding_lines")


class PENarrative(Base):
    """
    R-2 justification narrative for a PE (project_number == "" for the
    PE-level mission description; per-project rows carry the project's own).
    Sourced from the official jbook XML volumes.
    """
    __tablename__ = "pe_narratives"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    project_number: Mapped[str] = mapped_column(String(50), default="")
    project_title: Mapped[Optional[str]] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(String(255))


class PEAccomplishment(Base):
    """
    R-2A accomplishment/planned-program entry: per-year funding ($ millions)
    with the narrative of what the money did (PY) or will do (CY/BY).
    """
    __tablename__ = "pe_accomplishments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    project_number: Mapped[str] = mapped_column(String(50), default="")
    title: Mapped[Optional[str]] = mapped_column(String(500))
    year_label: Mapped[str] = mapped_column(String(20))
    accomplishment_fy: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    funding_millions: Mapped[Optional[float]] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str] = mapped_column(String(255))


class AICache(Base):
    """
    Shared, cross-user cache of AI results.

    ONLY non-grounded results belong here. Results produced with Grounding with
    Google Search may be shown "only to the end user who submitted the prompt"
    and may not be cached or resold, so they go to AIUserHistory instead. The
    invariant is enforced in analysis/ai_budget.AICache.put().
    """
    __tablename__ = "ai_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task: Mapped[str] = mapped_column(String(50), index=True)
    params_json: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)


class AIUserHistory(Base):
    """
    Per-user store for grounded results — the narrow carve-out the Gemini API
    terms allow (a user may see their own history). Never served to a different
    user, and never retained beyond config.GROUNDED_HISTORY_MAX_DAYS.
    """
    __tablename__ = "ai_user_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(String(50), index=True)
    params_json: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[str] = mapped_column(Text)
    search_suggestions_html: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)


class AISpend(Base):
    """
    One row per AI call attempt — the ledger that makes unit economics knowable.
    Token counts come from the response's usage metadata and search_queries from
    grounding metadata, so costs are measured rather than guessed. Cache hits are
    logged too (with zero cost) so hit rate is computable.
    """
    __tablename__ = "ai_spend"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="local")
    task: Mapped[str] = mapped_column(String(50), index=True)
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    thought_tokens: Mapped[int] = mapped_column(Integer, default=0)
    search_queries: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cache_hit: Mapped[int] = mapped_column(Integer, default=0)  # 0/1
    ok: Mapped[int] = mapped_column(Integer, default=1)         # 0 when the call failed


class SearchLog(Base):
    """
    Every Program Finder query, so precompute can follow real demand instead of
    guessing which programs matter. Also the harvest pool for expanding the
    golden eval set (see analysis/linker_eval.py).
    """
    __tablename__ = "search_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    user_id: Mapped[str] = mapped_column(String(128), default="local")
    query: Mapped[str] = mapped_column(String(500), index=True)
    matched_pe: Mapped[Optional[str]] = mapped_column(String(50))
    agency: Mapped[Optional[str]] = mapped_column(String(100))
    needs_review: Mapped[int] = mapped_column(Integer, default=0)


class PECongressionalAction(Base):
    """
    Authorization-committee action on a single Program Element, parsed from the
    RDT&E funding tables printed in HASC/SASC NDAA committee reports.

    These are public-domain government works (17 U.S.C. 105), so unlike Gemini
    Grounded Results they may be cached, analyzed, and resold freely.

    A PE can legitimately appear more than once in one report under different
    budget activities (e.g. 0604201F carries separate 18,041 and 163,156 lines
    in H. Rept. 118-125), so `line_number` is part of the natural key and
    amounts must never be summed blindly across rows.

    Machine-readable tables begin at FY2012; earlier reports print the same
    tables as GRAPHIC images, so coverage is roughly half the funding history.
    Disclose that wherever this data is surfaced.
    """
    __tablename__ = "pe_congressional_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    chamber: Mapped[str] = mapped_column(String(16), index=True)  # 'House' | 'Senate'
    report_citation: Mapped[str] = mapped_column(String(64), index=True)
    line_number: Mapped[str] = mapped_column(String(10))
    program_title: Mapped[str] = mapped_column(String(500))
    budget_activity_title: Mapped[Optional[str]] = mapped_column(String(200))
    request_k: Mapped[Optional[float]] = mapped_column(Float)
    committee_delta_k: Mapped[Optional[float]] = mapped_column(Float)
    authorized_k: Mapped[Optional[float]] = mapped_column(Float)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    # 1 when pe_number is a 9999... classified placeholder rather than a real PE
    is_classified: Mapped[int] = mapped_column(Integer, default=0)
    # 1 when request_k matched the FY's 'CY Request' funding line for this PE
    reconciled: Mapped[int] = mapped_column(Integer, default=0, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


def get_engine(db_uri: str) -> Engine:
    """
    Creates and returns a SQLAlchemy Engine instance.
    
    Args:
        db_uri (str): The database connection string (e.g., 'sqlite:///path/to/db.sqlite').
        
    Returns:
        Engine: Configured SQLAlchemy engine.
    """
    return create_engine(db_uri, echo=False)


def init_db(engine: Engine) -> None:
    """
    Initializes the database schema. Safe to call multiple times; 
    will not drop existing tables.
    
    Args:
        engine (Engine): The SQLAlchemy engine connected to the target database.
    """
    Base.metadata.create_all(engine)


def get_session_factory(engine: Engine) -> sessionmaker:
    """
    Returns a configured sessionmaker bound to the provided engine.
    
    Args:
        engine (Engine): The SQLAlchemy engine.
        
    Returns:
        sessionmaker: A factory for creating database sessions.
    """
    return sessionmaker(bind=engine)