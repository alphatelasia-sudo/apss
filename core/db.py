"""Database connection and schema bootstrap for APSS."""
import os
import re
from functools import lru_cache

import streamlit as st
from sqlalchemy import create_engine, text


_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "apss.db")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            url = None
    if url:
        return re.sub(r"^postgres(ql)?://", "postgresql+psycopg2://", url)
    # Local dev fallback: SQLite
    os.makedirs(os.path.dirname(_SQLITE_PATH), exist_ok=True)
    return f"sqlite:///{os.path.abspath(_SQLITE_PATH)}"


@lru_cache(maxsize=1)
def engine():
    eng = create_engine(_database_url(), pool_pre_ping=True)
    pg = eng.dialect.name == "postgresql"
    with eng.begin() as con:
        for ddl in _schema_ddl(pg):
            con.execute(text(ddl))
    return eng


def _ts(pg: bool) -> str:
    return "TIMESTAMPTZ DEFAULT NOW()" if pg else "TEXT DEFAULT (datetime('now'))"


def _insert_ignore(pg: bool, table: str, cols: str, vals: str) -> str:
    if pg:
        return f"INSERT INTO {table} ({cols}) VALUES {vals} ON CONFLICT DO NOTHING"
    return f"INSERT OR IGNORE INTO {table} ({cols}) VALUES {vals}"


def _schema_ddl(pg: bool) -> list[str]:
    ts = _ts(pg)
    return [
        f"""CREATE TABLE IF NOT EXISTS hotels (
            hotel_id TEXT PRIMARY KEY,
            hotel_name TEXT NOT NULL,
            contact_person TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            lark_webhook TEXT,
            active INTEGER DEFAULT 1,
            created_at {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS hotel_contacts (
            contact_id TEXT PRIMARY KEY,
            hotel_id TEXT REFERENCES hotels(hotel_id),
            contact_type TEXT,
            name TEXT,
            phone TEXT,
            email TEXT,
            line_id TEXT,
            note TEXT,
            created_at {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS roles (
            role_id TEXT PRIMARY KEY,
            role_name TEXT NOT NULL,
            description TEXT,
            color TEXT DEFAULT '#6366f1',
            created_at {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            role_id TEXT REFERENCES roles(role_id),
            role_name TEXT,
            lark_user_id TEXT,
            active INTEGER DEFAULT 1,
            created_at {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            ticket_number TEXT UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            priority TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'New',
            hotel_id TEXT,
            hotel_name TEXT,
            customer_name TEXT,
            customer_phone TEXT,
            customer_email TEXT,
            customer_position TEXT,
            assigned_to TEXT,
            assigned_name TEXT,
            created_by TEXT,
            created_by_name TEXT,
            created_at {ts},
            updated_at {ts},
            sla_hours INTEGER,
            sla_deadline TEXT,
            resolved_at TEXT,
            closed_at TEXT,
            tags TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS comments (
            comment_id TEXT PRIMARY KEY,
            ticket_id TEXT REFERENCES tickets(ticket_id),
            agent_id TEXT,
            agent_name TEXT,
            comment TEXT NOT NULL,
            is_internal INTEGER DEFAULT 0,
            created_at {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS history (
            history_id TEXT PRIMARY KEY,
            ticket_id TEXT REFERENCES tickets(ticket_id),
            action TEXT,
            field TEXT,
            old_value TEXT,
            new_value TEXT,
            agent_id TEXT,
            agent_name TEXT,
            timestamp {ts}
        )""",
        f"""CREATE TABLE IF NOT EXISTS attachments (
            attachment_id TEXT PRIMARY KEY,
            ticket_id TEXT REFERENCES tickets(ticket_id),
            filename TEXT,
            mime_type TEXT,
            file_url TEXT,
            uploaded_by TEXT,
            uploaded_by_name TEXT,
            created_at {ts}
        )""",
        """CREATE TABLE IF NOT EXISTS sla_config (
            config_id TEXT PRIMARY KEY,
            priority TEXT UNIQUE,
            sla_hours INTEGER,
            warning_percent INTEGER DEFAULT 75,
            lark_webhook TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
        _insert_ignore(pg, "roles", "role_id, role_name, description, color",
                       "('rol_admin','Admin','System Administrator','#6366f1'),"
                       "('rol_support','Support Agent','Support Team Member','#10b981'),"
                       "('rol_manager','Manager','Team Manager','#f59e0b')"),
        _insert_ignore(pg, "sla_config", "config_id, priority, sla_hours, warning_percent",
                       "('sla_urgent','Urgent',24,75),('sla_high','High',48,75),"
                       "('sla_medium','Medium',72,75),('sla_low','Low',120,75)"),
        _insert_ignore(pg, "settings", "key, value",
                       "('system_name','Partner Support System'),"
                       "('company_name','Alphatel'),"
                       "('lark_webhook_default',''),"
                       "('lark_enabled','false'),"
                       "('timezone','Asia/Bangkok')"),
    ]


def get_setting(key: str, default: str = "") -> str:
    with engine().connect() as con:
        val = con.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key}).scalar()
    return val if val is not None else default


def set_setting(key: str, value: str):
    with engine().begin() as con:
        con.execute(text("INSERT INTO settings (key, value) VALUES (:k, :v) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
                    {"k": key, "v": value})
