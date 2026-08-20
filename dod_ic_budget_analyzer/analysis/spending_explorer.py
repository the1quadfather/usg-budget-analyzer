"""
analysis/spending_explorer.py

"Where the money went" - execution-side drill-downs from the USAspending.gov
API, joined to the budget side by Treasury Account (TAS).

Two levels of fidelity, labeled honestly in the UI:

  account_breakdown()  - SOLID: obligations for a component's RDT&E
                         appropriation account broken down by recipient,
                         state, or industry (NAICS). Official TAS-filtered
                         totals.
  program_awards()     - BEST-EFFORT: DoD-funded prime awards (FAR contracts
                         AND CFR assistance instruments - grants/cooperative
                         agreements) whose records match the program keywords.
                         DoD award records carry no program-element linkage
                         (program-activity fields are null), so keyword
                         matching is the only public route to PE-ish
                         granularity. Deliberately NOT TAS-filtered: many
                         awards lack account linkage in the search index and
                         a TAS filter silently drops them (verified with
                         Army Launched Effects awards).
  program_subawards()  - subaward-level search for work that rides under
                         umbrella vehicles (PIAs, OTAs, IDIQs) whose prime
                         descriptions are generic boilerplate.

Known blind spots (surface these to users): Other Transactions are not a
searchable instrument group in the API; DoD awards post with a ~90-day
display delay; the current fiscal year is always partial.
"""

import logging
import re
from typing import Optional

import pandas as pd

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from acquisition.usaspending_client import USASpendingHTTP

logger = logging.getLogger(__name__)

# Component -> RDT&E appropriation Treasury Account (agency id, main account)
RDTE_ACCOUNTS = {
    "Army":         ("021", "2040"),
    "Navy":         ("017", "1319"),
    "Air Force":    ("057", "3600"),
    "Space Force":  ("057", "3620"),
    "Defense-Wide": ("097", "0400"),
    "OT&E":         ("097", "0460"),
}

CATEGORY_ENDPOINTS = {
    "recipient": "/search/spending_by_category/recipient",
    "state":     "/search/spending_by_category/state_territory",
    "industry":  "/search/spending_by_category/naics",
}

AWARD_URL = "https://www.usaspending.gov/award/{}"


def _fy_period(fy_start: int, fy_end: Optional[int] = None) -> list[dict]:
    fy_end = fy_end or fy_start
    return [{"start_date": f"{fy_start - 1}-10-01", "end_date": f"{fy_end}-09-30"}]


