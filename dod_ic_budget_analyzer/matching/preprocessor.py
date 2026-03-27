"""
matching/preprocessor.py

Query preprocessing pipeline for the DoD program name matcher.

Handles the gap between how users type queries (short, informal, acronym-heavy)
and how PE titles appear in the R-1 (verbose, formal, parenthetical).

Pipeline stages:
  1. Detect PE number (exact lookup bypass)
  2. Extract acronym candidates (ALL-CAPS tokens, parenthetical content)
  3. Expand known military abbreviations
  4. Normalize: lowercase, strip punctuation, remove stop words

Usage:
    preprocessor = QueryPreprocessor()
    result = preprocessor.process("LTAMDS")
    # result.pe_number_detected = None
    # result.acronyms = ["LTAMDS"]
    # result.normalized = "ltamds"
    # result.expanded = "lower tier air missile defense sensor"  (if in index)
"""

import re
import string
from dataclasses import dataclass, field
from typing import Optional

# ── PE Number Pattern ─────────────────────────────────────────────────────────
# Matches formats: 0604114A, 0602668D8Z, 1160401BB, 0305251A
PE_NUMBER_RE = re.compile(r"^[0-9]{7,9}[A-Z0-9]{0,3}$", re.IGNORECASE)

# ── Stop Words ────────────────────────────────────────────────────────────────
# Words that appear heavily in PE titles but carry little discriminating signal.
# NOTE: "advanced" is kept — it distinguishes BA3 programs meaningfully.
STOP_WORDS = {
    "program", "programs", "project", "projects",
    "system", "systems", "development", "technologies", "technology",
    "demonstration", "prototype", "prototypes", "management", "support",
    "research", "test", "evaluation", "initiative", "initiatives",
    "capability", "capabilities", "activities", "activity",
    "advanced",   
    "the", "and", "for", "of", "in", "with", "to", "a", "an",
}

# ── Military Abbreviation Expansions ─────────────────────────────────────────
# Covers the most common abbreviations found in R-1 PE titles and press releases.
# Key: lowercase abbreviation | Value: expanded form (also lowercase)
ABBREVIATION_MAP = {
    # Platforms
    "uav":      "unmanned aerial vehicle",
    "uas":      "unmanned aircraft system",
    "uavs":     "unmanned aerial vehicles",
    "ugv":      "unmanned ground vehicle",
    "usv":      "unmanned surface vehicle",
    "uuv":      "unmanned undersea vehicle",

    # Weapons / munitions
    "atk":      "attack",
    "aaw":      "anti air warfare",
    "amd":      "air missile defense",
    "amdr":     "air missile defense radar",
    "sam":      "surface to air missile",
    "gbsd":     "ground based strategic deterrent",
    "lrasm":    "long range anti ship missile",
    "lrpf":     "long range precision fires",
    "himars":   "high mobility artillery rocket system",
    "jassm":    "joint air to surface standoff missile",
    "jdam":     "joint direct attack munition",

    # Sensors / EW
    "ew":       "electronic warfare",
    "isr":      "intelligence surveillance reconnaissance",
    "sigint":   "signals intelligence",
    "elint":    "electronic intelligence",
    "imint":    "imagery intelligence",
    "geoint":   "geospatial intelligence",
    "aesa":     "active electronically scanned array",
    "irst":     "infrared search and track",
    "lidar":    "light detection and ranging",

    # C2 / Networks
    "c2":       "command control",
    "c3":       "command control communications",
    "c3i":      "command control communications intelligence",
    "c4isr":    "command control communications computers intelligence surveillance reconnaissance",
    "jadc2":    "joint all domain command and control",
    "link16":   "link 16 tactical data link",
    "satcom":   "satellite communications",
    "comms":    "communications",

    # Programs / platform names
    "ltamds":   "lower tier air missile defense sensor",
    "ltamd":    "lower tier air missile defense",
    "ngad":     "next generation air dominance",
    "b21":      "b 21 raider bomber",
    "f35":      "f 35 lightning joint strike fighter",
    "f22":      "f 22 raptor",
    "ch47":     "chinook helicopter",
    "uh60":     "black hawk helicopter",
    "ah64":     "apache helicopter",
    "v22":      "v 22 osprey tiltrotor",
    "ftuas":    "future tactical unmanned aircraft system",
    "m-shorad": "maneuver short range air defense",
    "mshorad":  "maneuver short range air defense",
    "shorad":   "short range air defense",
    "ibcs":     "integrated battle command system",
    "ngcv":     "next generation combat vehicle",
    "omfv":     "optionally manned fighting vehicle",
    "abrams":   "m1 abrams tank",
    "bradley":  "m2 bradley infantry fighting vehicle",

    # Space
    "gps":      "global positioning system",
    "pnt":      "positioning navigation timing",
    "sbirs":    "space based infrared system",
    "opir":     "overhead persistent infrared",
    "leo":      "low earth orbit",
    "geo":      "geosynchronous orbit",
    "meo":      "medium earth orbit",
    "satcom":   "satellite communications",

    # Cyber / AI
    "ai":       "artificial intelligence",
    "ml":       "machine learning",
    "c2c":      "cyber to cyber",
    "a2ad":     "anti access area denial",

    # General military
    "adv":      "advanced",
    "dev":      "development",
    "dem":      "demonstration",
    "val":      "validation",
    "eng":      "engineering",
    "mod":      "modernization",
    "mil":      "military",
    "ops":      "operations",
    "intel":    "intelligence",
    "recon":    "reconnaissance",
    "surv":     "surveillance",
    "maint":    "maintenance",
    "log":      "logistics",
    "med":      "medical",
    "chem":     "chemical",
    "bio":      "biological",
    "nuc":      "nuclear",
    "cbrn":     "chemical biological radiological nuclear",
    "wmd":      "weapons of mass destruction",
    "socom":    "special operations command",
    "sof":      "special operations forces",
    "darpa":    "defense advanced research projects agency",
    "mda":      "missile defense agency",
    "disa":     "defense information systems agency",
    "dia":      "defense intelligence agency",
    "nga":      "national geospatial intelligence agency",
    "nro":      "national reconnaissance office",
    "nsa":      "national security agency",
    "dtra":     "defense threat reduction agency",
}


