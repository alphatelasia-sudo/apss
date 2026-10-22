"""
Migrate APSS data from Google Sheets → Supabase.

Usage:
    pip install gspread oauth2client sqlalchemy psycopg2-binary
    python migrate_from_sheets.py --spreadsheet-id <ID> --database-url <URL>

The script reads each sheet (Hotels, Agents, Roles, Tickets, Comments, History,
Attachments, SLA_Config, Settings, Hotel_Contacts) and upserts into Supabase.
Run it once after provisioning the Supabase project and before going live.
"""
import argparse
import uuid
from datetime import datetime, timezone

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from sqlalchemy import create_engine, text


SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

SHEETS = [
    "Hotels", "Agents", "Roles", "Tickets", "Comments",
    "History", "Attachments", "SLA_Config", "Settings", "Hotel_Contacts",
]


def rows_to_dicts(sheet) -> list[dict]:
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:] if any(row)]


def migrate(spreadsheet_id: str, database_url: str, creds_file: str):
    # Connect to Google Sheets
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file, SCOPE)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(spreadsheet_id)

    # Connect to Supabase
    url = database_url.replace("postgres://", "postgresql+psycopg2://").replace(
        "postgresql://", "postgresql+psycopg2://"
    )
    eng = create_engine(url)

    for sheet_name in SHEETS:
        try:
            sheet = ss.worksheet(sheet_name)
        except Exception:
            print(f"  Sheet '{sheet_name}' not found, skipping.")
            continue
        rows = rows_to_dicts(sheet)
        print(f"  {sheet_name}: {len(rows)} rows")
        if not rows:
            continue
        _insert_sheet(eng, sheet_name, rows)

    print("Migration complete.")


def _insert_sheet(eng, sheet_name: str, rows: list[dict]):
    table = {
        "Hotels":         "hotels",
        "Agents":         "agents",
        "Roles":          "roles",
        "Tickets":        "tickets",
        "Comments":       "comments",
        "History":        "history",
        "Attachments":    "attachments",
        "SLA_Config":     "sla_config",
        "Settings":       "settings",
        "Hotel_Contacts": "hotel_contacts",
    }[sheet_name]

    pk = {
        "hotels":        "hotel_id",
        "agents":        "agent_id",
        "roles":         "role_id",
        "tickets":       "ticket_id",
        "comments":      "comment_id",
        "history":       "history_id",
        "attachments":   "attachment_id",
        "sla_config":    "config_id",
        "settings":      "key",
        "hotel_contacts": "contact_id",
    }[table]

    with eng.begin() as con:
        for row in rows:
            # Ensure PK has a value
            if pk != "key" and not row.get(pk):
                row[pk] = str(uuid.uuid4())
            # Clean empty strings → None for non-text columns
            cleaned = {k: (v if v != "" else None) for k, v in row.items()}
            cols = list(cleaned.keys())
            vals = list(cleaned.values())
            placeholders = ", ".join(f":{c}" for c in cols)
            updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != pk)
            sql = (
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT ({pk}) DO UPDATE SET {updates}"
            )
            try:
                con.execute(text(sql), dict(zip(cols, vals)))
            except Exception as e:
                print(f"    Warning: {table} row {row.get(pk)}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate APSS from Google Sheets to Supabase")
    parser.add_argument("--spreadsheet-id", required=True, help="Google Spreadsheet ID")
    parser.add_argument("--database-url", required=True,
                        help="Supabase postgres URL (postgresql://...)")
    parser.add_argument("--creds", default="service_account.json",
                        help="Path to Google service account JSON key file")
    args = parser.parse_args()
    migrate(args.spreadsheet_id, args.database_url, args.creds)
