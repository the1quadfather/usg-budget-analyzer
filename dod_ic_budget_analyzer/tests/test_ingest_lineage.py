"""Tests for replacing derived Program Element lineage rows."""

import json
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from storage.db import Base, PEAccomplishment, PELineage, PENarrative
from storage.ingest_lineage import ingest_lineage


LINEAGE_FIXTURE = Path(__file__).parent / "fixtures" / "lineage_sentences.json"


class IngestLineageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        cases = json.loads(LINEAGE_FIXTURE.read_text(encoding="utf-8"))
        for index, case in enumerate(cases):
            if index % 2 == 0:
                self.session.add(PENarrative(
                    pe_number=case["pe_number"],
                    agency=case["agency"],
                    fiscal_year=case["fiscal_year"],
                    description=case["text"],
                    source_file=case["source_file"],
                ))
            else:
                self.session.add(PEAccomplishment(
                    pe_number=case["pe_number"],
                    agency=case["agency"],
                    fiscal_year=case["fiscal_year"],
                    year_label="Description",
                    text=case["text"],
                    source_file=case["source_file"],
                ))
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _hashes(self) -> set[str]:
        return set(self.session.execute(
            select(PELineage.content_hash)
        ).scalars())

    def test_two_runs_leave_three_rows_with_identical_hashes(self):
        first = ingest_lineage(self.session)
        first_hashes = self._hashes()

        second = ingest_lineage(self.session)
        second_hashes = self._hashes()

        expected = {"ba_renumber": 0, "narrative": 3, "total": 3}
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(len(first_hashes), 3)
        self.assertEqual(first_hashes, second_hashes)
        self.assertEqual(
            self.session.query(PELineage).count(),
            3,
        )


if __name__ == "__main__":
    unittest.main()
