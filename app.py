"""AI Agency - autonomous app.

One command:  python app.py
 * 8 AI employees run by themselves in a loop (local Ollama model, no cloud key needed)
 * the Chief of Staff (PM) then audits everyone, appends rows to the Google Sheet ledger
   and e-mails the daily brief (once per day) -- automatically
 * a live dashboard at http://127.0.0.1:8080 shows what every employee is doing

Nobody has to click anything. Stop with Ctrl+C.
Env (all optional, see .env.example): CYCLE_MINUTES (default 60), PORT (default 8080).
"""
import json, os, sys, threading, time, traceback, webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bridge"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import ollama_agent as OA  # noqa: E402
from collect import collect, read_runlog  # noqa: E402
from daily_brief import send as send_mail  # noqa: E402
from sheet_logger import log_rows  # noqa: E402

CONFIG = json.loads((ROOT / "config/agency.json").read_text(encoding="utf-8"))
PM = CONFIG["project_manager"]
EMP_DIR = os.environ.get("EMPLOYEES_DIR") or str(ROOT / "employees")
CYCLE_MIN = float(os.environ.get("CYCLE_MINUTES", "60"))
PORT = int(os.environ.get("PORT", "8080"))
STATE_FILE = ROOT / "state" / "app_state.json"
LOCK = threading.Lock()

STATE = {"started": None, "cycles": 0, "current": "starting...", "next_cycle_at": None,
         "last_cycle_end": None, "email_last_date": None, "ledger": "not run yet",
         "email": "not run yet", "ollama": "checking...", "events": []}
if STATE_FILE.is_file():
    try:
        old = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for k in ("cycles", "email_last_date", "last_cycle_end"):
            STATE[k] = old.get(k, STATE[k])
    except Exception:  # noqa: BLE001
        pass


def event(msg):
    with LOCK:
        STATE["events"].insert(0, f"{datetime.now():%H:%M:%S}  {msg}")
        del STATE["events"][60:]
    print(msg, flush=True)


def save_state():
    STATE_FILE.parent.mkdir(exist_ok=True)
    keep = {k: STATE[k] for k in ("cycles", "email_last_date", "last_cycle_end")}
    STATE_FILE.write_text(json.dumps(keep), encoding="utf-8")


def configured_ledger():
    sid = os.environ.get("SHEET_ID", "")
    sa = Path(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "./service_account.json"))
    sa = sa if sa.is_absolute() else ROOT / sa
    if sa.is_file():
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = str(sa)
    return bool(sid) and sid != "your_google_sheet_id" and sa.is_file()


def configured_mail():
    u, p, t = (os.environ.get(k, "") for k in ("SMTP_USER", "SMTP_APP_PASSWORD", "MAIL_TO"))
    return all((u, p, t)) and "you@gmail.com" not in (u, t) and p != "your_gmail_app_password"


def pm_report():
    rows = collect(EMP_DIR)
    if configured_ledger():
        try:
            n = log_rows(rows)
            STATE["ledger"] = f"{n} rows logged at {datetime.now():%H:%M}"
            event(f"Ledger: {n} rows appended to Google Sheet")
        except Exception as e:  # noqa: BLE001
            STATE["ledger"] = f"error: {type(e).__name__}"
            event(f"Ledger ERROR: {type(e).__name__}: {str(e)[:100]}")
    else:
        STATE["ledger"] = "not configured (fill SHEET_ID + service_account.json)"
    today = str(date.today())
    if STATE["email_last_date"] == today:
        STATE["email"] = f"already sent today ({today})"
    elif configured_mail():
        try:
            send_mail(rows)
            STATE["email_last_date"] = today
            STATE["email"] = f"sent {datetime.now():%Y-%m-%d %H:%M}"
            event("Daily brief e-mailed")
        except Exception as e:  # noqa: BLE001
            STATE["email"] = f"error: {type(e).__name__}"
            event(f"E-mail ERROR: {type(e).__name__}: {str(e)[:100]}")
    else:
        STATE["email"] = "not configured (fill SMTP_* and MAIL_TO in .env)"


