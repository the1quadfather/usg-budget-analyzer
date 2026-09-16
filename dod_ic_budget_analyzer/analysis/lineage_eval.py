"""Evaluate PE-lineage detectors against a bounded, hand-checked golden set.

Expected on the shipped database: 433 raw edges, 432 distinct PE pairs,
recall 10/10, precision 10/11, 421 unlabelled pairs, and 10/10 matching
fiscal years. Precision is measured only inside the golden universe; all
other detected pairs are reported as unlabelled rather than assumed correct.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.lineage import LineageEdge
from analysis.lineage import detect_ba_renumbering
from analysis.lineage import detect_narrative_transfers
from storage.db import get_engine, get_session_factory


GOLDEN_PATH = Path(__file__).with_name("lineage_golden.json")
DB_PATH = Path(__file__).parent.parent / "data" / "processed" / "usg_budgets.db"
DB_URI = f"sqlite:///{DB_PATH.as_posix()}"


def _pair(item: dict | LineageEdge) -> tuple[str, str]:
    if isinstance(item, dict):
        return item["predecessor_pe"], item["successor_pe"]
    return item.predecessor_pe, item.successor_pe


def _load_golden() -> list[dict]:
    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    pairs = [_pair(case) for case in cases]
    if len(cases) != 12 or len(set(pairs)) != len(pairs):
        raise ValueError("lineage golden set must contain 12 distinct PE pairs")
    if sum(case["label"] == "edge" for case in cases) != 10:
        raise ValueError("lineage golden set must contain exactly 10 edges")
    if sum(case["label"] == "no_edge" for case in cases) != 2:
        raise ValueError("lineage golden set must contain exactly 2 no-edge cases")
    return cases


def run() -> int:
    cases = _load_golden()
    Session = get_session_factory(get_engine(DB_URI))
    with Session() as session:
        edges = (
            detect_ba_renumbering(session)
            + detect_narrative_transfers(session)
        )

    edges_by_pair: dict[tuple[str, str], list[LineageEdge]] = defaultdict(list)
    for edge in edges:
        edges_by_pair[_pair(edge)].append(edge)

    positive_pairs = {
        _pair(case) for case in cases if case["label"] == "edge"
    }
    negative_pairs = {
        _pair(case) for case in cases if case["label"] == "no_edge"
    }
    golden_pairs = positive_pairs | negative_pairs
    detected_pairs = set(edges_by_pair)

    recalled = 0
    year_matches = 0
    print(f"{'RESULT':7} {'LABEL':8} {'YEAR':9} PAIR")
    print("-" * 70)
    for case in cases:
        pair = _pair(case)
        detected = pair in detected_pairs
        expects_edge = case["label"] == "edge"
        passed = detected == expects_edge
        if expects_edge and detected:
            recalled += 1
            year_match = any(
                edge.first_fy_after == case["first_fy_after"]
                for edge in edges_by_pair[pair]
            )
            year_matches += int(year_match)
            year_result = "PASS" if year_match else "FAIL"
        else:
            year_result = "n/a"
        print(
            f"{'PASS' if passed else 'FAIL':7} {case['label']:8} "
            f"{year_result:9} {pair[0]} -> {pair[1]}"
        )

    labelled_detections = detected_pairs & golden_pairs
    true_detections = detected_pairs & positive_pairs
    unlabelled = detected_pairs - golden_pairs
    positives = len(positive_pairs)

    print("-" * 70)
    print(f"Raw edges: {len(edges)}")
    print(f"Distinct pairs: {len(detected_pairs)}")
    print(f"Recall: {recalled}/{positives} ({recalled / positives:.1%})")
    print(
        "Precision: "
        f"{len(true_detections)}/{len(labelled_detections)} "
        f"({len(true_detections) / len(labelled_detections):.1%})"
    )
    print(f"Unlabelled detected pairs: {len(unlabelled)}")
    print(f"Fiscal-year checks: {year_matches}/{positives}")
    return 0 if recalled == positives else 1


if __name__ == "__main__":
    sys.exit(run())
