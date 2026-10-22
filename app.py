"""Alphatel Partner Support System (APSS) — main entry point."""
import streamlit as st
import streamlit.components.v1 as components
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

st.logo("assets/logo.png", size="large")

# Force logo resize via JS (Streamlit caps st.logo height internally)
components.html("""
<script>
function resizeLogo() {
    var doc = window.parent.document;
    var selectors = [
        '[data-testid="stSidebarHeader"] img',
        '[data-testid="stLogo"] img',
        '[data-testid="stLogoLink"] img',
        'section[data-testid="stSidebar"] header img',
    ];
    var found = false;
    selectors.forEach(function(sel) {
        doc.querySelectorAll(sel).forEach(function(img) {
            img.style.setProperty('height', '80px', 'important');
            img.style.setProperty('max-height', 'none', 'important');
            img.style.setProperty('width', 'auto', 'important');
            img.style.setProperty('max-width', '200px', 'important');
            found = true;
        });
    });
    return found;
}
// Try immediately and retry until found
var tries = 0;
var interval = setInterval(function() {
    if (resizeLogo() || tries++ > 20) clearInterval(interval);
}, 200);
// Also watch for DOM changes (Streamlit re-renders)
var observer = new MutationObserver(resizeLogo);
observer.observe(window.parent.document.body, {childList: true, subtree: true});
</script>
""", height=0)

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
