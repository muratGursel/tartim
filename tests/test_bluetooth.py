import json
import struct
import tempfile
import time
import unittest
from pathlib import Path

from tartim import bluetooth as bt
from tartim.report import Wizard, run_wizard
from tartim.serial_io import PortSettings, open_port

ADDR = "C8:B2:1E:12:34:56"
DEV = "/org/bluez/hci0/dev_C8_B2_1E_12_34_56"

# Sample packets built by hand from the Bluetooth SIG specification.
WEIGHT = struct.pack("<BHHBBBBBHH", 0x0A, 14480, 2026, 10, 16, 9, 30, 0, 245, 1720)
BODY = struct.pack("<HHHHHH", 0x0008 | 0x0020 | 0x0100 | 0x0400, 213, 6276, 10800, 8040, 14480)


class DecoderTests(unittest.TestCase):
    def test_weight_measurement(self):
        self.assertEqual(bt.decode_weight_measurement(WEIGHT),
                         {"Wk": 72.4, "Da": "16/10/2026", "TI": "09:30", "MI": 24.5, "Hm": 172.0})

    def test_weight_measurement_imperial(self):
        data = struct.pack("<BH", 0x01, 15962)  # 159.62 lb
        self.assertAlmostEqual(bt.decode_weight_measurement(data)["Wk"], 72.4, places=1)

    def test_body_composition(self):
        self.assertEqual(bt.decode_body_composition(BODY),
                         {"FW": 21.3, "rB": 1500, "mW": 54.0, "wW": 40.2, "Wk": 72.4})

    def test_truncated_packet_is_ignored(self):
        self.assertIsNone(bt.decode_standard(bt.BODY_COMPOSITION_MEASUREMENT, b"\x08\x00\xd5"))
        self.assertIsNone(bt.decode_standard("0000ffe1-0000-1000-8000-00805f9b34fb", BODY))


class HelperTests(unittest.TestCase):
    def test_mask_and_parse(self):
        self.assertEqual(bt.mask_address(ADDR), "C8:B2:1E:XX:XX:XX")
        self.assertEqual(bt.parse_bt_port("bt:c8:b2:1e:12:34:56@2"), (ADDR, 2))
        self.assertEqual(bt.parse_bt_port(f"bt:{ADDR}"), (ADDR, None))

    def test_device_kind(self):
        self.assertEqual(bt.BtDevice(DEV, ADDR, "x", None, [bt.SPP_UUID]).kind,
                         "Classic (serial port)")
        self.assertEqual(bt.BtDevice(DEV, ADDR, "x", None, [bt.WEIGHT_SCALE_SERVICE]).kind,
                         "BLE (standard scale)")

    def test_bt_port_goes_to_rfcomm(self):
        opened = []
        original = bt.RfcommPort
        bt.RfcommPort = lambda address, channel, timeout: opened.append((address, channel))
        try:
            open_port(PortSettings("bt:c8:b2:1e:12:34:56@3"))
        finally:
            bt.RfcommPort = original
        self.assertEqual(opened, [(ADDR, 3)])


class FakeBlueZ:
    """Mimics the BlueZ D-Bus objects: one adapter and one BLE scale."""

    class GLib:
        @staticmethod
        def Variant(sig, value):
            return value

    def __init__(self, uuids=None, notifications=(), powered=False):
        self.calls = []
        self.callbacks = []
        self.pending = []
        self.to_send = list(notifications)
        base = DEV + "/service0010"
        self.tree = {
            "/org/bluez/hci0": {bt.ADAPTER: {"Powered": powered}},
            DEV: {bt.DEVICE: {"Address": ADDR, "Alias": "FAST", "RSSI": -52,
                              "Adapter": "/org/bluez/hci0",
                              "UUIDs": uuids or [bt.BODY_COMPOSITION_SERVICE]}},
            base: {bt.SERVICE: {"UUID": bt.BODY_COMPOSITION_SERVICE}},
            base + "/char0011": {bt.CHARACTERISTIC: {
                "UUID": bt.BODY_COMPOSITION_MEASUREMENT, "Service": base,
                "Flags": ["indicate"]}},
            base + "/char0014": {bt.CHARACTERISTIC: {
                "UUID": "00002a24-0000-1000-8000-00805f9b34fb", "Service": base,
                "Flags": ["read"]}},
            base + "/char0018": {bt.CHARACTERISTIC: {
                "UUID": bt.WEIGHT_MEASUREMENT, "Service": base, "Flags": ["indicate"]}},
            base + "/char0016": {bt.CHARACTERISTIC: {
                "UUID": "00002a25-0000-1000-8000-00805f9b34fb", "Service": base,
                "Flags": ["read"]}},
        }
        self.char = base + "/char0011"
        self.weight_char = base + "/char0018"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def adapter(self):
        return "/org/bluez/hci0"

    def objects(self):
        return self.tree

    def set_property(self, path, iface, name, value):
        self.tree[path][iface][name] = value

    def call(self, path, iface, method, signature=None, args=(), timeout_ms=0):
        self.calls.append((path.rsplit("/", 1)[-1], method))
        if method == "Connect":
            self.tree[DEV][bt.DEVICE]["ServicesResolved"] = True
        if method == "ReadValue":
            if path.endswith("char0016"):
                raise AssertionError("the serial number must not be read")
            return (list(b"FAST-200"),)
        if method == "StartNotify":
            self.pending = self.to_send
        return ()

    def subscribe(self, path, callback):
        self.callbacks.append(callback)

    def pump(self, seconds, until=lambda: False):
        end = time.monotonic() + min(seconds, 5)
        while self.pending:
            item = self.pending.pop(0)
            path, value = item if isinstance(item, tuple) else (self.char, item)
            for cb in self.callbacks:
                cb(path, bt.CHARACTERISTIC, {"Value": list(value)})
        while time.monotonic() < end and not until():
            time.sleep(0.01)


