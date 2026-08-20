"""
acquisition/usaspending_client.py

Client for the USASpending.gov REST API (v2).
Pulls contract awards, spending summaries, and agency breakdowns
for DoD and IC components.

API docs: https://api.usaspending.gov/

Primary endpoints used:
  - /api/v2/search/spending_by_award/      → contract-level award search
  - /api/v2/spending/                       → top-down spending hierarchy
  - /api/v2/agency/{toptier_code}/          → agency metadata
  - /api/v2/references/toptier_agencies/    → agency code lookup

Usage:
    client = USASpendingClient()
    df = client.search_awards(
        agency_codes=["097"],       # DoD
        fiscal_years=[2024, 2025],
        award_types=["A", "B", "C", "D"],
    )
    df.to_parquet("data/raw/usaspending/dod_contracts.parquet")
"""

import json
import logging
import time
from pathlib import Path

import httpx
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── Low-level HTTP ────────────────────────────────────────────────────────────

class USASpendingHTTP:
    """Thin wrapper around httpx for the USASpending API."""

    def __init__(self):
        transport = httpx.HTTPTransport(retries=config.HTTP_RETRY_ATTEMPTS)
        self._client = httpx.Client(
            base_url=config.USASPENDING_API_BASE,
            headers={**config.HTTP_HEADERS, "Content-Type": "application/json"},
            timeout=config.HTTP_TIMEOUT,
            transport=transport,
            follow_redirects=True,
        )

    def get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(config.HTTP_RETRY_ATTEMPTS):
            try:
                resp = self._client.get(path, params=params)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"GET {path} → HTTP {e.response.status_code} (attempt {attempt+1})"
                )
                if e.response.status_code in (400, 404):
                    raise
                _backoff(attempt)
            except httpx.RequestError as e:
                logger.warning(f"GET {path} → RequestError (attempt {attempt+1}): {e}")
                _backoff(attempt)
        raise RuntimeError(f"Exhausted retries for GET {path}")

    def post(self, path: str, payload: dict) -> dict:
        for attempt in range(config.HTTP_RETRY_ATTEMPTS):
            try:
                resp = self._client.post(path, content=json.dumps(payload))
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"POST {path} → HTTP {e.response.status_code} (attempt {attempt+1})"
                )
                if e.response.status_code in (400, 422):
                    logger.error(f"  Body: {e.response.text[:400]}")
                    raise
                _backoff(attempt)
            except httpx.RequestError as e:
                logger.warning(f"POST {path} → RequestError (attempt {attempt+1}): {e}")
                _backoff(attempt)
        raise RuntimeError(f"Exhausted retries for POST {path}")

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _backoff(attempt: int) -> None:
    wait = config.HTTP_RETRY_BACKOFF ** (attempt + 1)
    logger.debug(f"Sleeping {wait:.1f}s before retry")
    time.sleep(wait)


# ── Award Search ──────────────────────────────────────────────────────────────

# Fields to request from the awards endpoint
AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Start Date",
    "End Date",
    "Award Amount",
    "Total Outlays",
    "Description",
    "Contract Award Type",
    "Award Type",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Funding Sub Agency",
    "Place of Performance State Code",
    "Place of Performance Country Code",
    "NAICS Code",
    "NAICS Description",
    "Program Activity Name",
    "Program Activity Code",
    "Object Class",
    "Period of Performance Start Date",
    "Period of Performance Current End Date",
    "Last Date to Order",
    "SAI Number",
]


class AwardSearcher:
    """
    Wraps the /api/v2/search/spending_by_award/ endpoint.
    Handles pagination automatically, yielding pages of results.
    """

    ENDPOINT = "/search/spending_by_award/"

    def __init__(self, http: USASpendingHTTP):
        self.http = http

    def search(
        self,
        agency_codes: list[str],
        fiscal_years: list[int],
        award_types: list[str] = config.USASPENDING_AWARD_TYPES,
        keywords: list[str] | None = None,
        page_size: int = config.USASPENDING_PAGE_SIZE,
    ) -> list[dict]:
        """
        Search contract awards for the given agencies and fiscal years.

        Args:
            agency_codes: CGAC codes, e.g. ["097"] for DoD
            fiscal_years: e.g. [2024, 2025]
            award_types:  ["A","B","C","D"] = all contract types
            keywords:     optional keyword filter (e.g. program names)
            page_size:    results per page (max 100)

        Returns:
            Flat list of award dicts.
        """
        filters = self._build_filters(
            agency_codes, fiscal_years, award_types, keywords
        )
        all_records = []
        page = 1

        while True:
            payload = {
                "filters": filters,
                "fields": AWARD_FIELDS,
                "sort": "Award Amount",
                "order": "desc",
                "limit": page_size,
                "page": page,
            }
            logger.info(
                f"  Fetching awards page {page} "
                f"(agencies={agency_codes}, FY={fiscal_years}) ..."
            )
            data = self.http.post(self.ENDPOINT, payload)

            results = data.get("results", [])
            all_records.extend(results)

            total_count = data.get("page_metadata", {}).get("count", 0)
            has_next = data.get("page_metadata", {}).get("has_next_page", False)

            logger.info(
                f"    Page {page}: {len(results)} records "
                f"(total so far: {len(all_records)}/{total_count})"
            )

            if not has_next or not results:
                break

            page += 1
            time.sleep(0.5)  # polite paging

        return all_records

    def _build_filters(
        self,
        agency_codes: list[str],
        fiscal_years: list[int],
        award_types: list[str],
        keywords: list[str] | None,
    ) -> dict:
        filters: dict = {
            "award_type_codes": award_types,
            "agencies": [
                {"type": "funding", "tier": "toptier", "toptier_code": code}
                for code in agency_codes
            ],
            "time_period": [
                {"start_date": f"10/01/{fy - 1}", "end_date": f"09/30/{fy}"}
                for fy in fiscal_years
            ],
        }
        if keywords:
            filters["keywords"] = keywords
        return filters


