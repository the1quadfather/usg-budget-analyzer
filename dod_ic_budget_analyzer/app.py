"""
app.py

Streamlit interface for the DoD Budget Explorer.

Information architecture: four tabs organized around analyst questions,
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

import os
from pathlib import Path

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

import config as config_module
from storage.db import get_engine, get_session_factory
from matching.fuzzy_matcher import ProgramMatcher
from analysis.program_linker import ProgramLinker
from analysis.provenance import (
    csv_with_provenance,
    execution_sources,
    funding_sources,
    source_summary,
    xlsx_with_provenance,
)
from analysis.trend_tracker import TrendTracker
from analysis.text_render import escape_dollars
from analysis import primer
from analysis.user_identity import streamlit_user_id

# --- Configuration & State Setup ---
st.set_page_config(page_title="DoD Budget Explorer", layout="wide")

# Streamlit renders captions in ~60%-opacity grey and hides `help=` text
# behind a 12px "?" icon. Analysts read those lines for units, dollar basis,
# and coverage caveats, so raise their contrast and make the icon findable.
# Selectors are Streamlit's stable data-testid hooks, not generated classes.
st.markdown(
    """
    <style>
    [data-testid="stCaptionContainer"] p,
    [data-testid="stCaptionContainer"] {
        color: var(--text-color);
        opacity: 0.86;
        font-size: 0.92rem;
        line-height: 1.45;
    }
    [data-testid="stTooltipIcon"] svg,
    [data-testid="stTooltipHoverTarget"] svg {
        width: 1.05rem;
        height: 1.05rem;
        color: #2a78d6;
    }
    [data-testid="stTooltipContent"],
    [data-testid="stTooltipContent"] p {
        font-size: 0.95rem;
        line-height: 1.4;
        max-width: 28rem;
    }
    [data-testid="stMetricDelta"] svg {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _demo_allowed_emails() -> set[str]:
    """Optional deployment allowlist from environment or Streamlit Secrets."""
    raw = os.getenv("DEMO_ALLOWED_EMAILS", "")
    values: list[str] = raw.split(",") if raw else []
    try:
        secret_values = st.secrets.get("demo_allowed_emails", [])
        if isinstance(secret_values, str):
            values.extend(secret_values.split(","))
        else:
            values.extend(secret_values)
    except Exception:
        pass
    return {value.strip().lower() for value in values if value.strip()}


_allowed_emails = _demo_allowed_emails()
if _allowed_emails:
    if not getattr(st.user, "is_logged_in", False):
        st.title("Private demo")
        st.info("Sign in with an approved email address to continue.")
        if st.button("Sign in"):
            st.login()
        st.stop()
    viewer_email = str(getattr(st.user, "email", "")).strip().lower()
    if viewer_email not in _allowed_emails:
        st.error("This account is not authorized for the demo.")
        if st.button("Sign out"):
            st.logout()
        st.stop()


def _query_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read a bounded integer from the URL without trusting its contents."""
    try:
        return max(minimum, min(maximum, int(st.query_params.get(name, default))))
    except (TypeError, ValueError):
        return default


def _sync_trend_url() -> None:
    st.query_params.update(
        tab="trends",
        start=st.session_state["trend_start"],
        end=st.session_state["trend_end"],
    )


def _sync_finder_url() -> None:
    st.query_params["tab"] = "finder"


def _sync_rhetoric_url() -> None:
    st.query_params["tab"] = "rhetoric"
    if "rhetoric_query" in st.session_state:
        st.query_params["rq"] = st.session_state["rhetoric_query"]
    if "rhet_years" in st.session_state:
        start, end = st.session_state["rhet_years"]
        st.query_params.update(rstart=start, rend=end)


def _sync_profile_view(view: str) -> None:
    st.query_params.update(tab="finder", view=view)


def _sync_main_tab_url() -> None:
    """Mirror the tracked, stable tab selection into the shareable URL."""
    keys_by_label = {
        "Budget Trends": "trends",
        "Program Finder": "finder",
        "Rhetoric vs. Budget": "rhetoric",
        "Data Coverage": "coverage",
    }
    selected = st.session_state.get("main_tab")
    if selected in keys_by_label:
        st.query_params["tab"] = keys_by_label[selected]


def _sync_profile_tab_url(state_key: str) -> None:
    """Mirror a tracked program-profile tab into the shareable URL."""
    keys_by_label = {
        "Funding": "funding",
        "Plans & Work": "plans",
        "Contracts & Awards": "awards",
        "In the News": "news",
    }
    selected = st.session_state.get(state_key)
    if selected in keys_by_label:
        st.query_params.update(tab="finder", view=keys_by_label[selected])


def _sync_dollar_url() -> None:
    st.query_params["dollars"] = (
        "constant-2025"
        if st.session_state["dollar_basis"] == "Constant FY2025"
        else "then-year"
    )

# Anchor the DB path to this file so the app works from any working directory
DB_PATH = f"sqlite:///{(Path(__file__).parent / 'data' / 'processed' / 'usg_budgets.db').as_posix()}"

@st.cache_resource
def init_db_connection():
    engine = get_engine(DB_PATH)
    return get_session_factory(engine)


@st.cache_resource
def load_lexical_linker():
    """Build the fast matcher without importing the transformer stack."""
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        fuzzy = ProgramMatcher(session)
    return ProgramLinker(
        fuzzy, None, fuzzy_threshold=80.0, semantic_threshold=0.45
    )


@st.cache_resource
def load_lexical_linker():
    """Build the fast matcher without importing the transformer stack."""
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        fuzzy = ProgramMatcher(session)
    return ProgramLinker(
        fuzzy, None, fuzzy_threshold=80.0, semantic_threshold=0.45
    )


@st.cache_resource
def load_matching_models():
    """
    Builds the linker once per process. Loaded lazily (first search), and
    degrades to lexical-only matching if the PyTorch stack is unavailable.
    """
    lexical = load_lexical_linker()
    SessionFactory = init_db_connection()
    semantic = None
    with SessionFactory() as session:
        try:
            from matching.semantic_matcher import SemanticMatcher
            semantic = SemanticMatcher(session)
        except Exception as e:
            st.warning(
                f"Semantic matching unavailable ({type(e).__name__}) — "
                "running name-similarity matching only."
            )
    return ProgramLinker(
        lexical.fuzzy,
        semantic,
        fuzzy_threshold=80.0, semantic_threshold=0.45,
    )


def link_program_query(query: str) -> dict:
    """Avoid loading the transformer for exact or decisive lexical hits."""
    lexical_result = load_lexical_linker().link_query(query)
    candidates = lexical_result.get("candidates", [])
    if candidates:
        top = candidates[0]
        if top["strategy"] == "PE_NUMBER" or top["score"] >= 0.95:
            return lexical_result
    return load_matching_models().link_query(query)

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
    Who to bill, and whose grounded history to read.

    Authenticated users have a durable identity. Anonymous users receive a
    random identity scoped to their Streamlit session so two visitors can
    never read one another's grounded-result history. The global dollar cap
    remains the backstop when a new anonymous session receives fresh credits.
    """
    return streamlit_user_id(st)


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
            "execution_rows": "SELECT COUNT(*) FROM pe_execution",
            "execution_fy_min": "SELECT MIN(fy_start) FROM pe_execution",
            "execution_fy_max": "SELECT MAX(fy_start) FROM pe_execution",
            "execution_files": (
                "SELECT COUNT(DISTINCT source_document_id) FROM pe_execution"
            ),
        }.items():
            try:
                stats[key] = c.execute(text(q)).scalar() or 0
            except Exception:
                stats[key] = 0
        try:
            rows = c.execute(text(
                "SELECT agency, COUNT(DISTINCT pe_number), "
                "MIN(fiscal_year), MAX(fiscal_year) "
                "FROM pe_narratives GROUP BY agency ORDER BY agency"
            )).all()
            stats["narrative_by_agency"] = {
                agency: {
                    "programs": int(programs),
                    "first_fy": int(first_fy),
                    "last_fy": int(last_fy),
                }
                for agency, programs, first_fy, last_fy in rows
            }
        except Exception:
            stats["narrative_by_agency"] = {}
    return stats


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_funding_sources(
    pe_numbers: tuple[str, ...] = (),
    agencies: tuple[str, ...] = (),
    fiscal_years: tuple[int, int] | None = None,
) -> list[dict]:
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        return funding_sources(
            session,
            pe_numbers=pe_numbers or None,
            agencies=agencies or None,
            fiscal_years=fiscal_years,
        )


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_execution_data(
    pe_numbers: tuple[str, ...], agencies: tuple[str, ...]
) -> tuple[pd.DataFrame, list[dict]]:
    from analysis.execution_view import ExecutionView
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        frame = ExecutionView(session).latest_program_series(
            list(pe_numbers), list(agencies)
        )
        sources = execution_sources(
            session, pe_numbers=pe_numbers, agencies=agencies
        )
    return (
        frame.to_pandas() if not frame.is_empty() else pd.DataFrame(),
        sources,
    )


