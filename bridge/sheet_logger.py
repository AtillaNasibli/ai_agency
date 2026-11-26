"""Append ledger rows to Google Sheets: [Timestamp | Agent Name | Task Performed | Output Status]."""
import os
from datetime import datetime, timezone

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER = ["Timestamp", "Agent Name", "Task Performed", "Output Status"]


def _worksheet():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=SCOPES)
    sh = gspread.authorize(creds).open_by_key(os.environ["SHEET_ID"])
    tab = os.environ.get("SHEET_TAB", "Ledger")
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=1000, cols=4)
    if ws.row_values(1) != HEADER:
        ws.insert_row(HEADER, 1)
    return ws


def log_rows(rows):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    values = [[ts, r["agent"], r["task"], r["status"]] for r in rows]
    _worksheet().append_rows(values, value_input_option="USER_ENTERED")
    return len(values)