# ── Spending Hierarchy ────────────────────────────────────────────────────────

class SpendingHierarchyFetcher:
    """
    Wraps the /api/v2/spending/ endpoint to pull top-down budget hierarchy:
    Agency → Federal Account → Program Activity → Object Class.
    """

    ENDPOINT = "/spending/"

    def __init__(self, http: USASpendingHTTP):
        self.http = http

    def get_agency_spending(
        self,
        agency_code: str,
        fiscal_year: int,
        level: str = "program_activity",
    ) -> list[dict]:
        """
        Pull spending breakdown for an agency at the given level.

        Args:
            agency_code: CGAC toptier code (e.g. "097" for DoD)
            fiscal_year: FY to query
            level: one of "budget_function", "agency", "federal_account",
                   "program_activity", "object_class", "recipient", "award"

        Returns:
            List of spending category dicts with name, amount, etc.
        """
        payload = {
            "type": level,
            "filters": {
                "fy": str(fiscal_year),
                "quarter": "4",        # End-of-year actuals
                "agency": agency_code,
            },
        }
        logger.info(
            f"Fetching {level} spending for agency {agency_code} FY{fiscal_year}"
        )
        data = self.http.post(self.ENDPOINT, payload)
        results = data.get("results", [])
        logger.info(f"  → {len(results)} {level} categories")
        return results

    def get_full_hierarchy(
        self,
        agency_code: str,
        fiscal_years: list[int],
    ) -> dict[int, dict]:
        """
        For each fiscal year, fetch spending at multiple levels.
        Returns {fiscal_year: {level: [results]}}.
        """
        levels = ["federal_account", "program_activity", "object_class"]
        output = {}
        for fy in fiscal_years:
            output[fy] = {}
            for level in levels:
                try:
                    output[fy][level] = self.get_agency_spending(
                        agency_code, fy, level
                    )
                except Exception as e:
                    logger.warning(
                        f"  Skipping {level} for {agency_code} FY{fy}: {e}"
                    )
                time.sleep(0.3)
        return output


# ── Agency Metadata ───────────────────────────────────────────────────────────

class AgencyMetadataFetcher:
    """Fetches agency metadata and sub-agency listings."""

    def __init__(self, http: USASpendingHTTP):
        self.http = http

    def get_toptier_agencies(self) -> pd.DataFrame:
        """Return a DataFrame of all toptier agencies with their CGAC codes."""
        data = self.http.get("/references/toptier_agencies/")
        agencies = data.get("results", [])
        return pd.DataFrame(agencies)

    def get_subtier_agencies(self, toptier_code: str) -> list[dict]:
        """Return sub-tier agencies (e.g. Army, Navy) under a toptier (DoD)."""
        data = self.http.get(f"/agency/{toptier_code}/sub_components/")
        return data.get("results", [])


# ── Main Client ───────────────────────────────────────────────────────────────

