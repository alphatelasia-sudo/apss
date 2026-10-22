"""Tickets: list, create, view, edit, close, comments."""
import uuid
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import text

from core.auth import current_user
from core.db import engine
from core.lark import notify_ticket_created, notify_ticket_updated
from core.sla import compute_deadline, sla_status

STATUSES = ["New", "Open", "In Progress", "Resolved", "Closed"]
PRIORITIES = ["Low", "Medium", "High", "Urgent"]
CATEGORIES = ["General", "Complaint", "Request", "Technical", "Billing", "Other"]
PRIORITY_BADGE = {"Urgent": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}
STATUS_BADGE = {"New": "🆕", "Open": "📂", "In Progress": "🔄", "Resolved": "✅", "Closed": "🔒"}


def _gen_ticket_number() -> str:
    with engine().connect() as con:
        count = con.execute(text("SELECT COUNT(*) FROM tickets")).scalar() or 0
    return f"TK{(count + 1):05d}"


def _get_hotels():
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT hotel_id, hotel_name FROM hotels WHERE active = 1 ORDER BY hotel_name")
        ).fetchall()
    return {r.hotel_id: r.hotel_name for r in rows}


def _get_agents():
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT agent_id, name FROM agents WHERE active = 1 ORDER BY name")
        ).fetchall()
    return {r.agent_id: r.name for r in rows}


def _ticket_row(row) -> dict:
    return dict(row._mapping)


def show():
    st.header("🎫 Tickets")
    tab_list, tab_new = st.tabs(["Ticket List", "New Ticket"])

    with tab_list:
        _show_list()
    with tab_new:
        _show_create()


def _show_list():
    with st.form("ticket_filter"):
        c1, c2, c3 = st.columns(3)
        f_status = c1.selectbox("Status", ["All"] + STATUSES)
        f_priority = c2.selectbox("Priority", ["All"] + PRIORITIES)
        f_search = c3.text_input("Search title/hotel")
        st.form_submit_button("Apply Filter")

    query = "SELECT * FROM tickets WHERE 1=1"
    params: dict = {}
    if f_status != "All":
        query += " AND status = :status"
        params["status"] = f_status
    if f_priority != "All":
        query += " AND priority = :priority"
        params["priority"] = f_priority
    if f_search:
        query += " AND (title LIKE :q OR hotel_name LIKE :q)"
        params["q"] = f"%{f_search}%"
    query += " ORDER BY created_at DESC LIMIT 200"

    with engine().connect() as con:
        rows = con.execute(text(query), params).fetchall()

    if not rows:
        st.info("No tickets match the filter.")
        return

    selected_id = st.session_state.get("apss_selected_ticket")

    for r in rows:
        d = dict(r._mapping)
        badge = f"{PRIORITY_BADGE.get(d['priority'], '•')} {STATUS_BADGE.get(d['status'], '•')}"
        label = f"{badge} #{d['ticket_number']} — {d['title']}"
        sla = sla_status(d)
        if sla == "breached":
            label += " ⚠️SLA"
        with st.expander(label, expanded=(str(d["ticket_id"]) == str(selected_id))):
            _show_ticket_detail(d)


def _show_ticket_detail(d: dict):
    st.write(f"**Hotel:** {d.get('hotel_name') or '-'} | **Category:** {d.get('category') or '-'}")
    st.write(f"**Status:** {d['status']} | **Priority:** {d['priority']}")
    st.write(f"**Assigned to:** {d.get('assigned_name') or 'Unassigned'}")
    st.write(f"**Description:** {d.get('description') or '-'}")
    st.write(f"**SLA Deadline:** {d.get('sla_deadline') or '-'}")
    st.write(f"**Created:** {d.get('created_at')} by {d.get('created_by_name') or '-'}")

    st.divider()
    col_edit, col_close = st.columns(2)
    if col_edit.button("Edit", key=f"edit_{d['ticket_id']}"):
        st.session_state[f"editing_{d['ticket_id']}"] = True
    if col_close.button("Close Ticket", key=f"close_{d['ticket_id']}",
                        disabled=d["status"] == "Closed"):
        _close_ticket(d)
        st.rerun()

    if st.session_state.get(f"editing_{d['ticket_id']}"):
        _show_edit_form(d)

    _show_comments(d["ticket_id"])
    _show_add_comment(d["ticket_id"])


