"""End-to-end smoke checks for the default Streamlit render."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_default_page_renders_data_not_just_imports() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert len(app.get("vega_lite_chart")) >= 1
    assert len(app.dataframe) >= 1


def test_configured_demo_allowlist_fails_closed_for_anonymous_user(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEMO_ALLOWED_EMAILS", "owner@example.com")
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Private demo"]
    assert len(app.get("vega_lite_chart")) == 0
