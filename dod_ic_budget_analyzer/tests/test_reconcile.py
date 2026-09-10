"""Tests for the R-1 and DD 1416 reconciliation core."""

from pathlib import Path
import sys
import tempfile
import unittest

import openpyxl
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.reconcile import _amount_columns, tie_out_dd1416, tie_out_r1
from storage.db import (
    Base,
    FundingLine,
    PEExecution,
    ProgramElement,
    SourceDocument,
)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.document = SourceDocument(
            filename="fy2027_r1.xlsx",
            document_type="R1",
            publication_year=2027,
        )
        ordinary = ProgramElement(
            source_document=self.document,
            pe_number="0601102A",
            program_name="Defense Research Sciences",
            agency="Army",
        )
        classified = ProgramElement(
            source_document=self.document,
            pe_number="",
            program_name="Classified Programs",
            agency="Army",
        )
        self.session.add_all([ordinary, classified])
        self.session.flush()

        amounts = [
            (ordinary.id, 40.0),
            (ordinary.id, 35.0),
            (ordinary.id, 30.0),
            (classified.id, 45.0),
            (classified.id, 50.0),
        ]
        self.session.add_all([
            FundingLine(
                program_element_id=program_element_id,
                source_document_id=self.document.id,
                pb_cycle=2027,
                fiscal_year=2027,
                funding_type="BY Request",
                amount_thousands=amount,
            )
            for program_element_id, amount in amounts
        ])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def _write_workbook(raw_dir: Path) -> None:
        workbook_path = raw_dir / "2027" / "rdtee" / "fy2027_r1.xlsx"
        workbook_path.parent.mkdir(parents=True)
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Exhibit R-1"
        worksheet["G1"] = "Total of Displayed Rows"
        worksheet["J1"] = 250.0
        worksheet.append([
            "Account",
            "Account Title",
            "Organization",
            "Budget Activity",
            "Budget Activity Title",
            "Line Number",
            "PE/BLI",
            "Program Element/Budget Line Item (BLI) Title",
            "Include In TOA",
            "FY 2027 Discretionary Request",
            "Classification",
        ])
        worksheet.append([
            "2040A", "RDT&E, Army", "A", "01", "Basic research", "1",
            "0601102A", "Defense Research Sciences", "Y", 105.0, "U",
        ])
        worksheet.append([
            "2040A", "RDT&E, Army", "A", "01", "Basic research", "2",
            "9999999999", "Classified Programs", "Y", 95.0, "C",
        ])
        worksheet.append([
            "0130D", "Other Defense", "D", "01", "Other", "3",
            "0600000D", "Excluded program", "Y", 50.0, "U",
        ])
        workbook.save(workbook_path)
        workbook.close()

    def test_r1_ties_and_reports_excluded_account_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            self._write_workbook(raw_dir)
            rows = tie_out_r1(self.session, raw_dir)

        by_scope = {row.scope: row for row in rows}
        self.assertEqual(set(by_scope), {"DoD", "2040A", "0130D"})

        dod = by_scope["DoD"]
        self.assertEqual(dod.ingested_k, 200.0)
        self.assertEqual(dod.reference_k, 200.0)
        self.assertEqual(dod.residual_k, 0.0)
        self.assertEqual(dod.residual_pct, 0.0)
        self.assertEqual(dod.status, "ties")

        army = by_scope["2040A"]
        self.assertEqual(army.agency, "Army")
        self.assertEqual(army.ingested_k, 200.0)
        self.assertEqual(army.reference_k, 200.0)
        self.assertEqual(army.residual_k, 0.0)
        self.assertEqual(army.status, "ties")

        excluded = by_scope["0130D"]
        self.assertIsNone(excluded.agency)
        self.assertEqual(excluded.ingested_k, 0.0)
        self.assertEqual(excluded.reference_k, 50.0)
        self.assertEqual(excluded.residual_k, -50.0)
        self.assertEqual(excluded.residual_pct, -100.0)
        self.assertEqual(excluded.status, "outside_tolerance")
        self.assertEqual(
            excluded.explanation,
            "account not ingested (non-RDT&E appropriation)",
        )

    def test_r1_missing_workbook_has_no_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = tie_out_r1(self.session, Path(tmp))

        row = next(row for row in rows if row.scope == "DoD")
        self.assertEqual(row.status, "no_reference")
        self.assertIsNone(row.reference_k)
        self.assertIsNone(row.residual_k)
        self.assertIsNone(row.residual_pct)
        self.assertIn("python acquisition/comptroller_scraper.py", row.explanation)
        self.assertIn("--xlsx", row.explanation)
        self.assertIn("--years 2027", row.explanation)
        self.assertIn("--exhibits rdtee", row.explanation)

    def test_r1_column_priority_keeps_total_as_last_resort(self):
        headers = [
            "FY 2024 Total",
            "FY 2026 Total",
            "FY 2026 Disc Request",
            "FY 2026 Reconciliation Request",
        ]

        columns = _amount_columns(headers, 2026)

        self.assertEqual(columns[2024]["discretionary"], 0)
        self.assertEqual(columns[2026]["discretionary"], 2)
        self.assertEqual(columns[2026]["mandatory"], 3)

    def test_dd1416_uses_only_latest_report_date(self):
        reference = FundingLine(
            program_element_id=self.document.program_elements[0].id,
            source_document_id=self.document.id,
            pb_cycle=2026,
            fiscal_year=2025,
            funding_type="CY Request",
            amount_thousands=120.0,
        )
        execution_rows = [
            ("2025-03-31", "old", 999.0),
            ("2025-06-30", "latest-a", 70.0),
            ("2025-06-30", "latest-b", 50.0),
        ]
        self.session.add(reference)
        self.session.add_all([
            PEExecution(
                pe_number=f"060110{index}A",
                agency="Army",
                appropriation="2040A",
                fy_start=2025,
                fy_end=2026,
                report_date=report_date,
                line_number=str(index),
                program_title=title,
                enacted_k=amount,
                source_file=f"{title}.xlsx",
                content_hash=f"hash-{index}",
            )
            for index, (report_date, title, amount) in enumerate(
                execution_rows, start=1
            )
        ])
        self.session.commit()

        rows = tie_out_dd1416(self.session)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.pb_cycle, 2026)
        self.assertEqual(row.fiscal_year, 2025)
        self.assertEqual(row.scope, "2040A")
        self.assertEqual(row.agency, "Army")
        self.assertEqual(row.stream, "discretionary")
        self.assertEqual(row.basis, "CY Request")
        self.assertEqual(row.ingested_k, 120.0)
        self.assertEqual(row.reference_k, 120.0)
        self.assertEqual(row.residual_k, 0.0)
        self.assertEqual(row.status, "ties")


if __name__ == "__main__":
    unittest.main()
