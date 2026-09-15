"""Tests for deterministic budget change-feed events."""

from inspect import signature
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analysis.changefeed import (
    diff_vintages,
    new_committee_actions,
    new_reprogramming,
)
from storage.db import (
    Base,
    FundingLine,
    PECongressionalAction,
    PEExecution,
    ProgramElement,
    SourceDocument,
)


class ChangeFeedTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.document = SourceDocument(
            filename="synthetic_changefeed.xlsx",
            document_type="R1",
            publication_year=2027,
        )
        self.session.add(self.document)
        self.session.flush()
        self.programs: dict[tuple[str, str], ProgramElement] = {}
        self.hash_counter = 0

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _next_hash(self) -> str:
        self.hash_counter += 1
        return f"{self.hash_counter:064x}"

    def _program(
        self,
        pe_number: str,
        program_name: str,
        agency: str = "Army",
    ) -> ProgramElement:
        key = (pe_number, agency)
        if key not in self.programs:
            self.programs[key] = ProgramElement(
                source_document=self.document,
                pe_number=pe_number,
                program_name=program_name,
                agency=agency,
                budget_activity=5,
            )
            self.session.add(self.programs[key])
            self.session.flush()
        return self.programs[key]

    def _add_funding(
        self,
        pe_number: str,
        program_name: str,
        pb_cycle: int,
        fiscal_year: int,
        funding_type: str,
        amount_k: float,
        agency: str = "Army",
    ) -> None:
        program = self._program(pe_number, program_name, agency)
        self.session.add(FundingLine(
            program_element_id=program.id,
            source_document_id=self.document.id,
            pb_cycle=pb_cycle,
            fiscal_year=fiscal_year,
            funding_type=funding_type,
            amount_thousands=amount_k,
        ))

    def _add_committee_action(
        self,
        pe_number: str,
        chamber: str,
        delta_k: float,
        *,
        line_number: str,
        rationale: str,
    ) -> None:
        program_name = "Committee Test Program"
        self._program(pe_number, program_name)
        self.session.add(PECongressionalAction(
            pe_number=pe_number,
            agency="Army",
            fiscal_year=2027,
            chamber=chamber,
            report_citation=f"{chamber} Report",
            line_number=line_number,
            program_title=program_name,
            request_k=100.0,
            committee_delta_k=delta_k,
            authorized_k=100.0 + delta_k,
            rationale=rationale,
            content_hash=self._next_hash(),
        ))

    def _add_execution(
        self,
        pe_number: str,
        report_date: str,
        *,
        above_k: float | None,
        below_k: float | None,
        line_number: str | None = "10",
        budget_activity: int = 5,
        fy_start: int = 2025,
        program_name: str = "Execution Test Program",
    ) -> None:
        self._program(pe_number, program_name)
        self.session.add(PEExecution(
            source_document_id=self.document.id,
            pe_number=pe_number,
            agency="Army",
            appropriation="RDTE",
            fy_start=fy_start,
            fy_end=fy_start + 1,
            report_date=report_date,
            line_number=line_number,
            program_title=program_name,
            budget_activity=budget_activity,
            above_threshold_reprog_k=above_k,
            below_threshold_reprog_k=below_k,
            source_file=f"execution_{self.hash_counter + 1}.xlsx",
            content_hash=self._next_hash(),
        ))

    @staticmethod
    def _sort_key(event) -> tuple[str, str, str, int]:
        return event.kind, event.agency, event.pe_number, event.fiscal_year

    def test_swing_threshold_default_is_named_and_documented(self):
        parameter = signature(diff_vintages).parameters["swing_pct"]

        self.assertEqual(parameter.default, 20.0)
        self.assertIn("defaults to 20.0", diff_vintages.__doc__)

    def _assert_permalink(self, event) -> None:
        self.assertEqual(
            event.permalink,
            f"?tab=finder&pe={event.pe_number}&agency={event.agency}",
        )

    def test_diff_vintages_covers_required_classifications(self):
        self._add_funding(
            "0605001A", "New Start", 2027, 2027, "BY Request", 120.0
        )
        self._add_funding(
            "0605002A", "Termination", 2026, 2026, "BY Request", 80.0
        )
        self._add_funding(
            "0605003A", "Large Swing", 2026, 2026, "BY Request", 100.0
        )
        self._add_funding(
            "0605003A", "Large Swing", 2027, 2026, "CY Request", 130.0
        )
        self._add_funding(
            "0605004A", "Small Swing", 2026, 2026, "BY Request", 100.0
        )
        self._add_funding(
            "0605004A", "Small Swing", 2027, 2026, "CY Request", 119.0
        )
        self._add_funding(
            "0605005A", "Zeroed Program", 2026, 2026, "BY Request", 100.0
        )
        self._add_funding(
            "0605005A", "Zeroed Program", 2027, 2026, "CY Request", 0.0
        )
        self._add_funding(
            "0605006A", "Cross FY Trap", 2027, 2025, "PY Actual", 100.0
        )
        self._add_funding(
            "0605006A", "Cross FY Trap", 2027, 2026, "CY Request", 250.0
        )
        # Mandatory rows are a separate stream and must not alter the swing.
        self._add_funding(
            "0605003A", "Large Swing", 2026, 2026, "BY Mandatory", 900.0
        )
        self._add_funding(
            "0605003A", "Large Swing", 2027, 2026, "CY Mandatory", 1800.0
        )
        self.session.commit()

        events = diff_vintages(self.session, 2026, 2027)

        self.assertEqual(events, diff_vintages(self.session, 2026, 2027))
        keys = [self._sort_key(event) for event in events]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(events), 4)
        by_pe = {event.pe_number: event for event in events}
        self.assertEqual(
            set(by_pe),
            {"0605001A", "0605002A", "0605003A", "0605005A"},
        )

        new_start = by_pe["0605001A"]
        self.assertEqual(new_start.kind, "new_start")
        self.assertEqual(new_start.fiscal_year, 2027)
        self.assertIsNone(new_start.before_k)
        self.assertEqual(new_start.after_k, 120.0)

        termination = by_pe["0605002A"]
        self.assertEqual(termination.kind, "termination")
        self.assertEqual(termination.fiscal_year, 2026)
        self.assertEqual(termination.before_k, 80.0)
        self.assertIsNone(termination.after_k)

        swing = by_pe["0605003A"]
        self.assertEqual(swing.kind, "swing")
        self.assertEqual(swing.fiscal_year, 2026)
        self.assertEqual(swing.before_k, 100.0)
        self.assertEqual(swing.after_k, 130.0)
        self.assertAlmostEqual(swing.pct_change, 30.0)

        zeroed = by_pe["0605005A"]
        self.assertEqual(zeroed.kind, "swing")
        self.assertEqual(zeroed.before_k, 100.0)
        self.assertEqual(zeroed.after_k, 0.0)
        self.assertAlmostEqual(zeroed.pct_change, -100.0)
        self.assertNotEqual(zeroed.kind, "termination")
        for event in events:
            self._assert_permalink(event)

    def test_diff_vintages_sums_same_basis_funding_rows(self):
        for amount in (40.0, 60.0):
            self._add_funding(
                "0605007A", "Split Funding Lines", 2026, 2026,
                "BY Request", amount,
            )
        for amount in (70.0, 80.0):
            self._add_funding(
                "0605007A", "Split Funding Lines", 2027, 2026,
                "CY Request", amount,
            )
        self.session.commit()

        events = diff_vintages(self.session, 2026, 2027)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "swing")
        self.assertEqual(events[0].before_k, 100.0)
        self.assertEqual(events[0].after_k, 150.0)
        self.assertAlmostEqual(events[0].pct_change, 50.0)

    def test_committee_actions_keep_chambers_separate_and_lead_detail(self):
        self._add_committee_action(
            "0605101A", "House", 20.0,
            line_number="1", rationale="Program Increase [+20]",
        )
        self._add_committee_action(
            "0605101A", "Senate", -10.0,
            line_number="2", rationale="Program Reduction [-10]",
        )
        self._add_committee_action(
            "0605102A", "House", 0.0,
            line_number="3", rationale="No Change",
        )
        self.session.commit()

        events = new_committee_actions(self.session, 2027)

        self.assertEqual(events, new_committee_actions(self.session, 2027))
        self.assertEqual(len(events), 2)
        self.assertEqual(
            [self._sort_key(event) for event in events],
            sorted(self._sort_key(event) for event in events),
        )
        by_chamber = {
            chamber: next(
                event for event in events if event.detail.startswith(chamber)
            )
            for chamber in ("House", "Senate")
        }
        self.assertEqual(
            by_chamber["House"].detail,
            "House: Program Increase [+20]",
        )
        self.assertEqual(
            by_chamber["Senate"].detail,
            "Senate: Program Reduction [-10]",
        )
        self.assertEqual(by_chamber["House"].before_k, 100.0)
        self.assertEqual(by_chamber["House"].after_k, 120.0)
        self.assertEqual(by_chamber["Senate"].before_k, 100.0)
        self.assertEqual(by_chamber["Senate"].after_k, 90.0)
        for chamber, event in by_chamber.items():
            self.assertTrue(event.detail.startswith(chamber))
            self.assertNotIn("appropriated", event.detail.lower())
            self.assertNotIn("enacted", event.detail.lower())
            self.assertIsNone(event.from_vintage)
            self.assertIsNone(event.to_vintage)
            self._assert_permalink(event)

    def test_reprogramming_keeps_above_and_below_changes_separate(self):
        self._add_execution(
            "0605201A", "2025-09-30", above_k=999.0, below_k=999.0
        )
        self._add_execution(
            "0605201A", "2025-12-31", above_k=10.0, below_k=-2.0
        )
        self._add_execution(
            "0605201A", "2026-03-31", above_k=25.0, below_k=-7.0
        )
        self.session.commit()

        events = new_reprogramming(self.session, "2026-03-31")

        self.assertEqual(events, new_reprogramming(self.session, "2026-03-31"))
        self.assertEqual(len(events), 2)
        self.assertEqual(
            [self._sort_key(event) for event in events],
            sorted(self._sort_key(event) for event in events),
        )
        by_detail = {event.detail: event for event in events}
        above = next(
            event for detail, event in by_detail.items()
            if "above-threshold reprogramming" in detail
        )
        below = next(
            event for detail, event in by_detail.items()
            if "below-threshold reprogramming" in detail
        )
        self.assertEqual((above.before_k, above.after_k), (10.0, 25.0))
        self.assertEqual((below.before_k, below.after_k), (-2.0, -7.0))
        for event in events:
            self.assertEqual(event.kind, "reprogramming")
            self.assertEqual(event.fiscal_year, 2025)
            self.assertEqual(event.from_vintage, 2025)
            self.assertEqual(event.to_vintage, 2026)
            self._assert_permalink(event)

    def test_reprogramming_budget_activities_are_distinct_keys(self):
        for budget_activity, previous, current in (
            (4, 1.0, 3.0),
            (7, 10.0, 15.0),
        ):
            self._add_execution(
                "0605206A", "2025-12-31", above_k=previous, below_k=0.0,
                budget_activity=budget_activity,
            )
            self._add_execution(
                "0605206A", "2026-03-31", above_k=current, below_k=0.0,
                budget_activity=budget_activity,
            )
        self.session.commit()

        events = new_reprogramming(self.session, "2026-03-31")

        self.assertEqual(len(events), 2)
        self.assertEqual(
            {(event.before_k, event.after_k) for event in events},
            {(1.0, 3.0), (10.0, 15.0)},
        )

    def test_reprogramming_skips_a_current_date_key_collision(self):
        self._add_execution(
            "0605202A", "2025-12-31", above_k=0.0, below_k=0.0
        )
        self._add_execution(
            "0605202A", "2026-03-31", above_k=10.0, below_k=0.0
        )
        self._add_execution(
            "0605202A", "2026-03-31", above_k=20.0, below_k=0.0
        )
        self._add_execution(
            "0605203A", "2025-12-31", above_k=0.0, below_k=0.0
        )
        self._add_execution(
            "0605203A", "2026-03-31", above_k=5.0, below_k=0.0
        )
        self.session.commit()

        events = new_reprogramming(self.session, "2026-03-31")

        self.assertFalse(any(event.pe_number == "0605202A" for event in events))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].pe_number, "0605203A")

    def test_reprogramming_skips_a_previous_date_key_collision(self):
        self._add_execution(
            "0605204A", "2025-09-30", above_k=1.0, below_k=0.0
        )
        self._add_execution(
            "0605204A", "2025-12-31", above_k=2.0, below_k=0.0
        )
        self._add_execution(
            "0605204A", "2025-12-31", above_k=3.0, below_k=0.0
        )
        self._add_execution(
            "0605204A", "2026-03-31", above_k=4.0, below_k=0.0
        )
        self.session.commit()

        events = new_reprogramming(self.session, "2026-03-31")

        self.assertEqual(events, [])

    def test_reprogramming_matches_null_line_numbers_as_one_key(self):
        self._add_execution(
            "0605205A", "2025-12-31", above_k=0.0, below_k=0.0,
            line_number=None, budget_activity=3,
        )
        self._add_execution(
            "0605205A", "2026-03-31", above_k=9.0, below_k=0.0,
            line_number=None, budget_activity=3,
        )
        self.session.commit()

        events = new_reprogramming(self.session, "2026-03-31")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].pe_number, "0605205A")
        self.assertEqual((events[0].before_k, events[0].after_k), (0.0, 9.0))
        self.assertEqual(events[0].from_vintage, 2025)

    def test_committee_and_reprogramming_sort_deterministically(self):
        self._add_committee_action(
            "0605302A", "House", 1.0,
            line_number="1", rationale="Later PE",
        )
        self._add_committee_action(
            "0605301A", "House", 1.0,
            line_number="2", rationale="Earlier PE",
        )
        for pe_number in ("0605402A", "0605401A"):
            self._add_execution(
                pe_number, "2025-12-31", above_k=0.0, below_k=0.0
            )
            self._add_execution(
                pe_number, "2026-03-31", above_k=1.0, below_k=0.0
            )
        self.session.commit()

        committee = new_committee_actions(self.session, 2027)
        reprogramming = new_reprogramming(self.session, "2026-03-31")

        self.assertEqual(committee, new_committee_actions(self.session, 2027))
        self.assertEqual(
            [self._sort_key(event) for event in committee],
            sorted(self._sort_key(event) for event in committee),
        )
        self.assertEqual(
            reprogramming,
            new_reprogramming(self.session, "2026-03-31"),
        )
        self.assertEqual(
            [self._sort_key(event) for event in reprogramming],
            sorted(self._sort_key(event) for event in reprogramming),
        )


if __name__ == "__main__":
    unittest.main()