# ── Result Dataclass ──────────────────────────────────────────────────────────

@dataclass
class ProcessedQuery:
    raw: str                            # original input
    pe_number_detected: Optional[str]   # if input looks like a PE number
    acronyms: list[str]                 # ALL-CAPS tokens and parenthetical content
    normalized: str                     # lowercased, stop-word-stripped
    expanded: str                       # abbreviations expanded
    tokens: list[str]                   # final token list for matching


# ── Preprocessor ──────────────────────────────────────────────────────────────

class QueryPreprocessor:
    """
    Normalizes user queries before they reach the matching pipeline.

    Example:
        p = QueryPreprocessor()

        p.process("LTAMDS")
        # acronyms=["LTAMDS"], expanded="lower tier air missile defense sensor"

        p.process("0604114A")
        # pe_number_detected="0604114A"

        p.process("Future Tactical UAS (FTUAS) Advanced Dev")
        # acronyms=["FTUAS"], normalized="future tactical uas ftuas"
        # expanded="future tactical unmanned aircraft system"
    """

    def __init__(self, extra_abbreviations: dict[str, str] | None = None):
        self.abbrev = {**ABBREVIATION_MAP, **(extra_abbreviations or {})}

    def process(self, raw: str) -> ProcessedQuery:
        """Run the full preprocessing pipeline on a raw query string."""
        raw = raw.strip()

        # Stage 1: PE number detection
        pe_number = self._detect_pe_number(raw)
        if pe_number:
            return ProcessedQuery(
                raw=raw,
                pe_number_detected=pe_number,
                acronyms=[],
                normalized=pe_number,
                expanded=pe_number,
                tokens=[pe_number],
            )

        # Stage 2: Extract acronyms before lowercasing
        acronyms = self._extract_acronyms(raw)

        # Stage 3: Normalize
        normalized = self._normalize(raw)

        # Stage 4: Expand abbreviations
        expanded = self._expand(normalized)

        tokens = [t for t in expanded.split() if t]

        return ProcessedQuery(
            raw=raw,
            pe_number_detected=None,
            acronyms=acronyms,
            normalized=normalized,
            expanded=expanded,
            tokens=tokens,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_pe_number(text: str) -> Optional[str]:
        """Return the PE number if the query is (or contains) one."""
        stripped = text.strip().upper().replace(" ", "")
        if PE_NUMBER_RE.match(stripped):
            return stripped
        # Also check if a PE number appears embedded in a longer query
        m = re.search(r"\b([0-9]{7,9}[A-Z0-9]{0,3})\b", text.upper())
        if m:
            candidate = m.group(1)
            if PE_NUMBER_RE.match(candidate):
                return candidate
        return None

    @staticmethod
    def _extract_acronyms(text: str) -> list[str]:
        """
        Extract acronym candidates:
          - ALL-CAPS tokens of 2+ chars: "LTAMDS", "NGAD", "EW"
          - Parenthetical content: "Future Tactical UAS (FTUAS)" -> "FTUAS"
        """
        # Parenthetical content first
        paren_matches = re.findall(r"\(([A-Z0-9][A-Z0-9\-]{1,})\)", text)
        # ALL-CAPS tokens (2+ uppercase letters, may include digits/hyphens)
        caps_tokens = re.findall(r"\b([A-Z][A-Z0-9\-]{1,})\b", text)

        seen = set()
        acronyms = []
        for a in paren_matches + caps_tokens:
            a_clean = a.strip("-")
            if a_clean and a_clean not in seen:
                seen.add(a_clean)
                acronyms.append(a_clean)
        return acronyms

    def _normalize(self, text: str) -> str:
        """Lowercase, remove punctuation, strip stop words."""
        text = text.lower()
        # Remove punctuation except hyphens (M-SHORAD, C3I etc.)
        text = re.sub(r"[^\w\s\-]", " ", text)
        # Normalize hyphens to spaces
        text = text.replace("-", " ")
        tokens = [t for t in text.split() if t and t not in STOP_WORDS]
        return " ".join(tokens)

    def _expand(self, normalized: str) -> str:
        """Replace known abbreviations with their full forms."""
        tokens = normalized.split()
        expanded = []
        for token in tokens:
            if token in self.abbrev:
                expanded.append(self.abbrev[token])
            else:
                expanded.append(token)
        result = " ".join(expanded)
        # Collapse multiple spaces
        return re.sub(r"\s+", " ", result).strip()
