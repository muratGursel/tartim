"""Ölçümlerin yerel SQLite veritabanında saklanması.

Vücut ölçümleri KVKK kapsamında özel nitelikli kişisel veridir. Veritabanı
dosyası yalnızca sahibinin okuyabileceği izinlerle (0600) oluşturulur.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .protocol import Measurement, parse

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    measured_at TEXT,
    model       TEXT,
    subject_id  TEXT,
    weight      REAL,
    values_json TEXT NOT NULL,
    raw         TEXT NOT NULL,
    source      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS measurements_raw ON measurements(raw);
CREATE INDEX IF NOT EXISTS measurements_subject ON measurements(subject_id);
"""


def default_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "tartim" / "tartim.db"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def add(self, m: Measurement, source: str) -> int | None:
        """Ölçümü ekler. Aynı ham kayıt daha önce eklendiyse None döner."""
        measured = m.measured_at()
        with self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO measurements"
                " (received_at, measured_at, model, subject_id, weight, values_json, raw, source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    measured.isoformat(timespec="seconds") if measured else None,
                    m.model,
                    m.subject_id,
                    m.weight,
                    json.dumps(m.values, ensure_ascii=False),
                    m.raw,
                    source,
                ),
            )
        return cur.lastrowid if cur.rowcount else None

    def list(self, limit: int | None = None, subject_id: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM measurements"
        args: list[object] = []
        if subject_id is not None:
            sql += " WHERE subject_id = ?"
            args.append(subject_id)
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return self._db.execute(sql, args).fetchall()

    def measurements(self, **kwargs) -> list[Measurement]:
        return [parse(row["raw"]) for row in self.list(**kwargs)]