def cycle():
    m = OA.ensure_model()
    if not m:
        STATE["ollama"] = "NOT READY - start Ollama and `ollama pull llama3.1`"
        event("Ollama not reachable or no model installed; employees will log a failed run")
    else:
        STATE["ollama"] = f"ready, model {m}"
    order = [s for s in CONFIG["employees"] if s != PM] + [PM]
    for slug in order:
        STATE["current"] = f"{CONFIG['employees'][slug]['role']} is working..."
        try:
            ok = OA.run_employee(slug, EMP_DIR)
            event(f"{slug}: {'done' if ok else 'FAILED'}")
        except Exception as e:  # noqa: BLE001
            event(f"{slug}: crashed {type(e).__name__}")
            traceback.print_exc()
    STATE["current"] = "Project Manager is auditing + reporting..."
    try:
        pm_report()
    except Exception as e:  # noqa: BLE001
        event(f"PM report crashed: {type(e).__name__}")
    STATE["cycles"] += 1
    STATE["last_cycle_end"] = datetime.now().isoformat(timespec="seconds")
    save_state()


def scheduler():
    while True:
        try:
            cycle()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        nxt = datetime.now() + timedelta(minutes=CYCLE_MIN)
        STATE["next_cycle_at"] = nxt.isoformat(timespec="seconds")
        STATE["current"] = "idle - waiting for the next cycle"
        while datetime.now() < nxt:
            time.sleep(1)


def latest_output(slug):
    d = Path(EMP_DIR) / slug / "outputs"
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    return files[-1] if files else None


