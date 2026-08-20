"""
matching/normalizer.py

Provides text normalization utilities specifically tuned for DoD/IC program names.
Removes common stop words, expands standard acronyms, and extracts parenthetical
acronyms from PE titles for alias indexing.
"""

import re
import string

# Common DoD prefixes/suffixes that dilute string matching algorithms
DOD_STOP_WORDS = {
    "project", "program", "system", "systems", "development",
    "advanced", "demonstration", "prototype", "prototypes", "management", "support",
}

# Well-known acronyms that appear in press statements but rarely verbatim in
# PE titles (or vice versa). Expansion is applied token-wise to queries and
# corpus entries so both sides land on the same vocabulary.
DOD_ACRONYMS = {
    "ai":     "artificial intelligence",
    "ml":     "machine learning",
    "c2":     "command and control",
    "c3i":    "command control communications intelligence",
    "c4isr":  "command control communications computers intelligence surveillance reconnaissance",
    "isr":    "intelligence surveillance reconnaissance",
    "jadc2":  "joint all domain command and control",
    "ew":     "electronic warfare",
    "uas":    "unmanned aircraft",
    "uav":    "unmanned aircraft",
    "usv":    "unmanned surface vehicle",
    "uuv":    "unmanned undersea vehicle",
    "gps":    "global positioning",
    "pnt":    "positioning navigation timing",
    "sof":    "special operations forces",
    "hypersonics": "hypersonic",
    "lrhw":   "long range hypersonic weapon",
    "ngad":   "next generation air dominance",
    "gbsd":   "ground based strategic deterrent",
    "icbm":   "intercontinental ballistic missile",
    "slbm":   "submarine launched ballistic missile",
    "thaad":  "terminal high altitude area defense",
    "rdte":   "research development test evaluation",
    "rdt&e":  "research development test evaluation",
    "sbir":   "small business innovation research",
    "nc3":    "nuclear command control communications",
    "cbrn":   "chemical biological radiological nuclear",
    "wmd":    "weapons of mass destruction",
}

# Agency/organization names that appear in press statements but almost never
# in PE titles. Stripped from QUERIES before lexical matching (expanding them
# injects generic tokens like "advanced"/"research" that match the wrong
# programs). Deliberately excludes ambiguous words like "air"/"space"/"force"
# which occur in real titles.
AGENCY_TOKENS = {
    "darpa", "socom", "disa", "dia", "nga", "nro", "nsa", "mda", "sda",
    "osd", "dod", "dow", "pentagon", "army", "navy", "usaf", "usn", "usmc",
    "marines",
}

# Parenthetical acronyms in PE titles, e.g.
# "Tactical Intel Targeting Access Node (TITAN) Adv Dev" -> TITAN
PARENTHETICAL_ACRONYM_RE = re.compile(r"\(([A-Z][A-Za-z0-9&/-]{1,14})\)")

# Translate punctuation to spaces (not empty) so "C3I/ISR" tokenizes as two
# tokens instead of gluing into "c3iisr".
_PUNCT_TO_SPACE = str.maketrans({c: " " for c in string.punctuation})


def normalize_program_name(text: str, expand_acronyms: bool = True) -> str:
    """
    Normalizes a defense program name for high-fidelity fuzzy matching.

    Args:
        text (str): The raw program name.
        expand_acronyms (bool): Replace known acronym tokens with expansions.

    Returns:
        str: The normalized string.
    """
    if not isinstance(text, str):
        return ""

    text = text.lower().translate(_PUNCT_TO_SPACE)

    tokens = text.split()
    if expand_acronyms:
        tokens = [DOD_ACRONYMS.get(t, t) for t in tokens]
        # Expansions may introduce multi-word tokens
        tokens = " ".join(tokens).split()

    filtered_tokens = [t for t in tokens if t not in DOD_STOP_WORDS]
    # Guard: a query made entirely of stop words ("program development")
    # must not normalize to "" and silently match nothing.
    if not filtered_tokens:
        filtered_tokens = tokens

    return re.sub(r"\s+", " ", " ".join(filtered_tokens)).strip()


def light_normalize(text: str) -> str:
    """
    Minimal normalization: lowercase, punctuation to spaces, collapsed
    whitespace. No stop-word removal or acronym expansion - preserves exact
    titles for high-precision matching.
    """
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.lower().translate(_PUNCT_TO_SPACE)).strip()


def normalize_query(text: str, expand_acronyms: bool = True) -> str:
    """
    Query-side normalization: strips agency-name tokens (which PE titles
    rarely contain) before applying the standard normalization.
    """
    light = light_normalize(text)
    kept = [t for t in light.split() if t not in AGENCY_TOKENS]
    if not kept:   # query was ONLY agency names - keep it rather than empty it
        kept = light.split()
    return normalize_program_name(" ".join(kept), expand_acronyms=expand_acronyms)


def extract_parenthetical_acronyms(text: str) -> list[str]:
    """
    Pulls parenthetical acronyms out of a PE title so they can be indexed as
    standalone aliases, e.g. "... Access Node (TITAN) Adv Dev" -> ["TITAN"].
    """
    if not isinstance(text, str):
        return []
    return PARENTHETICAL_ACRONYM_RE.findall(text)


if __name__ == "__main__":
    samples = [
        "Advanced Next-Gen Fighter System Development",
        "C3I/ISR Modernization",
        "JADC2 integration effort",
        "Tactical Intel Targeting Access Node (TITAN) Adv Dev",
        "Program Development",   # all stop words - must survive
    ]
    for s in samples:
        print(f"{s!r:60} -> {normalize_program_name(s)!r} | acronyms={extract_parenthetical_acronyms(s)}")
