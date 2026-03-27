"""
acquisition/policy_scraper.py

Downloads NDAA and NDS/NSS policy documents from public government sources.

Sources:
  NDAA — congress.gov (enrolled bill PDFs, FY2000-present)
  NDS  — defense.gov/News/Special-Reports/NDS/
  NSS  — nsc.gov / various official mirrors

These documents are the primary source for policy language to cross-reference
against R-1 budget allocations in the Policy Alignment analysis.

Usage:
    scraper = PolicyScraper()

    # Download all available NDS documents
    scraper.download_nds()

    # Download NDAA for specific fiscal years
    scraper.download_ndaa(fiscal_years=[2022, 2023, 2024, 2025])

    # Download everything
    scraper.run_all()

CLI:
    python acquisition/policy_scraper.py --ndaa --years 2022 2023 2024 2025
    python acquisition/policy_scraper.py --nds
    python acquisition/policy_scraper.py --all
"""

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# ── Output directories ────────────────────────────────────────────────────────

NDAA_DIR = config.RAW_DIR / "policy" / "ndaa"
NDS_DIR  = config.RAW_DIR / "policy" / "nds"
NSS_DIR  = config.RAW_DIR / "policy" / "nss"

for _d in [NDAA_DIR, NDS_DIR, NSS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


# ── Known direct URLs ─────────────────────────────────────────────────────────
# These are stable public URLs to unclassified PDF versions.
# congress.gov enrolled bills are the official source for NDAAs.

NDS_URLS: dict[int, str] = {
    2022: "https://media.defense.gov/2022/Oct/27/2003103845/-1/-1/1/2022-NATIONAL-DEFENSE-STRATEGY-NPR-MDR.PDF",
    2018: "https://dod.defense.gov/Portals/1/Documents/pubs/2018-National-Defense-Strategy-Summary.pdf",
    2014: "https://media.defense.gov/2014/Mar/14/2001384272/-1/-1/1/2014_QUADRENNIAL_DEFENSE_REVIEW.PDF",
}

NSS_URLS: dict[int, str] = {
    # 2025 Trump NSS
    2025: "https://www.whitehouse.gov/wp-content/uploads/2025/12/2025-National-Security-Strategy.pdf",
    # 2022 Biden NSS — removed from whitehouse.gov after transition, use archive
    2022: "https://bidenwhitehouse.archives.gov/wp-content/uploads/2022/10/Biden-Harris-Administrations-National-Security-Strategy-10.2022.pdf",
    2017: "https://trumpwhitehouse.archives.gov/wp-content/uploads/2017/12/NSS-Final-12-18-2017-0905.pdf",
    2015: "https://obamawhitehouse.archives.gov/sites/default/files/docs/2015_national_security_strategy_2.pdf",
    2010: "https://obamawhitehouse.archives.gov/sites/default/files/rss_viewer/national_security_strategy.pdf",
    2006: "https://georgewbush-whitehouse.archives.gov/nsc/nss/2006/nss2006.pdf",
    2002: "https://georgewbush-whitehouse.archives.gov/nsc/nss/2002/nss.pdf",
}

# NDAA bill numbers by fiscal year (public law enrolled bill PDFs)
# Format: (congress_number, bill_number)
# (congress, bill_number, chamber, public_law_seq)
# chamber: "hr" = House bill, "s" = Senate bill
# public_law_seq: the sequence number in the public law citation (P.L. congress-seq)
NDAA_BILL_NUMBERS: dict[int, tuple[int, int, str, int]] = {
    2025: (118, 5009,  "hr", 159),  # H.R.5009, P.L. 118-159
    2024: (118, 2670,  "hr",  31),  # H.R.2670, P.L. 118-31
    2023: (117, 7776,  "hr", 263),  # H.R.7776, P.L. 117-263
    2022: (117, 1605,  "s",   81),  # S.1605,   P.L. 117-81
    2021: (116, 6395,  "hr", 283),  # H.R.6395, P.L. 116-283
    2020: (116, 2500,  "hr",  92),  # H.R.2500, P.L. 116-92
    2019: (115, 2810,  "hr",  91),  # H.R.2810, P.L. 115-91
    2018: (115, 2810,  "hr",  91),  # H.R.2810, P.L. 115-91
    2017: (114, 4909,  "hr", 328),  # H.R.4909, P.L. 114-328
    2016: (114, 1735,  "hr",  92),  # H.R.1735, P.L. 114-92
    2015: (113, 4435,  "hr", 291),  # H.R.4435, P.L. 113-291
    2014: (113, 1960,  "hr",  66),  # H.R.1960, P.L. 113-66
    2013: (112, 4310,  "hr", 239),  # H.R.4310, P.L. 112-239
    2012: (112, 1540,  "hr",  81),  # H.R.1540, P.L. 112-81
    2011: (111, 5136,  "hr", 383),  # H.R.5136, P.L. 111-383
    2010: (111, 2647,  "hr",  84),  # H.R.2647, P.L. 111-84
    2009: (110, 4986,  "hr", 417),  # H.R.4986, P.L. 110-417
    2008: (110, 1585,  "hr", 181),  # H.R.1585, P.L. 110-181
    2007: (109, 5122,  "hr", 364),  # H.R.5122, P.L. 109-364
    2006: (109, 1815,  "hr", 163),  # H.R.1815, P.L. 109-163
    2005: (108, 4200,  "hr", 375),  # H.R.4200, P.L. 108-375
}

CONGRESS_GOV_BASE = "https://www.congress.gov"


# ── HTTP Client ───────────────────────────────────────────────────────────────

def _make_client() -> httpx.Client:
    transport = httpx.HTTPTransport(retries=config.HTTP_RETRY_ATTEMPTS)
    return httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=60,  # NDAAs are large PDFs
        transport=transport,
        follow_redirects=True,
    )