def render_primer(title: str, body: str, *, expanded: bool = False) -> None:
    """A collapsed plain-language explainer placed next to the numbers."""
    with st.expander(title, expanded=expanded):
        st.markdown(escape_dollars(body))


def render_provenance(sources: list[dict]) -> None:
    st.caption(source_summary(sources))
    links = [
        f"[{source['filename']}]({source['source_url']})"
        for source in sources
        if source.get("source_url")
    ]
    if links:
        with st.expander("Source documents"):
            st.markdown("  \n".join(links))


def render_table_downloads(
    data: pd.DataFrame,
    *,
    name: str,
    key: str,
    sources: list[dict],
) -> None:
    """Offer both portable and analyst-friendly exports with provenance."""
    safe_name = name.replace(" ", "_").lower()
    csv_col, xlsx_col, _ = st.columns([1, 1, 4])
    csv_col.download_button(
        "Download CSV",
        csv_with_provenance(data, sources),
        file_name=f"{safe_name}.csv",
        mime="text/csv",
        key=f"csv::{key}",
    )
    xlsx_col.download_button(
        "Download XLSX",
        xlsx_with_provenance(data, sources),
        file_name=f"{safe_name}.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        key=f"xlsx::{key}",
    )

@st.cache_data(ttl=3600, show_spinner=False)
def congressional_year_bounds() -> tuple[int, int]:
    """First and last fiscal year with a stored committee action."""
    from analysis.congressional_actions import CongressionalActions
    SessionFactory = init_db_connection()
    with SessionFactory() as session:
        return CongressionalActions(session).fiscal_year_bounds()

# --- Chart styling (validated reference palette) ---

