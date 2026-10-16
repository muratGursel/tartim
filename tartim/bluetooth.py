"""Bluetooth support (BlueZ over D-Bus).

There are two kinds of devices:

* Classic Bluetooth serial port (SPP) devices behave like a cable once paired.
  Use ``bt:AA:BB:CC:DD:EE:FF`` as the port (optional channel:
  ``bt:AA:BB:CC:DD:EE:FF@1``); ``serial_io.open_port`` opens it as an RFCOMM socket.
* Bluetooth Low Energy (BLE) devices send data as notifications on GATT
  characteristics. Devices using the Bluetooth SIG standard Weight Scale
  (0x181D) and Body Composition (0x181B) services are decoded here; for
  vendor-specific services the raw notifications are saved in the report.
"""

from __future__ import annotations

import socket
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .i18n import _

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
SERVICE = "org.bluez.GattService1"
CHARACTERISTIC = "org.bluez.GattCharacteristic1"
PROPERTIES = "org.freedesktop.DBus.Properties"

SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
WEIGHT_SCALE_SERVICE = "0000181d-0000-1000-8000-00805f9b34fb"
BODY_COMPOSITION_SERVICE = "0000181b-0000-1000-8000-00805f9b34fb"
WEIGHT_MEASUREMENT = "00002a9d-0000-1000-8000-00805f9b34fb"
BODY_COMPOSITION_MEASUREMENT = "00002a9c-0000-1000-8000-00805f9b34fb"

# Names of well-known standard UUIDs (helpful when reading reports; not translated).
KNOWN_UUIDS = {
    "0000180a": "Device Information service",
    "0000181d": "Weight Scale service (standard)",
    "0000181b": "Body Composition service (standard)",
    "0000180f": "Battery service",
    "00002a00": "Device Name",
    "00002a19": "Battery Level",
    "00002a24": "Model Number",
    "00002a25": "Serial Number",
    "00002a26": "Firmware Revision",
    "00002a27": "Hardware Revision",
    "00002a28": "Software Revision",
    "00002a29": "Manufacturer Name",
    "00002a9c": "Body Composition Measurement",
    "00002a9d": "Weight Measurement",
    "00002a9e": "Weight Scale Feature",
}
# Values that uniquely identify a device are never put in a report.
PRIVATE_UUIDS = {"00002a25-0000-1000-8000-00805f9b34fb"}


def uuid_name(uuid: str) -> str:
    return KNOWN_UUIDS.get(uuid.lower()[:8], "")


def mask_address(address: str) -> str:
    """Keeps the first three bytes (vendor prefix) and hides the device-specific part."""
    parts = address.upper().split(":")
    return ":".join(parts[:3] + ["XX"] * (len(parts) - 3)) if len(parts) == 6 else "XX"


# --- Decoding standard BLE measurements ---------------------------------------

def decode_weight_measurement(data: bytes) -> dict:
    """Bluetooth SIG Weight Measurement (0x2A9D)."""
    flags = data[0]
    imperial = flags & 0x01
    raw = struct.unpack_from("<H", data, 1)[0]
    result: dict[str, object] = {}
    result["Wk"] = round(raw * 0.01 * 0.45359237, 2) if imperial else round(raw * 0.005, 2)
    offset = 3
    if flags & 0x02:  # time stamp
        year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data, offset)
        result["Da"] = f"{day:02d}/{month:02d}/{year}"
        result["TI"] = f"{hour:02d}:{minute:02d}"
        offset += 7
    if flags & 0x04:  # user id
        result["ID"] = str(data[offset])
        offset += 1
    if flags & 0x08:  # BMI and height
        bmi, height = struct.unpack_from("<HH", data, offset)
        result["MI"] = round(bmi * 0.1, 1)
        result["Hm"] = round(height * 0.1 * 2.54, 1) if imperial else round(height * 0.1, 1)
    return result


