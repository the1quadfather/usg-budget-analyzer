"""Tests for Program Element lineage detection."""

import json
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.lineage import detect_ba_renumbering
from analysis.lineage import detect_narrative_transfers
from storage.db import Base, FundingLine, ProgramElement, SourceDocument
from storage.db import PEAccomplishment, PENarrative


LINEAGE_FIXTURE = Path(__file__).parent / "fixtures" / "lineage_sentences.json"


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


class NarrativeLineageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.cases = json.loads(LINEAGE_FIXTURE.read_text(encoding="utf-8"))

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _add_narrative(self, case: dict) -> None:
        self.session.add(PENarrative(
            pe_number=case["pe_number"],
            agency=case["agency"],
            fiscal_year=case["fiscal_year"],
            description=case["text"],
            source_file=case["source_file"],
        ))

    def _add_accomplishment(self, case: dict) -> None:
        self.session.add(PEAccomplishment(
            pe_number=case["pe_number"],
            agency=case["agency"],
            fiscal_year=case["fiscal_year"],
            year_label="Description",
            text=case["text"],
            source_file=case["source_file"],
        ))

    def test_fixture_yields_three_directed_evidence_backed_edges(self):
        self.assertEqual(len(self.cases), 6)
        self.assertEqual(
            sum(bool(case["expect_edges"]) for case in self.cases),
            3,
        )
        for index, case in enumerate(self.cases):
            if index % 2 == 0:
                self._add_narrative(case)
            else:
                self._add_accomplishment(case)
        self.session.commit()

        edges = detect_narrative_transfers(self.session)

        expected = {}
        for case in self.cases:
            for item in case["expect_edges"]:
                key = (
                    item["predecessor_pe"],
                    case["agency"],
                    item["successor_pe"],
                    case["agency"],
                )
                expected[key] = (item, case)
        actual = {
            (
                edge.predecessor_pe,
                edge.predecessor_agency,
                edge.successor_pe,
                edge.successor_agency,
            ): edge
            for edge in edges
        }

        self.assertEqual(len(edges), 3)
        self.assertEqual(set(actual), set(expected))
        for key, (item, case) in expected.items():
            edge = actual[key]
            self.assertEqual(edge.first_fy_after, item["first_fy_after"])
            self.assertAlmostEqual(edge.confidence, item["confidence"])
            self.assertEqual(edge.relation, "transferred")
            self.assertEqual(edge.method, "narrative")
            self.assertEqual(edge.evidence_source, case["source_file"])
            self.assertIsNotNone(edge.evidence_text)
            self.assertIn(edge.evidence_text, case["text"])

    def test_two_digit_fiscal_year_is_2000_based(self):
        self._add_narrative({
            "pe_number": "0605003A",
            "agency": "Army",
            "fiscal_year": 2030,
            "source_file": "fy27_transfer.xml",
            "text": "Funding was transferred to PE 0605004A in FY27.",
        })
        self.session.commit()

        edges = detect_narrative_transfers(self.session)

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].first_fy_after, 2027)
        self.assertEqual(edges[0].confidence, 0.9)

    def test_pe_suffix_must_use_uppercase_alphanumerics(self):
        self._add_narrative({
            "pe_number": "0605005A",
            "agency": "Army",
            "fiscal_year": 2027,
            "source_file": "lowercase_citation.xml",
            "text": "Funding was transferred to PE 0605006a in FY 2027.",
        })
        self._add_narrative({
            "pe_number": "0605007a",
            "agency": "Army",
            "fiscal_year": 2027,
            "source_file": "lowercase_row.xml",
            "text": "Funding was transferred to PE 0605008A in FY 2027.",
        })
        self.session.commit()

        edges = detect_narrative_transfers(self.session)

        self.assertEqual(edges, [])

    def test_duplicate_edge_keeps_first_source_file_and_row_id(self):
        first_sentence = "Funding was transferred to PE 0605011A in FY 2025."
        self._add_narrative({
            "pe_number": "0605010A",
            "agency": "Army",
            "fiscal_year": 2027,
            "source_file": "a_source.xml",
            "text": first_sentence,
        })
        self._add_narrative({
            "pe_number": "0605010A",
            "agency": "Army",
            "fiscal_year": 2027,
            "source_file": "a_source.xml",
            "text": "Funding was transferred to PE 0605011A in FY 2026.",
        })
        self._add_accomplishment({
            "pe_number": "0605010A",
            "agency": "Army",
            "fiscal_year": 2027,
            "source_file": "z_source.xml",
            "text": "Funding was transferred to PE 0605011A in FY 2027.",
        })
        self.session.commit()

        edges = detect_narrative_transfers(self.session)

        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].evidence_source, "a_source.xml")
        self.assertEqual(edges[0].evidence_text, first_sentence)
        self.assertEqual(edges[0].first_fy_after, 2025)


if __name__ == "__main__":
    unittest.main()
