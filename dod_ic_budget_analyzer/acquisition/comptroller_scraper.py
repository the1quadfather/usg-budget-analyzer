"""
acquisition/comptroller_scraper.py

Handles DoD budget justification documents from comptroller.defense.gov.

PRIMARY MODE — Local ingestion (recommended):
    The comptroller site blocks automated access. The practical workflow is:
      1. Visit https://comptroller.defense.gov/Budget-Materials/ in your browser
      2. Navigate to the fiscal year you want
      3. Download the RDT&E justification book PDFs/ZIPs for the components you need
      4. Place them in:  data/raw/comptroller/{FY}/{exhibit_type}/
         e.g.           data/raw/comptroller/2025/rdtee/army_r2.pdf
      5. Run --local to build a manifest for the parser

SECONDARY MODE — Remote scrape (may 403 depending on site posture):
    python acquisition/comptroller_scraper.py --remote --years 2025 --exhibits rdtee

Usage (local scan):
    python acquisition/comptroller_scraper.py --local --years 2024 2025
"""

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── HTTP Client ───────────────────────────────────────────────────────────────

def _make_client() -> httpx.Client:
    """Return a configured httpx client with browser-like headers."""
    transport = httpx.HTTPTransport(retries=config.HTTP_RETRY_ATTEMPTS)
    client = httpx.Client(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        },
        timeout=config.HTTP_TIMEOUT,
        transport=transport,
        follow_redirects=True,
    )
    # Warm up session on the base domain first
    try:
        client.get(config.COMPTROLLER_BASE_URL)
        time.sleep(1.0)
    except Exception:
        pass
    return client


def _backoff_sleep(attempt: int) -> None:
    wait = config.HTTP_RETRY_BACKOFF ** attempt
    logger.debug(f"Backing off {wait:.1f}s (attempt {attempt})")
    time.sleep(wait)


def _safe_filename(url: str) -> str:
    return Path(urlparse(url).path).name or "document.pdf"


# ── Local File Ingestor ───────────────────────────────────────────────────────

