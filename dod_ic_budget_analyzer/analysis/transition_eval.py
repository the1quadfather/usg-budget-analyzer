"""Evaluate transition candidates against the twenty-case golden set.

Measured on 2026-09-20: recall@3 is 16/16, negatives are 4/4,
``bli_citation`` is 5/5, ``same_title`` is 11/11, and ``basic_research`` is
4/4. The four negatives are satisfied by Rule 0's BA 1/2 exclusion, so they
test that rule's coverage rather than matcher precision. Citation recall is
partly by construction because the same BLI regex built those cases; the
value of this eval is title retrieval, Rule 0 coverage, and regression
protection.
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from analysis.transition import CONFIDENCE_FLOOR, propose_transitions
from storage.db import get_engine, get_session_factory


GOLDEN_PATH = Path(__file__).with_name("transition_golden.json")
DB_URI = f"sqlite:///{(config.PROCESSED_DIR / 'usg_budgets.db').as_posix()}"


def run() -> int:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    Session = get_session_factory(get_engine(DB_URI))
    positives_passed = 0
    negatives_passed = 0
    breakdown: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    started = time.perf_counter()

    print(f"{'RESULT':7} {'PE':11} {'CLASS':15} DETAIL")
    print("-" * 110)
    with Session() as session:
        for case in cases:
            candidates = propose_transitions(
                session,
                case["pe_number"],
                case["agency"],
                limit=5,
            )
            evidence_class = case["evidence_class"]
            breakdown[evidence_class][1] += 1

            if case["label"] == "transition":
                acceptable = {
                    (item["bli"], item["appropriation"])
                    for item in case["acceptable"]
                }
                match = next(
                    (
                        (rank, candidate)
                        for rank, candidate in enumerate(candidates[:3], 1)
                        if (candidate.bli, candidate.appropriation) in acceptable
                    ),
                    None,
                )
                ok = match is not None
                positives_passed += int(ok)
                breakdown[evidence_class][0] += int(ok)
                if match is None:
                    top = candidates[0] if candidates else None
                    detail = (
                        "rank=- strategy=- confidence=-"
                        if top is None else
                        f"rank=- top={top.bli}@{top.appropriation} "
                        f"strategy={top.strategy} confidence={top.confidence:.3f}"
                    )
                else:
                    rank, candidate = match
                    detail = (
                        f"rank={rank} {candidate.bli}@{candidate.appropriation} "
                        f"strategy={candidate.strategy} "
                        f"confidence={candidate.confidence:.3f}"
                    )
            else:
                slipped = next(
                    (
                        candidate for candidate in candidates
                        if candidate.confidence >= CONFIDENCE_FLOOR
                    ),
                    None,
                )
                ok = slipped is None
                negatives_passed += int(ok)
                breakdown[evidence_class][0] += int(ok)
                detail = (
                    "no candidate at or above floor"
                    if slipped is None else
                    f"top={slipped.bli}@{slipped.appropriation} "
                    f"strategy={slipped.strategy} "
                    f"confidence={slipped.confidence:.3f}"
                )

            print(
                f"{'PASS' if ok else 'FAIL':7} "
                f"{case['pe_number']:11} {evidence_class:15} {detail}"
            )

    elapsed = time.perf_counter() - started
    positive_total = sum(
        case["label"] == "transition" for case in cases
    )
    negative_total = len(cases) - positive_total
    recall = positives_passed / positive_total if positive_total else 0.0
    print("-" * 110)
    print(f"Recall@3: {positives_passed}/{positive_total} ({recall:.1%})")
    print(
        f"Negatives passed: {negatives_passed}/{negative_total} "
        f"({negatives_passed / negative_total:.1%})"
    )
    for evidence_class in sorted(breakdown):
        passed, total = breakdown[evidence_class]
        print(
            f"{evidence_class}: {passed}/{total} "
            f"({passed / total:.1%})"
        )
    print(f"Timing: {elapsed:.2f} s for {len(cases)} cases")
    return 0 if recall >= 0.6 and negatives_passed == negative_total else 1


if __name__ == "__main__":
    raise SystemExit(run())
