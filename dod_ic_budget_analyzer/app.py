"""
app.py

DoD RDT&E Budget Analyzer — Streamlit Interface

Tabs:
  1. Program Linker    — match short names/acronyms to PE records + funding trends
  2. Macro Trends      — agency-level funding trajectories over time
  3. PE Explorer       — search and browse individual program elements
  4. Policy Alignment  — NDAA/NDS vs. actual budget (coming soon)
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import polars as pl
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from analysis.trend_tracker import TrendTracker
from analysis.policy_linker import PolicyLinker
from storage.db import FundingLine, ProgramElement, get_engine, get_session_factory, init_db
from sqlalchemy import select

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="DoD RDT&E Budget Analyzer",
    page_icon="🇺🇸",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Colour palette ────────────────────────────────────────────────────────────

PALETTE = {
    "Army":          "#4c7a34",
    "Navy":          "#1f4e79",
    "Air Force":     "#1b6ca8",
    "Space Force":   "#7030a0",
    "Defense-Wide":  "#c55a11",
    "OT&E":          "#767171",
    "Unknown":       "#a6a6a6",
}
DEFAULT_COLOUR = "#2e75b6"

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }

.match-card {
    background: #f8f9fa;
    border-left: 4px solid #1f4e79;
    border-radius: 4px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
}
.match-card-top { border-left-color: #4c7a34; }
.match-card-alt { border-left-color: #c55a11; opacity: 0.85; }

.badge-high   { background:#e6f4ea; color:#1e7e34; padding:2px 8px;
                border-radius:10px; font-size:0.78rem; font-weight:600; }
.badge-medium { background:#fff8e1; color:#856404; padding:2px 8px;
                border-radius:10px; font-size:0.78rem; font-weight:600; }
.badge-low    { background:#fdecea; color:#b71c1c; padding:2px 8px;
                border-radius:10px; font-size:0.78rem; font-weight:600; }
.badge-exact  { background:#e8eaf6; color:#283593; padding:2px 8px;
                border-radius:10px; font-size:0.78rem; font-weight:600; }

.stage-pill {
    background:#e3f2fd; color:#0d47a1;
    padding:2px 8px; border-radius:10px;
    font-size:0.75rem; font-family:monospace;
}

div[data-testid="metric-container"] {
    background:#f8f9fa;
    border:1px solid #e9ecef;
    border-radius:6px;
    padding:0.5rem 0.75rem;
}
</style>
""", unsafe_allow_html=True)

# ── DB path ───────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
DB_URI = f"sqlite:///{_HERE}/data/processed/usg_budgets.db"


# ── Cached resources ──────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def _get_session_factory():
    engine = get_engine(DB_URI)
    init_db(engine)
    return get_session_factory(engine)


SessionFactory = _get_session_factory()


@st.cache_resource(show_spinner=False)
def _get_policy_linker():
    """Load the PolicyLinker (embeds 12k chunks + 2k PEs — uses cache on disk)."""
    with SessionFactory() as session:
        return PolicyLinker(session)


@st.cache_resource(show_spinner=False)
def _get_linker():
    """
    Load the full matching pipeline.
    Cached after first call — subsequent searches are instant.
    The semantic model (~90MB) takes ~20s to encode on first load.
    """
    from matching.program_linker import ProgramLinker
    with SessionFactory() as session:
        return ProgramLinker(
            session,
            fuzzy_threshold=55.0,
            semantic_threshold=0.35,
            top_n=5,
            load_semantic=True,
        )


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_pe_funding_long(pe_id: int) -> pl.DataFrame:
    with SessionFactory() as session:
        rows = session.execute(
            select(
                FundingLine.fiscal_year,
                FundingLine.funding_type,
                FundingLine.amount_thousands,
            )
            .where(FundingLine.program_element_id == pe_id)
            .order_by(FundingLine.fiscal_year)
        ).all()
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, schema={
        "fiscal_year":      pl.Int64,
        "funding_type":     pl.Utf8,
        "amount_thousands": pl.Float64,
    }, orient="row")


def _get_pe_funding_wide(pe_id: int) -> pl.DataFrame:
    df = _get_pe_funding_long(pe_id)
    if df.is_empty():
        return df
    return df.pivot(
        index="funding_type",
        columns="fiscal_year",
        values="amount_thousands",
        aggregate_function="sum",
    ).fill_null(0.0)


