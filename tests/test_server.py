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
spec = importlib.util.spec_from_file_location("srv", ROOT / "server/tartim_rapor_sunucusu.py")
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
        self.assertFalse(limiter.allow("c"))  # günlük toplam sınır
        now[0] = 90000
        self.assertTrue(limiter.allow("a"))


class IssueTests(unittest.TestCase):
    def test_issue_body_escapes_note_and_summarises(self):
        title, body = srv.issue_for({"id": "20261016-1", "report": REPORT,
                                     "note": "```\n@biri <script> ```` dene"})
        self.assertEqual(title, "Cihaz raporu: MC-780MA (20261016-1)")
        self.assertIn("| Ekran karşılaştırması | 1/1 eşleşti |", body)
        self.assertIn("`````text", body)  # nottaki en uzun çitten uzun
        self.assertIn('"model": "MC-780MA"', body)

    def test_title_is_sanitised(self):
        rec = {"id": "x", "note": "", "report": {**REPORT, "device": {"model": "MC-780 [x](y) @z\n"}}}
        self.assertEqual(srv.issue_for(rec)[0], "Cihaz raporu: MC-780 x(y) z (x)")

    def test_large_report_is_truncated(self):
        big = {**REPORT, "measurements": [{"raw_hex": "ab" * 40000}]}
        _, body = srv.issue_for({"id": "x", "report": big, "note": ""})
        self.assertLess(len(body), 65536)
        self.assertIn("tamamı sunucuda saklanıyor", body)


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
        self.url = f"{self.base}/tartim/rapor"
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

        # Anahtar yoksa iletilmez, rapor beklemede kalır.
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
        self.assertIn("onaylamanız", str(ctx.exception))
        # Reddedilen deneme de sınıra sayılır (sınır: saatte 3).
        for _ in range(2):
            send_report(REPORT, url=self.url)
        with self.assertRaises(RuntimeError) as ctx:
            send_report(REPORT, url=self.url)
        self.assertIn("Çok fazla", str(ctx.exception))

    def test_full_store_rejects(self):
        original = srv.MAX_PENDING
        srv.MAX_PENDING = 1
        try:
            send_report(REPORT, url=self.url)
            with self.assertRaises(RuntimeError) as ctx:
                send_report(REPORT, url=self.url)
            self.assertIn("kabul etmiyor", str(ctx.exception))
        finally:
            srv.MAX_PENDING = original

    def test_health_and_unknown_paths(self):
        with urllib.request.urlopen(f"{self.base}/tartim/saglik", timeout=5) as r:
            self.assertEqual(json.load(r), {"ok": True})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base}/baska", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_unreachable_server(self):
        with self.assertRaises(RuntimeError) as ctx:
            send_report(REPORT, url="http://127.0.0.1:9/tartim/rapor", timeout=2)
        self.assertIn("ulaşılamadı", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
