"""Hotels: list, create, edit, hotel contacts."""
import uuid
from datetime import datetime, timezone

import streamlit as st
from sqlalchemy import text

from core.db import engine


def show():
    st.header("🏨 Hotels")
    tab_list, tab_new = st.tabs(["Hotel List", "Add Hotel"])

    with tab_list:
        _show_list()
    with tab_new:
        _show_create()


def _show_list():
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT * FROM hotels ORDER BY hotel_name")
        ).fetchall()

    if not rows:
        st.info("No hotels yet. Add one above.")
        return

    for r in rows:
        d = dict(r._mapping)
        status = "✅ Active" if d.get("active") else "❌ Inactive"
        with st.expander(f"{status} {d['hotel_name']}"):
            c1, c2 = st.columns(2)
            c1.write(f"**Contact:** {d.get('contact_person') or '-'}")
            c1.write(f"**Phone:** {d.get('phone') or '-'}")
            c2.write(f"**Email:** {d.get('email') or '-'}")
            c2.write(f"**Address:** {d.get('address') or '-'}")
            if st.button("Edit", key=f"edit_hotel_{d['hotel_id']}"):
                st.session_state[f"editing_hotel_{d['hotel_id']}"] = True
            if st.session_state.get(f"editing_hotel_{d['hotel_id']}"):
                _show_edit(d)
            _show_contacts(d["hotel_id"])


def _show_edit(d: dict):
    with st.form(f"edit_hotel_{d['hotel_id']}"):
        hotel_name = st.text_input("Hotel Name", value=d.get("hotel_name", ""))
        contact_person = st.text_input("Contact Person", value=d.get("contact_person", ""))
        phone = st.text_input("Phone", value=d.get("phone", ""))
        email = st.text_input("Email", value=d.get("email", ""))
        address = st.text_area("Address", value=d.get("address", ""))
        lark_webhook = st.text_input("Lark Webhook", value=d.get("lark_webhook", ""))
        active = st.checkbox("Active", value=bool(d.get("active", True)))
        if st.form_submit_button("Save"):
            with engine().begin() as con:
                con.execute(text("""
                    UPDATE hotels SET hotel_name=:name, contact_person=:cp, phone=:phone,
                        email=:email, address=:addr, lark_webhook=:webhook, active=:active
                    WHERE hotel_id=:id
                """), {"name": hotel_name, "cp": contact_person, "phone": phone,
                       "email": email, "addr": address, "webhook": lark_webhook,
                       "active": int(active), "id": d["hotel_id"]})
            st.session_state.pop(f"editing_hotel_{d['hotel_id']}", None)
            st.success("Hotel updated.")
            st.rerun()


def _show_contacts(hotel_id: str):
    st.subheader("Contacts")
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT * FROM hotel_contacts WHERE hotel_id = :hid ORDER BY name"),
            {"hid": hotel_id}
        ).fetchall()
    for r in rows:
        d = dict(r._mapping)
        st.write(f"• **{d['name']}** ({d.get('contact_type', '-')}) — {d.get('phone', '')} {d.get('email', '')}")

    with st.form(f"add_contact_{hotel_id}"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name")
        contact_type = c2.text_input("Type (e.g. GM, Sales)")
        phone = c3.text_input("Phone")
        email = st.text_input("Email")
        if st.form_submit_button("Add Contact"):
            if name.strip():
                with engine().begin() as con:
                    con.execute(text("""
                        INSERT INTO hotel_contacts (contact_id, hotel_id, contact_type, name, phone, email)
                        VALUES (:cid, :hid, :ctype, :name, :phone, :email)
                    """), {"cid": str(uuid.uuid4()), "hid": hotel_id, "ctype": contact_type,
                           "name": name, "phone": phone, "email": email})
                st.rerun()


def _show_create():
    st.subheader("Add New Hotel")
    with st.form("add_hotel"):
        hotel_name = st.text_input("Hotel Name *")
        c1, c2 = st.columns(2)
        contact_person = c1.text_input("Contact Person")
        phone = c2.text_input("Phone")
        email = st.text_input("Email")
        address = st.text_area("Address")
        lark_webhook = st.text_input("Lark Webhook URL (optional)")
        if st.form_submit_button("Add Hotel"):
            if not hotel_name.strip():
                st.error("Hotel name is required.")
                return
            with engine().begin() as con:
                con.execute(text("""
                    INSERT INTO hotels (hotel_id, hotel_name, contact_person, phone, email, address, lark_webhook)
                    VALUES (:hid, :name, :cp, :phone, :email, :addr, :webhook)
                """), {"hid": str(uuid.uuid4()), "name": hotel_name, "cp": contact_person,
                       "phone": phone, "email": email, "addr": address, "webhook": lark_webhook})
            st.success(f"Hotel '{hotel_name}' added.")
            st.rerun()

show()
