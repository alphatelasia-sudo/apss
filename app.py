"""Alphatel Partner Support System (APSS) — main entry point."""
import streamlit as st
from sqlalchemy.exc import OperationalError

from core import auth
from core.db import engine

st.set_page_config(
    page_title="APSS — Alphatel Partner Support",
    page_icon="assets/favicon.png",
    layout="wide",
)

# Bootstrap DB / catch config errors early
try:
    engine()
except OperationalError as e:
    msg = "Password authentication failed" if "password authentication" in str(e) else str(e)
    st.error(f"Database connection failed: {msg}")
    st.stop()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

st.logo("static/logo.png", size="large")

# st.logo() caps img at 2rem via inline style — override by using the static URL
# as a CSS background-image (/app/static/ is same-origin, not blocked by Cloud CSP).
st.markdown("""
<style>
[data-testid="stSidebarHeader"] {
    height: 80px !important;
    min-height: 80px !important;
}
[data-testid="stLogoSpacer"] {
    width: 200px !important;
    height: 64px !important;
    min-height: 64px !important;
    background: url('/app/static/logo.png') no-repeat left center !important;
    background-size: contain !important;
}
[data-testid="stLogoSpacer"] img,
[data-testid="stLogoSpacer"] a img {
    opacity: 0 !important;
    width: 1px !important;
    height: 1px !important;
}
</style>
""", unsafe_allow_html=True)

auth.gate()

MENU = {
    "Support": [
        ("views/dashboard.py",  "Dashboard",  "📊", "dashboard"),
        ("views/tickets.py",    "Tickets",    "🎫", "tickets"),
    ],
    "Management": [
        ("views/hotels.py",     "Hotels",     "🏨", "hotels"),
        ("views/agents.py",     "Agents",     "👥", "agents"),
        ("views/reports.py",    "Reports",    "📈", "reports"),
        ("views/settings.py",   "Settings",   "⚙️", "settings"),
    ],
}

home = list(MENU.values())[0][0]
st.navigation(
    {group: [st.Page(f, title=ti, icon=ic, url_path=u, default=(f, ti, ic, u) == home)
             for f, ti, ic, u in items]
     for group, items in MENU.items()}
).run()
