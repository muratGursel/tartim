"""Translations.

Source strings in the code are English. Translations live in
``tartim/locale/<language>.po`` and are compiled to the gettext ``.mo`` format
in memory at startup, so no build step (and no ``msgfmt``) is needed.

The language follows the usual gettext variables (``LANGUAGE``, ``LC_ALL``,
``LC_MESSAGES``, ``LANG``); ``TARTIM_LANG`` overrides them (e.g. ``TARTIM_LANG=en``).

Usage::

    from .i18n import _, N_, ngettext
    print(_("Measurement received"))
    print(ngettext("{n} measurement", "{n} measurements", n).format(n=n))
"""

from __future__ import annotations

import ast
import gettext
import io
import locale
import os
import struct
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent / "locale"
SOURCE_LANGUAGE = "en"

_catalog: gettext.NullTranslations = gettext.NullTranslations()
_language = SOURCE_LANGUAGE


def parse_po(text: str) -> dict[str | tuple[str, str], str | list[str]]:
    """Minimal .po parser: msgid, msgid_plural, msgstr and msgstr[n].
    Returns {msgid: msgstr} and {(singular, plural): [forms]} entries."""
    entries: dict = {}
    current: dict[str, object] = {}
    field = None

    def flush():
        if "msgid" in current and current.get("fuzzy") is not True:
            if "msgid_plural" in current:
                forms = [current[k] for k in sorted(k for k in current if k.startswith("msgstr["))]
                if any(forms):
                    entries[(current["msgid"], current["msgid_plural"])] = forms
            elif current.get("msgstr") or current["msgid"] == "":
                entries[current["msgid"]] = current.get("msgstr", "")
        current.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            field = None
            continue
        if line.startswith("#,") and "fuzzy" in line:
            current["fuzzy"] = True
            continue
        if line.startswith("#"):
            continue
        if line.startswith('"'):
            if field:
                current[field] = current.get(field, "") + ast.literal_eval(line)
            continue
        keyword, _sep, rest = line.partition(" ")
        if keyword == "msgid" and "msgid" in current:
            flush()
        field = keyword
        current[field] = ast.literal_eval(rest)
    flush()
    return entries


def compile_mo(entries: dict) -> bytes:
    """Builds a gettext .mo file (little-endian, no hash table)."""
    pairs = []
    for key, value in entries.items():
        if isinstance(key, tuple):
            msgid = "\0".join(key)
            msgstr = "\0".join(value)
        else:
            msgid, msgstr = key, value
        pairs.append((msgid.encode("utf-8"), msgstr.encode("utf-8")))
    pairs.sort()
    count = len(pairs)
    header = 7 * 4
    ids_table = header
    strs_table = ids_table + count * 8
    data_start = strs_table + count * 8
    ids_index, strs_index, blob = [], [], b""
    for msgid, _msgstr in pairs:
        ids_index.append((len(msgid), data_start + len(blob)))
        blob += msgid + b"\0"
    for _msgid, msgstr in pairs:
        strs_index.append((len(msgstr), data_start + len(blob)))
        blob += msgstr + b"\0"
    out = struct.pack("<7I", 0x950412DE, 0, count, ids_table, strs_table, 0, 0)
    out += b"".join(struct.pack("<2I", *item) for item in ids_index)
    out += b"".join(struct.pack("<2I", *item) for item in strs_index)
    return out + blob


def requested_languages() -> list[str]:
    forced = os.environ.get("TARTIM_LANG", "").strip()
    if forced:
        return [forced]
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "").strip()
        if value:
            return [part for part in value.split(":") if part]
    try:  # e.g. Windows: ('Turkish_Türkiye', '1254') or ('tr_TR', 'UTF-8')
        name = locale.getlocale()[0] or ""
    except ValueError:
        name = ""
    return ["tr"] if name.lower().startswith(("tr", "turkish")) else []


def _base(code: str) -> str:
    return code.split(".")[0].split("@")[0].split("_")[0].lower()


def setup(language: str | None = None) -> str:
    """Selects the language; returns the language actually used."""
    global _catalog, _language
    for code in [language] if language else requested_languages():
        base = _base(code)
        if base in (SOURCE_LANGUAGE, "c", "posix"):
            break
        po = LOCALE_DIR / f"{base}.po"
        if po.exists():
            mo = compile_mo(parse_po(po.read_text(encoding="utf-8")))
            _catalog = gettext.GNUTranslations(io.BytesIO(mo))
            _language = base
            return base
    _catalog = gettext.NullTranslations()
    _language = SOURCE_LANGUAGE
    return SOURCE_LANGUAGE


def current_language() -> str:
    return _language


def _(message: str) -> str:
    return _catalog.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _catalog.ngettext(singular, plural, n)


def N_(message: str) -> str:
    """Marks a string for translation without translating it yet (e.g. constants)."""
    return message


setup()
