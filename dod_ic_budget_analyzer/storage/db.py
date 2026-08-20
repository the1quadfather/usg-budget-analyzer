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