class LocalIngestor:
    """
    Scans a local directory tree for budget documents and builds a manifest.

    Expected layout:
        data/raw/comptroller/
            2024/
                rdtee/      <- place R-2 PDFs here
                    army_r2.pdf
                    darpa_r2.pdf
                procurement/
                    army_p40.pdf
            2025/
                rdtee/
                    ...

    A flat folder of PDFs also works — FY and exhibit type will be inferred
    from the path and filename where possible, otherwise marked "unknown".
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".zip"}

    EXHIBIT_PATTERNS = {
        "rdtee":       re.compile(r"r-?2|rdtee|rdte", re.IGNORECASE),
        "procurement": re.compile(r"p-?40|procurement", re.IGNORECASE),
        "om":          re.compile(r"o-?1|o&m|oper", re.IGNORECASE),
    }

    def __init__(self, base_dir: Path = config.COMPTROLLER_DIR):
        self.base_dir = base_dir

    def scan(
        self,
        fiscal_years: list[int] | None = None,
        exhibit_types: list[str] | None = None,
    ) -> list[dict]:
        """
        Walk base_dir and return a manifest of all found documents.

        Returns list of dicts:
            { local_path, filename, fiscal_year, exhibit_type, component }
        """
        if not self.base_dir.exists():
            logger.warning(
                f"Directory not found: {self.base_dir}\n"
                f"  Create it and place downloaded PDFs inside, or run --remote."
            )
            return []

        manifest = []
        for path in sorted(self.base_dir.rglob("*")):
            if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue

            fy = self._infer_fy(path)
            et = self._infer_exhibit_type(path)
            component = self._infer_component(path.name)

            if fiscal_years and fy not in fiscal_years:
                continue
            if exhibit_types and et not in exhibit_types:
                continue

            manifest.append({
                "local_path": path,
                "filename": path.name,
                "fiscal_year": fy,
                "exhibit_type": et,
                "component": component,
            })

        logger.info(f"Local scan of {self.base_dir}: {len(manifest)} document(s) found")
        for item in manifest:
            logger.info(
                f"  FY{item['fiscal_year']} | {item['exhibit_type']:<12} | "
                f"{item['component']:<10} | {item['filename']}"
            )
        return manifest

    def _infer_fy(self, path: Path) -> int | str:
        for part in path.parts:
            if part.isdigit() and 2000 <= int(part) <= 2040:
                return int(part)
        m = re.search(r"(?:fy|pb)(\d{4})", str(path), re.IGNORECASE)
        if m:
            return int(m.group(1))
        return "unknown"

    def _infer_exhibit_type(self, path: Path) -> str:
        path_str = str(path).lower()
        for part in Path(path_str).parts:
            for et, pattern in self.EXHIBIT_PATTERNS.items():
                if pattern.search(part):
                    return et
        for et, pattern in self.EXHIBIT_PATTERNS.items():
            if pattern.search(path.name):
                return et
        return "unknown"

    def _infer_component(self, filename: str) -> str:
        fn_lower = filename.lower()
        for key, label in config.DOD_COMPONENTS.items():
            if key in fn_lower or label.lower() in fn_lower:
                return key
        return "unknown"


# ── Remote Link Discovery ─────────────────────────────────────────────────────

class ComptrollerLinkDiscoverer:
    """Parses the comptroller.defense.gov index page for PDF links."""

    EXHIBIT_PATTERNS = {
        "rdtee":       re.compile(r"[-_](r2|rdtee|rdte)[-_.]", re.IGNORECASE),
        "procurement": re.compile(r"[-_](p40|p-40|procurement)[-_.]", re.IGNORECASE),
        "om":          re.compile(r"[-_](o1|o-1|om|o&m)[-_.]", re.IGNORECASE),
    }

    def __init__(self, client: httpx.Client):
        self.client = client

    def get_links_for_year(
        self,
        fiscal_year: int,
        exhibit_types: list[str] | None = None,
    ) -> dict[str, list[dict]]:
        exhibit_types = exhibit_types or list(config.DOD_EXHIBIT_TYPES.keys())
        page_url = config.COMPTROLLER_BUDGET_URL.format(year=fiscal_year)

        logger.info(f"Fetching index for FY{fiscal_year}: {page_url}")
        try:
            resp = self.client.get(
                page_url,
                headers={"Referer": config.COMPTROLLER_BASE_URL},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code} — {page_url}")
            return {}
        except httpx.RequestError as e:
            logger.error(f"Request failed — {page_url}: {e}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        all_links = [
            {
                "url": urljoin(page_url, tag["href"].strip()),
                "text": tag.get_text(strip=True),
            }
            for tag in soup.find_all("a", href=True)
            if re.search(r"\.(pdf|zip)$", tag["href"], re.IGNORECASE)
        ]

        results: dict[str, list[dict]] = {et: [] for et in exhibit_types}
        for link in all_links:
            for et in exhibit_types:
                pattern = self.EXHIBIT_PATTERNS.get(et)
                if pattern and pattern.search(link["url"]):
                    results[et].append({
                        "url": link["url"],
                        "filename": _safe_filename(link["url"]),
                        "fiscal_year": fiscal_year,
                        "exhibit_type": et,
                        "component": self._infer_component(link["url"]),
                        "page_source": page_url,
                    })

        for et, links in results.items():
            logger.info(f"  FY{fiscal_year} {et}: {len(links)} link(s) found")
        return results

    def _infer_component(self, url: str) -> str:
        url_lower = url.lower()
        for key, label in config.DOD_COMPONENTS.items():
            if key in url_lower or label.lower() in url_lower:
                return key
        return "unknown"


# ── Remote Downloader ─────────────────────────────────────────────────────────

class ComptrollerDownloader:
    """Downloads PDFs from the comptroller site into the local directory tree."""

    def __init__(self, client: httpx.Client, base_dir: Path = config.COMPTROLLER_DIR):
        self.client = client
        self.base_dir = base_dir

    def download(self, link_info: dict) -> Path | None:
        dest_dir = (
            self.base_dir / str(link_info["fiscal_year"]) / link_info["exhibit_type"]
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / link_info["filename"]

        if dest_path.exists():
            logger.debug(f"Skipping (exists): {dest_path}")
            return dest_path

        logger.info(f"Downloading {link_info['filename']} ...")
        for attempt in range(config.HTTP_RETRY_ATTEMPTS):
            try:
                with self.client.stream("GET", link_info["url"]) as resp:
                    resp.raise_for_status()
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)
                logger.info(f"  → {dest_path}")
                return dest_path
            except httpx.HTTPStatusError as e:
                logger.warning(f"HTTP {e.response.status_code} attempt {attempt + 1}")
                if e.response.status_code in (403, 404):
                    break
                _backoff_sleep(attempt)
            except httpx.RequestError as e:
                logger.warning(f"Request error attempt {attempt + 1}: {e}")
                _backoff_sleep(attempt)

        logger.error(f"Failed to download: {link_info['url']}")
        return None

    def download_batch(
        self, links: list[dict], delay: float = 1.0
    ) -> tuple[list[Path], list[dict]]:
        succeeded, failed = [], []
        for i, link in enumerate(links, 1):
            logger.info(f"[{i}/{len(links)}] {link['filename']}")
            result = self.download(link)
            if result:
                succeeded.append(result)
            else:
                failed.append(link)
            if i < len(links):
                time.sleep(delay)
        logger.info(f"Done: {len(succeeded)} succeeded, {len(failed)} failed")
        return succeeded, failed


# ── Orchestrator ──────────────────────────────────────────────────────────────

class ComptrollerScraper:
    """
    Top-level orchestrator with two modes:

    LOCAL (recommended — comptroller site blocks bots):
        scraper = ComptrollerScraper()
        manifest = scraper.scan_local(fiscal_years=[2024, 2025])

    REMOTE (attempt automated download — may 403):
        scraper = ComptrollerScraper()
        results = scraper.run_remote(fiscal_years=[2025], exhibit_types=["rdtee"])
    """

    def __init__(self):
        self.ingestor = LocalIngestor()

    def scan_local(
        self,
        fiscal_years: list[int] | None = None,
        exhibit_types: list[str] | None = None,
    ) -> list[dict]:
        """Scan locally downloaded files and return a manifest."""
        return self.ingestor.scan(
            fiscal_years=fiscal_years,
            exhibit_types=exhibit_types,
        )

    def run_remote(
        self,
        fiscal_years: list[int] | None = None,
        exhibit_types: list[str] | None = None,
        components: list[str] | None = None,
        download: bool = True,
        delay: float = 1.5,
    ) -> dict:
        """Attempt to scrape and download from comptroller.defense.gov."""
        fiscal_years = fiscal_years or config.FISCAL_YEARS
        exhibit_types = exhibit_types or list(config.DOD_EXHIBIT_TYPES.keys())

        client = _make_client()
        discoverer = ComptrollerLinkDiscoverer(client)
        downloader = ComptrollerDownloader(client)

        all_links: list[dict] = []
        for fy in fiscal_years:
            fy_links = discoverer.get_links_for_year(fy, exhibit_types)
            for et_links in fy_links.values():
                all_links.extend(et_links)
            time.sleep(delay)

        if components:
            all_links = [l for l in all_links if l.get("component") in components]

        logger.info(f"Remote: {len(all_links)} documents discovered")

        if not download:
            client.close()
            return {"manifest": all_links, "succeeded": [], "failed": []}

        succeeded, failed = downloader.download_batch(all_links, delay=delay)
        client.close()
        return {"manifest": all_links, "succeeded": succeeded, "failed": failed}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Manage DoD budget justification documents."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--local", action="store_true",
        help="Scan locally downloaded files (recommended)"
    )
    mode.add_argument(
        "--remote", action="store_true",
        help="Attempt to scrape comptroller.defense.gov"
    )
    parser.add_argument("--years", nargs="+", type=int, default=config.FISCAL_YEARS)
    parser.add_argument(
        "--exhibits", nargs="+",
        choices=list(config.DOD_EXHIBIT_TYPES.keys()),
        default=["rdtee"],
    )
    parser.add_argument(
        "--components", nargs="+",
        choices=list(config.DOD_COMPONENTS.keys()),
        default=None,
    )
    parser.add_argument(
        "--discover-only", action="store_true",
        help="(Remote mode) discover links without downloading"
    )
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    scraper = ComptrollerScraper()

    if args.local:
        manifest = scraper.scan_local(
            fiscal_years=args.years,
            exhibit_types=args.exhibits,
        )
        print(f"\n{'='*60}")
        print(f"Documents found locally: {len(manifest)}")
        if not manifest:
            print("\nNo documents found.")
            print("Download PDFs manually from:")
            print("  https://comptroller.defense.gov/Budget-Materials/")
            print(f"Place them in: {config.COMPTROLLER_DIR}/{{FY}}/{{exhibit_type}}/")
            print("Example:       data/raw/comptroller/2025/rdtee/army_r2.pdf")
        else:
            manifest_path = config.COMPTROLLER_DIR / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(manifest_path, "w") as f:
                json.dump(
                    [{**item, "local_path": str(item["local_path"])} for item in manifest],
                    f, indent=2,
                )
            print(f"Manifest saved → {manifest_path}")

    else:  # remote
        results = scraper.run_remote(
            fiscal_years=args.years,
            exhibit_types=args.exhibits,
            components=args.components,
            download=not args.discover_only,
            delay=args.delay,
        )
        print(f"\n{'='*60}")
        print(f"Discovered: {len(results['manifest'])}")
        print(f"Downloaded: {len(results['succeeded'])}")
        print(f"Failed:     {len(results['failed'])}")