def decode_body_composition(data: bytes) -> dict:
    """Bluetooth SIG Body Composition Measurement (0x2A9C)."""
    flags, fat = struct.unpack_from("<HH", data, 0)
    imperial = flags & 0x0001
    mass = (lambda v: round(v * 0.01 * 0.45359237, 2)) if imperial else (lambda v: round(v * 0.005, 2))
    result: dict[str, object] = {"FW": round(fat * 0.1, 1)}
    offset = 4

    def u16() -> int:
        nonlocal offset
        value = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        return value

    if flags & 0x0002:
        year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data, offset)
        result["Da"] = f"{day:02d}/{month:02d}/{year}"
        result["TI"] = f"{hour:02d}:{minute:02d}"
        offset += 7
    if flags & 0x0004:
        result["ID"] = str(data[offset])
        offset += 1
    if flags & 0x0008:
        result["rB"] = round(u16() / 4.184)  # kJ -> kcal
    if flags & 0x0010:
        result["mP"] = round(u16() * 0.1, 1)
    if flags & 0x0020:
        result["mW"] = mass(u16())
    if flags & 0x0040:
        result["MW"] = mass(u16())
    if flags & 0x0080:
        result["sL"] = mass(u16())
    if flags & 0x0100:
        result["wW"] = mass(u16())
    if flags & 0x0200:
        result["Im"] = round(u16() * 0.1, 1)
    if flags & 0x0400:
        result["Wk"] = mass(u16())
    if flags & 0x0800:
        height = u16()
        result["Hm"] = round(height * 0.1 * 2.54, 1) if imperial else round(height * 0.1, 1)
    return result


DECODERS = {WEIGHT_MEASUREMENT: decode_weight_measurement,
            BODY_COMPOSITION_MEASUREMENT: decode_body_composition}


def decode_standard(uuid: str, data: bytes) -> dict | None:
    decoder = DECODERS.get(uuid.lower())
    if not decoder:
        return None
    try:
        return decoder(data)
    except (struct.error, IndexError):
        return None


# --- Classic Bluetooth (RFCOMM) ------------------------------------------------

def parse_bt_port(port: str) -> tuple[str, int | None]:
    """``bt:AA:BB:CC:DD:EE:FF`` or ``bt:AA:BB:CC:DD:EE:FF@3``."""
    rest = port[3:]
    address, _sep, channel = rest.partition("@")
    return address.upper(), int(channel) if channel else None


