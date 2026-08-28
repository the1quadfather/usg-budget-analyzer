"""
analysis/ai_budget.py

Cost control for the AI features: a shared result cache, a measured spend
ledger, and a monthly budget governor.

Three jobs:

  1. AICache      - collapses repeat AI work to one call. A hundred users
                    asking about the same program should cost one call, not a
                    hundred. Non-grounded results only (see the compliance
                    note below); grounded results go to per-user history.
  2. SpendLedger  - one row per call with token counts read from the response's
                    usage metadata and the executed-query count read from
                    grounding metadata. Measured, not estimated - you cannot
                    price a product on guesses.
  3. budget_guard - refuses fresh calls once the month's ceiling is hit, so a
                    single enthusiastic user cannot run the bill up. Cached
                    content keeps rendering; only live calls stop.

COMPLIANCE NOTE - why grounded results are handled separately.
The Gemini API Additional Terms forbid callers from caching, framing,
syndicating, reselling, analyzing, training on, or otherwise learning from
Grounded Results, and require they be shown only to the end user who submitted
the prompt. A narrow carve-out permits storing the result text for up to two
years for that user's own history. So: non-grounded results are
shared-cacheable; grounded results are written to AIUserHistory keyed by
user_id, are never served to another user, and expire inside the two-year
ceiling. AICache.put() enforces this rather than trusting callers.
"""

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from storage.db import (
    AICache as AICacheRow,
    AISpend,
    AIUserHistory,
    Base,
    get_engine,
    get_session_factory,
)

logger = logging.getLogger(__name__)

def _utcnow() -> datetime:
    """Naive UTC, matching the naive datetimes the schema stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


DB_PATH = config.PROCESSED_DIR / "usg_budgets.db"
DB_URI = f"sqlite:///{DB_PATH.as_posix()}"

_session_factory = None


def session_factory():
    """Lazily built session factory, with the AI tables ensured to exist."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine(DB_URI)
        Base.metadata.create_all(engine)  # no-op for tables already present
        _session_factory = get_session_factory(engine)
    return _session_factory


# ── Pricing ───────────────────────────────────────────────────────────────────

