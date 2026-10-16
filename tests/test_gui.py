"""Arayüz testi. Bir ekran (X11, Wayland ya da GTK Broadway) gerektirir;
yoksa atlanır. Ekransız çalıştırmak için:

    broadwayd :5 & GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 python3 -m unittest tests.test_gui
"""

import tempfile
import unittest
from pathlib import Path

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    HAVE_DISPLAY = Gtk.init_check()[0] if hasattr(Gtk, "init_check") else False
except (ImportError, ValueError):
    HAVE_DISPLAY = False

from .test_protocol import SAMPLE

_APP = None


def shared_app():
    """Tüm testler için tek GTK uygulaması (aynı oturumda ikincisi kaydedilemez)."""
    global _APP
    if _APP is None:
        from gi.repository import Gio

        _APP = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
        _APP.register(None)
    return _APP


@unittest.skipUnless(HAVE_DISPLAY, "GTK 3 ve bir ekran gerekli")
class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = shared_app()

    def setUp(self):
        from tartim.gui import MainWindow
        from tartim.storage import Store

        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.window = MainWindow(self.app, self.store, port="/dev/ttyUSB9")

    def tearDown(self):
        self.window.destroy()
        self.store.close()
        self.tmp.cleanup()

    def test_record_is_saved_and_shown(self):
        self.assertEqual(self.window.selected_port(), "/dev/ttyUSB9")
        self.assertEqual(len(self.window.history_model), 0)
        self.window.on_record(SAMPLE)
        self.assertEqual(len(self.window.history_model), 1)
        self.assertIn("62.4 kg", self.window.headline.get_label())
        details = {row[0]: row[1] for row in self.window.detail_model}
        self.assertEqual(details["Cinsiyet"], "Kadın")
        self.assertEqual(details["Yağ oranı"], "27.1 %")
        self.assertNotIn("Durum", details)

    def test_unrecognized_record(self):
        self.window.on_record("garip,veri")
        self.assertIn("Tanınmayan kayıt", self.window.headline.get_label())

    def test_import_and_export(self):
        sd = Path(self.tmp.name) / "20261016.CSV"
        sd.write_text(SAMPLE + "\r\n", encoding="ascii")
        self.assertEqual(self.store.import_files([sd]), (1, 0, 0))
        self.window.refresh_history()
        self.assertEqual(len(self.window.history_model), 1)
        out = Path(self.tmp.name) / "o.csv"
        self.assertEqual(self.store.export_csv(out), 1)


@unittest.skipUnless(HAVE_DISPLAY, "GTK 3 ve bir ekran gerekli")
class ReportDoneTests(unittest.TestCase):
    def setUp(self):
        from tartim.gui import MainWindow, ReportDialog
        from tartim.storage import Store

        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.app = shared_app()
        self.window = MainWindow(self.app, self.store)
        self.dialog = ReportDialog(self.window, "/dev/ttyUSB0", 9600)

    def tearDown(self):
        self.dialog.destroy()
        self.window.destroy()
        self.store.close()
        self.tmp.cleanup()

    def test_send_choices(self):
        d = self.dialog
        self.assertEqual(list(d.send_choices), ["server", "github", "later"])
        self.assertEqual(d.action.get_label(), "Gönder")
        self.assertFalse(d.action.get_sensitive())  # onay olmadan gönderilemez
        d.consent.set_active(True)
        self.assertTrue(d.action.get_sensitive())
        d.send_choices["github"].set_active(True)
        self.assertEqual(d.action.get_label(), "GitHub formunu aç")
        d.send_choices["later"].set_active(True)
        self.assertEqual(d.action.get_label(), "Tamam")

    def test_successful_send_locks_choices(self):
        d = self.dialog
        d._sent("20261016-abc", None)
        self.assertIn("20261016-abc", d.send_status.get_label())
        self.assertFalse(d.send_choices["server"].get_sensitive())
        d._sent(None, "Sunucuya ulaşılamadı")
        self.assertIn("Gönderilemedi", d.send_status.get_label())


if __name__ == "__main__":
    unittest.main()
