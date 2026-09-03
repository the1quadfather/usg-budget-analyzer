"""
app.py

Streamlit interface for the DoD Budget Explorer.

Information architecture: three tabs organized around analyst questions,
not data sources.
  Budget Trends    - topline RDT&E by component, plus account-level
                     "who got paid" drill-down
  Program Finder   - search -> program profile (Funding / Plans & Work /
                     Contracts & Awards / In the News)
  Data Coverage    - what's ingested, what's live-queried, known blind spots

Interaction rule: anything from the local database renders immediately;
external, slow-or-billable calls (USAspending.gov, AI) sit behind buttons
labeled with their source.
"""

import altair as alt
import pandas as pd
import streamlit as st
import polars as pl
from pathlib import Path

import config as config_module
from storage.db import get_engine, get_session_factory
from matching.fuzzy_matcher import ProgramMatcher
from analysis.program_linker import ProgramLinker
from analysis.trend_tracker import TrendTracker

# --- Configuration & State Setup ---
st.set_page_config(page_title="DoD Budget Explorer", layout="wide")

# Anchor the DB path to this file so the app works from any working directory
DB_PATH = f"sqlite:///{(Path(__file__).parent / 'data' / 'processed' / 'usg_budgets.db').as_posix()}"

@st.cache_resource
def init_db_connection():
    engine = get_engine(DB_PATH)
    return get_session_factory(engine)

@st.cache_resource
def load_matching_models():
    """
    Builds the linker once per process. Loaded lazily (first search), and
    degrades to lexical-only matching if the PyTorch stack is unavailable.
    """
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        fuzzy = ProgramMatcher(session)
        semantic = None
        try:
            from matching.semantic_matcher import SemanticMatcher
            semantic = SemanticMatcher(session)
        except Exception as e:
            st.warning(
                f"Semantic matching unavailable ({type(e).__name__}) — "
                "running name-similarity matching only."
            )
        linker = ProgramLinker(
            fuzzy, semantic, fuzzy_threshold=80.0, semantic_threshold=0.45
        )
    return linker

@st.cache_resource
def get_enricher():
    """AI enrichment client, or None when no SDK/API key is configured."""
    try:
        from analysis import oss_enricher
        if oss_enricher.available():
            return oss_enricher.GeminiEnricher()
    except Exception:
        pass
    return None

def current_user_id() -> str:
    """
    Who to bill, and whose grounded history to read. Anonymous sessions share
    the "local" identity; wiring st.login() later replaces this without any
    caller needing to change.
    """
    try:
        if st.user.is_logged_in:
            return str(st.user.sub or st.user.email or "local")
    except Exception:
        pass
    return "local"


def log_search(query: str, result: dict) -> None:
    """
    Record a Program Finder query so precompute can follow real demand instead
    of guessing, and so the golden eval set has real queries to grow from.
    """
    from analysis.ai_budget import session_factory, _utcnow
    from storage.db import SearchLog
    try:
        with session_factory()() as sess:
            sess.add(SearchLog(
                ts=_utcnow(), user_id=current_user_id(), query=query[:500],
                matched_pe=result.get("pe_number"),
                agency=result.get("agency"),
                needs_review=1 if result.get("needs_review") else 0,
            ))
            sess.commit()
    except Exception:
        pass  # demand logging must never break a search


def render_ai_result(res, render_fn, empty_msg: str = "Nothing found.") -> None:
    """
    Render an EnrichmentResult with its provenance shown honestly.

    Three things every AI panel owes the reader: the answer, how old it is,
    and - for anything grounded in Google Search - the Search Suggestions the
    Gemini API terms require be displayed alongside it.
    """
    if res.blocked:
        st.info(res.message)
        return
    if not res.grounded:
        # The model answered without searching, so whatever it produced is
        # recollection rather than retrieved coverage. Say so plainly instead
        # of showing invented headlines that look exactly like real ones.
        st.warning(
            "The web search didn't run for this program, so there's nothing "
            "sourced to show. Low-visibility programs often produce no "
            "search-worthy coverage. Try again, or check Plans & Work for "
            "what the official justification says."
        )
        return
    if res.empty:
        st.info(empty_msg)
    else:
        render_fn(res.payload)
    if res.cached and res.created_at:
        st.caption(f"Saved analysis from {res.created_at:%Y-%m-%d}. "
                   "Re-run below for a fresh look.")
    if res.search_suggestions_html:
        st.html(res.search_suggestions_html)


# --- Cached external lookups (USAspending.gov) ---

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_program_awards(program_name: str, agency: str, fy: int,
                         query_text: str) -> pd.DataFrame:
    from analysis.spending_explorer import SpendingExplorer
    ex = SpendingExplorer()
    try:
        return ex.program_awards(program_name, agency, fy, fy,
                                 query_text=query_text)
    finally:
        ex.close()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_program_subawards(program_name: str, fy: int,
                            query_text: str) -> pd.DataFrame:
    from analysis.spending_explorer import SpendingExplorer
    ex = SpendingExplorer()
    try:
        return ex.program_subawards(program_name, fy - 1, fy,
                                    query_text=query_text)
    finally:
        ex.close()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_account_breakdown(agency: str, fy: int, category: str) -> pd.DataFrame:
    from analysis.spending_explorer import SpendingExplorer
    ex = SpendingExplorer()
    try:
        return ex.account_breakdown(agency, fy, category=category)
    finally:
        ex.close()

@st.cache_data(ttl=600, show_spinner=False)
def fetch_agency_trends(start_yr: int, end_yr: int) -> pd.DataFrame:
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        df = TrendTracker(session).get_agency_trends(start_yr, end_yr)
    return df.to_pandas() if not df.is_empty() else pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_coverage_stats() -> dict:
    from sqlalchemy import text
    stats = {}
    engine = get_engine(DB_PATH)
    with engine.connect() as c:
        for key, q in {
            "funding_lines": "SELECT COUNT(*) FROM funding_lines",
            "fy_min": "SELECT MIN(fiscal_year) FROM funding_lines",
            "fy_max": "SELECT MAX(fiscal_year) FROM funding_lines",
            "programs": "SELECT COUNT(*) FROM program_elements",
            "narrative_pes": "SELECT COUNT(DISTINCT pe_number) FROM pe_narratives",
            "narratives": "SELECT COUNT(*) FROM pe_narratives",
            "accomplishments": "SELECT COUNT(*) FROM pe_accomplishments",
        }.items():
            try:
                stats[key] = c.execute(text(q)).scalar() or 0
            except Exception:
                stats[key] = 0
    return stats

