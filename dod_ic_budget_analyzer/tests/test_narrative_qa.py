import sys
import time
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.narrative_qa import INDEX_PATH, chunk_text, index_rows, retrieve
from storage.db import Base, PENarrative


class ChunkTextTests(unittest.TestCase):
    def test_short_sentences_stay_in_one_chunk(self):
        text = "  First sentence. Second sentence! Third sentence?  "

        self.assertEqual(chunk_text(text), [text.strip()])

    def test_sentences_pack_without_crossing_limit(self):
        sentences = [f"{letter * 499}." for letter in "ABCD"]
        text = " ".join(sentences)

        chunks = chunk_text(text)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 1500 for chunk in chunks))
        self.assertTrue(all(chunk.endswith(".") for chunk in chunks))
        self.assertEqual(" ".join(chunks), text)

    def test_long_sentence_is_not_split(self):
        text = f"{'A' * 1999}."

        self.assertEqual(chunk_text(text), [text])
        self.assertEqual(len(chunk_text(text)[0]), 2000)


class IndexRowsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _add_narrative(self, fiscal_year: int, text: str) -> None:
        self.session.add(PENarrative(
            pe_number="0603032F",
            agency="Air Force",
            fiscal_year=fiscal_year,
            project_number="",
            description=text,
            source_file=f"fy{fiscal_year}.xml",
        ))

    def test_latest_duplicate_is_kept_and_distinct_text_is_added(self):
        self._add_narrative(2026, "Repeated passage.")
        self._add_narrative(2027, "Repeated passage.")
        self.session.commit()

        rows = index_rows(self.session)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], 2027)

        self._add_narrative(2025, "Different passage.")
        self.session.commit()

        self.assertEqual(len(index_rows(self.session)), 2)


class RetrieveTests(unittest.TestCase):
    def test_shipped_index_retrieves_skyborg_and_reuses_loaded_model(self):
        if not INDEX_PATH.exists():
            self.skipTest("shipped narrative index is absent")

        passages = retrieve(
            "Skyborg autonomous aircraft vanguard program",
            k=3,
        )

        self.assertEqual(len(passages), 3)
        self.assertEqual(
            [passage.score for passage in passages],
            sorted(
                (passage.score for passage in passages),
                reverse=True,
            ),
        )
        self.assertIn("0603032F", {
            passage.pe_number for passage in passages
        })

        started = time.perf_counter()
        retrieve("Skyborg autonomous aircraft vanguard program", k=3)
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
