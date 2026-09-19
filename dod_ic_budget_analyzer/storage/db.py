"""
storage/db.py

SQLAlchemy 2.0 declarative schema and database connection utilities for the
DoD/IC Budget Analyzer.
"""

import gzip
import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, create_engine, inspect, text
from sqlalchemy import UniqueConstraint
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC for compatibility with the existing SQLite columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    source_url: Mapped[Optional[str]] = mapped_column(String(2048))
    retrieved_at: Mapped[Optional[datetime]]
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    processed_date: Mapped[datetime] = mapped_column(default=_utcnow)

    program_elements: Mapped[List["ProgramElement"]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    funding_lines: Mapped[List["FundingLine"]] = relationship(
        back_populates="source_document"
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
    # Funding lines are versioned observations. A fiscal year can appear in
    # three different President's Budget submissions, so provenance belongs
    # on the observation rather than only on the canonical PE record.
    source_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("source_documents.id"), index=True
    )
    pb_cycle: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    funding_type: Mapped[str] = mapped_column(String(50))  # e.g., 'PY Actual', 'CY Request'
    amount_thousands: Mapped[float] = mapped_column(Float)

    program_element: Mapped["ProgramElement"] = relationship(back_populates="funding_lines")
    source_document: Mapped[Optional["SourceDocument"]] = relationship(
        back_populates="funding_lines"
    )


class ProcurementLine(Base):
    """One P-1 procurement budget-line observation."""

    __tablename__ = "procurement_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id")
    )
    bli: Mapped[str] = mapped_column(String(50))
    line_item_title: Mapped[str] = mapped_column(String(500))
    agency: Mapped[str] = mapped_column(String(100))
    appropriation: Mapped[str] = mapped_column(String(100))
    budget_activity: Mapped[int | None] = mapped_column(Integer)
    line_number: Mapped[str] = mapped_column(String(10))
    bsa: Mapped[str] = mapped_column(String(10))
    bsa_title: Mapped[str] = mapped_column(String(200))
    cost_type: Mapped[str] = mapped_column(String(10))
    cost_type_title: Mapped[str] = mapped_column(String(200))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    funding_type: Mapped[str] = mapped_column(String(50))
    amount_thousands: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    pb_cycle: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "bli",
            "agency",
            "appropriation",
            "budget_activity",
            "line_number",
            "cost_type",
            "cost_type_title",
            "fiscal_year",
            "funding_type",
            "pb_cycle",
            "source_document_id",
        ),
    )


class PEExecution(Base):
    """Quarterly DD 1416 budget-authority status for one RDT&E PE line."""

    __tablename__ = "pe_execution"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("source_documents.id"), index=True
    )
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100), index=True)
    appropriation: Mapped[str] = mapped_column(String(50), index=True)
    fy_start: Mapped[int] = mapped_column(Integer, index=True)
    fy_end: Mapped[int] = mapped_column(Integer)
    report_date: Mapped[str] = mapped_column(String(10), index=True)
    line_number: Mapped[Optional[str]] = mapped_column(String(50))
    program_title: Mapped[str] = mapped_column(String(500))
    budget_activity: Mapped[Optional[int]] = mapped_column(Integer)
    request_k: Mapped[Optional[float]] = mapped_column(Float)
    enacted_k: Mapped[Optional[float]] = mapped_column(Float)
    statutory_adj_k: Mapped[Optional[float]] = mapped_column(Float)
    suppl_resc_seq_k: Mapped[Optional[float]] = mapped_column(Float)
    other_adj_k: Mapped[Optional[float]] = mapped_column(Float)
    above_threshold_reprog_k: Mapped[Optional[float]] = mapped_column(Float)
    below_threshold_reprog_k: Mapped[Optional[float]] = mapped_column(Float)
    net_k: Mapped[Optional[float]] = mapped_column(Float)
    source_file: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(default=_utcnow)

    source_document: Mapped[Optional["SourceDocument"]] = relationship()


class PELineage(Base):
    """Evidence-backed relationship between predecessor and successor PEs."""

    __tablename__ = "pe_lineage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    predecessor_pe: Mapped[str] = mapped_column(String(50))
    predecessor_agency: Mapped[str] = mapped_column(String(100))
    successor_pe: Mapped[str] = mapped_column(String(50))
    successor_agency: Mapped[str] = mapped_column(String(100))
    relation: Mapped[str] = mapped_column(String(50))
    first_fy_after: Mapped[int] = mapped_column(Integer)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text)
    evidence_source: Mapped[Optional[str]] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(50))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(default=_utcnow)


FactType = Literal["contractor", "transition", "test_event", "location"]
FACT_TYPES: tuple[str, ...] = (
    "contractor", "transition", "test_event", "location"
)


class NarrativeFact(Base):
    """One structured fact extracted from a narrative sentence (T15b fills it)."""

    __tablename__ = "narrative_facts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    narrative_table: Mapped[str] = mapped_column(String(30))
    # "pe_narratives" | "pe_accomplishments"
    narrative_id: Mapped[int] = mapped_column(Integer)  # that table's id; no FK
    pe_number: Mapped[str] = mapped_column(String(50), index=True)
    agency: Mapped[str] = mapped_column(String(100))
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fact_type: Mapped[str] = mapped_column(String(20))  # one of FACT_TYPES
    value: Mapped[str] = mapped_column(String(500))  # normalised value
    sentence: Mapped[str] = mapped_column(Text)  # verbatim source sentence
    char_start: Mapped[int] = mapped_column(Integer)  # source text offset
    char_end: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(100))  # config.GEMINI_MODEL
    content_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    extracted_at: Mapped[datetime] = mapped_column(default=_utcnow)

    __table_args__ = (
        Index(
            "ix_narrative_facts_source", "narrative_table", "narrative_id"
        ),
    )


