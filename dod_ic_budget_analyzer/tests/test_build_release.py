import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from scripts.build_release import archive_checks, manifest_for, release_notes
from storage.db import AICache, Base, ProgramElement, SearchLog, SourceDocument


class BuildReleaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _archive_checks(self) -> list[str]:
        connection = self.engine.raw_connection()
        try:
            return archive_checks(connection)
        finally:
            connection.close()

    def test_archive_checks_accept_empty_runtime_tables(self):
        self.assertEqual(self._archive_checks(), [])

    def test_archive_checks_reject_grounded_ai_cache_row(self):
        with Session(self.engine) as session:
            session.add(AICache(
                cache_key="annual-signal",
                task="annual_signal",
                params_json="{}",
                model="test-model",
                payload_json="{}",
                expires_at=datetime(2030, 1, 1),
            ))
            session.commit()

        failures = self._archive_checks()

        self.assertEqual(len(failures), 1)
        self.assertIn("ai_cache", failures[0])
        self.assertIn("compliance query", failures[0])

    def test_archive_checks_reject_search_log_row(self):
        with Session(self.engine) as session:
            session.add(SearchLog(query="test search"))
            session.commit()

        failures = self._archive_checks()

        self.assertEqual(len(failures), 1)
        self.assertIn("search_log", failures[0])

    def test_manifest_has_exact_keys_counts_and_source_document(self):
        with Session(self.engine) as session:
            document = SourceDocument(
                filename="r1_test.xlsx",
                document_type="R1",
                publication_year=2027,
                source_url="https://example.test/r1_test.xlsx",
                content_hash="abc123",
            )
            session.add(ProgramElement(
                source_document=document,
                pe_number="0600001A",
                program_name="Test program",
                agency="Army",
            ))
            session.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "usg_budgets.db.gz"
            archive.write_bytes(b"test archive")
            connection = self.engine.raw_connection()
            try:
                manifest = manifest_for(connection, archive)
            finally:
                connection.close()

        self.assertEqual(set(manifest), {
            "built_at",
            "archive_sha256",
            "archive_bytes",
            "tables",
            "runtime_tables",
            "source_documents",
        })
        self.assertEqual(manifest["tables"]["program_elements"], 1)
        self.assertEqual(manifest["source_documents"], [{
            "filename": "r1_test.xlsx",
            "document_type": "R1",
            "source_url": "https://example.test/r1_test.xlsx",
            "content_hash": "abc123",
        }])

    def test_release_notes_identify_first_release(self):
        current = {
            "archive_sha256": "abc123",
            "tables": {"pe_lineage": 405},
            "runtime_tables": {},
        }

        notes = release_notes(None, current, "2026-09-18")

        self.assertIn(
            "First release; no previous manifest to compare.",
            notes,
        )

    def test_release_notes_report_changed_table(self):
        previous = {
            "_release_date": "2026-09-17",
            "tables": {"pe_lineage": 433},
        }
        current = {
            "archive_sha256": "abc123",
            "tables": {"pe_lineage": 405},
            "runtime_tables": {},
        }

        notes = release_notes(previous, current, "2026-09-18")

        self.assertIn("pe_lineage: 433 -> 405 (-28)", notes)


if __name__ == "__main__":
    unittest.main()