class RfcommPort:
    """Makes an RFCOMM socket usable like a pyserial port."""

    in_waiting = 0

    def __init__(self, address: str, channel: int | None = None, timeout: float = 0.5):
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise SystemExit(_("Bluetooth sockets are not supported on this system."))
        errors = []
        for ch in [channel] if channel else range(1, 6):
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(10)
            try:
                sock.connect((address, ch))
            except OSError as exc:
                sock.close()
                errors.append(_("channel {channel}: {error}").format(channel=ch, error=exc))
                continue
            sock.settimeout(timeout)
            self.sock, self.channel = sock, ch
            return
        raise SystemExit(
            _("Could not connect to {address} over Bluetooth ({errors}).").format(
                address=address, errors="; ".join(errors)) + "\n" +
            _("Turn the device on and pair it first in the Bluetooth section of the system "
              "settings (the PIN is usually 0000 or 1234)."))

    def read(self, n: int = 1) -> bytes:
        try:
            return self.sock.recv(max(n, 1024))
        except socket.timeout:
            return b""

    def write(self, data: bytes) -> int:
        self.sock.sendall(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.sock.close()


# --- BlueZ access --------------------------------------------------------------

@dataclass
class BtDevice:
    path: str
    address: str
    name: str
    rssi: int | None
    uuids: list[str] = field(default_factory=list)
    paired: bool = False

    @property
    def classic_serial(self) -> bool:
        return SPP_UUID in self.uuids

    @property
    def standard_scale(self) -> bool:
        return WEIGHT_SCALE_SERVICE in self.uuids or BODY_COMPOSITION_SERVICE in self.uuids

    @property
    def kind_code(self) -> str:
        """Stable identifier, used in reports."""
        if self.classic_serial:
            return "classic-serial"
        if self.standard_scale:
            return "ble-standard"
        return "ble"

    @property
    def kind(self) -> str:
        """Translated label for display."""
        return {"classic-serial": _("Classic (serial port)"),
                "ble-standard": _("BLE (standard scale)"),
                "ble": "BLE"}[self.kind_code]

    @property
    def port(self) -> str:
        return f"bt:{self.address}"


class BlueZ:
    """BlueZ over D-Bus. Signals are dispatched in the GLib context of the thread
    that created this object; long operations are advanced with ``pump``."""

    def __init__(self):
        try:
            from gi.repository import Gio, GLib  # noqa: PLC0415
        except ImportError as exc:
            raise SystemExit(_("Bluetooth needs python3-gi: sudo apt install python3-gi")) \
                from exc
        self.Gio, self.GLib = Gio, GLib
        self.context = GLib.MainContext.new()
        self.context.push_thread_default()
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error as exc:
            self.context.pop_thread_default()
            raise SystemExit(_("Could not connect to the system D-Bus: {error}").format(
                error=exc.message)) from exc
        self._subscriptions: list[int] = []

    def close(self) -> None:
        for sub in self._subscriptions:
            self.bus.signal_unsubscribe(sub)
        self._subscriptions.clear()
        self.context.pop_thread_default()

    def __enter__(self) -> "BlueZ":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def call(self, path: str, iface: str, method: str, signature: str | None = None,
             args: tuple = (), timeout_ms: int = 15000):
        GLib = self.GLib
        params = GLib.Variant(signature, args) if signature else None
        try:
            reply = self.bus.call_sync(BLUEZ, path, iface, method, params, None,
                                       self.Gio.DBusCallFlags.NONE, timeout_ms, None)
        except GLib.Error as exc:
            raise BluetoothError.from_dbus(exc.message) from exc
        return reply.unpack() if reply else ()

    def objects(self) -> dict:
        return self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0]

    def set_property(self, path: str, iface: str, name: str, value) -> None:
        self.call(path, PROPERTIES, "Set", "(ssv)", (iface, name, value))

    def subscribe(self, path: str, callback: Callable[[str, dict], None]) -> None:
        def on_signal(_conn, _sender, obj_path, _iface, _signal, params):
            iface, changed, _invalidated = params.unpack()
            callback(obj_path, iface, changed)
        sub = self.bus.signal_subscribe(BLUEZ, PROPERTIES, "PropertiesChanged", path, None,
                                        self.Gio.DBusSignalFlags.NONE, on_signal)
        self._subscriptions.append(sub)

    def pump(self, seconds: float, until: Callable[[], bool] = lambda: False) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not until():
            while self.context.iteration(False):
                pass
            time.sleep(0.02)

    def adapter(self) -> str:
        for path, ifaces in self.objects().items():
            if ADAPTER in ifaces:
                return path
        raise BluetoothError(_("No Bluetooth adapter found. Does this computer have Bluetooth?"),
                             reason="no-adapter")


class BluetoothError(Exception):
    def __init__(self, message: str, reason: str | None = None):
        super().__init__(message)
        self.reason = reason

    @classmethod
    def from_dbus(cls, message: str) -> "BluetoothError":
        """Turns a BlueZ error into a message the user can act on."""
        if "NotReady" in message or "not ready" in message.lower():
            return cls(_("Bluetooth is off. Turn it on in the system settings."), "not-ready")
        if "AccessDenied" in message or "NotPermitted" in message:
            return cls(_("No permission to use Bluetooth: {error}").format(error=message),
                       "denied")
        if "InProgress" in message:
            return cls(_("Another Bluetooth operation is in progress; try again shortly."),
                       "in-progress")
        return cls(message)


