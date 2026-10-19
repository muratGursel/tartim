import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from tartim import i18n, printout, reference
from tartim.cli import main
from tartim.protocol import parse
from tartim.storage import Store

try:
    import reportlab  # noqa: F401

    printout._fonts()
    HAVE_PDF = True
except (ImportError, RuntimeError):
    HAVE_PDF = False

# SYNTHETIC visits of one client: (date, time, weight, body fat %)
VISITS = [("18/02/2026", "09:04", 115.2, 28.3), ("16/03/2026", "09:00", 109.6, 26.7),
          ("06/07/2026", "09:19", 95.1, 17.3)]


def record(date, time, weight, fat, client="0000000000000042", segmental=True):
    fat_mass = round(weight * fat / 100, 1)
    ffm = round(weight - fat_mass, 1)
    pairs = [("MO", '"BC-418"'), ("ID", f'"{client}"'), ("Da", f'"{date}"'), ("TI", f'"{time}"'),
             ("GE", "1"), ("AG", "49"), ("Hm", "191.0"), ("Wk", weight), ("FW", fat),
             ("fW", fat_mass), ("MW", ffm), ("mW", round(ffm * 0.95, 1)), ("wW", 57.6),
             ("wI", 33.2), ("wO", 24.4), ("IF", 8), ("rB", 2290), ("rA", 43)]
    if segmental:
        pairs += [("FR", 16.9), ("FL", 17.4), ("Fr", 15.6), ("Fl", 16.4), ("FT", 18.1),
                  ("mR", 4.3), ("mL", 4.4), ("mr", 12.2), ("ml", 11.8), ("mT", 42.3)]
    return "{" + ",".join(f"{k},{v}" for k, v in pairs) + "}"


def page_count(path: Path) -> int:
    """Page count from the PDF's page tree (ReportLab writes a single /Pages node)."""
    return max(int(n) for n in re.findall(rb"/Count (\d+)", path.read_bytes()))


class ReferenceTests(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(reference.BMI.classify(26.1), reference.HIGH)
        self.assertEqual(reference.BMI.classify(22), reference.NORMAL)
        self.assertEqual(reference.fat_range(1, 49), reference.Range(11, 22))
        self.assertEqual(reference.fat_range(2, 25), reference.Range(21, 33))
        self.assertIsNone(reference.fat_range(1, 15))  # no adult range for children
        self.assertIsNone(reference.fat_range(None, 40))
        self.assertEqual(reference.water_range(2, 30), reference.Range(45, 60))
        self.assertEqual(reference.VISCERAL.classify(13), reference.HIGH)

    def test_weight_range(self):
        lower, ideal, upper = reference.weight_range(191)
        self.assertAlmostEqual(ideal, 80.26, places=1)
        self.assertLess(lower, ideal)
        self.assertGreater(upper, ideal)

    def test_number_format_follows_language(self):
        try:
            i18n.setup("tr")
            self.assertEqual(printout.number(95.14), "95,1")
            self.assertEqual(printout.signed(-2.5), "-2,5")
        finally:
            i18n.setup("en")
        self.assertEqual(printout.number(95.14), "95.1")
        self.assertEqual(printout.signed(0.1), "+0.1")
        self.assertEqual(printout.number(None), "–")


class EntriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        for visit in VISITS:
            self.store.add(parse(record(*visit)), source="test")
        self.store.add(parse(record("01/07/2026", "10:00", 70.0, 25.0, client="77")),
                       source="test")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_history_of_the_same_client_only(self):
        current, history = printout.entries(self.store, record_id=3)
        self.assertEqual(current.record_id, 3)
        self.assertEqual([e.record_id for e in history], [1, 2, 3])  # oldest first
        current, history = printout.entries(self.store)  # latest: another client
        self.assertEqual(current.m.subject_id, "77")
        self.assertEqual(len(history), 1)

    def test_earlier_record_ignores_later_ones(self):
        _current, history = printout.entries(self.store, record_id=2)
        self.assertEqual([e.record_id for e in history], [1, 2])

    def test_missing_record(self):
        with self.assertRaises(LookupError):
            printout.entries(self.store, record_id=99)


@unittest.skipUnless(HAVE_PDF, "ReportLab and a TrueType font are required")
class PdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "t.db"
        with Store(self.db) as store:
            for visit in VISITS:
                store.add(parse(record(*visit)), source="test")
            store.add(parse(record("01/07/2026", "10:00", 70.0, 25.0, client="77",
                                   segmental=False)), source="test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_pages_with_history(self):
        out = Path(self.tmp.name) / "a.pdf"
        with Store(self.db) as store:
            current, history = printout.entries(store, record_id=3)
            printout.write_pdf(out, current, history, client_name="Örnek Danışan")
        self.assertTrue(out.read_bytes().startswith(b"%PDF"))
        self.assertEqual(page_count(out), 2)

    def test_single_page_without_history_or_segments(self):
        out = Path(self.tmp.name) / "b.pdf"
        with Store(self.db) as store:
            current, history = printout.entries(store)
            printout.write_pdf(out, current, history)
        self.assertEqual(page_count(out), 1)

    def test_turkish_sheet_and_cli(self):
        out = Path(self.tmp.name) / "c.pdf"
        i18n.setup("tr")
        try:
            with contextlib.redirect_stdout(io.StringIO()) as said:
                # The Turkish command name works too.
                main(["--database", str(self.db), "yazdir", "--kayit", "3", "--ad", "Test",
                      "--cikti", str(out)])
        finally:
            i18n.setup("en")
        self.assertIn("Sonuç çıktısı yazıldı", said.getvalue())
        self.assertEqual(page_count(out), 2)

    def test_default_name(self):
        with Store(self.db) as store:
            current, _history = printout.entries(store, record_id=3)
        self.assertEqual(printout.default_name(current), "result-42-20260706-0919.pdf")


if __name__ == "__main__":
    unittest.main()
