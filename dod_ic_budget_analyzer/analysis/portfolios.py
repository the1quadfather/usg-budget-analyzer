"""Private, portable collection definitions and comparable annual requests.

Definitions contain identifiers, notes and view settings only. They are kept in
the viewer's browser, never in the shared budget archive or a server-wide cache.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from uuid import uuid4

import pandas as pd
from sqlalchemy import func, select, tuple_

from analysis.deflators import convert_amount, provenance_record
from storage.db import FundingLine, ProgramElement, SourceDocument


MAX_BACKUP_BYTES = 1_000_000
MAX_COLLECTIONS = 30
MAX_MEMBERS = 100
_ID = re.compile(r"^[a-f0-9]{32}$")
_PE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,49}$")
ROW_COLUMNS = [
    "pe_number", "agency", "program_name", "before_k", "after_k", "delta_k",
    "pct_change", "status", "flagged",
]


def new_workspace() -> dict:
    return {"schema_version": 1, "revision": uuid4().hex, "collections": []}


def _text(value, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} must be text of at most {maximum} characters.")
    value = value.strip()
    if not value and not empty:
        raise ValueError(f"{label} is required.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{label} contains unsupported control characters.")
    return value


def validate_settings(settings: dict) -> dict:
    expected = {"older_pb", "newer_pb", "basis", "min_change_m",
                "min_change_pct", "include_presence"}
    if not isinstance(settings, dict) or set(settings) != expected:
        raise ValueError("Collection comparison settings are incomplete.")
    for key in ("older_pb", "newer_pb"):
        if type(settings[key]) is not int or not 1900 <= settings[key] <= 2100:
            raise ValueError("PB years must be whole years between 1900 and 2100.")
    if settings["older_pb"] >= settings["newer_pb"]:
        raise ValueError("The baseline PB must precede the comparison PB.")
    if not isinstance(settings["basis"], str) or settings["basis"] not in {"then-year", "constant-2025"}:
        raise ValueError("Choose then-year or constant FY2025 dollars.")
    for key in ("min_change_m", "min_change_pct"):
        value = settings[key]
        if (type(value) not in (int, float) or not math.isfinite(value)
                or not 0 <= value <= 1_000_000):
            raise ValueError("Watch thresholds must be finite, non-negative numbers.")
    if type(settings["include_presence"]) is not bool:
        raise ValueError("The presence-change setting must be true or false.")
    return deepcopy(settings)


def default_settings(cycles: list[int]) -> dict:
    if len(cycles) < 2:
        raise ValueError("Two annual request submissions are needed.")
    return {
        "older_pb": cycles[-2], "newer_pb": cycles[-1], "basis": "then-year",
        "min_change_m": 10.0, "min_change_pct": 20.0, "include_presence": True,
    }


def validate_workspace(value: dict) -> dict:
    if (not isinstance(value, dict)
            or set(value) != {"schema_version", "revision", "collections"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1):
        raise ValueError("This is not a supported Budget Explorer backup (version 1).")
    if not isinstance(value["revision"], str) or not _ID.fullmatch(value["revision"]):
        raise ValueError("The backup revision is invalid.")
    collections = value["collections"]
    if not isinstance(collections, list) or len(collections) > MAX_COLLECTIONS:
        raise ValueError(f"A backup can contain at most {MAX_COLLECTIONS} collections.")
    clean = []
    ids, names = set(), set()
    expected = {"id", "name", "kind", "notes", "members", "settings"}
    for item in collections:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("A collection has unsupported or missing fields.")
        ident = item["id"]
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in ids:
            raise ValueError("Collection identifiers must be valid and unique.")
        name = _text(item["name"], "Collection name", 80)
        if name.casefold() in names:
            raise ValueError("Each collection needs a different name.")
        if not isinstance(item["kind"], str) or item["kind"] not in {"portfolio", "watchlist"}:
            raise ValueError("Choose a portfolio or a watchlist.")
        members = item["members"]
        if not isinstance(members, list) or len(members) > MAX_MEMBERS:
            raise ValueError(f"A collection can contain at most {MAX_MEMBERS} programs.")
        clean_members, seen = [], set()
        for member in members:
            if not isinstance(member, dict) or set(member) != {"pe_number", "agency"}:
                raise ValueError("A program must specify its PE and component.")
            pe = _text(member["pe_number"], "PE number", 50)
            agency = _text(member["agency"], "Component", 100)
            if not _PE.fullmatch(pe):
                raise ValueError("A PE number contains unsupported characters.")
            if (pe, agency) in seen:
                raise ValueError("A program appears more than once in a collection.")
            seen.add((pe, agency))
            clean_members.append({"pe_number": pe, "agency": agency})
        ids.add(ident)
        names.add(name.casefold())
        clean.append({
            "id": ident, "name": name, "kind": item["kind"],
            "notes": _text(item["notes"], "Notes", 3000, empty=True),
            "members": clean_members, "settings": validate_settings(item["settings"]),
        })
    return {"schema_version": 1, "revision": value["revision"], "collections": clean}


def _invalid_number(value):
    raise ValueError("A backup cannot contain NaN or infinite numbers.")


def load_workspace(payload: bytes | str) -> dict:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, bytes) or len(payload) > MAX_BACKUP_BYTES:
        raise ValueError("Choose a JSON backup smaller than 1 MB.")
    try:
        value = json.loads(payload.decode("utf-8-sig"), parse_constant=_invalid_number)
        return validate_workspace(value)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("The backup is not valid UTF-8 JSON.") from None


def dump_workspace(workspace: dict) -> bytes:
    payload = json.dumps(validate_workspace(workspace), ensure_ascii=False,
                         allow_nan=False, indent=2).encode("utf-8")
    if len(payload) > MAX_BACKUP_BYTES:
        raise ValueError("The backup exceeds the 1 MB size limit.")
    return payload


def save_collection(workspace: dict, *, name: str, kind: str, settings: dict,
                    notes: str = "", members: list[dict] | None = None,
                    collection_id: str | None = None) -> dict:
    updated = validate_workspace(workspace)
    ident = collection_id or uuid4().hex
    if collection_id and not any(c["id"] == ident for c in updated["collections"]):
        raise ValueError("That collection no longer exists.")
    item = {"id": ident, "name": name, "kind": kind, "notes": notes,
            "members": members if members is not None else [], "settings": settings}
    updated["collections"] = [c for c in updated["collections"] if c["id"] != ident]
    updated["collections"].append(item)
    updated["revision"] = uuid4().hex
    return validate_workspace(updated)


def remove_collection(workspace: dict, collection_id: str) -> dict:
    updated = validate_workspace(workspace)
    if not any(c["id"] == collection_id for c in updated["collections"]):
        raise ValueError("That collection no longer exists.")
    updated["collections"] = [c for c in updated["collections"] if c["id"] != collection_id]
    updated["revision"] = uuid4().hex
    return updated


def request_cycles(session) -> list[int]:
    return list(session.scalars(
        select(FundingLine.pb_cycle).where(
            FundingLine.funding_type == "BY Request",
            FundingLine.fiscal_year == FundingLine.pb_cycle,
        ).distinct().order_by(FundingLine.pb_cycle)
    ))


def program_catalog(session) -> dict[tuple[str, str], str]:
    rows = session.execute(select(
        ProgramElement.pe_number, ProgramElement.agency, ProgramElement.program_name,
    ).join(SourceDocument, ProgramElement.source_document_id == SourceDocument.id)
        .order_by(SourceDocument.publication_year.desc(), ProgramElement.id.desc()))
    catalog = {}
    for pe, agency, name in rows:
        catalog.setdefault((pe, agency), name)
    return catalog


@dataclass
class PortfolioSnapshot:
    collection: dict
    rows: pd.DataFrame
    sources: list[dict]

    @property
    def flagged(self) -> pd.DataFrame:
        return self.rows.loc[self.rows["flagged"]].copy()


def build_snapshot(session, collection: dict) -> PortfolioSnapshot:
    """Compare discretionary BY requests, each for its own submission year.

    Exact (PE, component) pairs prevent cross-service matches. An absent row is
    None, including for historical/unknown members restored from a backup.
    """
    validate_workspace({"schema_version": 1, "revision": uuid4().hex,
                        "collections": [collection]})
    settings = collection["settings"]
    older, newer = settings["older_pb"], settings["newer_pb"]
    pairs = [(m["pe_number"], m["agency"]) for m in collection["members"]]
    if not pairs:
        return PortfolioSnapshot(deepcopy(collection), pd.DataFrame(columns=ROW_COLUMNS), [])
    catalog = program_catalog(session)
    conditions = [
        tuple_(ProgramElement.pe_number, ProgramElement.agency).in_(pairs),
        FundingLine.pb_cycle.in_([older, newer]),
        FundingLine.fiscal_year == FundingLine.pb_cycle,
        FundingLine.funding_type == "BY Request",
    ]
    observations = session.execute(select(
        ProgramElement.pe_number, ProgramElement.agency, FundingLine.pb_cycle,
        func.sum(FundingLine.amount_thousands),
    ).join(FundingLine, FundingLine.program_element_id == ProgramElement.id)
        .where(*conditions).group_by(
            ProgramElement.pe_number, ProgramElement.agency, FundingLine.pb_cycle,
        ))
    amounts = {}
    for pe, agency, cycle, amount in observations:
        value = float(amount)
        if settings["basis"] == "constant-2025":
            value = convert_amount(value, cycle)
        amounts[(pe, agency, cycle)] = value
    rows = []
    for pe, agency in pairs:
        before = amounts.get((pe, agency, older))
        after = amounts.get((pe, agency, newer))
        delta = None if before is None or after is None else after - before
        pct = None if delta is None or before == 0 else delta / abs(before) * 100
        if before is None and after is None:
            status = "No request observations"
        elif before is None:
            status = "Newly observed request"
        elif after is None:
            status = "No longer observed request"
        elif before == 0 and after != 0:
            status = "Change from zero request"
        else:
            status = "Comparable requests"
        presence = status in {"Newly observed request", "No longer observed request",
                              "Change from zero request"}
        flagged = bool(
            (presence and settings["include_presence"])
            or (delta is not None and pct is not None and delta != 0
                and abs(delta) >= settings["min_change_m"] * 1000
                and abs(pct) >= settings["min_change_pct"])
        )
        rows.append({
            "pe_number": pe, "agency": agency,
            "program_name": catalog.get((pe, agency), "Program not in this data release"),
            "before_k": before, "after_k": after, "delta_k": delta,
            "pct_change": pct, "status": status, "flagged": flagged,
        })
    source_rows = session.execute(select(
        SourceDocument.filename, SourceDocument.document_type,
        SourceDocument.publication_year, SourceDocument.source_url,
        SourceDocument.retrieved_at, SourceDocument.processed_date,
    ).join(FundingLine, FundingLine.source_document_id == SourceDocument.id)
        .join(ProgramElement, FundingLine.program_element_id == ProgramElement.id)
        .where(*conditions).distinct()
        .order_by(SourceDocument.publication_year, SourceDocument.filename))
    sources = [dict(row._mapping) for row in source_rows]
    if settings["basis"] == "constant-2025":
        sources.append(provenance_record())
    frame = pd.DataFrame(rows, columns=ROW_COLUMNS).sort_values(
        ["agency", "program_name", "pe_number"], kind="stable",
    ).reset_index(drop=True)
    return PortfolioSnapshot(deepcopy(collection), frame, sources)


def comparison_table(snapshot: PortfolioSnapshot, *, flagged_only: bool = False) -> pd.DataFrame:
    frame = snapshot.flagged if flagged_only else snapshot.rows
    settings = snapshot.collection["settings"]
    result = pd.DataFrame({
        "PE": frame["pe_number"], "Component": frame["agency"],
        "Program": frame["program_name"],
        f"FY{settings['older_pb']} request ($M)": frame["before_k"] / 1000,
        f"FY{settings['newer_pb']} request ($M)": frame["after_k"] / 1000,
        "Change ($M)": frame["delta_k"] / 1000,
        "Change (%)": frame["pct_change"], "Observation": frame["status"],
        "Review flag": frame["flagged"],
    })
    return result