def _show_edit_form(d: dict):
    st.subheader("Edit Ticket")
    hotels = _get_hotels()
    agents = _get_agents()
    hotel_ids = list(hotels.keys())
    agent_ids = [""] + list(agents.keys())

    with st.form(f"edit_form_{d['ticket_id']}"):
        title = st.text_input("Title", value=d.get("title", ""))
        description = st.text_area("Description", value=d.get("description", ""))
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox("Status", STATUSES, index=STATUSES.index(d["status"]))
        priority = c2.selectbox("Priority", PRIORITIES,
                                index=PRIORITIES.index(d["priority"]) if d["priority"] in PRIORITIES else 1)
        category = c3.selectbox("Category", CATEGORIES,
                                index=CATEGORIES.index(d["category"]) if d.get("category") in CATEGORIES else 0)
        cur_hotel = hotel_ids.index(d["hotel_id"]) if d.get("hotel_id") in hotel_ids else 0
        hotel_id = st.selectbox("Hotel", hotel_ids, index=cur_hotel,
                                format_func=lambda x: hotels.get(x, x))
        cur_agent = agent_ids.index(d["assigned_to"]) if d.get("assigned_to") in agent_ids else 0
        assigned_to = st.selectbox("Assigned To", agent_ids, index=cur_agent,
                                   format_func=lambda x: agents.get(x, "Unassigned") if x else "Unassigned")
        if st.form_submit_button("Save Changes"):
            _update_ticket(d, title=title, description=description, status=status,
                           priority=priority, category=category, hotel_id=hotel_id,
                           assigned_to=assigned_to, agents=agents, hotels=hotels)
            st.session_state.pop(f"editing_{d['ticket_id']}", None)
            st.rerun()


def _update_ticket(d: dict, **fields):
    user = current_user()
    now = datetime.now(timezone.utc)
    with engine().begin() as con:
        con.execute(text("""
            UPDATE tickets SET
                title = :title, description = :description, status = :status,
                priority = :priority, category = :category,
                hotel_id = :hotel_id, hotel_name = :hotel_name,
                assigned_to = :assigned_to, assigned_name = :assigned_name,
                updated_at = :updated_at,
                resolved_at = CASE WHEN :status IN ('Resolved','Closed') AND resolved_at IS NULL
                                   THEN :now ELSE resolved_at END,
                closed_at   = CASE WHEN :status = 'Closed' AND closed_at IS NULL
                                   THEN :now ELSE closed_at END
            WHERE ticket_id = :ticket_id
        """), {
            "title": fields["title"],
            "description": fields["description"],
            "status": fields["status"],
            "priority": fields["priority"],
            "category": fields["category"],
            "hotel_id": fields["hotel_id"],
            "hotel_name": fields["hotels"].get(fields["hotel_id"], ""),
            "assigned_to": fields["assigned_to"] or None,
            "assigned_name": fields["agents"].get(fields["assigned_to"], "") if fields["assigned_to"] else "",
            "updated_at": now,
            "now": now,
            "ticket_id": d["ticket_id"],
        })
        # History entry
        con.execute(text("""
            INSERT INTO history (history_id, ticket_id, action, agent_id, agent_name, timestamp)
            VALUES (:hid, :tid, 'updated', :aid, :aname, :ts)
        """), {"hid": str(uuid.uuid4()), "tid": d["ticket_id"],
               "aid": user["email"], "aname": user["name"], "ts": now})
    # refresh updated ticket for Lark
    with engine().connect() as con:
        updated = dict(con.execute(
            text("SELECT * FROM tickets WHERE ticket_id = :id"), {"id": d["ticket_id"]}
        ).fetchone()._mapping)
    notify_ticket_updated(updated, f"Status → {fields['status']}, Priority → {fields['priority']}")
    st.success("Ticket updated.")


def _close_ticket(d: dict):
    user = current_user()
    now = datetime.now(timezone.utc)
    with engine().begin() as con:
        con.execute(text("""
            UPDATE tickets SET status = 'Closed', closed_at = :now, updated_at = :now
            WHERE ticket_id = :id
        """), {"now": now, "id": d["ticket_id"]})
        con.execute(text("""
            INSERT INTO history (history_id, ticket_id, action, agent_id, agent_name, timestamp)
            VALUES (:hid, :tid, 'closed', :aid, :aname, :ts)
        """), {"hid": str(uuid.uuid4()), "tid": d["ticket_id"],
               "aid": user["email"], "aname": user["name"], "ts": now})
    st.success("Ticket closed.")


