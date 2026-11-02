"""Send Lark webhook notifications for ticket events."""
import requests
import streamlit as st

from core.db import get_setting


def _webhook_url(ticket_priority: str | None = None) -> str | None:
    """Resolve the webhook URL: per-priority SLA webhook, then global default, then secrets."""
    if ticket_priority:
        from sqlalchemy import text
        from core.db import engine
        with engine().connect() as con:
            url = con.execute(
                text("SELECT lark_webhook FROM sla_config WHERE priority = :p"),
                {"p": ticket_priority}
            ).scalar()
        if url:
            return url
    url = get_setting("lark_webhook_default")
    if url:
        return url
    try:
        return st.secrets.get("lark", {}).get("webhook_url")
    except Exception:
        return None


def notify(title: str, body: str, priority: str | None = None, color: str = "green") -> bool:
    """Post a card message to Lark. Returns True on success."""
    enabled = get_setting("lark_enabled", "false").lower() == "true"
    if not enabled:
        return False
    url = _webhook_url(priority)
    if not url:
        return False
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": body}}],
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def notify_ticket_created(ticket: dict):
    notify(
        f"🎫 New Ticket #{ticket.get('ticket_number')}",
        f"**{ticket.get('title')}**\nPriority: {ticket.get('priority')} | Hotel: {ticket.get('hotel_name', '-')}",
        priority=ticket.get("priority"),
        color="blue",
    )


def notify_ticket_updated(ticket: dict, changes: str):
    notify(
        f"🔄 Ticket #{ticket.get('ticket_number')} Updated",
        f"**{ticket.get('title')}**\n{changes}",
        priority=ticket.get("priority"),
        color="yellow",
    )


def notify_ticket_closed(ticket: dict):
    notify(
        f"🔒 Ticket #{ticket.get('ticket_number')} Closed",
        f"**{ticket.get('title')}**\nPriority: {ticket.get('priority')} | Hotel: {ticket.get('hotel_name', '-')}",
        priority=ticket.get("priority"),
        color="grey",
    )


def notify_ticket_overdue(ticket: dict) -> bool:
    return notify(
        f"⏰ Due Date Passed — #{ticket.get('ticket_number')}",
        f"**{ticket.get('title')}**\n"
        f"Due: {ticket.get('due_date')} | Priority: {ticket.get('priority')} | Hotel: {ticket.get('hotel_name', '-')}",
        priority=ticket.get("priority"),
        color="orange",
    )


def notify_stop_sale(ss: dict) -> bool:
    action = ss.get("action", "Closed")
    color = "red" if action == "Closed" else "green"
    icon = "🚫" if action == "Closed" else "✅"
    return notify(
        f"{icon} Stop Sale {action} — {ss.get('hotel_name', '-')}",
        f"**ห้องพัก:** {ss.get('room_types', '-')}\n"
        f"**Board:** {ss.get('board', '-')}\n"
        f"**วันที่:** {ss.get('date_from')} → {ss.get('date_to')}\n"
        f"**Ticket:** {ss.get('ticket_ref', '-')} | **By:** {ss.get('requested_by_name', '-')}",
        color=color,
    )


def notify_sla_breach(ticket: dict):
    notify(
        f"🚨 SLA Breach — #{ticket.get('ticket_number')}",
        f"**{ticket.get('title')}**\nPriority: {ticket.get('priority')} | Hotel: {ticket.get('hotel_name', '-')}",
        priority=ticket.get("priority"),
        color="red",
    )
