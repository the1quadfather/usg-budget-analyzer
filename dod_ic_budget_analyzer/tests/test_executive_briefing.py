"""Verify the distributed PDF's figures, scope, complete pagination and text."""

from datetime import datetime, timezone
from io import BytesIO

import pandas as pd
import pdfplumber
import pytest

from analysis.executive_briefing import export_pdf
from analysis.portfolios import PortfolioSnapshot, ROW_COLUMNS, default_settings, new_workspace, save_collection


ARCHIVE = "a" * 64
STAMP = datetime(2026, 11, 22, 18, 30, tzinfo=timezone.utc)


def snapshot():
    root = save_collection(new_workspace(), name="Leadership", kind="watchlist",
                           settings=default_settings([2026, 2027]))
    item = root["collections"][0]
    item["notes"] = "Analyst note: review $5M and $10M; café."
    rows = pd.DataFrame([
        ("0600001A", "Army", "Comparable program", 100_000, 140_000, 40_000, 40.0, "Comparable requests", True),
        ("0600002A", "Army", "Missing comparison", 500_000, None, None, None, "No longer observed request", True),
        ("0600003F", "Air Force", "Newly observed", None, 200_000, None, None, "Newly observed request", True),
    ], columns=ROW_COLUMNS)
    sources = [{"filename": "fy2027_r1.xlsx", "document_type": "R1", "publication_year": 2027,
                "source_url": "https://example.gov/budget/r1.xlsx", "retrieved_at": None, "processed_date": None}]
    return PortfolioSnapshot(item, rows, sources)


def export(value=None, **kwargs):
    return export_pdf(value or snapshot(), title="Leadership review", archive_sha256=ARCHIVE,
                      generated_at=STAMP, **kwargs)


def test_pdf_preserves_scope_math_missing_values_notes_sources_and_metadata():
    payload = export(prepared_for="Senior management", decision="Agree the next review date.")
    assert payload.startswith(b"%PDF-")
    with pdfplumber.open(BytesIO(payload)) as pdf:
        pages = [page.extract_text() for page in pdf.pages]
        text = "\n".join(pages)
        assert "340.0" in pages[0]  # covered FY2027 requests, $K -> $M
        assert "+40.0" in pages[0]  # same-program cohort, NOT 340 - 600
        assert "2 of 3 programs observed" in pages[0]
        assert "Senior management" in pages[0]
        assert "PB2026 FY2026 request / PB2027 FY2027 request" in text
        assert "Then-year dollars" in text
        assert "Not observed" in text
        assert "review $5M and $10M; café" in text
        assert "analyst-provided" in text
        assert "example.gov/budget/r1.xlsx" in text
        assert "not enacted appropriations" in " ".join(text.split())
        assert "2026-11-22 18:30 UTC" in text
        assert ARCHIVE in text
        assert pdf.metadata["Title"] == "Leadership review"
        assert any(p.annots for p in pdf.pages)
        assert "agreed" not in text.lower()  # requested decision is not a recorded approval


def test_long_portfolio_and_notes_paginate_without_losing_rows_or_full_names():
    value = snapshot()
    value.collection["notes"] = ("Review this source sentence. " * 103)[:2980] + " FINAL_NOTE"
    rows = []
    for i in range(100):
        row = list(value.rows.iloc[0])
        row[0] = f"06{i:05d}A"
        row[2] = (f"Long program {i} " + "source description " * 12 + f"END_NAME_{i}")
        rows.append(row)
    value.rows = pd.DataFrame(rows, columns=ROW_COLUMNS)
    payload = export(value, decision="Discussion item. " * 80)
    with pdfplumber.open(BytesIO(payload)) as pdf:
        text = "\n".join(page.extract_text() for page in pdf.pages)
        assert 20 <= len(pdf.pages) <= 35
        assert "FINAL_NOTE" in text
        for i in range(100):
            assert f"06{i:05d}A" in text
            assert f"END_NAME_{i}" in text
        for page in pdf.pages:
            assert all(20 < word["x0"] < word["x1"] < page.width - 20
                       and 20 < word["top"] < word["bottom"] < page.height - 15
                       for word in page.extract_words())


def test_all_missing_has_no_invented_zero_and_constant_basis_is_explicit():
    value = snapshot()
    value.rows[["before_k", "after_k", "delta_k", "pct_change"]] = float("nan")
    value.collection["settings"]["basis"] = "constant-2025"
    with pdfplumber.open(BytesIO(export(value))) as pdf:
        first = pdf.pages[0].extract_text()
        assert first.count("Not observed") >= 2
        assert "0.0" not in first
        assert "Constant FY2025 dollars" in first
        assert "0 of 3 programs observed" in first


def test_export_rejects_empty_scope_invalid_metadata_and_unsupported_glyphs():
    value = snapshot()
    value.rows = value.rows.iloc[0:0]
    with pytest.raises(ValueError, match="Add programs"):
        export(value)
    with pytest.raises(ValueError, match="SHA-256"):
        export_pdf(snapshot(), title="Test", archive_sha256="unknown")
    with pytest.raises(ValueError, match="required"):
        export_pdf(snapshot(), title=" ", archive_sha256=ARCHIVE)
    value = snapshot()
    value.collection["notes"] = "Review \U0001f680"
    with pytest.raises(ValueError, match="font cannot display"):
        export(value)