# --- Chart styling (validated reference palette) ---

BASIS_COLORS = alt.Scale(
    domain=["Actual", "Enacted/CY", "Request"],
    range=["#2a78d6", "#1baf7a", "#eb6834"],
)
STRATEGY_LABELS = {
    "FUZZY": "Name similarity",
    "SEMANTIC": "Meaning (AI)",
    "ACRONYM": "Acronym",
    "PE_NUMBER": "PE number",
}
STRATEGY_COLORS = alt.Scale(
    domain=list(STRATEGY_LABELS.values()),
    range=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
)
AGENCY_COLORS = alt.Scale(
    domain=["Air Force", "Army", "Defense-Wide", "Navy", "Space Force", "OT&E"],
    range=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
)

def money_bar(df: pd.DataFrame, name_col: str) -> alt.Chart:
    """Single-hue horizontal bars for $ magnitude by category."""
    d = df.copy()
    d["amount_m"] = d["amount"] / 1e6
    return (
        alt.Chart(d)
        .mark_bar(color="#2a78d6", cornerRadiusEnd=3)
        .encode(
            x=alt.X("amount_m:Q", title="$ Millions obligated"),
            y=alt.Y(f"{name_col}:N", sort="-x", title=None),
            tooltip=[alt.Tooltip(f"{name_col}:N", title="Name"),
                     alt.Tooltip("amount_m:Q", format=",.1f", title="$M")],
        )
        .properties(height=max(30 * len(d) + 30, 120))
    )

EXECUTION_FYS = list(range(2018, 2027))

SessionFactory = init_db_connection()

# --- UI Layout ---
st.title("🇺🇸 DoD Budget Explorer")

tab_trends, tab_finder, tab_rhetoric, tab_coverage = st.tabs(
    ["Budget Trends", "Program Finder", "Rhetoric vs. Budget", "Data Coverage"]
)

