"""Stop Sale management — create, view, cancel stop sale records."""
import threading
import uuid
from datetime import date, datetime, timezone

import streamlit as st
from sqlalchemy import text

from core.auth import current_user
from core.db import engine
from core.lark import notify_stop_sale

BOARDS = ["ALL", "RO", "RB"]
ACTIONS = ["Closed", "Re-Open"]

# Common room type presets (user can also type free-form)
_ROOM_PRESETS = [
    "Standard Double Room",
    "Standard Twin Room",
    "Deluxe Jacuzzi",
    "Deluxe Poolside",
    "Suite Jacuzzi",
    "Suite Poolside",
    "Superior Room",
    "Deluxe Room",
    "Family Room",
    "Villa",
]

ACTION_BADGE = {"Closed": "🚫", "Re-Open": "✅"}
STATUS_COLOR = {"Active": "🟢", "Cancelled": "⚫"}


@st.cache_data(ttl=300)
def _get_hotels():
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT hotel_id, hotel_name FROM hotels WHERE active = 1 ORDER BY hotel_name")
        ).fetchall()
    return {r.hotel_id: r.hotel_name for r in rows}


def show():
    st.header("🚫 Stop Sale")
    tab_list, tab_new = st.tabs(["Stop Sale List", "New Stop Sale"])
    with tab_list:
        _show_list()
    with tab_new:
        _show_create()


# ── List ───────────────────────────────────────────────────────────────────────

def _show_list():
    hotels = _get_hotels()

    with st.form("ss_filter"):
        c1, c2, c3 = st.columns(3)
        f_hotel = c1.selectbox("Hotel", ["All"] + list(hotels.values()))
        f_action = c2.selectbox("Action", ["All"] + ACTIONS)
        f_status = c3.selectbox("Status", ["Active", "All", "Cancelled"])
        c4, c5, _ = st.columns(3)
        f_from = c4.date_input("From", value=None)
        f_to = c5.date_input("To", value=None)
        st.form_submit_button("Apply Filter")

    query = "SELECT * FROM stop_sales WHERE 1=1"
    params: dict = {}
    if f_hotel != "All":
        query += " AND hotel_name = :hotel_name"
        params["hotel_name"] = f_hotel
    if f_action != "All":
        query += " AND action = :action"
        params["action"] = f_action
    if f_status != "All":
        query += " AND status = :status"
        params["status"] = f_status
    if f_from:
        query += " AND date_to >= :df"
        params["df"] = str(f_from)
    if f_to:
        query += " AND date_from <= :dt"
        params["dt"] = str(f_to)
    query += " ORDER BY created_at DESC LIMIT 300"

    with engine().connect() as con:
        rows = con.execute(text(query), params).fetchall()

    if not rows:
        st.info("ไม่พบรายการ Stop Sale ที่ตรงกับเงื่อนไข")
        return

    st.caption(f"{len(rows)} รายการ")
    for r in rows:
        d = dict(r._mapping)
        badge = ACTION_BADGE.get(d["action"], "•")
        status_icon = STATUS_COLOR.get(d["status"], "•")
        label = (
            f"{badge} {d['hotel_name']} — {d['room_types']} "
            f"| {d['date_from']} → {d['date_to']} "
            f"| Board: {d['board']} "
            f"| {status_icon} {d['status']}"
        )
        with st.expander(label):
            c1, c2 = st.columns(2)
            c1.write(f"**Hotel:** {d['hotel_name']}")
            c1.write(f"**Room Types:** {d['room_types']}")
            c1.write(f"**Board:** {d['board']}")
            c1.write(f"**Action:** {d['action']}")
            c2.write(f"**Date From:** {d['date_from']}")
            c2.write(f"**Date To:** {d['date_to']}")
            c2.write(f"**Status:** {d['status']}")
            c2.write(f"**Ticket:** {d.get('ticket_id') or '-'}")
            if d.get("note"):
                st.write(f"**Note:** {d['note']}")
            st.caption(
                f"Created by {d.get('requested_by_name') or '-'} "
                f"at {d.get('created_at') or '-'}"
            )
            if d["status"] == "Active":
                if st.button("⚫ Cancel Stop Sale", key=f"cancel_ss_{d['stop_sale_id']}"):
                    _cancel_stop_sale(d["stop_sale_id"])
                    st.rerun()


