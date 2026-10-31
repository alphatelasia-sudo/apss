"""Alphatel Partner Support System (APSS) — main entry point."""
from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from core import auth
from core.db import engine, get_setting, set_setting

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

st.markdown("""
<style>
[data-testid="stSidebarHeader"] {
    min-height: 0 !important;
    height: auto !important;
    padding: 8px 16px !important;
}
[data-testid="stLogoSpacer"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.image("static/logo.png", width=190)

def _check_overdue_tickets():
    """Send Lark alerts for tickets past due_date. Runs at most once per hour."""
    try:
        # Skip entirely if Lark not enabled — don't consume the hourly slot
        if get_setting("lark_enabled", "false").lower() != "true":
            return
        last = get_setting("last_overdue_check", "")
        if last:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last_dt < timedelta(hours=1):
                return
        set_setting("last_overdue_check", datetime.now(timezone.utc).isoformat())
        with engine().connect() as con:
            rows = con.execute(text("""
                SELECT * FROM tickets
                WHERE due_date IS NOT NULL
                  AND due_date < NOW()
                  AND status NOT IN ('Resolved', 'Closed')
                  AND due_notified_at IS NULL
            """)).fetchall()
        if not rows:
            return
        from core.lark import notify_ticket_overdue
        now = datetime.now(timezone.utc)
        for r in rows:
            d = dict(r._mapping)
            sent = notify_ticket_overdue(d)
            # Only mark as notified if Lark actually delivered the message
            if sent:
                with engine().begin() as con:
                    con.execute(text(
                        "UPDATE tickets SET due_notified_at = :now WHERE ticket_id = :id"
                    ), {"now": now, "id": d["ticket_id"]})
    except Exception:
        pass  # never break the app over notification errors


auth.gate()
_check_overdue_tickets()

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
