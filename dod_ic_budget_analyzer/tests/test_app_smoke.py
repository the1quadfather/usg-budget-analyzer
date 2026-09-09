"""End-to-end smoke checks for the default Streamlit render."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


MAIN_TAB_LABELS = [
    "Budget Trends",
    "Program Finder",
    "Rhetoric vs. Budget",
    "Data Coverage",
]
PROFILE_TAB_LABELS = [
    "Funding",
    "Plans & Work",
    "Contracts & Awards",
    "In the News",
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


def test_program_finder_rerun_keeps_tab_content_mapped(monkeypatch) -> None:
    """A search rerun must not reorder index-keyed frontend tab panels."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.query_params["tab"] = "finder"
    app.query_params["view"] = "plans"
    app.run()

    assert _main_tab_labels(app) == MAIN_TAB_LABELS
    assert app.session_state["main_tab"] == "Program Finder"

    # Skip persistent demand logging in this deterministic UI test.
    app.session_state["_logged_query"] = "0601102A"
    app.text_input[0].input("0601102A").run()

    assert not app.exception
    assert _main_tab_labels(app) == MAIN_TAB_LABELS
    assert app.session_state["main_tab"] == "Program Finder"
    assert _profile_tab_labels(app) == PROFILE_TAB_LABELS
    assert app.session_state["profile_tab::0601102A::Army"] == "Plans & Work"
    assert any(metric.label == "Net current program" for metric in app.metric)


def test_configured_demo_allowlist_fails_closed_for_anonymous_user(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEMO_ALLOWED_EMAILS", "owner@example.com")
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Private demo"]
    assert len(app.get("vega_lite_chart")) == 0
