# Alphatel Partner Support System (APSS)

Streamlit + Supabase replacement for the Google Apps Script APSS.  
Deployed at **apss.alphatel.asia** via Streamlit Community Cloud.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Streamlit 1.46 (`streamlit[auth]`) |
| Database | Supabase Postgres via SQLAlchemy 2 + psycopg2 |
| Auth | Google Sign-in via `st.login` |
| Notifications | Lark webhook (configurable in UI) |
| Deploy | Streamlit Community Cloud (auto-deploy on GitHub push) |

## Project Structure

```
apss/
├── app.py                  # Entry point, navigation
├── views/
│   ├── dashboard.py        # Ticket stats, SLA breaches, recent tickets
│   ├── tickets.py          # Create / list / view / edit / close tickets + comments
│   ├── hotels.py           # Hotel list management + contacts
│   ├── agents.py           # Agent & role management
│   ├── reports.py          # Stats by date range, hotel, agent
│   └── settings.py         # SLA config, Lark webhook, app settings
├── core/
│   ├── db.py               # SQLAlchemy engine, schema bootstrap, settings helpers
│   ├── auth.py             # Google Sign-in gate + current_user()
│   ├── lark.py             # Lark webhook notifications
│   └── sla.py              # SLA deadline & status helpers
├── migrate_from_sheets.py  # One-time data migration from Google Sheets
├── requirements.txt
└── .streamlit/
    └── secrets.toml.example
```

## Setup

### 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) → New Project → **apss** (or any name).
2. Copy the **Session pooler** connection string from Project → Connect.
3. The schema is created automatically on first app start (no manual SQL needed).

### 2. Configure secrets

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml with your real values
```

For Streamlit Community Cloud, paste each value into **App settings → Secrets**.

### 3. Google OAuth (same credentials as APC)

- Add `https://apss.alphatel.asia/oauth2callback` as an authorized redirect URI in Google Cloud Console.
- Copy `client_id`, `client_secret` from the APC project or create a new OAuth 2.0 client.

### 4. Run locally

```bash
cd "D:\My Folder C\Alphatel\apss"
pip install -r requirements.txt
streamlit run app.py
```

### 5. Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repository (e.g. `alphatel/apss`).
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app.
3. Set **Main file path** to `app.py`.
4. Add secrets (from `secrets.toml.example`) in App settings → Secrets.
5. Add a custom domain: **apss.alphatel.asia** → Settings → Custom domain.

## Data Migration from Google Sheets

```bash
pip install gspread oauth2client
python migrate_from_sheets.py \
  --spreadsheet-id YOUR_SHEET_ID \
  --database-url "postgresql://postgres.xxx:PASSWORD@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres" \
  --creds service_account.json
```

- `service_account.json`: Google service account key with read access to the spreadsheet.
- Run **once** before going live. The script upserts, so it is safe to run again.

## Features

| Feature | Status |
|---------|--------|
| Dashboard — stats, SLA breach count, recent tickets | ✅ |
| Tickets — create, list, filter, edit, close | ✅ |
| Comments — internal & external per ticket | ✅ |
| SLA tracking — deadline, warning, breach indicators | ✅ |
| Hotels — list, create, edit, contacts | ✅ |
| Agents & Roles — manage agents, role colors | ✅ |
| Reports — by date range, hotel, agent, priority, daily trend | ✅ |
| Settings — SLA config, Lark webhook, app settings | ✅ |
| Google Sign-in | ✅ |
| Lark notifications on ticket create/update/SLA breach | ✅ |
| File attachments | ⏳ (URL-based; no Google Drive dependency) |
