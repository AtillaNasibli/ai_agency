"""Project Manager automation: scan 7 employees -> log to Google Sheet -> e-mail daily brief.
Usage: python bridge/run_daily.py [--dry-run] [--demo]
"""
import argparse, os, sys
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:  # optional
    load_dotenv = lambda: None

sys.path.insert(0, str(Path(__file__).parent))
from collect import collect, DEMO_ROWS
from daily_brief import build, send
from sheet_logger import log_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print only; no Sheet write, no e-mail")
    ap.add_argument("--demo", action="store_true", help="use built-in sample rows (no employee logs needed)")
    args = ap.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    rows = DEMO_ROWS if args.demo else collect(os.environ.get("EMPLOYEES_DIR") or str(Path(__file__).resolve().parent.parent / "employees"))
    if args.dry_run:
        print(build(rows)[0]); return
    n = log_rows(rows)
    print(f"Logged {n} rows to Google Sheet")
    send(rows)
    print("Daily brief e-mailed")


if __name__ == "__main__":
    main()
