"""Source-linked executive PDF snapshots. No Streamlit, network or AI calls."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import re
from threading import RLock
import textwrap

from matplotlib import rc_context
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib import font_manager, ft2font
from matplotlib.lines import Line2D
import pandas as pd

from analysis.portfolios import PortfolioSnapshot


_PDF_LOCK = RLock()  # Matplotlib's font/config state is process-wide.
_INK, _BLUE, _MUTED = "#132D46", "#2474AB", "#526579"
_LINE = "#D5E0EA"


def _lines(value: str, width: int) -> list[str]:
    """Preserve paragraphs, wrap long identifiers, and leave dollar signs literal."""
    result = []
    for paragraph in value.expandtabs(4).splitlines() or [""]:
        for line in textwrap.wrap(paragraph, width=width, break_long_words=True,
                                  break_on_hyphens=False) or [""]:
            if line or not result or result[-1]:
                result.append(line)
    return result


def _money(value_k, *, signed=False) -> str:
    if value_k is None or pd.isna(value_k):
        return "Not observed"
    return f"{float(value_k) / 1000:+,.1f}" if signed else f"{float(value_k) / 1000:,.1f}"


def _total(series) -> float | None:
    value = series.sum(min_count=1)
    return None if pd.isna(value) else float(value)


def _field(value, label: str, limit: int, *, required=False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{label} must be text of at most {limit} characters.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label} is required.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{label} contains unsupported control characters.")
    return value


def export_pdf(snapshot: PortfolioSnapshot, *, title: str,
               prepared_for: str = "", decision: str = "",
               archive_sha256: str, generated_at: datetime | None = None) -> bytes:
    """Create a fixed PDF of the saved comparison, including every selected row.

    Amounts in the snapshot are $K, converted to $M only for presentation.
    Cohort change uses only programs observed in both submissions. Missing
    observations are never treated as zero, including component chart totals.
    """
    title = " ".join(_field(title, "Briefing title", 120, required=True).split())
    prepared_for = " ".join(_field(prepared_for, "Audience", 120).split())
    decision = _field(decision, "Decision or discussion requested", 1500)
    if not re.fullmatch(r"[a-f0-9]{64}", archive_sha256):
        raise ValueError("A SHA-256 identifier for the budget archive is required.")
    if snapshot.rows.empty:
        raise ValueError("Add programs to the collection before exporting a briefing.")
    # Fail visibly rather than replacing unsupported user text with blank boxes.
    glyphs = ft2font.FT2Font(font_manager.findfont("DejaVu Sans")).get_charmap()
    all_text = title + prepared_for + decision + str(snapshot.collection) + str(snapshot.sources)
    all_text += " ".join(snapshot.rows[["pe_number", "agency", "program_name"]].astype(str).values.ravel())
    if any(ord(c) not in glyphs and not c.isspace() for c in all_text):
        raise ValueError("Some text uses characters this PDF font cannot display. Use Latin, Greek or Cyrillic text for this export; keep the original in your JSON backup.")
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ValueError("The generation time must include a time zone.")
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    settings = snapshot.collection["settings"]
    older, newer = settings["older_pb"], settings["newer_pb"]
    basis = "Constant FY2025 dollars" if settings["basis"] == "constant-2025" else "Then-year dollars"
    scope = f"PB{older} FY{older} request / PB{newer} FY{newer} request | {basis} | $M"
    rows = snapshot.rows
    cohort = rows.loc[rows["before_k"].notna() & rows["after_k"].notna()]
    output = BytesIO()
    page_number = 0

    def text(fig, x, y, value, *, size=10, color=_INK, weight="normal", **kwargs):
        return fig.text(x / 11, y / 8.5, value, fontsize=size, color=color,
                        fontweight=weight, va="top", parse_math=False, **kwargs)

    def page(heading):
        fig = Figure(figsize=(11, 8.5), facecolor="white")
        text(fig, .55, 8.05, "DOD BUDGET EXPLORER  /  EXECUTIVE BRIEFING", size=9,
             weight="bold", color=_BLUE)
        text(fig, .55, 7.65, heading, size=19, weight="bold")
        text(fig, .55, 7.15, scope, size=9, color=_MUTED)
        return fig

    def save(pdf, fig):
        nonlocal page_number
        page_number += 1
        fig.add_artist(Line2D(
            [.05, .95], [.075, .075], transform=fig.transFigure, color=_LINE, linewidth=.7))
        text(fig, .55, .48, f"Generated {stamp} | Bundled archive SHA-256 {archive_sha256[:12]}", size=8, color=_MUTED)
        text(fig, 10.45, .48, f"Page {page_number}", size=8, color=_MUTED, ha="right")
        pdf.savefig(fig)
        fig.clear()

    # Render within a lock without pyplot's shared figure registry. No user data
    # is cached or written to disk; each caller receives their own bytes.
    with _PDF_LOCK, rc_context({"font.family": "DejaVu Sans", "pdf.fonttype": 42,
                               "text.parse_math": False}), PdfPages(output, metadata={
        "Title": title, "Author": "DoD Budget Explorer", "Subject": scope,
        "CreationDate": generated_at, "ModDate": generated_at,
        "Keywords": f"Budget requests; archive SHA-256 {archive_sha256}",
    }) as pdf:
        fig = page("Portfolio at a glance")
        title_lines = _lines(title, 73)
        text(fig, .55, 6.72, "\n".join(title_lines), size=15, weight="bold")
        if prepared_for:
            text(fig, .55, 6.15, "Prepared for: " + "\n".join(_lines(prepared_for, 100)), size=10)
        metrics = [
            (f"FY{newer} covered requests ($M)", _money(_total(rows["after_k"]))),
            ("Comparable-cohort change ($M)", _money(_total(cohort["delta_k"]), signed=True)),
            ("Programs flagged for review", f"{len(snapshot.flagged)} / {len(rows)}"),
        ]
        for x, (label, value) in zip([.55, 4.0, 7.45], metrics):
            text(fig, x, 5.65, label, size=10, color=_MUTED)
            text(fig, x, 5.30, value, size=23, weight="bold")
        text(fig, .55, 4.65, "Covered request totals by component ($M)", size=12, weight="bold")
        grouped = rows.groupby("agency", sort=True)[["before_k", "after_k"]].sum(min_count=1) / 1000
        grouped = grouped.dropna(how="all")
        if len(grouped) > 6:
            grouped = grouped.assign(_rank=grouped.max(axis=1)).sort_values("_rank", ascending=False).drop(columns="_rank")
            other = grouped.iloc[5:].sum(min_count=1).to_frame().T
            other.index = ["Other components"]
            grouped = pd.concat([grouped.iloc[:5], other])
        ax = fig.add_axes([.20, .19, .40, .32])
        positions = list(range(len(grouped)))
        height = .32
        for column, offset, color, label in [
            ("before_k", -height / 2, "#A7BFCE", f"FY{older}"),
            ("after_k", height / 2, _BLUE, f"FY{newer}"),
        ]:
            for i, value in enumerate(grouped[column]):
                if not pd.isna(value):
                    ax.barh(i + offset, value, height=height, color=color,
                            label=label if i == next((j for j, v in enumerate(grouped[column]) if not pd.isna(v)), -1) else None)
                else:
                    ax.text(0, i + offset, " Not observed", fontsize=7, va="center", color=_MUTED)
        ax.set_yticks(positions, ["\n".join(_lines(str(name), 21)[:2]) for name in grouped.index], fontsize=9)
        if grouped.empty:
            ax.text(.5, .5, "No request observations", transform=ax.transAxes, ha="center", color=_MUTED)
            ax.set_axis_off()
        ax.invert_yaxis()
        ax.tick_params(axis="x", labelsize=8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(_LINE)
        ax.set_xlabel("Request ($M)", fontsize=9)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="upper left", bbox_to_anchor=(0, 1.24), frameon=False, ncol=2, fontsize=9)
        cover = [
            "COVERAGE AND INTERPRETATION", "",
            f"FY{older}: {rows['before_k'].notna().sum()} of {len(rows)} programs observed.",
            f"FY{newer}: {rows['after_k'].notna().sum()} of {len(rows)} programs observed.",
            f"Comparable cohort: {len(cohort)} of {len(rows)} programs.", "",
            "Totals cover observed requests only. Different coverage can change totals.", "",
            "Discretionary requests only; these are not enacted appropriations, obligations or outlays.",
        ]
        text(fig, 7.15, 4.65, "\n".join(line for p in cover for line in _lines(p, 43)), size=10,
             linespacing=1.4)
        text(fig, .55, 1.02, "Missing observations do not establish a start, transfer or cancellation. See all programs and sources on following pages.",
             size=9, color=_MUTED)
        save(pdf, fig)

        # Analyst-authored context is explicitly labelled and paginated in full.
        context = []
        for heading, value in [
            ("Decision or discussion requested (analyst-provided)", decision),
            ("Saved collection notes (analyst-provided)", snapshot.collection["notes"]),
        ]:
            if value:
                context.extend([(heading, True), ("", False)])
                context.extend((line, False) for line in _lines(value, 112))
                context.extend([("", False), ("", False)])
        for start in range(0, len(context), 31):
            fig = page("Analyst context" + (" / continued" if start else ""))
            text(fig, .55, 6.65, "User-supplied commentary; not an official source finding or an AI-generated assessment.",
                 size=9, color=_MUTED)
            for i, (line, bold) in enumerate(context[start:start + 31]):
                text(fig, .55, 6.18 - i * .165, line, size=10, weight="bold" if bold else "normal")
            save(pdf, fig)

        # Six rows per page leave space for multi-line program names and
        # presence descriptions, including the longest imported identifiers.
        for start in range(0, len(rows), 6):
            fig = page("Program comparison" + (" / continued" if start else ""))
            text(fig, .55, 6.65, f"All selected programs: {start + 1}-{min(start + 6, len(rows))} of {len(rows)}. Amounts in $M.", size=10)
            columns = [(.55, "PROGRAM / COMPONENT"), (5.25, f"FY{older}"), (6.40, f"FY{newer}"),
                       (7.55, "CHANGE"), (8.60, "%"), (9.32, "REVIEW")]
            for x, label in columns:
                text(fig, x, 6.18, label, size=9, color=_MUTED, weight="bold")
            y = 5.82
            for row in rows.iloc[start:start + 6].itertuples():
                identity = _lines(f"{row.pe_number} | {row.agency}", 57)
                text(fig, .55, y, "\n".join(identity[:2]), size=9, weight="bold")
                text(fig, .55, y - .31, "\n".join(_lines(row.program_name, 59)[:2]), size=9)
                # Full names, including unusually long names, are preserved in
                # the source appendix below if this summary requires shortening.
                if len(_lines(row.program_name, 59)) > 2 or len(identity) > 2:
                    text(fig, .55, y - .60, "Full program identity in appendix", size=7, color=_MUTED)
                for x, value in [(5.25, _money(row.before_k)), (6.40, _money(row.after_k)),
                                 (7.55, _money(row.delta_k, signed=True)),
                                 (8.60, "n/a" if pd.isna(row.pct_change) else f"{row.pct_change:+,.1f}"),
                                 (9.32, "Flag" if row.flagged else "-")]:
                    text(fig, x, y, "\n".join(_lines(value, 13)), size=8)
                text(fig, 5.25, y - .28, row.status, size=8, color=_MUTED)
                y -= .78
            text(fig, .55, 1.02, "Change uses paired observations only. Percent is undefined for a zero baseline or a missing observation.", size=9, color=_MUTED)
            save(pdf, fig)

        appendix = [
            "METHOD AND WATCH RULES", "",
            f"Collection: {snapshot.collection['name']} ({snapshot.collection['kind']}).",
            f"Comparison: annual discretionary BY Request, fiscal year equals PB cycle ({older} and {newer}).",
            f"Dollar basis: {basis}. Funding source values are $K; report values are $M ($K / 1,000).",
            "Mandatory funding, CY estimates, PY actuals, authorization actions, execution and awards are excluded.",
            "Multiple budget-activity lines for the same PE/component in a cycle are summed. Components are never cross-matched.",
            "Comparable-cohort change sums changes only for programs observed in both submissions; no cohort means Not observed.",
            f"A nonzero comparable movement must meet BOTH |change| >= ${settings['min_change_m']:,.2f}M and |percent| >= {settings['min_change_pct']:,.2f}%.",
            f"Presence-change flags: {'enabled' if settings['include_presence'] else 'disabled'} (newly observed, no longer observed, or changed from zero).",
            "Percent change = (new request - old request) / |old request| x 100. A zero baseline has no defined percent.",
            "Absence of a request observation is not evidence of termination, transfer or cancellation. Review official source context.",
            "This PDF is a fixed download, not a live alert or a complete archive. Save the JSON collection backup separately.",
            "Generated UTC timestamp records export time, not source publication or data-refresh time.",
            f"Bundled archive SHA-256: {archive_sha256}",
            "The archive identifier names the shipped compressed data file. A locally extended database can contain additional observations.", "",
        ]
        if settings["basis"] == "constant-2025":
            appendix.extend(["Constant dollars use the existing RDT&E deflator for each request's own fiscal year; see deflator source below.", ""])
        for row in rows.itertuples():
            if len(_lines(row.program_name, 59)) > 2 or len(_lines(f"{row.pe_number} | {row.agency}", 57)) > 2:
                appendix.extend([f"Full program name: {row.pe_number} | {row.agency} | {row.program_name}", ""])
        appendix.extend(["SUPPORTING SOURCE DOCUMENTS", ""])
        if not snapshot.sources:
            appendix.append("No source observations were found for these selected programs and cycles.")
        for i, source in enumerate(snapshot.sources, 1):
            year = source.get("publication_year")
            cycle = (f"PB{year}" if year and source.get("document_type") in {"R1", "P1"}
                     else f"Reference year: {year or 'not recorded'}")
            appendix.append(f"[{i}] {source.get('filename', 'Source')} | {source.get('document_type', '')} | {cycle}")
            appendix.append(f"Retrieved: {source.get('retrieved_at') or 'not recorded'} | processed: {source.get('processed_date') or 'not recorded'}")
            appendix.append(source.get("source_url") or "Source URL not recorded in the archive.")
            appendix.append("")
        appendix_lines = [(line, str(paragraph) if str(paragraph).startswith(("https://", "http://")) else None)
                          for paragraph in appendix for line in _lines(str(paragraph), 126)]
        for start in range(0, len(appendix_lines), 34):
            fig = page("Method and sources" + (" / continued" if start else ""))
            for i, (line, url) in enumerate(appendix_lines[start:start + 34]):
                kwargs = {"url": url} if url else {}
                text(fig, .55, 6.65 - i * .167, line, size=9, **kwargs)
            save(pdf, fig)
    return output.getvalue()
