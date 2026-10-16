"""Uçtan uca test: socat ile sanal seri port çifti kurulur, bir uca sanal tartı
yazar, diğer uçtan 'tartim dinle' okur. Linux, socat ve pyserial gerektirir."""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    import serial  # noqa: F401
except ImportError:
    serial = None

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("socat") and serial,
                     "Linux + socat + pyserial gerekli")
class SerialEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.scale, self.pc, self.db = tmp / "tarti", tmp / "pc", tmp / "t.db"
        self.socat = subprocess.Popen(
            ["socat", f"pty,raw,echo=0,link={self.scale}", f"pty,raw,echo=0,link={self.pc}"],
            stderr=subprocess.DEVNULL)
        for _ in range(50):
            if self.scale.exists() and self.pc.exists():
                break
            time.sleep(0.1)
        self.env = {**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(ROOT)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])}

    def tearDown(self):
        self.socat.terminate()
        self.socat.wait()
        self.tmp.cleanup()

    def _tartim(self, *args, **kwargs):
        return subprocess.Popen([sys.executable, "-m", "tartim", "--veritabani", str(self.db),
                                 *args], env=self.env, text=True, **kwargs)

    def test_listen_receives_simulated_measurements(self):
        listener = self._tartim("dinle", "--port", str(self.pc), "--adet", "3",
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Port açılmadan gönderilen veri kaybolur (pyserial açılışta giriş
        # tamponunu boşaltır); dinleyicinin hazır olduğunu söylemesini bekle.
        ready = threading.Event()
        threading.Thread(target=lambda: ready.set() if "dinleniyor" in
                         listener.stderr.readline() else None, daemon=True).start()
        self.assertTrue(ready.wait(30), "dinleyici başlamadı")
        sim = self._tartim("simule", "--port", str(self.scale), "--adet", "3",
                           "--aralik", "0.2", "--tohum", "7", stderr=subprocess.DEVNULL)
        self.assertEqual(sim.wait(timeout=20), 0)
        out, err = listener.communicate(timeout=20)
        self.assertEqual(listener.returncode, 0, err)
        self.assertEqual(out.count("--- Ölçüm: MC-780"), 3)
        self.assertIn("Kilo", out)

        listed = self._tartim("listele", stdout=subprocess.PIPE)
        lines = listed.communicate(timeout=20)[0].strip().splitlines()
        self.assertEqual(len(lines), 4)  # başlık + 3 ölçüm


if __name__ == "__main__":
    unittest.main()
