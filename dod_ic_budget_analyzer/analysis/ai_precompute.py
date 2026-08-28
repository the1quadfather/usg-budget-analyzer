"""
analysis/ai_precompute.py

Offline batch worker that warms the AI cache so the app renders analysis on
arrival instead of making every user pay for a button press.

This is a build step, not a service: run it on a schedule (Task Scheduler now,
cron on the host later), let it fill the cache, and the UI turns warm.

Which programs get warmed, in priority order:
  1. What people actually searched for (search_log), most recent first -
     demand is a better signal than any guess about importance.
  2. The largest programs by latest-year funding, as the cold-start filler
     before there is any search history.

Only shared-cacheable tasks are precomputed. Grounded tasks are deliberately
excluded: the Gemini API terms permit storing Grounded Results only for the
user who asked, so warming them centrally would be both useless (nobody else
may be served from it) and non-compliant.

Usage:
    python analysis/ai_precompute.py --limit 20 --dry-run
    python analysis/ai_precompute.py --limit 20
    python analysis/ai_precompute.py --limit 50 --source funding
"""

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from analysis.ai_budget import SpendLedger, budget_guard, report, session_factory
from storage.db import FundingLine, ProgramElement, SearchLog

logger = logging.getLogger(__name__)

# Precompute only tasks whose results may be shared across users.
PRECOMPUTABLE_TASKS = [t for t in ("adjudicate",)
                       if t not in config.GROUNDED_TASKS]


def demand_targets(limit: int) -> list[dict]:
    """
    Programs people actually searched for, newest first. Ambiguous searches
    come first within that: those are the ones adjudication exists to fix.
    """
    with session_factory()() as s:
        rows = s.execute(
            select(SearchLog.query, func.max(SearchLog.ts).label("last_seen"),
                   func.count(SearchLog.id).label("hits"),
                   func.max(SearchLog.needs_review).label("ambiguous"))
            .group_by(SearchLog.query)
            .order_by(func.max(SearchLog.needs_review).desc(),
                      func.count(SearchLog.id).desc(),
                      func.max(SearchLog.ts).desc())
            .limit(limit)
        ).all()
    return [{"query": q, "hits": h, "ambiguous": bool(a), "source": "demand"}
            for q, _, h, a in rows]


def funding_targets(limit: int) -> list[dict]:
    """
    Biggest programs by their most recent funding line - the cold-start filler
    for when search_log is empty or thin.

    Classified aggregates and placeholder rows (blank PE number) are excluded
    on the same rule the matchers use: they are not real programs, so warming
    them would spend on an answer nobody can use.
    """
    with session_factory()() as s:
        latest_fy = s.execute(
            select(func.max(FundingLine.fiscal_year))).scalar()
        if latest_fy is None:
            return []
        rows = s.execute(
            select(ProgramElement.program_name, ProgramElement.pe_number,
                   ProgramElement.agency,
                   func.sum(FundingLine.amount_thousands).label("amt"))
            .join(FundingLine,
                  FundingLine.program_element_id == ProgramElement.id)
            .where(FundingLine.fiscal_year == latest_fy,
                   ProgramElement.pe_number != "",
                   ProgramElement.pe_number.is_not(None),
                   ProgramElement.program_name.is_not(None))
            .group_by(ProgramElement.pe_number, ProgramElement.agency)
            .order_by(func.sum(FundingLine.amount_thousands).desc())
            .limit(limit)
        ).all()
    return [{"query": name, "pe_number": pe, "agency": ag,
             "amount_thousands": float(amt or 0), "source": "funding"}
            for name, pe, ag, amt in rows]


def build_worklist(limit: int, source: str) -> list[dict]:
    """Demand first, topped up from funding until `limit` is reached."""
    work: list[dict] = []
    seen: set[str] = set()
    if source in ("demand", "both"):
        for t in demand_targets(limit):
            if t["query"].lower() not in seen:
                seen.add(t["query"].lower())
                work.append(t)
    if source in ("funding", "both") and len(work) < limit:
        for t in funding_targets(limit * 2):
            if len(work) >= limit:
                break
            if t["query"].lower() not in seen:
                seen.add(t["query"].lower())
                work.append(t)
    return work[:limit]


