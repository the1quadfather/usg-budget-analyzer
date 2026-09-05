"""
analysis/text_render.py

Helpers for text that is handed to Streamlit's markdown renderer.

Streamlit renders `st.markdown`, `st.write(str)` and `st.caption` through a
markdown pipeline with single-dollar LaTeX enabled and no way to turn it off,
so any string carrying two dollar amounts -- "$91.0M ... $1,654.9M" -- has the
span between them parsed as an inline math expression. The text survives, but
in a monospace math chip with markdown markup shown literally. Budget prose is
full of dollar amounts, so every dynamic string that reaches those calls goes
through `escape_dollars()` first.
"""

_ESCAPED_DOLLAR = chr(92) + "$"   # a backslash then "$": CommonMark's escape


def escape_dollars(text: str | None) -> str:
    """
    Backslash-escape every "$" so markdown shows it as a literal dollar sign.

    Escape AFTER any truncation (`text[:500]`), never before, so a slice can
    never end in a dangling backslash. Idempotent on already-escaped text.
    """
    if not text:
        return ""
    return text.replace(_ESCAPED_DOLLAR, "$").replace("$", _ESCAPED_DOLLAR)
