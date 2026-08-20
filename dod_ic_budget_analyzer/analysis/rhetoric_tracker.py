"""
analysis/rhetoric_tracker.py

Correlates AI-characterized open-source emphasis on a program with its
funding trajectory - "did the money follow the talk?"

The alignment coefficient is a Spearman rank correlation between annual
mention intensity and annual funding, evaluated at 0/1/2-year leads
(rhetoric in year Y is tested against funding in Y, Y+1, Y+2 - budget
requests are built one to two years ahead, so a lead is expected). The
reported coefficient is the strongest of the three, with its lead.

Pure pandas - no API calls - so it is testable without Gemini. Signal data
comes from oss_enricher.annual_signal(); funding from TrendTracker
pe histories summed over the selected PEs.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

MIN_OVERLAP_YEARS = 4  # below this a rank correlation is numerology


def align_rhetoric_funding(
    signal: pd.DataFrame, funding: pd.DataFrame
) -> dict:
    """
    Args:
        signal:  columns fiscal_year, mention_intensity, positive_pct,
                 negative_pct, stated_priority (from annual_signal()).
        funding: columns fiscal_year, amount_thousands (aggregated over the
                 selected PEs; one row per year).

    Returns dict with:
        merged            per-year DataFrame (signal + funding + yoy_pct)
        mention_trend_pct first->last change in mention intensity (%)
        positive_share    statement-weighted mean positive share (%)
        priority_years    (count, total) years officials named it a priority
        funding_trend_pct first->last funding change (%)
        funding_cagr_pct  funding CAGR over the span (%)
        alignment         {"coefficient", "lead_years", "n_years",
                           "by_lead": {lead: rho}} or None if too few years
    """
    result = {
        "merged": pd.DataFrame(), "mention_trend_pct": None,
        "positive_share": None, "priority_years": (0, 0),
        "funding_trend_pct": None, "funding_cagr_pct": None,
        "alignment": None,
    }
    if signal.empty or funding.empty:
        return result

    sig = signal.sort_values("fiscal_year").reset_index(drop=True)
    fund = (
        funding.groupby("fiscal_year", as_index=False)["amount_thousands"]
        .sum().sort_values("fiscal_year").reset_index(drop=True)
    )
    fund["amount_m"] = fund["amount_thousands"] / 1e3
    fund["yoy_pct"] = fund["amount_m"].pct_change() * 100

    merged = sig.merge(fund, on="fiscal_year", how="left")
    result["merged"] = merged

    # Rhetoric-side headline numbers
    first_i, last_i = sig["mention_intensity"].iloc[0], sig["mention_intensity"].iloc[-1]
    if first_i > 0:
        result["mention_trend_pct"] = (last_i - first_i) / first_i * 100
    elif last_i > 0:
        result["mention_trend_pct"] = float("inf")
    result["positive_share"] = float(sig["positive_pct"].mean())
    result["priority_years"] = (int(sig["stated_priority"].sum()), len(sig))

    # Funding-side headline numbers
    span_fund = fund[fund["fiscal_year"].isin(
        range(int(sig["fiscal_year"].min()), int(sig["fiscal_year"].max()) + 1)
    )]
    if len(span_fund) >= 2:
        f0, f1 = span_fund["amount_m"].iloc[0], span_fund["amount_m"].iloc[-1]
        yrs = int(span_fund["fiscal_year"].iloc[-1] - span_fund["fiscal_year"].iloc[0])
        if f0 > 0:
            result["funding_trend_pct"] = (f1 - f0) / f0 * 100
            if f1 > 0 and yrs > 0:
                result["funding_cagr_pct"] = ((f1 / f0) ** (1 / yrs) - 1) * 100

    # Alignment: Spearman between intensity(Y) and funding(Y + lead)
    by_lead = {}
    for lead in (0, 1, 2):
        shifted = fund.copy()
        shifted["fiscal_year"] = shifted["fiscal_year"] - lead
        pair = sig.merge(
            shifted[["fiscal_year", "amount_m"]], on="fiscal_year", how="inner"
        ).dropna(subset=["mention_intensity", "amount_m"])
        if len(pair) < MIN_OVERLAP_YEARS:
            continue
        if pair["mention_intensity"].nunique() < 2 or pair["amount_m"].nunique() < 2:
            continue  # constant series - correlation undefined
        rho = pair["mention_intensity"].corr(pair["amount_m"], method="spearman")
        if pd.notna(rho):
            by_lead[lead] = round(float(rho), 3)

    if by_lead:
        best_lead = max(by_lead, key=lambda k: abs(by_lead[k]))
        shifted_n = len(sig) - best_lead
        result["alignment"] = {
            "coefficient": by_lead[best_lead],
            "lead_years": best_lead,
            "n_years": shifted_n,
            "by_lead": by_lead,
        }
    return result


def headline_sentence(program_name: str, r: dict, start: int, end: int) -> str:
    """One-paragraph plain-language summary of the alignment result."""
    bits = []
    if r["mention_trend_pct"] is not None and r["mention_trend_pct"] != float("inf"):
        bits.append(
            f"open-source emphasis on **{program_name}** "
            f"{'rose' if r['mention_trend_pct'] >= 0 else 'fell'} "
            f"~{abs(r['mention_trend_pct']):.0f}%"
        )
    if r["positive_share"] is not None:
        bits.append(f"~{r['positive_share']:.0f}% of characterized statements "
                    "were favorable")
    pr, total = r["priority_years"]
    if total:
        bits.append(f"officials named it a priority in {pr} of {total} years")
    if r["funding_trend_pct"] is not None:
        cagr = (f" ({r['funding_cagr_pct']:+.1f}%/yr)"
                if r["funding_cagr_pct"] is not None else "")
        bits.append(
            f"funding {'rose' if r['funding_trend_pct'] >= 0 else 'fell'} "
            f"{abs(r['funding_trend_pct']):.0f}% over the span{cagr}"
        )
    text = f"From FY{start}–FY{end}, " + "; ".join(bits) + "." if bits else ""
    a = r["alignment"]
    if a:
        lead_txt = (f"funding follows rhetoric with a {a['lead_years']}-year lead"
                    if a["lead_years"] else "rhetoric and funding move together")
        text += (
            f" **Alignment coefficient: {a['coefficient']:+.2f}** "
            f"(Spearman ρ, n={a['n_years']} years; {lead_txt})."
        )
    return text
