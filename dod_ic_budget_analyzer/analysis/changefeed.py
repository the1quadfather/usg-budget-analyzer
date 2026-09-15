"""Deterministic PE-level change events across the stored budget sources."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, TypeAlias

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from storage.db import (
    FundingLine,
    PECongressionalAction,
    PEExecution,
    ProgramElement,
)


Kind = Literal[
    "new_start",
    "termination",
    "swing",
    "committee_action",
    "reprogramming",
]


@dataclass(frozen=True)
class ChangeEvent:
    pe_number: str
    agency: str
    program_name: str
    kind: Kind
    fiscal_year: int
    from_vintage: int | None
    to_vintage: int | None
    before_k: float | None
    after_k: float | None
    pct_change: float | None
    detail: str
    permalink: str


_DISCRETIONARY_TYPES = frozenset({"PY Actual", "CY Request", "BY Request"})
_REPROGRAMMING_COLUMNS = (
    ("above_threshold_reprog_k", "above-threshold reprogramming"),
    ("below_threshold_reprog_k", "below-threshold reprogramming"),
)
_EXECUTION_BATCH_SIZE = 100

_ProgramKey: TypeAlias = tuple[str, str]
_FundingKey: TypeAlias = tuple[str, str, int, int]
_ProgramYearKey: TypeAlias = tuple[str, str, int]
_ExecutionKey: TypeAlias = tuple[str, str, int, str | None, int | None]


def _permalink(pe_number: str, agency: str) -> str:
    return f"?tab=finder&pe={pe_number}&agency={agency}"


def _optional_number_key(value: int | float | None) -> tuple[bool, float]:
    return value is not None, float(value or 0.0)


def _event_sort_key(event: ChangeEvent) -> tuple:
    """Required public ordering plus deterministic ties for repeated PE rows."""
    return (
        event.kind,
        event.agency,
        event.pe_number,
        event.fiscal_year,
        event.detail,
        event.program_name,
        _optional_number_key(event.from_vintage),
        _optional_number_key(event.to_vintage),
        _optional_number_key(event.before_k),
        _optional_number_key(event.after_k),
        _optional_number_key(event.pct_change),
        event.permalink,
    )


def _sorted_events(events: list[ChangeEvent]) -> list[ChangeEvent]:
    return sorted(events, key=_event_sort_key)


def _funding_label(labels: set[str]) -> str:
    return " + ".join(sorted(labels))


def _vintage_detail(
    older_pb: int,
    newer_pb: int,
    before_type: str | None,
    after_type: str | None,
) -> str:
    if before_type and after_type and before_type != after_type:
        return f"PB{newer_pb} {after_type} vs PB{older_pb} {before_type}"
    basis = after_type or before_type or "Request"
    return f"PB{newer_pb} vs PB{older_pb} {basis}"


def diff_vintages(
    session: Session,
    older_pb: int,
    newer_pb: int,
    *,
    swing_pct: float = 20.0,
) -> list[ChangeEvent]:
    """Compare like fiscal years in two PB vintages.

    Same-basis funding lines are summed to the PE level, and mandatory rows are
    excluded from amounts. New starts and terminations still use all funding
    types to decide whether the PE is absent from a vintage. One termination is
    emitted for an absent PE, using its latest nonzero discretionary amount.
    ``swing_pct`` is the materiality threshold and defaults to 20.0 percent. A
    budget-activity renumbering intentionally appears here as a termination
    plus a new start; T11d will cross-reference those events with
    ``pe_lineage``.
    """
    statement = (
        select(
            ProgramElement.pe_number,
            ProgramElement.agency,
            ProgramElement.program_name,
            FundingLine.pb_cycle,
            FundingLine.fiscal_year,
            FundingLine.funding_type,
            FundingLine.amount_thousands,
        )
        .join(FundingLine, FundingLine.program_element_id == ProgramElement.id)
        .where(FundingLine.pb_cycle.in_([older_pb, newer_pb]))
    )

    program_names: dict[_ProgramKey, str] = {}
    presence: set[tuple[str, str, int]] = set()
    amounts: dict[_FundingKey, float] = defaultdict(float)
    funding_types: dict[_FundingKey, set[str]] = defaultdict(set)

    for (
        pe_number,
        agency,
        program_name,
        pb_cycle,
        fiscal_year,
        funding_type,
        amount_k,
    ) in session.execute(statement):
        pb_cycle = int(pb_cycle)
        fiscal_year = int(fiscal_year)
        program_key = (pe_number, agency)
        program_names[program_key] = program_name
        presence.add((pe_number, agency, pb_cycle))
        if funding_type not in _DISCRETIONARY_TYPES:
            continue
        funding_key = (pe_number, agency, pb_cycle, fiscal_year)
        amounts[funding_key] += float(amount_k)
        funding_types[funding_key].add(funding_type)

    older_amounts: dict[_ProgramYearKey, float] = {}
    newer_amounts: dict[_ProgramYearKey, float] = {}
    older_types: dict[_ProgramYearKey, str] = {}
    newer_types: dict[_ProgramYearKey, str] = {}
    for (pe_number, agency, pb_cycle, fiscal_year), amount_k in amounts.items():
        key = (pe_number, agency, fiscal_year)
        label = _funding_label(
            funding_types[(pe_number, agency, pb_cycle, fiscal_year)]
        )
        if pb_cycle == older_pb:
            older_amounts[key] = amount_k
            older_types[key] = label
        if pb_cycle == newer_pb:
            newer_amounts[key] = amount_k
            newer_types[key] = label

    events: list[ChangeEvent] = []

    for (pe_number, agency, fiscal_year), after_k in newer_amounts.items():
        if fiscal_year != newer_pb or after_k == 0.0:
            continue
        if (pe_number, agency, older_pb) in presence:
            continue
        program_name = program_names[(pe_number, agency)]
        events.append(ChangeEvent(
            pe_number=pe_number,
            agency=agency,
            program_name=program_name,
            kind="new_start",
            fiscal_year=fiscal_year,
            from_vintage=None,
            to_vintage=newer_pb,
            before_k=None,
            after_k=after_k,
            pct_change=None,
            detail=_vintage_detail(
                older_pb, newer_pb, None,
                newer_types[(pe_number, agency, fiscal_year)],
            ),
            permalink=_permalink(pe_number, agency),
        ))

    terminations: dict[_ProgramKey, tuple[int, float, str]] = {}
    for (pe_number, agency, fiscal_year), before_k in older_amounts.items():
        if before_k == 0.0 or (pe_number, agency, newer_pb) in presence:
            continue
        program_key = (pe_number, agency)
        candidate = (
            fiscal_year,
            before_k,
            older_types[(pe_number, agency, fiscal_year)],
        )
        previous = terminations.get(program_key)
        if previous is None or candidate[0] > previous[0]:
            terminations[program_key] = candidate

    for (pe_number, agency), (fiscal_year, before_k, funding_type) in (
        terminations.items()
    ):
        events.append(ChangeEvent(
            pe_number=pe_number,
            agency=agency,
            program_name=program_names[(pe_number, agency)],
            kind="termination",
            fiscal_year=fiscal_year,
            from_vintage=older_pb,
            to_vintage=None,
            before_k=before_k,
            after_k=None,
            pct_change=None,
            detail=_vintage_detail(
                older_pb, newer_pb, funding_type, None,
            ),
            permalink=_permalink(pe_number, agency),
        ))

    for key in older_amounts.keys() & newer_amounts.keys():
        before_k = older_amounts[key]
        if before_k == 0.0:
            continue
        after_k = newer_amounts[key]
        pct_change = (after_k - before_k) / abs(before_k) * 100.0
        if abs(pct_change) < swing_pct:
            continue
        pe_number, agency, fiscal_year = key
        events.append(ChangeEvent(
            pe_number=pe_number,
            agency=agency,
            program_name=program_names[(pe_number, agency)],
            kind="swing",
            fiscal_year=fiscal_year,
            from_vintage=older_pb,
            to_vintage=newer_pb,
            before_k=before_k,
            after_k=after_k,
            pct_change=pct_change,
            detail=_vintage_detail(
                older_pb,
                newer_pb,
                older_types[key],
                newer_types[key],
            ),
            permalink=_permalink(pe_number, agency),
        ))

    return _sorted_events(events)


def _optional_float(value: float | None) -> float | None:
    return None if value is None else float(value)


def new_committee_actions(
    session: Session,
    fiscal_year: int,
) -> list[ChangeEvent]:
    """Return each nonzero House or Senate authorizing action separately."""
    statement = (
        select(
            PECongressionalAction.pe_number,
            PECongressionalAction.agency,
            PECongressionalAction.program_title,
            PECongressionalAction.fiscal_year,
            PECongressionalAction.chamber,
            PECongressionalAction.request_k,
            PECongressionalAction.committee_delta_k,
            PECongressionalAction.authorized_k,
            PECongressionalAction.rationale,
        )
        .where(
            PECongressionalAction.fiscal_year == fiscal_year,
            PECongressionalAction.committee_delta_k.is_not(None),
            PECongressionalAction.committee_delta_k != 0,
        )
    )

    events: list[ChangeEvent] = []
    for row in session.execute(statement):
        delta_k = float(row.committee_delta_k)
        rationale = (row.rationale or "").strip()
        detail = (
            f"{row.chamber}: {rationale}"
            if rationale
            else f"{row.chamber}: Committee action [{delta_k:+,.0f}]"
        )
        events.append(ChangeEvent(
            pe_number=row.pe_number,
            agency=row.agency,
            program_name=row.program_title,
            kind="committee_action",
            fiscal_year=int(row.fiscal_year),
            from_vintage=None,
            to_vintage=None,
            before_k=_optional_float(row.request_k),
            after_k=_optional_float(row.authorized_k),
            pct_change=None,
            detail=detail,
            permalink=_permalink(row.pe_number, row.agency),
        ))
    return _sorted_events(events)


def _execution_columns() -> tuple:
    return (
        PEExecution.pe_number,
        PEExecution.agency,
        PEExecution.fy_start,
        PEExecution.line_number,
        PEExecution.budget_activity,
        PEExecution.report_date,
        PEExecution.program_title,
        PEExecution.above_threshold_reprog_k,
        PEExecution.below_threshold_reprog_k,
    )


def _execution_key(row: Any) -> _ExecutionKey:
    return (
        row.pe_number,
        row.agency,
        int(row.fy_start),
        row.line_number,
        row.budget_activity,
    )


def _execution_key_sort(key: _ExecutionKey) -> tuple:
    pe_number, agency, fy_start, line_number, budget_activity = key
    return (
        pe_number,
        agency,
        fy_start,
        line_number is not None,
        line_number or "",
        budget_activity is not None,
        budget_activity or 0,
    )


def _execution_key_clause(key: _ExecutionKey):
    pe_number, agency, fy_start, line_number, budget_activity = key
    return and_(
        PEExecution.pe_number == pe_number,
        PEExecution.agency == agency,
        PEExecution.fy_start == fy_start,
        PEExecution.line_number.is_(None)
        if line_number is None
        else PEExecution.line_number == line_number,
        PEExecution.budget_activity.is_(None)
        if budget_activity is None
        else PEExecution.budget_activity == budget_activity,
    )


def _report_fiscal_year(report_date: str) -> int:
    """Fiscal year a DD 1416 report date belongs to; 12-31 is Q1 of the next FY."""
    report = date.fromisoformat(report_date)
    return report.year + 1 if report.month >= 10 else report.year


def _reprogramming_value_changed(
    before_k: float | None,
    after_k: float | None,
) -> bool:
    before_value = 0.0 if before_k is None else float(before_k)
    after_value = 0.0 if after_k is None else float(after_k)
    return before_value != after_value


def new_reprogramming(
    session: Session,
    report_date: str,
) -> list[ChangeEvent]:
    """Return changed DD 1416 reprogramming columns for one report date.

    Rows are matched on PE, agency, appropriation FY, line number, and budget
    activity. If that key has multiple rows in either the requested report or
    its greatest earlier report, the key is ambiguous and is skipped; rows are
    never summed and no arbitrary row is selected. ``from_vintage`` and
    ``to_vintage`` are the fiscal years the two report dates fall in, so a
    12-31 report belongs to the following fiscal year.
    """
    current_statement = select(*_execution_columns()).where(
        PEExecution.report_date == report_date
    )
    current_groups: dict[_ExecutionKey, list[Any]] = defaultdict(list)
    for row in session.execute(current_statement):
        current_groups[_execution_key(row)].append(row)

    unique_current_keys = sorted(
        (key for key, rows in current_groups.items() if len(rows) == 1),
        key=_execution_key_sort,
    )
    latest_prior: dict[_ExecutionKey, tuple[str, list[Any]]] = {}
    for offset in range(0, len(unique_current_keys), _EXECUTION_BATCH_SIZE):
        batch = unique_current_keys[offset:offset + _EXECUTION_BATCH_SIZE]
        prior_statement = select(*_execution_columns()).where(
            PEExecution.report_date < report_date,
            or_(*[_execution_key_clause(key) for key in batch]),
        )
        for row in session.execute(prior_statement):
            key = _execution_key(row)
            previous = latest_prior.get(key)
            if previous is None or row.report_date > previous[0]:
                latest_prior[key] = (row.report_date, [row])
            elif row.report_date == previous[0]:
                previous[1].append(row)

    to_vintage = _report_fiscal_year(report_date)
    events: list[ChangeEvent] = []
    for key in unique_current_keys:
        current = current_groups[key][0]
        prior_group = latest_prior.get(key)
        if prior_group is not None and len(prior_group[1]) != 1:
            continue
        previous = prior_group[1][0] if prior_group is not None else None
        from_vintage = (
            _report_fiscal_year(previous.report_date)
            if previous is not None
            else None
        )

        for column, detail in _REPROGRAMMING_COLUMNS:
            before_k = getattr(previous, column) if previous is not None else None
            after_k = getattr(current, column)
            if not _reprogramming_value_changed(before_k, after_k):
                continue
            events.append(ChangeEvent(
                pe_number=current.pe_number,
                agency=current.agency,
                program_name=current.program_title,
                kind="reprogramming",
                fiscal_year=int(current.fy_start),
                from_vintage=from_vintage,
                to_vintage=to_vintage,
                before_k=_optional_float(before_k),
                after_k=_optional_float(after_k),
                pct_change=None,
                detail=detail,
                permalink=_permalink(current.pe_number, current.agency),
            ))

    return _sorted_events(events)
