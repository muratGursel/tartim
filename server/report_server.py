"""Tartım device report server.

Receives device reports from the application, validates them, stores them on
disk and opens them as issues in a private GitHub repository. Uses only the
Python standard library.

The GitHub access token is never in the code or the repository. systemd passes
it with ``LoadCredential`` (``$CREDENTIALS_DIRECTORY/github-token``); see
server/INSTALL.md. Without a token reports are only stored and are forwarded
once a token is added.

Errors are returned as ``{"ok": false, "code": "...", "error": "..."}``; the
application shows a translated message for the ``code``.

    python3 report_server.py --port 8095 --data /var/lib/tartim-rapor
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 2 * 1024 * 1024
MAX_MEASUREMENTS = 10
MAX_NOTE = 2000
ISSUE_JSON_LIMIT = 60000  # a GitHub issue body is at most 65536 characters
PER_IP_HOURLY = 5
GLOBAL_DAILY = 200
MAX_PENDING = 500  # reports waiting to be forwarded: protects against filling the disk

# The Turkish paths are used by releases before 0.6 and keep working.
REPORT_PATHS = ("/tartim/report", "/tartim/rapor")
HEALTH_PATHS = ("/tartim/health", "/tartim/saglik")

log = logging.getLogger("tartim-report")


class Rejected(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def validate(payload: object) -> dict:
    """Validates a request; returns the record to store if it is valid."""
    if not isinstance(payload, dict):
        raise Rejected(HTTPStatus.BAD_REQUEST, "invalid-request", "Invalid request.")
    if payload.get("consent") is not True:
        raise Rejected(HTTPStatus.BAD_REQUEST, "consent-required",
                       "You must confirm that the measurement does not belong to a real client.")
    report = payload.get("report")
    if not isinstance(report, dict) or report.get("schema") != 1:
        raise Rejected(HTTPStatus.BAD_REQUEST, "unknown-format", "Unknown report format.")
    device = report.get("device")
    if not isinstance(device, dict) or not isinstance(device.get("model"), str) \
            or not 0 < len(device["model"].strip()) <= 64:
        raise Rejected(HTTPStatus.BAD_REQUEST, "model-missing", "The device model is missing.")
    measurements = report.get("measurements")
    if not isinstance(measurements, list) or len(measurements) > MAX_MEASUREMENTS:
        raise Rejected(HTTPStatus.BAD_REQUEST, "measurements-invalid",
                       "The measurement list is not valid.")
    note = payload.get("note") or ""
    if not isinstance(note, str):
        raise Rejected(HTTPStatus.BAD_REQUEST, "note-invalid", "The note must be text.")
    return {"report": report, "note": note[:MAX_NOTE]}


class RateLimiter:
    def __init__(self, per_ip_hourly: int = PER_IP_HOURLY, global_daily: int = GLOBAL_DAILY,
                 clock=time.monotonic):
        self.per_ip, self.global_daily, self.clock = per_ip_hourly, global_daily, clock
        self.hits: dict[str, deque] = defaultdict(deque)
        self.all: deque = deque()
        self.lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        now = self.clock()
        with self.lock:
            hits = self.hits[ip]
            while hits and now - hits[0] > 3600:
                hits.popleft()
            while self.all and now - self.all[0] > 86400:
                self.all.popleft()
            if len(hits) >= self.per_ip or len(self.all) >= self.global_daily:
                return False
            hits.append(now)
            self.all.append(now)
            return True


class Store:
    """Reports live in ``incoming/`` (to forward) and ``sent/``, with 0600 permissions."""

    LEGACY_DIRS = {"gelen": "incoming", "iletildi": "sent"}  # names before 0.6

    def __init__(self, root: Path):
        self.incoming = root / "incoming"
        self.sent = root / "sent"
        for d in (self.incoming, self.sent):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
        for old, new in self.LEGACY_DIRS.items():
            legacy = root / old
            if legacy.is_dir():
                for path in legacy.glob("*.json"):
                    path.rename(root / new / path.name)
                legacy.rmdir()

    def save(self, record: dict) -> str:
        rid = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        record = {"id": rid, "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  **record}
        path = self.incoming / f"{rid}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1)
        return rid

    def full(self) -> bool:
        return sum(1 for _path in self.incoming.glob("*.json")) >= MAX_PENDING

    def pending(self) -> list[Path]:
        return sorted(self.incoming.glob("*.json"))

    def mark_sent(self, path: Path, issue_url: str) -> None:
        record = json.loads(path.read_text(encoding="utf-8"))
        record["issue_url"] = issue_url
        target = self.sent / path.name
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1)
        path.unlink()


def _fence(text: str) -> str:
    """A code fence longer than the longest run of ` in the content (Markdown escaping)."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def issue_for(record: dict) -> tuple[str, str]:
    report = record["report"]
    device = report.get("device", {})
    system = report.get("system", {})
    measurements = report.get("measurements", [])
    recognized = sum(1 for m in measurements for r in m.get("records", []) if r.get("recognized"))
    checks = [c for m in measurements for c in m.get("screen", []) + m.get("inputs", [])]
    matched = sum(1 for c in checks if c.get("matches_expected"))
    notes = sum(len(m.get("bluetooth", {}).get("notifications", [])) for m in measurements)
    # GitHub does not render titles as Markdown, but keep to safe characters anyway.
    model = re.sub(r"[^\w .()+/-]", "", str(device.get("model", "?")))[:64] or "?"
    title = f"Device report: {model} ({record['id']})"
    rows = [
        ("Model", model),
        ("Connection", device.get("connection", "?")),
        ("Report mode", report.get("mode", "?")),
        ("System", f"{system.get('os', '?')} · tartim {system.get('tartim', '?')}"),
        ("Measurement attempts", len(measurements)),
        ("Recognized records", recognized),
        ("Display comparison", f"{matched}/{len(checks)} matched" if checks else "none"),
        ("Bluetooth notifications", notes),
    ]
    table = "\n".join(f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows)
    body = [f"Opened automatically by the report server. Report id: `{record['id']}`\n",
            "| | |\n|---|---|", table, ""]
    if record.get("note"):
        fence = _fence(record["note"])
        body += ["**Note from the user:**", f"{fence}text", record["note"], fence, ""]
    data = json.dumps(report, ensure_ascii=False, indent=1)
    if len(data) > ISSUE_JSON_LIMIT:
        body.append(f"The report has {len(data)} characters; the full report is stored on the "
                    f"server (`sent/{record['id']}.json`). First part:")
        data = data[:ISSUE_JSON_LIMIT] + "\n…"
    fence = _fence(data)
    body += ["<details><summary>Report (JSON)</summary>\n", f"{fence}json", data, fence,
             "</details>"]
    return title, "\n".join(body)


class GitHub:
    def __init__(self, repo: str, token: str, api: str = "https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api

    def create_issue(self, title: str, body: str) -> str:
        request = urllib.request.Request(
            f"{self.api}/repos/{self.repo}/issues",
            data=json.dumps({"title": title, "body": body}).encode(),
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "tartim-report-server"},
            method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["html_url"]


def read_token() -> str | None:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    path = Path(directory) / "github-token" if directory else \
        Path(os.environ.get("TARTIM_GITHUB_TOKEN_FILE", "/nonexistent"))
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def forward_pending(store: Store, github: GitHub | None) -> int:
    """Forwards pending reports to GitHub; returns how many were forwarded."""
    if github is None:
        return 0
    sent = 0
    for path in store.pending():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            url = github.create_issue(*issue_for(record))
        except urllib.error.HTTPError as exc:
            log.warning("Could not forward to GitHub (%s): HTTP %s", path.name, exc.code)
            if exc.code in (401, 403, 404):
                break  # token or repository problem: try again next round
            continue
        except (OSError, ValueError) as exc:
            log.warning("Could not forward to GitHub (%s): %s", path.name, exc)
            break
        store.mark_sent(path, url)
        log.info("Report forwarded: %s", path.stem)
        sent += 1
    return sent


def _matches(path: str, candidates: tuple[str, ...]) -> bool:
    path = path.split("?", 1)[0].rstrip("/")
    return any(path.endswith(c) for c in candidates)


def make_handler(store: Store, limiter: RateLimiter, on_saved):
    class Handler(BaseHTTPRequestHandler):
        server_version = "tartim-report"
        sys_version = ""

        def _reply(self, status: HTTPStatus, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _not_found(self) -> None:
            self._reply(HTTPStatus.NOT_FOUND, {"ok": False, "code": "not-found",
                                               "error": "Not found."})

        def log_message(self, fmt, *args):  # neither content nor IP addresses are logged
            log.debug("%s %s", self.command, self.path)

        def do_GET(self):
            if _matches(self.path, HEALTH_PATHS):
                self._reply(HTTPStatus.OK, {"ok": True})
            else:
                self._not_found()

        def do_POST(self):
            if not _matches(self.path, REPORT_PATHS):
                return self._not_found()
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_BODY:
                    raise Rejected(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too-large",
                                   "The report is too large.")
                # Behind nginx: the client address is in the X-Real-IP header.
                ip = self.headers.get("X-Real-IP") or self.client_address[0]
                if not limiter.allow(ip):
                    raise Rejected(HTTPStatus.TOO_MANY_REQUESTS, "rate-limited",
                                   "Too many reports; please try again later.")
                try:
                    payload = json.loads(self.rfile.read(length))
                except ValueError:
                    raise Rejected(HTTPStatus.BAD_REQUEST, "unreadable",
                                   "The report could not be read.") from None
                record = validate(payload)
                if store.full():
                    raise Rejected(HTTPStatus.SERVICE_UNAVAILABLE, "server-full",
                                   "The server is not accepting reports right now.")
                rid = store.save(record)
            except Rejected as exc:
                return self._reply(exc.status, {"ok": False, "code": exc.code,
                                                "error": exc.message})
            log.info("Report received: %s", rid)
            on_saved()
            self._reply(HTTPStatus.CREATED, {"ok": True, "id": rid})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tartım device report server")
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--data", default=os.environ.get("STATE_DIRECTORY", "./report-data"))
    parser.add_argument("--repo", default=os.environ.get("TARTIM_GITHUB_REPO",
                                                         "muratGursel/tartim-raporlar"))
    parser.add_argument("--interval", type=float, default=60,
                        help="How often to forward to GitHub, seconds")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    store = Store(Path(args.data))
    token = read_token()
    github = GitHub(args.repo, token) if token else None
    log.info("GitHub forwarding: %s", f"on ({args.repo})" if github else
             "off (no token; reports are only stored on disk)")
    wake = threading.Event()

    def forwarder():
        while True:
            forward_pending(store, github)
            wake.wait(args.interval)
            wake.clear()

    threading.Thread(target=forwarder, daemon=True).start()
    server = ThreadingHTTPServer((args.address, args.port),
                                 make_handler(store, RateLimiter(), wake.set))
    log.info("Listening on %s:%s", args.address, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
