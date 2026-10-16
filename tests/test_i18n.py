import ast
import gettext
import io
import re
import unittest
from pathlib import Path

from tartim import i18n

ROOT = Path(__file__).resolve().parent.parent

SAMPLE_PO = r'''
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgid "Weight"
msgstr "Kilo"

msgid "{n} measurement added"
msgid_plural "{n} measurements added"
msgstr[0] "{n} ölçüm eklendi"
msgstr[1] "{n} ölçüm eklendi"

#, fuzzy
msgid "Fuzzy"
msgstr "Bulanık"

msgid "Untranslated"
msgstr ""

msgid "Line \"one\"\n"
"two"
msgstr "Satır \"bir\"\n"
"iki"
'''


class CatalogTests(unittest.TestCase):
    def test_parse_and_compile(self):
        entries = i18n.parse_po(SAMPLE_PO)
        self.assertNotIn("Fuzzy", entries)
        self.assertNotIn("Untranslated", entries)
        t = gettext.GNUTranslations(io.BytesIO(i18n.compile_mo(entries)))
        self.assertEqual(t.gettext("Weight"), "Kilo")
        self.assertEqual(t.ngettext("{n} measurement added", "{n} measurements added", 3),
                         "{n} ölçüm eklendi")
        self.assertEqual(t.gettext("Fuzzy"), "Fuzzy")
        self.assertEqual(t.gettext('Line "one"\ntwo'), 'Satır "bir"\niki')

    def test_language_selection(self):
        try:
            self.assertEqual(i18n.setup("tr_TR.UTF-8"), "tr")
            self.assertEqual(i18n._("Weight"), "Kilo")
            self.assertEqual(i18n.setup("en_US"), "en")
            self.assertEqual(i18n._("Weight"), "Weight")
            self.assertEqual(i18n.setup("xx"), "en")  # unknown language falls back to English
        finally:
            i18n.setup("en")


def translatable_strings() -> dict[str, set[str]]:
    """Every literal passed to _(), N_() or ngettext() in the code, with its file."""
    found: dict[str, set[str]] = {}
    files = sorted((ROOT / "tartim").glob("*.py"))
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in ("_", "N_", "ngettext"):
                args = node.args[:2] if node.func.id == "ngettext" else node.args[:1]
                for arg in args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.setdefault(arg.value, set()).add(path.name)
    return found


class TurkishCatalogTests(unittest.TestCase):
    """Turkish is the main audience: every message must be translated."""

    def setUp(self):
        self.entries = i18n.parse_po((i18n.LOCALE_DIR / "tr.po").read_text(encoding="utf-8"))
        self.msgids = {k if isinstance(k, str) else k[0] for k in self.entries} | \
                      {k[1] for k in self.entries if isinstance(k, tuple)}

    def test_every_message_is_translated(self):
        missing = {s: sorted(f) for s, f in translatable_strings().items() if s not in self.msgids}
        self.assertEqual(missing, {}, "messages without a translation in tr.po")

    def test_placeholders_match(self):
        for key, value in self.entries.items():
            if not key:
                continue
            source = key if isinstance(key, str) else key[0]
            targets = [value] if isinstance(value, str) else value
            for target in targets:
                with self.subTest(msgid=source):
                    self.assertEqual(sorted(re.findall(r"\{\w*\}", source)),
                                     sorted(re.findall(r"\{\w*\}", target)))

    def test_no_stale_entries(self):
        used = set(translatable_strings())
        stale = sorted(m for m in self.msgids if m and m not in used)
        self.assertEqual(stale, [], "entries in tr.po that are no longer used")


if __name__ == "__main__":
    unittest.main()
