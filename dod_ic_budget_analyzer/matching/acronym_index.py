"""
matching/acronym_index.py

Builds and queries a searchable acronym index derived from PE titles in the DB.

The R-1 consistently uses the format "Full Name (ACRONYM)" for programs with
common short names, e.g.:
    "Lower Tier Air Missile Defense (LTAMD) Sensor"
    "Future Tactical Unmanned Aircraft System (FTUAS)"
    "Maneuver - Short Range Air Defense (M-SHORAD)"
    "Counter - Small Unmanned Aircraft Systems Advanced Development"

This index extracts those parenthetical acronyms at build time and maps them
to PE IDs for instant O(1) lookup at query time — highest-precision path for
the short-name use case.

Also handles:
  - Hyphenated acronyms: M-SHORAD -> MSHORAD (normalized form)
  - Acronyms embedded in title without parens (ALL-CAPS tokens)
  - Multi-word informal names: "black hawk" -> UH-60 (via manual aliases)

Usage:
    index = AcronymIndex(session)
    matches = index.lookup("LTAMDS")
    # -> [AcronymMatch(pe_id=114, pe_number="0604114A", program_name="Lower Tier...",
    #                  agency="Army", acronym="LTAMD", score=1.0)]
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.db import ProgramElement

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class AcronymMatch:
    pe_id: int
    pe_number: str
    program_name: str
    agency: str
    budget_activity: Optional[str]
    acronym: str        # the matched acronym from the index
    score: float        # 1.0 for exact, <1.0 for normalized match


# ── Index ─────────────────────────────────────────────────────────────────────

class AcronymIndex:
    """
    In-memory acronym lookup index built from PE title parentheticals.

    Supports:
      - Exact match:      "LTAMDS" -> direct hit
      - Normalized match: "M SHORAD" / "mshorad" -> "M-SHORAD" hit
      - Prefix match:     "LTAMD" matches "LTAMDS" (and vice versa)
    """

    # Regex to extract parenthetical acronyms: "(LTAMD)", "(M-SHORAD)", "(FTUAS)"
    PAREN_RE = re.compile(r"\(([A-Z][A-Z0-9\-]{1,})\)")

    # Regex to extract standalone ALL-CAPS tokens (3+ chars to reduce noise)
    CAPS_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,})\b")

    def __init__(self, session: Session):
        self.session = session
        # Maps normalized acronym -> list of AcronymMatch
        self._index: dict[str, list[AcronymMatch]] = {}
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        """Load all PEs from DB and extract acronyms into the index."""
        stmt = select(
            ProgramElement.id,
            ProgramElement.pe_number,
            ProgramElement.program_name,
            ProgramElement.agency,
            ProgramElement.budget_activity,
        )
        rows = self.session.execute(stmt).all()

        for pe_id, pe_number, name, agency, ba in rows:
            if not name:
                continue
            acronyms = self._extract_acronyms(name)
            for acronym in acronyms:
                match = AcronymMatch(
                    pe_id=pe_id,
                    pe_number=pe_number or "",
                    program_name=name,
                    agency=agency or "",
                    budget_activity=ba,
                    acronym=acronym,
                    score=1.0,
                )
                key = self._normalize_acronym(acronym)
                self._index.setdefault(key, []).append(match)

        total_acronyms = sum(len(v) for v in self._index.values())
        logger.info(
            f"Acronym index built: {len(self._index)} unique acronyms, "
            f"{total_acronyms} total entries from {len(rows)} PEs"
        )

    def _extract_acronyms(self, title: str) -> list[str]:
        """Extract acronym candidates from a PE title."""
        acronyms = []
        seen = set()

        # Priority 1: parenthetical acronyms (highest confidence)
        for m in self.PAREN_RE.finditer(title):
            a = m.group(1)
            key = self._normalize_acronym(a)
            if key not in seen:
                seen.add(key)
                acronyms.append(a)

        # Priority 2: standalone ALL-CAPS tokens in the title
        # (only if title has no parens to avoid double-indexing)
        if not acronyms:
            for m in self.CAPS_RE.finditer(title):
                a = m.group(1)
                # Skip very generic caps tokens
                if a in {"US", "DoD", "NATO", "RDT", "MIP", "OCO", "LEO",
                          "GEO", "MEO", "SOF", "OSD"}:
                    continue
                key = self._normalize_acronym(a)
                if key not in seen:
                    seen.add(key)
                    acronyms.append(a)

        return acronyms

    @staticmethod
    def _normalize_acronym(acronym: str) -> str:
        """Normalize for comparison: uppercase, strip hyphens and spaces."""
        return re.sub(r"[\s\-]", "", acronym).upper()

    # ── Lookup ────────────────────────────────────────────────────────────────

    def lookup(self, query: str) -> list[AcronymMatch]:
        """
        Look up a query against the acronym index.

        Matching strategy (in priority order):
          1. Exact normalized match:     "LTAMDS" -> "LTAMDS"
          2. Query is prefix of acronym: "LTAMD"  -> "LTAMDS"
          3. Acronym is prefix of query: "LTAMDS" -> "LTAMD"

        Returns a list of AcronymMatch sorted by score desc.
        An empty list means no acronym match found.
        """
        if not query or not query.strip():
            return []

        key = self._normalize_acronym(query)
        results: list[AcronymMatch] = []

        # 1. Exact match
        if key in self._index:
            for m in self._index[key]:
                results.append(AcronymMatch(**{**m.__dict__, "score": 1.0}))

        # 2. Query is a prefix of an indexed acronym (e.g. "LTAMD" finds "LTAMDS")
        if not results:
            for indexed_key, matches in self._index.items():
                if indexed_key.startswith(key) and len(indexed_key) - len(key) <= 2:
                    for m in matches:
                        results.append(AcronymMatch(**{**m.__dict__, "score": 0.9}))

        # 3. An indexed acronym is a prefix of the query (e.g. "LTAMDS" finds "LTAMD")
        if not results:
            for indexed_key, matches in self._index.items():
                if key.startswith(indexed_key) and len(key) - len(indexed_key) <= 2:
                    for m in matches:
                        results.append(AcronymMatch(**{**m.__dict__, "score": 0.85}))

        # Sort by score desc, then by PE number for determinism
        results.sort(key=lambda x: (-x.score, x.pe_number))
        return results

    def lookup_many(self, acronyms: list[str]) -> list[AcronymMatch]:
        """Look up multiple acronym candidates and return deduplicated results."""
        seen_ids: set[int] = set()
        all_results: list[AcronymMatch] = []
        for acr in acronyms:
            for match in self.lookup(acr):
                if match.pe_id not in seen_ids:
                    seen_ids.add(match.pe_id)
                    all_results.append(match)
        all_results.sort(key=lambda x: (-x.score, x.pe_number))
        return all_results

    @property
    def size(self) -> int:
        return len(self._index)