def status():
    rows = {r["agent"]: r for r in collect(EMP_DIR)}
    emps = []
    for slug, meta in CONFIG["employees"].items():
        logs = read_runlog(Path(EMP_DIR) / slug)
        last = logs[-1] if logs else None
        out = latest_output(slug)
        mpath = Path(EMP_DIR) / slug / "metrics.jsonl"
        met = {}
        if mpath.is_file():
            try:
                met = json.loads(mpath.read_text(encoding="utf-8").strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                met = {}
        if slug == PM:
            st = (last or {}).get("status", "no run yet")
            st = "OK" if st == "ok" else ("No log found" if not last else "Needs attention")
            task = (last or {}).get("notes", meta["tasks"])
        else:
            r = rows.get(meta["role"], {})
            st, task = r.get("status", "No log found"), r.get("task", meta["tasks"])
        emps.append({"slug": slug, "role": meta["role"], "status": st, "task": task,
                     "runs": len(logs), "last": (last or {}).get("end"), "has_output": bool(out),
                     "provider": met.get("provider"), "model": met.get("model"),
                     "latency_s": met.get("latency_s"), "tokens": met.get("tokens")})
    lasts = [e for e in emps if e["provider"]]
    local = sum(1 for e in lasts if e["provider"] in ("ollama", "council"))
    stats = {"runs_with_metrics": len(lasts), "local_runs": local,
             "total_tokens": sum(e["tokens"] or 0 for e in lasts),
             "avg_latency_s": round(sum(e["latency_s"] or 0 for e in lasts) / len(lasts), 1) if lasts else 0}
    with LOCK:
        return {**{k: STATE[k] for k in STATE if k != "events"}, "events": list(STATE["events"]),
                "employees": emps, "cycle_minutes": CYCLE_MIN, "stats": stats}


PAGE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>AI Agency</title><style>
:root{--bg:#f6f7f9;--fg:#1b1f24;--card:#fff;--mut:#6b7280;--line:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#0f1216;--fg:#e8eaed;--card:#181c22;--mut:#9aa0a6;--line:#2a2f37}}
body{margin:0;font:15px system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:18px 24px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:20px}
.sub{color:var(--mut);margin-top:4px}main{padding:20px 24px;max-width:1100px;margin:auto}
.bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:18px}
.box,.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.box b{display:block;color:var(--mut);font-size:12px;font-weight:600;margin-bottom:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}
.card h3{margin:0 0 2px;font-size:15px}.role{color:var(--mut);font-size:12px;margin-bottom:8px}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600}
.OK{background:#dcfce7;color:#166534}.Needs{background:#fee2e2;color:#991b1b}.Stale{background:#fef3c7;color:#92400e}.None{background:#e5e7eb;color:#374151}
.task{margin:8px 0;font-size:13px}a{color:#2563eb;cursor:pointer;font-size:13px}
pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;font-size:12.5px;max-height:240px;overflow:auto}
h2{font-size:15px;margin:22px 0 8px}#view{display:none}
</style></head><body><header><h1>AI Marketing &amp; Growth Agency</h1>
<div class=sub id=now>loading...</div></header><main>
<div class=bar id=bar></div><div class=grid id=grid></div>
<div id=view><h2 id=vt></h2><pre id=vb></pre></div>
<h2>Live activity</h2><pre id=ev></pre></main><script>
const $=id=>document.getElementById(id);
function pill(s){const c=s=="OK"?"OK":s.startsWith("Needs")?"Needs":s.startsWith("Stale")?"Stale":"None";const e=document.createElement("span");e.className="pill "+c;e.textContent=s;return e}
function box(t,v){const d=document.createElement("div");d.className="box";const b=document.createElement("b");b.textContent=t;d.append(b,document.createTextNode(v));return d}
async function show(slug,role){const r=await fetch("/api/output?slug="+slug);$("vt").textContent=role+" - latest draft";$("vb").textContent=await r.text();$("view").style.display="block";$("view").scrollIntoView({behavior:"smooth"})}
async function tick(){try{const s=await (await fetch("/api/status")).json();
$("now").textContent="Now: "+s.current;
const bar=$("bar");bar.replaceChildren(box("Cycles completed",s.cycles),box("Next cycle",s.next_cycle_at?s.next_cycle_at.replace("T"," "):"running now"),box("Ollama",s.ollama),box("Google Sheet ledger",s.ledger),box("Daily e-mail",s.email),box("Efficiency (last run each)",s.stats.local_runs+"/"+s.stats.runs_with_metrics+" local | "+s.stats.total_tokens+" tokens | avg "+s.stats.avg_latency_s+" s"));
const g=$("grid");g.replaceChildren();for(const e of s.employees){const c=document.createElement("div");c.className="card";
const h=document.createElement("h3");h.textContent=e.slug;const r=document.createElement("div");r.className="role";r.textContent=e.role;
const t=document.createElement("div");t.className="task";t.textContent=e.task;const m=document.createElement("div");m.className="role";m.textContent="runs: "+e.runs+(e.last?" | last: "+e.last.replace("T"," ").slice(0,19):"")+(e.provider?" | "+e.provider+(e.latency_s?" "+e.latency_s+"s":"")+(e.tokens?" "+e.tokens+" tok":""):"");
c.append(h,r,pill(e.status),t,m);if(e.has_output){const a=document.createElement("a");a.textContent="Read latest draft";a.onclick=()=>show(e.slug,e.role);c.append(a)}g.append(c)}
$("ev").textContent=s.events.join("\\n")||"(no events yet)"}catch(x){$("now").textContent="dashboard cannot reach the app"}}
tick();setInterval(tick,4000)</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, PAGE, "text/html")
        elif u.path == "/api/status":
            self._send(200, json.dumps(status()), "application/json")
        elif u.path == "/api/output":
            slug = parse_qs(u.query).get("slug", [""])[0]
            f = latest_output(slug) if slug in CONFIG["employees"] else None
            self._send(200 if f else 404, f.read_text(encoding="utf-8") if f else "no output yet", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


def main():
    STATE["started"] = datetime.now().isoformat(timespec="seconds")
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"AI Agency running. Dashboard: {url}  (cycle every {CYCLE_MIN:g} min, Ctrl+C to stop)", flush=True)
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
