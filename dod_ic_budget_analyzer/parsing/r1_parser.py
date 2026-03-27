"""
parsing/r1_parser.py

Parses DoD R-1 (RDT&E Programs) PDFs into a normalized DataFrame.

Ground-truth structure (verified against FY2025 R-1):
  - Native text PDF (FY2002+), pdftotext -layout for column-accurate extraction
  - Scanned image PDF (FY1998-2001) - OCR path
  - Dollars in THOUSANDS
  - Three amount columns: FY N-2 Actuals | FY N-1 PB Request | FY N Request
  - Budget Activity from "Act" column (two-digit code 01-08)
  - Appropriation from page header: "Appropriation: XXXX Research, Development..."
  - Space Force uses "Test, and Evaluation" (comma) vs others "Test and Evaluation"
  - PE numbers: 7-9 digits + 0-3 letter suffix (e.g. 0601102A, 0602668D8Z)
  - Classified rows: PE number 999999999
  - Multi-line titles: continuation line has no line number / PE number
  - BA subtotal rows (e.g. "Basic Research  616,802  497,455  513,917") - excluded
  - Individual agency section (pages 78+) repeats Defense-Wide PEs - deduplicated
  - Non-RDT&E appropriations (DHP, OIG, Chemical/Munitions) - skipped

Output schema:
    fiscal_year         int
    component           str    e.g. "Army", "Space Force", "Defense-Wide"
    appropriation       str    e.g. "Research, Development, Test and Evaluation, Army"
    budget_activity     str    e.g. "BA3 - Advanced Technology Development"
    pe_number           str    e.g. "0603001A"  (empty string for classified)
    pe_title            str
    line_no             Int64
    act_code            str    e.g. "03"
    is_classified       bool
    py_amount           float  Prior Year actuals ($K)
    cy_amount           float  Current Year PB request ($K) - None if CR year
    by_amount           float  Budget Year request ($K)
    source_file         str
    extraction_method   str    "native" | "ocr"

Usage:
    parser = R1Parser()
    df = parser.parse_file(Path("data/raw/comptroller/2025/rdtee/FY2025_r1.pdf"))

    from acquisition.comptroller_scraper import ComptrollerScraper
    manifest = ComptrollerScraper().scan_local(exhibit_types=["rdtee"])
    df_all = parser.parse_manifest(manifest)
    df_all.to_parquet("data/processed/r1_all_years.parquet")

CLI:
    python parsing/r1_parser.py --file data/raw/comptroller/2025/rdtee/FY2025_r1.pdf
    python parsing/r1_parser.py --manifest --years 2020 2021 2022 2023 2024 2025
"""

import logging
import re
import subprocess
from pathlib import Path

import pandas as pd
import pdfplumber

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

BA_MAP = {
    "01": "BA1 - Basic Research",
    "02": "BA2 - Applied Research",
    "03": "BA3 - Advanced Technology Development",
    "04": "BA4 - Advanced Component Development & Prototypes",
    "05": "BA5 - System Development & Demonstration",
    "06": "BA6 - Management Support",
    "07": "BA7 - Operational Systems Development",
    "08": "BA8 - Software And Digital Technology Pilot Programs",
    "20": "BA20 - Continuing Resolution Programs",
}

# PE number: 7-9 digits + 0-3 uppercase alphanumeric chars
# Covers: 0601102A, 0602668D8Z, 1160401BB, 0305251A, 999999999
PE_NUMBER_RE = re.compile(r"^[0-9]{7,9}[A-Z0-9]{0,3}$")

