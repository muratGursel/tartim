"""Storing measurements in a local SQLite database.

Body measurements are health data (special category personal data under KVKK
and GDPR). The database file is created readable by its owner only (0600).
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .clients import Client, normalize_number
from .fields import describe
from .i18n import _
from .protocol import Framer, Measurement, parse

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
CREATE TABLE IF NOT EXISTS clients (
    number      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    gender      INTEGER,
    birth_date  TEXT,
    height      REAL,
    body_type   INTEGER NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


TURKISH_I = str.maketrans("İIı", "iii")


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
        """Adds a measurement. Returns None if the same raw record was added before."""
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
            args.append(normalize_number(subject_id))
        sql += " ORDER BY id DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return self._db.execute(sql, args).fetchall()

    # --- Clients ---------------------------------------------------------------

    def save_client(self, client: Client, replace_number: str | None = None) -> None:
        """Adds or updates a client. ``replace_number`` renames an existing client;
        its measurements follow the new number."""
        now = datetime.now().isoformat(timespec="seconds")
        row = client.to_row()
        with self._db:
            if replace_number is not None and replace_number != client.number:
                if self.client(client.number):
                    raise ValueError(_("Client number {number} is already used.").format(
                        number=client.number))
                self._db.execute("UPDATE clients SET number = ? WHERE number = ?",
                                 (client.number, replace_number))
                self._db.execute("UPDATE measurements SET subject_id = ? WHERE subject_id = ?",
                                 (client.number, replace_number))
            self._db.execute(
                "INSERT INTO clients (number, name, gender, birth_date, height, body_type, note,"
                " created_at, updated_at) VALUES (:number, :name, :gender, :birth_date, :height,"
                " :body_type, :note, :now, :now) ON CONFLICT(number) DO UPDATE SET"
                " name = excluded.name, gender = excluded.gender,"
                " birth_date = excluded.birth_date, height = excluded.height,"
                " body_type = excluded.body_type, note = excluded.note,"
                " updated_at = excluded.updated_at", {**row, "now": now})

    def client(self, number: str | None) -> Client | None:
        if number is None:
            return None
        row = self._db.execute("SELECT * FROM clients WHERE number = ?",
                               (normalize_number(number),)).fetchone()
        return Client.from_row(row) if row else None

    def clients(self, search: str = "") -> list[Client]:
        # SQLite's LIKE only folds ASCII letters; Turkish names are matched here.
        def fold(text: str) -> str:
            return text.translate(TURKISH_I).casefold()

        needle = fold(search.strip())
        rows = self._db.execute("SELECT * FROM clients").fetchall()
        found = [Client.from_row(r) for r in rows
                 if needle in fold(r["name"]) or needle in fold(r["number"])]
        return sorted(found, key=lambda c: fold(c.name))

    def delete_client(self, number: str, with_measurements: bool = False) -> int:
        """Deletes a client record; with ``with_measurements`` their measurements too.
        Returns how many measurements were deleted."""
        number = normalize_number(number)
        with self._db:
            deleted = 0
            if with_measurements:
                deleted = self._db.execute("DELETE FROM measurements WHERE subject_id = ?",
                                           (number,)).rowcount
            self._db.execute("DELETE FROM clients WHERE number = ?", (number,))
        return deleted

    def assign(self, record_id: int, number: str | None) -> None:
        """Links a measurement to a client number (None: unlink)."""
        with self._db:
            cur = self._db.execute("UPDATE measurements SET subject_id = ? WHERE id = ?",
                                   (normalize_number(number) if number else None, record_id))
        if not cur.rowcount:
            raise LookupError(_("No measurement with number {number}.").format(number=record_id))

    def get(self, record_id: int) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM measurements WHERE id = ?",
                                (record_id,)).fetchone()

    def measurements(self, **kwargs) -> list[Measurement]:
        return [parse(row["raw"]) for row in self.list(**kwargs)]

    def import_files(self, paths) -> tuple[int, int, int]:
        """Imports SD card or raw capture files.
        Returns (added, skipped as duplicates, unrecognized) counts."""
        added = skipped = unknown = 0
        for path in map(Path, paths):
            framer = Framer()
            for record in framer.feed(path.read_bytes()) + framer.flush():
                m = parse(record)
                if not m.recognized:
                    unknown += 1
                elif self.add(m, source=f"file:{path.name}"):
                    added += 1
                else:
                    skipped += 1
        return added, skipped, unknown

    def export_csv(self, path, subject_id: str | None = None) -> int:
        """CSV that Excel and LibreOffice open directly (; separated, with BOM)."""
        rows = list(reversed(self.list(subject_id=subject_id)))
        codes: list[str] = []
        for r in rows:
            for code in json.loads(r["values_json"]):
                if code not in codes and code != "CS":
                    codes.append(code)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow([_("No"), _("Received at")] + [describe(c).name for c in codes])
            for r in rows:
                values = json.loads(r["values_json"])
                writer.writerow([r["id"], r["received_at"]] + [values.get(c, "") for c in codes])
        return len(rows)