def run(limit: int, source: str, dry_run: bool) -> int:
    work = build_worklist(limit, source)
    if not work:
        print("Nothing to precompute: no search history and no funding data.")
        return 0

    demand = sum(1 for w in work if w["source"] == "demand")
    print(f"Worklist: {len(work)} programs "
          f"({demand} from search demand, {len(work) - demand} from funding).")
    print(f"Tasks: {', '.join(PRECOMPUTABLE_TASKS) or '(none)'}  "
          f"[grounded tasks excluded by design]")

    if dry_run:
        print("\nDRY RUN - no API calls, no cache writes.\n")
        print(f"{'SOURCE':<9}{'AMBIG':<7}{'QUERY'}")
        print("-" * 78)
        for w in work:
            print(f"{w['source']:<9}"
                  f"{('yes' if w.get('ambiguous') else '-'):<7}"
                  f"{w['query'][:60]}")
        print("-" * 78)
        print(f"{len(work)} programs would be warmed.")
        return 0

    from analysis.oss_enricher import GeminiEnricher, available
    if not available():
        print("AI enrichment unavailable: install google-genai and set "
              f"one of {config.GEMINI_API_KEY_ENV_VARS}.")
        return 1

    # Precompute runs under the same ceiling as the app, and stops the moment
    # it would exceed it - a scheduled job is exactly the thing that would
    # otherwise quietly drain a month's budget overnight.
    guard = budget_guard("adjudicate", user_id="precompute", credits=None)
    if not guard.allowed and guard.reason == "budget":
        print(f"Refusing to start: {guard.message}")
        return 1

    from analysis.program_linker import ProgramLinker
    from matching.fuzzy_matcher import ProgramMatcher
    from storage.db import get_engine, get_session_factory
    from analysis.ai_budget import DB_URI

    engine = get_engine(DB_URI)
    with get_session_factory(engine)() as sess:
        fuzzy = ProgramMatcher(sess)
        semantic = None
        try:
            from matching.semantic_matcher import SemanticMatcher
            semantic = SemanticMatcher(sess)
        except Exception as e:
            logger.warning(f"Semantic matching unavailable ({type(e).__name__}); "
                           "precomputing on lexical matches only.")
        linker = ProgramLinker(fuzzy, semantic, fuzzy_threshold=80.0,
                               semantic_threshold=0.45)

        enricher = GeminiEnricher()
        warmed = skipped = failed = 0
        start_spend = SpendLedger.month_to_date()

        for i, w in enumerate(work, 1):
            query = w["query"]
            result = linker.link_query(query)
            candidates = result.get("candidates") or []
            if not candidates:
                skipped += 1
                continue

            # Precompute runs with a generous credit allowance but still under
            # the dollar ceiling, so it stops cleanly rather than overrunning.
            res = enricher.adjudicate(query, candidates, user_id="precompute",
                                      allow_fresh=True, credits=len(work) + 1)
            if res.blocked:
                print(f"[{i}/{len(work)}] stopped: {res.message}")
                failed += 1
                break
            warmed += 1
            state = "cached" if res.cached else "fresh"
            print(f"[{i}/{len(work)}] {state:<6} {query[:55]}")

    spent = SpendLedger.month_to_date() - start_spend
    print(f"\nWarmed {warmed}, skipped {skipped} (no candidates), "
          f"failed {failed}. Spend this run: ${spent:.4f}")
    print()
    print(report())
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Warm the AI cache so the app renders analysis on arrival.")
    ap.add_argument("--limit", type=int, default=20,
                    help="how many programs to warm (default 20)")
    ap.add_argument("--source", choices=("demand", "funding", "both"),
                    default="both",
                    help="pick targets from search demand, funding size, or both")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the worklist without calling the API")
    args = ap.parse_args()
    sys.exit(run(args.limit, args.source, args.dry_run))


if __name__ == "__main__":
    logging.basicConfig(level="WARNING", format="%(levelname)s %(message)s")
    main()
