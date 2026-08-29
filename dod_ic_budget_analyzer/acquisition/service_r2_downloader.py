"""
acquisition/service_r2_downloader.py

Downloads RDT&E justification books (R-2 exhibits) published as PDF by the
military departments, and ingests their narratives into the same tables the
Defense-Wide XML pipeline writes.

Why this exists
---------------
`pe_narratives` covered 285 of 2,055 PEs, 282 of them Defense-Wide -- Army,
Navy, Air Force and Space Force had none, because they publish PDF where
Defense-Wide publishes DTIC-schema XML. The PDFs carry a clean text layer with
the PE number printed verbatim in every exhibit header, so the join is exact
rather than fuzzy. See parsing/r2_pdf_parser.py.

Per-host access notes, all measured 2026-08-28
----------------------------------------------
* **Army** (asafm.army.mil) returns Akamai 403 for a default client AND for a
  bare browser User-Agent. It needs the FULL Chrome header set -- the
  `sec-ch-ua*` and `Sec-Fetch-*` headers included. This is almost certainly why
  the services were previously written off as unreachable.
* **Navy** (secnav.navy.mil) works with browser headers but serves slowly
  (~0.4 MB/s; a 39 MB book took 94 s), and HEAD requests hang without
  returning, so existence checks use a ranged GET rather than HEAD.
* **Air Force / Space Force** (saffm.hq.af.mil) is NOT reachable: its edge
  aborts the TLS handshake with alert 80 against every client, protocol and
  cipher tried, so no HTTP status is ever returned. The identical PDFs are
  retrievable from the Wayback Machine, which is a third-party dependency and
  is deliberately left for a second pass rather than quietly relied on here.

Text extraction uses poppler's `pdftotext -layout`, which is already installed.
pdfplumber is listed in requirements.txt but is often missing from the venv.

Usage::

    python acquisition/service_r2_downloader.py --service army --years 2027 --list
    python acquisition/service_r2_downloader.py --service army --years 2027
    python acquisition/service_r2_downloader.py --service army navy --years 2027 --ingest
"""

import argparse
import logging
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: E402
from parsing.r2_pdf_parser import parse_book  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_DEST = config.RAW_DIR / "service_r2"

# The full Chrome header set. A User-Agent alone is NOT enough for Army --
# Akamai still answers 403 without the client hints and fetch metadata.
BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="124", "Not:A-Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

ARMY_INDEX = "https://www.asafm.army.mil/Budget-Materials/"

# Air Force and Space Force publish to a host whose edge aborts the TLS
# handshake for every client, so the only route to their books is the Wayback
# Machine. `id_` returns the archived bytes unmodified rather than a rewritten
# page. Snapshot coverage runs FY2018-FY2024; newer books are not archived.
CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{url}"
AF_DOMAIN = "saffm.hq.af.mil"
AF_ARCHIVE_FIRST_FY, AF_ARCHIVE_LAST_FY = 2018, 2024
_cdx_cache: Dict[str, list] = {}
NAVY_BOOKS = [
    "RDTEN_BA1-3_Book.pdf", "RDTEN_BA4_Book.pdf", "RDTEN_BA5_Book.pdf",
    "RDTEN_BA6_Book.pdf", "RDTEN_BA7-8_Book.pdf",
]
NAVY_URL = "https://www.secnav.navy.mil/fmc/fmb/Documents/{yy}pres/{book}"

# Navy books are tens of MB at ~0.4 MB/s.
TIMEOUT = httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=30.0)

# The Wayback Machine throttles rapid sequential fetches with 503s -- a
# single manual fetch succeeds while a backfill loop gets refused on every
# request. Retry with backoff and space the requests out.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = int(os.environ.get("R2_RETRY_ATTEMPTS", "5"))
# Measured: the FIRST archive request of a run succeeds and everything after it
# gets 503 until a long cool-off. Backoff capped at ~80s never recovers. These
# are env-tunable so a patient overnight pass can use minutes, not seconds,
# without editing code.
WAYBACK_DELAY = float(os.environ.get("R2_WAYBACK_DELAY", "5"))

