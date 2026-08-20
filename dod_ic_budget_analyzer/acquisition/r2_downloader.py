"""
acquisition/r2_downloader.py

Discovers and downloads the machine-readable R-2 justification book XML
volumes (DTIC jbook schema) that the comptroller publishes for Defense-Wide
components alongside the PDF books.

Verified: FY2026 and FY2027 pages each list ~19 RDT&E XML volumes under
budget_justification/pdfs/03_RDT_and_E/. Some listed XMLs 404 (e.g. the
FY2027 MDA volume) - those are logged and skipped.

Note: the military services (Army, Navy, Air Force) host their justification
books on their own sites as PDF only; this downloader covers the
comptroller-hosted Defense-Wide volumes.

Usage:
    python acquisition/r2_downloader.py --years 2025 2026 2027
    python acquisition/r2_downloader.py --years 2026 --ingest
"""

import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

from acquisition.comptroller_scraper import _make_client

logger = logging.getLogger(__name__)

# Page URL variants observed across budget cycles
JUSTIFICATION_PAGE_PATTERNS = [
    "{base}/BudgetMaterials/FY{year}budgetjustification.aspx",
    "{base}/Budget-Materials/FY{year}BudgetJustification/",
]

RDTE_XML_RE = re.compile(r"03_RDT_and_E/[^/]+\.xml$", re.IGNORECASE)


class R2Downloader:
    def __init__(self, base_dir: Path = config.COMPTROLLER_DIR):
        self.base_dir = base_dir
        self.client = _make_client()

    def close(self):
        self.client.close()

    def discover(self, fiscal_year: int) -> list[str]:
        """Scrape the FY's justification page for RDT&E jbook XML URLs."""
        for pattern in JUSTIFICATION_PAGE_PATTERNS:
            url = pattern.format(base=config.COMPTROLLER_BASE_URL, year=fiscal_year)
            try:
                resp = self.client.get(url)
                if resp.status_code != 200:
                    continue
            except Exception as e:
                logger.warning(f"Fetch failed {url}: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            links = sorted({
                urljoin(url, a["href"].strip())
                for a in soup.find_all("a", href=True)
                if RDTE_XML_RE.search(a["href"])
            })
            if links:
                logger.info(f"FY{fiscal_year}: {len(links)} jbook XML link(s) on {url}")
                return links
        logger.warning(f"FY{fiscal_year}: no justification page with XML links found")
        return []

    def download(self, fiscal_year: int, delay: float = 0.8) -> list[Path]:
        dest = self.base_dir / str(fiscal_year) / "rdtee" / "jbooks"
        dest.mkdir(parents=True, exist_ok=True)

        downloaded = []
        for url in self.discover(fiscal_year):
            out = dest / url.rsplit("/", 1)[-1]
            if out.exists():
                downloaded.append(out)
                continue
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
                if len(resp.content) < 1000:
                    raise ValueError("suspiciously small response")
                out.write_bytes(resp.content)
                logger.info(f"  -> {out.name} ({len(resp.content):,} bytes)")
                downloaded.append(out)
            except Exception as e:
                logger.warning(f"  skip {out.name}: {e}")
            time.sleep(delay)

        logger.info(f"FY{fiscal_year}: {len(downloaded)} jbook XML file(s) present")
        return downloaded


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level="INFO",
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Download R-2 jbook XML volumes.")
    ap.add_argument("--years", nargs="+", type=int, required=True)
    ap.add_argument("--ingest", action="store_true",
                    help="Parse and ingest into SQLite after downloading")
    args = ap.parse_args()

    dl = R2Downloader()
    all_dirs = []
    try:
        for fy in args.years:
            paths = dl.download(fy)
            if paths:
                all_dirs.append(paths[0].parent)
    finally:
        dl.close()

    if args.ingest and all_dirs:
        from parsing.r2_parser import R2Parser
        from storage.db import get_engine, get_session_factory, init_db
        from storage.ingest_r2 import R2Ingestor

        db_uri = (f"sqlite:///"
                  f"{(Path(__file__).parent.parent / 'data' / 'processed' / 'usg_budgets.db').as_posix()}")
        engine = get_engine(db_uri)
        init_db(engine)
        parser = R2Parser()
        with get_session_factory(engine)() as session:
            ingestor = R2Ingestor(session)
            for d in all_dirs:
                frames = parser.parse_directory(d)
                ingestor.ingest_frames(frames["narratives"], frames["accomplishments"])
