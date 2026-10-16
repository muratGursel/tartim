import json
import random
import tempfile
import unittest
from pathlib import Path

from tartim.report import Wizard, analyze_record, compare, mask_subject_ids, run_wizard
from tartim.simulator import synthetic_record

from .test_protocol import SAMPLE


class FakePort:
    """Her read çağrısında sıradaki parçayı veren sahte seri port."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.in_waiting = 0
        self.closed = False

    def read(self, n):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def scripted(answers):
    answers = list(answers)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        if not answers:
            raise EOFError
        return answers.pop(0)
    return ask, asked


class HelperTests(unittest.TestCase):
    def test_mask_subject_ids_keeps_length(self):
        masked, count = mask_subject_ids(SAMPLE.encode())
        self.assertEqual(count, 1)
        self.assertEqual(len(masked), len(SAMPLE))
        self.assertIn(b'ID,"0000000000000000"', masked)

    def test_compare_finds_expected_and_unknown_formats(self):
        result = compare(analyze_record(SAMPLE), "Kilo", "Wk", 62.4)
        self.assertTrue(result["matches_expected"])
        self.assertIn("Wk", result["codes_with_value"])

        positional = analyze_record("1,2,62.4,27.1")
        result = compare(positional, "Kilo", "Wk", 62.4)
        self.assertFalse(result["matches_expected"])
        self.assertEqual(result["token_positions"], [2])


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "rapor.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, answers, **kwargs):
        ask, asked = scripted(answers)
        said = []
        run_wizard(Wizard(ask=ask, say=said.append), output=str(self.out), idle=0.05, **kwargs)
        return json.loads(self.out.read_text(encoding="utf-8")), asked, "\n".join(said)

    def test_quick_mode_asks_only_model_and_weight(self):
        record = synthetic_record(subject=99, rng=random.Random(5))
        weight = str(analyze_record(record)["values"]["Wk"])
        port = FakePort([record[:40].encode(), record[40:].encode()])
        report, asked, said = self._run(
            ["MC-780MA", weight], port_opener=lambda s: port,
            ports=[("/dev/ttyS0", "n/a"), ("/dev/ttyUSB0", "FT232R")])

        self.assertEqual(len(asked), 2)
        self.assertIn("Port: /dev/ttyUSB0", said)
        self.assertTrue(port.closed)
        self.assertEqual(report["mode"], "hizli")
        self.assertEqual(report["device"]["model"], "MC-780MA")
        self.assertEqual(report["port"]["baudrate"], 9600)
        m = report["measurements"][0]
        self.assertEqual(m["subject_ids_masked"], 1)
        self.assertNotIn("0000000000000099", m["raw_text"])
        self.assertTrue(m["records"][0]["recognized"])
        self.assertTrue(m["screen"][0]["matches_expected"])

    def test_quick_mode_without_data(self):
        report, asked, said = self._run(["BC-418"], port="/dev/ttyUSB0", timeout=0.1,
                                         port_opener=lambda s: FakePort([]))
        self.assertIn("Hiç veri gelmedi", said)
        self.assertEqual(report["measurements"][0]["summary"]["bytes"], 0)

    def test_sd_card_file(self):
        sd = Path(self.tmp.name) / "20261016.CSV"
        sd.write_bytes((SAMPLE + "\r\n").encode())
        report, asked, _ = self._run(["MC-780", ""], files=[str(sd)])
        self.assertEqual(report["device"]["connection"], "SD kart dosyası")
        self.assertTrue(report["measurements"][0]["records"][0]["recognized"])

    def test_detailed_mode_compares_inputs_and_screen(self):
        port = FakePort([(SAMPLE + "\r\n").encode()])
        answers = ["MC-780MA", "Tanita", "1.0", "varsayılan", "1", "/dev/ttyUSB0", "9600", "1",
                   "2", "34", "165", "0.5",          # cihaza girilenler
                   "62.4", "27.1", "", "", "", "", "4", "1350", "", "22.9",  # ekran
                   "test notu"]
        report, asked, said = self._run(answers, port_opener=lambda s: port, ports=[],
                                        detailed=True)
        m = report["measurements"][0]
        self.assertEqual(len(m["inputs"]), 4)
        self.assertTrue(all(c["matches_expected"] for c in m["inputs"] + m["screen"]))
        self.assertEqual(report["notes"], "test notu")
        self.assertIn("9 değerden 9 tanesi", said)


class SendChoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sd = Path(self.tmp.name) / "20261016.CSV"
        self.sd.write_bytes((SAMPLE + "\r\n").encode())
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, answers, env=None):
        import os
        ask, _ = scripted(answers)
        said = []
        old = os.environ.get("TARTIM_RAPOR_ADRESI")
        if env is not None:
            os.environ["TARTIM_RAPOR_ADRESI"] = env
        try:
            run_wizard(Wizard(ask=ask, say=said.append), files=[str(self.sd)],
                       output=str(Path(self.tmp.name) / "r.json"),
                       send=lambda report, note: self.sent.append(note) or {"ok": True, "id": "R1"})
        finally:
            if env is not None:
                if old is None:
                    del os.environ["TARTIM_RAPOR_ADRESI"]
                else:
                    os.environ["TARTIM_RAPOR_ADRESI"] = old
        return "\n".join(said)

    def test_server_with_consent(self):
        said = self._run(["MC-780", "", "1", "e", "deneme notu"])
        self.assertEqual(self.sent, ["deneme notu"])
        self.assertIn("Rapor numaranız: R1", said)

    def test_server_without_consent_is_not_sent(self):
        said = self._run(["MC-780", "", "1", "h"])
        self.assertEqual(self.sent, [])
        self.assertIn("gönderilmez", said)

    def test_github_and_later(self):
        self.assertIn("issues/new", self._run(["MC-780", "", "2"]))
        self.assertIn("rapor-gonder", self._run(["MC-780", "", "3"]))
        self.assertEqual(self.sent, [])

    def test_server_option_can_be_disabled(self):
        said = self._run(["MC-780", "", "1"], env="")
        self.assertNotIn("Proje sunucusuna", said)
        self.assertIn("issues/new", said)  # 1. seçenek artık GitHub formu
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
