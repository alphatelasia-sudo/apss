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

ACTIONS = ["Closed", "Re-Open"]


@st.cache_data(ttl=300)
def _get_apc_plans(hotel_code: str) -> list[tuple[str, str]]:
    """Return list of (room_type, board) from apc_rs_config for this hotel_code.
    Falls back to empty list if not found."""
    if not hotel_code:
        return []
    try:
        import json as _json
        with engine().connect() as con:
            body_str = con.execute(
                text("SELECT body FROM apc_rs_config WHERE code = :code"),
                {"code": hotel_code},
            ).scalar()
        if not body_str:
            return []
        body = _json.loads(body_str) if isinstance(body_str, str) else body_str
        plans = body.get("plans", [])
        seen = set()
        result = []
        for p in plans:
            rt = (p.get("type") or "").strip()
            board = (p.get("plan") or p.get("board") or "").strip().upper()
            if rt and board and (rt, board) not in seen:
                result.append((rt, board))
                seen.add((rt, board))
        return result
    except Exception:
        return []


@st.cache_data(ttl=300)
def _get_hotel_room_types(hotel_id: str) -> list[str]:
    """Fallback: fetch room types from APSS hotels.room_types (comma-separated)."""
    try:
        with engine().connect() as con:
            rt_str = con.execute(
                text("SELECT room_types FROM hotels WHERE hotel_id = :hid"),
                {"hid": hotel_id},
            ).scalar()
        if not rt_str:
            return []
        return [r.strip() for r in rt_str.split(",") if r.strip()]
    except Exception:
        return []


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
    try:
        with engine().connect() as con:
            rows = con.execute(
                text("SELECT hotel_id, hotel_name, hotel_code FROM hotels WHERE active = 1 ORDER BY hotel_name")
            ).fetchall()
        return {r.hotel_id: {"name": r.hotel_name, "code": r.hotel_code or ""} for r in rows}
    except Exception:
        # hotel_code column may not exist yet — fall back without it
        try:
            with engine().connect() as con:
                rows = con.execute(
                    text("SELECT hotel_id, hotel_name FROM hotels WHERE active = 1 ORDER BY hotel_name")
                ).fetchall()
            return {r.hotel_id: {"name": r.hotel_name, "code": ""} for r in rows}
        except Exception as e2:
            return {"__error__": str(e2)}


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
        "Hotel", [v["name"] for v in hotels.values()], key="cal_hotel"
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
        (hid for hid, v in hotels.items() if v["name"] == sel_hotel_name), None
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

    th_base = "padding:5px 6px;border:1px solid #ccc;white-space:nowrap;font-size:11px;font-weight:600;"
    td_day  = "padding:3px 2px;border:1px solid #e0e0e0;text-align:center;font-size:11px;min-width:28px;"
    td_board = "padding:4px 8px;border:1px solid #ddd;text-align:center;font-size:11px;font-weight:500;white-space:nowrap;"
    td_rt_base = "padding:5px 10px;border:1px solid #ccc;white-space:nowrap;font-size:12px;font-weight:600;vertical-align:middle;min-width:160px;"

    # Pre-compute rowspan per room type (count boards that have data)
    rt_rowspan = {}
    for rt_lower, _ in sorted_room_types:
        count = sum(1 for b in boards_to_show if any(k[0] == rt_lower and k[1] == b for k in status_matrix))
        rt_rowspan[rt_lower] = max(count, 1)

    html = ["<div style='overflow-x:auto;border:1px solid #ddd;border-radius:6px;'>"]
    html.append("<table style='border-collapse:collapse;width:100%;'>")

    # Header
    html.append("<thead>")
    html.append(
        f"<tr style='background:{C_HDR};'>"
        f"<th style='{th_base}min-width:160px;text-align:left;background:{C_HDR};'>Room Type</th>"
        f"<th style='{th_base}min-width:52px;background:{C_HDR};'>Board</th>"
    )
    for day in range(1, days_in_month + 1):
        dow_idx = date(sel_month.year, sel_month.month, day).weekday()
        bg = C_SAT if dow_idx == 5 else (C_SUN if dow_idx == 6 else C_HDR)
        html.append(
            f"<th style='{th_base}background:{bg};min-width:28px;text-align:center;font-weight:600;'>"
            f"{day}<br><span style='font-weight:400;color:#888;font-size:9px;'>"
            f"{dow[dow_idx][:2]}</span></th>"
        )
    html.append("</tr></thead><tbody>")

    # Data rows
    stripe_colors = ["#ffffff", "#f9f9f9"]
    for idx, (rt_lower, rt_original) in enumerate(sorted_room_types):
        row_bg = stripe_colors[idx % 2]
        active_boards = [b for b in boards_to_show if any(k[0] == rt_lower and k[1] == b for k in status_matrix)]
        if not active_boards:
            active_boards = boards_to_show[:1]
        rowspan = rt_rowspan[rt_lower]
        for b_idx, b in enumerate(active_boards):
            html.append(f"<tr style='background:{row_bg};'>")
            if b_idx == 0:
                border_top = "border-top:2px solid #bbb;" if idx > 0 else ""
                html.append(f"<td style='{td_rt_base}background:{row_bg};{border_top}' rowspan='{rowspan}'>{rt_original}</td>")
            html.append(f"<td style='{td_board}background:{row_bg};color:#555;'>{b}</td>")
            for day in range(1, days_in_month + 1):
                action = status_matrix.get((rt_lower, b, day))
                dow_idx = date(sel_month.year, sel_month.month, day).weekday()
                if action == "Closed":
                    cell_bg, cell_text, fw = C_CLOSED, "C", "font-weight:700;"
                elif action == "Re-Open":
                    cell_bg, cell_text, fw = C_REOPEN, "O", "font-weight:700;"
                else:
                    cell_bg = C_SAT if dow_idx == 5 else (C_SUN if dow_idx == 6 else row_bg)
                    cell_text, fw = "", ""
                html.append(f"<td style='{td_day}background:{cell_bg};{fw}'>{cell_text}</td>")
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
        f_hotel = c1.selectbox("Hotel", ["All"] + [v["name"] for v in hotels.values()])
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
    if "__error__" in hotels:
        st.error(f"ไม่สามารถโหลด Hotels ได้: {hotels['__error__']}")
        return
    hotel_ids = list(hotels.keys())

    # Determine default hotel index from prefill
    default_hotel_idx = 0
    if prefill and prefill.get("hotel_id") in hotel_ids:
        default_hotel_idx = hotel_ids.index(prefill["hotel_id"])

    # Hotel selectbox OUTSIDE form so plans reload when hotel changes
    hotel_id = st.selectbox(
        "Hotel *",
        hotel_ids,
        index=default_hotel_idx,
        format_func=lambda x: hotels.get(x, {}).get("name", x),
        key="create_ss_hotel",
    )

    # Load APC plans for the currently selected hotel (reactive)
    # hotel_code from hotels table, fallback to hotel_id (both follow H001/H002 pattern)
    hotel_code = hotels.get(hotel_id, {}).get("code", "") or hotel_id or ""
    apc_plans = _get_apc_plans(hotel_code) if hotel_code else []
    # Fallback: APSS hotel room_types when APC has no config
    fallback_rooms = _get_hotel_room_types(hotel_id) if (hotel_id and not apc_plans) else []

    # DEBUG — remove after fix confirmed
    with st.expander("🔍 Debug", expanded=False):
        st.write(f"hotel_id={hotel_id!r} hotel_code={hotel_code!r} apc_plans={apc_plans} fallback_rooms={fallback_rooms}")

    with st.form("create_stop_sale", clear_on_submit=True):
        if apc_plans:
            # Show room type + board options from APC Rate Structure
            plan_labels = [f"{rt}  /  {board_}" for rt, board_ in apc_plans]
            st.write("**Room Types & Rate Plan** — ดึงจาก APC Rate Structure")
            selected_plan_labels = st.multiselect(
                "เลือก Room Type / Board (เลือกได้หลายรายการ)",
                plan_labels,
                help="รายการนี้ดึงมาจาก APC Rate Structure โดยอัตโนมัติ",
            )
            custom_rooms = st.text_input(
                "Room Types เพิ่มเติม (คั่นด้วยลูกน้ำ)",
                placeholder="กรณีต้องการเพิ่มนอกเหนือจากรายการข้างต้น",
            )
            # Board is derived from selections; default ALL for mixed or when user types custom_rooms
            board = "ALL"
        elif fallback_rooms:
            st.info("ไม่พบ APC Rate Structure — ใช้ Room Types จาก APSS แทน")
            selected_plan_labels = []
            selected_presets = st.multiselect("Room Types (เลือกได้หลายห้อง)", fallback_rooms)
            custom_rooms = st.text_input(
                "Room Types เพิ่มเติม (คั่นด้วยลูกน้ำ)",
                placeholder="พิมพ์ room type ที่ต้องการ",
            )
            board = st.selectbox("Board Type", ["ALL", "RO", "RB"])
        else:
            st.info("ยังไม่มี Room Types — ระบุชื่อห้องโดยตรง")
            selected_plan_labels = []
            selected_presets = []
            custom_rooms = st.text_input(
                "Room Types (คั่นด้วยลูกน้ำ เช่น Superior Double or Twin, Deluxe Pool Access) *",
                placeholder="พิมพ์ room type ที่ต้องการ",
            )
            board = st.selectbox("Board Type", ["ALL", "RO", "RB"])

        action = st.selectbox("Action", ACTIONS)

        c3, c4 = st.columns(2)
        date_from = c3.date_input("วันที่เริ่มปิด *", value=date.today())
        date_to = c4.date_input("วันที่สิ้นสุด *", value=date.today())

        note = st.text_area("หมายเหตุ (optional)")
        auto_ticket = st.checkbox("สร้าง Ticket อัตโนมัติ", value=True,
                                  help="สร้าง ticket ประเภท Request/High ให้อัตโนมัติพร้อมกับ Stop Sale")

        if st.form_submit_button("🚫 สร้าง Stop Sale"):
            # Build room list and derive board from APC plans selections
            if apc_plans:
                # Parse selected "RoomType  /  Board" labels
                selected_pairs = []
                for lbl in selected_plan_labels:
                    parts = lbl.split("  /  ", 1)
                    if len(parts) == 2:
                        selected_pairs.append((parts[0].strip(), parts[1].strip()))
                all_rooms = [rt for rt, _ in selected_pairs]
                if custom_rooms.strip():
                    all_rooms += [r.strip() for r in custom_rooms.split(",") if r.strip()]
                # Derive board: if all selected pairs have same board, use it; else ALL
                boards_in_selection = {b for _, b in selected_pairs}
                if len(boards_in_selection) == 1 and not custom_rooms.strip():
                    board = boards_in_selection.pop()
                else:
                    board = "ALL"
            else:
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
            hotel_name = hotels.get(hotel_id, {}).get("name", "")
            hotel_code_save = hotel_code or None
            room_types_str = ", ".join(all_rooms)

            with engine().begin() as con:
                con.execute(text("""
                    INSERT INTO stop_sales (
                        stop_sale_id, hotel_id, hotel_name, hotel_code, room_types, board,
                        date_from, date_to, action, status,
                        requested_by, requested_by_name, note, created_at
                    ) VALUES (
                        :id, :hotel_id, :hotel_name, :hotel_code, :room_types, :board,
                        :date_from, :date_to, :action, 'Active',
                        :by, :by_name, :note, :now
                    )
                """), {
                    "id": ss_id,
                    "hotel_id": hotel_id,
                    "hotel_name": hotel_name,
                    "hotel_code": hotel_code_save,
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
