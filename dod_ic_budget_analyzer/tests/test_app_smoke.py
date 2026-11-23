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


def test_constant_dollars_toggle_and_permalink_render_without_errors() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.radio(key="dollar_basis").set_value("Constant FY2025").run()

    assert not app.exception
    assert len(app.get("vega_lite_chart")) >= 1
    assert app.query_params["dollars"] == "constant-2025"

    linked = AppTest.from_file(str(app_path), default_timeout=30)
    linked.query_params["dollars"] = "constant-2025"
    linked.run()

    assert not linked.exception
    assert linked.radio(key="dollar_basis").value == "Constant FY2025"
    assert len(linked.get("vega_lite_chart")) >= 1


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
    from analysis import transition

    def missing_semantic_model(*args, **kwargs):
        raise OSError("model is not cached")

    monkeypatch.setattr(
        transition, "_semantic_candidates", missing_semantic_model
    )
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
    empty_funding_tab = next(
        tab for tab in empty_app.get("tab") if tab.label == "Funding"
    )
    assert any(
        "Semantic title matching is unavailable" in caption.value
        for caption in empty_funding_tab.caption
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


def test_collections_create_edit_clone_and_restore_across_sessions(monkeypatch) -> None:
    """Exercise forms with the browser-storage transport replaced at its boundary."""
    saved = {"payload": None}

    def register(*args, **kwargs):
        def render(*, data, **mount_kwargs):
            if data["action"] == "save":
                saved["payload"] = data["payload"]
                status = "saved"
            else:
                status = "loaded"
            return {"response": {"id": data["id"], "status": status,
                                 "payload": saved["payload"]}}
        return render

    monkeypatch.setattr(st.components.v2, "component", register)
    st.cache_resource.clear()
    app_path = Path(__file__).parents[1] / "app.py"
    try:
        app = AppTest.from_file(str(app_path), default_timeout=30)
        app.query_params["tab"] = "finder"
        app.run()
        assert app.session_state["_collections_ready"]
        next(b for b in app.button if b.label == "Restore backup").click().run()
        assert any("confirm replacement" in e.value for e in app.error)
        assert not app.session_state["_collection_workspace"]["collections"]
        app.text_input(key="new_collection_name").input("Leadership")
        next(b for b in app.button if b.label == "Create collection").click().run()
        assert not app.exception
        assert len(app.session_state["_collection_workspace"]["collections"]) == 1
        members = next(m for m in app.multiselect if m.label == "Programs in this collection")
        members.set_value([("0601102A", "Army"), ("0602702E", "Defense-Wide")])
        next(b for b in app.button if b.label == "Save collection").click().run()
        assert not app.exception
        assert len(app.session_state["_collection_workspace"]["collections"][0]["members"]) == 2
        next(b for b in app.button if b.label == "Create watchlist from portfolio").click().run()
        assert not app.exception
        items = app.session_state["_collection_workspace"]["collections"]
        assert [i["kind"] for i in items] == ["portfolio", "watchlist"]
        next(b for b in app.button if b.label == "Generate briefing PDF").click().run()
        assert not app.exception
        assert app.session_state["_executive_briefing"]["payload"].startswith(b"%PDF-")
        assert any(b.label == "Download executive briefing PDF" for b in app.get("download_button"))
        # Editing briefing fields invalidates the old download until regenerated.
        next(t for t in app.text_area if t.label == "Decision or discussion requested (optional)").input("Review scope.").run()
        assert not any(b.label == "Download executive briefing PDF" for b in app.get("download_button"))
        from io import BytesIO
        import json
        backup = json.loads(saved["payload"])
        backup["collections"][0]["name"] = "Restored leadership"
        uploaded = BytesIO(json.dumps(backup).encode())
        uploaded.size = len(uploaded.getvalue())
        monkeypatch.setattr(st, "file_uploader", lambda *args, **kwargs: uploaded)
        app.checkbox(key="collection_replace").check()
        next(b for b in app.button if b.label == "Restore backup").click().run()
        assert not app.exception
        assert app.session_state["_collection_workspace"]["collections"][0]["name"] == "Restored leadership"
        restored = AppTest.from_file(str(app_path), default_timeout=30).run()
        assert not restored.exception
        assert len(restored.session_state["_collection_workspace"]["collections"]) == 2
        assert restored.session_state["_collection_workspace"]["collections"][0]["name"] == "Restored leadership"
        assert _main_tab_labels(restored) == MAIN_TAB_LABELS
    finally:
        st.cache_resource.clear()


def test_configured_demo_allowlist_fails_closed_for_anonymous_user(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEMO_ALLOWED_EMAILS", "owner@example.com")
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Private demo"]
    assert len(app.get("vega_lite_chart")) == 0