def _show_comments(ticket_id: str):
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT * FROM comments WHERE ticket_id = :tid ORDER BY created_at"),
            {"tid": ticket_id}
        ).fetchall()
    if rows:
        st.subheader("Comments")
        for r in rows:
            d = dict(r._mapping)
            icon = "🔒" if d.get("is_internal") else "💬"
            with st.chat_message("assistant"):
                st.markdown(f"{icon} **{d['agent_name']}** — {d['created_at']}\n\n{d['comment']}")


def _show_add_comment(ticket_id: str):
    st.subheader("Add Comment")
    with st.form(f"comment_{ticket_id}"):
        comment = st.text_area("Comment")
        is_internal = st.checkbox("Internal (not visible to hotel)")
        if st.form_submit_button("Post"):
            if not comment.strip():
                st.warning("Comment cannot be empty.")
            else:
                user = current_user()
                now = datetime.now(timezone.utc)
                with engine().begin() as con:
                    con.execute(text("""
                        INSERT INTO comments (comment_id, ticket_id, agent_id, agent_name,
                                             comment, is_internal, created_at)
                        VALUES (:cid, :tid, :aid, :aname, :comment, :internal, :ts)
                    """), {"cid": str(uuid.uuid4()), "tid": ticket_id,
                           "aid": user["email"], "aname": user["name"],
                           "comment": comment, "internal": is_internal, "ts": now})
                st.rerun()


def _show_create():
    st.subheader("Create New Ticket")
    hotels = _get_hotels()
    agents = _get_agents()

    with st.form("create_ticket"):
        title = st.text_input("Title *")
        description = st.text_area("Description")
        c1, c2, c3 = st.columns(3)
        priority = c1.selectbox("Priority", PRIORITIES, index=1)
        category = c2.selectbox("Category", CATEGORIES)
        hotel_id = c3.selectbox("Hotel", list(hotels.keys()),
                                format_func=lambda x: hotels.get(x, x))
        c4, c5 = st.columns(2)
        customer_name = c4.text_input("Customer Name")
        customer_phone = c5.text_input("Customer Phone")
        customer_email = st.text_input("Customer Email")
        assigned_to = st.selectbox("Assign To", [""] + list(agents.keys()),
                                   format_func=lambda x: agents.get(x, "Unassigned") if x else "Unassigned")

        if st.form_submit_button("Create Ticket"):
            if not title.strip():
                st.error("Title is required.")
                return
            user = current_user()
            now = datetime.now(timezone.utc)
            ticket_id = str(uuid.uuid4())
            ticket_number = _gen_ticket_number()
            deadline = compute_deadline(now, priority)
            with engine().begin() as con:
                con.execute(text("""
                    INSERT INTO tickets (
                        ticket_id, ticket_number, title, description, category, priority,
                        status, hotel_id, hotel_name, customer_name, customer_phone,
                        customer_email, assigned_to, assigned_name,
                        created_by, created_by_name, created_at, updated_at,
                        sla_hours, sla_deadline
                    ) VALUES (
                        :tid, :tnum, :title, :desc, :cat, :priority,
                        'New', :hotel_id, :hotel_name, :cname, :cphone,
                        :cemail, :assigned_to, :assigned_name,
                        :created_by, :created_by_name, :now, :now,
                        :sla_hours, :deadline
                    )
                """), {
                    "tid": ticket_id, "tnum": ticket_number, "title": title,
                    "desc": description, "cat": category, "priority": priority,
                    "hotel_id": hotel_id, "hotel_name": hotels.get(hotel_id, ""),
                    "cname": customer_name, "cphone": customer_phone, "cemail": customer_email,
                    "assigned_to": assigned_to or None,
                    "assigned_name": agents.get(assigned_to, "") if assigned_to else "",
                    "created_by": user["email"], "created_by_name": user["name"],
                    "now": now, "sla_hours": 0, "deadline": deadline,
                })
                con.execute(text("""
                    INSERT INTO history (history_id, ticket_id, action, agent_id, agent_name, timestamp)
                    VALUES (:hid, :tid, 'created', :aid, :aname, :ts)
                """), {"hid": str(uuid.uuid4()), "tid": ticket_id,
                       "aid": user["email"], "aname": user["name"], "ts": now})
            with engine().connect() as con2:
                new_ticket = dict(con2.execute(
                    text("SELECT * FROM tickets WHERE ticket_id = :id"), {"id": ticket_id}
                ).fetchone()._mapping)
            notify_ticket_created(new_ticket)
            st.success(f"Ticket #{ticket_number} created.")
            st.session_state["apss_selected_ticket"] = ticket_id

show()
