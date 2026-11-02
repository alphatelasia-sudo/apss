"""Stop Sale management — create, view, cancel stop sale records."""
import threading
import uuid
from datetime import date, datetime, timezone

import streamlit as st
from sqlalchemy import text

from core.auth import current_user
from core.db import engine
from core.lark import notify_stop_sale
from core.sla import compute_deadline

BOARDS = ["ALL", "RO", "RB"]
ACTIONS = ["Closed", "Re-Open"]

_ROOM_PRESETS_FALLBACK = [
    "Standard Double Room", "Standard Twin Room", "Deluxe Jacuzzi",
    "Deluxe Poolside", "Suite Jacuzzi", "Suite Poolside",
    "Superior Room", "Deluxe Room", "Family Room", "Villa",
]


@st.cache_data(ttl=600)
def _get_apc_room_types(hotel_name: str) -> list[str]:
    """Fetch distinct room types from APC bookings for a hotel (matched by name).
    Strips leading APC code prefix e.g. 'H002_Guuden ...' → 'Guuden ...' before matching.
    """
    import re
    clean = re.sub(r'^H\d+[_\s]+', '', hotel_name).strip()
    search = clean if clean else hotel_name
    try:
        with engine().connect() as con:
            rows = con.execute(text("""
                SELECT DISTINCT ab.room_type
                FROM apc_bookings ab
                JOIN apc_properties ap ON ab.code = ap.code
                WHERE (
                    LOWER(ap.name) LIKE '%' || LOWER(:name) || '%'
                    OR LOWER(:name) LIKE '%' || LOWER(ap.name) || '%'
                )
                  AND ab.room_type IS NOT NULL AND ab.room_type != ''
                ORDER BY ab.room_type
            """), {"name": search}).fetchall()
        result = [r[0] for r in rows if r[0]]
        return result if result else _ROOM_PRESETS_FALLBACK
    except Exception:
        return _ROOM_PRESETS_FALLBACK


def _gen_ticket_number() -> str:
    with engine().connect() as con:
        count = con.execute(text("SELECT COUNT(*) FROM tickets")).scalar() or 0
    return f"TK{(count + 1):05d}"


def _create_ticket_for_stop_sale(
    ss_id: str, hotel_id: str, hotel_name: str,
    room_types_str: str, board: str, date_from, date_to, action: str,
    note: str, user: dict, now: datetime,
) -> str:
    """Insert a ticket for this stop sale and return its ticket_id."""
    ticket_id = str(uuid.uuid4())
    ticket_number = _gen_ticket_number()
    title = f"Stop Sale: {hotel_name} {date_from} → {date_to} ({action})"
    description = (
        f"Stop Sale สร้างอัตโนมัติจากระบบ\n\n"
        f"**Hotel:** {hotel_name}\n"
        f"**Room Types:** {room_types_str}\n"
        f"**Board:** {board}\n"
        f"**วันที่:** {date_from} → {date_to}\n"
        f"**Action:** {action}\n"
    )
    if note:
        description += f"**หมายเหตุ:** {note}\n"
    deadline = compute_deadline(now, "High")
    with engine().begin() as con:
        con.execute(text("""
            INSERT INTO tickets (
                ticket_id, ticket_number, title, description, category, priority,
                status, hotel_id, hotel_name,
                created_by, created_by_name, created_at, updated_at,
                sla_hours, sla_deadline
            ) VALUES (
                :tid, :tnum, :title, :desc, 'Request', 'High',
                'New', :hotel_id, :hotel_name,
                :by, :by_name, :now, :now,
                48, :deadline
            )
        """), {
            "tid": ticket_id, "tnum": ticket_number, "title": title,
            "desc": description, "hotel_id": hotel_id, "hotel_name": hotel_name,
            "by": user["email"], "by_name": user["name"],
            "now": now, "deadline": deadline,
        })
        con.execute(text("""
            INSERT INTO history (history_id, ticket_id, action, agent_id, agent_name, timestamp)
            VALUES (:hid, :tid, 'created', :aid, :aname, :ts)
        """), {"hid": str(uuid.uuid4()), "tid": ticket_id,
               "aid": user["email"], "aname": user["name"], "ts": now})
        con.execute(text(
            "UPDATE stop_sales SET ticket_id = :tid WHERE stop_sale_id = :ssid"
        ), {"tid": ticket_id, "ssid": ss_id})
    return ticket_id

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
    tab_cal, tab_list, tab_new = st.tabs(["📅 Calendar", "📋 List", "➕ New Stop Sale"])
    with tab_cal:
        _show_calendar()
    with tab_list:
        _show_list()
    with tab_new:
        _show_create()


# ── Calendar ──────────────────────────────────────────────────────────────────