class USASpendingClient:
    """
    Top-level client. Combines award search and spending hierarchy
    into a simple interface for pulling and saving data.

    Example:
        with USASpendingClient() as client:
            # Pull all DoD RDT&E contract awards for FY2024-2025
            df = client.get_awards_dataframe(
                agency_codes=["097"],
                fiscal_years=[2024, 2025],
                keywords=["research", "development", "test"],
            )
            client.save(df, "dod_rdtee_awards")

            # Pull spending hierarchy
            hierarchy = client.get_spending_hierarchy(
                agency_code="097",
                fiscal_years=[2024, 2025],
            )
    """

    def __init__(self):
        self.http = USASpendingHTTP()
        self.awards = AwardSearcher(self.http)
        self.spending = SpendingHierarchyFetcher(self.http)
        self.agencies = AgencyMetadataFetcher(self.http)

    def get_awards_dataframe(
        self,
        agency_codes: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        award_types: list[str] = config.USASPENDING_AWARD_TYPES,
        keywords: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Search awards and return as a pandas DataFrame.
        """
        agency_codes = agency_codes or list(config.USASPENDING_AGENCY_CODES.values())
        fiscal_years = fiscal_years or config.FISCAL_YEARS

        records = self.awards.search(
            agency_codes=agency_codes,
            fiscal_years=fiscal_years,
            award_types=award_types,
            keywords=keywords,
        )

        if not records:
            logger.warning("No records returned.")
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df = self._clean_awards_df(df)
        logger.info(f"Awards DataFrame: {len(df)} rows, {len(df.columns)} columns")
        return df

    def get_spending_hierarchy(
        self,
        agency_code: str,
        fiscal_years: list[int] | None = None,
    ) -> dict:
        fiscal_years = fiscal_years or config.FISCAL_YEARS
        return self.spending.get_full_hierarchy(agency_code, fiscal_years)

    def save(
        self,
        df: pd.DataFrame,
        name: str,
        fmt: str = "parquet",
    ) -> Path:
        """
        Save a DataFrame to data/raw/usaspending/.

        Args:
            df:   DataFrame to save
            name: base filename (no extension)
            fmt:  "parquet" (default) or "csv"
        """
        config.USASPENDING_DIR.mkdir(parents=True, exist_ok=True)
        path = config.USASPENDING_DIR / f"{name}.{fmt}"
        if fmt == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)
        logger.info(f"Saved {len(df)} rows → {path}")
        return path

    def save_json(self, data: dict | list, name: str) -> Path:
        path = config.USASPENDING_DIR / f"{name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved JSON → {path}")
        return path

    # ── Convenience methods for DoD/IC ────────────────────────────────────────

    def pull_dod_contracts(
        self,
        fiscal_years: list[int] | None = None,
        rdtee_only: bool = True,
    ) -> pd.DataFrame:
        """
        Pull DoD-wide contract awards.
        If rdtee_only=True, filters by R&D NAICS codes.
        """
        keywords = None
        if rdtee_only:
            # Broad R&D related keywords — refine as needed
            keywords = [
                "research", "development", "test and evaluation",
                "RDT&E", "prototype", "advanced technology",
            ]
        return self.get_awards_dataframe(
            agency_codes=[config.USASPENDING_AGENCY_CODES["dod"]],
            fiscal_years=fiscal_years,
            keywords=keywords,
        )

    def pull_ic_contracts(
        self,
        fiscal_years: list[int] | None = None,
    ) -> pd.DataFrame:
        """Pull contract awards for the public IC components (DIA, NGA, NRO)."""
        codes = [
            config.USASPENDING_AGENCY_CODES[c]
            for c in config.IC_COMPONENTS_PUBLIC
            if c in config.USASPENDING_AGENCY_CODES
        ]
        return self.get_awards_dataframe(
            agency_codes=codes,
            fiscal_years=fiscal_years,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_awards_df(df: pd.DataFrame) -> pd.DataFrame:
        """Normalise column names and types."""
        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace(r"[\s/]+", "_", regex=True)
            .str.replace(r"[^a-z0-9_]", "", regex=True)
        )
        # Numeric coercion
        for col in ["award_amount", "total_outlays"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # Date coercion
        for col in ["start_date", "end_date",
                    "period_of_performance_start_date",
                    "period_of_performance_current_end_date"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── CLI Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Pull DoD/IC award data from USASpending.gov"
    )
    parser.add_argument(
        "--target", choices=["dod", "ic", "both"], default="dod",
        help="Which agency group to pull"
    )
    parser.add_argument(
        "--years", nargs="+", type=int,
        default=config.FISCAL_YEARS,
        help="Fiscal years (e.g. 2024 2025)"
    )
    parser.add_argument(
        "--rdtee-only", action="store_true",
        help="Filter DoD pull to R&D-related keywords"
    )
    parser.add_argument(
        "--hierarchy", action="store_true",
        help="Also pull spending hierarchy for DoD"
    )
    parser.add_argument(
        "--format", choices=["parquet", "csv"], default="parquet",
        help="Output format"
    )
    args = parser.parse_args()

    with USASpendingClient() as client:
        if args.target in ("dod", "both"):
            df = client.pull_dod_contracts(
                fiscal_years=args.years,
                rdtee_only=args.rdtee_only,
            )
            if not df.empty:
                client.save(df, "dod_contracts", fmt=args.format)
                print(f"\nDoD contracts: {len(df)} awards")
                print(df[["award_id", "award_amount", "description",
                           "awarding_sub_agency"]].head(10).to_string())

        if args.target in ("ic", "both"):
            df_ic = client.pull_ic_contracts(fiscal_years=args.years)
            if not df_ic.empty:
                client.save(df_ic, "ic_contracts", fmt=args.format)
                print(f"\nIC contracts: {len(df_ic)} awards")

        if args.hierarchy:
            h = client.get_spending_hierarchy(
                agency_code=config.USASPENDING_AGENCY_CODES["dod"],
                fiscal_years=args.years,
            )
            client.save_json(h, "dod_spending_hierarchy")
            print("\nSpending hierarchy saved.")
