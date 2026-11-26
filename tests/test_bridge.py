"""Offline tests: no Google, no SMTP, no Ollama needed. Run: python -m unittest discover -s tests -v"""
import json, os, sys, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))
import collect as C  # noqa: E402
import daily_brief  # noqa: E402


def rec(status="ok", hours_ago=1, blockers=None, routine="seo-standup", notes="done"):
    end = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"routine": routine, "period": "p", "start": end.isoformat(), "end": end.isoformat(),
            "status": status, "outputs": ["x.md"], "blockers": blockers or [], "notes": notes}


def make_fleet(tmp, per_slug):
    cfg = json.loads((ROOT / "config/agency.json").read_text())
    for slug in cfg["employees"]:
        (Path(tmp) / slug).mkdir(parents=True)
    for slug, lines in per_slug.items():
        (Path(tmp) / slug / "runlog.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class CollectTests(unittest.TestCase):
    def rows(self, per_slug):
        with tempfile.TemporaryDirectory() as t:
            make_fleet(t, per_slug)
            return {r["agent"]: r for r in C.collect(t)}

    def test_seven_employees_pm_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            make_fleet(t, {})
            self.assertEqual(len(C.collect(t)), 7)

    def test_no_log_found_and_changelog_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            make_fleet(t, {})
            (Path(t) / "seo-employee" / "CHANGELOG.md").write_text("# changelog\nfailed error blocked")
            r = {x["agent"]: x for x in C.collect(t)}["SEO/AEO Specialist + Researcher"]
            self.assertEqual(r["status"], "No log found")

    def test_ok(self):
        r = self.rows({"seo-employee": [json.dumps(rec())]})["SEO/AEO Specialist + Researcher"]
        self.assertEqual(r["status"], "OK"); self.assertIn("seo-standup", r["task"])

    def test_failed_and_blockers_need_attention(self):
        r = self.rows({"seo-employee": [json.dumps(rec("failed"))]})["SEO/AEO Specialist + Researcher"]
        self.assertEqual(r["status"], "Needs attention")
        r = self.rows({"seo-employee": [json.dumps(rec("ok", blockers=["x"]))]})["SEO/AEO Specialist + Researcher"]
        self.assertEqual(r["status"], "Needs attention")

    def test_stale(self):
        r = self.rows({"seo-employee": [json.dumps(rec(hours_ago=50))]})["SEO/AEO Specialist + Researcher"]
        self.assertEqual(r["status"], "Stale (>36h)")

    def test_skipped_ignored_and_bad_lines_tolerated(self):
        lines = [json.dumps(rec(routine="a", hours_ago=3)), "not json", json.dumps(rec("skipped-already-ran", hours_ago=0, routine="b"))]
        r = self.rows({"seo-employee": lines})["SEO/AEO Specialist + Researcher"]
        self.assertTrue(r["task"].startswith("a"))

    def test_bom_tolerated(self):
        with tempfile.TemporaryDirectory() as t:
            make_fleet(t, {})
            (Path(t) / "seo-employee" / "runlog.jsonl").write_bytes(b"\xef\xbb\xbf" + json.dumps(rec()).encode() + b"\n")
            self.assertEqual({x["agent"]: x for x in C.collect(t)}["SEO/AEO Specialist + Researcher"]["status"], "OK")


class BriefTests(unittest.TestCase):
    def test_build(self):
        text, html = daily_brief.build(C.DEMO_ROWS, "https://example.com/sheet")
        self.assertIn("6/7 employees OK", text); self.assertIn("<table", html); self.assertIn("example.com/sheet", html)


class _Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"message": {"role": "assistant", "content": "Draft: hello world from the fake model"}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        body = json.dumps({"models": [{"name": "llama3.1:latest"}]}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a): pass


class OllamaRunnerTests(unittest.TestCase):
    def test_run_employee_writes_output_and_runlog(self):
        srv = HTTPServer(("127.0.0.1", 0), _Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{srv.server_port}"
        import ollama_agent as O
        with tempfile.TemporaryDirectory() as t:
            make_fleet(t, {})
            self.assertTrue(O.run_employee("seo-employee", t))
            logs = C.read_runlog(Path(t) / "seo-employee")
            self.assertEqual(logs[-1]["status"], "ok"); self.assertEqual(logs[-1]["harness"], "ollama-agent")
            self.assertTrue(list((Path(t) / "seo-employee" / "outputs").glob("*.md")))
            r = {x["agent"]: x for x in C.collect(t)}["SEO/AEO Specialist + Researcher"]
            self.assertEqual(r["status"], "OK")
        srv.shutdown()

    def test_ollama_down_is_logged_as_failed(self):
        os.environ["OLLAMA_HOST"] = "http://127.0.0.1:9"
        import ollama_agent as O
        with tempfile.TemporaryDirectory() as t:
            make_fleet(t, {})
            self.assertFalse(O.run_employee("seo-employee", t))
            self.assertEqual(C.read_runlog(Path(t) / "seo-employee")[-1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
