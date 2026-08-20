"""
matching/fuzzy_matcher.py

Implements fuzzy string matching using RapidFuzz to map unstructured
text to canonical DoD Program Elements.

Each PE is indexed under several aliases: its normalized title, the title
with parenthetical acronyms stripped, and each parenthetical acronym on its
own ("TITAN" -> Tactical Intel Targeting Access Node). Classified aggregate
rows ("Classified Programs", blank PE number) are excluded - they are
placeholders, not matchable programs.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from rapidfuzz import process, fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.db import ProgramElement
from matching.normalizer import (
    normalize_program_name,
    normalize_query,
    light_normalize,
    extract_parenthetical_acronyms,
)

logger = logging.getLogger(__name__)

# PE numbers as they appear inside free text, e.g. "PE 0602702E" or "0601102A"
PE_NUMBER_IN_TEXT_RE = re.compile(r"\b([0-9]{7,9}[A-Z0-9]{0,3})\b")


class ProgramMatcher:
    """
    In-memory fuzzy matching engine for DoD Program Elements.
    """

    def __init__(self, session: Session):
        self.session = session
        # pe_id -> metadata for result construction
        self._pe_meta: Dict[int, dict] = {}
        # alias index: alias_idx -> normalized alias string / owning pe_id
        self._alias_strings: Dict[int, str] = {}
        self._alias_to_pe: Dict[int, int] = {}
        # exact lookup: pe_number -> [pe_id, ...] (same PE number can exist
        # under multiple agencies)
        self._by_pe_number: Dict[str, List[int]] = {}
        # parenthetical acronym -> [pe_id, ...] for deterministic token hits
        self._acronym_index: Dict[str, List[int]] = {}
        self._load_dictionary()

    def _load_dictionary(self) -> None:
        """
        Extracts program names from SQLite and builds the alias index.
        """
        stmt = select(
            ProgramElement.id,
            ProgramElement.program_name,
            ProgramElement.pe_number,
            ProgramElement.agency,
        )
        results = self.session.execute(stmt).all()

        alias_idx = 0
        for pe_id, name, pe_number, agency in results:
            if not name or not (pe_number or "").strip():
                continue  # classified aggregates / placeholder rows
            self._pe_meta[pe_id] = {
                "name": name, "pe_number": pe_number, "agency": agency,
            }
            self._by_pe_number.setdefault(pe_number, []).append(pe_id)

            # Light aliases preserve the exact title; heavy (stop-word
            # stripped, acronym-expanded) aliases add recall - but only when
            # they retain >=2 tokens or equal the light form, otherwise a
            # title like "Advanced Program Evaluation" degenerates to the
            # single token "evaluation" and partial-matches everything.
            stripped = re.sub(r"\([^)]*\)", " ", name)
            aliases = set()
            for variant in (name, stripped):
                light = light_normalize(variant)
                if light:
                    aliases.add(light)
                heavy = normalize_program_name(variant)
                if heavy and (len(heavy.split()) >= 2 or heavy == light):
                    aliases.add(heavy)

            for acronym in extract_parenthetical_acronyms(name):
                self._acronym_index.setdefault(acronym.lower(), []).append(pe_id)

            for alias in aliases:
                self._alias_strings[alias_idx] = alias
                self._alias_to_pe[alias_idx] = pe_id
                alias_idx += 1

        alias_idx = self._index_project_titles(alias_idx)

        logger.info(
            f"Loaded {len(self._pe_meta)} Program Elements "
            f"({len(self._alias_strings)} aliases, "
            f"{len(self._acronym_index)} acronyms) into matcher memory."
        )

    def _index_project_titles(self, alias_idx: int) -> int:
        """
        R-2 project titles (e.g. "MATH AND COMPUTER SCIENCES" under PE
        0601101E) become aliases for their parent PE - press statements often
        quote the project name, not the PE title. No-op when narratives
        haven't been ingested.
        """
        try:
            from sqlalchemy import select as sa_select
            from storage.db import PENarrative
            rows = self.session.execute(
                sa_select(PENarrative.pe_number, PENarrative.agency,
                          PENarrative.project_title)
                .where(PENarrative.project_number != "")
            ).all()
        except Exception:
            return alias_idx

        meta_by_key = {
            (m["pe_number"], m["agency"]): pe_id
            for pe_id, m in self._pe_meta.items()
        }
        added = 0
        for r in rows:
            pe_id = meta_by_key.get((r.pe_number, r.agency))
            if pe_id is None or not r.project_title:
                continue
            light = light_normalize(r.project_title)
            heavy = normalize_program_name(r.project_title)
            for alias in {light, heavy}:
                # >=2 tokens strictly: a one-word project title ("Quantum")
                # is a token-subset of any query containing that word and
                # sails past the token_set_ratio sanity floor.
                if alias and len(alias.split()) >= 2:
                    self._alias_strings[alias_idx] = alias
                    self._alias_to_pe[alias_idx] = pe_id
                    alias_idx += 1
                    added += 1
        if added:
            logger.info(f"Indexed {added} R-2 project-title aliases")
        return alias_idx

    # ── Lookups ───────────────────────────────────────────────────────────────

    def lookup_pe_number(self, text: str) -> List[dict]:
        """
        Exact lookup for PE numbers appearing anywhere in the text.
        Returns one candidate per (PE number, agency) hit, confidence 1.0.
        """
        hits = []
        for pe_number in PE_NUMBER_IN_TEXT_RE.findall(text.upper()):
            for pe_id in self._by_pe_number.get(pe_number, []):
                meta = self._pe_meta[pe_id]
                hits.append({
                    "pe_id": pe_id,
                    "name": meta["name"],
                    "pe_number": meta["pe_number"],
                    "agency": meta["agency"],
                    "score": 1.0,
                    "strategy": "PE_NUMBER",
                })
        return hits

    def find_matches(
        self,
        query: str,
        limit: int = 5,
        score_cutoff: float = 60.0,
        sanity_floor: float = 55.0,
    ) -> List[dict]:
        """
        Top-k fuzzy candidates, deduplicated by PE. Scores are normalized to
        0-1 so they compose with semantic confidences downstream.

        Robustness measures:
          - A parenthetical-acronym token in the query ("TITAN") is a
            near-deterministic hit (0.98), bypassing string similarity.
          - The query is matched in both light (exact-title) and heavy
            (stop-word/acronym normalized) forms; best score per PE wins.
          - WRatio's partial matching inflates short-alias hits, so every
            candidate must also clear `sanity_floor` on token_set_ratio -
            this stops "quantum blockchain pizza delivery" from confidently
            matching "Quantum Application".
        """
        light_query = light_normalize(query)
        heavy_query = normalize_query(query)
        if not light_query:
            return []

        candidates: Dict[int, dict] = {}

        def add(pe_id: int, score: float, strategy: str = "FUZZY") -> None:
            if pe_id not in candidates or score > candidates[pe_id]["score"]:
                meta = self._pe_meta[pe_id]
                candidates[pe_id] = {
                    "pe_id": pe_id,
                    "name": meta["name"],
                    "pe_number": meta["pe_number"],
                    "agency": meta["agency"],
                    "score": round(score, 4),
                    "strategy": strategy,
                }

        # Deterministic acronym-token hits
        query_tokens = set(light_query.split())
        for acronym, pe_ids in self._acronym_index.items():
            if acronym in query_tokens:
                for pe_id in pe_ids:
                    add(pe_id, 0.98, "ACRONYM")

        # Dual-form fuzzy extraction
        for q in {light_query, heavy_query}:
            if not q:
                continue
            raw = process.extract(
                query=q,
                choices=self._alias_strings,
                scorer=fuzz.WRatio,
                score_cutoff=score_cutoff,
                limit=limit * 4,  # oversample: several aliases map to one PE
            )
            for alias, score, alias_idx in raw:
                if fuzz.token_set_ratio(q, alias) < sanity_floor:
                    continue
                add(self._alias_to_pe[alias_idx], score / 100.0)

        ranked = sorted(candidates.values(), key=lambda c: c["score"], reverse=True)
        return ranked[:limit]

    def find_best_match(
        self, query: str, score_cutoff: float = 75.0
    ) -> Optional[Tuple[int, str, float]]:
        """
        Backward-compatible single-best lookup.
        Returns (pe_id, canonical_name, score_0_to_100) or None.
        """
        matches = self.find_matches(query, limit=1, score_cutoff=score_cutoff)
        if matches:
            m = matches[0]
            return (m["pe_id"], m["name"], m["score"] * 100.0)
        return None
