"""Agents & Roles management."""
import uuid

import streamlit as st
from sqlalchemy import text

from core.db import engine


def show():
    st.header("👥 Agents & Roles")
    tab_agents, tab_roles = st.tabs(["Agents", "Roles"])
    with tab_agents:
        _show_agents()
    with tab_roles:
        _show_roles()


def _show_agents():
    st.subheader("Agents")

    with engine().connect() as con:
        roles = {r.role_id: r.role_name for r in
                 con.execute(text("SELECT role_id, role_name FROM roles ORDER BY role_name")).fetchall()}
        agents = con.execute(text("SELECT * FROM agents ORDER BY name")).fetchall()

    for r in agents:
        d = dict(r._mapping)
        status = "✅" if d.get("active") else "❌"
        with st.expander(f"{status} {d['name']} — {d.get('role_name', '-')}"):
            st.write(f"**Email:** {d.get('email', '-')}")
            st.write(f"**Lark ID:** {d.get('lark_user_id', '-')}")
            if st.button("Edit", key=f"edit_agent_{d['agent_id']}"):
                st.session_state[f"editing_agent_{d['agent_id']}"] = True
            if st.session_state.get(f"editing_agent_{d['agent_id']}"):
                _edit_agent(d, roles)

    st.divider()
    st.subheader("Add Agent")
    with st.form("add_agent"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name *")
        email = c2.text_input("Email *")
        role_ids = list(roles.keys())
        role_id = st.selectbox("Role", role_ids, format_func=lambda x: roles.get(x, x))
        lark_user_id = st.text_input("Lark User ID (optional)")
        if st.form_submit_button("Add Agent"):
            if not name.strip() or not email.strip():
                st.error("Name and email are required.")
                return
            with engine().begin() as con:
                con.execute(text("""
                    INSERT INTO agents (agent_id, name, email, role_id, role_name, lark_user_id)
                    VALUES (:aid, :name, :email, :rid, :rname, :luid)
                    ON CONFLICT (email) DO NOTHING
                """), {"aid": str(uuid.uuid4()), "name": name, "email": email,
                       "rid": role_id, "rname": roles.get(role_id, ""), "luid": lark_user_id})
            st.success(f"Agent '{name}' added.")
            st.rerun()


def _edit_agent(d: dict, roles: dict):
    with st.form(f"edit_agent_{d['agent_id']}"):
        name = st.text_input("Name", value=d.get("name", ""))
        email = st.text_input("Email", value=d.get("email", ""))
        role_ids = list(roles.keys())
        cur = role_ids.index(d["role_id"]) if d.get("role_id") in role_ids else 0
        role_id = st.selectbox("Role", role_ids, index=cur, format_func=lambda x: roles.get(x, x))
        lark_user_id = st.text_input("Lark User ID", value=d.get("lark_user_id", ""))
        active = st.checkbox("Active", value=bool(d.get("active", True)))
        if st.form_submit_button("Save"):
            with engine().begin() as con:
                con.execute(text("""
                    UPDATE agents SET name=:name, email=:email, role_id=:rid, role_name=:rname,
                        lark_user_id=:luid, active=:active
                    WHERE agent_id=:id
                """), {"name": name, "email": email, "rid": role_id,
                       "rname": roles.get(role_id, ""), "luid": lark_user_id,
                       "active": int(active), "id": d["agent_id"]})
            st.session_state.pop(f"editing_agent_{d['agent_id']}", None)
            st.success("Agent updated.")
            st.rerun()


def _show_roles():
    st.subheader("Roles")
    with engine().connect() as con:
        roles = con.execute(text("SELECT * FROM roles ORDER BY role_name")).fetchall()

    for r in roles:
        d = dict(r._mapping)
        color = d.get("color", "#6366f1")
        st.markdown(
            f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px">'
            f'{d["role_name"]}</span> — {d.get("description", "")}',
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("Add Role")
    with st.form("add_role"):
        c1, c2, c3 = st.columns(3)
        role_name = c1.text_input("Role Name *")
        description = c2.text_input("Description")
        color = c3.color_picker("Color", value="#6366f1")
        if st.form_submit_button("Add Role"):
            if not role_name.strip():
                st.error("Role name is required.")
                return
            with engine().begin() as con:
                con.execute(text("""
                    INSERT INTO roles (role_id, role_name, description, color)
                    VALUES (:rid, :rname, :desc, :color)
                """), {"rid": str(uuid.uuid4()), "rname": role_name,
                       "desc": description, "color": color})
            st.success(f"Role '{role_name}' added.")
            st.rerun()

show()