BASIS_COLORS = alt.Scale(
    domain=["Actual", "Enacted/CY", "Request"],
    range=["#2a78d6", "#1baf7a", "#eb6834"],
)
STRATEGY_LABELS = {
    "FUZZY": "Name similarity",
    "SEMANTIC": "Meaning (local model)",
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


def execution_waterfall(row: pd.Series) -> alt.Chart:
    """Request → enacted → adjustments → net, with oversight types distinct."""
    request = float(row["request_k"] or 0) / 1e3
    enacted = float(row["enacted_k"] or 0) / 1e3
    steps = [
        ("Request", request, "Request / net"),
        ("Enacted change", enacted - request, "Congressional change"),
        ("Statutory", float(row["statutory_adj_k"] or 0) / 1e3,
         "Other adjustment"),
        ("Suppl./rescission", float(row["suppl_resc_seq_k"] or 0) / 1e3,
         "Other adjustment"),
        ("Other", float(row["other_adj_k"] or 0) / 1e3,
         "Other adjustment"),
        ("Above-threshold", float(row["above_threshold_reprog_k"] or 0) / 1e3,
         "Prior-approval reprogramming"),
        ("Below-threshold", float(row["below_threshold_reprog_k"] or 0) / 1e3,
         "Below-threshold reprogramming"),
    ]
    records = []
    running = 0.0
    for index, (label, change, kind) in enumerate(steps):
        start = running
        end = change if index == 0 else running + change
        records.append({
            "step": label,
            "order": index,
            "start": min(start, end),
            "end": max(start, end),
            "change": change,
            "kind": kind,
        })
        running = end
    net = float(row["net_k"] or 0) / 1e3
    records.append({
        "step": "Net current program", "order": len(records),
        "start": 0.0, "end": net, "change": net,
        "kind": "Request / net",
    })
    frame = pd.DataFrame(records)
    order = frame["step"].tolist()
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadius=2)
        .encode(
            x=alt.X("step:N", sort=order, title=None,
                    axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("start:Q", title="$ Millions of budget authority"),
            y2="end:Q",
            color=alt.Color(
                "kind:N",
                scale=alt.Scale(
                    domain=[
                        "Request / net", "Congressional change",
                        "Other adjustment", "Prior-approval reprogramming",
                        "Below-threshold reprogramming",
                    ],
                    range=["#2a78d6", "#1baf7a", "#898781", "#e34948", "#eda100"],
                ),
                title=None,
            ),
            tooltip=[
                alt.Tooltip("step:N", title="Step"),
                alt.Tooltip("change:Q", format="+,.1f", title="$M change/total"),
            ],
        )
        .properties(height=300)
    )


EXECUTION_FYS = list(range(2018, 2027))

SessionFactory = init_db_connection()

# --- UI Layout ---
st.title("🇺🇸 DoD Budget Explorer")
dollar_basis = st.radio(
    "R-1 funding dollar basis",
    ["Then-year", "Constant FY2025"],
    index=(
        1 if st.query_params.get("dollars") == "constant-2025" else 0
    ),
    horizontal=True,
    key="dollar_basis",
    on_change=_sync_dollar_url,
    help=(
        "Constant dollars use the RDT&E-specific DoD Green Book TOA "
        "deflator—not CPI or the GDP deflator."
    ),
)
constant_dollars = dollar_basis == "Constant FY2025"


def include_deflator_source(sources: list[dict]) -> list[dict]:
    if not constant_dollars:
        return sources
    from analysis.deflators import provenance_record
    return [*sources, provenance_record()]

tab_definitions = [
    ("trends", "Budget Trends"),
    ("finder", "Program Finder"),
    ("rhetoric", "Rhetoric vs. Budget"),
    ("coverage", "Data Coverage"),
]
requested_tab = st.query_params.get("tab", "trends")
if requested_tab not in {key for key, _ in tab_definitions}:
    requested_tab = "trends"
tab_labels = [label for _, label in tab_definitions]
default_tab = dict(tab_definitions)[requested_tab]
# Keep label/container order immutable. Reordering this list across reruns
# causes Streamlit's index-keyed frontend panels to retain the old selection,
# which maps one tab's content under another tab's label.
tab_containers = st.tabs(
    tab_labels,
    default=default_tab,
    key="main_tab",
    on_change=_sync_main_tab_url,
)
tabs_by_key = {
    key: container
    for (key, _), container in zip(tab_definitions, tab_containers)
}
tab_trends = tabs_by_key["trends"]
tab_finder = tabs_by_key["finder"]
tab_rhetoric = tabs_by_key["rhetoric"]
tab_coverage = tabs_by_key["coverage"]