class ScanAndCaptureTests(unittest.TestCase):
    def test_scan_powers_on_and_lists(self):
        bz = FakeBlueZ()
        # A cached device (no signal, not paired) must not be listed.
        bz.tree["/org/bluez/hci0/dev_11_22_33_44_55_66"] = {bt.DEVICE: {
            "Address": "11:22:33:44:55:66", "Alias": "Eski", "Adapter": "/org/bluez/hci0"}}
        devices = bt.scan(bz, 0)
        self.assertTrue(bz.tree["/org/bluez/hci0"][bt.ADAPTER]["Powered"])
        self.assertIn(("hci0", "StartDiscovery"), bz.calls)
        self.assertIn(("hci0", "StopDiscovery"), bz.calls)
        self.assertEqual([(d.name, d.kind) for d in devices], [("FAST", "BLE (standard scale)")])

    def test_capture_ble_reads_and_decodes(self):
        bz = FakeBlueZ(notifications=[BODY])
        device = bt.scan(bz, 0)[0]
        result = bt.capture_ble(bz, device, timeout=1, idle=0.1)
        self.assertEqual(result["notify_characteristics"],
                         [bt.BODY_COMPOSITION_MEASUREMENT, bt.WEIGHT_MEASUREMENT])
        chars = result["services"][0]["characteristics"]
        self.assertEqual(chars[1]["value_text"], "FAST-200")
        self.assertNotIn("value_hex", chars[2])  # the serial number was not read
        self.assertEqual(result["notifications"][0]["decoded"]["Wk"], 72.4)
        self.assertIn(("dev_C8_B2_1E_12_34_56", "Disconnect"), bz.calls)

    def test_capture_without_notifications_times_out(self):
        bz = FakeBlueZ()
        result = bt.capture_ble(bz, bt.scan(bz, 0)[0], timeout=0.2, idle=0.1)
        self.assertEqual(result["notifications"], [])


class ListenStandardTests(unittest.TestCase):
    def test_merges_packets_into_one_measurement(self):
        from tartim.protocol import parse

        bz = FakeBlueZ()
        bz.to_send = [(bz.weight_char, WEIGHT), BODY]
        got = []
        bt.listen_standard(bz, bt.scan(bz, 0)[0], got.append, stopping=lambda: bool(got),
                           quiet=0.1)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["Wk"], 72.4)
        self.assertEqual(got[0]["FW"], 21.3)
        self.assertEqual(got[0]["Hm"], 172.0)
        m = parse(bt.record_from_values("FAST", got[0]))
        self.assertTrue(m.recognized)
        self.assertEqual((m.model, m.weight, m.values["rB"]), ("FAST", 72.4, 1500))
        self.assertIn(("dev_C8_B2_1E_12_34_56", "Disconnect"), bz.calls)

    def test_non_standard_device_is_rejected(self):
        bz = FakeBlueZ(uuids=["0000ffe0-0000-1000-8000-00805f9b34fb"])
        for path, ifaces in bz.tree.items():
            if bt.CHARACTERISTIC in ifaces:
                ifaces[bt.CHARACTERISTIC]["UUID"] = "0000ffe1-0000-1000-8000-00805f9b34fb"
        with self.assertRaises(bt.BluetoothError):
            bt.listen_standard(bz, bt.scan(bz, 0)[0], lambda v: None, stopping=lambda: True)


class WizardBluetoothTests(unittest.TestCase):
    def test_quick_bluetooth_report(self):
        answers = iter(["FAST", "1", "72,4"])
        out = Path(tempfile.mkdtemp()) / "r.json"
        run_wizard(Wizard(ask=lambda q: next(answers), say=lambda s: None), output=str(out),
                   bluetooth=True, bt_session=lambda: FakeBlueZ(notifications=[BODY]),
                   timeout=1, idle=0.1)
        report = json.loads(out.read_text(encoding="utf-8"))
        m = report["measurements"][0]
        self.assertEqual(report["device"]["connection"], "bluetooth (ble-standard)")
        self.assertEqual(m["bluetooth"]["address"], "C8:B2:1E:XX:XX:XX")
        self.assertNotIn(ADDR, out.read_text(encoding="utf-8"))
        self.assertEqual(m["standard_values"]["FW"], 21.3)
        self.assertTrue(m["screen"][0]["matches_expected"])


if __name__ == "__main__":
    unittest.main()
