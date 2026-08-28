"""
analysis/oss_enricher.py

Optional Gemini-backed enrichment for the Program Finder:

  1. adjudicate()           - given the user's statement and the linker's
                              candidate list, an LLM judges which Program
                              Element the statement most likely refers to,
                              with a confidence and a written rationale.
                              Raises semantic fidelity beyond cosine scores.
  2. find_open_source_hits() - Google-Search-grounded lookup of recent open
                              source mentions (news, press releases, hearings)
                              of a matched program, returned as structured
                              hits with source links.
  3. annual_signal()        - year-by-year characterization of open-source
                              emphasis, for the Rhetoric vs. Budget tab.

Every call is governed (see analysis/ai_budget.py): results are served from
cache when warm, a monthly ceiling and per-user credits gate fresh calls, and
each call's real token and search-query counts are written to a spend ledger.
Callers get an EnrichmentResult that says whether the answer was cached, when
it was produced, and - if the call was refused - a message to show the user.

Grounded tasks (find_open_source_hits, annual_signal) additionally carry the
Search Suggestions HTML that the Gemini API terms require be displayed with any
grounded result, and are cached per-user only, never shared.

Requires the `google-genai` package and an API key in GEMINI_API_KEY (or
GOOGLE_API_KEY). Everything degrades gracefully: no key / no package / API
error -> an empty result, never an exception to the caller.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from analysis.ai_budget import AICache, SpendLedger, budget_guard

logger = logging.getLogger(__name__)

# Bump a task's version when its prompt or output shape changes, so stale
# answers from the old prompt are never served.
PROMPT_VERSIONS = {
    "adjudicate": 1,
    "find_open_source_hits": 1,
    "annual_signal": 1,
}

ADJUDICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "pe_number": {"type": "STRING", "description": "PE number of the best candidate, or empty string if none fits"},
        "agency": {"type": "STRING"},
        "confidence": {"type": "NUMBER", "description": "0.0-1.0"},
        "rationale": {"type": "STRING", "description": "2-3 sentences, plain language"},
        "no_match": {"type": "BOOLEAN"},
    },
    "required": ["pe_number", "agency", "confidence", "rationale", "no_match"],
}


@dataclass
class EnrichmentResult:
    """
    What the UI needs to render an AI panel honestly: the answer, whether it
    came from cache (and when), the Search Suggestions that must accompany a
    grounded answer, and - when nothing was produced - why.
    """
    payload: Any = None
    cached: bool = False
    created_at: Optional[datetime] = None
    search_suggestions_html: Optional[str] = None
    blocked: bool = False      # a guard or an error stopped a fresh call
    cold: bool = False         # nothing cached and we were told not to spend
    grounded: bool = True      # False when a search-backed task didn't search
    message: str = ""

    @property
    def empty(self) -> bool:
        return self.payload is None or self.payload == [] or self.payload == {}


def _api_key() -> Optional[str]:
    for var in config.GEMINI_API_KEY_ENV_VARS:
        key = os.environ.get(var, "").strip()
        if key:
            return key
    # Hosted Streamlit (Community Cloud) delivers secrets via st.secrets,
    # not environment variables. Guarded: fine when streamlit is absent or
    # no secrets file exists.
    try:
        import streamlit as st
        for var in config.GEMINI_API_KEY_ENV_VARS:
            key = str(st.secrets.get(var, "")).strip()
            if key:
                return key
    except Exception:
        pass
    return None


def status() -> tuple[bool, str]:
    """
    ("ok" | "package" | "key") - whether enrichment can run, and if not,
    which piece is missing so the UI can show the right fix.
    """
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False, "package"
    if _api_key() is None:
        return False, "key"
    return True, "ok"


def available() -> bool:
    """True when the SDK is importable and an API key is configured."""
    return status()[0]


def _usage(resp) -> dict:
    """
    Pull the billable quantities out of a response. Defensive throughout: the
    SDK has moved these fields between versions, and a metering bug that raises
    is better than one that silently books every call as free.

    Verified against google-genai 2.19.0.
    """
    out = {"input_tokens": 0, "output_tokens": 0, "thought_tokens": 0,
           "search_queries": 0, "search_suggestions_html": None}
    um = getattr(resp, "usage_metadata", None)
    if um is not None:
        prompt = getattr(um, "prompt_token_count", 0) or 0
        # Tool-use prompt tokens are billed as input too - grounding pushes
        # search results back through the prompt, so this is not negligible.
        tool_prompt = getattr(um, "tool_use_prompt_token_count", 0) or 0
        out["input_tokens"] = prompt + tool_prompt
        out["output_tokens"] = getattr(um, "candidates_token_count", 0) or 0
        out["thought_tokens"] = getattr(um, "thoughts_token_count", 0) or 0
    try:
        gm = resp.candidates[0].grounding_metadata
        # Billing is per query EXECUTED, and one prompt can fire several.
        out["search_queries"] = len(getattr(gm, "web_search_queries", None) or [])
        sep = getattr(gm, "search_entry_point", None)
        if sep is not None:
            out["search_suggestions_html"] = getattr(sep, "rendered_content", None)
    except Exception:
        pass
    return out


class GeminiEnricher:
    """Thin wrapper around google-genai for Program Finder enrichment tasks."""

    def __init__(self, model: str = config.GEMINI_MODEL):
        from google import genai
        self.model = model
        self.client = genai.Client(api_key=_api_key())

    # ── Governance ────────────────────────────────────────────────────────────

    def _governed(self, task: str, params: dict, user_id: str,
                  allow_fresh: bool, credits: Optional[int],
                  call: Callable[[], tuple], empty,
                  force: bool = False) -> EnrichmentResult:
        """
        Cache -> guard -> call -> meter -> cache. The single path every AI task
        takes, so cost accounting and the compliance routing can't be bypassed
        by adding a new task later.

        `call` returns (payload, usage_dict). `empty` is the task's neutral
        value ([] or None) used when nothing can be produced.

        `force` skips the cache READ so a refresh actually refreshes - without
        it a "refresh" button just re-serves the cached answer it was meant to
        replace. It does not skip the guard: a forced call still has to fit
        under the ceiling.
        """
        version = PROMPT_VERSIONS.get(task, 1)

        hit = (None if force else
               AICache.get(task, self.model, version, params, user_id=user_id))
        if hit is not None:
            # Only count a hit when the caller would actually have spent.
            # Cache-only probes run on every Streamlit rerun, and booking those
            # would swamp the ledger and make the hit rate meaningless.
            if allow_fresh:
                SpendLedger.record(task, self.model, user_id=user_id,
                                   cache_hit=True)
            return EnrichmentResult(
                payload=hit["payload"], cached=True,
                created_at=hit["created_at"],
                search_suggestions_html=hit["search_suggestions_html"],
            )

        if not allow_fresh:
            # Cache-only probe: the caller is auto-rendering on page load and
            # explicitly does not want to spend. A miss here is normal, not an
            # error - the UI turns it into an offer to fetch.
            return EnrichmentResult(payload=empty, cold=True)

        decision = budget_guard(task, user_id=user_id, credits=credits)
        if not decision.allowed:
            logger.info(f"AI call refused ({decision.reason}): {task}")
            return EnrichmentResult(payload=empty, blocked=True,
                                    message=decision.message)

        try:
            payload, usage = call()
            ok = True
        except Exception as e:
            logger.warning(f"Gemini {task} failed: {e}")
            payload, usage, ok = empty, {}, False

        SpendLedger.record(
            task, self.model, user_id=user_id,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            thought_tokens=usage.get("thought_tokens", 0),
            search_queries=usage.get("search_queries", 0),
            cache_hit=False, ok=ok,
        )
        if not ok:
            return EnrichmentResult(
                payload=empty, blocked=True,
                message="The AI lookup failed. See the logs for details.",
            )

        suggestions = usage.get("search_suggestions_html")
        grounded = usage.get("grounded", True)

        # Never cache an empty answer: a transient failure or a skipped search
        # would otherwise be served as settled fact for the whole TTL.
        if payload not in (None, [], {}):
            AICache.put(task, self.model, version, params, payload,
                        user_id=user_id, search_suggestions_html=suggestions)
        return EnrichmentResult(payload=payload, cached=False,
                                created_at=datetime.now(),
                                search_suggestions_html=suggestions,
                                grounded=grounded)

    # ── Candidate adjudication ────────────────────────────────────────────────

    def adjudicate(self, query: str, candidates: List[dict],
                   user_id: str = "local", allow_fresh: bool = True,
                   credits: Optional[int] = None,
                   force: bool = False) -> EnrichmentResult:
        """
        LLM judgment over the linker's candidate list. Payload is
        {pe_number, agency, confidence, rationale, no_match} or None.

        Not grounded, so the answer is shared-cacheable - and at temperature 0
        over a fixed candidate set it's stable enough for a long TTL.
        """
        if not candidates:
            return EnrichmentResult(payload=None)

        params = {
            "query": query,
            "candidates": sorted(f"{c['pe_number']}|{c['agency']}"
                                 for c in candidates),
        }

        def call():
            from google.genai import types

            listing = "\n".join(
                f"- PE {c['pe_number']} [{c['agency']}]: {c['name']} "
                f"(retrieval: {c['strategy']} {c['score']:.2f})"
                for c in candidates
            )
            prompt = (
                "You are a US defense budget analyst. A user pasted this "
                f"statement or program reference:\n\n\"{query}\"\n\n"
                "Retrieval produced these candidate DoD RDT&E Program "
                f"Elements:\n{listing}\n\n"
                "Decide which single candidate the statement most likely "
                "refers to, using your knowledge of DoD programs, agencies, "
                "and terminology. If the statement names or implies a service "
                "or agency, weight that heavily. If none of the candidates "
                "plausibly match, set no_match=true. Be candid about "
                "uncertainty in the confidence value."
            )
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ADJUDICATION_SCHEMA,
                    temperature=0.0,
                ),
            )
            verdict = json.loads(resp.text)
            # Only trust verdicts that point at an actual candidate
            if not verdict.get("no_match"):
                known = {c["pe_number"] for c in candidates}
                if verdict.get("pe_number") not in known:
                    verdict["no_match"] = True
                    verdict["rationale"] += " (Model named a PE outside the candidate list - discarded.)"
            return verdict, _usage(resp)

        return self._governed("adjudicate", params, user_id, allow_fresh,
                              credits, call, empty=None, force=force)

    # ── Open-source mention search ────────────────────────────────────────────

    def find_open_source_hits(
        self, program_name: str, pe_number: str, agency: str,
        max_hits: int = 6, user_id: str = "local", allow_fresh: bool = True,
        credits: Optional[int] = None, force: bool = False,
    ) -> EnrichmentResult:
        """
        Grounded search for recent open-source mentions of the program.
        Payload is a list of {title, source, date, summary, url} dicts
        (possibly empty).

        Two calls, deliberately. Asking for grounded search AND strict JSON in
        one prompt is unreliable on this model: it frequently answers from
        memory instead of searching, returning invented outlets and dates with
        no grounding metadata. That fails twice over - the "news" is not news,
        and with no metadata the search queries bill invisibly. So:

          step 1  grounded research, prose output. Prose reliably triggers the
                  search tool, and its metadata carries both the executed-query
                  count (for billing) and the Search Suggestions HTML (which
                  the Gemini API terms require be displayed).
          step 2  a cheap, ungrounded call that structures step 1's findings.

        If step 1 did not actually search, this returns nothing rather than
        passing model recollection off as sourced coverage.
        """
        params = {"program_name": program_name, "pe_number": pe_number,
                  "agency": agency, "max_hits": max_hits}

        def call():
            from google.genai import types

            research_prompt = (
                "Use Google Search now to find recent public coverage of the "
                f"US defense budget program \"{program_name}\" (program "
                f"element {pe_number}, {agency}): news articles, DoD press "
                "releases, congressional hearing coverage, and analyst "
                "reporting - not the budget justification documents "
                "themselves. Search first and report only what you actually "
                "retrieved in this session; do not answer from memory.\n\n"
                f"List at most {max_hits} items. For each give the headline, "
                "the outlet, the approximate date, one sentence on what it "
                "says about this program, and how confident you are that it "
                "refers to THIS program rather than a similarly named one."
            )
            research = self.client.models.generate_content(
                model=self.model,
                contents=research_prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2,
                ),
            )
            usage = _usage(research)
            usage["grounded"] = (
                getattr(research.candidates[0], "grounding_metadata", None)
                is not None
            )
            if not usage["grounded"]:
                # The model skipped the search. Whatever it wrote is
                # recollection, not coverage - discard it.
                logger.info("find_open_source_hits: model did not search; "
                            "discarding ungrounded output.")
                return [], usage

            structure_prompt = (
                "Convert these research notes into JSON. Use ONLY what the "
                f"notes contain; invent nothing.\n\n"
                f"NOTES:\n{research.text or ''}\n\n"
                f"Output ONLY a JSON array of at most {max_hits} objects with "
                'keys: "title" (headline), "source" (outlet or site), '
                '"date" (YYYY-MM or "unknown"), "summary" (1-2 sentences), '
                '"relevance" (0.0-1.0). Empty array if the notes list nothing.'
            )
            structured = self.client.models.generate_content(
                model=self.model,
                contents=structure_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            # Bill both calls: the second is ungrounded but not free.
            s_usage = _usage(structured)
            for k in ("input_tokens", "output_tokens", "thought_tokens"):
                usage[k] += s_usage[k]

            hits = self._parse_hits(structured.text or "")
            self._attach_citations(hits, research)
            hits.sort(key=lambda h: h.get("relevance", 0), reverse=True)
            return hits[:max_hits], usage

        return self._governed("find_open_source_hits", params, user_id,
                              allow_fresh, credits, call, empty=[], force=force)

    # ── Annual open-source signal (rhetoric vs. budget) ───────────────────────

    def annual_signal(
        self, program_name: str, pe_numbers: List[str], start_year: int,
        end_year: int, user_id: str = "local", allow_fresh: bool = True,
        credits: Optional[int] = None, force: bool = False,
    ) -> EnrichmentResult:
        """
        Year-by-year AI characterization of open-source emphasis on a
        program: mention intensity, sentiment split, whether officials named
        it a priority, and one notable sourced statement per year. This is an
        LLM estimate grounded in web search - NOT a media-analytics count.
        Payload is a list of per-year dicts (possibly empty).
        """
        params = {"program_name": program_name,
                  "pe_numbers": sorted(pe_numbers),
                  "start_year": start_year, "end_year": end_year}

        def call():
            from google.genai import types

            years = ", ".join(str(y) for y in range(start_year, end_year + 1))
            prompt = (
                "Use Google Search now to research public statements about "
                f"the US defense program \"{program_name}\" (budget program "
                f"elements: {', '.join(pe_numbers)}) for each fiscal year: "
                f"{years}. Search first and base your answer on what you "
                "actually retrieved; do not answer from memory alone. "
                "Consider DoD press briefings, congressional testimony, "
                "service officials' speeches, trade press, and social media "
                "coverage of official statements.\n\n"
                "Return ONLY a JSON array (no prose) with one object per "
                "year, keys:\n"
                '"fiscal_year" (int), '
                '"mention_intensity" (0-10: how much public discussion vs. '
                "this program's own typical baseline; 0=none, 10=constant), "
                '"positive_pct" (0-100: share of statements favorable/'
                "expanding), "
                '"negative_pct" (0-100: share critical/cutting), '
                '"stated_priority" (bool: did officials explicitly name it '
                "a priority or area of emphasis that year), "
                '"notable_statement" (one short paraphrased statement), '
                '"statement_source" (who said it / where, with year).\n'
                "Estimate honestly; use low intensity for years you find "
                "little evidence. Cover every requested year."
            )
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2,
                ),
            )
            usage = _usage(resp)
            usage["grounded"] = (
                getattr(resp.candidates[0], "grounding_metadata", None)
                is not None
            )
            if not usage["grounded"]:
                # This feeds a correlation coefficient presented as evidence.
                # Numbers the model recalled rather than researched would look
                # identical to real ones on the chart, so refuse them.
                logger.info("annual_signal: model did not search; discarding "
                            "ungrounded characterization.")
                return [], usage
            rows = self._parse_annual_signal(resp.text or "",
                                             start_year, end_year)
            return rows, usage

        return self._governed("annual_signal", params, user_id, allow_fresh,
                              credits, call, empty=[], force=force)

    @staticmethod
    def _parse_annual_signal(text: str, start_year: int,
                             end_year: int) -> List[dict]:
        """Defensive parse (grounded search cannot use JSON mode)."""
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            raw = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                fy = int(item.get("fiscal_year"))
            except (TypeError, ValueError):
                continue
            if not (start_year <= fy <= end_year):
                continue

            def num(key, lo, hi, default=0.0):
                try:
                    return min(max(float(item.get(key, default)), lo), hi)
                except (TypeError, ValueError):
                    return default

            out.append({
                "fiscal_year": fy,
                "mention_intensity": num("mention_intensity", 0, 10),
                "positive_pct": num("positive_pct", 0, 100),
                "negative_pct": num("negative_pct", 0, 100),
                "stated_priority": bool(item.get("stated_priority")),
                "notable_statement": str(item.get("notable_statement") or ""),
                "statement_source": str(item.get("statement_source") or ""),
            })
        out.sort(key=lambda d: d["fiscal_year"])
        return out

    @staticmethod
    def _parse_hits(text: str) -> List[dict]:
        """Search grounding cannot use JSON mode, so parse defensively."""
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            raw = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
        hits = []
        for item in raw:
            if isinstance(item, dict) and item.get("title"):
                hits.append({
                    "title": str(item.get("title", "")),
                    "source": str(item.get("source", "")),
                    "date": str(item.get("date", "unknown")),
                    "summary": str(item.get("summary", "")),
                    "relevance": float(item.get("relevance", 0.5) or 0.5),
                    "url": str(item.get("url", "")),
                })
        return hits

    @staticmethod
    def _attach_citations(hits: List[dict], resp) -> None:
        """Best-effort: pair grounding citation URLs with hits by title/source."""
        try:
            chunks = resp.candidates[0].grounding_metadata.grounding_chunks or []
            citations = [
                {"title": (c.web.title or ""), "url": c.web.uri}
                for c in chunks if getattr(c, "web", None) and c.web.uri
            ]
        except Exception:
            return
        for hit in hits:
            if hit.get("url"):
                continue
            probe = (hit["source"] or hit["title"]).lower()[:25]
            for cit in citations:
                if probe and probe in cit["title"].lower():
                    hit["url"] = cit["url"]
                    break
        # Leftover citations become bare source links on hits without URLs
        unused = [c for c in citations if c["url"] not in {h.get("url") for h in hits}]
        for hit, cit in zip([h for h in hits if not h.get("url")], unused):
            hit["url"] = cit["url"]


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    if not available():
        print("Gemini enrichment unavailable: install google-genai and set "
              f"one of {config.GEMINI_API_KEY_ENV_VARS}.")
        sys.exit(1)
    enricher = GeminiEnricher()
    result = enricher.find_open_source_hits(
        "Tactical Technology", "0602702E", "Defense-Wide"
    )
    print(json.dumps(result.payload, indent=2))
    print(f"\ncached={result.cached} blocked={result.blocked} "
          f"{result.message}")
    print("\n--- month to date ---")
    from analysis.ai_budget import report
    print(report())
