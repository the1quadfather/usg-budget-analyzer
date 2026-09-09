"""Discover and download official DD 1416 quarterly XLSX reports."""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

import config
from acquisition.comptroller_scraper import _make_client


logger = logging.getLogger(__name__)

_SOURCE_MANIFEST = "source_manifest.json"

_FY_PAIR_RE = re.compile(r"FY[_ -]?(\d{4})[_ -](\d{4})", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})_(\d{1,2})_(\d{4})(?=\.xlsx$)", re.IGNORECASE)
_COMPONENT_RE = re.compile(
    r"(?:^|/)(Defense[-_]Wide|Space_Force|Air_Force|Army|Navy)_(?:RDTE_)?FY_",
    re.IGNORECASE,
)


def metadata_from_url(url: str) -> dict:
    """Extract stable report identity from an official href."""
    decoded = unquote(url)
    filename = Path(urlparse(decoded).path).name
    fy_match = _FY_PAIR_RE.search(filename)
    date_match = _DATE_RE.search(filename)
    component_match = _COMPONENT_RE.search(decoded)
    if not (fy_match and date_match and component_match):
        raise ValueError(f"Unrecognized DD 1416 filename: {filename}")
    component = (
        component_match.group(1).replace("_", " ").replace("-", " ").title()
    )
    if component == "Defense Wide":
        component = "Defense-Wide"
    return {
        "url": url,
        "filename": filename,
        "agency": component,
        "appropriation": "RDTE",
        "fy_start": int(fy_match.group(1)),
        "fy_end": int(fy_match.group(2)),
        "report_date": (
            f"{int(date_match.group(3)):04d}-"
            f"{int(date_match.group(1)):02d}-"
            f"{int(date_match.group(2)):02d}"
        ),
    }


def discover_links(client: httpx.Client, fiscal_year: int) -> list[dict]:
    """Scrape official hrefs; URL construction is intentionally avoided."""
    page_url = config.DD1416_INDEX_URL.format(year=fiscal_year)
    response = client.get(page_url, headers={"Referer": config.COMPTROLLER_BASE_URL})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    links: list[dict] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not re.search(r"\.xlsx(?:$|\?)", href, re.IGNORECASE):
            continue
        if "DD_1416_RDTE" not in href.upper():
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        seen.add(url)
        try:
            item = metadata_from_url(url)
        except ValueError:
            logger.warning("Skipping unrecognized DD 1416 link: %s", url)
            continue
        item["index_url"] = page_url
        links.append(item)
    return sorted(
        links,
        key=lambda item: (
            item["report_date"], item["fy_start"], item["agency"],
        ),
    )


def download_reports(
    years: list[int],
    *,
    destination: Path = config.DD1416_DIR,
    pause_seconds: float = 3.0,
) -> list[dict]:
    """Download discovered reports idempotently and return a manifest."""
    destination.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    manifest_path = destination / _SOURCE_MANIFEST
    try:
        persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        persisted = {}
    client = _make_client()
    try:
        for year in years:
            links = discover_links(client, year)
            logger.info("FY%s: discovered %s RDT&E files", year, len(links))
            for item in links:
                year_dir = destination / str(year)
                year_dir.mkdir(parents=True, exist_ok=True)
                path = year_dir / item["filename"]
                if not path.exists() or path.stat().st_size == 0:
                    try:
                        response = client.get(
                            item["url"],
                            headers={"Referer": item["index_url"]},
                        )
                        response.raise_for_status()
                    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                        # Some official index pages contain dead links (for
                        # example a literal 6_31 folder in FY2021). Preserve
                        # the gap in logs and continue; never synthesize a URL.
                        logger.warning("Unavailable official link %s: %s", item["url"], exc)
                        continue
                    path.write_bytes(response.content)
                    time.sleep(pause_seconds)
                record = {**item, "local_path": path}
                manifest.append(record)
                persisted[f"{year}/{item['filename']}"] = {
                    key: value for key, value in item.items()
                    if key != "local_path"
                }
    finally:
        client.close()
    manifest_path.write_text(
        json.dumps(persisted, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def local_manifest(
    destination: Path = config.DD1416_DIR,
    years: list[int] | None = None,
) -> list[dict]:
    """Describe already-downloaded reports without network access."""
    allowed = set(years or [])
    manifest = []
    try:
        persisted = json.loads(
            (destination / _SOURCE_MANIFEST).read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError):
        persisted = {}
    for path in sorted(destination.glob("*/*.xlsx")):
        if allowed and int(path.parent.name) not in allowed:
            continue
        fallback = metadata_from_url(path.name)
        item = persisted.get(f"{path.parent.name}/{path.name}", fallback)
        manifest.append({**item, "local_path": path})
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--pause", type=float, default=3.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rows = download_reports(args.years, pause_seconds=args.pause)
    print(f"Downloaded/discovered {len(rows)} DD 1416 RDT&E workbooks.")


if __name__ == "__main__":
    main()