def _plot_pe_trend(pe_id: int, program_name: str, agency: str) -> None:
    """Bar chart of BY Request funding across all fiscal years for one PE."""
    df = _get_pe_funding_long(pe_id)
    if df.is_empty():
        st.info("No funding data available.")
        return

    df_by = df.filter(pl.col("funding_type") == "BY Request").sort("fiscal_year")
    if df_by.is_empty():
        st.info("No Budget Year request data available.")
        return

    years   = df_by["fiscal_year"].to_list()
    amounts = [v / 1_000 for v in df_by["amount_thousands"].to_list()]  # $K -> $M
    colour  = PALETTE.get(agency, DEFAULT_COLOUR)

    fig, ax = plt.subplots(figsize=(11, 3.2))
    fig.patch.set_facecolor("#fafafa")
    ax.set_facecolor("#fafafa")

    bars = ax.bar(years, amounts, color=colour, alpha=0.82, width=0.6, zorder=3)
    ax.plot(years, amounts, color=colour, linewidth=1.6,
            marker="o", markersize=4, zorder=4)

    max_val = max(amounts) if amounts else 1
    for bar, val in zip(bars, amounts):
        if val > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max_val * 0.02,
                f"${val:,.0f}M",
                ha="center", va="bottom", fontsize=7.5, color="#333",
            )

    title = program_name[:70] + ("…" if len(program_name) > 70 else "")
    ax.set_title(title, fontsize=10, pad=8, loc="left")
    ax.set_ylabel("$M (BY Request)", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}M"))
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=len(years)))
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _badge_html(score: float, stage: str) -> str:
    if stage == "PE_NUMBER":
        return '<span class="badge-exact">🔢 Exact PE#</span>'
    if score >= 0.90:
        return f'<span class="badge-high">🟢 High {score:.0%}</span>'
    if score >= 0.65:
        return f'<span class="badge-medium">🟡 Medium {score:.0%}</span>'
    return f'<span class="badge-low">🟠 Low {score:.0%}</span>'


def _stage_html(stage: str) -> str:
    return f'<span class="stage-pill">{stage}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════

st.title("🇺🇸 DoD RDT&E Budget Analyzer")
st.caption("FY1998–2026  ·  Unclassified R-1 Data  ·  Amounts in $K unless noted")
st.divider()

