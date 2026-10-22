"""Reports: ticket stats by date range, hotel, agent."""
import streamlit as st
from sqlalchemy import text

import pandas as pd

from core.db import engine


def show():
    st.header("📈 Reports")

    c1, c2 = st.columns(2)
    from datetime import date, timedelta
    default_from = date.today() - timedelta(days=30)
    date_from = c1.date_input("From", value=default_from)
    date_to = c2.date_input("To", value=date.today())

    if date_from > date_to:
        st.error("'From' must be before 'To'.")
        return

    with engine().connect() as con:
        # Overall stats
        stats = con.execute(text("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status NOT IN ('Resolved','Closed') THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN status IN ('Resolved','Closed') THEN 1 ELSE 0 END) AS closed_count,
                SUM(CASE WHEN sla_deadline < datetime('now') AND status NOT IN ('Resolved','Closed') THEN 1 ELSE 0 END) AS sla_breach
            FROM tickets
            WHERE DATE(created_at) BETWEEN :from_d AND :to_d
        """), {"from_d": str(date_from), "to_d": str(date_to)}).fetchone()

        # By hotel
        by_hotel = pd.read_sql(text("""
            SELECT hotel_name, COUNT(*) AS tickets,
                   SUM(CASE WHEN status IN ('Resolved','Closed') THEN 1 ELSE 0 END) AS resolved
            FROM tickets
            WHERE DATE(created_at) BETWEEN :from_d AND :to_d AND hotel_name IS NOT NULL
            GROUP BY hotel_name ORDER BY tickets DESC
        """), con, params={"from_d": str(date_from), "to_d": str(date_to)})

        # By agent
        by_agent = pd.read_sql(text("""
            SELECT assigned_name, COUNT(*) AS tickets,
                   SUM(CASE WHEN status IN ('Resolved','Closed') THEN 1 ELSE 0 END) AS resolved
            FROM tickets
            WHERE DATE(created_at) BETWEEN :from_d AND :to_d AND assigned_name IS NOT NULL AND assigned_name != ''
            GROUP BY assigned_name ORDER BY tickets DESC
        """), con, params={"from_d": str(date_from), "to_d": str(date_to)})

        # By priority
        by_priority = pd.read_sql(text("""
            SELECT priority, COUNT(*) AS tickets
            FROM tickets
            WHERE DATE(created_at) BETWEEN :from_d AND :to_d
            GROUP BY priority ORDER BY tickets DESC
        """), con, params={"from_d": str(date_from), "to_d": str(date_to)})

        # Daily trend
        daily = pd.read_sql(text("""
            SELECT DATE(created_at) AS day, COUNT(*) AS tickets
            FROM tickets
            WHERE DATE(created_at) BETWEEN :from_d AND :to_d
            GROUP BY day ORDER BY day
        """), con, params={"from_d": str(date_from), "to_d": str(date_to)})

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total", int(stats.total or 0))
    m2.metric("Open", int(stats.open_count or 0))
    m3.metric("Resolved/Closed", int(stats.closed_count or 0))
    m4.metric("SLA Breach", int(stats.sla_breach or 0))

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("By Hotel")
        st.dataframe(by_hotel, use_container_width=True)
    with col2:
        st.subheader("By Agent")
        st.dataframe(by_agent, use_container_width=True)

    st.subheader("By Priority")
    st.dataframe(by_priority, use_container_width=True)

    if not daily.empty:
        st.subheader("Daily Ticket Volume")
        st.line_chart(daily.set_index("day")["tickets"])

show()