class SpendingExplorer:
    """USAspending drill-downs keyed to the analyzer's components."""

    def __init__(self):
        self.http = USASpendingHTTP()

    def close(self):
        self.http.close()

    def _account_filter(self, component: str) -> Optional[list[dict]]:
        acct = RDTE_ACCOUNTS.get(component)
        if acct is None:
            logger.warning(f"No RDT&E account mapping for component '{component}'")
            return None
        return [{"aid": acct[0], "main": acct[1]}]

    # ── Account-level (solid) ─────────────────────────────────────────────────

    def account_breakdown(
        self,
        component: str,
        fiscal_year: int,
        category: str = "recipient",
        limit: int = 10,
    ) -> pd.DataFrame:
        """
        Top obligations in the component's RDT&E account for one fiscal year,
        by recipient / state / industry. Returns columns [name, amount].
        """
        tas = self._account_filter(component)
        endpoint = CATEGORY_ENDPOINTS.get(category)
        if tas is None or endpoint is None:
            return pd.DataFrame()

        payload = {
            "filters": {
                "time_period": _fy_period(fiscal_year),
                "tas_codes": tas,
                "award_type_codes": list(config.USASPENDING_AWARD_TYPES),
            },
            "category": endpoint.rsplit("/", 1)[-1],
            "limit": limit,
            "page": 1,
        }
        try:
            data = self.http.post(endpoint, payload)
        except Exception as e:
            logger.warning(f"account_breakdown({component}, {fiscal_year}) failed: {e}")
            return pd.DataFrame()

        rows = [
            {"name": r.get("name") or r.get("code") or "Unknown",
             "amount": float(r.get("amount") or 0.0)}
            for r in data.get("results", [])
        ]
        return pd.DataFrame(rows)

    # ── Program-level (best-effort keyword match) ─────────────────────────────

    ASSISTANCE_TYPES = ["02", "03", "04", "05"]
    DOD_FUNDING = [{"type": "funding", "tier": "toptier",
                    "name": "Department of Defense"}]

    @staticmethod
    def build_keywords(program_name: str, query_text: str = "") -> list[str]:
        """
        Keyword phrases for award search, OR'd by the API. The user's own
        query phrase is the strongest signal (full PE titles almost never
        appear verbatim in award descriptions); parenthetical acronyms and
        the stripped title round it out.
        """
        stripped = re.sub(r"\([^)]*\)", " ", program_name)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        candidates = {stripped, *re.findall(r"\(([^)]+)\)", program_name)}
        query_clean = re.sub(r"\s+", " ", query_text or "").strip()
        if query_clean:
            candidates.add(query_clean)
        return [k for k in candidates if len(k) >= 3][:8]

    def program_awards(
        self,
        program_name: str,
        component: str,
        fy_start: int,
        fy_end: int,
        query_text: str = "",
        limit: int = 12,
    ) -> pd.DataFrame:
        """
        Largest DoD-funded prime awards matching the program keywords, across
        both instrument groups the API can address: FAR contracts (A-D) and
        CFR assistance (grants/cooperative agreements). Keyword-based -
        treat as leads, not ledger truth.
        """
        keywords = self.build_keywords(program_name, query_text)
        if not keywords:
            return pd.DataFrame()

        groups = [
            ("Contract", list(config.USASPENDING_AWARD_TYPES),
             "Contract Award Type"),
            ("Assistance", self.ASSISTANCE_TYPES, "Award Type"),
        ]
        rows = []
        for group_label, type_codes, type_field in groups:
            payload = {
                "filters": {
                    "time_period": _fy_period(fy_start, fy_end),
                    "award_type_codes": type_codes,
                    "keywords": keywords,
                    "agencies": self.DOD_FUNDING,
                },
                "fields": [
                    "Award ID", "Recipient Name", "Award Amount",
                    "Description", "Awarding Sub Agency", "Start Date",
                    type_field, "generated_internal_id",
                ],
                "sort": "Award Amount",
                "order": "desc",
                "limit": limit,
                "page": 1,
            }
            try:
                data = self.http.post("/search/spending_by_award/", payload)
            except Exception as e:
                logger.warning(f"program_awards {group_label} failed: {e}")
                continue
            for r in data.get("results", []):
                rows.append({
                    "recipient": r.get("Recipient Name") or "Unknown",
                    "amount": float(r.get("Award Amount") or 0.0),
                    "instrument": (r.get(type_field) or group_label).title(),
                    "description": (r.get("Description") or "").strip(),
                    "sub_agency": r.get("Awarding Sub Agency") or "",
                    "start_date": r.get("Start Date") or "",
                    "url": AWARD_URL.format(r["generated_internal_id"])
                           if r.get("generated_internal_id") else "",
                })

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("amount", ascending=False).head(limit).reset_index(drop=True)

    def program_subawards(
        self,
        program_name: str,
        fy_start: int,
        fy_end: int,
        query_text: str = "",
        limit: int = 10,
    ) -> pd.DataFrame:
        """
        Subaward-level search - catches work executed under umbrella vehicles
        (PIAs, IDIQs) where the prime award description is boilerplate.
        """
        keywords = self.build_keywords(program_name, query_text)
        if not keywords:
            return pd.DataFrame()

        rows = []
        for type_codes in (list(config.USASPENDING_AWARD_TYPES),
                           self.ASSISTANCE_TYPES):
            payload = {
                "filters": {
                    "time_period": _fy_period(fy_start, fy_end),
                    "award_type_codes": type_codes,
                    "keywords": keywords,
                },
                "fields": [
                    "Sub-Award ID", "Sub-Awardee Name", "Sub-Award Amount",
                    "Sub-Award Date", "Sub-Award Description",
                    "Prime Recipient Name",
                ],
                "spending_level": "subawards",
                "sort": "Sub-Award Amount",
                "order": "desc",
                "limit": limit,
                "page": 1,
            }
            try:
                data = self.http.post("/search/spending_by_award/", payload)
            except Exception as e:
                logger.warning(f"program_subawards failed: {e}")
                continue
            for r in data.get("results", []):
                rows.append({
                    "subawardee": r.get("Sub-Awardee Name") or "Unknown",
                    "amount": float(r.get("Sub-Award Amount") or 0.0),
                    "date": r.get("Sub-Award Date") or "",
                    "description": (r.get("Sub-Award Description") or "").strip(),
                    "prime_recipient": r.get("Prime Recipient Name") or "",
                })

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("amount", ascending=False).head(limit).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    ex = SpendingExplorer()
    print("Top Army RDT&E recipients, FY2025:")
    print(ex.account_breakdown("Army", 2025).to_string())
    print("\nAwards matching 'Tactical Technology' (Defense-Wide, FY2024-25):")
    df = ex.program_awards("Tactical Technology", "Defense-Wide", 2024, 2025)
    print(df[["recipient", "amount", "description"]].head().to_string()
          if not df.empty else "  (none)")
    ex.close()
