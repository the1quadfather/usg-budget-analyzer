import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import polars as pl
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.ai_budget import LedgerUnavailable, SpendLedger, budget_guard
from analysis.gap_analyzer import GapAnalyzer
from analysis.program_linker import ProgramLinker
from analysis.rhetoric_tracker import align_rhetoric_funding
from analysis.spending_explorer import SpendingExplorer
from analysis.trend_tracker import TrendTracker
from analysis.user_identity import streamlit_user_id
from storage.db import Base, FundingLine, ProgramElement, SourceDocument
from storage.ingest_r1 import R1Ingestor


class FundingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        doc = SourceDocument(
            filename="seed.xlsx", document_type="R1", publication_year=2026
        )
        pe = ProgramElement(
            source_document=doc,
            pe_number="0207423F",
            program_name="Advanced Communications Systems",
            agency="Air Force",
        )
        self.session.add(pe)
        self.session.flush()
        self.pe_id = pe.id
        self.session.add_all([
            FundingLine(
                program_element_id=pe.id,
                fiscal_year=2024,
                funding_type="PY Actual",
                amount_thousands=11_264,
            ),
            FundingLine(
                program_element_id=pe.id,
                fiscal_year=2024,
                funding_type="PY Actual",
                amount_thousands=12_693,
            ),
            FundingLine(
                program_element_id=pe.id,
                fiscal_year=2024,
                funding_type="PY Mandatory",
                amount_thousands=99_999,
            ),
        ])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_program_history_sums_lines_and_excludes_mandatory_stream(self):
        history = TrendTracker(self.session).get_pe_history(
            "0207423F", "Air Force"
        )
        self.assertEqual(history.height, 1)
        self.assertEqual(history.row(0, named=True)["amount_thousands"], 23_957)
        self.assertEqual(history.row(0, named=True)["basis"], "Actual")

    def test_gap_analyzer_sums_same_basis_before_selecting_it(self):
        funding = GapAnalyzer(self.session)._fetch_funding_data([self.pe_id])
        self.assertEqual(funding.height, 1)
        self.assertEqual(funding.row(0, named=True)["amount_thousands"], 23_957)


class IngestionRegressionTests(unittest.TestCase):
    def test_ingest_is_idempotent_and_retains_mandatory_streams(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(engine)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                parquet = Path(tmp) / "r1.parquet"
                pl.DataFrame([{
                    "source_file": "fy2027_r1.xlsx",
                    "fiscal_year": 2027,
                    "pe_number": "0600001A",
                    "component": "Army",
                    "act_code": "04",
                    "line_no": 1,
                    "pe_title": "Test Program",
                    "py_amount": 10.0,
                    "cy_amount": 20.0,
                    "by_amount": 30.0,
                    "py_mandatory_amount": 1.0,
                    "cy_mandatory_amount": 2.0,
                    "by_mandatory_amount": 3.0,
                }]).write_parquet(parquet)

                ingestor = R1Ingestor(session)
                ingestor.ingest_parquet(str(parquet))
                ingestor.ingest_parquet(str(parquet))

            count = session.execute(select(func.count(FundingLine.id))).scalar_one()
            types = set(session.execute(select(FundingLine.funding_type)).scalars())
            self.assertEqual(count, 6)
            self.assertEqual(
                types,
                {
                    "PY Actual", "CY Request", "BY Request",
                    "PY Mandatory", "CY Mandatory", "BY Mandatory",
                },
            )
        finally:
            session.close()
            engine.dispose()


class MatchingRegressionTests(unittest.TestCase):
    def test_exact_pe_across_agencies_requires_review(self):
        candidates = [
            {
                "pe_id": 1,
                "name": "Space Weather",
                "pe_number": "0604002SF",
                "agency": "Air Force",
                "score": 1.0,
                "strategy": "PE_NUMBER",
            },
            {
                "pe_id": 2,
                "name": "Space Weather",
                "pe_number": "0604002SF",
                "agency": "Space Force",
                "score": 1.0,
                "strategy": "PE_NUMBER",
            },
        ]

        class ExactMatcher:
            def lookup_pe_number(self, _query):
                return candidates

        result = ProgramLinker(ExactMatcher()).link_query("PE 0604002SF")
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["match_strategy"], "AMBIGUOUS")


class ExternalQueryRegressionTests(unittest.TestCase):
    def test_subaward_queries_are_scoped_to_dod(self):
        class FakeHTTP:
            def __init__(self):
                self.payloads = []

            def post(self, _path, payload):
                self.payloads.append(payload)
                return {"results": []}

        explorer = SpendingExplorer.__new__(SpendingExplorer)
        explorer.http = FakeHTTP()
        explorer.program_subawards("Test Program", 2024, 2025)

        self.assertEqual(len(explorer.http.payloads), 2)
        for payload in explorer.http.payloads:
            self.assertEqual(
                payload["filters"]["agencies"], explorer.DOD_FUNDING
            )


class GovernanceRegressionTests(unittest.TestCase):
    def test_budget_guard_fails_closed_when_ledger_is_unavailable(self):
        with patch.object(
            SpendLedger,
            "month_to_date",
            side_effect=LedgerUnavailable("locked"),
        ):
            decision = budget_guard("adjudicate", user_id="alice")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "metering")

    def test_anonymous_streamlit_sessions_do_not_share_identity(self):
        first = SimpleNamespace(
            user=SimpleNamespace(is_logged_in=False), session_state={}
        )
        second = SimpleNamespace(
            user=SimpleNamespace(is_logged_in=False), session_state={}
        )
        first_id = streamlit_user_id(first)
        self.assertEqual(streamlit_user_id(first), first_id)
        self.assertNotEqual(streamlit_user_id(second), first_id)


class StatisticsRegressionTests(unittest.TestCase):
    def test_alignment_reports_actual_overlap_count(self):
        signal = pd.DataFrame({
            "fiscal_year": range(2020, 2026),
            "mention_intensity": [1, 2, 3, 4, 5, 6],
            "positive_pct": [50] * 6,
            "negative_pct": [10] * 6,
            "stated_priority": [False] * 6,
        })
        funding = pd.DataFrame({
            "fiscal_year": [2021, 2022, 2024, 2025],
            "amount_thousands": [1_000, 2_000, 4_000, 5_000],
        })
        result = align_rhetoric_funding(signal, funding)
        self.assertEqual(result["alignment"]["n_years"], 4)


if __name__ == "__main__":
    unittest.main()
