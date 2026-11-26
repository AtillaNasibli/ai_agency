"""Build and send the scannable daily status bulletin by e-mail."""
import os, smtplib, ssl
from datetime import date
from email.message import EmailMessage

ICON = {"OK": "🟢", "Needs attention": "🔴", "Stale (>36h)": "🟡", "No log found": "⚪"}


def build(rows, sheet_url=""):
    ok = sum(r["status"] == "OK" for r in rows)
    text = [f"AI Agency Daily Brief — {date.today()}", f"{ok}/{len(rows)} employees OK", ""]
    html = [f"<h2>AI Agency Daily Brief — {date.today()}</h2><p><b>{ok}/{len(rows)}</b> employees OK</p>",
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>",
            "<tr><th>Status</th><th>Agent</th><th>Latest task</th></tr>"]
    for r in rows:
        i = ICON.get(r["status"], "⚪")
        text.append(f"{i} {r['agent']}: {r['task']} [{r['status']}]")
        html.append(f"<tr><td>{i} {r['status']}</td><td>{r['agent']}</td><td>{r['task']}</td></tr>")
    html.append("</table>")
    if sheet_url:
        text += ["", f"Ledger: {sheet_url}"]
        html.append(f"<p><a href='{sheet_url}'>Open the live Google Sheet ledger</a></p>")
    return "\n".join(text), "".join(html)


def send(rows):
    sheet_url = f"https://docs.google.com/spreadsheets/d/{os.environ['SHEET_ID']}"
    text, html = build(rows, sheet_url)
    msg = EmailMessage()
    msg["Subject"] = f"[AI Agency] Daily Brief {date.today()}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["MAIL_TO"]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 465)),
                          context=ssl.create_default_context()) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"])
        s.send_message(msg)