# secnav.navy.mil serves at ~0.4 MB/s and starts timing out entirely once a
# backfill has been pulling from it for a while. These are public government
# servers, so pace every host between files, and back off on retries there too
# rather than immediately re-issuing a request that just timed out.
HOST_DELAY = 2.0
RETRY_DELAY = 20.0


def _client() -> httpx.Client:
    return httpx.Client(headers=BROWSER_HEADERS, timeout=TIMEOUT,
                        follow_redirects=True)


def discover_army(client: httpx.Client, fiscal_year: int) -> List[Tuple[str, str]]:
    """
    Scrape the Budget-Materials index for that year's RDT&E volumes.

    The index lists every fiscal year at once, so the year is matched inside
    the path (.../BudgetMaterial/2027/...) rather than by requesting a
    per-year page.
    """
    response = client.get(ARMY_INDEX)
    response.raise_for_status()
    found: List[Tuple[str, str]] = []
    seen = set()
    for href in re.findall(r'href="([^"]+\.pdf)"', response.text, re.IGNORECASE):
        if f"/{fiscal_year}/" not in href:
            continue
        if not re.search(r"/rdte/|rdte", href, re.IGNORECASE):
            continue
        url = urljoin(ARMY_INDEX, href)
        name = unquote(Path(href).name)
        if name in seen:
            continue
        seen.add(name)
        found.append((url, f"army_fy{fiscal_year}_{name.replace(' ', '_')}"))
    return sorted(found, key=lambda p: p[1])


def discover_navy(client: httpx.Client, fiscal_year: int) -> List[Tuple[str, str]]:
    """
    Navy publishes at a predictable path, so existence is probed rather than
    scraped. A ranged GET is used because HEAD hangs on this host.
    """
    yy = f"{fiscal_year % 100:02d}"
    found: List[Tuple[str, str]] = []
    for book in NAVY_BOOKS:
        url = NAVY_URL.format(yy=yy, book=book)
        try:
            probe = client.get(url, headers={"Range": "bytes=0-63"})
        except Exception as exc:
            logger.debug(f"navy probe failed {url}: {exc}")
            continue
        if probe.status_code in (200, 206) and probe.content[:4] == b"%PDF":
            found.append((url, f"navy_fy{fiscal_year}_{book}"))
        else:
            logger.debug(f"navy {book} FY{fiscal_year}: {probe.status_code}")
    return found


def _af_archive_index(client: httpx.Client) -> Dict[str, tuple]:
    """
    Every archived Air Force / Space Force RDT&E book, newest snapshot per file.

    The `?ver=` query strings the CMS appends make the same document appear
    many times, so entries are deduplicated on the path before the query
    string and the most recent capture of each is kept.
    """
    if "af" in _cdx_cache:
        return _cdx_cache["af"]
    params = {
        "url": AF_DOMAIN, "matchType": "domain", "output": "json",
        "collapse": "urlkey", "filter": ["statuscode:200",
                                         "mimetype:application/pdf"],
        "limit": "40000",
    }
    rows = client.get(CDX_URL, params=params).json()
    header, data = rows[0], rows[1:]
    ts_i, url_i = header.index("timestamp"), header.index("original")

    best: Dict[str, tuple] = {}
    for row in data:
        original = row[url_i]
        if not re.search(r"rdt", original, re.IGNORECASE):
            continue
        path = original.split("?")[0]
        if path not in best or row[ts_i] > best[path][0]:
            best[path] = (row[ts_i], original)
    _cdx_cache["af"] = best
    logger.info(f"Wayback: {len(best)} archived Air Force/Space Force RDT&E books")
    return best


