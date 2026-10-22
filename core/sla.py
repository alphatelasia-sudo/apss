"""SLA calculation helpers."""
from datetime import datetime, timezone

from sqlalchemy import text

from core.db import engine


def get_sla_hours(priority: str) -> int:
    with engine().connect() as con:
        hours = con.execute(
            text("SELECT sla_hours FROM sla_config WHERE priority = :p"),
            {"p": priority}
        ).scalar()
    return int(hours) if hours else 72


def compute_deadline(created_at: datetime, priority: str) -> datetime:
    from datetime import timedelta
    hours = get_sla_hours(priority)
    return created_at + timedelta(hours=hours)


def sla_status(ticket: dict) -> str:
    """'ok' | 'warning' | 'breached' | 'resolved'"""
    if ticket.get("status") in ("Resolved", "Closed"):
        return "resolved"
    deadline = ticket.get("sla_deadline")
    if not deadline:
        return "ok"
    if isinstance(deadline, str):
        try:
            deadline = datetime.fromisoformat(deadline)
        except Exception:
            return "ok"
    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if now >= deadline:
        return "breached"
    # warning at 75% of elapsed time
    created_at = ticket.get("created_at")
    if created_at:
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except Exception:
                return "ok"
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        total = (deadline - created_at).total_seconds()
        elapsed = (now - created_at).total_seconds()
        if total > 0 and elapsed / total >= 0.75:
            return "warning"
    return "ok"