tab_linker, tab_trends, tab_explorer, tab_policy = st.tabs([
    "🔍  Program Linker",
    "📈  Macro Trends",
    "🗂  PE Explorer",
    "📄  Policy Alignment",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Program Linker
# ══════════════════════════════════════════════════════════════════════════════

with tab_linker:
    st.subheader("Program Linker")
    st.markdown(
        "Enter a program name, acronym, or PE number from a press release or article. "
        "The first search loads the AI model (~20 seconds). Searches after that are instant."
    )

    col_q, col_btn = st.columns([5, 1])
    with col_q:
        query = st.text_input(
            "query",
            placeholder="e.g.  LTAMDS  ·  future vertical lift  ·  0604114A  ·  hypersonics",
            label_visibility="collapsed",
            key="linker_query",
        )
    with col_btn:
        search_clicked = st.button("Search", type="primary", use_container_width=True)

    if search_clicked and query.strip():
        # Show loading message on first search only
        status_slot = st.empty()
        if "linker_loaded" not in st.session_state:
            status_slot.info("⏳ Loading AI matching model for the first time — ~20 seconds…")

        linker = _get_linker()
        st.session_state["linker_loaded"] = True
        status_slot.empty()

        with st.spinner("Searching…"):
            result = linker.link(query.strip())

        if not result.matched:
            st.warning(
                "No match found above the confidence threshold. "
                "Try a different name, acronym, or PE number."
            )
        else:
            top = result.candidates[0]

            # ── Top match card ─────────────────────────────────────────────
            st.markdown(
                f"""
                <div class="match-card match-card-top">
                    <div style="font-size:1.05rem;font-weight:600;margin-bottom:4px;">
                        {top.program_name}
                    </div>
                    <div style="font-size:0.85rem;color:#555;
                                display:flex;gap:12px;flex-wrap:wrap;">
                        <span>📋 <b>{top.pe_number}</b></span>
                        <span>🏛 {top.agency}</span>
                        <span>{top.budget_activity or ''}</span>
                        <span>{_badge_html(top.score, result.match_stage)}</span>
                        <span>via {_stage_html(result.match_stage)}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ── Metrics row ────────────────────────────────────────────────
            df_long = _get_pe_funding_long(top.pe_id)
            if not df_long.is_empty():
                df_by = df_long.filter(pl.col("funding_type") == "BY Request")
                if not df_by.is_empty():
                    latest_fy  = int(df_by["fiscal_year"].max())
                    earliest_fy = int(df_by["fiscal_year"].min())
                    latest_amt  = df_by.filter(
                        pl.col("fiscal_year") == latest_fy
                    )["amount_thousands"].sum()
                    earliest_amt = df_by.filter(
                        pl.col("fiscal_year") == earliest_fy
                    )["amount_thousands"].sum()
                    n_yrs  = latest_fy - earliest_fy
                    delta  = (latest_amt - earliest_amt) / earliest_amt * 100 \
                             if earliest_amt > 0 else 0.0
                    cagr   = ((latest_amt / earliest_amt) ** (1 / n_yrs) - 1) * 100 \
                             if n_yrs > 0 and earliest_amt > 0 else 0.0

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric(f"FY{latest_fy} BY Request",
                              f"${latest_amt/1_000:,.1f}M")
                    m2.metric(f"FY{earliest_fy} BY Request",
                              f"${earliest_amt/1_000:,.1f}M")
                    m3.metric(f"Total Change ({earliest_fy}→{latest_fy})",
                              f"{delta:+.1f}%", delta=f"{delta:+.1f}%")
                    m4.metric("CAGR", f"{cagr:+.1f}%/yr")

            # ── Trend chart ────────────────────────────────────────────────
            _plot_pe_trend(top.pe_id, top.program_name, top.agency)

            # ── Full funding table ─────────────────────────────────────────
            with st.expander("📊 Full funding detail (PY / CY / BY by year)"):
                df_wide = _get_pe_funding_wide(top.pe_id)
                if not df_wide.is_empty():
                    st.dataframe(df_wide.to_pandas(), use_container_width=True)
                    st.caption(
                        "PY Actual = prior year actuals  ·  "
                        "CY Request = current year enacted/request  ·  "
                        "BY Request = budget year request  ·  Amounts in $K"
                    )

            # ── Alternatives ───────────────────────────────────────────────
            if len(result.candidates) > 1:
                with st.expander(
                    f"🔀 {len(result.candidates) - 1} alternative candidate(s)"
                ):
                    for i, c in enumerate(result.candidates[1:], start=2):
                        st.markdown(
                            f"""
                            <div class="match-card match-card-alt">
                                <div style="font-size:0.95rem;font-weight:600;">
                                    {i}. {c.program_name}
                                </div>
                                <div style="font-size:0.82rem;color:#666;
                                            display:flex;gap:10px;flex-wrap:wrap;">
                                    <span>📋 <b>{c.pe_number}</b></span>
                                    <span>🏛 {c.agency}</span>
                                    <span>{_badge_html(c.score, c.match_stage)}</span>
                                    <span>{c.match_detail}</span>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if st.button("View funding →", key=f"alt_{c.pe_id}"):
                            st.session_state["alt_pe_id"]    = c.pe_id
                            st.session_state["alt_pe_name"]  = c.program_name
                            st.session_state["alt_pe_agency"] = c.agency

            if "alt_pe_id" in st.session_state:
                st.divider()
                st.markdown(f"**Funding: {st.session_state['alt_pe_name']}**")
                _plot_pe_trend(
                    st.session_state["alt_pe_id"],
                    st.session_state["alt_pe_name"],
                    st.session_state.get("alt_pe_agency", ""),
                )

    # ── Batch mode ─────────────────────────────────────────────────────────────
    st.divider()
    with st.expander("📋 Batch mode — link multiple programs at once"):
        batch_input = st.text_area(
            "One program name, acronym, or PE number per line",
            height=130,
            placeholder="LTAMDS\nfuture vertical lift\nhypersonics\n0604114A",
        )
        col_run, col_dl = st.columns([2, 1])
        run_batch = col_run.button("▶ Run batch match", type="primary")

        if run_batch and batch_input.strip():
            queries_b = [q.strip() for q in batch_input.splitlines() if q.strip()]
            slot2 = st.empty()
            if "linker_loaded" not in st.session_state:
                slot2.info("⏳ Loading AI model — ~20 seconds…")
            linker = _get_linker()
            st.session_state["linker_loaded"] = True
            slot2.empty()

            with st.spinner(f"Linking {len(queries_b)} queries…"):
                df_batch = linker.link_batch(queries_b)
            st.session_state["batch_results"] = df_batch

        if "batch_results" in st.session_state:
            df_b   = st.session_state["batch_results"]
            df_top = df_b.filter(pl.col("rank") == 1)
            st.dataframe(
                df_top.select([
                    "query", "match_stage", "pe_number",
                    "program_name", "agency", "score",
                ]).to_pandas(),
                use_container_width=True, height=300,
            )
            csv_b = df_b.to_pandas().to_csv(index=False)
            col_dl.download_button(
                "⬇️ Download CSV",
                data=csv_b,
                file_name="batch_match_results.csv",
                mime="text/csv",
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Macro Trends
# ══════════════════════════════════════════════════════════════════════════════

with tab_trends:
    st.subheader("Agency Funding Trends")

    col1, col2 = st.columns(2)
    start_yr = col1.slider("Start Year", 2006, 2024, 2015)
    end_yr   = col2.slider("End Year",   2007, 2026, 2026)
    agencies_sel = st.multiselect(
        "Agencies to display",
        ["Army", "Navy", "Air Force", "Defense-Wide", "Space Force"],
        default=["Army", "Navy", "Air Force", "Defense-Wide"],
    )

    if st.button("Generate Trends", type="primary"):
        with st.spinner("Calculating…"):
            with SessionFactory() as session:
                tracker = TrendTracker(session)
                df_trends = tracker.get_agency_trends(start_yr, end_yr)

        if df_trends.is_empty():
            st.warning("No data found for the selected range.")
        else:
            df_f = df_trends.filter(pl.col("agency").is_in(agencies_sel)) \
                   if agencies_sel else df_trends

            year_cols = sorted(
                [c for c in df_f.columns if c.isdigit()], key=int
            )
            df_pd = df_f.to_pandas()

            if not df_pd.empty and year_cols:
                fig, ax = plt.subplots(figsize=(13, 5))
                fig.patch.set_facecolor("#fafafa")
                ax.set_facecolor("#fafafa")

                for _, row in df_pd.iterrows():
                    agency = row["agency"]
                    vals   = [row.get(y, 0) / 1_000 for y in year_cols]
                    colour = PALETTE.get(agency, DEFAULT_COLOUR)
                    ax.plot(
                        [int(y) for y in year_cols], vals,
                        marker="o", markersize=4, linewidth=2,
                        color=colour, label=agency, zorder=3,
                    )

                ax.set_title(
                    f"RDT&E BY Request by Component (FY{start_yr}–FY{end_yr})",
                    fontsize=11, pad=10, loc="left",
                )
                ax.set_ylabel("$M", fontsize=9)
                ax.yaxis.set_major_formatter(
                    mticker.FuncFormatter(lambda x, _: f"${x:,.0f}M")
                )
                ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
                ax.tick_params(axis="x", rotation=45, labelsize=8)
                ax.tick_params(axis="y", labelsize=8)
                ax.grid(axis="y", color="#e0e0e0", linewidth=0.8, zorder=0)
                ax.spines[["top", "right"]].set_visible(False)
                ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1),
                          fontsize=9, frameon=False)
                plt.tight_layout()
                st.pyplot(fig)
                plt.close(fig)

                # ── Period summary metrics ─────────────────────────────────
                mcols = st.columns(len(df_pd))
                last_col  = year_cols[-1]
                first_col = year_cols[0]
                for ci, (_, row) in enumerate(df_pd.iterrows()):
                    latest   = row.get(last_col, 0) / 1_000
                    earliest = row.get(first_col, 0) / 1_000
                    delta    = (latest - earliest) / earliest * 100 \
                               if earliest > 0 else 0.0
                    mcols[ci].metric(
                        row["agency"], f"${latest:,.0f}M", f"{delta:+.1f}%"
                    )

            with st.expander("📊 Full data table + download"):
                display_cols = (
                    ["agency"]
                    + [c for c in df_f.columns if c.isdigit()]
                    + ["total_delta_pct", "cagr_pct"]
                )
                display_cols = [c for c in display_cols if c in df_f.columns]
                st.dataframe(
                    df_f.select(display_cols).to_pandas(),
                    use_container_width=True,
                )
                st.download_button(
                    "⬇️ Download CSV",
                    data=df_f.to_pandas().to_csv(index=False),
                    file_name=f"agency_trends_{start_yr}_{end_yr}.csv",
                    mime="text/csv",
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — PE Explorer
# ══════════════════════════════════════════════════════════════════════════════

with tab_explorer:
    st.subheader("Program Element Explorer")

    col_a, col_b, col_c = st.columns(3)
    agency_filter = col_a.multiselect(
        "Agency",
        ["Army", "Navy", "Air Force", "Defense-Wide", "Space Force", "OT&E"],
    )
    ba_filter = col_b.multiselect(
        "Budget Activity",
        [
            "BA1 - Basic Research",
            "BA2 - Applied Research",
            "BA3 - Advanced Technology Development",
            "BA4 - Advanced Component Development & Prototypes",
            "BA5 - System Development & Demonstration",
            "BA6 - Management Support",
            "BA7 - Operational Systems Development",
            "BA8 - Software And Digital Technology Pilot Programs",
        ],
    )
    name_search = col_c.text_input("Search name", placeholder="e.g. hypersonic")

    if st.button("Search PEs", type="primary"):
        with SessionFactory() as session:
            stmt = select(
                ProgramElement.pe_number,
                ProgramElement.program_name,
                ProgramElement.agency,
                ProgramElement.budget_activity,
            ).where(ProgramElement.is_classified == False)  # noqa: E712
            if agency_filter:
                stmt = stmt.where(ProgramElement.agency.in_(agency_filter))
            if ba_filter:
                stmt = stmt.where(ProgramElement.budget_activity.in_(ba_filter))
            if name_search:
                stmt = stmt.where(
                    ProgramElement.program_name.ilike(f"%{name_search}%")
                )
            stmt = stmt.order_by(ProgramElement.agency, ProgramElement.pe_number)
            rows = session.execute(stmt).all()

        if not rows:
            st.info("No program elements match the filters.")
        else:
            df_pe = pl.DataFrame(rows, schema={
                "pe_number":       pl.Utf8,
                "program_name":    pl.Utf8,
                "agency":          pl.Utf8,
                "budget_activity": pl.Utf8,
            }, orient="row")
            st.caption(f"{len(df_pe):,} program elements found")
            st.dataframe(df_pe.to_pandas(), use_container_width=True, height=420)

            st.divider()
            options = ["— select a PE —"] + [
                f"{r[0]}  |  {r[1][:55]}  |  {r[2]}" for r in rows
            ]
            pe_choice = st.selectbox("View funding trend", options)
            if pe_choice != options[0]:
                sel_num    = pe_choice.split("|")[0].strip()
                sel_agency = pe_choice.split("|")[-1].strip()
                with SessionFactory() as session:
                    pe_row = session.execute(
                        select(ProgramElement.id, ProgramElement.program_name)
                        .where(ProgramElement.pe_number == sel_num)
                    ).first()
                if pe_row:
                    _plot_pe_trend(pe_row[0], pe_row[1], sel_agency)
                    with st.expander("Full funding table"):
                        df_w = _get_pe_funding_wide(pe_row[0])
                        if not df_w.is_empty():
                            st.dataframe(df_w.to_pandas(), use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Policy Alignment
# ══════════════════════════════════════════════════════════════════════════════

with tab_policy:
    st.subheader("Policy Alignment")
    st.markdown(
        "Cross-reference NDAA, NDS, and NSS policy documents against actual "
        "R-1 budget allocations. First load takes ~5 seconds (uses cached embeddings)."
    )

    pol_sub = st.tabs([
        "🎯  Gap Analysis",
        "📄  PE → Policy",
        "🗺  NDS Priority Map",
    ])

    # ── Shared: lazy-load the policy linker ───────────────────────────────────
    # Loaded on first interaction with this tab, then cached.

    # ══ Sub-tab 1 — Gap Analysis ══════════════════════════════════════════════
    with pol_sub[0]:
        st.markdown(
            "Enter a defence priority topic. See which programs fund it "
            "and whether spending went up or down after policy was published."
        )

        col_g1, col_g2 = st.columns([4, 1])
        gap_query = col_g1.text_input(
            "Policy topic",
            placeholder="e.g.  hypersonic strike  ·  integrated deterrence  ·  cyber warfare",
            key="gap_query",
        )
        col_s1, col_s2, col_s3 = st.columns(3)
        gap_start = col_s1.slider("Start FY", 2015, 2024, 2020, key="gap_start")
        gap_end   = col_s2.slider("End FY",   2016, 2026, 2026, key="gap_end")
        gap_dtype = col_s3.multiselect(
            "Doc types",
            ["NDS", "NSS", "NDAA"],
            default=["NDS"],
            key="gap_dtype",
        )

        if st.button("Run Gap Analysis", type="primary", key="run_gap"):
            if not gap_query.strip():
                st.warning("Enter a topic first.")
            else:
                status_pol = st.empty()
                if "policy_linker_loaded" not in st.session_state:
                    status_pol.info("⏳ Loading policy embeddings from cache (~5s)…")
                pol_linker = _get_policy_linker()
                st.session_state["policy_linker_loaded"] = True
                status_pol.empty()

                with st.spinner("Analysing…"):
                    df_gap = pol_linker.gap_analysis(
                        gap_query.strip(),
                        start_fy=gap_start,
                        end_fy=gap_end,
                        doc_type_filter=gap_dtype or None,
                        top_n_pes=10,
                    )

                if df_gap.is_empty():
                    st.warning("No matching programs found. Try a broader topic.")
                else:
                    # ── Summary metrics ────────────────────────────────────
                    fy_cols = sorted(
                        [c for c in df_gap.columns if c.startswith("FY")
                         and c.endswith("$M")],
                        key=lambda x: int(x[2:6])
                    )
                    n_up   = df_gap.filter(pl.col("funding_trend") == "↑ UP").height
                    n_down = df_gap.filter(pl.col("funding_trend") == "↓ DOWN").height
                    n_flat = df_gap.filter(pl.col("funding_trend") == "→ FLAT").height

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Programs matched", len(df_gap))
                    m2.metric("↑ Funding up",   n_up)
                    m3.metric("↓ Funding down", n_down)
                    m4.metric("→ Flat",          n_flat)

                    # ── Trend chart ────────────────────────────────────────
                    if fy_cols and len(df_gap) > 0:
                        import matplotlib.pyplot as plt
                        import matplotlib.ticker as mticker

                        fig, ax = plt.subplots(figsize=(12, 4))
                        fig.patch.set_facecolor("#fafafa")
                        ax.set_facecolor("#fafafa")

                        df_pd = df_gap.to_pandas()
                        for _, row in df_pd.head(6).iterrows():
                            vals = [row.get(c, 0) or 0 for c in fy_cols]
                            years = [int(c[2:6]) for c in fy_cols]
                            ax.plot(
                                years, vals,
                                marker="o", markersize=4, linewidth=1.8,
                                label=row.get("pe_number", ""),
                            )

                        ax.set_title(
                            f"BY Request Funding — '{gap_query}' matched programs",
                            fontsize=10, loc="left"
                        )
                        ax.set_ylabel("$M")
                        ax.yaxis.set_major_formatter(
                            mticker.FuncFormatter(lambda x, _: f"${x:,.0f}M")
                        )
                        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
                        ax.tick_params(axis="x", rotation=45, labelsize=8)
                        ax.tick_params(axis="y", labelsize=8)
                        ax.grid(axis="y", color="#e0e0e0", linewidth=0.7, zorder=0)
                        ax.spines[["top", "right"]].set_visible(False)
                        ax.legend(
                            loc="upper left", bbox_to_anchor=(1.01, 1),
                            fontsize=8, frameon=False,
                        )
                        plt.tight_layout()
                        st.pyplot(fig)
                        plt.close(fig)

                    # ── Results table ──────────────────────────────────────
                    display_cols = (
                        ["pe_number", "program_name", "agency",
                         "relevance_score", "funding_trend"]
                        + fy_cols
                    )
                    display_cols = [c for c in display_cols if c in df_gap.columns]
                    st.dataframe(
                        df_gap.select(display_cols).to_pandas(),
                        use_container_width=True,
                    )

                    # ── Policy context ─────────────────────────────────────
                    with st.expander("📄 Supporting policy excerpts"):
                        pol_hits = pol_linker.query_policy(
                            gap_query.strip(), top_n=5,
                            doc_type_filter=gap_dtype or None,
                        )
                        if not pol_hits.is_empty():
                            for row in pol_hits.to_dicts():
                                st.markdown(
                                    f"**{row['doc_type']} {row['year']} "
                                    f"— {row['section_title'] or ''}**  "
                                    f"*(score: {row['score']:.2f})*"
                                )
                                st.caption(row["text"][:500])
                                st.divider()

                    # ── Download ───────────────────────────────────────────
                    st.download_button(
                        "⬇️ Download results (CSV)",
                        data=df_gap.to_pandas().to_csv(index=False),
                        file_name=f"gap_analysis_{gap_query[:30].replace(' ','_')}.csv",
                        mime="text/csv",
                    )

    # ══ Sub-tab 2 — PE → Policy ═══════════════════════════════════════════════
    with pol_sub[1]:
        st.markdown(
            "Enter a PE number or program name to find the policy language "
            "— NDAA sections, NDS passages — that covers it."
        )

        pe_pol_input = st.text_input(
            "PE number or program name",
            placeholder="e.g.  0604114A  ·  LTAMDS  ·  hypersonics",
            key="pe_pol_input",
        )
        pe_pol_types = st.multiselect(
            "Doc types to search",
            ["NDS", "NSS", "NDAA"],
            default=["NDS", "NDAA"],
            key="pe_pol_types",
        )

        if st.button("Find Policy References", type="primary", key="run_pe_pol"):
            if not pe_pol_input.strip():
                st.warning("Enter a PE number or name first.")
            else:
                status_pol2 = st.empty()
                if "policy_linker_loaded" not in st.session_state:
                    status_pol2.info("⏳ Loading policy embeddings from cache (~5s)…")
                pol_linker = _get_policy_linker()
                st.session_state["policy_linker_loaded"] = True
                status_pol2.empty()

                with st.spinner("Searching policy documents…"):
                    df_pol = pol_linker.pe_to_policy(
                        pe_pol_input.strip(),
                        top_n=10,
                        doc_type_filter=pe_pol_types or None,
                    )

                if df_pol.is_empty():
                    st.warning("No policy references found.")
                else:
                    st.caption(f"{len(df_pol)} policy references found")
                    for row in df_pol.to_dicts():
                        score = row["score"]
                        badge = (
                            "🟢" if score >= 0.55
                            else "🟡" if score >= 0.40
                            else "🟠"
                        )
                        st.markdown(
                            f"{badge} **{row['doc_type']} {row['year']}"
                            f" — {row['section_title'] or 'Unknown Section'}**"
                            f"  *(similarity: {score:.2f})*"
                        )
                        st.caption(row["text"][:600])
                        st.divider()

    # ══ Sub-tab 3 — NDS Priority Map ══════════════════════════════════════════
    with pol_sub[2]:
        st.markdown(
            "Map every NDS section to its most relevant budget programs. "
            "Useful for understanding which programs operationalise each strategic priority."
        )

        nds_yr = st.selectbox(
            "NDS year",
            [2022, 2018, 2014],
            index=0,
            key="nds_map_year",
        )

        if st.button("Generate NDS → PE Map", type="primary", key="run_nds_map"):
            status_pol3 = st.empty()
            if "policy_linker_loaded" not in st.session_state:
                status_pol3.info("⏳ Loading policy embeddings from cache (~5s)…")
            pol_linker = _get_policy_linker()
            st.session_state["policy_linker_loaded"] = True
            status_pol3.empty()

            with st.spinner(
                f"Mapping NDS {nds_yr} sections to PE programs "
                "(may take ~30s)…"
            ):
                df_map = pol_linker.nds_priority_mapping(
                    nds_year=nds_yr,
                    top_pes_per_section=5,
                )

            if df_map.is_empty():
                st.warning(
                    f"No NDS {nds_yr} data found. "
                    "Check that the document was parsed into the DB."
                )
            else:
                st.caption(
                    f"{df_map['nds_section'].n_unique()} NDS sections · "
                    f"{len(df_map)} PE mappings"
                )
                st.dataframe(
                    df_map.to_pandas(),
                    use_container_width=True,
                    height=500,
                )
                st.download_button(
                    "⬇️ Download mapping (CSV)",
                    data=df_map.to_pandas().to_csv(index=False),
                    file_name=f"nds_{nds_yr}_pe_mapping.csv",
                    mime="text/csv",
                )