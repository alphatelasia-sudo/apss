"""Google Sign-in auth gate, mirroring the APC pattern with st.login."""
import streamlit as st


def gate():
    """Require Google sign-in when [auth] is configured in secrets; no-op otherwise."""
    try:
        auth_cfg = st.secrets.get("auth", {})
    except Exception:
        auth_cfg = {}
    if not auth_cfg:
        return  # local dev: open access
    if not st.user.is_logged_in:
        st.title("Alphatel Partner Support System")
        st.info("Please sign in with your Alphatel Google account to continue.")
        st.login()
        st.stop()
    email = st.user.email or ""
    if not email.endswith("@alphatel.asia"):
        st.error(f"Access denied: {email} is not an Alphatel account.")
        st.logout()
        st.stop()


def current_user() -> dict:
    """Return {email, name} for the signed-in user, or dev defaults."""
    try:
        u = st.user
        if u and u.is_logged_in:
            return {"email": u.email or "", "name": u.name or u.email or "User"}
    except Exception:
        pass
    return {"email": "dev@alphatel.asia", "name": "Dev User"}


def is_admin() -> bool:
    """True if the current user's agent record has the Admin role."""
    from core.db import engine
    from sqlalchemy import text
    user = current_user()
    with engine().connect() as con:
        role = con.execute(
            text("SELECT role_name FROM agents WHERE email = :e AND active = 1"),
            {"e": user["email"]}
        ).scalar()
    return role == "Admin"
