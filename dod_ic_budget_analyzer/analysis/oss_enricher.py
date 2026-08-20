"""
analysis/oss_enricher.py

Optional Gemini-backed enrichment for the Statement Linker:

  1. adjudicate()           - given the user's statement and the linker's
                              candidate list, an LLM judges which Program
                              Element the statement most likely refers to,
                              with a confidence and a written rationale.
                              Raises semantic fidelity beyond cosine scores.
  2. find_open_source_hits() - Google-Search-grounded lookup of recent open
                              source mentions (news, press releases, hearings)
                              of a matched program, returned as structured
                              hits with source links.

Requires the `google-genai` package and an API key in GEMINI_API_KEY (or
GOOGLE_API_KEY). Everything degrades gracefully: no key / no package / API
error -> None or [], never an exception to the caller.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

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


def _api_key() -> Optional[str]:
    for var in config.GEMINI_API_KEY_ENV_VARS:
        key = os.environ.get(var, "").strip()
        if key:
            return key
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


class GeminiEnricher:
    """Thin wrapper around google-genai for linker enrichment tasks."""

    def __init__(self, model: str = config.GEMINI_MODEL):
        from google import genai
        self.model = model
        self.client = genai.Client(api_key=_api_key())

    # ── Candidate adjudication ────────────────────────────────────────────────

    def adjudicate(self, query: str, candidates: List[dict]) -> Optional[dict]:
        """
        LLM judgment over the linker's candidate list. Returns
        {pe_number, agency, confidence, rationale, no_match} or None on error.
        """
        if not candidates:
            return None
        try:
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
            return verdict
        except Exception as e:
            logger.warning(f"Gemini adjudication failed: {e}")
            return None

    # ── Open-source mention search ────────────────────────────────────────────

    def find_open_source_hits(
        self, program_name: str, pe_number: str, agency: str, max_hits: int = 6
    ) -> List[dict]:
        """
        Grounded search for recent open-source mentions of the program.
        Returns a list of {title, source, date, summary, url} dicts
        (possibly empty). Grounding citations fill in missing URLs.
        """
        try:
            from google.genai import types

            prompt = (
                f"Search for recent open-source mentions of the US defense "
                f"program \"{program_name}\" (budget program element "
                f"{pe_number}, {agency}). Look for news articles, DoD press "
                f"releases, congressional hearing coverage, and analyst "
                f"reporting - not the budget documents themselves.\n\n"
                f"Return ONLY a JSON array (no prose) of at most {max_hits} "
                "objects with keys: "
                '"title" (headline), "source" (outlet or site), '
                '"date" (YYYY-MM or "unknown"), '
                '"summary" (1-2 sentences on what it says about the program), '
                '"relevance" (0.0-1.0, how clearly it refers to THIS program '
                "rather than a similarly named one)."
            )
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.2,
                ),
            )
            hits = self._parse_hits(resp.text or "")
            self._attach_citations(hits, resp)
            hits.sort(key=lambda h: h.get("relevance", 0), reverse=True)
            return hits[:max_hits]
        except Exception as e:
            logger.warning(f"Gemini open-source search failed: {e}")
            return []

    # ── Annual open-source signal (rhetoric vs. budget) ───────────────────────

    def annual_signal(
        self,
        program_name: str,
        pe_numbers: List[str],
        start_year: int,
        end_year: int,
    ) -> List[dict]:
        """
        Year-by-year AI characterization of open-source emphasis on a
        program: mention intensity, sentiment split, whether officials named
        it a priority, and one notable sourced statement per year. This is an
        LLM estimate grounded in web search - NOT a media-analytics count.
        Returns a list of per-year dicts (possibly empty).
        """
        try:
            from google.genai import types

            years = ", ".join(str(y) for y in range(start_year, end_year + 1))
            prompt = (
                f"Research public statements about the US defense program "
                f"\"{program_name}\" (budget program elements: "
                f"{', '.join(pe_numbers)}) for each fiscal year: {years}. "
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
            return self._parse_annual_signal(resp.text or "",
                                             start_year, end_year)
        except Exception as e:
            logger.warning(f"Gemini annual_signal failed: {e}")
            return []

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
    hits = enricher.find_open_source_hits(
        "Tactical Technology", "0602702E", "Defense-Wide"
    )
    print(json.dumps(hits, indent=2))