def _token_rates(model: str, when: Optional[date] = None) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for `model` on `when`."""
    spec = config.GEMINI_PRICING.get(model)
    if spec is None:
        logger.warning(f"No published pricing for model {model!r}; using the "
                       "higher fallback rates so estimates never run low.")
        fb = config.GEMINI_PRICING_FALLBACK
        return fb["input"], fb["output"]
    when = when or date.today()
    step_up = date.fromisoformat(spec["step_up_date"])
    if when >= step_up:
        return spec["input_after"], spec["output_after"]
    return spec["input"], spec["output"]


def token_cost(model: str, input_tokens: int, output_tokens: int,
               thought_tokens: int = 0, when: Optional[date] = None) -> float:
    """
    USD for a call's tokens. Thinking tokens bill at the output rate, so they
    are folded into the output side rather than ignored - they are easy to
    forget and can dominate a reasoning-heavy call.
    """
    in_rate, out_rate = _token_rates(model, when)
    billed_out = output_tokens + thought_tokens
    return (input_tokens * in_rate + billed_out * out_rate) / 1_000_000.0


def grounding_cost(new_queries: int, queries_already_this_month: int) -> float:
    """
    USD for `new_queries` search queries, honoring the monthly free allowance.

    Grounding bills per query EXECUTED, not per API call - one prompt can fire
    several - and the free allowance is a project-wide monthly pool, so the
    marginal cost of a call depends on what the month has already spent.
    """
    if new_queries <= 0:
        return 0.0
    free = config.GROUNDING_FREE_QUERIES_PER_MONTH
    before = max(0, queries_already_this_month - free)
    after = max(0, queries_already_this_month + new_queries - free)
    return (after - before) * config.GROUNDING_USD_PER_1K / 1000.0


# ── Cache ─────────────────────────────────────────────────────────────────────

def cache_key(task: str, model: str, prompt_version: int, params: dict) -> str:
    """Stable content hash. sort_keys so dict ordering never splits the cache."""
    blob = json.dumps(
        {"task": task, "model": model, "v": prompt_version, "params": params},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class AICache:
    """Shared cache for non-grounded results; per-user history for grounded."""

    @staticmethod
    def _ttl_days(task: str) -> int:
        return config.AI_CACHE_TTL_DAYS.get(task, 30)

    @staticmethod
    def get(task: str, model: str, prompt_version: int, params: dict,
            user_id: str = "local") -> Optional[dict]:
        """
        Returns {"payload", "created_at", "search_suggestions_html"} or None.
        Grounded tasks read only this user's own history.
        """
        key = cache_key(task, model, prompt_version, params)
        now = _utcnow()
        grounded = task in config.GROUNDED_TASKS
        try:
            with session_factory()() as s:
                if grounded:
                    row = s.execute(
                        select(AIUserHistory).where(
                            AIUserHistory.cache_key == key,
                            AIUserHistory.user_id == user_id,
                            AIUserHistory.expires_at > now,
                        ).order_by(AIUserHistory.created_at.desc())
                    ).scalars().first()
                else:
                    row = s.execute(
                        select(AICacheRow).where(
                            AICacheRow.cache_key == key,
                            AICacheRow.expires_at > now,
                        )
                    ).scalars().first()
                if row is None:
                    return None
                return {
                    "payload": json.loads(row.payload_json),
                    "created_at": row.created_at,
                    "search_suggestions_html": getattr(
                        row, "search_suggestions_html", None),
                }
        except Exception as e:
            logger.warning(f"AI cache read failed ({type(e).__name__}: {e}); "
                           "treating as a miss.")
            return None

    @staticmethod
    def put(task: str, model: str, prompt_version: int, params: dict,
            payload: Any, user_id: str = "local",
            search_suggestions_html: Optional[str] = None) -> None:
        """
        Store a result. Grounded tasks are routed to per-user history with a TTL
        clamped to the two-year ceiling the terms allow; they never reach the
        shared table. This routing is the enforcement point for that rule.
        """
        key = cache_key(task, model, prompt_version, params)
        now = _utcnow()
        ttl = AICache._ttl_days(task)
        params_json = json.dumps(params, sort_keys=True, default=str)
        payload_json = json.dumps(payload, default=str)
        try:
            with session_factory()() as s:
                if task in config.GROUNDED_TASKS:
                    ttl = min(ttl, config.GROUNDED_HISTORY_MAX_DAYS)
                    s.add(AIUserHistory(
                        user_id=user_id, cache_key=key, task=task,
                        params_json=params_json, model=model,
                        payload_json=payload_json,
                        search_suggestions_html=search_suggestions_html,
                        created_at=now,
                        expires_at=now + timedelta(days=ttl),
                    ))
                else:
                    existing = s.execute(
                        select(AICacheRow).where(AICacheRow.cache_key == key)
                    ).scalars().first()
                    if existing is not None:
                        existing.payload_json = payload_json
                        existing.created_at = now
                        existing.expires_at = now + timedelta(days=ttl)
                    else:
                        s.add(AICacheRow(
                            cache_key=key, task=task, params_json=params_json,
                            model=model, prompt_version=prompt_version,
                            payload_json=payload_json, created_at=now,
                            expires_at=now + timedelta(days=ttl),
                        ))
                s.commit()
        except Exception as e:
            logger.warning(f"AI cache write failed ({type(e).__name__}: {e}); "
                           "result still returned to the caller.")


# ── Ledger ────────────────────────────────────────────────────────────────────

def _month_start(when: Optional[datetime] = None) -> datetime:
    when = when or _utcnow()
    return datetime(when.year, when.month, 1)


class SpendLedger:
    """Append-only record of AI calls; month-to-date queries read from it."""

    @staticmethod
    def record(task: str, model: str, user_id: str = "local",
               input_tokens: int = 0, output_tokens: int = 0,
               thought_tokens: int = 0, search_queries: int = 0,
               cache_hit: bool = False, ok: bool = True) -> float:
        """Compute the call's cost, persist the row, and return the cost."""
        cost = 0.0
        if not cache_hit:
            cost = token_cost(model, input_tokens, output_tokens, thought_tokens)
            if search_queries:
                cost += grounding_cost(
                    search_queries, SpendLedger.queries_this_month())
        try:
            with session_factory()() as s:
                s.add(AISpend(
                    ts=_utcnow(), user_id=user_id, task=task,
                    model=model, input_tokens=input_tokens,
                    output_tokens=output_tokens, thought_tokens=thought_tokens,
                    search_queries=search_queries, est_cost_usd=cost,
                    cache_hit=1 if cache_hit else 0, ok=1 if ok else 0,
                ))
                s.commit()
        except Exception as e:
            logger.warning(f"Spend ledger write failed ({type(e).__name__}: {e}).")
        return cost

    @staticmethod
    def _sum(column, user_id: Optional[str] = None) -> float:
        try:
            with session_factory()() as s:
                q = select(func.coalesce(func.sum(column), 0)).where(
                    AISpend.ts >= _month_start())
                if user_id is not None:
                    q = q.where(AISpend.user_id == user_id)
                return float(s.execute(q).scalar() or 0)
        except Exception as e:
            logger.warning(f"Spend ledger read failed ({type(e).__name__}: {e}).")
            return 0.0

    @staticmethod
    def month_to_date(user_id: Optional[str] = None) -> float:
        return SpendLedger._sum(AISpend.est_cost_usd, user_id)

    @staticmethod
    def queries_this_month() -> int:
        return int(SpendLedger._sum(AISpend.search_queries))

    @staticmethod
    def fresh_calls_this_month(user_id: str) -> int:
        """Cache misses only - cached reads are free and shouldn't spend credits."""
        try:
            with session_factory()() as s:
                return int(s.execute(
                    select(func.count(AISpend.id)).where(
                        AISpend.ts >= _month_start(),
                        AISpend.user_id == user_id,
                        AISpend.cache_hit == 0,
                        AISpend.ok == 1,
                    )
                ).scalar() or 0)
        except Exception as e:
            logger.warning(f"Credit count failed ({type(e).__name__}: {e}).")
            return 0