def _download_pdf(
    client: httpx.Client,
    url: str,
    dest_path: Path,
    label: str = "",
    delay: float = 2.0,
) -> bool:
    """Download a single PDF. Returns True on success."""
    if dest_path.exists():
        logger.info(f"  Already exists, skipping: {dest_path.name}")
        return True

    logger.info(f"  Downloading {label or dest_path.name} ...")
    try:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                # Some congress.gov redirects land on HTML — detect and skip
                body = b"".join(resp.iter_bytes(4096))
                if b"<html" in body[:500].lower():
                    logger.warning(f"  Got HTML instead of PDF for {url} — skipping")
                    return False
                dest_path.write_bytes(body)
            else:
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(8192):
                        f.write(chunk)
        logger.info(f"  → Saved to {dest_path}")
        time.sleep(delay)
        return True
    except httpx.HTTPStatusError as e:
        logger.warning(f"  HTTP {e.response.status_code} for {url}")
        return False
    except Exception as e:
        logger.warning(f"  Error downloading {url}: {e}")
        return False


# ── NDAA Downloader ───────────────────────────────────────────────────────────

class NDAAScraper:
    """
    Downloads NDAA enrolled bill PDFs from congress.gov.

    Congress.gov hosts enrolled bills (the final signed version) at:
    https://www.congress.gov/bill/{congress}th-congress/house-bill/{bill}/text
    The PDF link is typically at:
    https://www.congress.gov/{congress}/plaws/publ{seq}/PLAW-{congress}publ{seq}.pdf

    For older bills the structure varies — we try multiple URL patterns.
    """

    def __init__(self, client: httpx.Client):
        self.client = client

    def download(
        self,
        fiscal_years: list[int] | None = None,
    ) -> dict[int, Path | None]:
        """
        Download NDAAs for the specified fiscal years.
        Returns {fiscal_year: local_path} — None if download failed.
        """
        fiscal_years = fiscal_years or list(NDAA_BILL_NUMBERS.keys())
        results: dict[int, Path | None] = {}

        for fy in sorted(fiscal_years):
            if fy not in NDAA_BILL_NUMBERS:
                logger.warning(f"No bill number known for NDAA FY{fy}")
                results[fy] = None
                continue

            congress, bill_num, chamber, plaw_seq = NDAA_BILL_NUMBERS[fy]
            dest = NDAA_DIR / f"ndaa_fy{fy}.pdf"
            chamber_label = "H.R." if chamber == "hr" else "S."

            # Try 1: govinfo.gov enrolled bill PDF
            url = self._build_govinfo_url(congress, bill_num, chamber)
            success = _download_pdf(
                self.client, url, dest,
                label=f"NDAA FY{fy} (Congress {congress}, {chamber_label}{bill_num})"
            )

            if not success:
                # Try 2: govinfo.gov public law PDF (more stable URL)
                url_plaw = self._build_plaw_url(congress, plaw_seq)
                success = _download_pdf(
                    self.client, url_plaw, dest,
                    label=f"NDAA FY{fy} (P.L. {congress}-{plaw_seq})"
                )

            if not success:
                # Try 3: congress.gov enrolled text page link scrape
                url2 = self._build_congress_url(congress, bill_num, chamber)
                pdf_url = self._find_pdf_link_on_page(url2)
                if pdf_url:
                    success = _download_pdf(
                        self.client, pdf_url, dest,
                        label=f"NDAA FY{fy} (congress.gov fallback)"
                    )

            results[fy] = dest if success and dest.exists() else None

        return results

    @staticmethod
    def _build_govinfo_url(congress: int, bill_num: int, chamber: str = "hr") -> str:
        """
        GovInfo.gov enrolled bill PDF URL.
        chamber: 'hr' for House bills, 's' for Senate bills.
        """
        pkg = f"BILLS-{congress}{chamber}{bill_num}enr"
        return f"https://www.govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf"

    @staticmethod
    def _build_plaw_url(congress: int, public_law_num: int) -> str:
        """Public law PDF URL — reliable fallback when enrolled bill URL fails."""
        pkg = f"PLAW-{congress}publ{public_law_num}"
        return f"https://www.govinfo.gov/content/pkg/{pkg}/pdf/{pkg}.pdf"  

    @staticmethod
    def _build_congress_url(congress: int, bill_num: int, chamber: str = "hr") -> str:
        bill_type = "house-bill" if chamber == "hr" else "senate-bill"
        return f"{CONGRESS_GOV_BASE}/bill/{congress}th-congress/{bill_type}/{bill_num}/text"  

    def _find_pdf_link_on_page(self, page_url: str) -> str | None:
        """Parse congress.gov bill text page to find a PDF download link."""
        try:
            resp = self.client.get(page_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if ".pdf" in href.lower() and "enr" in href.lower():
                    return urljoin(CONGRESS_GOV_BASE, href)
        except Exception as e:
            logger.debug(f"Failed to parse {page_url}: {e}")
        return None


# ── NDS Downloader ────────────────────────────────────────────────────────────

class NDSScraper:
    """
    Downloads National Defense Strategy (NDS) and National Security Strategy (NSS)
    documents from defense.gov and whitehouse.gov.
    """

    def __init__(self, client: httpx.Client):
        self.client = client

    def download_nds(self) -> dict[int, Path | None]:
        """Download all known NDS documents."""
        results = {}
        for year, url in NDS_URLS.items():
            dest = NDS_DIR / f"nds_{year}.pdf"
            ok = _download_pdf(self.client, url, dest, label=f"NDS {year}")
            results[year] = dest if ok and dest.exists() else None
        return results

    def download_nss(self) -> dict[int, Path | None]:
        """Download all known NSS documents."""
        results = {}
        for year, url in NSS_URLS.items():
            dest = NSS_DIR / f"nss_{year}.pdf"
            ok = _download_pdf(self.client, url, dest, label=f"NSS {year}")
            results[year] = dest if ok and dest.exists() else None
        return results

    def scrape_defense_gov_nds_page(self) -> list[dict]:
        """
        Attempt to scrape the defense.gov NDS page for additional documents.
        Returns list of {year, url, title} dicts.
        """
        nds_page = "https://www.defense.gov/News/Special-Reports/NDS/"
        found = []
        try:
            resp = self.client.get(nds_page)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if ".pdf" in href.lower() and any(
                    kw in href.lower() for kw in ["nds", "defense-strategy", "strategy"]
                ):
                    full_url = urljoin("https://www.defense.gov", href)
                    year_m = re.search(r"(20\d{2})", href)
                    year = int(year_m.group(1)) if year_m else 0
                    found.append({
                        "year": year,
                        "url":  full_url,
                        "title": a.get_text(strip=True)[:100],
                    })
                    logger.info(f"  Found NDS link: {year} — {full_url}")
        except Exception as e:
            logger.warning(f"Could not scrape defense.gov NDS page: {e}")
        return found


# ══════════════════════════════════════════════════════════════════════════════
# Top-level orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class PolicyScraper:
    """
    Downloads NDAA and NDS/NSS policy documents.

    Example:
        scraper = PolicyScraper()
        scraper.download_ndaa(fiscal_years=[2022, 2023, 2024, 2025])
        scraper.download_nds()
        scraper.run_all()
    """

    def __init__(self):
        self.client = _make_client()
        self.ndaa   = NDAAScraper(self.client)
        self.nds    = NDSScraper(self.client)

    def download_ndaa(
        self, fiscal_years: list[int] | None = None
    ) -> dict[int, Path | None]:
        logger.info("=== Downloading NDAA documents ===")
        results = self.ndaa.download(fiscal_years)
        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"NDAA: {success}/{len(results)} downloaded")
        return results

    def download_nds(self) -> dict[int, Path | None]:
        logger.info("=== Downloading NDS documents ===")
        results = self.nds.download_nds()
        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"NDS: {success}/{len(results)} downloaded")
        return results

    def download_nss(self) -> dict[int, Path | None]:
        logger.info("=== Downloading NSS documents ===")
        results = self.nds.download_nss()
        success = sum(1 for v in results.values() if v is not None)
        logger.info(f"NSS: {success}/{len(results)} downloaded")
        return results

    def run_all(
        self, ndaa_years: list[int] | None = None
    ) -> dict:
        ndaa = self.download_ndaa(ndaa_years)
        nds  = self.download_nds()
        nss  = self.download_nss()
        return {"ndaa": ndaa, "nds": nds, "nss": nss}

    def print_manifest(self) -> None:
        """Print what's been downloaded so far."""
        print(f"\n{'='*60}")
        print("Downloaded policy documents")
        print(f"{'='*60}")
        for label, directory in [("NDAA", NDAA_DIR), ("NDS", NDS_DIR), ("NSS", NSS_DIR)]:
            pdfs = sorted(directory.glob("*.pdf"))
            print(f"\n{label} ({len(pdfs)} files):")
            for p in pdfs:
                size_kb = p.stat().st_size // 1024
                print(f"  {p.name:<35} {size_kb:>6} KB")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Download NDAA and NDS/NSS policy documents"
    )
    parser.add_argument("--ndaa", action="store_true", help="Download NDAA PDFs")
    parser.add_argument("--nds",  action="store_true", help="Download NDS PDFs")
    parser.add_argument("--nss",  action="store_true", help="Download NSS PDFs")
    parser.add_argument("--all",  action="store_true", help="Download everything")
    parser.add_argument(
        "--years", nargs="+", type=int, default=None,
        help="Fiscal years for NDAA (e.g. 2022 2023 2024 2025)"
    )
    parser.add_argument(
        "--manifest", action="store_true",
        help="Print what has been downloaded so far"
    )
    args = parser.parse_args()

    with PolicyScraper() as scraper:
        if args.manifest:
            scraper.print_manifest()
        elif args.all:
            results = scraper.run_all(ndaa_years=args.years)
            scraper.print_manifest()
        else:
            if args.ndaa:
                scraper.download_ndaa(fiscal_years=args.years)
            if args.nds:
                scraper.download_nds()
            if args.nss:
                scraper.download_nss()
            if not any([args.ndaa, args.nds, args.nss]):
                parser.print_help()

        if not args.manifest:
            scraper.print_manifest()