def _cancel_stop_sale(stop_sale_id: str):
    now = datetime.now(timezone.utc)
    with engine().begin() as con:
        con.execute(
            text("UPDATE stop_sales SET status='Cancelled', cancelled_at=:now WHERE stop_sale_id=:id"),
            {"now": now, "id": stop_sale_id},
        )
    st.success("Stop Sale cancelled.")


# ── Create ─────────────────────────────────────────────────────────────────────

def _show_create(prefill: dict | None = None):
    """
    prefill: optional dict with hotel_id, hotel_name, ticket_id keys
    (used when called from ticket detail to pre-fill fields).
    """
    st.subheader("สร้าง Stop Sale ใหม่")
    hotels = _get_hotels()
    hotel_ids = list(hotels.keys())

    # Determine default hotel index from prefill
    default_hotel_idx = 0
    if prefill and prefill.get("hotel_id") in hotel_ids:
        default_hotel_idx = hotel_ids.index(prefill["hotel_id"])

    with st.form("create_stop_sale", clear_on_submit=True):
        hotel_id = st.selectbox(
            "Hotel *",
            hotel_ids,
            index=default_hotel_idx,
            format_func=lambda x: hotels.get(x, x),
        )

        st.write("**Room Types** — เลือกจากรายการด้านล่าง หรือพิมพ์เพิ่มเติมในช่อง Custom")
        selected_presets = st.multiselect("Room Types (เลือกได้หลายห้อง)", _ROOM_PRESETS)
        custom_rooms = st.text_input(
            "Room Types เพิ่มเติม (คั่นด้วยลูกน้ำ เช่น Pool Villa, Grand Suite)",
            placeholder="เว้นว่างถ้าใช้รายการด้านบนครบแล้ว",
        )

        c1, c2 = st.columns(2)
        board = c1.selectbox("Board Type", BOARDS)
        action = c2.selectbox("Action", ACTIONS)

        c3, c4 = st.columns(2)
        date_from = c3.date_input("วันที่เริ่มปิด *", value=date.today())
        date_to = c4.date_input("วันที่สิ้นสุด *", value=date.today())

        note = st.text_area("หมายเหตุ (optional)")
        ticket_id_link = st.text_input(
            "Ticket ID (optional)",
            value=prefill.get("ticket_id", "") if prefill else "",
            placeholder="เชื่อมกับ ticket ถ้ามี",
        )

        if st.form_submit_button("🚫 สร้าง Stop Sale"):
            # Validate room types
            all_rooms = list(selected_presets)
            if custom_rooms.strip():
                all_rooms += [r.strip() for r in custom_rooms.split(",") if r.strip()]
            if not all_rooms:
                st.error("กรุณาเลือกหรือระบุ Room Type อย่างน้อย 1 ประเภท")
                return
            if date_to < date_from:
                st.error("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่มต้น")
                return

            user = current_user()
            now = datetime.now(timezone.utc)
            ss_id = str(uuid.uuid4())
            hotel_name = hotels.get(hotel_id, "")
            room_types_str = ", ".join(all_rooms)

            with engine().begin() as con:
                con.execute(text("""
                    INSERT INTO stop_sales (
                        stop_sale_id, hotel_id, hotel_name, room_types, board,
                        date_from, date_to, action, status, ticket_id,
                        requested_by, requested_by_name, note, created_at
                    ) VALUES (
                        :id, :hotel_id, :hotel_name, :room_types, :board,
                        :date_from, :date_to, :action, 'Active', :ticket_id,
                        :by, :by_name, :note, :now
                    )
                """), {
                    "id": ss_id,
                    "hotel_id": hotel_id,
                    "hotel_name": hotel_name,
                    "room_types": room_types_str,
                    "board": board,
                    "date_from": str(date_from),
                    "date_to": str(date_to),
                    "action": action,
                    "ticket_id": ticket_id_link.strip() or None,
                    "by": user["email"],
                    "by_name": user["name"],
                    "note": note.strip() or None,
                    "now": now,
                })

            # Non-blocking Lark notification
            ss_brief = {
                "hotel_name": hotel_name,
                "room_types": room_types_str,
                "board": board,
                "date_from": str(date_from),
                "date_to": str(date_to),
                "action": action,
                "ticket_ref": ticket_id_link.strip() or "-",
                "requested_by_name": user["name"],
            }
            threading.Thread(
                target=notify_stop_sale, args=(ss_brief,), daemon=True
            ).start()

            st.success(
                f"✅ Stop Sale สร้างเรียบร้อย — {hotel_name} | {room_types_str} "
                f"| {date_from} → {date_to} | {action}"
            )
            st.cache_data.clear()
            st.rerun()


show()
