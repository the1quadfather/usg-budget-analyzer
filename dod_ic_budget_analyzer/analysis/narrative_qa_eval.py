"""Evaluate local narrative passage retrieval against a fixed golden set."""

from __future__ import annotations

from pathlib import Path
import sys
from time import perf_counter


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.narrative_qa import retrieve


GOLDEN_CASES = (
    (
        "Skyborg autonomous aircraft vanguard program",
        {"0603032F"},
        True,
    ),
    (
        "counter-UAS directed energy laser for base defense",
        {"0602605F"},
        True,
    ),
    (
        "software defined radio for the Joint Tactical Radio System",
        {"0605042A"},
        True,
    ),
    (
        "Next Generation Jammer for the EA-18G Growler",
        {"0604269N", "0604274N"},
        True,
    ),
    (
        "What is the Army doing on launched effects for unmanned aircraft?",
        {"0605345A", "0609345A"},
        True,
    ),
    (
        "Long Range Hypersonic Weapon Dark Eagle",
        {"0604182A"},
        False,
    ),
    (
        "Ground Based Strategic Deterrent Sentinel ICBM replacement",
        {"0604858F", "0101125F"},
        False,
    ),
)


def run() -> int:
    retrieve("narrative retrieval warmup", k=1)
    gated_passed = 0
    gated_total = sum(gated for _, _, gated in GOLDEN_CASES)
    print(
        f"{'RESULT':7} {'GATED':6} {'RANK':>5} {'TOP SCORE':>9} "
        f"{'TIME MS':>9} {'TOP PE':12} QUESTION"
    )
    print("-" * 120)
    for question, acceptable, gated in GOLDEN_CASES:
        started = perf_counter()
        passages = retrieve(question, k=8)
        elapsed_ms = (perf_counter() - started) * 1000
        rank = next((
            position
            for position, passage in enumerate(passages, start=1)
            if passage.pe_number in acceptable
        ), None)
        passed = rank is not None and rank <= 3
        if gated and passed:
            gated_passed += 1
        rank_text = str(rank) if rank is not None else "miss"
        top_score = passages[0].score if passages else 0.0
        top_pe = passages[0].pe_number if passages else "none"
        print(
            f"{'PASS' if passed else 'FAIL':7} "
            f"{'yes' if gated else 'no':6} {rank_text:>5} "
            f"{top_score:>9.4f} {elapsed_ms:>9.1f} "
            f"{top_pe:12} {question}"
        )
    print("-" * 120)
    print(f"Gated: {gated_passed}/{gated_total} passed")
    return 0 if gated_passed == gated_total else 1


if __name__ == "__main__":
    raise SystemExit(run())
