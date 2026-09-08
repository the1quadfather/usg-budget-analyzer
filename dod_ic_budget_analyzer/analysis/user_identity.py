"""Per-user identity helpers for AI history and spend accounting."""

import secrets


def streamlit_user_id(st) -> str:
    """
    Return a durable authenticated ID or an anonymous Streamlit-session ID.

    A shared anonymous fallback such as ``local`` would let one visitor read
    another visitor's grounded-result history. Anonymous IDs intentionally
    last only for the current Streamlit session.
    """
    try:
        if st.user.is_logged_in:
            subject = getattr(st.user, "sub", None)
            email = getattr(st.user, "email", None)
            if subject or email:
                return f"user:{subject or email}"
    except Exception:
        pass

    if "_anonymous_user_id" not in st.session_state:
        st.session_state["_anonymous_user_id"] = (
            f"anon:{secrets.token_urlsafe(24)}"
        )
    return st.session_state["_anonymous_user_id"]