def narrative_fact_hash(narrative_table: str, narrative_id: int, fact_type: str,
                        value: str, char_start: int, char_end: int) -> str:
    """sha256 over the tab-joined identity fields; the idempotency key for T15b."""
    identity = "\t".join([
        narrative_table,
        str(narrative_id),
        fact_type,
        value,
        str(char_start),
        str(char_end),
    ])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
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
    created_at: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
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
    ts: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
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
    ts: Mapped[datetime] = mapped_column(default=_utcnow, index=True)
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
    ingested_at: Mapped[datetime] = mapped_column(default=_utcnow)


def ensure_sqlite_file(db_uri: str) -> None:
    """
    Decompress the shipped `<name>.db.gz` when the plain `.db` is missing or
    older than the archive.

    The database is the product -- the app is useful the moment you clone --
    but it outgrew GitHub's 100 MB per-file limit. It is highly compressible,
    so it stores at roughly a quarter of its raw size and ships as
    `usg_budgets.db.gz`, expanded here on first use.

    Decompression writes a temporary file in the same directory and then
    renames it, because os.replace is atomic on POSIX: a crash, or a second
    process starting mid-write, can never leave a truncated database that
    looks complete. The mtime check means a pulled update is picked up rather
    than silently ignored, while a locally rebuilt database (newer than the
    archive) is left alone.
    """
    prefix = "sqlite:///"
    if not db_uri.startswith(prefix):
        return
    path = Path(db_uri[len(prefix):])
    archive = path.with_name(path.name + ".gz")
    if not archive.exists():
        return
    if path.exists() and path.stat().st_mtime >= archive.stat().st_mtime:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Expanding {archive.name} -> {path.name}")
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=f".{path.name}.", suffix=".tmp")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        with gzip.open(archive, "rb") as src, open(temp_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def get_engine(db_uri: str) -> Engine:
    """
    Creates and returns a SQLAlchemy Engine instance.
    
    Args:
        db_uri (str): The database connection string (e.g., 'sqlite:///path/to/db.sqlite').
        
    Returns:
        Engine: Configured SQLAlchemy engine.
    """
    # Every entry point -- app, scrapers, evals -- opens the database through
    # here, so this is the one place the archive needs expanding.
    ensure_sqlite_file(db_uri)
    engine = create_engine(db_uri, echo=False)
    _ensure_schema_compatibility(engine)
    return engine


def _ensure_schema_compatibility(engine: Engine) -> None:
    """Apply small, additive migrations needed by older shipped databases.

    SQLite's ``create_all`` creates new tables but does not add columns to an
    existing table. Migrations preserve stored rows; the empty procurement
    table can be rebuilt when its unique key changes. The provenance rebuild
    command populates new funding-line fields from the tracked parquet corpus.
    """
    Base.metadata.create_all(engine)
    if engine.dialect.name != "sqlite":
        return

    schema = inspect(engine)
    source_columns = {c["name"] for c in schema.get_columns("source_documents")}
    funding_columns = {c["name"] for c in schema.get_columns("funding_lines")}
    procurement_columns = {
        c["name"] for c in schema.get_columns("procurement_lines")
    }

    procurement_additions = {
        "line_number",
        "bsa",
        "bsa_title",
        "cost_type",
        "cost_type_title",
    }
    procurement_unique = (
        "bli",
        "agency",
        "appropriation",
        "budget_activity",
        "line_number",
        "cost_type",
        "cost_type_title",
        "fiscal_year",
        "funding_type",
        "pb_cycle",
        "source_document_id",
    )
    existing_procurement_uniques = {
        tuple(constraint["column_names"])
        for constraint in schema.get_unique_constraints("procurement_lines")
    }
    procurement_needs_rebuild = (
        not procurement_additions.issubset(procurement_columns)
        or procurement_unique not in existing_procurement_uniques
    )

    if procurement_needs_rebuild:
        with engine.begin() as connection:
            row_count = connection.scalar(text(
                "SELECT COUNT(*) FROM procurement_lines"
            ))
            if row_count:
                raise RuntimeError(
                    "Cannot migrate non-empty procurement_lines table"
                )
            ProcurementLine.__table__.drop(connection)
            ProcurementLine.__table__.create(connection)

    source_additions = {
        "source_url": "VARCHAR(2048)",
        "retrieved_at": "DATETIME",
        "content_hash": "VARCHAR(64)",
    }
    funding_additions = {
        "source_document_id": "INTEGER REFERENCES source_documents(id)",
        "pb_cycle": "INTEGER",
    }

    with engine.begin() as connection:
        for name, sql_type in source_additions.items():
            if name not in source_columns:
                connection.execute(text(
                    f"ALTER TABLE source_documents ADD COLUMN {name} {sql_type}"
                ))
        for name, sql_type in funding_additions.items():
            if name not in funding_columns:
                connection.execute(text(
                    f"ALTER TABLE funding_lines ADD COLUMN {name} {sql_type}"
                ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_source_documents_content_hash "
            "ON source_documents (content_hash)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_funding_lines_source_document_id "
            "ON funding_lines (source_document_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_funding_lines_pb_cycle "
            "ON funding_lines (pb_cycle)"
        ))


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