# ── Governor ──────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    """Whether a fresh call may proceed, and a message the UI can show as-is."""
    allowed: bool
    reason: str = ""
    message: str = ""


def budget_guard(task: str, user_id: str = "local",
                 credits: Optional[int] = None) -> Decision:
    """
    Gate a fresh (cache-miss) AI call. Cached reads never come through here.

    `credits` overrides the free-tier monthly allowance - pass a paid tier's
    larger number, or None to use config.AI_FREE_CREDITS_PER_MONTH.
    """
    cap = config.AI_MONTHLY_BUDGET_USD
    if cap is not None:
        spent = SpendLedger.month_to_date()
        if spent >= cap:
            return Decision(
                False, "budget",
                f"Fresh AI lookups are paused for the rest of this month "
                f"(${spent:,.2f} of the ${cap:,.2f} ceiling used). Everything "
                "already analyzed still loads normally.",
            )

    allowance = (config.AI_FREE_CREDITS_PER_MONTH if credits is None
                 else credits)
    if allowance is not None:
        used = SpendLedger.fresh_calls_this_month(user_id)
        if used >= allowance:
            return Decision(
                False, "credits",
                f"You've used all {allowance} fresh AI lookups for this month. "
                "Previously analyzed programs still load instantly.",
            )
    return Decision(True)


# ── Reporting ─────────────────────────────────────────────────────────────────