def discover_air_force(client: httpx.Client,
                       fiscal_year: int) -> List[Tuple[str, str]]:
    """
    Archived Air Force and Space Force books for one fiscal year.

    Both services share this host and this listing; which one a book belongs to
    is read from its own exhibit banner at parse time rather than guessed from
    the filename.
    """
    if not AF_ARCHIVE_FIRST_FY <= fiscal_year <= AF_ARCHIVE_LAST_FY:
        logger.info(f"air force FY{fiscal_year}: outside archived coverage "
                    f"(FY{AF_ARCHIVE_FIRST_FY}-FY{AF_ARCHIVE_LAST_FY})")
        return []

    yy = f"{fiscal_year % 100:02d}"
    found: List[Tuple[str, str]] = []
    for path, (timestamp, original) in _af_archive_index(client).items():
        if not re.search(rf"/FY[-_ ]?{yy}\b", path, re.IGNORECASE):
            continue
        name = unquote(Path(path).name).replace(" ", "_").replace("%20", "_")
        found.append((WAYBACK_RAW.format(timestamp=timestamp, url=original),
                      f"af_fy{fiscal_year}_{name}"))
    return sorted(found, key=lambda p: p[1])


DISCOVERERS = {"army": discover_army, "navy": discover_navy,
               "airforce": discover_air_force}