# Appropriation header. Handles all observed variants:
#   "Test and Evaluation, Army"          (FY2024+)
#   "Test, and Evaluation, Space Force"  (Space Force)
#   "Test & Eval, Army"                  (FY2022-2023 abbreviated)
APPR_RE = re.compile(
    r"Appropriation:\s*\S+\s+(Research,\s+Development,\s+"
    r"Test(?:,?\s+and\s+Evaluation|\s*&\s*Eval)[,\s]+(.+?))\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# OT&E is a valid separate appropriation we want to capture
OTE_APPR_RE = re.compile(
    r"Appropriation:\s*\S+\s+Operational\s+Test\s+and\s+Evaluation",
    re.IGNORECASE | re.MULTILINE,
)

# Non-RDT&E appropriations to skip entirely
NON_RDTEE_RE = re.compile(
    r"Appropriation:\s*\S+\s+(?:Defense Health Program|"
    r"Office of the Inspector General|Chemical Agents|"
    r"National Defense Sealift)",
    re.IGNORECASE,
)

# Data row regex.
# Groups: (line_no, pe_number, title, act_code, remainder)
#
# Two column layouts across fiscal years:
#   FY2024+:   line  pe  title  act  SEC  py  cy  by   (Sec before amounts)
#   FY2022-23: line  pe  title  act  py   cy  by  SEC  (Sec after amounts)
#
# We capture everything after the act code as "remainder" and strip the
# single-letter Sec value in _parse_page before calling parse_amounts.
DATA_ROW_RE = re.compile(
    r"^\s*(\d+)\s+"                # line number
    r"([0-9]{7,9}[A-Z0-9]{0,3})"  # PE number
    r"\s+(.+?)\s{2,}"              # title (2+ spaces as right boundary)
    r"(\d{2})\s+"                  # Act code
    r"(.*?)\s*$",                  # remainder: Sec + amounts (either order)
    re.DOTALL,
)

# Continuation line: indented text with no leading line number
CONTINUATION_RE = re.compile(r"^\s{5,}([A-Za-z(].+?)\s*$")

# BA subtotal labels (strip trailing amounts before checking)
SUBTOTAL_LABELS = {
    "basic research",
    "applied research",
    "advanced technology development",
    "advanced component development & prototypes",
    "advanced component development and prototypes",
    "system development & demonstration",
    "system development and demonstration",
    "management support",
    "operational systems development",
    "software and digital technology pilot programs",
}

OUTPUT_COLUMNS = [
    "fiscal_year", "component", "appropriation", "budget_activity",
    "pe_number", "pe_title", "line_no", "act_code", "is_classified",
    "py_amount", "cy_amount", "by_amount",
    "source_file", "extraction_method",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_subtotal(text: str) -> bool:
    """True if text (possibly with trailing amounts) is a BA subtotal label."""
    label = re.sub(r"[\d,\s\*]+$", "", text).strip().lower()
    return label in SUBTOTAL_LABELS


def parse_amounts(
    token_str: str,
) -> tuple[float | None, float | None, float | None]:
    """
    Parse three right-aligned dollar columns from the amounts portion of a row.
    Amounts are in $thousands, comma-formatted, right-aligned.

    Uses gap-based splitting (2+ spaces = column boundary) so blank columns
    are preserved correctly. Example:
      "386,594             296,670       310,191"  -> (386594, 296670, 310191)
      "24,359                            21,349"   -> (24359,  None,   21349)
      "27,833              34,572"                 -> (27833,  None,   34572)
      ""                                           -> (None,   None,   None)

    When only two values are present the R-1 convention is PY and BY,
    with CY blank (e.g. a CR year or a new-start program).

    Returns (py_amount, cy_amount, by_amount).
    """
    parts = [p.strip() for p in re.split(r"\s{2,}", token_str.strip()) if p.strip()]

    def _f(s: str) -> float | None:
        try:
            return float(s.replace(",", "").replace("*", ""))
        except ValueError:
            return None

    if len(parts) >= 3:
        return _f(parts[0]), _f(parts[1]), _f(parts[2])
    elif len(parts) == 2:
        return _f(parts[0]), None, _f(parts[1])
    elif len(parts) == 1:
        return _f(parts[0]), None, None
    return None, None, None


def is_native_pdf(pdf_path: Path, sample_pages: int = 3) -> bool:
    """True if PDF has extractable text (native), False if scanned."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            chars = sum(len(p.extract_text() or "") for p in pdf.pages[:sample_pages])
        return chars > 200
    except Exception:
        return False


# ── Era Detection ─────────────────────────────────────────────────────────────

class Era:
    LEGACY  = "legacy"    # FY1998-2001: scanned
    MODERN1 = "modern1"   # FY2002-2016
    MODERN2 = "modern2"   # FY2017-present

def detect_era(fy: int) -> str:
    if fy <= 2001: return Era.LEGACY
    if fy <= 2016: return Era.MODERN1
    return Era.MODERN2


# ── Native PDF Parser ─────────────────────────────────────────────────────────

class NativeR1Parser:
    """
    Parses native (text-based) R-1 PDFs.

    Strategy:
      1. Extract pages via pdftotext -layout (preserves column spacing)
      2. Track current appropriation/component from section headers
      3. Skip non-RDT&E pages (DHP, OIG, Chemical/Munitions, Sealift)
      4. Match data rows with DATA_ROW_RE; handle multi-line titles
      5. Map Act code -> BA label
    """

    def __init__(self, fiscal_year: int, pdf_path: Path):
        self.fiscal_year = fiscal_year
        self.pdf_path = pdf_path

    def parse(self) -> list[dict]:
        records: list[dict] = []
        current_appropriation = "Unknown"
        current_component = "Unknown"

        for page_text in self._extract_pages():
            # Skip non-RDT&E appropriation pages entirely
            if NON_RDTEE_RE.search(page_text):
                continue

            appr, comp = self._parse_appropriation_header(page_text)
            if appr:
                current_appropriation = appr
                current_component = comp

            records.extend(
                self._parse_page(page_text, current_component, current_appropriation)
            )

        logger.info(f"  Native: {self.pdf_path.name} -> {len(records)} raw PE records")
        return records

    # ── Text extraction ───────────────────────────────────────────────────────

    def _extract_pages(self) -> list[str]:
        """Extract pages via pdftotext -layout, fall back to pdfplumber."""
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(self.pdf_path), "-"],
                capture_output=True, text=True, check=True,
            )
            return result.stdout.split("\f")
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning("pdftotext unavailable - falling back to pdfplumber")
            with pdfplumber.open(self.pdf_path) as pdf:
                return [p.extract_text(layout=True) or "" for p in pdf.pages]

    # ── Header parsing ────────────────────────────────────────────────────────

    def _parse_appropriation_header(
        self, page_text: str
    ) -> tuple[str | None, str | None]:
        """
        Extract (appropriation, component) from page header.
        Returns (None, None) if no RDT&E/OT&E appropriation header found.
        """
        m = APPR_RE.search(page_text)
        if m:
            appropriation = m.group(1).strip()
            # Older PDFs append date on same line: "AF                 Date: Feb 2010"
            # Strip at "Date:" and collapse whitespace
            comp_raw = m.group(2)
            comp_raw = re.sub(r"\s+Date:.*$", "", comp_raw, flags=re.IGNORECASE)
            comp_raw = comp_raw.strip().rstrip(".,")
            component = self._normalise_component(comp_raw)
            return appropriation, component

        if OTE_APPR_RE.search(page_text):
            return "Operational Test and Evaluation, Defense", "OT&E"

        return None, None

    @staticmethod
    def _normalise_component(raw: str) -> str:
        # Collapse internal whitespace before matching
        cleaned = re.sub(r"\s+", " ", raw).strip().lower()
        # Exact / prefix abbreviations used in older R-1 PDFs
        abbrev = {
            "af":       "Air Force",
            "ar":       "Army",
            "na":       "Navy",
            "dw":       "Defense-Wide",
            "ote":      "OT&E",
            "sf":       "Space Force",
        }
        if cleaned in abbrev:
            return abbrev[cleaned]
        # Multi-component entries like "Dw, Ra" -> keep as Defense-Wide (primary)
        first = cleaned.split(",")[0].strip()
        if first in abbrev:
            return abbrev[first]
        # Full-name substring matching
        mapping = {
            "army":             "Army",
            "navy":             "Navy",
            "air force":        "Air Force",
            "space force":      "Space Force",
            "defense-wide":     "Defense-Wide",
            "defense wide":     "Defense-Wide",
            "defensewide":      "Defense-Wide",
            "operational test": "OT&E",
        }
        for key, val in mapping.items():
            if key in cleaned:
                return val
        return raw.strip().title()

    # ── Row parsing ───────────────────────────────────────────────────────────

    def _parse_page(
        self,
        page_text: str,
        component: str,
        appropriation: str,
    ) -> list[dict]:
        lines = page_text.split("\n")
        records: list[dict] = []
        pending: dict | None = None

        for line in lines:
            # ── Possible title continuation for pending record ────────────────
            if pending is not None:
                cont = CONTINUATION_RE.match(line)
                if cont and not DATA_ROW_RE.match(line):
                    text = cont.group(1).strip()
                    if not _is_subtotal(text):
                        pending["pe_title"] = (pending["pe_title"] + " " + text).strip()
                    records.append(pending)
                    pending = None
                    continue
                else:
                    records.append(pending)
                    pending = None

            # ── Try data row match ────────────────────────────────────────────
            m = DATA_ROW_RE.match(line)
            if not m:
                continue

            line_no_str = m.group(1)
            pe_raw      = m.group(2).strip().upper()
            title_raw   = m.group(3).strip()
            act_code    = m.group(4)
            # Strip Sec column (single uppercase letter) from either end:
            #   FY2024+:   "U    386,594   296,670   310,191"
            #   FY2022-23: "25,492   43,357   31,426   U"
            remainder   = m.group(5).strip()
            remainder   = re.sub(r"^[A-Z]\s+", "", remainder)  # leading Sec
            remainder   = re.sub(r"\s+[A-Z]$", "", remainder)  # trailing Sec
            amounts_str = remainder

            # Skip BA subtotal rows
            if _is_subtotal(title_raw):
                continue

            # Validate PE number
            if not PE_NUMBER_RE.match(pe_raw):
                continue

            is_classified = (pe_raw == "999999999")
            py_amt, cy_amt, by_amt = parse_amounts(amounts_str)

            pending = {
                "fiscal_year":     self.fiscal_year,
                "component":       component,
                "appropriation":   appropriation,
                "budget_activity": BA_MAP.get(act_code, f"BA{act_code}"),
                "pe_number":       "" if is_classified else pe_raw,
                "pe_title":        title_raw,
                "line_no":         int(line_no_str),
                "act_code":        act_code,
                "is_classified":   is_classified,
                "py_amount":       py_amt,
                "cy_amount":       cy_amt,
                "by_amount":       by_amt,
            }

        if pending is not None:
            records.append(pending)

        return records


# ── OCR Parser (Legacy FY1998-2001) ──────────────────────────────────────────

class OCRParser:
    """
    Parses scanned R-1 PDFs (FY1998-2001) via PyMuPDF rasterization + pytesseract.

    Install requirements:
        pip install pytesseract pillow pymupdf
        # Plus Tesseract binary: https://github.com/tesseract-ocr/tesseract

    Results are best-effort - scanned late-90s government docs vary in quality.
    """

    OCR_DPI = 300

    def __init__(self, fiscal_year: int, pdf_path: Path):
        self.fiscal_year = fiscal_year
        self.pdf_path = pdf_path

    def parse(self) -> list[dict]:
        try:
            import fitz
            import pytesseract
            from PIL import Image
            import io
        except ImportError as e:
            logger.error(
                f"OCR dependencies missing: {e}\n"
                "Run: pip install pytesseract pillow pymupdf\n"
                "And install Tesseract: https://github.com/tesseract-ocr/tesseract"
            )
            return []

        records: list[dict] = []
        current_appropriation = "Unknown"
        current_component = "Unknown"
        doc = fitz.open(str(self.pdf_path))

        logger.info(
            f"  OCR: {self.pdf_path.name} ({doc.page_count} pages) "
            "- this may take several minutes"
        )

        for page_num in range(doc.page_count):
            mat = fitz.Matrix(self.OCR_DPI / 72, self.OCR_DPI / 72)
            pix = doc[page_num].get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            page_text = pytesseract.image_to_string(img, config="--psm 6 --oem 3")

            if NON_RDTEE_RE.search(page_text):
                continue

            # Reuse the native parser's header and row logic on OCR text
            worker = NativeR1Parser(self.fiscal_year, self.pdf_path)
            appr, comp = worker._parse_appropriation_header(page_text)
            if appr:
                current_appropriation = appr
                current_component = comp

            records.extend(
                worker._parse_page(page_text, current_component, current_appropriation)
            )

        doc.close()
        logger.info(f"  OCR complete: {len(records)} raw PE records")
        return records


# ── Main Parser ───────────────────────────────────────────────────────────────

class R1Parser:
    """
    Top-level R-1 parser. Routes each PDF to the correct extractor,
    normalises, deduplicates, and returns a clean DataFrame.

    Example:
        parser = R1Parser()
        df = parser.parse_file(Path("data/raw/comptroller/2025/rdtee/FY2025_r1.pdf"))
        print(df.groupby("component")["by_amount"].sum() / 1e6)
    """

    def parse_file(
        self,
        pdf_path: Path,
        fiscal_year: int | None = None,
    ) -> pd.DataFrame:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

        if fiscal_year is None:
            fiscal_year = self._infer_fy(pdf_path)

        logger.info(f"Parsing {pdf_path.name} (FY{fiscal_year})")

        if is_native_pdf(pdf_path):
            worker = NativeR1Parser(fiscal_year, pdf_path)
            method = "native"
        else:
            logger.info("  Scanned PDF detected - routing to OCR parser")
            worker = OCRParser(fiscal_year, pdf_path)
            method = "ocr"

        raw = worker.parse()
        if not raw:
            logger.warning(f"  No records extracted from {pdf_path.name}")
            return pd.DataFrame(columns=OUTPUT_COLUMNS)

        df = pd.DataFrame(raw)
        df["source_file"] = pdf_path.name
        df["extraction_method"] = method
        df = self._normalise(df)
        logger.info(f"  -> {len(df):,} clean PE records")
        return df

    def parse_manifest(
        self,
        manifest: list[dict],
        save_intermediate: bool = True,
    ) -> pd.DataFrame:
        """
        Parse every file in a comptroller manifest.
        Saves per-FY Parquet files as it goes (resume-safe).
        """
        all_dfs: list[pd.DataFrame] = []
        failed: list[dict] = []

        by_year: dict = {}
        for item in manifest:
            fy = item.get("fiscal_year", 0)
            by_year.setdefault(fy, []).append(item)

        for fy, items in sorted(by_year.items()):
            fy_frames: list[pd.DataFrame] = []
            for item in items:
                path = Path(item["local_path"])
                try:
                    df = self.parse_file(
                        path,
                        fiscal_year=fy if isinstance(fy, int) else None,
                    )
                    if not df.empty:
                        fy_frames.append(df)
                except Exception as e:
                    logger.error(f"Failed {path.name}: {e}")
                    failed.append(item)

            if fy_frames:
                fy_df = pd.concat(fy_frames, ignore_index=True)
                all_dfs.append(fy_df)
                if save_intermediate and isinstance(fy, int):
                    out = config.PROCESSED_DIR / f"r1_{fy}.parquet"
                    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
                    fy_df.to_parquet(out, index=False)
                    logger.info(f"  Intermediate saved -> {out}")

        if not all_dfs:
            return pd.DataFrame(columns=OUTPUT_COLUMNS)

        combined = (
            pd.concat(all_dfs, ignore_index=True)
            .sort_values(["fiscal_year", "component", "line_no"])
            .reset_index(drop=True)
        )

        if failed:
            logger.warning(f"{len(failed)} file(s) failed:")
            for f in failed:
                logger.warning(f"  {f.get('local_path')}")

        logger.info(
            f"Complete: {len(combined):,} records | "
            f"{combined['fiscal_year'].nunique()} FYs | "
            f"{combined['component'].nunique()} components"
        )
        return combined

    def save(
        self,
        df: pd.DataFrame,
        name: str = "r1_all_years",
        fmt: str = "parquet",
    ) -> Path:
        config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        path = config.PROCESSED_DIR / f"{name}.{fmt}"
        if fmt == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)
        logger.info(f"Saved {len(df):,} rows -> {path}")
        return path

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _infer_fy(path: Path) -> int:
        for part in path.parts:
            if part.isdigit() and 2000 <= int(part) <= 2040:
                return int(part)
        m = re.search(r"(?:fy|pb|FY)(\d{4})", path.name)
        if m:
            return int(m.group(1))
        logger.warning(f"Cannot infer FY from {path} - defaulting to 0")
        return 0

    @staticmethod
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        # String columns
        for col in ["component", "appropriation", "budget_activity",
                    "pe_number", "pe_title", "source_file", "extraction_method"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        # Numeric columns
        for col in ["py_amount", "cy_amount", "by_amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Integer columns
        for col in ["fiscal_year", "line_no"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        # Bool
        if "is_classified" in df.columns:
            df["is_classified"] = df["is_classified"].astype(bool)

        # Deduplicate: the individual agency section (pages 78+) re-lists
        # all Defense-Wide PEs. Keep the row with the most non-null amounts.
        df["_amt_count"] = df[["py_amount", "cy_amount", "by_amount"]].notna().sum(axis=1)
        df = (
            df.sort_values("_amt_count", ascending=False)
              .drop_duplicates(subset=["fiscal_year", "component", "pe_number", "act_code"], keep="first")
              .drop(columns=["_amt_count"])
        )

        # Ensure all output columns present
        for col in OUTPUT_COLUMNS:
            if col not in df.columns:
                df[col] = pd.NA

        return df[OUTPUT_COLUMNS].reset_index(drop=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cli = argparse.ArgumentParser(description="Parse DoD R-1 PDFs")
    cli.add_argument("--file",     type=Path, help="Parse a single PDF")
    cli.add_argument("--manifest", action="store_true",
                     help="Parse all files found by the local ingestor")
    cli.add_argument("--years",    nargs="+", type=int, default=None)
    cli.add_argument("--output",   choices=["parquet", "csv"], default="parquet")
    cli.add_argument("--no-intermediate", action="store_true")
    args = cli.parse_args()

    parser = R1Parser()

    if args.file:
        df = parser.parse_file(args.file)
        if not df.empty:
            out = parser.save(df, name=args.file.stem, fmt=args.output)
            print(f"\nSaved {len(df):,} records -> {out}")
            print(f"\nBy component (BY $M):")
            comp_summary = (
                df.groupby("component")
                  .agg(pes=("pe_number", "count"), by_m=("by_amount", lambda x: x.sum()/1e6))
                  .sort_values("by_m", ascending=False)
            )
            print(comp_summary.to_string())
            print(f"\nTotal BY: ${df['by_amount'].sum()/1e9:.3f}B")
            print(f"Classified rows: {df['is_classified'].sum()}")

    elif args.manifest:
        from acquisition.comptroller_scraper import ComptrollerScraper
        manifest = ComptrollerScraper().scan_local(
            fiscal_years=args.years,
            exhibit_types=["rdtee"],
        )
        if not manifest:
            print("No files found. Check data/raw/comptroller/ structure.")
        else:
            df_all = parser.parse_manifest(
                manifest,
                save_intermediate=not args.no_intermediate,
            )
            if not df_all.empty:
                out = parser.save(df_all, fmt=args.output)
                print(f"\nTotal records  : {len(df_all):,}")
                print(f"Fiscal years   : {sorted(df_all['fiscal_year'].dropna().unique())}")
                print(f"Components     : {sorted(df_all['component'].unique())}")
                print(f"Classified rows: {df_all['is_classified'].sum():,}")
                print(f"Saved -> {out}")
    else:
        cli.print_help()