"""Interface tests. They need a display (X11, Wayland or GTK Broadway) and are
skipped without one. To run them headless:

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
    """One GTK application for all tests (a second one cannot be registered)."""
    global _APP
    if _APP is None:
        from gi.repository import Gio

        _APP = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
        _APP.register(None)
    return _APP


@unittest.skipUnless(HAVE_DISPLAY, "GTK 3 and a display are required")
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
        self.assertEqual(details["Gender"], "Female")
        self.assertEqual(details["Body fat"], "27.1 %")
        self.assertNotIn("Status", details)

    def test_turkish_interface(self):
        from tartim import i18n
        from tartim.gui import MainWindow

        i18n.setup("tr")
        try:
            window = MainWindow(self.app, self.store)
            window.on_record(SAMPLE)
            details = {row[0]: row[1] for row in window.detail_model}
            self.assertEqual(details["Cinsiyet"], "Kadın")
            self.assertEqual(details["Yaş"], "34 yıl")
            self.assertEqual(window.connect_button.get_label(), "Bağlan")
            window.destroy()
        finally:
            i18n.setup("en")

    def test_unrecognized_record(self):
        self.window.on_record("garip,veri")
        self.assertIn("Unrecognized record", self.window.headline.get_label())

    def test_import_and_export(self):
        sd = Path(self.tmp.name) / "20261016.CSV"
        sd.write_text(SAMPLE + "\r\n", encoding="ascii")
        self.assertEqual(self.store.import_files([sd]), (1, 0, 0))
        self.window.refresh_history()
        self.assertEqual(len(self.window.history_model), 1)
        out = Path(self.tmp.name) / "o.csv"
        self.assertEqual(self.store.export_csv(out), 1)

    def test_clients(self):
        from tartim.clients import Client
        from tartim.gui import ClientForm, ClientsDialog

        self.window.on_record(SAMPLE)
        self.store.save_client(Client("42", "Örnek Kişi", gender=2, height=165))
        self.window.refresh_history()
        self.assertEqual(self.window.history_model[0][4], "Örnek Kişi")
        self.window.show_measurement(self.store.measurements()[0])
        self.assertIn("Örnek Kişi", self.window.headline.get_label())

        dialog = ClientsDialog(self.window)
        self.assertEqual([row[1] for row in dialog.model], ["Örnek Kişi"])
        dialog.search.set_text("yok")
        dialog.refresh()
        self.assertEqual(len(dialog.model), 0)
        dialog.destroy()

        form = ClientForm(self.window, self.store.client("42"))
        form.birth.set_text("01.05.1980")
        form.height.set_text("165,5")
        client = form.client()
        self.assertEqual((client.height, client.birth_date.year, client.gender), (165.5, 1980, 2))
        form.height.set_text("abc")
        with self.assertRaises(ValueError):
            form.client()
        form.destroy()


@unittest.skipUnless(HAVE_DISPLAY, "GTK 3 and a display are required")
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
        self.assertEqual(d.action.get_label(), "Send")
        self.assertFalse(d.action.get_sensitive())  # cannot be sent without consent
        d.consent.set_active(True)
        self.assertTrue(d.action.get_sensitive())
        d.send_choices["github"].set_active(True)
        self.assertEqual(d.action.get_label(), "Open the GitHub form")
        d.send_choices["later"].set_active(True)
        self.assertEqual(d.action.get_label(), "OK")

    def test_successful_send_locks_choices(self):
        d = self.dialog
        d._sent("20261016-abc", None)
        self.assertIn("20261016-abc", d.send_status.get_label())
        self.assertFalse(d.send_choices["server"].get_sensitive())
        d._sent(None, "Server unreachable")
        self.assertIn("Could not send", d.send_status.get_label())


if __name__ == "__main__":
    unittest.main()
