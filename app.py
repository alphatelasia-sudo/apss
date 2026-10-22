"""Alphatel Partner Support System (APSS) — main entry point."""
import streamlit as st
from sqlalchemy.exc import OperationalError

from core import auth
from core.db import engine

st.set_page_config(
    page_title="APSS — Alphatel Partner Support",
    page_icon="assets/logo.png",
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

st.logo("assets/logo.png", size="large")

# Override Streamlit's logo height cap
st.markdown("""
<style>
[data-testid="stSidebarHeader"] {
    padding-top: 0.75rem;
    padding-bottom: 0.75rem;
    min-height: 100px;
}
[data-testid="stSidebarHeader"] img,
[data-testid="stSidebarHeader"] > div img,
section[data-testid="stSidebar"] header img {
    max-height: none !important;
    height: 80px !important;
    width: auto !important;
    max-width: 200px !important;
    object-fit: contain !important;
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
