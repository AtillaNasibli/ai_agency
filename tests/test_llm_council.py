"""Offline tests for model routing (Ollama/OpenRouter) and the LLM council. No real model needed."""
import json, os, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge"))
import llm, council, collect as C  # noqa: E402
import test_bridge as TB  # noqa: E402  (reuse make_fleet)


class Fake(BaseHTTPRequestHandler):
    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "llama3.1:latest"}, {"name": "llama3.2:latest"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        content = body["messages"][-1]["content"]
        if "FINAL RANKING" in content:
            text = "Both fine.\nFINAL RANKING:\n1. Response B\n2. Response A"
        elif "chairman" in content:
            text = "FINAL combined answer"
        else:
            text = f"Answer from {body.get('model')}"
        if self.path.endswith("/chat/completions"):      # OpenRouter / OpenAI style
            self._send({"choices": [{"message": {"content": "cloud: " + text}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        else:                                             # Ollama style
            self._send({"message": {"role": "assistant", "content": text}, "prompt_eval_count": 5, "eval_count": 7})

    def log_message(self, *a): pass


class RouteAndCouncil(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.saved = dict(os.environ)
        for k in ("OPENROUTER_API_KEY", "COUNCIL_MODELS", "COUNCIL_CHAIRMAN", "LLM_ROUTE"):
            os.environ.pop(k, None)
        os.environ["OLLAMA_HOST"] = self.url
        llm.litellm = None      # these tests cover the built-in HTTP path

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.saved)

    def test_local_first_returns_metrics(self):
        r = llm.complete("sys", "hello")
        self.assertEqual((r["provider"], r["fallback"]), ("ollama", False))
        self.assertEqual((r["prompt_tokens"], r["completion_tokens"]), (5, 7))

    def test_cloud_fallback_when_local_down(self):
        os.environ.update(OLLAMA_HOST="http://127.0.0.1:9", OPENROUTER_API_KEY="k", OPENROUTER_BASE=self.url)
        r = llm.complete("sys", "hello")
        self.assertEqual((r["provider"], r["fallback"]), ("openrouter", True))
        self.assertTrue(r["text"].startswith("cloud:"))

    def test_no_route_raises(self):
        os.environ["OLLAMA_HOST"] = "http://127.0.0.1:9"
        with self.assertRaises(RuntimeError):
            llm.complete("sys", "hello")

    def test_parse_ranking(self):
        self.assertEqual(council.parse_ranking("x\nFINAL RANKING:\n1. Response C\n2. Response A\n3. Response Z", {"A", "B", "C"}), ["C", "A"])

    def test_members_from_installed_models(self):
        self.assertEqual(council.members(), ["ollama:llama3.1:latest", "ollama:llama3.2:latest"])

    def test_single_model_means_no_council(self):
        os.environ["COUNCIL_MODELS"] = "ollama:llama3.1"
        self.assertEqual(council.members(), [])

    def test_council_three_stages(self):
        c = council.deliberate("sys", "What should we decide?")
        self.assertIn("## Council final answer", c["text"]); self.assertIn("FINAL combined answer", c["text"])
        self.assertEqual(len(c["ranking"]), 2)
        self.assertEqual(c["metrics"]["calls"], 5)      # 2 answers + 2 rankings + 1 chairman

    def test_pm_run_uses_council_and_logs_it(self):
        import ollama_agent as O
        with tempfile.TemporaryDirectory() as t:
            TB.make_fleet(t, {})
            self.assertTrue(O.run_employee("chief-of-staff", t))
            rec = C.read_runlog(Path(t) / "chief-of-staff")[-1]
            met = json.loads((Path(t) / "chief-of-staff" / "metrics.jsonl").read_text().strip().splitlines()[-1])
            self.assertEqual((rec["status"], met["provider"], met["council_members"]), ("ok", "council", 2))
            self.assertIn("Council final answer", next((Path(t) / "chief-of-staff" / "outputs").glob("*.md")).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
