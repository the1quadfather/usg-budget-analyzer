"""
Central configuration for the DoD/IC Budget Analyzer.
Adjust fiscal years, paths, and agency targets here.
"""

from pathlib import Path

# ── Fiscal Years ──────────────────────────────────────────────────────────────
# PB = President's Budget submission year (e.g., PB2025 funds FY2025)
FISCAL_YEARS = list(range(1998, 2028))   # FY1998–FY2027
CURRENT_FY = 2027

# First fiscal year with an official machine-readable R-1 spreadsheet
# (r1_display.xlsx) on the comptroller site. FY2011 and earlier are PDF-only.
XLSX_FIRST_FY = 2012

# ── Directory Layout ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Sub-directories under raw/
COMPTROLLER_DIR = RAW_DIR / "comptroller"
USASPENDING_DIR = RAW_DIR / "usaspending"
GAO_DIR = RAW_DIR / "gao"
CONGRESS_DIR = RAW_DIR / "congress"

for d in [COMPTROLLER_DIR, USASPENDING_DIR, GAO_DIR, CONGRESS_DIR, PROCESSED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── DoD Comptroller ───────────────────────────────────────────────────────────
# The site moved from comptroller.defense.gov to comptroller.war.gov after the
# 2025 Department of War rename; the old domain 403s automated clients.
COMPTROLLER_BASE_URL = "https://comptroller.war.gov"
COMPTROLLER_LEGACY_BASE_URL = "https://comptroller.defense.gov"
COMPTROLLER_BUDGET_URL = "https://comptroller.war.gov/budgetmaterials/budget{year}.aspx"

# Official machine-readable exhibit spreadsheets (verified FY2012–FY2027 for R-1)
COMPTROLLER_XLSX_URL = (
    "https://comptroller.war.gov/Portals/45/Documents/defbudget/FY{year}/{stem}.xlsx"
)
XLSX_EXHIBIT_STEMS = {
    "rdtee":       "r1_display",   # R-1: RDT&E programs
    "procurement": "p1_display",   # P-1: Procurement programs
    "om":          "o1_display",   # O-1: Operation & Maintenance
}

# Document type codes used in URL/filename patterns on the comptroller site
# R-2: RDT&E Program/Project Justification (most detail-rich for research programs)
# P-40: Procurement line-item justification
# O-1: Operation & Maintenance activity group
DOD_EXHIBIT_TYPES = {
    "rdtee":        "r2",    # Research, Development, Test & Evaluation
    "procurement":  "p40",   # Procurement
    "om":           "o1",    # Operation & Maintenance
}

# Service / Agency identifiers as they appear in comptroller filenames
DOD_COMPONENTS = {
    "army":     "Army",
    "navy":     "Navy",
    "af":       "AirForce",
    "usmc":     "Marines",
    "socom":    "SOCOM",
    "darpa":    "DARPA",
    "mda":      "MDA",       # Missile Defense Agency
    "disa":     "DISA",
    "dia":      "DIA",
    "nga":      "NGA",
    "nro":      "NRO",
    "nsa":      "NSA",       # limited unclassified exhibits
    "dod_wide": "OSD",       # OSD / Defense-Wide
}

# Components with known (some) public budget exhibits
IC_COMPONENTS_PUBLIC = ["dia", "nga", "nro"]

# ── USASpending.gov API ───────────────────────────────────────────────────────
USASPENDING_API_BASE = "https://api.usaspending.gov/api/v2"

# DoD agency codes on USASpending (CGAC / FREC codes)
USASPENDING_AGENCY_CODES = {
    "dod":   "097",
    "army":  "021",
    "navy":  "017",
    "af":    "057",
    "dia":   "202",
    "nga":   "289",
    "nro":   "012",
}

# Award types to pull — contracts are most relevant for R&D programs
USASPENDING_AWARD_TYPES = ["A", "B", "C", "D"]  # Contract types
USASPENDING_PAGE_SIZE = 100  # Max results per API page

# ── GAO ───────────────────────────────────────────────────────────────────────
GAO_BASE_URL = "https://www.gao.gov"
GAO_REPORTS_API = "https://www.gao.gov/api/v1/reports"

# Report categories most relevant to DoD/IC programs
GAO_CATEGORIES = [
    "Defense",
    "Intelligence",
    "Science, Technology and Innovation",
    "Information Technology",
]

# ── Gemini enrichment (optional) ──────────────────────────────────────────────
# Used by analysis/oss_enricher.py for open-source statement search and
# candidate adjudication. The app runs fine without a key - Gemini panels
# simply stay disabled. Key is read from the first env var found.
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

# ── HTTP Client Defaults ──────────────────────────────────────────────────────
HTTP_TIMEOUT = 30           # seconds
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF = 2.0    # exponential backoff base (seconds)
# Browser-like headers — the comptroller site's bot filtering rejects
# self-identifying crawler user agents.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