def scan(bz: BlueZ, seconds: float = 10.0) -> list[BtDevice]:
    """Scans for nearby devices. Turns the adapter on if it is off."""
    adapter = bz.adapter()
    props = bz.objects()[adapter][ADAPTER]
    if not props.get("Powered"):
        bz.set_property(adapter, ADAPTER, "Powered", bz.GLib.Variant("b", True))
        bz.pump(1.0)
    try:
        bz.call(adapter, ADAPTER, "StartDiscovery")
    except BluetoothError as exc:
        if exc.reason != "in-progress":
            raise
    try:
        bz.pump(seconds)
    finally:
        try:
            bz.call(adapter, ADAPTER, "StopDiscovery")
        except BluetoothError:
            pass
    devices = []
    for path, ifaces in bz.objects().items():
        dev = ifaces.get(DEVICE)
        if not dev or dev.get("Adapter") != adapter:
            continue
        if dev.get("RSSI") is None and not dev.get("Paired"):
            continue  # cached device that is not nearby right now
        devices.append(BtDevice(
            path=path, address=dev.get("Address", ""),
            name=dev.get("Alias") or dev.get("Name") or "",
            rssi=dev.get("RSSI"), uuids=[u.lower() for u in dev.get("UUIDs", [])],
            paired=bool(dev.get("Paired"))))
    # Standard scales and named devices first, then by signal strength.
    devices.sort(key=lambda d: (not d.standard_scale, not d.name, -(d.rssi or -999)))
    return devices


def find_device(bz: BlueZ, address: str) -> BtDevice | None:
    for path, ifaces in bz.objects().items():
        dev = ifaces.get(DEVICE)
        if dev and dev.get("Address", "").upper() == address.upper():
            return BtDevice(path, dev["Address"], dev.get("Alias") or dev.get("Name") or "",
                            dev.get("RSSI"), [u.lower() for u in dev.get("UUIDs", [])],
                            bool(dev.get("Paired")))
    return None


def _connect(bz: BlueZ, device: BtDevice) -> dict[str, dict]:
    """Connects, waits until services are resolved and returns the GATT characteristics."""
    try:
        bz.call(device.path, DEVICE, "Connect", timeout_ms=30000)
    except BluetoothError as exc:
        raise BluetoothError(_("Could not connect to the device: {error}. Make sure it is on "
                               "and nearby.").format(error=exc)) from exc

    def resolved() -> bool:
        return bool(bz.objects().get(device.path, {}).get(DEVICE, {}).get("ServicesResolved"))
    bz.pump(20, until=resolved)
    return {path: ifaces[CHARACTERISTIC] for path, ifaces in sorted(bz.objects().items())
            if path.startswith(device.path + "/") and CHARACTERISTIC in ifaces}


def _disconnect(bz: BlueZ, device: BtDevice, started: list[str]) -> None:
    for path in started:
        try:
            bz.call(path, CHARACTERISTIC, "StopNotify")
        except BluetoothError:
            pass
    try:
        bz.call(device.path, DEVICE, "Disconnect")
    except BluetoothError:
        pass


def _start_notify(bz: BlueZ, chars: dict[str, dict], only: set[str] | None = None) -> list[str]:
    started = []
    for path, props in chars.items():
        flags = props.get("Flags", [])
        if ("notify" in flags or "indicate" in flags) and \
                (only is None or props.get("UUID", "").lower() in only):
            try:
                bz.call(path, CHARACTERISTIC, "StartNotify")
                started.append(path)
            except BluetoothError:
                pass
    return started


