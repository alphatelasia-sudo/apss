"""Settings: SLA config, Lark webhook, app settings."""
import streamlit as st
from sqlalchemy import text

from core.db import engine, get_setting, set_setting


def show():
    st.header("⚙️ Settings")
    tab_app, tab_sla, tab_lark = st.tabs(["App Settings", "SLA Config", "Lark Notifications"])

    with tab_app:
        _show_app_settings()
    with tab_sla:
        _show_sla_config()
    with tab_lark:
        _show_lark_config()


def _show_app_settings():
    st.subheader("Application Settings")
    system_name = get_setting("system_name", "Partner Support System")
    company_name = get_setting("company_name", "Alphatel")
    timezone = get_setting("timezone", "Asia/Bangkok")

    with st.form("app_settings"):
        system_name = st.text_input("System Name", value=system_name)
        company_name = st.text_input("Company Name", value=company_name)
        timezone = st.text_input("Timezone", value=timezone)
        if st.form_submit_button("Save"):
            set_setting("system_name", system_name)
            set_setting("company_name", company_name)
            set_setting("timezone", timezone)
            st.success("Settings saved.")


def _show_sla_config():
    st.subheader("SLA Configuration")
    with engine().connect() as con:
        rows = con.execute(
            text("SELECT * FROM sla_config ORDER BY sla_hours")
        ).fetchall()

    for r in rows:
        d = dict(r._mapping)
        with st.expander(f"Priority: **{d['priority']}** — {d['sla_hours']}h"):
            with st.form(f"sla_{d['config_id']}"):
                sla_hours = st.number_input("SLA Hours", value=int(d["sla_hours"]), min_value=1)
                warn_pct = st.number_input("Warning at % elapsed", value=int(d.get("warning_percent", 75)),
                                           min_value=1, max_value=99)
                webhook = st.text_input("Priority Lark Webhook", value=d.get("lark_webhook", ""))
                if st.form_submit_button("Save"):
                    with engine().begin() as con2:
                        con2.execute(text("""
                            UPDATE sla_config SET sla_hours=:h, warning_percent=:wp, lark_webhook=:wh
                            WHERE config_id=:id
                        """), {"h": sla_hours, "wp": warn_pct, "wh": webhook, "id": d["config_id"]})
                    st.success("SLA updated.")
                    st.rerun()


def _show_lark_config():
    st.subheader("Lark Notifications")
    enabled = get_setting("lark_enabled", "false") == "true"
    webhook = get_setting("lark_webhook_default", "")

    with st.form("lark_settings"):
        enabled = st.toggle("Enable Lark Notifications", value=enabled)
        webhook = st.text_input("Default Webhook URL", value=webhook)
        if st.form_submit_button("Save"):
            set_setting("lark_enabled", "true" if enabled else "false")
            set_setting("lark_webhook_default", webhook)
            st.success("Lark settings saved.")

    if enabled and webhook:
        if st.button("Send Test Notification"):
            from core.lark import notify
            ok = notify("🧪 APSS Test", "Lark notifications are working correctly.", color="green")
            st.success("Test sent!") if ok else st.error("Failed. Check webhook URL.")

show()
