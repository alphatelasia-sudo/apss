"""Dashboard: ticket stats, SLA breaches, recent tickets."""
import streamlit as st
from sqlalchemy import text

from core.db import engine
from core.sla import sla_status

PRIORITY_COLOR = {"Urgent": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}
STATUS_COLOR = {"New": "🆕", "Open": "📂", "In Progress": "🔄", "Resolved": "✅", "Closed": "🔒"}


def show():
    st.header("📊 Dashboard")

    with engine().connect() as con:
        total = con.execute(text("SELECT COUNT(*) FROM tickets")).scalar() or 0
        open_count = con.execute(
            text("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('Resolved','Closed')")
        ).scalar() or 0
        resolved_today = con.execute(
            text("SELECT COUNT(*) FROM tickets WHERE DATE(resolved_at) = CURRENT_DATE")
        ).scalar() or 0
        sla_breach = con.execute(
            text("SELECT COUNT(*) FROM tickets WHERE sla_deadline < datetime('now') AND status NOT IN ('Resolved','Closed')")
        ).scalar() or 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Tickets", total)
    c2.metric("Open", open_count)
    c3.metric("Resolved Today", resolved_today)
    c4.metric("⚠️ SLA Breach", sla_breach, delta_color="inverse")

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("By Status")
        with engine().connect() as con:
            rows = con.execute(
                text("SELECT status, COUNT(*) AS cnt FROM tickets GROUP BY status ORDER BY cnt DESC")
            ).fetchall()
        for r in rows:
            st.write(f"{STATUS_COLOR.get(r.status, '•')} **{r.status}**: {r.cnt}")

    with col2:
        st.subheader("By Priority")
        with engine().connect() as con:
            rows = con.execute(
                text("SELECT priority, COUNT(*) AS cnt FROM tickets GROUP BY priority ORDER BY cnt DESC")
            ).fetchall()
        for r in rows:
            st.write(f"{PRIORITY_COLOR.get(r.priority, '•')} **{r.priority}**: {r.cnt}")

    st.divider()
    st.subheader("Recent Tickets (last 10)")

    with engine().connect() as con:
        rows = con.execute(
            text("""SELECT ticket_number, title, priority, status, hotel_name, created_at
                    FROM tickets ORDER BY created_at DESC LIMIT 10""")
        ).fetchall()

    if not rows:
        st.info("No tickets yet.")
        return

    for r in rows:
        status_icon = STATUS_COLOR.get(r.status, "•")
        priority_icon = PRIORITY_COLOR.get(r.priority, "•")
        with st.expander(f"{status_icon} #{r.ticket_number} — {r.title} {priority_icon}"):
            st.write(f"**Hotel:** {r.hotel_name or '-'}")
            st.write(f"**Status:** {r.status} | **Priority:** {r.priority}")
            st.write(f"**Created:** {r.created_at}")

show()