# ═══════════════════════════════ Budget Trends ═══════════════════════════════
with tab_trends:
    st.header("RDT&E topline by component")
    trend_start_default = _query_int("start", 2010, 1996, 2026)
    trend_end_default = _query_int("end", 2027, 1997, 2027)
    if trend_start_default >= trend_end_default:
        trend_start_default, trend_end_default = 2010, 2027
    col1, col2 = st.columns(2)
    start_yr = col1.slider(
        "Start Year", 1996, 2026, trend_start_default,
        key="trend_start", on_change=_sync_trend_url,
    )
    end_yr = col2.slider(
        "End Year", 1997, 2027, trend_end_default,
        key="trend_end", on_change=_sync_trend_url,
    )

    df_trends = fetch_agency_trends(start_yr, end_yr)
    trend_sources = fetch_funding_sources(fiscal_years=(start_yr, end_yr))
    trend_sources = include_deflator_source(trend_sources)
    if df_trends.empty:
        st.info("No funding data for that year range.")
    else:
        year_cols = [c for c in df_trends.columns if c.isdigit()]
        long = df_trends.melt(
            id_vars=["agency"], value_vars=year_cols,
            var_name="fiscal_year", value_name="amount_k",
        )
        if constant_dollars:
            from analysis.deflators import apply_deflator
            long["amount_k"] = apply_deflator(
                long, amount_column="amount_k"
            )
        long["amount_b"] = long["amount_k"] / 1e6
        long["fiscal_year"] = long["fiscal_year"].astype(int)
        long = long[long["amount_b"] > 0]

        trend_chart = (
            alt.Chart(long)
            .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(filled=True, size=45))
            .encode(
                x=alt.X("fiscal_year:O", title="Fiscal Year"),
                y=alt.Y(
                    "amount_b:Q",
                    title=(
                        "$ Billions (constant FY2025)"
                        if constant_dollars else "$ Billions (then-year)"
                    ),
                ),
                color=alt.Color("agency:N", scale=AGENCY_COLORS, title="Component"),
                tooltip=[
                    alt.Tooltip("agency:N", title="Component"),
                    alt.Tooltip("fiscal_year:O", title="FY"),
                    alt.Tooltip("amount_b:Q", format=",.1f", title="$B"),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(trend_chart, width="stretch")
        st.caption(
            "Each year shows its most reliable figure: reported actuals, then "
            "enacted, then the budget request. Discretionary only — "
            "reconciliation/mandatory funds are tracked separately. "
            + (
                "Amounts use the RDT&E-specific FY2025 Green Book deflator."
                if constant_dollars else "Amounts are then-year dollars."
            )
        )
        render_provenance(trend_sources)
        with st.expander("Data table"):
            trend_table = df_trends.copy()
            if constant_dollars:
                from analysis.deflators import convert_amount
                for column in [c for c in trend_table.columns if c.isdigit()]:
                    trend_table[column] = trend_table[column].apply(
                        lambda amount, year=int(column): convert_amount(
                            amount, year
                        )
                    )
            st.dataframe(trend_table, width="stretch", hide_index=True)
            render_table_downloads(
                trend_table,
                name=f"rdte_component_trends_fy{start_yr}_{end_yr}",
                key=f"trends::{start_yr}::{end_yr}",
                sources=trend_sources,
            )

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
            st.altair_chart(money_bar(breakdown, "name"), width="stretch")
            st.caption(
                f"Top {len(breakdown)} by contract obligations, "
                f"{exec_comp} RDT&E account, FY{exec_fy}. DoD awards post "
                "with a ~90-day delay; the current fiscal year is partial."
            )
            usa_source = [{
                "filename": "USAspending.gov live API query",
                "document_type": "USAspending API",
                "publication_year": exec_fy,
                "source_url": "https://api.usaspending.gov/",
                "retrieved_at": None,
                "processed_date": None,
            }]
            render_provenance(usa_source)
            render_table_downloads(
                breakdown,
                name=f"{exec_comp}_rdte_obligations_fy{exec_fy}_{exec_dim}",
                key=f"breakdown::{exec_comp}::{exec_fy}::{exec_dim}",
                sources=usa_source,
            )

# ═══════════════════════════════ Program Finder ══════════════════════════════
with tab_finder:
    st.header("Find a program")
    linked_pe = st.query_params.get("pe", "")
    query = st.text_input(
        "Search — program name, quote from an article, or PE number",
        value=(f"PE {linked_pe}" if linked_pe else ""),
        placeholder='e.g. "launched effects", DARPA Tactical Technology, 0602345A',
        key="program_query",
        on_change=_sync_finder_url,
    )

    if query:
        with st.spinner("Searching programs..."):
            result = link_program_query(query)

        # Log demand once per query, not once per rerun: every widget click
        # anywhere in the app re-executes this block while the box is filled.
        if st.session_state.get("_logged_query") != query:
            log_search(query, result)
            st.session_state["_logged_query"] = query

        if not result["matched_pe_id"]:
            st.warning(
                "No program match. Try the program's common name, a quote "
                "that names it, or its PE number (e.g. 0602345A)."
            )
        else:
            enricher = get_enricher()
            candidates = result["candidates"]

            if result["needs_review"]:
                # Only offer the AI resolver when one is actually configured.
                st.warning(
                    f'Several programs match "{query}" — pick the right one '
                    "below" + (", or use the AI resolver." if enricher else ".")
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
            linked_agency = st.query_params.get("agency", "")
            if linked_pe:
                for i, candidate in enumerate(candidates):
                    if (
                        candidate["pe_number"] == linked_pe
                        and (not linked_agency
                             or candidate["agency"] == linked_agency)
                    ):
                        default_idx = i
                        break
            if adjudication and not adjudication.get("no_match"):
                for i, c in enumerate(candidates):
                    if (
                        c["pe_number"] == adjudication["pe_number"]
                        and c["agency"] == adjudication["agency"]
                    ):
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
                    width="stretch",
                )
            else:
                sel = candidates[0]

            if (
                st.query_params.get("pe") != sel["pe_number"]
                or st.query_params.get("agency") != sel["agency"]
            ):
                st.query_params.update(
                    pe=sel["pe_number"], agency=sel["agency"]
                )

            # ═══ Program profile ═══
            profile_definitions = [
                ("funding", "Funding"),
                ("plans", "Plans & Work"),
                ("awards", "Contracts & Awards"),
                ("news", "In the News"),
            ]
            requested_view = st.query_params.get("view", "funding")
            if requested_view not in {key for key, _ in profile_definitions}:
                requested_view = "funding"
            profile_labels = [label for _, label in profile_definitions]
            profile_state_key = (
                f"profile_tab::{sel['pe_number']}::{sel['agency']}"
            )
            profile_containers = st.tabs(
                profile_labels,
                default=dict(profile_definitions)[requested_view],
                key=profile_state_key,
                on_change=_sync_profile_tab_url,
                args=(profile_state_key,),
            )
            profile_tabs = {
                key: container
                for (key, _), container in zip(
                    profile_definitions, profile_containers
                )
            }
            sub_funding = profile_tabs["funding"]
            sub_plans = profile_tabs["plans"]
            sub_awards = profile_tabs["awards"]
            sub_news = profile_tabs["news"]

            # --- Funding ---
            with sub_funding:
                render_primer(
                    "How to read this program's funding",
                    primer.PROGRAM_STRUCTURE + primer.FUNDING_BASES,
                )
                with SessionFactory() as session:
                    hist = TrendTracker(session).get_pe_history(
                        sel["pe_number"], sel["agency"]
                    )
                if hist.is_empty():
                    st.info(
                        "No funding lines for this program in the database "
                        "(R-1 coverage: FY1996–FY2027)."
                    )
                else:
                    pdf = hist.to_pandas()
                    pdf["pb_cycle_label"] = pdf["pb_cycle"].apply(
                        lambda value: (
                            f"PB{int(value)}" if pd.notna(value) else "Unknown"
                        )
                    )
                    if constant_dollars:
                        from analysis.deflators import apply_deflator
                        pdf["amount_thousands"] = apply_deflator(
                            pdf, amount_column="amount_thousands"
                        )
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
                        help=primer.HELP["latest"],
                    )
                    peak = pdf.loc[pdf["amount_m"].idxmax()]
                    m2.metric(f"Peak (FY{int(peak.fiscal_year)})",
                              f"${peak.amount_m:,.1f}M",
                              help=primer.HELP["peak"])
                    m3.metric(
                        "History",
                        f"{len(pdf)} yrs",
                        delta=(f"FY{int(pdf.fiscal_year.min())}–"
                               f"FY{int(pdf.fiscal_year.max())}"),
                        delta_color="off",
                        help=primer.HELP["history"],
                    )
                    first = pdf.iloc[0]
                    span = int(latest.fiscal_year - first.fiscal_year)
                    if span > 0 and first.amount_m > 0 and latest.amount_m > 0:
                        cagr = ((latest.amount_m / first.amount_m)
                                ** (1 / span) - 1) * 100
                        m4.metric(f"CAGR ({span}y)", f"{cagr:+.1f}%",
                                  help=primer.HELP["cagr"])

                    base = alt.Chart(pdf).encode(
                        x=alt.X("fiscal_year:O", title="Fiscal Year")
                    )
                    line = base.mark_line(color="#c3c2b7", strokeWidth=2).encode(
                        y=alt.Y(
                            "amount_m:Q",
                            title=(
                                "$ Millions (constant FY2025)"
                                if constant_dollars else "$ Millions (then-year)"
                            ),
                        ),
                    )
                    points = base.mark_point(filled=True, size=90).encode(
                        y="amount_m:Q",
                        color=alt.Color("basis:N", scale=BASIS_COLORS,
                                        title="Figure basis"),
                        tooltip=[
                            alt.Tooltip("fiscal_year:O", title="FY"),
                            alt.Tooltip("amount_m:Q", format=",.1f", title="$M"),
                            alt.Tooltip("basis:N", title="Basis"),
                            alt.Tooltip("pb_cycle_label:N", title="Submission"),
                        ],
                    )
                    st.altair_chart((line + points).properties(height=280),
                                    width="stretch")
                    st.caption(
                        "Each year shows its most reliable figure: reported "
                        "actuals, then the enacted/current-year figure, then "
                        "the budget request. Tooltips identify the PB "
                        "submission supplying each observation. "
                        + (
                            "Amounts use the RDT&E-specific FY2025 Green Book "
                            "deflator."
                            if constant_dollars else
                            "Amounts are then-year dollars."
                        )
                    )
                    program_sources = fetch_funding_sources(
                        pe_numbers=(sel["pe_number"],),
                        agencies=(sel["agency"],),
                    )
                    program_sources = include_deflator_source(program_sources)
                    render_provenance(program_sources)

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
                                        width="stretch")

                    with st.expander("Underlying funding table"):
                        funding_table = pdf[[
                            "fiscal_year", "amount_thousands", "basis",
                            "pb_cycle_label",
                        ]].rename(columns={
                            "fiscal_year": "FY",
                            "amount_thousands": "$K",
                            "basis": "Basis",
                            "pb_cycle_label": "PB submission",
                        })
                        st.dataframe(
                            funding_table,
                            width="stretch", hide_index=True,
                        )
                        render_table_downloads(
                            funding_table,
                            name=f"{sel['pe_number']}_funding_history",
                            key=f"funding::{sel['pe_number']}::{sel['agency']}",
                            sources=program_sources,
                        )

                st.divider()
                st.subheader("Execution: request to net current program")
                render_primer(
                    "What each step means, and why the numbers differ",
                    primer.EXECUTION_STEPS,
                )
                execution, execution_source_rows = fetch_execution_data(
                    (sel["pe_number"],), (sel["agency"],)
                )
                if execution.empty:
                    st.caption(
                        "No DD 1416 execution row is currently ingested for "
                        "this PE and component. Missing coverage is not zero."
                    )
                else:
                    available_fys = sorted(
                        execution["fy_start"].astype(int).unique(), reverse=True
                    )
                    execution_fy = st.selectbox(
                        "Execution fiscal year",
                        available_fys,
                        key=f"execution_fy::{sel['pe_number']}::{sel['agency']}",
                    )
                    execution_row = execution[
                        execution["fy_start"] == execution_fy
                    ].sort_values("report_date").iloc[-1]
                    request_m = execution_row["request_k"] / 1e3
                    enacted_m = execution_row["enacted_k"] / 1e3
                    net_m = execution_row["net_k"] / 1e3
                    reprogramming_m = (
                        execution_row["above_threshold_reprog_k"]
                        + execution_row["below_threshold_reprog_k"]
                    ) / 1e3
                    e1, e2, e3, e4 = st.columns(4)
                    e1.metric("President's request", f"${request_m:,.1f}M",
                              help=primer.HELP["request"])
                    e2.metric("Enacted", f"${enacted_m:,.1f}M",
                              help=primer.HELP["enacted"])
                    e3.metric("Reprogramming", f"${reprogramming_m:+,.1f}M",
                              help=primer.HELP["reprogramming"])
                    e4.metric("Net current program", f"${net_m:,.1f}M",
                              help=primer.HELP["net"])
                    st.altair_chart(
                        execution_waterfall(execution_row), width="stretch"
                    )
                    st.caption(
                        "Above-threshold reprogramming required congressional "
                        "prior approval; below-threshold reprogramming did not. "
                        "DD 1416 reports budget authority—not obligations or "
                        "outlays. Amounts are then-year dollars. Latest "
                        "ingested quarter for this FY: "
                        f"{execution_row['report_date']}."
                    )
                    render_provenance(execution_source_rows)
                    execution_table = execution.rename(columns={
                        "fy_start": "FY",
                        "fy_end": "Availability end FY",
                        "report_date": "Latest quarter",
                    })
                    with st.expander("Execution data table"):
                        st.dataframe(
                            execution_table, width="stretch", hide_index=True
                        )
                        render_table_downloads(
                            execution_table,
                            name=f"{sel['pe_number']}_dd1416_execution",
                            key=(f"execution::{sel['pe_number']}::"
                                 f"{sel['agency']}"),
                            sources=execution_source_rows,
                        )

            # --- Plans & Work (R-2 justification narratives) ---
            with sub_plans:
                st.caption(primer.PROJECTS_NOTE)
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
                        "R-2 coverage varies by component and fiscal year; "
                        "see Data Coverage for the currently ingested corpus."
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
                            # Narrative prose is full of dollar amounts, and
                            # markdown reads "$…$" as LaTeX (see text_render).
                            st.write(escape_dollars(pe_level[0].description))
                    if projects:
                        with st.expander(
                            f"Projects under this program ({len(projects)})"
                        ):
                            for p in sorted(projects,
                                            key=lambda n: n.project_number):
                                st.markdown(
                                    f"**{p.project_number} — {p.project_title}**"
                                )
                                st.caption(escape_dollars(
                                    p.description[:500]
                                    + ("…" if len(p.description) > 500 else "")
                                ))
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
                            on_change=_sync_profile_view,
                            args=("plans",),
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
                            st.markdown(escape_dollars(
                                f"**{amt}{a.title or a.project_number}**"))
                            if a.text:
                                st.caption(escape_dollars(
                                    a.text[:700]
                                    + ("…" if len(a.text) > 700 else "")))
                        if len(year_accs) > 12:
                            st.caption(
                                f"…and {len(year_accs) - 12} more line items."
                            )

            # --- Contracts & Awards ---
            with sub_awards:
                render_primer("Why awards never tie to the budget figures",
                              primer.AWARDS_VS_BUDGET)
                ac1, _ = st.columns([1, 3])
                award_fy = ac1.selectbox(
                    "Fiscal year", EXECUTION_FYS,
                    index=EXECUTION_FYS.index(2025), key="award_fy",
                )
                awards_key = f"awards::{sel['pe_number']}::{award_fy}::{query}"
                if st.button(
                    "Search awards (USAspending.gov)",
                    on_click=_sync_profile_view,
                    args=("awards",),
                ):
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
                                        width="stretch")
                        display = awards.copy()
                        display["amount_m"] = display["amount"] / 1e6
                        display["description"] = (
                            display["description"].str.slice(0, 140)
                        )
                        award_table = display[[
                            "recipient", "amount_m", "instrument",
                            "sub_agency", "start_date", "description", "url",
                        ]]
                        st.dataframe(
                            award_table,
                            width="stretch", hide_index=True,
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
                        award_sources = [{
                            "filename": "USAspending.gov award search",
                            "document_type": "USAspending API",
                            "publication_year": award_fy,
                            "source_url": "https://api.usaspending.gov/",
                            "retrieved_at": None,
                            "processed_date": None,
                        }]
                        render_provenance(award_sources)
                        render_table_downloads(
                            award_table,
                            name=f"{sel['pe_number']}_awards_fy{award_fy}",
                            key=(f"awards::{sel['pe_number']}::{award_fy}::"
                                 f"{query}"),
                            sources=award_sources,
                        )

                    subs_key = f"subs::{sel['pe_number']}::{award_fy}::{query}"
                    if st.button(
                        "Search subawards (umbrella vehicles)",
                        on_click=_sync_profile_view,
                        args=("awards",),
                    ):
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
                            subaward_table = sdisp[[
                                "subawardee", "amount_m", "prime_recipient",
                                "date", "description",
                            ]]
                            st.dataframe(
                                subaward_table,
                                width="stretch", hide_index=True,
                                column_config={
                                    "subawardee": "Subawardee",
                                    "amount_m": st.column_config.NumberColumn(
                                        "Sub-award $M", format="%.2f"),
                                    "prime_recipient": "Prime recipient",
                                    "date": "Date",
                                    "description": "Description",
                                },
                            )
                            subaward_sources = [{
                                "filename": "USAspending.gov subaward search",
                                "document_type": "USAspending API",
                                "publication_year": award_fy,
                                "source_url": "https://api.usaspending.gov/",
                                "retrieved_at": None,
                                "processed_date": None,
                            }]
                            render_provenance(subaward_sources)
                            render_table_downloads(
                                subaward_table,
                                name=(f"{sel['pe_number']}_subawards_"
                                      f"fy{award_fy}"),
                                key=(f"subawards::{sel['pe_number']}::"
                                     f"{award_fy}::{query}"),
                                sources=subaward_sources,
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
                            "AI lookups are off — no Gemini API key is "
                            "configured for this instance. To enable them, "
                            "run the app with your own GEMINI_API_KEY (an "
                            "environment variable locally, or a Secret on "
                            "Streamlit Community Cloud) and restart it."
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
                        if st.button(
                            "Search recent coverage (AI + Google Search)",
                            on_click=_sync_profile_view,
                            args=("news",),
                        ):
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
                        if st.button(
                            "Refresh coverage (AI + Google Search)",
                            on_click=_sync_profile_view,
                            args=("news",),
                        ):
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
        value=st.query_params.get("rq", ""),
        placeholder="e.g. launched effects",
        on_change=_sync_rhetoric_url,
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
            # Bounds come from the data, not a hardcoded range: committee
            # actions are on record from FY2012 (earlier tables are images)
            # through the newest report ingested.
            fy_first, fy_last = congressional_year_bounds()
            if fy_last <= fy_first:          # empty table; keep a valid slider
                fy_last = fy_first + 1
            rhet_start = _query_int(
                "rstart", max(fy_first, fy_last - 7), fy_first, fy_last
            )
            rhet_end = _query_int("rend", fy_last, fy_first, fy_last)
            if rhet_start > rhet_end:
                rhet_start, rhet_end = max(fy_first, fy_last - 7), fy_last
            yr_lo, yr_hi = st.slider(
                "Analysis window", fy_first, fy_last,
                (rhet_start, rhet_end),
                key="rhet_years",
                on_change=_sync_rhetoric_url,
                help="Scopes both the congressional figures and the optional "
                     "AI signal below.",
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
                render_primer("Authorization versus appropriation",
                              primer.AUTHORIZATION_VS_APPROPRIATION)
                with SessionFactory() as session:
                    ca = CongressionalActions(session)
                    ca_pes = [c["pe_number"] for c in sel_cands]
                    ca_agencies = [c["agency"] for c in sel_cands]
                    ca_series_all = ca.get_program_series(ca_pes, ca_agencies)
                    ca_series = ca_series_all
                    ca_rows = ca.get_actions(ca_pes, ca_agencies)

                # The analysis window scopes this section too. Remember what
                # exists outside it so an empty window is never mistaken for
                # "no action on record".
                years_on_record = sorted(
                    ca_rows["fiscal_year"].unique().to_list())
                in_window = pl.col("fiscal_year").is_between(yr_lo, yr_hi)
                ca_rows = ca_rows.filter(in_window)
                if not ca_series.is_empty():   # schema-less when nothing matched
                    ca_series = ca_series.filter(in_window)

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
                if not ca_sum["years_covered"] and years_on_record:
                    st.markdown(
                        f"**No committee action on "
                        f"{escape_dollars(display_name)} inside "
                        f"FY{yr_lo}–FY{yr_hi}.** Actions are on record for "
                        f"FY{years_on_record[0]}–FY{years_on_record[-1]} — "
                        "widen the window to see them."
                    )
                else:
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
                                    width="stretch")

                    biggest = ca_sum["largest_cut"] or ca_sum["largest_add"]
                    if biggest and biggest.get("rationale"):
                        st.caption(
                            f"Largest single-year change — FY"
                            f"{biggest['fiscal_year']}, "
                            f"${biggest['amount_m']:+,.1f}M: "
                            f"{biggest['rationale']}"
                        )

                    with st.expander("Line-by-line committee actions"):
                        committee_table = ca_rows.to_pandas()[[
                            "fiscal_year", "chamber", "pe_number",
                            "program_title", "budget_activity_title",
                            "request_k", "committee_delta_k",
                            "authorized_k", "rationale", "report_citation",
                        ]]
                        st.dataframe(
                            committee_table,
                            width="stretch", hide_index=True,
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
                        committee_sources = [
                            {
                                "filename": citation,
                                "document_type": "NDAA committee report",
                                "publication_year": int(
                                    committee_table.loc[
                                        committee_table["report_citation"]
                                        == citation,
                                        "fiscal_year",
                                    ].iloc[0]
                                ),
                                "source_url": (
                                    "https://www.govinfo.gov/content/pkg/"
                                    f"{citation}/html/{citation}.htm"
                                ),
                                "retrieved_at": None,
                                "processed_date": None,
                            }
                            for citation in sorted(
                                committee_table["report_citation"].unique()
                            )
                        ]
                        render_provenance(committee_sources)
                        render_table_downloads(
                            committee_table,
                            name=f"committee_actions_fy{yr_lo}_{yr_hi}",
                            key=(f"committee::{yr_lo}::{yr_hi}::"
                                 f"{','.join(ca_pes)}"),
                            sources=committee_sources,
                        )
                st.caption(coverage_note())

                st.subheader("Request → authorization → execution")
                render_primer("What each stage means",
                              primer.EXECUTION_STEPS)
                execution, execution_source_rows = fetch_execution_data(
                    tuple(ca_pes), tuple(ca_agencies)
                )
                execution = execution[
                    execution["fy_start"].between(yr_lo, yr_hi)
                ] if not execution.empty else execution
                if execution.empty:
                    st.caption(
                        "No DD 1416 execution record falls inside this "
                        "window. Authorization above remains distinct from "
                        "appropriation."
                    )
                else:
                    chain_fys = sorted(
                        execution["fy_start"].astype(int).unique(), reverse=True
                    )
                    chain_fy = st.selectbox(
                        "Fiscal year for full chain",
                        chain_fys,
                        key="rhet_execution_fy",
                    )
                    erow = execution[
                        execution["fy_start"] == chain_fy
                    ].sort_values("report_date").iloc[-1]
                    chain = [{
                        "stage": "President's request",
                        "amount_m": erow["request_k"] / 1e3,
                        "kind": "Request",
                    }]
                    if not ca_series_all.is_empty():
                        auth_for_year = ca_series_all.filter(
                            pl.col("fiscal_year") == chain_fy
                        ).sort("chamber")
                        for auth_row in auth_for_year.iter_rows(named=True):
                            chain.append({
                                "stage": f"{auth_row['chamber']} authorized",
                                "amount_m": auth_row["authorized_k"] / 1e3,
                                "kind": "Authorization",
                            })
                    chain.extend([
                        {
                            "stage": "Enacted appropriation",
                            "amount_m": erow["enacted_k"] / 1e3,
                            "kind": "Appropriation",
                        },
                        {
                            "stage": "Net current program",
                            "amount_m": erow["net_k"] / 1e3,
                            "kind": "Execution",
                        },
                    ])
                    chain_df = pd.DataFrame(chain)
                    chain_order = chain_df["stage"].tolist()
                    chain_chart = (
                        alt.Chart(chain_df)
                        .mark_bar(cornerRadiusEnd=4)
                        .encode(
                            x=alt.X("stage:N", sort=chain_order, title=None,
                                    axis=alt.Axis(labelAngle=-25)),
                            y=alt.Y("amount_m:Q", title="$ Millions"),
                            color=alt.Color(
                                "kind:N",
                                scale=alt.Scale(
                                    domain=["Request", "Authorization",
                                            "Appropriation", "Execution"],
                                    range=["#2a78d6", "#8b6fc0",
                                           "#1baf7a", "#eb6834"],
                                ),
                                title=None,
                            ),
                            tooltip=[
                                alt.Tooltip("stage:N", title="Stage"),
                                alt.Tooltip("amount_m:Q", format=",.1f",
                                            title="$M"),
                            ],
                        )
                        .properties(height=280)
                    )
                    st.altair_chart(chain_chart, width="stretch")
                    st.caption(
                        "House and Senate authorizations are shown separately. "
                        "DD 1416 supplies enacted appropriation and the latest "
                        "net program after statutory adjustments and "
                        "reprogramming; it does not report outlays. All stages "
                        "in this chart are then-year dollars."
                    )
                    render_provenance(execution_source_rows)
                    render_table_downloads(
                        chain_df,
                        name=f"request_authorization_execution_fy{chain_fy}",
                        key=f"rhet-chain::{chain_fy}::{','.join(ca_pes)}",
                        sources=execution_source_rows,
                    )

            # ── Optional AI layer: open-source emphasis ───────────────────
            st.divider()
            st.subheader("Open-source emphasis (AI)")
            enricher_r = get_enricher()
            if enricher_r is None:
                st.caption(
                    "Optional, and off in this instance — no Gemini API key "
                    "is configured. With your own GEMINI_API_KEY (an "
                    "environment variable locally, or a Secret on Streamlit "
                    "Community Cloud) and a restart, this adds an "
                    "AI-characterized signal for how much the program was "
                    "publicly discussed. The congressional figures above "
                    "need no key."
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
                                        width="stretch")

                        merged = r["merged"].copy()
                        merged["statement"] = merged.apply(
                            lambda row: (f"{row['notable_statement']} "
                                         f"({row['statement_source']})"
                                         if row["notable_statement"] else ""),
                            axis=1,
                        )
                        rhetoric_table = merged[[
                            "fiscal_year", "mention_intensity",
                            "positive_pct", "stated_priority", "amount_m",
                            "yoy_pct", "statement",
                        ]]
                        st.dataframe(
                            rhetoric_table,
                            width="stretch", hide_index=True,
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
                        rhetoric_sources = [{
                            "filename": "Per-user Gemini Grounded Search result",
                            "document_type": "AI-grounded web research",
                            "publication_year": yr_hi,
                            "source_url": None,
                            "retrieved_at": sig_res.created_at,
                            "processed_date": sig_res.created_at,
                        }]
                        render_provenance(rhetoric_sources)
                        render_table_downloads(
                            rhetoric_table,
                            name=f"rhetoric_funding_fy{yr_lo}_{yr_hi}",
                            key=(f"rhetoric::{yr_lo}::{yr_hi}::"
                                 f"{','.join(c['pe_number'] for c in sel_cands)}"),
                            sources=rhetoric_sources,
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
              delta=f"FY{stats['fy_min']}–FY{stats['fy_max']}",
              delta_color="off")
    s3.metric("Programs with narratives", f"{stats['narrative_pes']:,}")
    s4.metric("Work line items", f"{stats['accomplishments']:,}")
    render_primer(
        "How the numbers relate: program elements, projects, request, "
        "authorization, appropriation, execution, and awards",
        primer.GLOSSARY,
    )

    if get_enricher() is None:
        st.caption(
            "AI features are off in this instance — no Gemini API key is "
            "configured. Everything shown comes from the local database and "
            "USAspending.gov."
        )
    else:
        try:
            from analysis.ai_budget import SpendLedger
            used = SpendLedger.fresh_calls_this_month(current_user_id())
            allowance = config_module.AI_FREE_CREDITS_PER_MONTH
            if allowance is not None:
                st.caption(f"Fresh AI lookups used this month: "
                           f"{used} of {allowance}. Saved analysis is "
                           "unlimited.")
        except Exception:
            pass

    narrative_coverage = stats.get("narrative_by_agency", {})
    if narrative_coverage:
        r2_detail = ", ".join(
            f"{agency} {detail['programs']:,} "
            f"(FY{detail['first_fy']}–FY{detail['last_fy']})"
            for agency, detail in narrative_coverage.items()
        )
    else:
        r2_detail = "No narratives currently ingested"

    st.markdown(f"""
| Source | Coverage | How it's used |
|---|---|---|
| **R-1 budget exhibits** (comptroller.war.gov) | FY{stats['fy_min']}–FY{stats['fy_max']} observations across PB submissions. Official XLSX for FY2012+; parsed PDFs before that | Funding trends, vintage labels, and program funding histories (local database) |
| **DD 1416 quarterly execution reports** (comptroller.war.gov) | {stats['execution_rows']:,} rows from {stats['execution_files']:,} official XLSX files; FY{stats['execution_fy_min'] or '—'}–FY{stats['execution_fy_max'] or '—'} | Request, enacted appropriation, statutory adjustments, above-/below-threshold reprogramming, and net current program |
| **R-2 justification books** (official XML and service PDFs) | {stats['narratives']:,} narratives and {stats['accomplishments']:,} accomplishment line items. {r2_detail} | Mission descriptions and "Plans & Work"; also sharpens program matching |
| **USAspending.gov** (live queries) | Prime awards (contracts + grants/cooperative agreements), subawards, account-level obligations | "Contracts & Awards" and "Who got paid" |
| **AI enrichment** (optional) | Google-grounded search and match resolution | "In the News", "Rhetoric vs. Budget", and ambiguity resolution |

**Known blind spots — an empty result is often one of these, not an error:**

- **Award ↔ program linkage doesn't exist in public data.** Award records carry no program-element field, so the Contracts & Awards search is keyword matching against award descriptions. Awards described generically won't surface.
- **Umbrella vehicles hide task detail.** Work under PIAs, OTAs, and IDIQ task orders often posts under a generic umbrella description; the subaward search catches some, not all.
- **Other Transactions** are not a searchable instrument group in the USAspending API.
- **Timing:** DoD awards post with a ~90-day display delay, and the current fiscal year is always partial.
- **Justification coverage varies by component and year.** Army has no published FY2023 RDT&E books in the ingested sources; Air Force and Space Force archive coverage currently ends at FY2024. An absent program/year may therefore reflect a source gap rather than no planned work.
- **Classified programs** appear only as aggregate lines; the Intelligence Community publishes topline figures only.

**How the AI features are stored and metered**

- **Match resolution is shared.** It doesn't use web search, so once one person resolves an ambiguous name, everyone else's identical search resolves instantly and for free.
- **Web-grounded results are yours alone.** "In the News" and "Rhetoric vs. Budget" run against Google Search, and Google's API terms allow those results to be shown only to the person who asked for them. They're saved to your own history, never pooled, and always displayed with Google's Search Suggestions.
- **Fresh lookups are metered**, so a busy month can't run up an unbounded bill. Anything already analyzed keeps loading normally even after the allowance runs out.
""")
