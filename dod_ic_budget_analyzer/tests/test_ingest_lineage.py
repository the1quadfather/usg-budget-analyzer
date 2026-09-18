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
from storage.db import ProgramElement, SourceDocument
from storage.ingest_lineage import ingest_lineage


LINEAGE_FIXTURE = Path(__file__).parent / "fixtures" / "lineage_sentences.json"


class IngestLineageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.document = SourceDocument(
            filename="synthetic_r2.xml",
            document_type="R1",
            publication_year=2027,
        )
        self.session.add(self.document)
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
        for pe_number, agency in (
            ("0603176BR", "Defense-Wide"),
            ("0603160BR", "Defense-Wide"),
            ("0602182A", "Army"),
            ("0602146A", "Army"),
            ("0602144A", "Army"),
            ("0605001A", "Army"),
            ("0605002A", "Army"),
            ("0604659N", "Navy"),
            ("0105519N", "Navy"),
        ):
            self._add_program_element(pe_number, agency)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _add_program_element(self, pe_number: str, agency: str) -> None:
        self.session.add(ProgramElement(
            source_document=self.document,
            pe_number=pe_number,
            program_name=f"Synthetic {pe_number}",
            agency=agency,
        ))

    def _hashes(self) -> set[str]:
        return set(self.session.execute(
            select(PELineage.content_hash)
        ).scalars())

    def test_two_runs_leave_three_rows_with_identical_hashes(self):
        first = ingest_lineage(self.session)
        first_hashes = self._hashes()

        second = ingest_lineage(self.session)
        second_hashes = self._hashes()

        expected = {
            "ba_renumber": 0,
            "narrative": 3,
            "total": 3,
            "rejected_unknown_predecessor": 0,
            "rejected_unknown_successor": 0,
        }
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(len(first_hashes), 3)
        self.assertEqual(first_hashes, second_hashes)
        self.assertEqual(
            self.session.query(PELineage).count(),
            3,
        )

    def test_unseeded_successor_is_rejected(self):
        self.session.query(ProgramElement).filter(
            ProgramElement.pe_number == "0105519N",
            ProgramElement.agency == "Navy",
        ).delete()
        self.session.commit()

        result = ingest_lineage(self.session)

        self.assertEqual(result, {
            "ba_renumber": 0,
            "narrative": 2,
            "total": 2,
            "rejected_unknown_predecessor": 0,
            "rejected_unknown_successor": 1,
        })
        self.assertEqual(self.session.query(PELineage).count(), 2)


if __name__ == "__main__":
    unittest.main()
