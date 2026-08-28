"""
analysis/ai_budget_eval.py

Self-check for analysis/ai_budget.py, in the same runnable-eval style as
linker_eval.py. Two things are worth guarding here because both fail silently:

  1. The cost math. If it drifts, every pricing decision downstream is built on
     a wrong number and nothing complains.
  2. The grounded/non-grounded cache routing. A bug here doesn't raise - it
     quietly puts Grounded Results into a shared, cross-user table, which is
     exactly what the Gemini API terms forbid.

Runs against a throwaway database, never the real one.

Usage:
    python analysis/ai_budget_eval.py
"""

import logging
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config

results: list[tuple[bool, str, str]] = []


def check(name: str, got, want, tol: float = 0.0) -> None:
    if isinstance(want, float):
        ok = abs(float(got) - want) <= max(tol, 1e-9)
    else:
        ok = got == want
    results.append((ok, name, f"got {got!r}, want {want!r}"))


def run() -> int:
    # Point the module at a scratch DB before it builds its session factory.
    tmp = Path(tempfile.mkdtemp(prefix="ai_budget_eval_"))
    import analysis.ai_budget as ab
    ab.DB_URI = f"sqlite:///{(tmp / 'scratch.db').as_posix()}"
    ab._session_factory = None

    MODEL = "gemini-3.6-flash"

    # ── Token pricing ─────────────────────────────────────────────────────────
    # 1M in + 1M out at the pre-step-up rates = 0.75 + 3.75
    check("tokens: 1M in + 1M out (2026 rates)",
          ab.token_cost(MODEL, 1_000_000, 1_000_000, when=date(2026, 8, 25)),
          4.50, tol=1e-6)
    # Same call after the 2027-01-01 step-up = 1.50 + 7.50
    check("tokens: same call after 2027 step-up",
          ab.token_cost(MODEL, 1_000_000, 1_000_000, when=date(2027, 1, 1)),
          9.00, tol=1e-6)
    # Thinking tokens bill at the output rate - the easy one to forget.
    check("tokens: thinking tokens billed as output",
          ab.token_cost(MODEL, 0, 0, thought_tokens=1_000_000,
                        when=date(2026, 8, 25)),
          3.75, tol=1e-6)
    # An unknown model must over-estimate, never under-estimate.
    check("tokens: unknown model uses the higher fallback",
          ab.token_cost("gemini-9-imaginary", 1_000_000, 0,
                        when=date(2026, 8, 25)),
          1.50, tol=1e-6)
    # A realistic adjudicate() call: ~1.5K in, ~250 out.
    adj = ab.token_cost(MODEL, 1500, 250, when=date(2026, 8, 25))
    check("tokens: adjudicate() stays under a cent", adj < 0.01, True)

    # ── Grounding pricing (per query executed, monthly free pool) ─────────────
    free = config.GROUNDING_FREE_QUERIES_PER_MONTH
    check("grounding: inside the free pool costs nothing",
          ab.grounding_cost(10, 0), 0.0, tol=1e-9)
    check("grounding: 1,000 queries past the pool = $14",
          ab.grounding_cost(1000, free), 14.0, tol=1e-6)
    # A call straddling the boundary bills only the overflow.
    check("grounding: straddling the boundary bills only the overflow",
          ab.grounding_cost(100, free - 40), 60 * 14.0 / 1000, tol=1e-6)
    check("grounding: zero queries is free", ab.grounding_cost(0, 99_999), 0.0)

    # ── Cache routing: the compliance invariant ──────────────────────────────
    params = {"pe_number": "0602702E", "agency": "Defense-Wide"}

    # Non-grounded results are shared: user B reads what user A wrote.
    ab.AICache.put("adjudicate", MODEL, 1, params, {"verdict": "ok"},
                   user_id="alice")
    hit = ab.AICache.get("adjudicate", MODEL, 1, params, user_id="bob")
    check("cache: non-grounded result is shared across users",
          hit is not None and hit["payload"] == {"verdict": "ok"}, True)

    # Grounded results are NOT shared: user B must miss.
    ab.AICache.put("find_open_source_hits", MODEL, 1, params,
                   [{"title": "story"}], user_id="alice",
                   search_suggestions_html="<div>chips</div>")
    check("cache: grounded result is NOT visible to another user",
          ab.AICache.get("find_open_source_hits", MODEL, 1, params,
                         user_id="bob"), None)
    own = ab.AICache.get("find_open_source_hits", MODEL, 1, params,
                         user_id="alice")
    check("cache: grounded result IS visible to its own user",
          own is not None and own["payload"] == [{"title": "story"}], True)
    check("cache: search suggestions survive the round trip",
          own and own["search_suggestions_html"], "<div>chips</div>")

    # And nothing grounded may sit in the shared table at all.
    from storage.db import AICache as AICacheRow
    from sqlalchemy import select
    with ab.session_factory()() as s:
        shared_tasks = set(s.execute(select(AICacheRow.task)).scalars().all())
    check("cache: shared table holds no grounded tasks",
          shared_tasks & set(config.GROUNDED_TASKS), set())

    # Expiry is honored rather than merely recorded.
    ab.AICache.put("adjudicate", MODEL, 1, {"k": "expired"}, {"v": 1})
    with ab.session_factory()() as s:
        row = s.execute(select(AICacheRow).where(
            AICacheRow.cache_key == ab.cache_key(
                "adjudicate", MODEL, 1, {"k": "expired"}))).scalars().one()
        row.expires_at = datetime(2000, 1, 1)
        s.commit()
    check("cache: expired rows are not served",
          ab.AICache.get("adjudicate", MODEL, 1, {"k": "expired"}), None)

    # A changed prompt version must not serve the old answer.
    check("cache: prompt version busts the key",
          ab.AICache.get("adjudicate", MODEL, 2, params), None)

    # ── Ledger and governor ──────────────────────────────────────────────────
    cost = ab.SpendLedger.record("adjudicate", MODEL, user_id="alice",
                                 input_tokens=1500, output_tokens=250)
    check("ledger: records the computed cost", abs(cost - adj) < 1e-9, True)
    check("ledger: month-to-date reflects it",
          abs(ab.SpendLedger.month_to_date() - adj) < 1e-9, True)

    # Cache hits are logged but cost nothing, so hit rate stays computable.
    ab.SpendLedger.record("adjudicate", MODEL, user_id="alice", cache_hit=True)
    check("ledger: cache hits cost nothing",
          abs(ab.SpendLedger.month_to_date() - adj) < 1e-9, True)
    check("ledger: cache hits don't consume credits",
          ab.SpendLedger.fresh_calls_this_month("alice"), 1)

    # Budget ceiling: a zero cap stops fresh calls but says why.
    original_cap = config.AI_MONTHLY_BUDGET_USD
    config.AI_MONTHLY_BUDGET_USD = 0.0
    d = ab.budget_guard("adjudicate", user_id="alice")
    check("governor: a zero ceiling blocks fresh calls", d.allowed, False)
    check("governor: blocked calls explain themselves",
          bool(d.message) and d.reason == "budget", True)
    config.AI_MONTHLY_BUDGET_USD = original_cap

    # Credit ceiling is separate from the dollar ceiling.
    d = ab.budget_guard("adjudicate", user_id="alice", credits=1)
    check("governor: credit exhaustion blocks the call", d.allowed, False)
    check("governor: credit block is labeled as such", d.reason, "credits")
    d = ab.budget_guard("adjudicate", user_id="alice", credits=99)
    check("governor: room under both ceilings allows the call", d.allowed, True)
    d = ab.budget_guard("adjudicate", user_id="newcomer", credits=None)
    check("governor: a fresh user is allowed", d.allowed, True)


    # ── Enricher governance (mocked SDK - no real API spend) ─────────────────
    # Proves the cache/guard/meter path end to end, including that a grounded
    # task's Search Suggestions survive and that its result never lands in the
    # shared table. A fake response object stands in for the SDK's.
    import analysis.oss_enricher as oe

    class _FakeUsage:
        prompt_token_count = 2000
        tool_use_prompt_token_count = 500
        candidates_token_count = 400
        thoughts_token_count = 100

    class _FakeSEP:
        rendered_content = "<div id='chips'>Search suggestions</div>"

    class _FakeGrounding:
        web_search_queries = ["hypersonics budget", "hypersonics FY2026",
                              "hypersonics testimony"]
        search_entry_point = _FakeSEP()
        grounding_chunks = []

    class _FakeCandidate:
        grounding_metadata = _FakeGrounding()

    class _FakeResp:
        candidates = [_FakeCandidate()]
        usage_metadata = _FakeUsage()
        text = '[{"title": "Hypersonics push", "source": "Breaking Defense", '               '"date": "2026-03", "summary": "More money.", "relevance": 0.9}]'

    u = oe._usage(_FakeResp())
    check("enricher: input tokens include tool-use prompt tokens",
          u["input_tokens"], 2500)
    check("enricher: thinking tokens are captured", u["thought_tokens"], 100)
    check("enricher: counts every executed search query",
          u["search_queries"], 3)
    check("enricher: captures the required Search Suggestions HTML",
          u["search_suggestions_html"], _FakeSEP.rendered_content)

    # Drive the governed path with a stubbed client.
    enricher = oe.GeminiEnricher.__new__(oe.GeminiEnricher)
    enricher.model = MODEL
    calls = {"n": 0}

    class _FakeModels:
        def generate_content(self, **kw):
            calls["n"] += 1
            return _FakeResp()

    class _FakeClient:
        models = _FakeModels()

    enricher.client = _FakeClient()

    # Cache-only probe on a cold key must not call the API.
    r = enricher.find_open_source_hits("Hypersonics", "0603286E", "Defense-Wide",
                                       user_id="carol", allow_fresh=False)
    check("enricher: cache-only probe does not call the API", calls["n"], 0)
    check("enricher: cold probe reports cold, not blocked",
          (r.cold, r.blocked), (True, False))

    # A fresh news lookup is deliberately two calls: grounded research, then
    # an ungrounded pass that structures it. See find_open_source_hits.
    r = enricher.find_open_source_hits("Hypersonics", "0603286E", "Defense-Wide",
                                       user_id="carol", credits=99)
    check("enricher: fresh news lookup makes both calls", calls["n"], 2)
    check("enricher: payload parsed", len(r.payload), 1)
    check("enricher: suggestions returned to the caller",
          r.search_suggestions_html, _FakeSEP.rendered_content)
    check("enricher: fresh call is not marked cached", r.cached, False)

    # The identical call is now served from cache without touching the API.
    r2 = enricher.find_open_source_hits("Hypersonics", "0603286E",
                                        "Defense-Wide", user_id="carol",
                                        credits=99)
    check("enricher: repeat call served from cache", calls["n"], 2)
    check("enricher: cached result is flagged cached", r2.cached, True)
    check("enricher: cached grounded result keeps its suggestions",
          r2.search_suggestions_html, _FakeSEP.rendered_content)

    # A different user must NOT see carol's grounded result - it re-fetches.
    r3 = enricher.find_open_source_hits("Hypersonics", "0603286E",
                                        "Defense-Wide", user_id="dave",
                                        credits=99)
    check("enricher: grounded cache is not shared across users",
          (calls["n"], r3.cached), (4, False))

    # force=True must skip the cache READ, or a "refresh" button silently
    # re-serves the answer it was supposed to replace - and at a spent budget
    # it would report success instead of explaining the refusal.
    n_pre = calls["n"]
    r_forced = enricher.find_open_source_hits("Hypersonics", "0603286E",
                                              "Defense-Wide", user_id="carol",
                                              credits=99, force=True)
    check("enricher: force bypasses the cache and re-calls",
          (calls["n"] - n_pre, r_forced.cached), (2, False))

    # ...but force must NOT bypass the ceiling.
    original_cap2 = config.AI_MONTHLY_BUDGET_USD
    config.AI_MONTHLY_BUDGET_USD = 0.0
    n_pre = calls["n"]
    r_capped = enricher.find_open_source_hits("Hypersonics", "0603286E",
                                              "Defense-Wide", user_id="carol",
                                              credits=99, force=True)
    check("enricher: a forced call still obeys the ceiling",
          (r_capped.blocked, calls["n"] - n_pre), (True, 0))
    check("enricher: the refusal carries a message",
          bool(r_capped.message), True)
    config.AI_MONTHLY_BUDGET_USD = original_cap2

    # If the model answers a "search the news" prompt without searching, the
    # output is recollection dressed as coverage. It must be discarded, not
    # cached, and flagged - this is the failure that motivated the two-step
    # design in the first place.
    class _UngroundedCandidate:
        grounding_metadata = None

    class _UngroundedResp:
        candidates = [_UngroundedCandidate()]
        usage_metadata = _FakeUsage()
        text = '[{"title": "Plausible but invented", "source": "Nowhere", '               '"date": "2026-01", "summary": "Recalled.", "relevance": 0.9}]'

    _FakeModels.generate_content = lambda self, **kw: (
        calls.__setitem__("n", calls["n"] + 1) or _UngroundedResp())
    n_before = calls["n"]
    r_ung = enricher.find_open_source_hits("Ghost Program", "0000000X",
                                           "Army", user_id="erin", credits=99)
    check("enricher: ungrounded news output is discarded",
          r_ung.payload, [])
    check("enricher: ungrounded result is flagged", r_ung.grounded, False)
    check("enricher: no second call once the search is skipped",
          calls["n"] - n_before, 1)
    check("enricher: an empty answer is not cached",
          ab.AICache.get("find_open_source_hits", MODEL, 1,
                         {"program_name": "Ghost Program",
                          "pe_number": "0000000X", "agency": "Army",
                          "max_hits": 6}, user_id="erin"), None)

    # Non-grounded adjudication IS shared across users.
    cands = [{"pe_number": "0603286E", "agency": "Defense-Wide",
              "name": "Advanced Aerospace Systems", "strategy": "FUZZY",
              "score": 0.9}]

    # A non-grounded response carries no grounding metadata at all - modelling
    # it as such is what makes the "adjudicate costs no search queries" check
    # meaningful.
    class _FakeAdjCandidate:
        grounding_metadata = None

    class _FakeAdjResp:
        candidates = [_FakeAdjCandidate()]
        usage_metadata = _FakeUsage()
        text = '{"pe_number": "0603286E", "agency": "Defense-Wide", '               '"confidence": 0.8, "rationale": "Fits.", "no_match": false}'

    _FakeModels.generate_content = lambda self, **kw: (
        calls.__setitem__("n", calls["n"] + 1) or _FakeAdjResp())
    before = calls["n"]
    enricher.adjudicate("hypersonics", cands, user_id="carol", credits=99)
    r4 = enricher.adjudicate("hypersonics", cands, user_id="dave", credits=99)
    check("enricher: non-grounded result IS shared across users",
          (calls["n"] - before, r4.cached), (1, True))

    # Ledger reflects the grounded queries so grounding cost is visible - and
    # ONLY the grounded ones: three grounded research calls (carol, dave, and
    # carol's forced refresh) at 3 queries each. The structuring pass, the
    # adjudications, and the ceiling-refused call all add nothing.
    check("enricher: only grounded calls add search queries",
          ab.SpendLedger.queries_this_month(), 9)

    # And the compliance invariant still holds after all that traffic.
    with ab.session_factory()() as s:
        tasks_now = set(s.execute(select(AICacheRow.task)).scalars().all())
    check("enricher: shared table still free of grounded tasks",
          tasks_now & set(config.GROUNDED_TASKS), set())

    # ── Report ───────────────────────────────────────────────────────────────
    text = ab.report()
    check("report: renders with data", "adjudicate" in text and "TOTAL" in text,
          True)

    # ── Output ───────────────────────────────────────────────────────────────
    print(f"{'RESULT':<8}{'CHECK'}")
    print("-" * 100)
    passed = 0
    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL':<8}{name}")
        if not ok:
            print(f"        {detail}")
        passed += ok
    print("-" * 100)
    print(f"{passed}/{len(results)} passed ({passed / len(results):.0%})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    logging.basicConfig(level="ERROR")
    sys.exit(run())
