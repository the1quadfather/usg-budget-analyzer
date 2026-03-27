"""
Central configuration for the DoD/IC Budget Analyzer.
Adjust fiscal years, paths, and agency targets here.
"""

from pathlib import Path

# ── Fiscal Years ──────────────────────────────────────────────────────────────
# PB = President's Budget submission year (e.g., PB2025 funds FY2025)
FISCAL_YEARS = list(range(2020, 2026))   # FY2020–FY2025
CURRENT_FY = 2025

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
COMPTROLLER_BASE_URL = "https://comptroller.defense.gov"
COMPTROLLER_BUDGET_URL = "https://comptroller.defense.gov/Budget-Materials/Budget{year}/"

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

# ── HTTP Client Defaults ──────────────────────────────────────────────────────
HTTP_TIMEOUT = 30           # seconds
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF = 2.0    # exponential backoff base (seconds)
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BudgetResearchBot/1.0; "
        "+https://github.com/your-org/dod-ic-budget-analyzer)"
    )
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
