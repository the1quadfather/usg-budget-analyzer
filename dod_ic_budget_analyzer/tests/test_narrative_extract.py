"""Pure-function tests for the bounded narrative extraction batch."""

import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

import config
from analysis.ai_budget import token_cost
from analysis.narrative_extract import (
    PROMPT_VERSION,
    build_worklist,
    estimate_cost,
    locate_sentence,
    text_hash,
    verify_facts,
    write_results,
)
from storage.db import (
    Base,
    NarrativeExtraction,
    NarrativeFact,
    PENarrative,
)


class LocateSentenceTests(unittest.TestCase):
    def test_exact_hit(self):
        text = "Opening. The contractor is Acme Systems. Closing."

        self.assertEqual(locate_sentence(text, "The contractor is Acme Systems."),
                         (9, 40))

    def test_whitespace_normalised_hit_maps_to_original_offsets(self):
        text = "Opening. The   contractor\nis Acme Systems. Closing."

        start, end = locate_sentence(
            text, "The contractor is Acme Systems."
        )

        self.assertEqual(text[start:end],
                         "The   contractor\nis Acme Systems.")

    def test_miss(self):
        self.assertIsNone(locate_sentence("An exact source.", "A made-up sentence."))


class VerifyFactsTests(unittest.TestCase):
    def test_filters_invalid_facts_and_keeps_exact_offsets(self):
        text = "Acme Systems will test Falcon at White Sands."
        raw = [
            {
                "fact_type": "contractor",
                "value": "  Acme Systems  ",
                "sentence": text,
            },
            {"fact_type": "unknown", "value": "Falcon", "sentence": text},
            {"fact_type": "location", "value": "  ", "sentence": text},
            {
                "fact_type": "test_event",
                "value": "Falcon",
                "sentence": "This sentence is not present.",
            },
        ]

        kept, dropped = verify_facts(raw, text)

        self.assertEqual(dropped, 3)
        self.assertEqual(kept, [{
            "fact_type": "contractor",
            "value": "Acme Systems",
            "sentence": text,
            "char_start": 0,
            "char_end": len(text),
        }])


class EstimateCostTests(unittest.TestCase):
    def test_two_text_estimate_equals_token_cost_sum(self):
        work = [{"text": "a" * 400}, {"text": "b" * 804}]
        expected_inputs = [400, 501]
        expected_cost = sum(
            token_cost(config.GEMINI_MODEL, input_tokens, 200, 512)
            for input_tokens in expected_inputs
        )

        estimate = estimate_cost(work)

        self.assertEqual(estimate["items"], 2)
        self.assertEqual(estimate["input_tokens"], sum(expected_inputs))
        self.assertEqual(estimate["output_tokens"], 400)
        self.assertEqual(estimate["thought_tokens"], 1024)
        self.assertAlmostEqual(estimate["usd"], expected_cost)


class ExtractionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _add_narrative(self, fiscal_year: int, text: str,
                       project_number: str = "") -> PENarrative:
        narrative = PENarrative(
            pe_number="0601234A",
            agency="Army",
            fiscal_year=fiscal_year,
            project_number=project_number,
            description=text,
            source_file=f"fy{fiscal_year}.xml",
        )
        self.session.add(narrative)
        self.session.flush()
        return narrative

    def test_worklist_deduplicates_and_skips_completed_text(self):
        old = self._add_narrative(2026, "Shared narrative.")
        latest = self._add_narrative(2027, "Shared narrative.")
        self._add_narrative(2028, "Project text.", project_number="P001")
        self.session.commit()

        work = build_worklist(self.session, limit=10)

        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["narrative_id"], latest.id)
        self.assertNotEqual(work[0]["narrative_id"], old.id)

        self.session.add(NarrativeExtraction(
            narrative_table="pe_narratives",
            narrative_id=latest.id,
            text_hash=text_hash(latest.description),
            model=config.GEMINI_MODEL,
            prompt_version=PROMPT_VERSION,
            fact_count=0,
            dropped_count=0,
            input_tokens=1,
            output_tokens=1,
            thought_tokens=1,
            est_cost_usd=0.0,
        ))
        self.session.commit()

        self.assertEqual(build_worklist(self.session, limit=10), [])

    def test_write_results_twice_inserts_once(self):
        narrative = self._add_narrative(
            2027, "Acme Systems supports the Falcon program."
        )
        self.session.commit()
        item = {
            "narrative_table": "pe_narratives",
            "narrative_id": narrative.id,
            "pe_number": narrative.pe_number,
            "agency": narrative.agency,
            "fiscal_year": narrative.fiscal_year,
            "text": narrative.description,
        }
        kept, dropped = verify_facts([{
            "fact_type": "contractor",
            "value": "Acme Systems",
            "sentence": narrative.description,
        }], narrative.description)
        usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "thought_tokens": 30,
        }

        first = write_results(
            self.session, item, kept, dropped, usage, 0.001
        )
        second = write_results(
            self.session, item, kept, dropped, usage, 0.001
        )

        self.assertEqual((first, second), (1, 0))
        self.assertEqual(self.session.scalar(
            select(func.count(NarrativeFact.id))
        ), 1)
        self.assertEqual(self.session.scalar(
            select(func.count(NarrativeExtraction.id))
        ), 1)


if __name__ == "__main__":
    unittest.main()
