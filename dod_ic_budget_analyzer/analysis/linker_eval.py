"""
analysis/linker_eval.py

Golden-set evaluation for the ProgramLinker. Runs realistic press-statement
style queries against the live database and reports per-case results plus
overall accuracy, so matcher/threshold changes are measured instead of guessed.

Usage:
    python analysis/linker_eval.py            # full pipeline (semantic if available)
    python analysis/linker_eval.py --fuzzy-only
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import get_engine, get_session_factory
from matching.fuzzy_matcher import ProgramMatcher
from analysis.program_linker import ProgramLinker

logger = logging.getLogger(__name__)

DB_URI = f"sqlite:///{(Path(__file__).parent.parent / 'data' / 'processed' / 'usg_budgets.db').as_posix()}"

# Each case: query, set of acceptable PE-number PREFIXES (joint programs
# share a base number across agencies - any suffix is a correct link; empty
# set = expect NO confident match), and whether an ambiguity flag is
# acceptable for a pass.
GOLDEN_CASES = [
    # Stage 0: explicit PE numbers in text
    ("Funding for PE 0601102A increased sharply", {"0601102A"}, True),
    ("the 0602702E line", {"0602702E"}, True),
    # Exact / near-exact titles (multi-agency programs accept any variant)
    ("Defense Research Sciences", {"0601102", "0601153"}, True),
    ("Global Command and Control System", {"0303150"}, True),
    ("DARPA Tactical Technology", {"0602702"}, True),
    ("University Research Initiatives", {"0601103"}, True),
    # Acronym alias from a parenthetical title
    ("the TITAN targeting node", {"0604037"}, True),
    # Paraphrases that need lexical tolerance or semantics
    ("live fire testing and evaluation office", {"0605131"}, True),
    ("special operations aviation platforms", {"1160403"}, True),
    ("cyber operations technology", {"0306250"}, True),
    # Nonsense must NOT confidently match
    ("quantum blockchain pizza delivery", set(), True),
]


def run(fuzzy_only: bool = False) -> int:
    Session = get_session_factory(get_engine(DB_URI))
    with Session() as session:
        fuzzy = ProgramMatcher(session)
        semantic = None
        if not fuzzy_only:
            try:
                from matching.semantic_matcher import SemanticMatcher
                semantic = SemanticMatcher(session)
            except Exception as e:
                print(f"[warn] semantic matcher unavailable ({e}) - fuzzy only\n")
        linker = ProgramLinker(fuzzy, semantic)

        passed = 0
        print(f"{'RESULT':7} {'STRATEGY':11} {'CONF':>5}  {'MATCHED PE':12} QUERY")
        print("-" * 100)
        for query, acceptable, allow_ambiguous in GOLDEN_CASES:
            r = linker.link_query(query)
            got_pe = r["pe_number"]

            if not acceptable:
                # Expect: no match, or a match flagged for review
                ok = r["matched_pe_id"] is None or r["needs_review"]
            else:
                ok = (
                    got_pe is not None
                    and any(got_pe.startswith(p) for p in acceptable)
                    and (allow_ambiguous or not r["needs_review"])
                )

            passed += ok
            flag = " (review)" if r["needs_review"] else ""
            print(
                f"{'PASS' if ok else 'FAIL':7} {r['match_strategy']:11} "
                f"{r['confidence_score']:>5.2f}  {str(got_pe):12} "
                f"{query!r}{flag}"
            )
            if not ok and r["candidates"]:
                for c in r["candidates"][:3]:
                    print(f"        candidate: {c['pe_number']} {c['name']} "
                          f"[{c['agency']}] {c['strategy']} {c['score']:.2f}")

        total = len(GOLDEN_CASES)
        print("-" * 100)
        print(f"{passed}/{total} passed ({passed / total:.0%})")
        return 0 if passed == total else 1


if __name__ == "__main__":
    logging.basicConfig(level="WARNING")
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuzzy-only", action="store_true")
    args = ap.parse_args()
    sys.exit(run(fuzzy_only=args.fuzzy_only))
