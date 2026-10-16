import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from tartim.cli import main
from tartim.protocol import parse
from tartim.storage import Store

from .test_protocol import SAMPLE


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "alt" / "tartim.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_and_deduplicate(self):
        with Store(self.db) as store:
            self.assertIsNotNone(store.add(parse(SAMPLE), source="test"))
            self.assertIsNone(store.add(parse(SAMPLE), source="test"))
            rows = store.list()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["subject_id"], "42")
            self.assertEqual(rows[0]["measured_at"], "2026-10-16T09:30:00")
            self.assertEqual(store.measurements(subject_id="42")[0].weight, 62.4)
            self.assertEqual(store.list(subject_id="7"), [])

    @unittest.skipIf(os.name != "posix", "dosya izinleri yalnızca POSIX'te")
    def test_database_is_private(self):
        Store(self.db).close()
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_import_and_export_cli(self):
        sd_file = Path(self.tmp.name) / "20261016.CSV"
        other = SAMPLE.replace('"0000000000000042"', '"0000000000000043"')
        sd_file.write_text(f"{SAMPLE}\r\n{other}\r\nbozuk,satir\r\n", encoding="ascii")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--veritabani", str(self.db), "ice-aktar", str(sd_file)])
            main(["--veritabani", str(self.db), "ice-aktar", str(sd_file)])
        self.assertIn("2 ölçüm eklendi, 0 tekrar atlandı, 1 kayıt tanınmadı", out.getvalue())
        self.assertIn("0 ölçüm eklendi, 2 tekrar atlandı", out.getvalue())

        csv_path = Path(self.tmp.name) / "cikti.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--veritabani", str(self.db), "disa-aktar", "--cikti", str(csv_path)])
        lines = csv_path.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("Kilo", lines[0])
        self.assertIn("62.4", lines[1])


if __name__ == "__main__":
    unittest.main()