def download(client: httpx.Client, url: str, dest: Path,
             refresh: bool = False) -> Optional[Path]:
    """
    Fetch one book, verifying it is a whole PDF.

    A truncated download still looks like a PDF at the front, so both the
    leading magic bytes and a trailing %%EOF are checked before the file is
    accepted -- otherwise a silent partial fetch becomes silent missing rows.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not refresh and dest.stat().st_size > 0:
        logger.info(f"{dest.name}: cached")
        return dest

    logger.info(f"{dest.name}: downloading")
    is_archive = "web.archive.org" in url
    body = None
    base_delay = WAYBACK_DELAY if is_archive else RETRY_DELAY
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        if attempt > 1:
            # Exponential backoff with jitter, for every host. The archive
            # returns 503 for a while after deciding a client is going too
            # fast; the Navy host simply stops responding.
            wait = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 3)
            logger.info(f"{dest.name}: retry {attempt}/{RETRY_ATTEMPTS} "
                        f"in {wait:.0f}s")
            time.sleep(wait)
        try:
            response = client.get(url)
            if response.status_code in RETRY_STATUS:
                logger.warning(f"{dest.name}: HTTP {response.status_code}")
                continue
            response.raise_for_status()
            body = response.content
            break
        except httpx.HTTPStatusError as exc:
            logger.error(f"{dest.name}: FAILED {exc}")
            return None
        except Exception as exc:
            logger.warning(f"{dest.name}: {type(exc).__name__} {exc}")
            continue
    if body is None:
        logger.error(f"{dest.name}: FAILED after {RETRY_ATTEMPTS} attempts")
        return None
    time.sleep(WAYBACK_DELAY if is_archive else HOST_DELAY)
    if body[:4] != b"%PDF":
        logger.error(f"{dest.name}: not a PDF (got {body[:16]!r})")
        return None
    if b"%%EOF" not in body[-2048:]:
        logger.error(f"{dest.name}: truncated -- no %%EOF in the tail")
        return None

    dest.write_bytes(body)
    logger.info(f"{dest.name}: {len(body) / 1e6:.1f} MB")
    return dest


def to_text(pdf: Path, refresh: bool = False) -> Optional[str]:
    """Extract the text layer with poppler, caching the result beside the PDF."""
    cached = pdf.with_suffix(".txt")
    if cached.exists() and not refresh:
        return cached.read_text(encoding="utf-8", errors="replace")
    try:
        subprocess.run(["pdftotext", "-layout", str(pdf), str(cached)],
                       check=True, capture_output=True, timeout=900)
    except FileNotFoundError:
        logger.error("pdftotext not found -- install poppler-utils")
        return None
    except subprocess.CalledProcessError as exc:
        logger.error(f"{pdf.name}: pdftotext failed: {exc.stderr[:200]}")
        return None
    return cached.read_text(encoding="utf-8", errors="replace")


def harvest(services: List[str], years: List[int], dest: Path,
            refresh: bool = False, list_only: bool = False) -> dict:
    """Download and parse every requested service-year, returning parsed rows."""
    narratives: List[dict] = []
    accomplishments: List[dict] = []
    report: List[dict] = []
    harvested: set = set()
    empty: List[str] = []

    with _client() as client:
        for service in services:
            discover = DISCOVERERS.get(service)
            if discover is None:
                logger.error(f"unknown service {service!r} "
                             f"(known: {', '.join(DISCOVERERS)})")
                continue
            for year in years:
                try:
                    books = discover(client, year)
                except Exception as exc:
                    logger.error(f"{service} FY{year}: discovery failed: {exc}")
                    continue
                logger.info(f"{service} FY{year}: {len(books)} book(s)")
                if list_only:
                    for url, name in books:
                        print(f"  {name}  <- {url}", flush=True)
                    continue

                for url, name in books:
                    if name in harvested:
                        continue
                    harvested.add(name)
                    pdf = download(client, url, dest / name, refresh=refresh)
                    if pdf is None:
                        continue
                    text = to_text(pdf, refresh=refresh)
                    if not text:
                        continue
                    parsed = parse_book(text, name)
                    diag = parsed["diagnostics"]
                    narratives.extend(parsed["narratives"])
                    accomplishments.extend(parsed["accomplishments"])
                    report.append({"file": name, **diag,
                                   "narratives": len(parsed["narratives"]),
                                   "accomplishments": len(parsed["accomplishments"])})
                    unparsed = diag["pes_printed_but_unparsed"]
                    flag = f"  !! {len(unparsed)} PE(s) unparsed" if unparsed else ""
                    # A book that yields nothing is the failure mode that
                    # matters: the FY2018 books all parsed to zero because
                    # their banner says 'FY 2018' where newer ones say
                    # 'PB 2027'. Never let that scroll past as a quiet 0.
                    if not diag["exhibits"]:
                        flag = "  !! ZERO EXHIBITS - format not recognised"
                        empty.append(name)
                    # flush: stdout is block-buffered when piped, and a
                    # multi-minute harvest that prints nothing looks hung.
                    print(f"  {name}: {diag['exhibits']} exhibits, "
                          f"{diag['distinct_pes']} PEs, "
                          f"{len(parsed['narratives'])} narratives, "
                          f"{len(parsed['accomplishments'])} accomplishments{flag}",
                          flush=True)

    if empty:
        logger.error(f"{len(empty)} book(s) parsed to ZERO exhibits: {empty[:5]}")
    return {"narratives": narratives, "accomplishments": accomplishments,
            "report": report, "empty": empty}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", nargs="+",
                        default=["army", "navy", "airforce"],
                        choices=sorted(DISCOVERERS),
                        help="which departments to harvest")
    parser.add_argument("--years", nargs="+", type=int, required=True,
                        help="fiscal years, e.g. --years 2026 2027")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                        help=f"where PDFs are cached (default {DEFAULT_DEST})")
    parser.add_argument("--list", action="store_true", dest="list_only",
                        help="show what would be downloaded and stop")
    parser.add_argument("--refresh", action="store_true",
                        help="re-download and re-extract even if cached")
    parser.add_argument("--ingest", action="store_true",
                        help="write parsed rows into the database")
    parser.add_argument("--db", default=None, help="override the database URI")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    result = harvest(args.service, args.years, args.dest,
                     refresh=args.refresh, list_only=args.list_only)
    if args.list_only:
        return 0

    print(f"\nparsed {len(result['narratives'])} narratives, "
          f"{len(result['accomplishments'])} accomplishments")
    if result["empty"]:
        print(f"FAIL: {len(result['empty'])} book(s) yielded no exhibits at all "
              f"-- {result['empty'][:5]}")
    if not args.ingest:
        print("(dry run - pass --ingest to write)")
        return 0

    import pandas as pd
    from storage.db import get_engine, get_session_factory, init_db
    from storage.ingest_r2 import R2Ingestor

    db_uri = args.db or (
        "sqlite:///" + (Path(__file__).parent.parent / "data" / "processed"
                        / "usg_budgets.db").as_posix()
    )
    engine = get_engine(db_uri)
    init_db(engine)
    with get_session_factory(engine)() as session:
        counts = R2Ingestor(session).ingest_frames(
            pd.DataFrame(result["narratives"]),
            pd.DataFrame(result["accomplishments"]),
        )
    print(f"ingested: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
