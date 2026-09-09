"""RDT&E-specific constant-dollar conversion from the DoD Green Book."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

import config


DEFLATOR_PATH = config.PROCESSED_DIR / "rdte_deflators_fy2025.csv"
DEFAULT_BASE_YEAR = 2025


def provenance_record() -> dict:
    row = load_rdte_deflators().iloc[0]
    return {
        "filename": "FY2025 Green Book, Table 5-4",
        "document_type": "RDT&E deflator",
        "publication_year": 2025,
        "source_url": row["source_url"],
        "retrieved_at": None,
        "processed_date": None,
    }


@lru_cache(maxsize=1)
def load_rdte_deflators(path: Path = DEFLATOR_PATH) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"fiscal_year", "rdte_index", "base_year", "source_url"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Deflator file is missing {sorted(missing)}")
    if frame["fiscal_year"].duplicated().any():
        raise ValueError("Deflator file contains duplicate fiscal years")
    return frame.sort_values("fiscal_year").reset_index(drop=True)


def convert_amount(
    amount: float,
    fiscal_year: int,
    *,
    base_year: int = DEFAULT_BASE_YEAR,
) -> float:
    """Convert a then-year RDT&E amount to constant ``base_year`` dollars."""
    frame = load_rdte_deflators()
    indexes = dict(zip(frame["fiscal_year"], frame["rdte_index"]))
    if fiscal_year not in indexes or base_year not in indexes:
        raise KeyError(f"No RDT&E deflator for FY{fiscal_year} or FY{base_year}")
    return float(amount) * float(indexes[base_year]) / float(indexes[fiscal_year])


def apply_deflator(
    frame: pd.DataFrame,
    *,
    amount_column: str,
    year_column: str = "fiscal_year",
    base_year: int = DEFAULT_BASE_YEAR,
) -> pd.Series:
    indexes = load_rdte_deflators().set_index("fiscal_year")["rdte_index"]
    factors = frame[year_column].map(indexes)
    if factors.isna().any():
        missing = sorted(frame.loc[factors.isna(), year_column].unique())
        raise KeyError(f"No RDT&E deflator for fiscal years {missing}")
    base_index = float(indexes.loc[base_year])
    return frame[amount_column].astype(float) * base_index / factors.astype(float)