def capture_ble(bz: BlueZ, device: BtDevice, timeout: float = 180.0, idle: float = 3.0,
                cancelled: Callable[[], bool] = lambda: False,
                on_connected: Callable[[], None] = lambda: None) -> dict:
    """Connects, reads the GATT structure and collects the notifications that
    arrive during a measurement. Nothing is written to the device."""
    started: list[str] = []
    try:
        chars = _connect(bz, device)
        services: dict[str, dict] = {}
        for path, ifaces in sorted(bz.objects().items()):
            if path.startswith(device.path + "/") and SERVICE in ifaces:
                uuid = ifaces[SERVICE].get("UUID", "")
                services[path] = {"uuid": uuid, "name": uuid_name(uuid), "characteristics": []}
        for path, props in chars.items():
            uuid = props.get("UUID", "")
            entry = {"uuid": uuid, "name": uuid_name(uuid), "flags": list(props.get("Flags", []))}
            if "read" in entry["flags"] and uuid not in PRIVATE_UUIDS:
                try:
                    value = bytes(bz.call(path, CHARACTERISTIC, "ReadValue", "(a{sv})", ({},))[0])
                    entry["value_hex"] = value.hex()
                    if value and all(32 <= b < 127 for b in value):
                        entry["value_text"] = value.decode("ascii")
                except BluetoothError as exc:
                    entry["read_error"] = str(exc)
            service = services.setdefault(props.get("Service", "?"),
                                          {"uuid": "?", "name": "", "characteristics": []})
            service["characteristics"].append(entry)

        notifications: list[dict] = []
        start = time.monotonic()
        state = {"last": None}

        def on_changed(path: str, iface: str, changed: dict) -> None:
            if iface == CHARACTERISTIC and "Value" in changed and path in chars:
                now = time.monotonic()
                state["last"] = now
                uuid = chars[path].get("UUID", "")
                value = bytes(changed["Value"])
                note = {"t_ms": round((now - start) * 1000), "uuid": uuid, "hex": value.hex()}
                decoded = decode_standard(uuid, value)
                if decoded:
                    note["decoded"] = decoded
                notifications.append(note)

        bz.subscribe(None, on_changed)
        started = _start_notify(bz, chars)
        on_connected()

        def done() -> bool:
            if cancelled():
                return True
            if state["last"] is None:
                return time.monotonic() - start > timeout
            return time.monotonic() - state["last"] > idle
        bz.pump(timeout + idle + 1, until=done)
        return {"services": list(services.values()), "notifications": notifications,
                "notify_characteristics": [chars[p].get("UUID") for p in started]}
    finally:
        _disconnect(bz, device, started)


def listen_standard(bz: BlueZ, device: BtDevice, on_values: Callable[[dict], None],
                    stopping: Callable[[], bool], quiet: float = 1.5,
                    on_connected: Callable[[], None] = lambda: None) -> None:
    """Listens to a standard BLE scale. The packets of one measurement (weight and
    body composition arrive separately) are merged after ``quiet`` seconds of
    silence and passed to ``on_values``."""
    started: list[str] = []
    try:
        chars = _connect(bz, device)
        if not any(p.get("UUID", "").lower() in DECODERS for p in chars.values()):
            raise BluetoothError(
                _("This device does not use the standard Bluetooth scale service, so it cannot "
                  "be read directly yet. If you send a “Device report”, we can add support."),
                reason="not-standard")
        merged: dict[str, object] = {}
        state = {"last": None}

        def on_changed(path: str, iface: str, changed: dict) -> None:
            if iface == CHARACTERISTIC and "Value" in changed and path in chars:
                decoded = decode_standard(chars[path].get("UUID", ""), bytes(changed["Value"]))
                if decoded:
                    merged.update(decoded)
                    state["last"] = time.monotonic()

        bz.subscribe(None, on_changed)
        started = _start_notify(bz, chars, only=set(DECODERS))
        on_connected()
        while not stopping():
            bz.pump(0.2)
            if state["last"] is not None and time.monotonic() - state["last"] > quiet:
                if "Wk" in merged:
                    on_values(dict(merged))
                merged.clear()
                state["last"] = None
    finally:
        _disconnect(bz, device, started)


def record_from_values(model: str, values: dict) -> str:
    """Turns decoded values into the record format the rest of the application handles."""
    pairs = [("MO", f'"{model}"')]
    for code, value in values.items():
        pairs.append((code, f'"{value}"' if isinstance(value, str) else str(value)))
    return "{" + ",".join(f"{k},{v}" for k, v in pairs) + "}"


def standard_values(capture: dict) -> dict:
    """Merged measurement values from standard notifications (with Tanita field codes)."""
    values: dict[str, object] = {}
    for note in capture.get("notifications", []):
        values.update(note.get("decoded") or {})
    return values
