"""Portable collections and financially comparable watchlist calculations."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis import portfolios
from analysis.deflators import convert_amount
from storage.db import Base, FundingLine, ProgramElement, SourceDocument


def collection(members=(), **overrides):
    settings = portfolios.default_settings([2026, 2027])
    settings.update(overrides)
    root = portfolios.save_collection(
        portfolios.new_workspace(), name="Leadership", kind="watchlist", settings=settings,
        members=[{"pe_number": pe, "agency": agency} for pe, agency in members],
    )
    return root, root["collections"][0]


@pytest.fixture
def budget():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        docs = {}
        programs = {}

        def add(pe, agency, cycle, amount_k, *, kind="BY Request", fy=None, source=None):
            filename = source or f"fy{cycle}_r1.xlsx"
            if filename not in docs:
                docs[filename] = SourceDocument(
                    filename=filename, document_type="R1", publication_year=cycle,
                    source_url=f"https://example.gov/{filename}",
                )
                session.add(docs[filename])
                session.flush()
            if (pe, agency) not in programs:
                programs[(pe, agency)] = ProgramElement(
                    pe_number=pe, agency=agency, program_name=f"Program {pe}",
                    source_document_id=docs[filename].id,
                )
                session.add(programs[(pe, agency)])
                session.flush()
            session.add(FundingLine(
                program_element_id=programs[(pe, agency)].id,
                source_document_id=docs[filename].id, pb_cycle=cycle,
                fiscal_year=cycle if fy is None else fy, funding_type=kind,
                amount_thousands=amount_k,
            ))
            session.flush()

        yield session, add
    engine.dispose()


def test_round_trip_preserves_private_definitions_and_mutations_are_isolated():
    root, item = collection([("0600001A", "Army")])
    original = deepcopy(root)
    updated = portfolios.save_collection(
        root, collection_id=item["id"], name="Board <review>", kind="portfolio",
        notes="Review $5M; café.\nSource-backed only.", settings=item["settings"],
        members=item["members"],
    )
    assert root == original
    assert updated["revision"] != root["revision"]
    assert portfolios.load_workspace(portfolios.dump_workspace(updated)) == updated
    assert "before_k" not in portfolios.dump_workspace(updated).decode()
    assert portfolios.remove_collection(updated, item["id"])["collections"] == []
    assert len(updated["collections"]) == 1


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(schema_version=2),
    lambda r: r.update(revision="../bad"),
    lambda r: r["collections"][0].update(kind=[]),
    lambda r: r["collections"][0]["settings"].update(basis=[]),
    lambda r: r["collections"][0]["settings"].update(older_pb=True),
    lambda r: r["collections"][0]["settings"].update(min_change_m=float("inf")),
    lambda r: r["collections"][0]["settings"].update(newer_pb=2025),
    lambda r: r["collections"][0].update(notes="bad\x00text"),
    lambda r: r["collections"][0].update(secret="must not be accepted"),
    lambda r: r["collections"][0]["members"].append(r["collections"][0]["members"][0]),
])
def test_invalid_backups_are_rejected_without_mutating_current_work(mutation):
    root, _ = collection([("0600001A", "Army")])
    invalid = deepcopy(root)
    mutation(invalid)
    before = deepcopy(root)
    with pytest.raises(ValueError):
        portfolios.validate_workspace(invalid)
    assert root == before


def test_backup_limits_and_duplicate_names():
    root, item = collection()
    with pytest.raises(ValueError, match="1 MB"):
        portfolios.load_workspace(b" " * (portfolios.MAX_BACKUP_BYTES + 1))
    with pytest.raises(ValueError):
        portfolios.load_workspace(b'{"schema_version": NaN}')
    with pytest.raises(ValueError, match="different name"):
        portfolios.save_collection(root, name=" LEADERSHIP ", kind="portfolio", settings=item["settings"])


def test_requests_are_same_basis_and_exact_pairs_with_exact_sources(budget):
    session, add = budget
    pairs = [("0600001A", "Army"), ("0600002F", "Air Force")]
    add(*pairs[0], 2026, 100_000)
    add(*pairs[0], 2026, 50_000)  # separate budget-activity line
    add(*pairs[0], 2027, 200_000)
    add(*pairs[1], 2026, 30_000)
    add(*pairs[1], 2027, 40_000)
    add(*pairs[0], 2027, 999_000, kind="CY Request", fy=2026, source="cy.xlsx")
    add(*pairs[0], 2027, 999_000, kind="BY Mandatory", source="mandatory.xlsx")
    add("0600001A", "Air Force", 2027, 999_000, source="cross-service.xlsx")
    add("0600002F", "Army", 2027, 999_000, source="cross-service.xlsx")
    _, item = collection(pairs)
    snapshot = portfolios.build_snapshot(session, item)
    rows = snapshot.rows.set_index(["pe_number", "agency"])
    assert rows.loc[pairs[0], "before_k"] == 150_000
    assert rows.loc[pairs[0], "after_k"] == 200_000
    assert rows.loc[pairs[0], "delta_k"] == 50_000
    assert {s["filename"] for s in snapshot.sources} == {"fy2026_r1.xlsx", "fy2027_r1.xlsx"}
    assert portfolios.request_cycles(session) == [2026, 2027]


def test_both_watch_thresholds_are_required_and_units_are_thousands(budget):
    session, add = budget
    pairs = [("0600001A", "Army"), ("0600002A", "Army"), ("0600003A", "Army")]
    for pair, before, after in zip(pairs, [100_000, 1000, 100_000], [115_000, 3000, 140_000]):
        add(*pair, 2026, before)
        add(*pair, 2027, after)
    _, item = collection(pairs)
    snapshot = portfolios.build_snapshot(session, item)
    assert snapshot.flagged["pe_number"].tolist() == ["0600003A"]
    table = portfolios.comparison_table(snapshot, flagged_only=True)
    assert table.iloc[0]["Change ($M)"] == 40
    assert table.iloc[0]["Change (%)"] == 40


def test_absence_is_not_zero_or_cancellation_and_zero_base_has_no_percent(budget):
    session, add = budget
    pairs = [(f"060000{i}A", "Army") for i in range(1, 5)]
    add(*pairs[0], 2027, 25_000)
    add(*pairs[1], 2026, 25_000)
    add(*pairs[2], 2026, 0)
    add(*pairs[2], 2027, 20_000)
    _, item = collection(pairs)
    snapshot = portfolios.build_snapshot(session, item)
    rows = snapshot.rows.set_index("pe_number")
    assert pd.isna(rows.loc[pairs[0][0], "before_k"])
    assert pd.isna(rows.loc[pairs[1][0], "after_k"])
    assert rows.loc[pairs[1][0], "status"] == "No longer observed request"
    assert rows.loc[pairs[2][0], "before_k"] == 0
    assert pd.isna(rows.loc[pairs[2][0], "pct_change"])
    assert rows.loc[pairs[3][0], "status"] == "No request observations"
    assert len(snapshot.flagged) == 3
    item["settings"]["include_presence"] = False
    assert portfolios.build_snapshot(session, item).flagged.empty


def test_constant_dollars_use_each_request_year_and_include_deflator_source(budget):
    session, add = budget
    pair = ("0600001A", "Army")
    add(*pair, 2026, 100_000)
    add(*pair, 2027, 110_000)
    _, item = collection([pair], basis="constant-2025")
    snapshot = portfolios.build_snapshot(session, item)
    row = snapshot.rows.iloc[0]
    assert row.before_k == pytest.approx(convert_amount(100_000, 2026))
    assert row.after_k == pytest.approx(convert_amount(110_000, 2027))
    assert any(s["document_type"] == "RDT&E deflator" for s in snapshot.sources)


def test_empty_collection_exports_without_inventing_rows(budget):
    session, _ = budget
    _, item = collection()
    snapshot = portfolios.build_snapshot(session, item)
    assert snapshot.rows.empty
    assert portfolios.comparison_table(snapshot).empty
    assert snapshot.sources == []
