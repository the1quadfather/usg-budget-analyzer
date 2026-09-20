"""End-to-end smoke checks for the default Streamlit render."""

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest


MAIN_TAB_LABELS = [
    "Trends",
    "Programs",
    "Rhetoric vs. Budget",
    "Coverage",
]
PROFILE_TAB_LABELS = [
    "Funding",
    "Justification",
    "Awards",
    "News",
]


def _main_tab_labels(app: AppTest) -> list[str]:
    return [
        tab.label for tab in app.get("tab")
        if tab.label in MAIN_TAB_LABELS
    ]


def _profile_tab_labels(app: AppTest) -> list[str]:
    return [
        tab.label for tab in app.get("tab")
        if tab.label in PROFILE_TAB_LABELS
    ]


def test_default_page_renders_data_not_just_imports() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert len(app.get("vega_lite_chart")) >= 1
    assert len(app.dataframe) >= 1
    coverage_tab = next(
        tab for tab in app.get("tab") if tab.label == "Coverage"
    )
    assert any(
        "Reconciliation" in header.value for header in coverage_tab.subheader
    )


def test_program_finder_rerun_keeps_tab_content_mapped(monkeypatch) -> None:
    """A search rerun must not reorder index-keyed frontend tab panels."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.query_params["tab"] = "finder"
    app.query_params["view"] = "plans"
    app.run()

    assert _main_tab_labels(app) == MAIN_TAB_LABELS
    assert app.session_state["main_tab"] == "Programs"

    # Skip persistent demand logging in this deterministic UI test.
    app.session_state["_logged_query"] = "0601102A"
    app.text_input(key="program_query").input("0601102A").run()

    assert not app.exception
    assert _main_tab_labels(app) == MAIN_TAB_LABELS
    assert app.session_state["main_tab"] == "Programs"
    assert _profile_tab_labels(app) == PROFILE_TAB_LABELS
    assert app.session_state["profile_tab::0601102A::Army"] == "Justification"
    assert any(metric.label == "Net current program" for metric in app.metric)


def test_ask_the_corpus_renders_passages_without_a_key(monkeypatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    st.cache_resource.clear()
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=120)
    app.query_params["tab"] = "finder"
    app.run()

    app.text_input(key="corpus_question").input(
        "Skyborg autonomous aircraft vanguard program"
    ).run()

    assert not app.exception
    passage_expander = next(
        expander for expander in app.expander
        if expander.label.startswith("Passages (")
    )
    assert any(
        "0603032F" in markdown.value
        for markdown in passage_expander.markdown
    )
    assert not any(
        button.label == "Answer with AI"
        for button in app.button
    )
    assert _main_tab_labels(app) == MAIN_TAB_LABELS
    assert app.session_state["main_tab"] == "Programs"


def test_transition_panel_renders_inference_label(monkeypatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    st.cache_data.clear()
    st.cache_resource.clear()
    app_path = Path(__file__).parents[1] / "app.py"

    def render(pe_number: str, agency: str) -> AppTest:
        app = AppTest.from_file(str(app_path), default_timeout=120)
        app.query_params["tab"] = "finder"
        app.query_params["pe"] = pe_number
        app.query_params["agency"] = agency
        app.run()
        assert not app.exception
        assert _main_tab_labels(app) == MAIN_TAB_LABELS
        assert app.session_state["main_tab"] == "Programs"
        assert _profile_tab_labels(app) == PROFILE_TAB_LABELS
        assert any(
            expander.label == "Procurement transition"
            for expander in app.expander
        )
        assert any(
            ">Inference<" in markdown.value for markdown in app.markdown
        )
        return app

    transition_app = render("0207146F", "Air Force")
    funding_tab = next(
        tab for tab in transition_app.get("tab") if tab.label == "Funding"
    )
    assert any(
        "F015EX" in dataframe.value.to_string()
        for dataframe in funding_tab.dataframe
    )

    research_app = render("0601102A", "Army")
    research_tab = next(
        tab for tab in research_app.get("tab") if tab.label == "Funding"
    )
    assert any(
        "Basic and applied research" in caption.value
        for caption in research_tab.caption
    )

    empty_app = render("0605018F", "Air Force")
    empty_tab = next(
        tab for tab in empty_app.get("tab") if tab.label == "Funding"
    )
    assert any(
        "No procurement line" in caption.value
        for caption in empty_tab.caption
    )


def test_verified_facts_panel_states(monkeypatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    st.cache_data.clear()
    st.cache_resource.clear()
    app_path = Path(__file__).parents[1] / "app.py"

    def render(pe_number: str, agency: str) -> AppTest:
        app = AppTest.from_file(str(app_path), default_timeout=120)
        app.query_params["tab"] = "finder"
        app.query_params["pe"] = pe_number
        app.query_params["agency"] = agency
        app.query_params["view"] = "plans"
        app.run()
        assert not app.exception
        assert _main_tab_labels(app) == MAIN_TAB_LABELS
        assert app.session_state["main_tab"] == "Programs"
        assert _profile_tab_labels(app) == PROFILE_TAB_LABELS
        return app

    facts_app = render("0101226N", "Navy")
    facts_tab = next(
        tab for tab in facts_app.get("tab") if tab.label == "Justification"
    )
    assert any(
        expander.label.startswith("Extracted facts (")
        for expander in facts_tab.expander
    )
    assert any(
        "Developmental Testing" in dataframe.value.to_string()
        for dataframe in facts_tab.dataframe
    )

    empty_app = render("0603032F", "Air Force")
    empty_tab = next(
        tab for tab in empty_app.get("tab") if tab.label == "Justification"
    )
    assert any(
        "not yet been extracted" in caption.value
        for caption in empty_tab.caption
    )

    coverage_app = AppTest.from_file(str(app_path), default_timeout=120)
    coverage_app.query_params["tab"] = "coverage"
    coverage_app.run()
    assert not coverage_app.exception
    coverage_tab = next(
        tab for tab in coverage_app.get("tab")
        if tab.label == "Coverage"
    )
    assert any(
        "Extracted facts:" in caption.value
        for caption in coverage_tab.caption
    )


def test_no_parenthetical_qualifiers_in_labels() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    source = app_path.read_text(encoding="utf-8")

    assert "(AI)" not in source
    assert "(inference)" not in source


def test_configured_demo_allowlist_fails_closed_for_anonymous_user(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEMO_ALLOWED_EMAILS", "owner@example.com")
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Private demo"]
    assert len(app.get("vega_lite_chart")) == 0
