import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tartim.report import send_report

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("srv", ROOT / "server/report_server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

REPORT = {"schema": 1, "mode": "hizli", "device": {"model": "MC-780MA", "connection": "seri port"},
          "system": {"os": "Pardus 25", "tartim": "0.5.0"},
          "measurements": [{"records": [{"recognized": True}],
                            "screen": [{"matches_expected": True}], "inputs": []}]}


class ValidationTests(unittest.TestCase):
    def test_valid(self):
        rec = srv.validate({"report": REPORT, "consent": True, "note": "x" * 5000})
        self.assertEqual(len(rec["note"]), srv.MAX_NOTE)

    def test_rejections(self):
        bad = [
            [],
            {"report": REPORT},  # onay yok
            {"report": {**REPORT, "schema": 2}, "consent": True},
            {"report": {**REPORT, "device": {"model": ""}}, "consent": True},
            {"report": {**REPORT, "measurements": [{}] * 11}, "consent": True},
            {"report": REPORT, "consent": True, "note": 5},
        ]
        for payload in bad:
            with self.subTest(payload=str(payload)[:40]), self.assertRaises(srv.Rejected):
                srv.validate(payload)

    def test_rate_limiter(self):
        now = [0.0]
        limiter = srv.RateLimiter(per_ip_hourly=2, global_daily=3, clock=lambda: now[0])
        self.assertEqual([limiter.allow("a") for _ in range(3)], [True, True, False])
        self.assertTrue(limiter.allow("b"))
        self.assertFalse(limiter.allow("c"))  # daily total limit
        now[0] = 90000
        self.assertTrue(limiter.allow("a"))


class IssueTests(unittest.TestCase):
    def test_issue_body_escapes_note_and_summarises(self):
        title, body = srv.issue_for({"id": "20261016-1", "report": REPORT,
                                     "note": "```\n@biri <script> ```` dene"})
        self.assertEqual(title, "Device report: MC-780MA (20261016-1)")
        self.assertIn("| Display comparison | 1/1 matched |", body)
        self.assertIn("`````text", body)  # longer than the longest fence in the note
        self.assertIn('"model": "MC-780MA"', body)

    def test_title_is_sanitised(self):
        rec = {"id": "x", "note": "", "report": {**REPORT, "device": {"model": "MC-780 [x](y) @z\n"}}}
        self.assertEqual(srv.issue_for(rec)[0], "Device report: MC-780 x(y) z (x)")

    def test_large_report_is_truncated(self):
        big = {**REPORT, "measurements": [{"raw_hex": "ab" * 40000}]}
        _, body = srv.issue_for({"id": "x", "report": big, "note": ""})
        self.assertLess(len(body), 65536)
        self.assertIn("the full report is stored on the", body)


class FakeGitHub(BaseHTTPRequestHandler):
    issues: list = []
    status = 201

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeGitHub.issues.append((self.path, self.headers["Authorization"], body))
        data = json.dumps({"html_url": f"https://github.com/x/issues/{len(self.issues)}"}).encode()
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = srv.Store(Path(self.tmp.name))
        self.saved = threading.Event()
        self.httpd, self.base = serve(srv.make_handler(self.store, srv.RateLimiter(per_ip_hourly=3),
                                                       self.saved.set))
        self.url = f"{self.base}/tartim/report"
        FakeGitHub.issues, FakeGitHub.status = [], 201

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_app_sends_report_and_server_forwards(self):
        result = send_report(REPORT, note="deneme", url=self.url)
        self.assertTrue(result["ok"])
        self.assertTrue(self.saved.is_set())
        pending = self.store.pending()
        self.assertEqual(len(pending), 1)
        if os.name == "posix":
            self.assertEqual(pending[0].stat().st_mode & 0o777, 0o600)

        # Without a token nothing is forwarded and the report waits.
        self.assertEqual(srv.forward_pending(self.store, None), 0)
        gh_server, gh_url = serve(FakeGitHub)
        try:
            gh = srv.GitHub("muratGursel/tartim-raporlar", "gizli-anahtar", api=gh_url)
            self.assertEqual(srv.forward_pending(self.store, gh), 1)
        finally:
            gh_server.shutdown()
            gh_server.server_close()
        path, auth, body = FakeGitHub.issues[0]
        self.assertEqual(path, "/repos/muratGursel/tartim-raporlar/issues")
        self.assertEqual(auth, "Bearer gizli-anahtar")
        self.assertIn("MC-780MA", body["title"])
        self.assertEqual(self.store.pending(), [])
        sent = json.loads(next(self.store.sent.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(sent["issue_url"], "https://github.com/x/issues/1")

    def test_forward_stops_on_auth_error(self):
        send_report(REPORT, url=self.url)
        gh_server, gh_url = serve(FakeGitHub)
        FakeGitHub.status = 401
        try:
            self.assertEqual(srv.forward_pending(self.store, srv.GitHub("r/r", "x", api=gh_url)), 0)
        finally:
            gh_server.shutdown()
            gh_server.server_close()
        self.assertEqual(len(self.store.pending()), 1)

    def test_server_errors_reach_the_app(self):
        with self.assertRaises(RuntimeError) as ctx:
            send_report(REPORT, url=self.url, consent=False)
        self.assertIn("must confirm", str(ctx.exception))
        # A rejected attempt counts towards the limit too (limit: 3 per hour).
        for _ in range(2):
            send_report(REPORT, url=self.url)
        with self.assertRaises(RuntimeError) as ctx:
            send_report(REPORT, url=self.url)
        self.assertIn("Too many", str(ctx.exception))

    def test_full_store_rejects(self):
        original = srv.MAX_PENDING
        srv.MAX_PENDING = 1
        try:
            send_report(REPORT, url=self.url)
            with self.assertRaises(RuntimeError) as ctx:
                send_report(REPORT, url=self.url)
            self.assertIn("not accepting", str(ctx.exception))
        finally:
            srv.MAX_PENDING = original

    def test_health_and_unknown_paths(self):
        with urllib.request.urlopen(f"{self.base}/tartim/health", timeout=5) as r:
            self.assertEqual(json.load(r), {"ok": True})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base}/baska", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_legacy_path_and_translated_errors(self):
        from tartim import i18n

        legacy = f"{self.base}/tartim/rapor"  # used by releases before 0.6
        self.assertTrue(send_report(REPORT, url=legacy)["ok"])
        i18n.setup("tr")
        try:
            with self.assertRaises(RuntimeError) as ctx:
                send_report(REPORT, url=legacy, consent=False)
        finally:
            i18n.setup("en")
        # The server answers in English with a code; the app shows it in Turkish.
        self.assertIn("onaylamanız gerekir", str(ctx.exception))

    def test_legacy_directories_are_migrated(self):
        root = Path(self.tmp.name) / "old"
        (root / "gelen").mkdir(parents=True)
        (root / "gelen" / "a.json").write_text("{}", encoding="utf-8")
        store = srv.Store(root)
        self.assertEqual([p.name for p in store.pending()], ["a.json"])
        self.assertFalse((root / "gelen").exists())

    def test_unreachable_server(self):
        with self.assertRaises(RuntimeError) as ctx:
            send_report(REPORT, url="http://127.0.0.1:9/tartim/report", timeout=2)
        self.assertIn("Could not reach", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
