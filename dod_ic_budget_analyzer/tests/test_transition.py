"""Tests for procurement-transition candidate generation."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.transition import is_research_pe, propose_transitions
from storage.db import (
    Base,
    PEAccomplishment,
    ProcurementLine,
    ProgramElement,
    SourceDocument,
)


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.document = SourceDocument(
            filename="synthetic_p1.xlsx",
            document_type="P1",
            publication_year=2027,
        )
        self.session.add(self.document)
        self.session.flush()
        semantic = patch(
            "analysis.transition._semantic_candidates", return_value=[]
        )
        semantic.start()
        self.addCleanup(semantic.stop)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _program(self, pe_number: str, name: str,
                 agency: str = "Air Force") -> None:
        self.session.add(ProgramElement(
            source_document_id=self.document.id,
            pe_number=pe_number,
            program_name=name,
            agency=agency,
        ))

    def _procurement(self, bli: str, title: str, appropriation: str,
                     agency: str = "Air Force") -> None:
        self.session.add(ProcurementLine(
            source_document_id=self.document.id,
            bli=bli,
            line_item_title=title,
            agency=agency,
            appropriation=appropriation,
            budget_activity=1,
            line_number=bli[:10],
            bsa="01",
            bsa_title="Synthetic",
            cost_type="C",
            cost_type_title="Cost",
            fiscal_year=2027,
            funding_type="BY Request",
            amount_thousands=100.0,
            quantity=None,
            pb_cycle=2027,
            content_hash=f"hash-{bli}-{appropriation}",
        ))

    def test_exact_title_fuzzy_hit_ranks_first(self):
        self._program("0207146F", "F-15EX")
        self._procurement(
            "F015EX", "F-15EX", "Aircraft Procurement, Air Force"
        )
        self.session.commit()

        candidates = propose_transitions(
            self.session, "0207146F", "Air Force"
        )

        self.assertEqual(candidates[0].bli, "F015EX")
        self.assertEqual(candidates[0].strategy, "FUZZY")
        self.assertGreaterEqual(candidates[0].confidence, 0.95)

    def test_bli_citation_yields_narrative_evidence(self):
        self._program("0604258N", "Target Systems Development", "Navy")
        self._procurement(
            "2280", "Aerial Targets", "Weapons Procurement, Navy", "Navy"
        )
        sentence = (
            "FY 2019 funds were reprogrammed to the Weapons Procurement, "
            "Navy appropriation (BLI 2280)."
        )
        self.session.add(PEAccomplishment(
            pe_number="0604258N",
            agency="Navy",
            fiscal_year=2020,
            project_number="",
            title="Target Systems",
            year_label="FY 2019",
            accomplishment_fy=2019,
            funding_millions=1.0,
            text=f"Testing continued. {sentence} Follow-on work continued.",
            source_file="navy_test_book.pdf",
        ))
        self.session.commit()

        candidates = propose_transitions(
            self.session, "0604258N", "Navy"
        )
        candidate = next(item for item in candidates if item.bli == "2280")

        self.assertEqual(candidate.strategy, "NARRATIVE")
        self.assertEqual(candidate.evidence_text, sentence)
        self.assertEqual(candidate.evidence_source, "navy_test_book.pdf")

    def test_basic_research_without_similar_title_returns_empty(self):
        self._program("0601102A", "Defense Research Sciences", "Army")
        self._procurement(
            "2073GZ0410",
            "Heavy Combat Vehicle",
            "Procurement of Weapons and Tracked Combat Vehicles, Army",
            "Army",
        )
        self.session.commit()

        self.assertEqual(
            propose_transitions(self.session, "0601102A", "Army"), []
        )

    def test_research_pe_with_identical_procurement_title_returns_empty(self):
        self._program("0601999A", "Identical Research Vehicle", "Army")
        self._procurement(
            "RESEARCH01",
            "Identical Research Vehicle",
            "Other Procurement, Army",
            "Army",
        )
        self.session.commit()

        self.assertTrue(is_research_pe("0601999A"))
        self.assertEqual(
            propose_transitions(self.session, "0601999A", "Army"), []
        )

    def test_close_titles_mark_top_candidate_ambiguous(self):
        self._program("0609999F", "Falcon Strike Vehicle")
        self._procurement(
            "FALC01",
            "Falcon Strike Vehicle",
            "Aircraft Procurement, Air Force",
        )
        self._procurement(
            "FALC02",
            "Falcon Strike Vehicle Increment",
            "Aircraft Procurement, Air Force",
        )
        self.session.commit()

        candidates = propose_transitions(
            self.session, "0609999F", "Air Force"
        )

        self.assertGreaterEqual(len(candidates), 2)
        self.assertTrue(candidates[0].ambiguous)
        self.assertLessEqual(
            candidates[0].confidence - candidates[1].confidence, 0.1
        )

    def test_classified_program_returns_empty(self):
        self._program("0209999F", "Classified Programs")
        self._procurement(
            "SECRET", "Classified Programs", "Aircraft Procurement, Air Force"
        )
        self.session.commit()

        self.assertEqual(
            propose_transitions(self.session, "0209999F", "Air Force"), []
        )


if __name__ == "__main__":
    unittest.main()
