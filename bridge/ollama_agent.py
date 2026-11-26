"""Run the AI Employees locally with Ollama (no cloud API key needed).

The employee kits (employees/<role>/) are full agent-harness kits (Claude Code etc.).
This runner is the lightweight local path: for each employee it sends one short, bounded
task to a local Ollama model, saves the DRAFT to ``employees/<role>/outputs/`` and appends a
run record to ``employees/<role>/runlog.jsonl`` -- the file the Project Manager bridge reads.

Employees only draft. Nothing is sent, posted or spent.

Usage:
    python bridge/ollama_agent.py --check                 # is Ollama up, is the model pulled?
    python bridge/ollama_agent.py --employee seo-employee # one employee
    python bridge/ollama_agent.py --all                   # 7 employees, then the Chief of Staff
"""
import argparse, json, os, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional
    load_dotenv = lambda: None

sys.path.insert(0, str(Path(__file__).parent))
from collect import collect, read_runlog  # noqa: E402
import llm  # noqa: E402
import council  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SYSTEM = (
    "You are {name}, one of eight AI employees at the agency '{agency}', working for the client "
    "'{client}'. Client brief: {brief}\n"
    "Your role: {role}. Your usual work: {tasks}.\n"
    "Rules: you only produce DRAFTS for a human to approve. You never claim to have sent, posted, "
    "published or spent anything. Be concrete, use short sections and bullet points, no filler."
)


def cfg():
    return (json.loads((ROOT / "config/agency.json").read_text(encoding="utf-8")),
            json.loads((ROOT / "config/ollama_tasks.json").read_text(encoding="utf-8")))


def host():
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def model():
    return os.environ.get("OLLAMA_MODEL", "llama3.1")


def check():
    import requests
    try:
        tags = requests.get(f"{host()}/api/tags", timeout=5).json()
    except Exception as e:  # noqa: BLE001
        print(f"Ollama is not reachable at {host()} ({e}). Start it with: ollama serve"); return False
    names = [m["name"] for m in tags.get("models", [])]
    want = model()
    if not any(n == want or n.split(":")[0] == want.split(":")[0] for n in names):
        print(f"Model '{want}' not found. Installed: {names or 'none'}. Run: ollama pull {want}"); return False
    print(f"Ollama OK at {host()}, model '{want}' available."); return True


def ensure_model():
    """Return a usable model name: OLLAMA_MODEL if installed, else the first installed one, else None."""
    import requests
    try:
        names = [m["name"] for m in requests.get(f"{host()}/api/tags", timeout=5).json().get("models", [])]
    except Exception:  # noqa: BLE001
        return None
    want = model()
    for n in names:
        if n == want or n.split(":")[0] == want.split(":")[0]:
            return n
    if names:
        os.environ["OLLAMA_MODEL"] = names[0]
        return names[0]
    return None


def chat(system, user):
    """Backward-compatible helper: text only. Route: local Ollama first, OpenRouter fallback (see llm.py)."""
    return llm.complete(system, user)["text"]


def write_runlog(folder: Path, record: dict):
    """Prefer the kit's own validated writer (node); fall back to a plain UTF-8 append."""
    node = shutil.which("node")
    script = folder / "scripts" / "runlog.mjs"
    if node and script.is_file():
        p = subprocess.run([node, str(script), "--stdin"], input=json.dumps(record), text=True,
                           capture_output=True, cwd=folder)
        if p.returncode == 0:
            return
        print(f"  runlog.mjs refused the record ({p.stderr.strip()[:120]}); writing plain record")
    with open(folder / "runlog.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def pm_context(employees_dir):
    lines = [f"- {r['agent']}: {r['task']} [{r['status']}]" for r in collect(employees_dir, str(ROOT / "config/agency.json"))]
    return "Latest reports from the other employees:\n" + "\n".join(lines)


def run_employee(slug, employees_dir):
    agency, tasks = cfg()
    meta, job = agency["employees"][slug], tasks[slug]
    folder = Path(employees_dir) / slug
    name = json.loads((folder / "employee.json").read_text(encoding="utf-8")).get("name", slug) if (folder / "employee.json").is_file() else slug
    system = SYSTEM.format(name=name, agency=agency["agency"], role=meta["role"], tasks=meta["tasks"],
                           client=os.environ.get("CLIENT_NAME", "Acme Coffee Roasters"),
                           brief=os.environ.get("CLIENT_BRIEF", "A small online business."))
    user = job["task"] + (("\n\n" + pm_context(employees_dir)) if slug == agency["project_manager"] else "")
    start = datetime.now().astimezone()
    print(f">>> {slug} ({job['routine']}) ...")
    extra = {}
    try:
        c = None
        if slug == agency["project_manager"] and len(council.members()) >= 2:
            try:
                c = council.deliberate(system, user)
            except Exception as e:  # noqa: BLE001
                print(f"    council failed ({type(e).__name__}); using a single model")
        if c:
            text, m = c["text"], c["metrics"]
            extra = {"provider": "council", "model": c["chairman"], "council_members": len(c["members"]),
                     "latency_s": m["latency_s"], "tokens": m["prompt_tokens"] + m["completion_tokens"]}
            how = f"council of {len(c['members'])} models"
        else:
            r = llm.complete(system, user)
            text = r["text"]
            extra = {"provider": r["provider"], "model": r["model"], "latency_s": r["latency_s"],
                     "tokens": r["prompt_tokens"] + r["completion_tokens"], "fallback_used": r["fallback"]}
            how = f"{r['provider']}/{r['model']}"
        out_dir = folder / "outputs"; out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{start:%Y-%m-%d}-{job['routine']}.md"
        out.write_text(f"# {name} - {job['routine']} ({start:%Y-%m-%d})\n\n_Draft generated by {how}. Needs human approval._\n\n{text}\n", encoding="utf-8")
        status, outputs, blockers = "ok", [f"outputs/{out.name}"], []
        notes = f"draft saved via {how}, {len(text.split())} words"
    except Exception as e:  # noqa: BLE001
        status, outputs, blockers, notes = "failed", [], [f"model call failed: {type(e).__name__}"], "run did not complete"
    write_runlog(folder, {"routine": job["routine"], "period": f"{start:%Y-%m-%d}",
                          "start": start.isoformat(timespec="seconds"),
                          "end": datetime.now().astimezone().isoformat(timespec="seconds"),
                          "status": status, "outputs": outputs, "blockers": blockers, "notes": notes,
                          "harness": "ollama-agent", **({"model": extra["model"]} if "model" in extra else {})})
    # efficiency metrics live beside the kit-validated run log (the kit's schema has no such fields)
    with open(folder / "metrics.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"routine": job["routine"], "end": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "status": status, **extra}) + "\n")
    print(f"    {status}: {notes}")
    return status == "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--employee")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    d = os.environ.get("EMPLOYEES_DIR") or str(ROOT / "employees")
    if args.check:
        sys.exit(0 if check() else 1)
    agency, _ = cfg()
    pm = agency["project_manager"]
    if args.employee:
        sys.exit(0 if run_employee(args.employee, d) else 1)
    if args.all:
        order = [s for s in agency["employees"] if s != pm] + [pm]
        results = [run_employee(s, d) for s in order]
        print(f"\n{sum(results)}/{len(results)} employees completed.")
        sys.exit(0 if all(results) else 1)
    ap.print_help()


if __name__ == "__main__":
    main()
