"""Parsing Tanita measurement records and splitting them out of a serial stream.

An example record (field order depends on the model)::

    {0,16,~0,1,~1,1,~2,1,MO,"MC-780",ID,"0000000000000001",...,Wk,70.4,FW,21.3,...,CS,3A}

Leading format headers such as ``0,16,~0,1,...`` are skipped; after the first
key the items are read as ``key, value`` pairs. Records that cannot be parsed
are kept with their raw text so that samples of new models can be collected.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime

from .fields import describe

_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]$")
_DATE_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S",
                 "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M")


@dataclass
class Measurement:
    raw: str
    values: dict[str, object] = field(default_factory=dict)

    @property
    def recognized(self) -> bool:
        return bool(self.values)

    @property
    def model(self) -> str | None:
        return self.values.get("MO")  # type: ignore[return-value]

    @property
    def subject_id(self) -> str | None:
        value = self.values.get("ID")
        if value is None:
            return None
        return str(value).lstrip("0") or "0"

    @property
    def weight(self) -> float | None:
        return self.values.get("Wk")  # type: ignore[return-value]

    def measured_at(self) -> datetime | None:
        """Measurement time reported by the device. The date format depends on its settings."""
        date = self.values.get("Da") or self.values.get("DT")
        time = self.values.get("TI") or self.values.get("Ti")
        if not date:
            return None
        text = f"{date} {time or '00:00'}"
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None


def _convert(code: str, text: str) -> object:
    kind = describe(code).kind
    try:
        if kind == "int":
            return int(float(text))
        if kind == "float":
            return float(text)
    except ValueError:
        pass
    return text


def parse(record: str) -> Measurement:
    """Parses one record. For an unknown format ``values`` is empty."""
    text = record.strip().lstrip("{").rstrip("}").strip()
    text = text.replace("\r", "").replace("\n", "")
    try:
        tokens = [t.strip() for t in next(csv.reader([text]), [])]
    except csv.Error:
        return Measurement(raw=record)

    start = next((i for i, t in enumerate(tokens) if _KEY_RE.match(t)), None)
    values: dict[str, object] = {}
    if start is not None:
        pairs = tokens[start:]
        if len(pairs) % 2:
            # Incomplete (truncated) record.
            return Measurement(raw=record)
        for key, value in zip(pairs[0::2], pairs[1::2]):
            if not _KEY_RE.match(key):
                # The pair sequence broke: this record is not in a known format.
                return Measurement(raw=record)
            values[key] = _convert(key, value)
    # A few random items matching a key pattern do not make a measurement.
    if "Wk" not in values:
        values = {}
    return Measurement(raw=record, values=values)


class Framer:
    """Splits byte chunks from a serial port into complete records.

    Records end with CR/LF. A record that starts with ``{`` and is not yet
    closed with ``}`` is kept together even if it contains line breaks.
    """

    def __init__(self, encoding: str = "latin-1", max_len: int = 64 * 1024):
        self._buffer = ""
        self._encoding = encoding
        self._max_len = max_len

    def feed(self, chunk: bytes) -> list[str]:
        self._buffer += chunk.decode(self._encoding, errors="replace")
        records = []
        while True:
            index = self._next_end()
            if index is None:
                break
            record, self._buffer = self._buffer[:index], self._buffer[index:].lstrip("\r\n")
            record = record.strip("\r\n\x00 ")
            if record:
                records.append(record)
        if len(self._buffer) > self._max_len:
            # Noise or a wrong baud rate: do not let the buffer grow without bound.
            records.append(self._buffer)
            self._buffer = ""
        return records

    def flush(self) -> list[str]:
        rest, self._buffer = self._buffer.strip("\r\n\x00 "), ""
        return [rest] if rest else []

    def _next_end(self) -> int | None:
        buf = self._buffer.lstrip("\r\n")
        offset = len(self._buffer) - len(buf)
        if buf.startswith("{"):
            close = buf.find("}")
            return offset + close + 1 if close >= 0 else None
        newline = min((i for i in (buf.find("\r"), buf.find("\n")) if i >= 0), default=-1)
        return offset + newline if newline >= 0 else None
