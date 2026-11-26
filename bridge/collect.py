"""Collect the latest activity of each AI Employee from its run log.

Every employee kit appends one JSON object per routine run to ``<employee>/runlog.jsonl``
(written by the kit's own ``scripts/runlog.mjs``). A record looks like::

    {"routine": "seo-standup", "period": "2026-03-05", "start": "...", "end": "...",
     "status": "ok", "outputs": [...], "blockers": [...], "notes": "one line"}

The Project Manager bridge reads the newest records and turns them into ledger rows:
``agent`` (role), ``task`` (what was done), ``status`` (OK / Needs attention / Stale / No log found).
Static kit documents (CHANGELOG.md, README.md, ...) are never treated as activity.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

STALE_HOURS = 36
OK_STATUSES = {"ok"}
SKIP_PREFIX = "skipped"          # skipped-already-ran, skipped-out-of-window: not a problem, not activity
RUNLOG = "runlog.jsonl"


def read_runlog(folder: Path):
    """Return all valid records of folder/runlog.jsonl (bad lines are ignored)."""
    path = folder / RUNLOG
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and "routine" in rec and "status" in rec:
            records.append(rec)
    return records


def _parse_time(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def describe(rec, max_len=140):
    """One readable line for 'Task Performed'."""
    notes = (rec.get("notes") or "").strip()
    outputs = rec.get("outputs") or []
    text = rec["routine"]
    if notes:
        text += f": {notes}"
    elif outputs:
        text += f": {outputs[0]}"
    return text[:max_len]


def classify(rec, now=None):
    """Map a run record to the ledger's Output Status."""
    now = now or datetime.now(timezone.utc)
    status = str(rec.get("status", "")).lower()
    if status not in OK_STATUSES or rec.get("blockers"):
        return "Needs attention"
    end = _parse_time(rec.get("end") or rec.get("start"))
    if end and (now - end).total_seconds() / 3600 > STALE_HOURS:
        return "Stale (>36h)"
    return "OK"


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "agency.json"


def collect(employees_dir: str, config_path=DEFAULT_CONFIG, now=None):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    rows = []
    for slug, meta in cfg["employees"].items():
        if slug == cfg["project_manager"]:
            continue  # the PM audits the others
        folder = Path(employees_dir) / slug
        real = [r for r in read_runlog(folder) if not str(r.get("status", "")).startswith(SKIP_PREFIX)]
        if not real:
            rows.append(dict(agent=meta["role"], task=meta["tasks"], status="No log found", detail=""))
            continue
        latest = max(real, key=lambda r: str(r.get("end") or r.get("start") or ""))
        rows.append(dict(agent=meta["role"], task=describe(latest),
                         status=classify(latest, now), detail=str(folder / RUNLOG)))
    return rows


DEMO_ROWS = [
    dict(agent="Campaign Builder / Launch Lead", task="gtm-board-standup: launch board refreshed, 3 cards moved", status="OK", detail="demo"),
    dict(agent="SEO/AEO Specialist + Researcher", task="seo-draft-run: 1 article drafted (coffee-grind-size-guide)", status="OK", detail="demo"),
    dict(agent="Technical Auditor", task="web-site-sweep: 2 broken links found, fix list filed", status="Needs attention", detail="demo"),
    dict(agent="Content Writer", task="soc-draft-queue: 5 posts drafted in brand voice", status="OK", detail="demo"),
    dict(agent="Performance Analyst", task="ads-desk-standup: weekly change list ready", status="OK", detail="demo"),
    dict(agent="Outbound Strategist", task="sales-first-touch-drafts: 8 first-touch drafts staged", status="OK", detail="demo"),
    dict(agent="Support Triage", task="csat-inbox-sweep: 14 tickets triaged, 1 churn flag", status="OK", detail="demo"),
]
