import contextlib
import io
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from tartim import i18n, printout
from tartim.cli import main
from tartim.clients import Client, age_on, normalize_number, parse_date
from tartim.protocol import parse
from tartim.storage import Store

from .test_printout import VISITS, record

# A SYNTHETIC client, as an analyzer without input fields (e.g. a Bluetooth scale) sends it.
BARE = '{MO,"BLE",Wk,82.4,FW,24.0}'


class ClientTests(unittest.TestCase):
    def test_numbers_and_dates(self):
        self.assertEqual(normalize_number("0000000000000042"), "42")
        self.assertEqual(normalize_number(" A-7 "), "A-7")
        self.assertEqual(parse_date("01.05.1977"), date(1977, 5, 1))
        self.assertEqual(parse_date("1977-05-01"), date(1977, 5, 1))
        with self.assertRaises(ValueError):
            parse_date("1 May")

    def test_age_on_measurement_day(self):
        self.assertEqual(age_on(date(1980, 7, 6), date(2026, 7, 5)), 45)
        self.assertEqual(age_on(date(1980, 7, 6), date(2026, 7, 6)), 46)

    def test_validation(self):
        with self.assertRaises(ValueError):
            Client("", "Ad")
        with self.assertRaises(ValueError):
            Client("1", "  ")
        with self.assertRaises(ValueError):
            Client("1", "Ad", gender=3)
        with self.assertRaises(ValueError):
            Client("1", "Ad", height=20)

    def test_fill_keeps_device_values(self):
        c = Client("5", "Ad", gender=2, birth_date=date(1990, 1, 1), height=165)
        values, filled = c.fill({"GE": 1, "Wk": 60.0}, datetime(2026, 3, 1))
        self.assertEqual(values["GE"], 1)  # the device's value wins
        self.assertEqual((values["AG"], values["Hm"]), (36, 165))
        self.assertEqual(filled, ["AG", "Hm", "Bt"])


class StoreClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        for visit in VISITS:
            self.store.add(parse(record(*visit)), source="test")
        self.store.add(parse(BARE), source="test")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_save_find_and_rename(self):
        self.store.save_client(Client("0042", "Örnek Kişi", gender=1))
        self.assertEqual(self.store.client("42").name, "Örnek Kişi")
        self.assertEqual([c.number for c in self.store.clients("örnek")], ["42"])
        self.store.save_client(self.store.client("42").with_changes(number="43"),
                               replace_number="42")
        self.assertIsNone(self.store.client("42"))
        self.assertEqual(len(self.store.list(subject_id="43")), 3)  # measurements follow

    def test_rename_to_used_number_fails(self):
        self.store.save_client(Client("1", "A"))
        self.store.save_client(Client("2", "B"))
        with self.assertRaises(ValueError):
            self.store.save_client(Client("2", "A"), replace_number="1")

    def test_assign_and_delete(self):
        self.store.save_client(Client("9", "Ad"))
        self.store.assign(4, "9")
        self.assertEqual([r["id"] for r in self.store.list(subject_id="9")], [4])
        self.assertEqual(self.store.delete_client("9", with_measurements=True), 1)
        self.assertIsNone(self.store.get(4))
        with self.assertRaises(LookupError):
            self.store.assign(99, "9")

    def test_sheet_uses_the_client_record(self):
        self.store.save_client(Client("9", "Kayıtlı Kişi", gender=2,
                                      birth_date=date(1990, 1, 1), height=170))
        self.store.assign(4, "9")
        current, history = printout.entries(self.store, record_id=4)
        self.assertEqual(current.name, "Kayıtlı Kişi")
        self.assertEqual((current.get("GE"), current.get("Hm")), (2, 170))
        self.assertIsNotNone(current.get("AG"))
        self.assertEqual(current.filled, ("GE", "AG", "Hm", "Bt"))
        self.assertTrue(printout.default_name(current).startswith("result-9-"))

    def test_unregistered_client_keeps_number(self):
        current, _history = printout.entries(self.store, record_id=3)
        self.assertEqual(current.name, "Client 42")
        self.assertEqual(current.filled, ())


class ClientCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "t.db")
        with Store(self.db) as store:
            store.add(parse(BARE), source="test")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            main(["--database", self.db, *argv])
        return out.getvalue()

    def test_add_edit_assign_delete(self):
        self.run_cli("client", "add", "7", "--name", "Test Kişi", "--gender", "female",
                     "--birth", "01.05.1980", "--height", "165")
        self.run_cli("client", "edit", "7", "--note", "deneme")
        self.assertIn("deneme", self.run_cli("client", "list"))
        self.assertIn("1", self.run_cli("assign", "--record", "1", "--client", "7"))
        self.assertIn("Test Kişi", self.run_cli("list"))
        self.run_cli("assign", "--record", "1", "--none")
        with Store(self.db) as store:
            self.assertIsNone(store.get(1)["subject_id"])
        self.run_cli("client", "delete", "7")
        self.assertIn("No client", self.run_cli("client", "list"))

    def test_turkish_names(self):
        i18n.setup("tr")
        try:
            said = self.run_cli("danisan", "ekle", "8", "--ad", "Ad Soyad", "--cinsiyet", "erkek",
                                "--boy", "180", "--vucut-tipi", "atletik")
            said += self.run_cli("ata", "--kayit", "1", "--danisan", "8")
        finally:
            i18n.setup("en")
        self.assertIn("Danışan kaydedildi", said)
        with Store(self.db) as store:
            self.assertEqual(store.client("8").body_type, 2)

    def test_errors(self):
        with self.assertRaises(SystemExit):
            self.run_cli("assign", "--record", "1", "--client", "404")
        with self.assertRaises(SystemExit):
            self.run_cli("client", "edit", "404", "--name", "X")
        self.run_cli("client", "add", "1", "--name", "A")
        with self.assertRaises(SystemExit):
            self.run_cli("client", "add", "1", "--name", "B")


if __name__ == "__main__":
    unittest.main()