def report() -> str:
    """Month-to-date spend by task, cache hit rate, and grounded-query count."""
    try:
        with session_factory()() as s:
            rows = s.execute(
                select(
                    AISpend.task,
                    func.count(AISpend.id),
                    func.sum(AISpend.cache_hit),
                    func.sum(AISpend.search_queries),
                    func.sum(AISpend.est_cost_usd),
                ).where(AISpend.ts >= _month_start()).group_by(AISpend.task)
            ).all()
    except Exception as e:
        return f"Could not read the ledger: {type(e).__name__}: {e}"

    if not rows:
        return ("No AI calls recorded this month. (An empty ledger and a broken "
                "ledger look alike - run a lookup in the app to confirm rows "
                "appear.)")

    header = (f"{'TASK':<24}{'CALLS':>7}{'HITS':>6}{'HIT%':>7}"
              f"{'QUERIES':>9}{'COST':>10}{'$/FRESH':>10}")
    lines = [f"Month to date ({_month_start():%Y-%m}), UTC", header,
             "-" * len(header)]
    tot_calls = tot_hits = tot_q = 0
    tot_cost = 0.0
    for task, calls, hits, queries, cost in rows:
        hits, queries, cost = int(hits or 0), int(queries or 0), float(cost or 0)
        fresh = calls - hits
        per = cost / fresh if fresh else 0.0
        pct = 100.0 * hits / calls if calls else 0.0
        lines.append(f"{task:<24}{calls:>7}{hits:>6}{pct:>6.0f}%"
                     f"{queries:>9}{cost:>10.4f}{per:>10.4f}")
        tot_calls += calls
        tot_hits += hits
        tot_q += queries
        tot_cost += cost
    tot_pct = 100.0 * tot_hits / tot_calls if tot_calls else 0.0
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<24}{tot_calls:>7}{tot_hits:>6}{tot_pct:>6.0f}%"
                 f"{tot_q:>9}{tot_cost:>10.4f}")

    free = config.GROUNDING_FREE_QUERIES_PER_MONTH
    lines.append("")
    lines.append(f"Grounding queries: {tot_q:,} of {free:,} free "
                 f"({max(0, tot_q - free):,} billable at "
                 f"${config.GROUNDING_USD_PER_1K:.0f}/1k)")
    cap = config.AI_MONTHLY_BUDGET_USD
    if cap:
        lines.append(f"Budget: ${tot_cost:,.2f} of ${cap:,.2f} "
                     f"({100.0 * tot_cost / cap:.1f}%)")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="AI spend ledger and cache maintenance.")
    ap.add_argument("--report", action="store_true",
                    help="print month-to-date spend by task")
    ap.add_argument("--prune", action="store_true",
                    help="delete expired cache and history rows")
    ap.add_argument("--reset-runtime", action="store_true",
                    help="delete ALL AI runtime rows (cache, history, ledger, "
                         "search log). Run before committing: the database is "
                         "tracked in a PUBLIC repo, and grounded results must "
                         "never be published.")
    args = ap.parse_args()

    if args.reset_runtime:
        from storage.db import SearchLog
        with session_factory()() as s:
            counts = {}
            for model, name in ((AICacheRow, "ai_cache"),
                                (AIUserHistory, "ai_user_history"),
                                (AISpend, "ai_spend"),
                                (SearchLog, "search_log")):
                counts[name] = s.query(model).delete()
            s.commit()
        # Deleted SQLite rows linger in free pages until the file is rebuilt,
        # which is not good enough for something that gets git-committed.
        with get_engine(DB_URI).connect() as c:
            c.exec_driver_sql("VACUUM")
        for name, n in counts.items():
            print(f"cleared {n:>5} rows from {name}")
        print("VACUUMed - freed pages rewritten, not just unlinked.")
        return

    if args.prune:
        now = _utcnow()
        with session_factory()() as s:
            n1 = s.query(AICacheRow).filter(AICacheRow.expires_at <= now).delete()
            n2 = s.query(AIUserHistory).filter(
                AIUserHistory.expires_at <= now).delete()
            s.commit()
        print(f"Pruned {n1} cache rows and {n2} history rows.")
        return

    print(report())


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    main()