# ═══════════════════════════════ Budget Trends ═══════════════════════════════
with tab_trends:
    st.header("RDT&E topline by component")
    col1, col2 = st.columns(2)
    start_yr = col1.slider("Start Year", 1998, 2026, 2010)
    end_yr = col2.slider("End Year", 1999, 2027, 2027)

    df_trends = fetch_agency_trends(start_yr, end_yr)
    if df_trends.empty:
        st.info("No funding data for that year range.")
    else:
        year_cols = [c for c in df_trends.columns if c.isdigit()]
        long = df_trends.melt(
            id_vars=["agency"], value_vars=year_cols,
            var_name="fiscal_year", value_name="amount_k",
        )
        long["amount_b"] = long["amount_k"] / 1e6
        long["fiscal_year"] = long["fiscal_year"].astype(int)
        long = long[long["amount_b"] > 0]

        trend_chart = (
            alt.Chart(long)
            .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(filled=True, size=45))
            .encode(
                x=alt.X("fiscal_year:O", title="Fiscal Year"),
                y=alt.Y("amount_b:Q", title="$ Billions"),
                color=alt.Color("agency:N", scale=AGENCY_COLORS, title="Component"),
                tooltip=[
                    alt.Tooltip("agency:N", title="Component"),
                    alt.Tooltip("fiscal_year:O", title="FY"),
                    alt.Tooltip("amount_b:Q", format=",.1f", title="$B"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(trend_chart, use_container_width=True)
        st.caption(
            "Each year shows its most reliable figure: reported actuals, then "
            "enacted, then the budget request. Discretionary only — "
            "reconciliation/mandatory funds are tracked separately."
        )
        with st.expander("Data table"):
            st.dataframe(df_trends, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Who got paid — account-level obligations")
    st.markdown(
        "Actual contract obligations from each component's RDT&E "
        "appropriation account."
    )
    from analysis.spending_explorer import RDTE_ACCOUNTS

    c1, c2, c3 = st.columns([1.2, 1, 1])
    exec_comp = c1.selectbox("Component", list(RDTE_ACCOUNTS.keys()))
    exec_fy = c2.selectbox("Fiscal year", EXECUTION_FYS,
                           index=EXECUTION_FYS.index(2025))
    exec_dim = c3.selectbox("Break down by", ["recipient", "industry", "state"])

    breakdown_key = f"breakdown::{exec_comp}::{exec_fy}::{exec_dim}"
    if st.button("Look up obligations (USAspending.gov)"):
        with st.spinner("Querying USAspending.gov..."):
            st.session_state[breakdown_key] = fetch_account_breakdown(
                exec_comp, exec_fy, exec_dim
            )
    breakdown = st.session_state.get(breakdown_key)
    if breakdown is not None:
        if breakdown.empty:
            st.info("No obligation data returned for this selection.")
        else:
            st.altair_chart(money_bar(breakdown, "name"), use_container_width=True)
            st.caption(
                f"Top {len(breakdown)} by contract obligations, "
                f"{exec_comp} RDT&E account, FY{exec_fy}. DoD awards post "
                "with a ~90-day delay; the current fiscal year is partial."
            )

# ═══════════════════════════════ Program Finder ══════════════════════════════
with tab_finder:
    st.header("Find a program")
    query = st.text_input(
        "Search — program name, quote from an article, or PE number",
        placeholder='e.g. "launched effects", DARPA Tactical Technology, 0602345A',
    )

    if query:
        with st.spinner("Searching programs..."):
            linker = load_matching_models()
            result = linker.link_query(query)

        log_search(query, result)

        if not result["matched_pe_id"]:
            st.warning(
                "No program match. Try the program's common name, a quote "
                "that names it, or its PE number (e.g. 0602345A)."
            )
        else:
            enricher = get_enricher()
            candidates = result["candidates"]

            if result["needs_review"]:
                st.warning(
                    f'Several programs match "{query}" — pick the right one '
                    "below, or use the AI resolver."
                )
            else:
                strat = STRATEGY_LABELS.get(result["match_strategy"],
                                            result["match_strategy"])
                st.success(
                    f"**{result['matched_name']}** — PE {result['pe_number']} "
                    f"({result['agency']}) · matched by {strat} · confidence "
                    f"{result['confidence_score'] * 100:.0f}%"
                )

            # --- AI resolution of ambiguous candidate sets ---
            # Semi-automatic: a resolution this query has had before renders
            # straight away; a new one offers a button. Adjudication isn't
            # grounded, so one user's resolution serves everyone who later
            # asks the same question.
            adjudication = None
            if enricher and result["needs_review"]:
                uid = current_user_id()
                res = enricher.adjudicate(query, candidates, user_id=uid,
                                          allow_fresh=False)
                if res.cold and st.button("Resolve ambiguous match (AI)"):
                    with st.spinner("Comparing candidates..."):
                        res = enricher.adjudicate(query, candidates,
                                                  user_id=uid,
                                                  allow_fresh=True)
                if res.blocked:
                    st.info(res.message)
                elif res.payload:
                    adjudication = res.payload
                    if adjudication.get("no_match"):
                        st.info("**AI assessment:** no confident pick. "
                                f"{adjudication['rationale']}")
                    else:
                        st.info(
                            f"**AI assessment:** PE {adjudication['pe_number']} "
                            f"({adjudication['agency']}) · confidence "
                            f"{adjudication['confidence'] * 100:.0f}%\n\n"
                            f"{adjudication['rationale']}"
                        )
                    if res.cached and res.created_at:
                        st.caption("Saved resolution from "
                                   f"{res.created_at:%Y-%m-%d}.")

            # --- Candidate selector ---
            labels = [
                f"PE {c['pe_number']} — {c['name'][:50]} [{c['agency']}]"
                for c in candidates
            ]
            default_idx = 0
            if adjudication and not adjudication.get("no_match"):
                for i, c in enumerate(candidates):
                    if c["pe_number"] == adjudication["pe_number"]:
                        default_idx = i
                        break
            if len(candidates) > 1:
                chosen_label = st.selectbox("Viewing:", labels, index=default_idx)
                sel = candidates[labels.index(chosen_label)]

                cand_df = pd.DataFrame([
                    {"label": lbl, "confidence": c["score"],
                     "matched_by": STRATEGY_LABELS.get(c["strategy"], c["strategy"])}
                    for lbl, c in zip(labels, candidates)
                ])
                bars = alt.Chart(cand_df).mark_bar(cornerRadiusEnd=3).encode(
                    x=alt.X("confidence:Q", scale=alt.Scale(domain=[0, 1]),
                            title="Match confidence"),
                    y=alt.Y("label:N", sort="-x", title=None),
                    color=alt.Color("matched_by:N", scale=STRATEGY_COLORS,
                                    title="How it matched"),
                    tooltip=["label:N", "matched_by:N",
                             alt.Tooltip("confidence:Q", format=".2f")],
                )
                values = bars.mark_text(align="left", dx=4, color="#898781").encode(
                    text=alt.Text("confidence:Q", format=".2f")
                )
                st.altair_chart(
                    (bars + values).properties(height=30 * len(candidates) + 40),
                    use_container_width=True,
                )
            else:
                sel = candidates[0]

            # ═══ Program profile ═══
            sub_funding, sub_plans, sub_awards, sub_news = st.tabs(
                ["Funding", "Plans & Work", "Contracts & Awards", "In the News"]
            )

            # --- Funding ---
            with sub_funding:
                with SessionFactory() as session:
                    hist = TrendTracker(session).get_pe_history(
                        sel["pe_number"], sel["agency"]
                    )
                if hist.is_empty():
                    st.info(
                        "No funding lines for this program in the database "
                        "(R-1 coverage: FY1998–FY2027)."
                    )
                else:
                    pdf = hist.to_pandas()
                    pdf["amount_m"] = pdf["amount_thousands"] / 1_000.0
                    pdf["yoy_pct"] = pdf["amount_m"].pct_change() * 100.0

                    latest = pdf.iloc[-1]
                    m1, m2, m3, m4 = st.columns(4)
                    delta = (
                        f"{pdf['yoy_pct'].iloc[-1]:+.1f}% YoY"
                        if len(pdf) > 1 and pd.notna(pdf["yoy_pct"].iloc[-1])
                        else None
                    )
                    m1.metric(
                        f"FY{int(latest.fiscal_year)} ({latest.basis})",
                        f"${latest.amount_m:,.1f}M",
                        delta=delta,
                    )
                    peak = pdf.loc[pdf["amount_m"].idxmax()]
                    m2.metric(f"Peak (FY{int(peak.fiscal_year)})",
                              f"${peak.amount_m:,.1f}M")
                    m3.metric(
                        "History",
                        f"{len(pdf)} yrs",
                        help=f"FY{int(pdf.fiscal_year.min())}–"
                             f"FY{int(pdf.fiscal_year.max())}",
                    )
                    first = pdf.iloc[0]
                    span = int(latest.fiscal_year - first.fiscal_year)
                    if span > 0 and first.amount_m > 0 and latest.amount_m > 0:
                        cagr = ((latest.amount_m / first.amount_m)
                                ** (1 / span) - 1) * 100
                        m4.metric(f"CAGR ({span}y)", f"{cagr:+.1f}%")

                    base = alt.Chart(pdf).encode(
                        x=alt.X("fiscal_year:O", title="Fiscal Year")
                    )
                    line = base.mark_line(color="#c3c2b7", strokeWidth=2).encode(
                        y=alt.Y("amount_m:Q", title="$ Millions"),
                    )
                    points = base.mark_point(filled=True, size=90).encode(
                        y="amount_m:Q",
                        color=alt.Color("basis:N", scale=BASIS_COLORS,
                                        title="Figure basis"),
                        tooltip=[
                            alt.Tooltip("fiscal_year:O", title="FY"),
                            alt.Tooltip("amount_m:Q", format=",.1f", title="$M"),
                            alt.Tooltip("basis:N", title="Basis"),
                        ],
                    )
                    st.altair_chart((line + points).properties(height=280),
                                    use_container_width=True)
                    st.caption(
                        "Each year shows its most reliable figure: reported "
                        "actuals, then the enacted/current-year figure, then "
                        "the budget request."
                    )

                    yoy_df = pdf.dropna(subset=["yoy_pct"])
                    if not yoy_df.empty:
                        yoy_chart = alt.Chart(yoy_df).mark_bar(
                            cornerRadiusEnd=2
                        ).encode(
                            x=alt.X("fiscal_year:O", title="Fiscal Year"),
                            y=alt.Y("yoy_pct:Q", title="YoY change (%)"),
                            color=alt.condition(
                                alt.datum.yoy_pct >= 0,
                                alt.value("#2a78d6"), alt.value("#e34948"),
                            ),
                            tooltip=[
                                alt.Tooltip("fiscal_year:O", title="FY"),
                                alt.Tooltip("yoy_pct:Q", format="+.1f",
                                            title="YoY %"),
                            ],
                        )
                        st.altair_chart(yoy_chart.properties(height=160),
                                        use_container_width=True)

                    with st.expander("Underlying funding table"):
                        st.dataframe(
                            pdf[["fiscal_year", "amount_thousands", "basis"]]
                            .rename(columns={"fiscal_year": "FY",
                                             "amount_thousands": "$K",
                                             "basis": "Basis"}),
                            use_container_width=True, hide_index=True,
                        )

            # --- Plans & Work (R-2 justification narratives) ---
            with sub_plans:
                from sqlalchemy import select as sa_select
                from storage.db import PEAccomplishment, PENarrative
                with SessionFactory() as session:
                    narrs = session.execute(
                        sa_select(PENarrative).where(
                            PENarrative.pe_number == sel["pe_number"],
                            PENarrative.agency == sel["agency"],
                        ).order_by(PENarrative.fiscal_year.desc(),
                                   PENarrative.project_number)
                    ).scalars().all()
                    accs = session.execute(
                        sa_select(PEAccomplishment).where(
                            PEAccomplishment.pe_number == sel["pe_number"],
                            PEAccomplishment.agency == sel["agency"],
                        )
                    ).scalars().all()

                if not narrs and not accs:
                    st.info(
                        "No justification narrative for this program. "
                        "Narrative books are ingested for Defense-Wide "
                        "components (PB2026–PB2027); Army, Navy, and Air "
                        "Force publish theirs as PDF only — not yet ingested."
                    )
                else:
                    pe_level = [n for n in narrs if n.project_number == ""]
                    projects, seen_projects = [], set()
                    for n in narrs:
                        if n.project_number and n.project_number not in seen_projects:
                            seen_projects.add(n.project_number)
                            projects.append(n)
                    if pe_level:
                        with st.expander(
                            f"Program mission description "
                            f"(PB{pe_level[0].fiscal_year})", expanded=True
                        ):
                            st.write(pe_level[0].description)
                    if projects:
                        with st.expander(
                            f"Projects under this program ({len(projects)})"
                        ):
                            for p in sorted(projects,
                                            key=lambda n: n.project_number):
                                st.markdown(
                                    f"**{p.project_number} — {p.project_title}**"
                                )
                                st.caption(
                                    p.description[:500]
                                    + ("…" if len(p.description) > 500 else "")
                                )
                    if accs:
                        label_rank = {"PY": 0, "CY": 1, "BY": 2}
                        best_rank = {}
                        for a in accs:
                            if a.accomplishment_fy:
                                r = label_rank.get(a.year_label[:2], 3)
                                best_rank[a.accomplishment_fy] = min(
                                    r, best_rank.get(a.accomplishment_fy, 3)
                                )
                        year_tag = {0: "reported work", 1: "current-year plan",
                                    2: "requested plan"}
                        fys = sorted(best_rank)
                        pick_fy = st.selectbox(
                            "Work detailed for", fys,
                            format_func=lambda y: (
                                f"FY{y} ({year_tag.get(best_rank[y], 'plan')})"
                            ),
                            key=f"acc_fy::{sel['pe_number']}",
                        )
                        year_accs = sorted(
                            (a for a in accs
                             if a.accomplishment_fy == pick_fy
                             and label_rank.get(a.year_label[:2], 3)
                                 == best_rank[pick_fy]),
                            key=lambda a: -(a.funding_millions or 0),
                        )
                        for a in year_accs[:12]:
                            amt = (f"${a.funding_millions:,.1f}M — "
                                   if a.funding_millions else "")
                            st.markdown(f"**{amt}{a.title or a.project_number}**")
                            if a.text:
                                st.caption(a.text[:700]
                                           + ("…" if len(a.text) > 700 else ""))
                        if len(year_accs) > 12:
                            st.caption(
                                f"…and {len(year_accs) - 12} more line items."
                            )

            # --- Contracts & Awards ---
            with sub_awards:
                ac1, _ = st.columns([1, 3])
                award_fy = ac1.selectbox(
                    "Fiscal year", EXECUTION_FYS,
                    index=EXECUTION_FYS.index(2025), key="award_fy",
                )
                awards_key = f"awards::{sel['pe_number']}::{award_fy}::{query}"
                if st.button("Search awards (USAspending.gov)"):
                    with st.spinner("Querying USAspending.gov..."):
                        st.session_state[awards_key] = fetch_program_awards(
                            sel["name"], sel["agency"], award_fy, query
                        )
                awards = st.session_state.get(awards_key)
                if awards is not None:
                    if awards.empty:
                        st.info(
                            f"No prime awards matched this program's keywords "
                            f"in FY{award_fy}. Why this can happen even when "
                            "money moved: award descriptions rarely name the "
                            "budget program; Other Transactions aren't "
                            "searchable as a group; work under umbrella "
                            "vehicles (PIAs, IDIQs) hides in generic prime "
                            "descriptions — try the subaward search below; "
                            "and DoD awards post with a ~90-day delay."
                        )
                    else:
                        by_recipient = (
                            awards.groupby("recipient", as_index=False)["amount"]
                            .sum().sort_values("amount", ascending=False)
                        )
                        st.altair_chart(money_bar(by_recipient, "recipient"),
                                        use_container_width=True)
                        display = awards.copy()
                        display["amount_m"] = display["amount"] / 1e6
                        display["description"] = (
                            display["description"].str.slice(0, 140)
                        )
                        st.dataframe(
                            display[["recipient", "amount_m", "instrument",
                                     "sub_agency", "start_date",
                                     "description", "url"]],
                            use_container_width=True, hide_index=True,
                            column_config={
                                "recipient": "Recipient",
                                "amount_m": st.column_config.NumberColumn(
                                    "Award $M", format="%.2f"),
                                "instrument": "Instrument",
                                "sub_agency": "Awarding office",
                                "start_date": "Start",
                                "description": "Description",
                                "url": st.column_config.LinkColumn(
                                    "Record", display_text="Open"),
                            },
                        )
                        st.caption(
                            "Keyword-matched DoD-funded prime awards "
                            "(contracts and grants/cooperative agreements) — "
                            "treat as leads, not a ledger: public award "
                            "records carry no program-element linkage."
                        )

                    subs_key = f"subs::{sel['pe_number']}::{award_fy}::{query}"
                    if st.button("Search subawards (umbrella vehicles)"):
                        with st.spinner("Querying subawards..."):
                            st.session_state[subs_key] = fetch_program_subawards(
                                sel["name"], award_fy, query
                            )
                    subs = st.session_state.get(subs_key)
                    if subs is not None:
                        if subs.empty:
                            st.caption(
                                "No matching subawards. Subaward reporting "
                                "is less complete than prime awards."
                            )
                        else:
                            sdisp = subs.copy()
                            sdisp["amount_m"] = sdisp["amount"] / 1e6
                            sdisp["description"] = (
                                sdisp["description"].str.slice(0, 140)
                            )
                            st.dataframe(
                                sdisp[["subawardee", "amount_m",
                                       "prime_recipient", "date",
                                       "description"]],
                                use_container_width=True, hide_index=True,
                                column_config={
                                    "subawardee": "Subawardee",
                                    "amount_m": st.column_config.NumberColumn(
                                        "Sub-award $M", format="%.2f"),
                                    "prime_recipient": "Prime recipient",
                                    "date": "Date",
                                    "description": "Description",
                                },
                            )

            # --- In the News ---
            with sub_news:
                if enricher is None:
                    from analysis import oss_enricher
                    _, missing = oss_enricher.status()
                    if missing == "package":
                        st.caption(
                            "AI lookups are disabled — install the SDK with "
                            "`pip install google-genai` (into the Python that "
                            "runs streamlit), then restart the app."
                        )
                    else:
                        st.caption(
                            "AI lookups are disabled — set the GEMINI_API_KEY "
                            "environment variable and restart the app."
                        )
                else:
                    uid = current_user_id()

                    def render_hits(hits):
                        for hit in hits:
                            title = (f"{hit['title']} — {hit['source']} "
                                     f"({hit['date']})")
                            with st.expander(title):
                                st.write(hit["summary"])
                                st.progress(
                                    min(max(hit["relevance"], 0.0), 1.0),
                                    text=f"Relevance {hit['relevance']:.0%}",
                                )
                                if hit.get("url"):
                                    st.markdown(f"[Source link]({hit['url']})")

                    # Cache-only probe first: coverage already fetched for this
                    # program renders on arrival, and only a genuinely new
                    # lookup costs anything. Grounded results are per-user by
                    # design, so this reads only your own history.
                    news = enricher.find_open_source_hits(
                        sel["name"], sel["pe_number"], sel["agency"],
                        user_id=uid, allow_fresh=False,
                    )
                    if news.cold:
                        st.caption(
                            "No saved coverage for this program yet."
                        )
                        if st.button("Search recent coverage "
                                     "(AI + Google Search)"):
                            with st.spinner(
                                    "Searching news and public sources..."):
                                news = enricher.find_open_source_hits(
                                    sel["name"], sel["pe_number"],
                                    sel["agency"], user_id=uid,
                                    allow_fresh=True,
                                )
                            render_ai_result(news, render_hits,
                                             "No recent coverage found.")
                    else:
                        render_ai_result(news, render_hits,
                                         "No recent coverage found.")
                        if st.button("Refresh coverage (AI + Google Search)"):
                            with st.spinner("Searching for newer coverage..."):
                                fresh = enricher.find_open_source_hits(
                                    sel["name"], sel["pe_number"],
                                    sel["agency"], user_id=uid,
                                    allow_fresh=True, force=True,
                                )
                            # A refused refresh must say so rather than
                            # silently re-showing the old answer.
                            if fresh.blocked:
                                st.info(fresh.message)
                            else:
                                st.rerun()

# ═══════════════════════════ Rhetoric vs. Budget ═════════════════════════════
with tab_rhetoric:
    st.header("Rhetoric vs. budget")
    st.markdown(
        "Did the money follow the talk? What was requested, what the "
        "authorizing committees actually authorized, and the reason they "
        "printed for the change — plus, optionally, how loudly the program "
        "was being talked about."
    )

    rq = st.text_input(
        "Program to analyze", key="rhetoric_query",
        placeholder="e.g. launched effects",
    )
    if rq:
        with st.spinner("Finding the program..."):
            linker = load_matching_models()
            rres = linker.link_query(rq)
        if not rres["matched_pe_id"]:
            st.warning("No program match — try another name or a PE number.")
        else:
            rcands = rres["candidates"]
            rlabels = [
                f"PE {c['pe_number']} — {c['name'][:45]} [{c['agency']}]"
                for c in rcands
            ]
            picked = st.multiselect(
                "Programs to aggregate (related PEs sum into one "
                "funding series)",
                rlabels, default=rlabels[:1], key="rhet_pes",
            )
            yr_lo, yr_hi = st.slider(
                "Analysis window", 2015, 2026, (2020, 2026),
                key="rhet_years",
            )
            sel_cands = [rcands[rlabels.index(l)] for l in picked]
            display_name = sel_cands[0]["name"] if sel_cands else ""

            # ── What Congress actually did ────────────────────────────────
            # Exact join against authorizing-committee reports. Public-domain
            # source, no API key, no AI — so this renders on the free tier and
            # costs nothing per user, unlike the grounded signal below.
            if sel_cands:
                from analysis.congressional_actions import (
                    CongressionalActions, coverage_note,
                    headline as ca_headline, summarize as ca_summarize,
                )

                st.subheader("What Congress authorized")
                with SessionFactory() as session:
                    ca = CongressionalActions(session)
                    ca_pes = [c["pe_number"] for c in sel_cands]
                    ca_agencies = [c["agency"] for c in sel_cands]
                    ca_series = ca.get_program_series(ca_pes, ca_agencies)
                    ca_rows = ca.get_actions(ca_pes, ca_agencies)

                # House and Senate score the same request separately, so one
                # chamber is chosen BEFORE anything is totalled. Summing both
                # would report roughly double the real dollars.
                if not ca_series.is_empty():
                    chambers = sorted(ca_series["chamber"].unique().to_list())
                    chamber_pick = chambers[0]
                    if len(chambers) > 1:
                        chamber_pick = st.radio(
                            "Chamber", chambers, horizontal=True,
                            key="rhet_chamber",
                            help="Each chamber's committee scores the same "
                                 "request on its own; the two are never added "
                                 "together.",
                        )
                    ca_series = ca_series.filter(
                        pl.col("chamber") == chamber_pick)
                    ca_rows = ca_rows.filter(pl.col("chamber") == chamber_pick)

                ca_sum = ca_summarize(ca_series)
                st.markdown(ca_headline(display_name, ca_sum))

                if ca_sum["years_covered"]:
                    cdf = ca_series.to_pandas()

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Requested",
                              f"${ca_sum['total_requested_m']:,.1f}M")
                    c2.metric("Authorized",
                              f"${ca_sum['total_authorized_m']:,.1f}M")
                    c3.metric(
                        "Committee change",
                        f"${ca_sum['net_delta_m']:+,.1f}M",
                        delta=(f"{ca_sum['net_delta_pct']:+.1f}%"
                               if ca_sum["net_delta_pct"] is not None else None),
                    )
                    c4.metric("Years on record",
                              f"{ca_sum['years_covered']}")

                    # The delta is the story: requested and authorized differ
                    # by a few percent, so plotting them side by side would
                    # bury the signal in two near-identical bars. Diverging
                    # bar instead — sign carried by position AND hue.
                    cdf["direction"] = [
                        "Committee increase" if v is not None and v >= 0
                        else "Committee cut"
                        for v in cdf["delta_m"]
                    ]
                    zero_rule = (
                        alt.Chart(pd.DataFrame({"y": [0]}))
                        .mark_rule(color="#c9c7c2", strokeWidth=1)
                        .encode(y="y:Q")
                    )
                    delta_bars = (
                        alt.Chart(cdf)
                        .mark_bar(cornerRadiusEnd=4, size=28)
                        .encode(
                            x=alt.X("fiscal_year:O", title="Fiscal Year"),
                            y=alt.Y("delta_m:Q",
                                    title="Committee change $M"),
                            color=alt.Color(
                                "direction:N",
                                scale=alt.Scale(
                                    domain=["Committee increase",
                                            "Committee cut"],
                                    range=["#2a78d6", "#e34948"]),
                                legend=alt.Legend(title=None, orient="top"),
                            ),
                            tooltip=[
                                alt.Tooltip("fiscal_year:O", title="FY"),
                                alt.Tooltip("chamber:N", title="Chamber"),
                                alt.Tooltip("request_m:Q", format=",.1f",
                                            title="Requested $M"),
                                alt.Tooltip("authorized_m:Q", format=",.1f",
                                            title="Authorized $M"),
                                alt.Tooltip("delta_m:Q", format="+,.1f",
                                            title="Change $M"),
                                alt.Tooltip("rationale_text:N",
                                            title="Stated reason"),
                            ],
                        )
                        .properties(height=220)
                    )
                    st.altair_chart(zero_rule + delta_bars,
                                    use_container_width=True)

                    biggest = ca_sum["largest_cut"] or ca_sum["largest_add"]
                    if biggest and biggest.get("rationale"):
                        st.caption(
                            f"Largest single-year change — FY"
                            f"{biggest['fiscal_year']}, "
                            f"${biggest['amount_m']:+,.1f}M: "
                            f"{biggest['rationale']}"
                        )

                    with st.expander("Line-by-line committee actions"):
                        st.dataframe(
                            ca_rows.to_pandas()[[
                                "fiscal_year", "chamber", "pe_number",
                                "program_title", "budget_activity_title",
                                "request_k", "committee_delta_k",
                                "authorized_k", "rationale",
                                "report_citation",
                            ]],
                            use_container_width=True, hide_index=True,
                            column_config={
                                "fiscal_year": "FY",
                                "chamber": "Chamber",
                                "pe_number": "PE",
                                "program_title": "Program",
                                "budget_activity_title": "Budget activity",
                                "request_k": st.column_config.NumberColumn(
                                    "Requested $K", format="%,.0f"),
                                "committee_delta_k": st.column_config
                                    .NumberColumn("Change $K", format="%+,.0f"),
                                "authorized_k": st.column_config.NumberColumn(
                                    "Authorized $K", format="%,.0f"),
                                "rationale": "Stated reason",
                                "report_citation": "Report",
                            },
                        )
                st.caption(coverage_note())

            # ── Optional AI layer: open-source emphasis ───────────────────
            st.divider()
            st.subheader("Open-source emphasis (AI)")
            enricher_r = get_enricher()
            if enricher_r is None:
                st.caption(
                    "Optional — set the GEMINI_API_KEY environment variable "
                    "and restart to add an AI-characterized signal for how "
                    "much the program was publicly discussed. The "
                    "congressional figures above need no key."
                )
            elif not sel_cands:
                st.caption("Select at least one program element above.")
            else:
                rkey = (
                    "rhet::" + "|".join(sorted(c["pe_number"] for c in sel_cands))
                    + f"::{yr_lo}-{yr_hi}"
                )
                # Semi-automatic, same rule as the other AI panels: an analysis
                # this program and window has had before renders on arrival;
                # only a new combination costs a call. This one is the most
                # expensive AI action in the app — a multi-year grounded
                # research prompt fires several billable search queries — so
                # never run it implicitly.
                uid_r = current_user_id()
                sig_res = enricher_r.annual_signal(
                    sel_cands[0]["name"],
                    [c["pe_number"] for c in sel_cands],
                    yr_lo, yr_hi, user_id=uid_r, allow_fresh=False,
                )
                label = ("Analyze open-source signal (AI + web search)"
                         if sig_res.cold
                         else "Re-run analysis (AI + web search)")
                if st.button(label):
                    was_cold = sig_res.cold
                    with st.spinner(
                            "Characterizing public statements by year..."):
                        sig_res = enricher_r.annual_signal(
                            sel_cands[0]["name"],
                            [c["pe_number"] for c in sel_cands],
                            yr_lo, yr_hi, user_id=uid_r, allow_fresh=True,
                            force=not was_cold,
                        )
                if sig_res.blocked:
                    st.info(sig_res.message)
                elif not sig_res.grounded:
                    st.warning(
                        "The web search didn't run for this program, so "
                        "there's no sourced basis for a rhetoric signal. "
                        "Rather than correlate funding against numbers the "
                        "model recalled, this shows nothing. Try a "
                        "higher-profile program or a narrower year window."
                    )
                if sig_res.search_suggestions_html:
                    st.html(sig_res.search_suggestions_html)
                if sig_res.cached and sig_res.created_at:
                    st.caption(f"Saved analysis from "
                               f"{sig_res.created_at:%Y-%m-%d}.")

                # None means "nothing to render here" - a cold panel shows its
                # button, and a refused call already showed the governor's
                # message, so neither should fall through to the "could not
                # characterize this program" note below.
                sig_rows = (sig_res.payload
                            if not sig_res.cold and not sig_res.blocked
                            and sig_res.grounded else None)
                if sig_rows is not None:
                    if not sig_rows:
                        st.info(
                            "The AI could not characterize open-source "
                            "coverage for this program and window — usually "
                            "a very low-visibility program."
                        )
                    else:
                        from analysis.rhetoric_tracker import (
                            align_rhetoric_funding, headline_sentence,
                        )
                        signal = pd.DataFrame(sig_rows)
                        with SessionFactory() as session:
                            tracker = TrendTracker(session)
                            frames = [
                                tracker.get_pe_history(
                                    c["pe_number"], c["agency"]
                                ).to_pandas()
                                for c in sel_cands
                            ]
                        frames = [f for f in frames if not f.empty]
                        funding = (
                            pd.concat(frames)[["fiscal_year", "amount_thousands"]]
                            if frames else
                            pd.DataFrame(columns=["fiscal_year",
                                                  "amount_thousands"])
                        )
                        funding = funding[funding["fiscal_year"] >= yr_lo]

                        r = align_rhetoric_funding(signal, funding)
                        st.markdown(headline_sentence(display_name, r,
                                                      yr_lo, yr_hi))

                        a = r["alignment"]
                        m1, m2, m3, m4 = st.columns(4)
                        if r["mention_trend_pct"] not in (None, float("inf")):
                            m1.metric("Mention trend",
                                      f"{r['mention_trend_pct']:+.0f}%")
                        if r["positive_share"] is not None:
                            m2.metric("Favorable statements",
                                      f"{r['positive_share']:.0f}%")
                        if r["funding_cagr_pct"] is not None:
                            m3.metric("Funding CAGR",
                                      f"{r['funding_cagr_pct']:+.1f}%/yr")
                        if a:
                            m4.metric(
                                "Alignment", f"{a['coefficient']:+.2f}",
                                help=(f"Spearman ρ at a {a['lead_years']}-year "
                                      f"funding lead, n={a['n_years']} years. "
                                      f"All leads: {a['by_lead']}"),
                            )

                        fund_year = (
                            funding.groupby("fiscal_year", as_index=False)
                            ["amount_thousands"].sum()
                        )
                        fund_year["amount_m"] = fund_year["amount_thousands"] / 1e3
                        fund_year = fund_year[fund_year["fiscal_year"] <= yr_hi + 2]
                        top_chart = (
                            alt.Chart(fund_year)
                            .mark_line(color="#2a78d6", strokeWidth=2,
                                       point=alt.OverlayMarkDef(filled=True,
                                                                size=60,
                                                                color="#2a78d6"))
                            .encode(
                                x=alt.X("fiscal_year:O", title=None),
                                y=alt.Y("amount_m:Q", title="Funding $M"),
                                tooltip=[
                                    alt.Tooltip("fiscal_year:O", title="FY"),
                                    alt.Tooltip("amount_m:Q", format=",.1f",
                                                title="$M"),
                                ],
                            )
                            .properties(height=200)
                        )
                        bottom_chart = (
                            alt.Chart(signal)
                            .mark_line(color="#eb6834", strokeWidth=2,
                                       point=alt.OverlayMarkDef(filled=True,
                                                                size=60,
                                                                color="#eb6834"))
                            .encode(
                                x=alt.X("fiscal_year:O", title="Fiscal Year"),
                                y=alt.Y("mention_intensity:Q",
                                        scale=alt.Scale(domain=[0, 10]),
                                        title="Mention intensity (AI, 0–10)"),
                                tooltip=[
                                    alt.Tooltip("fiscal_year:O", title="FY"),
                                    alt.Tooltip("mention_intensity:Q",
                                                title="Intensity"),
                                    alt.Tooltip("positive_pct:Q",
                                                title="Favorable %"),
                                    alt.Tooltip("negative_pct:Q",
                                                title="Critical %"),
                                    alt.Tooltip("notable_statement:N",
                                                title="Notable statement"),
                                ],
                            )
                            .properties(height=160)
                        )
                        st.altair_chart(alt.vconcat(top_chart, bottom_chart),
                                        use_container_width=True)

                        merged = r["merged"].copy()
                        merged["statement"] = merged.apply(
                            lambda row: (f"{row['notable_statement']} "
                                         f"({row['statement_source']})"
                                         if row["notable_statement"] else ""),
                            axis=1,
                        )
                        st.dataframe(
                            merged[["fiscal_year", "mention_intensity",
                                    "positive_pct", "stated_priority",
                                    "amount_m", "yoy_pct", "statement"]],
                            use_container_width=True, hide_index=True,
                            column_config={
                                "fiscal_year": "FY",
                                "mention_intensity": st.column_config
                                    .NumberColumn("Intensity", format="%.0f"),
                                "positive_pct": st.column_config
                                    .NumberColumn("Favorable %", format="%.0f"),
                                "stated_priority": "Named a priority",
                                "amount_m": st.column_config
                                    .NumberColumn("Funding $M", format="%.1f"),
                                "yoy_pct": st.column_config
                                    .NumberColumn("YoY %", format="%+.1f"),
                                "statement": "Notable statement",
                            },
                        )

            with st.expander("Methodology & caveats"):
                st.markdown(
                    "- **Congressional figures are an exact join**, parsed "
                    "from the RDT&E funding tables printed in HASC/SASC NDAA "
                    "committee reports — requested, the committee's change, "
                    "authorized, and the reason the committee printed. Not "
                    "inferred, not AI. Coverage begins at FY2012 because "
                    "earlier reports print those tables as images.\n"
                    "- A program element can carry **several lines in one "
                    "report**, one per budget activity; those are summed per "
                    "fiscal year. House and Senate score the same request "
                    "separately and are never pooled.\n"
                    "- Authorization is not appropriation — a committee can "
                    "authorize money that is never appropriated.\n"
                    "- **The open-source signal is an AI estimate**, grounded "
                    "in web search — not a media-analytics mention count. "
                    "Intensity is relative to the program's own baseline.\n"
                    "- **Alignment coefficient** = Spearman rank correlation "
                    "between annual mention intensity and annual funding, "
                    "evaluated at 0, 1, and 2-year funding leads (budgets are "
                    "written 1–2 years after the rhetoric); the strongest "
                    "lead is reported.\n"
                    "- With at most a handful of years, treat the coefficient "
                    "as directional, not precise. Coverage bias: recent years "
                    "are better documented online than older ones.\n"
                    "- Funding series = discretionary figures for the "
                    "selected PEs (actuals, then enacted, then request)."
                )

# ═══════════════════════════════ Data Coverage ═══════════════════════════════
with tab_coverage:
    st.header("What this tool covers")
    stats = fetch_coverage_stats()
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Programs tracked", f"{stats['programs']:,}")
    s2.metric("Funding lines",
              f"{stats['funding_lines']:,}",
              help=f"FY{stats['fy_min']}–FY{stats['fy_max']}")
    s3.metric("Programs with narratives", f"{stats['narrative_pes']:,}")
    s4.metric("Work line items", f"{stats['accomplishments']:,}")

    try:
        from analysis.ai_budget import SpendLedger
        used = SpendLedger.fresh_calls_this_month(current_user_id())
        allowance = config_module.AI_FREE_CREDITS_PER_MONTH
        if allowance is not None:
            st.caption(f"Fresh AI lookups used this month: "
                       f"{used} of {allowance}. Saved analysis is unlimited.")
    except Exception:
        pass

    st.markdown(f"""
| Source | Coverage | How it's used |
|---|---|---|
| **R-1 budget exhibits** (comptroller.war.gov) | FY1998–FY2027 requests; FY2026 enacted. Official XLSX for FY2012+; parsed PDFs before that | Funding trends and program funding histories (local database) |
| **R-2 justification books** (official XML) | Defense-Wide components, PB2026–PB2027: {stats['narratives']:,} narratives, {stats['accomplishments']:,} accomplishment line items | Mission descriptions and "Plans & Work"; also sharpens program matching |
| **USAspending.gov** (live queries) | Prime awards (contracts + grants/cooperative agreements), subawards, account-level obligations | "Contracts & Awards" and "Who got paid" |
| **AI enrichment** (optional) | Google-grounded search and match resolution | "In the News", "Rhetoric vs. Budget", and ambiguity resolution |

**Known blind spots — an empty result is often one of these, not an error:**

- **Award ↔ program linkage doesn't exist in public data.** Award records carry no program-element field, so the Contracts & Awards search is keyword matching against award descriptions. Awards described generically won't surface.
- **Umbrella vehicles hide task detail.** Work under PIAs, OTAs, and IDIQ task orders often posts under a generic umbrella description; the subaward search catches some, not all.
- **Other Transactions** are not a searchable instrument group in the USAspending API.
- **Timing:** DoD awards post with a ~90-day display delay, and the current fiscal year is always partial.
- **Service justification books** (Army, Navy, Air Force) are published as PDF only — narratives currently cover Defense-Wide components. FY2025-and-earlier books are also PDF-only. Two broken links upstream: MDA's PB2027 and CYBERCOM's PB2026 XML (each covered by the other cycle).
- **Classified programs** appear only as aggregate lines; the Intelligence Community publishes topline figures only.

**How the AI features are stored and metered**

- **Match resolution is shared.** It doesn't use web search, so once one person resolves an ambiguous name, everyone else's identical search resolves instantly and for free.
- **Web-grounded results are yours alone.** "In the News" and "Rhetoric vs. Budget" run against Google Search, and Google's API terms allow those results to be shown only to the person who asked for them. They're saved to your own history, never pooled, and always displayed with Google's Search Suggestions.
- **Fresh lookups are metered**, so a busy month can't run up an unbounded bill. Anything already analyzed keeps loading normally even after the allowance runs out.
""")
