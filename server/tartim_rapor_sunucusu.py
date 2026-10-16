"""Tartım cihaz raporu sunucusu.

Uygulamadan gelen cihaz raporlarını alır, denetler, diske kaydeder ve GitHub'daki
özel bir depoda kayıt (issue) olarak açar. Yalnızca Python standart kütüphanesi
kullanılır.

GitHub erişim anahtarı kodda ya da depoda bulunmaz. systemd ``LoadCredential``
ile verilir (``$CREDENTIALS_DIRECTORY/github-token``); bkz. server/KURULUM.md.
Anahtar yoksa raporlar yalnızca diske kaydedilir ve anahtar eklendiğinde
sırayla iletilir.

    python3 tartim_rapor_sunucusu.py --port 8095 --veri /var/lib/tartim-rapor
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
ISSUE_JSON_LIMIT = 60000  # GitHub issue gövdesi en fazla 65536 karakter
PER_IP_HOURLY = 5
GLOBAL_DAILY = 200
MAX_PENDING = 500  # iletilmeyi bekleyen rapor sınırı: diski doldurma saldırısına karşı

log = logging.getLogger("tartim-rapor")


class Rejected(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def validate(payload: object) -> dict:
    """Gelen isteği denetler; geçerliyse saklanacak kaydı döndürür."""
    if not isinstance(payload, dict):
        raise Rejected(HTTPStatus.BAD_REQUEST, "Geçersiz istek.")
    if payload.get("consent") is not True:
        raise Rejected(HTTPStatus.BAD_REQUEST,
                       "Ölçümün gerçek bir danışana ait olmadığını onaylamanız gerekir.")
    report = payload.get("report")
    if not isinstance(report, dict) or report.get("schema") != 1:
        raise Rejected(HTTPStatus.BAD_REQUEST, "Rapor biçimi tanınmadı.")
    device = report.get("device")
    if not isinstance(device, dict) or not isinstance(device.get("model"), str) \
            or not 0 < len(device["model"].strip()) <= 64:
        raise Rejected(HTTPStatus.BAD_REQUEST, "Cihaz modeli eksik.")
    measurements = report.get("measurements")
    if not isinstance(measurements, list) or len(measurements) > MAX_MEASUREMENTS:
        raise Rejected(HTTPStatus.BAD_REQUEST, "Ölçüm listesi geçersiz.")
    note = payload.get("note") or ""
    if not isinstance(note, str):
        raise Rejected(HTTPStatus.BAD_REQUEST, "Not metin olmalı.")
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
    """Raporlar: ``gelen/`` (iletilecek) ve ``iletildi/`` klasörlerinde, 0600 izinle."""

    def __init__(self, root: Path):
        self.incoming = root / "gelen"
        self.sent = root / "iletildi"
        for d in (self.incoming, self.sent):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)

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
        return sum(1 for _ in self.incoming.glob("*.json")) >= MAX_PENDING

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
    """İçerikteki en uzun ` dizisinden uzun bir kod bloğu çiti (Markdown kaçışı)."""
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
    # Başlık GitHub'da Markdown olarak işlenmez ama yine de yalnızca güvenli karakterler.
    model = re.sub(r"[^\w .()+/-]", "", str(device.get("model", "?")))[:64] or "?"
    title = f"Cihaz raporu: {model} ({record['id']})"
    rows = [
        ("Model", model),
        ("Bağlantı", device.get("connection", "?")),
        ("Rapor kipi", report.get("mode", "?")),
        ("Sistem", f"{system.get('os', '?')} · tartim {system.get('tartim', '?')}"),
        ("Ölçüm denemesi", len(measurements)),
        ("Tanınan kayıt", recognized),
        ("Ekran karşılaştırması", f"{matched}/{len(checks)} eşleşti" if checks else "yok"),
        ("Bluetooth bildirimi", notes),
    ]
    table = "\n".join(f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows)
    body = [f"Rapor sunucusundan otomatik açıldı. Rapor no: `{record['id']}`\n",
            "| | |\n|---|---|", table, ""]
    if record.get("note"):
        fence = _fence(record["note"])
        body += ["**Kullanıcının notu:**", f"{fence}text", record["note"], fence, ""]
    data = json.dumps(report, ensure_ascii=False, indent=1)
    if len(data) > ISSUE_JSON_LIMIT:
        body.append(f"Rapor {len(data)} karakter; tamamı sunucuda saklanıyor "
                    f"(`iletildi/{record['id']}.json`). İlk kısım:")
        data = data[:ISSUE_JSON_LIMIT] + "\n…"
    fence = _fence(data)
    body += ["<details><summary>Rapor (JSON)</summary>\n", f"{fence}json", data, fence,
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
                     "User-Agent": "tartim-rapor-sunucusu"},
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
    """Bekleyen raporları GitHub'a iletir; iletilen sayısını döndürür."""
    if github is None:
        return 0
    sent = 0
    for path in store.pending():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            url = github.create_issue(*issue_for(record))
        except urllib.error.HTTPError as exc:
            log.warning("GitHub'a iletilemedi (%s): HTTP %s", path.name, exc.code)
            if exc.code in (401, 403, 404):
                break  # anahtar ya da depo sorunu: sonraki turda yeniden dene
            continue
        except (OSError, ValueError) as exc:
            log.warning("GitHub'a iletilemedi (%s): %s", path.name, exc)
            break
        store.mark_sent(path, url)
        log.info("Rapor iletildi: %s", path.stem)
        sent += 1
    return sent


def make_handler(store: Store, limiter: RateLimiter, on_saved):
    class Handler(BaseHTTPRequestHandler):
        server_version = "tartim-rapor"
        sys_version = ""

        def _reply(self, status: HTTPStatus, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # içerik ve IP günlüğe yazılmaz
            log.debug("%s %s", self.command, self.path)

        def do_GET(self):
            if self.path.rstrip("/").endswith("/tartim/saglik"):
                self._reply(HTTPStatus.OK, {"ok": True})
            else:
                self._reply(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Bulunamadı."})

        def do_POST(self):
            if not self.path.rstrip("/").endswith("/tartim/rapor"):
                return self._reply(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Bulunamadı."})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= MAX_BODY:
                    raise Rejected(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Rapor çok büyük.")
                # nginx arkasında: istemci adresi X-Real-IP başlığında.
                ip = self.headers.get("X-Real-IP") or self.client_address[0]
                if not limiter.allow(ip):
                    raise Rejected(HTTPStatus.TOO_MANY_REQUESTS,
                                   "Çok fazla rapor gönderildi, lütfen daha sonra deneyin.")
                try:
                    payload = json.loads(self.rfile.read(length))
                except ValueError:
                    raise Rejected(HTTPStatus.BAD_REQUEST, "Rapor okunamadı.") from None
                record = validate(payload)
                if store.full():
                    raise Rejected(HTTPStatus.SERVICE_UNAVAILABLE,
                                   "Sunucu şu an rapor kabul etmiyor, lütfen daha sonra deneyin.")
                rid = store.save(record)
            except Rejected as exc:
                return self._reply(exc.status, {"ok": False, "error": exc.message})
            log.info("Rapor alındı: %s", rid)
            on_saved()
            self._reply(HTTPStatus.CREATED, {"ok": True, "id": rid})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tartım cihaz raporu sunucusu")
    parser.add_argument("--adres", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--veri", default=os.environ.get("STATE_DIRECTORY", "./rapor-verisi"))
    parser.add_argument("--depo", default=os.environ.get("TARTIM_GITHUB_REPO",
                                                         "muratGursel/tartim-raporlar"))
    parser.add_argument("--aralik", type=float, default=60, help="GitHub'a iletme aralığı, sn")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    store = Store(Path(args.veri))
    token = read_token()
    github = GitHub(args.depo, token) if token else None
    log.info("GitHub iletimi: %s", f"açık ({args.depo})" if github else
             "kapalı (anahtar yok; raporlar yalnızca diske kaydediliyor)")
    wake = threading.Event()

    def forwarder():
        while True:
            forward_pending(store, github)
            wake.wait(args.aralik)
            wake.clear()

    threading.Thread(target=forwarder, daemon=True).start()
    server = ThreadingHTTPServer((args.adres, args.port),
                                 make_handler(store, RateLimiter(), wake.set))
    log.info("Dinleniyor: %s:%s", args.adres, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
