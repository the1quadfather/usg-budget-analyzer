"""Tests for Program Element lineage detection."""

from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.lineage import detect_ba_renumbering
from storage.db import Base, FundingLine, ProgramElement, SourceDocument


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.document = SourceDocument(
            filename="synthetic_r1.xlsx",
            document_type="R1",
            publication_year=2027,
        )
        self.session.add(self.document)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _add_funded_pe(
        self,
        pe_number: str,
        program_name: str,
        fiscal_year: int,
        pb_cycle: int,
    ) -> None:
        program_element = ProgramElement(
            source_document=self.document,
            pe_number=pe_number,
            program_name=program_name,
            agency="Army",
            budget_activity=int(pe_number[2:4]),
        )
        self.session.add(program_element)
        self.session.flush()
        self.session.add(FundingLine(
            program_element_id=program_element.id,
            source_document_id=self.document.id,
            pb_cycle=pb_cycle,
            fiscal_year=fiscal_year,
            funding_type="BY Request",
            amount_thousands=100.0,
        ))

    def test_matching_same_fy_newer_vintage_is_detected_as_renumbering(self):
        self._add_funded_pe(
            "0609123D8Z", "Sentinel Demonstration Program", 2025, 2025
        )
        self._add_funded_pe(
            "0605123D8Z", "Sentinel Demonstration Program", 2025, 2026
        )
        self.session.commit()

        edges = detect_ba_renumbering(self.session)

        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge.predecessor_pe, "0609123D8Z")
        self.assertEqual(edge.successor_pe, "0605123D8Z")
        self.assertEqual(edge.first_fy_after, 2025)
        self.assertEqual(edge.relation, "renumbered")
        self.assertEqual(edge.method, "ba_renumber")

    def test_same_fy_without_newer_successor_vintage_is_rejected(self):
        self._add_funded_pe(
            "0609234A", "Shared Sentinel Program", 2025, 2026
        )
        self._add_funded_pe(
            "0605234A", "Shared Sentinel Program", 2025, 2026
        )
        self.session.commit()

        edges = detect_ba_renumbering(self.session)

        self.assertEqual(edges, [])

    def test_abutting_pair_with_dissimilar_titles_is_rejected(self):
        self._add_funded_pe(
            "0609456A", "Quantum Communications Research", 2024, 2024
        )
        self._add_funded_pe(
            "0605456A", "Undersea Propulsion Laboratory", 2025, 2025
        )
        self.session.commit()

        edges = detect_ba_renumbering(self.session)

        self.assertEqual(edges, [])

    def test_stopped_series_without_successor_has_no_edge(self):
        self._add_funded_pe(
            "0609789A", "Stopped Test Program", 2024, 2024
        )
        self.session.commit()

        edges = detect_ba_renumbering(self.session)

        self.assertEqual(edges, [])


if __name__ == "__main__":
    unittest.main()
