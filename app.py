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

with st.sidebar:
    st.image("static/logo.png", width=190)

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
