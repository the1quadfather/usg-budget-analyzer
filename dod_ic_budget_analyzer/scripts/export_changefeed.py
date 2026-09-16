"""Export PB-vintage change events to ``release/changefeed.json``."""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import json
from pathlib import Path
import sys


APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parent
sys.path.insert(0, str(APP_DIR))

import config
from analysis.changefeed import ChangeEvent, diff_vintages
from storage.db import FundingLine, get_engine, get_session_factory
from sqlalchemy import select


DEFAULT_OUTPUT = REPO_ROOT / "release" / "changefeed.json"
EVENT_FIELDS = tuple(field.name for field in fields(ChangeEvent))


def _available_pb_cycles(session) -> list[int]:
    return list(session.execute(
        select(FundingLine.pb_cycle)
        .where(FundingLine.pb_cycle.is_not(None))
        .distinct()
        .order_by(FundingLine.pb_cycle)
    ).scalars())


def _validated_records(events: list[ChangeEvent]) -> list[dict]:
    expected = set(EVENT_FIELDS)
    records = []
    for index, event in enumerate(events):
        if not isinstance(event, ChangeEvent):
            raise TypeError(f"event {index} is not a ChangeEvent")
        record = asdict(event)
        actual = set(record)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(
                f"event {index} fields do not match ChangeEvent; "
                f"missing={missing}, extra={extra}"
            )
        records.append(record)
    return records


def export_changefeed(
    database: Path,
    output: Path,
    *,
    older_pb: int | None = None,
    newer_pb: int | None = None,
) -> tuple[int, int, int]:
    engine = get_engine(f"sqlite:///{database.resolve().as_posix()}")
    Session = get_session_factory(engine)
    with Session() as session:
        cycles = _available_pb_cycles(session)
        if len(cycles) < 2:
            raise ValueError("at least two PB cycles are required")
        older_pb = cycles[-2] if older_pb is None else older_pb
        newer_pb = cycles[-1] if newer_pb is None else newer_pb
        if older_pb not in cycles or newer_pb not in cycles:
            raise ValueError(
                f"PB cycles must be present in the database: {cycles}"
            )
        if older_pb >= newer_pb:
            raise ValueError("older PB cycle must precede newer PB cycle")
        records = _validated_records(
            diff_vintages(session, older_pb, newer_pb)
        )

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return older_pb, newer_pb, len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-pb", type=int)
    parser.add_argument("--newer-pb", type=int)
    parser.add_argument(
        "--database",
        type=Path,
        default=config.PROCESSED_DIR / "usg_budgets.db",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    older_pb, newer_pb, count = export_changefeed(
        args.database,
        args.output,
        older_pb=args.older_pb,
        newer_pb=args.newer_pb,
    )
    print(
        f"Exported {count:,} events for PB{older_pb} -> PB{newer_pb} "
        f"to {args.output.resolve()}."
    )


if __name__ == "__main__":
    main()