def _show_calendar():
    import calendar as cal_mod
    from datetime import timedelta

    hotels = _get_hotels()
    if not hotels:
        st.info("ยังไม่มีโรงแรมในระบบ")
        return

    today = date.today()

    c1, c2 = st.columns([2, 1])
    sel_hotel_name = c1.selectbox(
        "Hotel", list(hotels.values()), key="cal_hotel"
    )
    # Build month options: 3 months back → 12 months ahead
    month_opts = []
    for delta in range(-3, 13):
        m = today.month + delta
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        month_opts.append(date(y, m, 1))
    default_idx = month_opts.index(date(today.year, today.month, 1))
    sel_month = c2.selectbox(
        "Month",
        month_opts,
        index=default_idx,
        format_func=lambda d: d.strftime("%B %Y"),
        key="cal_month",
    )

    hotel_id = next(
        (hid for hid, hname in hotels.items() if hname == sel_hotel_name), None
    )
    if not hotel_id:
        return

    # Date range for selected month
    _, days_in_month = cal_mod.monthrange(sel_month.year, sel_month.month)
    month_start = sel_month
    month_end = date(sel_month.year, sel_month.month, days_in_month)

    with engine().connect() as con:
        rows = con.execute(text("""
            SELECT * FROM stop_sales
            WHERE hotel_id = :hid
              AND status = 'Active'
              AND date_from <= :me
              AND date_to   >= :ms
            ORDER BY created_at ASC
        """), {"hid": hotel_id, "me": str(month_end), "ms": str(month_start)}).fetchall()

    # Build status matrix: (room_type_lower, board, day_int) → action
    # Last-written record wins; "Closed" and "Re-Open" can alternate
    status_matrix: dict[tuple, str] = {}
    all_room_type_originals: dict[str, str] = {}  # lower → original case

    for r in rows:
        d = dict(r._mapping)
        room_types = [rt.strip() for rt in d["room_types"].split(",") if rt.strip()]
        boards = ["RO", "RB"] if d["board"] == "ALL" else [d["board"]]
        ss_from = max(date.fromisoformat(str(d["date_from"])), month_start)
        ss_to   = min(date.fromisoformat(str(d["date_to"])), month_end)
        for rt in room_types:
            rt_lower = rt.lower()
            all_room_type_originals[rt_lower] = rt  # keep original casing
            for b in boards:
                cur = ss_from
                while cur <= ss_to:
                    status_matrix[(rt_lower, b, cur.day)] = d["action"]
                    cur += timedelta(days=1)

    if not all_room_type_originals:
        st.info(
            f"ไม่มีรายการ Stop Sale ที่ Active สำหรับ **{sel_hotel_name}** "
            f"ในเดือน {sel_month.strftime('%B %Y')}"
        )
        st.caption("สร้าง Stop Sale ได้ที่แท็บ ➕ New Stop Sale")
        return

    sorted_room_types = sorted(all_room_type_originals.items())  # (lower, original)
    boards_to_show = ["RO", "RB"]

    # Day-of-week abbreviations
    dow = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    # ── Build HTML table ────────────────────────────────────────────────────
    # Color scheme
    C_CLOSED  = "#FFCCCC"  # light red
    C_REOPEN  = "#CCFFCC"  # light green
    C_EMPTY   = "#FAFAFA"
    C_HDR     = "#F0F0F0"
    C_SAT     = "#E8F0FF"  # light blue for Saturday
    C_SUN     = "#FFE8E8"  # light pink for Sunday

    th = "padding:4px 5px;border:1px solid #ccc;white-space:nowrap;font-size:11px;"
    td = "padding:3px 4px;border:1px solid #ddd;text-align:center;font-size:11px;"
    td_rt = "padding:4px 6px;border:1px solid #ccc;white-space:nowrap;font-size:11px;font-weight:500;"

    html = ["<div style='overflow-x:auto;'>"]
    html.append(f"<table style='border-collapse:collapse;min-width:600px;'>")

    # Header row 1: day numbers
    html.append("<thead>")
    html.append(
        f"<tr>"
        f"<th style='{th}background:{C_HDR};min-width:120px;'>Room Type</th>"
        f"<th style='{th}background:{C_HDR};'>Board</th>"
    )
    for day in range(1, days_in_month + 1):
        dow_idx = date(sel_month.year, sel_month.month, day).weekday()
        bg = C_SAT if dow_idx == 5 else (C_SUN if dow_idx == 6 else C_HDR)
        html.append(
            f"<th style='{th}background:{bg};min-width:26px;'>"
            f"{day}<br><span style='font-weight:400;color:#666;font-size:10px;'>"
            f"{dow[dow_idx][:2]}</span></th>"
        )
    html.append("</tr>")
    html.append("</thead><tbody>")

    # Data rows: one per (room_type, board)
    for rt_lower, rt_original in sorted_room_types:
        first_board = True
        for b in boards_to_show:
            # Check if this board has any data for this room type
            has_data = any(
                k[0] == rt_lower and k[1] == b for k in status_matrix
            )
            if not has_data:
                continue
            if first_board:
                rt_cell = f"<td style='{td_rt}' rowspan='0'>{rt_original}</td>"
                first_board = False
            else:
                rt_cell = ""
            html.append(f"<tr>")
            if rt_cell:
                html.append(rt_cell)
            html.append(
                f"<td style='{td}background:{C_HDR};font-weight:500;'>{b}</td>"
            )
            for day in range(1, days_in_month + 1):
                action = status_matrix.get((rt_lower, b, day))
                if action == "Closed":
                    cell_bg = C_CLOSED
                    cell_text = "C"
                    title = "Closed"
                elif action == "Re-Open":
                    cell_bg = C_REOPEN
                    cell_text = "O"
                    title = "Re-Open"
                else:
                    cell_bg = C_EMPTY
                    cell_text = ""
                    title = ""
                html.append(
                    f"<td style='{td}background:{cell_bg};' title='{title}'>"
                    f"{cell_text}</td>"
                )
            html.append("</tr>")

    html.append("</tbody></table></div>")

    # Legend
    html.append(
        "<div style='margin-top:8px;font-size:11px;display:flex;gap:16px;'>"
        f"<span><span style='background:{C_CLOSED};padding:2px 8px;border:1px solid #ccc;'>C</span> Closed</span>"
        f"<span><span style='background:{C_REOPEN};padding:2px 8px;border:1px solid #ccc;'>O</span> Re-Open / Open</span>"
        f"<span><span style='background:{C_EMPTY};padding:2px 8px;border:1px solid #ccc;'>&nbsp;&nbsp;</span> ไม่มีรายการ</span>"
        "</div>"
    )

    st.markdown("".join(html), unsafe_allow_html=True)

    # Summary count
    closed_count = sum(1 for v in status_matrix.values() if v == "Closed")
    reopen_count = sum(1 for v in status_matrix.values() if v == "Re-Open")
    st.caption(
        f"📊 เดือนนี้: Closed {closed_count} เซลล์ | Re-Open {reopen_count} เซลล์ "
        f"| ห้อง {len(sorted_room_types)} ประเภท"
    )


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

    # Pre-load room types for the default hotel (outside form so it can react to hotel change)
    default_hotel_id = hotel_ids[default_hotel_idx] if hotel_ids else None
    default_hotel_name = hotels.get(default_hotel_id, "") if default_hotel_id else ""
    room_type_options = _get_apc_room_types(default_hotel_name) if default_hotel_name else _ROOM_PRESETS_FALLBACK

    with st.form("create_stop_sale", clear_on_submit=True):
        hotel_id = st.selectbox(
            "Hotel *",
            hotel_ids,
            index=default_hotel_idx,
            format_func=lambda x: hotels.get(x, x),
        )

        st.write("**Room Types** — ข้อมูลจาก APC (เลือกได้หลายห้อง หรือพิมพ์เพิ่มเติม)")
        selected_presets = st.multiselect("Room Types", room_type_options)
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
        auto_ticket = st.checkbox("สร้าง Ticket อัตโนมัติ", value=True,
                                  help="สร้าง ticket ประเภท Request/High ให้อัตโนมัติพร้อมกับ Stop Sale")

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
                        date_from, date_to, action, status,
                        requested_by, requested_by_name, note, created_at
                    ) VALUES (
                        :id, :hotel_id, :hotel_name, :room_types, :board,
                        :date_from, :date_to, :action, 'Active',
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
                    "by": user["email"],
                    "by_name": user["name"],
                    "note": note.strip() or None,
                    "now": now,
                })

            # Auto-create ticket if requested
            new_ticket_id = None
            new_ticket_num = None
            if auto_ticket:
                try:
                    new_ticket_id = _create_ticket_for_stop_sale(
                        ss_id, hotel_id, hotel_name, room_types_str,
                        board, date_from, date_to, action,
                        note.strip(), user, now,
                    )
                    with engine().connect() as con:
                        new_ticket_num = con.execute(
                            text("SELECT ticket_number FROM tickets WHERE ticket_id = :tid"),
                            {"tid": new_ticket_id},
                        ).scalar()
                except Exception as e:
                    st.warning(f"Stop Sale สร้างแล้ว แต่สร้าง ticket ไม่สำเร็จ: {e}")

            # Non-blocking Lark notification
            ss_brief = {
                "hotel_name": hotel_name,
                "room_types": room_types_str,
                "board": board,
                "date_from": str(date_from),
                "date_to": str(date_to),
                "action": action,
                "ticket_ref": new_ticket_num or "-",
                "requested_by_name": user["name"],
            }
            threading.Thread(
                target=notify_stop_sale, args=(ss_brief,), daemon=True
            ).start()

            msg = (f"✅ Stop Sale สร้างเรียบร้อย — {hotel_name} | {room_types_str} "
                   f"| {date_from} → {date_to} | {action}")
            if new_ticket_num:
                msg += f"\n\n🎫 Ticket **#{new_ticket_num}** ถูกสร้างอัตโนมัติ"
            st.success(msg)
            if new_ticket_id:
                st.session_state["apss_selected_ticket"] = new_ticket_id
            st.cache_data.clear()
            st.rerun()


show()
