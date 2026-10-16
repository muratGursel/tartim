"""Device report: collecting development data from people who own a scale.

``tartim report`` asks a few short questions, records the raw measurement data
from the device and compares it with the values read on the device display.
The result is a single JSON file to share with the project. The client number
is masked with zeros before anything is written.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import __version__
from .fields import describe
from .i18n import N_, _, ngettext
from .protocol import Framer, parse

SCHEMA_VERSION = 1
# The template keeps its original file name so links in older releases still work.
REPORT_FORM_URL = "https://github.com/muratGursel/tartim/issues/new?template=cihaz-raporu.yml"
DEFAULT_SERVER = "https://ldow.duckdns.org/tartim/report"

# Results read on the device display: (question, expected code)
SCREEN_FIELDS = [
    (N_("Weight (kg)"), "Wk"),
    (N_("Body fat (%)"), "FW"),
    (N_("Fat mass (kg)"), "fW"),
    (N_("Muscle mass (kg)"), "mW"),
    (N_("Bone mass (kg)"), "bW"),
    (N_("Total body water (%)"), "ww"),
    (N_("Visceral fat rating"), "IF"),
    (N_("Basal metabolic rate (kcal)"), "rB"),
    (N_("Metabolic age"), "rA"),
    ("BMI", "MI"),
]
# Values entered on the device before measuring.
INPUT_FIELDS = [
    (N_("Gender (1: male, 2: female)"), "GE"),
    (N_("Age"), "AG"),
    (N_("Height (cm)"), "Hm"),
    (N_("Clothes weight / tare (kg)"), "Pt"),
]
CONNECTIONS = [N_("RS-232 (with a USB-serial adapter)"), N_("USB (direct)"),
               N_("SD card file"), "Bluetooth"]
SEND_OPTIONS = [
    (N_("Send to the project server (no account needed)"), "server"),
    (N_("I will send it myself with the GitHub form"), "github"),
    (N_("Do not send now, keep the file on my computer"), "later"),
]

# Messages for the error codes returned by the report server.
SERVER_ERRORS = {
    "consent-required": N_("You must confirm that the measurement does not belong to a "
                           "real client."),
    "unknown-format": N_("The report format was not recognised."),
    "model-missing": N_("The device model is missing."),
    "measurements-invalid": N_("The measurement list is not valid."),
    "note-invalid": N_("The note must be text."),
    "invalid-request": N_("The request was not valid."),
    "unreadable": N_("The report could not be read."),
    "too-large": N_("The report is too large."),
    "rate-limited": N_("Too many reports were sent; please try again later."),
    "server-full": N_("The server is not accepting reports right now; please try again later."),
}

_ID_RE = re.compile(rb'(\bID,"?)(\d+)')


def mask_subject_ids(data: bytes) -> tuple[bytes, int]:
    """Replaces the client numbers in ``ID`` fields with zeros of the same length."""
    return _ID_RE.subn(lambda m: m.group(1) + b"0" * len(m.group(2)), data)


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def analyze_record(record: str) -> dict:
    """Splits a record into items and extracts the recognised fields."""
    text = record.strip().lstrip("{").rstrip("}").replace("\r", "").replace("\n", "")
    try:
        tokens = next(csv.reader([text]), [])
    except csv.Error:
        tokens = text.split(",")
    m = parse(record)
    return {"raw": record, "tokens": tokens, "recognized": m.recognized, "values": m.values}


def compare(analysis: dict, label: str, code: str, value: float) -> dict:
    """Matches a value read on the display against the items of a record.

    Even when the record is not in key-value format this finds the position of
    the value, which is enough of a hint to decode unknown formats.
    """
    tolerance = 0.051
    positions = [i for i, t in enumerate(analysis["tokens"])
                 if (n := _number(t.strip().strip('"'))) is not None and abs(n - value) < tolerance]
    tokens = analysis["tokens"]
    codes = [tokens[i - 1].strip() for i in positions if i > 0]
    expected = analysis["values"].get(code)
    matches = isinstance(expected, (int, float)) and abs(expected - value) < tolerance
    return {"label": label, "expected_code": code, "screen_value": value,
            "record_value": expected, "matches_expected": matches,
            "token_positions": positions, "codes_with_value": codes}


def system_info() -> dict:
    info = {"python": platform.python_version(), "kernel": platform.release(),
            "tartim": __version__}
    try:
        info["os"] = platform.freedesktop_os_release().get("PRETTY_NAME")
    except OSError:
        info["os"] = platform.platform()
    try:
        import serial  # noqa: PLC0415

        info["pyserial"] = serial.__version__
    except ImportError:
        info["pyserial"] = None
    return info


def port_details(device: str) -> dict:
    """Device details such as the USB id. The USB serial number is deliberately left out."""
    if device.lower().startswith("bt:"):
        from .bluetooth import mask_address, parse_bt_port  # noqa: PLC0415

        address, channel = parse_bt_port(device)
        return {"device": f"bt:{mask_address(address)}", "transport": "bluetooth-rfcomm",
                "channel": channel}
    try:
        from serial.tools import list_ports  # noqa: PLC0415
    except ImportError:
        return {"device": device}
    resolved = str(Path(device).resolve()) if Path(device).exists() else device
    for p in list_ports.comports():
        if p.device in (device, resolved):
            return {"device": device, "description": p.description,
                    "vid": f"{p.vid:04x}" if p.vid is not None else None,
                    "pid": f"{p.pid:04x}" if p.pid is not None else None,
                    "manufacturer": p.manufacturer, "product": p.product}
    return {"device": device}


def capture(port, timeout: float, idle: float = 2.0,
            clock: Callable[[], float] = time.monotonic,
            cancelled: Callable[[], bool] = lambda: False) -> tuple[bytes, list[list[int]]]:
    """Waits at most ``timeout`` seconds for the first byte; once data arrives it
    stops after ``idle`` seconds of silence. Returns the byte stream and the
    timing of every chunk (ms, byte count)."""
    start = clock()
    last = None
    data = bytearray()
    timing: list[list[int]] = []
    while not cancelled():
        now = clock()
        if last is None and now - start > timeout:
            break
        if last is not None and now - last > idle:
            break
        chunk = port.read(port.in_waiting or 1)
        if chunk:
            last = clock()
            timing.append([round((last - start) * 1000), len(chunk)])
            data += chunk
    return bytes(data), timing


def stream_summary(data: bytes) -> dict:
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in data)
    return {
        "bytes": len(data),
        "printable_ratio": round(printable / len(data), 3) if data else None,
        "crlf": b"\r\n" in data,
        "lf_only": b"\n" in data and b"\r\n" not in data,
        "starts_with_brace": data.lstrip().startswith(b"{"),
    }


class Wizard:
    """Question-and-answer flow. ``ask`` and ``say`` can be replaced in tests."""

    def __init__(self, ask: Callable[[str], str] = input,
                 say: Callable[[str], None] = print):
        self._ask = ask
        self.say = say

    def ask(self, question: str, default: str = "", required: bool = False) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            try:
                answer = self._ask(f"{question}{suffix}: ").strip()
            except EOFError:
                if required and not default:
                    raise SystemExit(_("Input ended; no report was created.")) from None
                answer = ""
            answer = answer or default
            if answer or not required:
                return answer
            self.say("  " + _("This is required."))

    def ask_number(self, question: str) -> float | None:
        while True:
            answer = self.ask(question)
            if not answer:
                return None
            value = _number(answer)
            if value is not None:
                return value
            self.say("  " + _("Enter a number (or press Enter to skip)."))

    def choose(self, question: str, options: list[str], default: int = 1) -> int:
        for i, option in enumerate(options, 1):
            self.say(f"  {i}) {option}")
        while True:
            answer = self.ask(question, str(default))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            self.say("  " + _("Enter a number between 1 and {count}.").format(
                count=len(options)))

    def yes(self, question: str, default: bool = True) -> bool:
        # TRANSLATORS: the letters for "yes" and "no" in yes/no questions.
        yes_letter, no_letter = _("y"), _("n")
        answer = self.ask(f"{question} ({yes_letter}/{no_letter})",
                          yes_letter if default else no_letter).lower()
        return answer[:1] in {yes_letter.lower(), "y", "e"}


def build_entry(data: bytes, timing: list, source: str) -> tuple[dict, dict | None]:
    """Prepares the report entry of one measurement attempt. The second value is
    the record that display values are compared with (None without data)."""
    masked, count = mask_subject_ids(data)
    framer = Framer()
    records = framer.feed(masked) + framer.flush()
    analyses = [analyze_record(r) for r in records]
    entry = {"source": source, "summary": stream_summary(masked), "timing_ms": timing,
             "raw_hex": masked.hex(), "raw_text": masked.decode("latin-1"),
             "subject_ids_masked": count, "records": analyses,
             "inputs": [], "screen": []}
    measured = [a for a in analyses if a["tokens"]]
    target = next((a for a in measured if a["recognized"]), measured[-1]) if measured else None
    return entry, target


def report_server() -> str | None:
    """Address of the report server. An organisation can set its own server with
    TARTIM_REPORT_URL; an empty value disables sending to a server."""
    for variable in ("TARTIM_REPORT_URL", "TARTIM_RAPOR_ADRESI"):  # the latter: before 0.6
        if variable in os.environ:
            return os.environ[variable].strip() or None
    return DEFAULT_SERVER


def send_report(report: dict, note: str = "", url: str | None = None, consent: bool = True,
                timeout: float = 30) -> dict:
    """Sends the report to the project server over HTTPS and returns the server's
    answer; on failure raises RuntimeError with a message for the user."""
    url = url or report_server()
    if not url:
        raise RuntimeError(_("Sending to a server is disabled in this installation "
                             "(TARTIM_REPORT_URL is empty)."))
    data = json.dumps({"report": report, "note": note, "consent": consent},
                      ensure_ascii=False).encode()
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": f"tartim/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except ValueError:
            body = {}
        message = SERVER_ERRORS.get(body.get("code"))
        raise RuntimeError(_(message) if message else body.get("error") or _(
            "The server did not accept the report (HTTP {status}).").format(status=exc.code)) \
            from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(_("Could not reach the report server. Check your internet "
                             "connection; the report file is still on your computer and can "
                             "be sent later.")) from exc


def new_report(device: dict, mode: str) -> dict:
    return {"schema": SCHEMA_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": mode, "system": system_info(), "device": device, "measurements": []}


def save_report(report: dict, output: str | Path | None = None,
                directory: Path | None = None) -> Path:
    model = re.sub(r"[^A-Za-z0-9-]+", "", report["device"].get("model", "")) or "device"
    name = f"tartim-report-{model}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path = Path(output) if output else (directory or Path.cwd()) / name
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _ask_weight(w: Wizard, entry: dict, target: dict) -> None:
    label, code = SCREEN_FIELDS[0]
    value = w.ask_number(_("Weight shown on the display (optional)"))
    if value is not None:
        entry["screen"].append(compare(target, label, code, value))


def _measurement_entry(w: Wizard, data: bytes, timing: list, source: str,
                       detailed: bool) -> dict:
    entry, target = build_entry(data, timing, source)
    if target is None:
        return entry
    if not detailed:
        # Quick mode: only the weight is asked; that is enough of a hint to verify a record.
        _ask_weight(w, entry, target)
        return entry

    if target["recognized"]:
        w.say("\n" + _("Decoded values:"))
        for code, value in target["values"].items():
            if code not in ("CS", "ID"):
                w.say(f"  {describe(code).name:<38} {value}")
    else:
        w.say("\n" + _("The record is not in a known format. The values on the display will "
                       "help us decode it."))
    w.say("\n" + _("Values you entered on the device before measuring (leave empty if unsure):"))
    for label, code in INPUT_FIELDS:
        value = w.ask_number(f"  {_(label)}")
        if value is not None:
            entry["inputs"].append(compare(target, label, code, value))
    w.say("\n" + _("Results shown on the device display or printout (optional):"))
    for label, code in SCREEN_FIELDS:
        value = w.ask_number(f"  {_(label)}")
        if value is not None:
            entry["screen"].append(compare(target, label, code, value))
    checks = entry["inputs"] + entry["screen"]
    if checks:
        ok = sum(c["matches_expected"] for c in checks)
        w.say("\n" + ngettext("Comparison: {ok} of {count} value matched the expected field.",
                              "Comparison: {ok} of {count} values matched the expected field.",
                              len(checks)).format(ok=ok, count=len(checks)))
    return entry


def _pick_port(w: Wizard, ports: list[tuple[str, str]], detailed: bool) -> str:
    """Picks the only USB-serial port (in quick mode), otherwise asks the user."""
    usb = [dev for dev, _desc in ports if "ttyUSB" in dev or "ttyACM" in dev]
    if len(usb) == 1 and not detailed:
        w.say(_("Port: {port}").format(port=usb[0]))
        return usb[0]
    if ports:
        w.say("\n" + _("Serial ports found:"))
        for i, (dev, desc) in enumerate(ports, 1):
            w.say(f"  {i}) {dev}  {desc}")
    else:
        w.say("\n" + _("No serial port found. Plug in the cable and check with 'lsusb'."))
    answer = w.ask(_("Port (number or path, e.g. /dev/ttyUSB0)"), required=True)
    if answer.isdigit() and 0 < int(answer) <= len(ports):
        return ports[int(answer) - 1][0]
    return answer


def ble_entry(device, result: dict) -> tuple[dict, dict | None]:
    """Report entry from a BLE capture. The notifications are joined and parsed
    for text-based protocols too; decoded standard scale data is used if present."""
    from .bluetooth import mask_address, standard_values  # noqa: PLC0415

    data = b"".join(bytes.fromhex(n["hex"]) for n in result["notifications"])
    timing = [[n["t_ms"], len(n["hex"]) // 2] for n in result["notifications"]]
    entry, target = build_entry(data, timing, source="bluetooth-le")
    entry["bluetooth"] = {"address": mask_address(device.address), "name": device.name,
                          "kind": device.kind_code, "uuids": device.uuids, **result}
    values = standard_values(result)
    if values:
        entry["standard_values"] = values
        target = {"raw": "", "tokens": [], "recognized": True, "values": values}
    return entry, target


def _pick_bluetooth(w: Wizard, devices: list) -> object:
    if not devices:
        raise SystemExit(_("No Bluetooth device found. Turn the scale on and try again."))
    w.say("\n" + _("Bluetooth devices found:"))
    for i, d in enumerate(devices, 1):
        rssi = f"{d.rssi} dBm" if d.rssi is not None else ""
        w.say(f"  {i}) {d.name or _('(no name)'):<24} {d.kind:<22} {rssi}")
    while True:
        answer = w.ask(_("Which one is your scale? (number)"), "1", required=True)
        if answer.isdigit() and 0 < int(answer) <= len(devices):
            return devices[int(answer) - 1]
        w.say("  " + _("Enter a number between 1 and {count}.").format(count=len(devices)))


def _bluetooth_measurements(w: Wizard, report: dict, timeout: float, idle: float,
                            detailed: bool, session_factory: Callable | None,
                            port_opener: Callable | None) -> None:
    from . import bluetooth  # noqa: PLC0415

    w.say("\n" + _("Turn the scale on. Scanning for nearby Bluetooth devices (10 s)..."))
    with (session_factory or bluetooth.BlueZ)() as bz:
        try:
            devices = bluetooth.scan(bz, 10)
        except bluetooth.BluetoothError as exc:
            raise SystemExit(str(exc)) from exc
        device = _pick_bluetooth(w, devices)
        report["device"]["connection"] = f"bluetooth ({device.kind_code})"
        if device.classic_serial:
            from . import serial_io  # noqa: PLC0415

            report["port"] = port_details(device.port)
            conn = (port_opener or serial_io.open_port)(serial_io.PortSettings(device.port))
            try:
                w.say("\n" + _("Connected to {name}. Take a measurement on the device now...")
                      .format(name=device.name or device.address))
                data, timing = capture(conn, timeout, idle)
            finally:
                conn.close()
            w.say(_("Data received ({count} bytes).").format(count=len(data)) if data
                  else _("No data received."))
            report["measurements"].append(_measurement_entry(
                w, data, timing, source="bluetooth-rfcomm", detailed=detailed))
            return
        w.say("\n" + _("Connecting to {name}...").format(name=device.name or _("the device")))
        try:
            result = bluetooth.capture_ble(
                bz, device, timeout=timeout, idle=idle,
                on_connected=lambda: w.say(_("Connected. Take a measurement on the device now "
                                             "(waiting up to {seconds} s)...").format(
                                                 seconds=f"{timeout:g}")))
        except bluetooth.BluetoothError as exc:
            raise SystemExit(str(exc)) from exc
    count = len(result["notifications"])
    w.say(ngettext("{count} Bluetooth notification received.",
                   "{count} Bluetooth notifications received.", count).format(count=count)
          if count else
          _("No notifications arrived. The device may be waiting for a command from its app "
            "before sending data; the report still contains its service structure."))
    entry, target = ble_entry(device, result)
    if target is not None:
        _ask_weight(w, entry, target)
    report["measurements"].append(entry)


def run_wizard(w: Wizard, port_opener: Callable | None = None, port: str | None = None,
               baud: int | None = None, timeout: float = 180.0,
               output: str | None = None, idle: float = 2.0,
               files: list[str] | None = None, detailed: bool = False,
               ports: list[tuple[str, str]] | None = None, bluetooth: bool = False,
               bt_session: Callable | None = None, send: Callable | None = None) -> Path:
    """If ``send`` is given (e.g. ``send_report``) the user is offered to send the
    report after it has been saved."""
    w.say(_("=== tartim device report ===") + "\n" +
          _("A report file will be prepared so that we can learn your device's data format.") +
          "\n" + _("The client number is masked. Measure yourself or a test person.") + "\n")

    device = {"brand": "Tanita",
              "model": w.ask(_("Device model (on the label, e.g. MC-780MA)"), required=True)}
    if detailed:
        device["brand"] = w.ask(_("Brand"), "Tanita")
        device["software_version"] = w.ask(_("Device software version (if known)"))
        device["output_setting"] = w.ask(
            _("PC data output setting (if known, e.g. 'default' or 'BC-418')"))
        if not files and not port and not bluetooth:
            w.say("\n" + _("Connection type:"))
            choice = w.choose(_("Your choice"), [_(c) for c in CONNECTIONS])
            if choice == 2:
                files = [w.ask(_("Path of the file on the SD card"), required=True)]
            bluetooth = choice == 3
    device["connection"] = "sd-card-file" if files else "serial-port"

    report = new_report(device, "detailed" if detailed else "quick")

    if bluetooth:
        _bluetooth_measurements(w, report, timeout, idle, detailed, bt_session, port_opener)
    elif files:
        for path in files:
            try:
                data = Path(path).read_bytes()[:256 * 1024]
            except OSError as exc:
                w.say(_("Could not read {path}: {error}").format(path=path, error=exc))
                continue
            w.say(_("{name} read.").format(name=Path(path).name))
            report["measurements"].append(_measurement_entry(
                w, data, [], source=f"file:{Path(path).name}", detailed=detailed))
    else:
        from . import serial_io  # noqa: PLC0415

        if not port:
            port = _pick_port(w, serial_io.list_ports() if ports is None else ports, detailed)
        if not baud:
            baud = int(w.ask(_("Baud rate"), "9600")) if detailed else 9600
        settings = serial_io.PortSettings(port, baud)
        report["port"] = {**port_details(port), "baudrate": baud, "bytesize": settings.bytesize,
                          "parity": settings.parity, "stopbits": settings.stopbits}
        count = int(w.ask(_("How many measurements should be recorded?"), "1")) if detailed else 1
        conn = (port_opener or serial_io.open_port)(settings)
        try:
            for i in range(count):
                prefix = f"[{i + 1}/{count}] " if count > 1 else ""
                w.say("\n" + prefix + _("Take a measurement on the device now. Waiting (up to "
                                        "{seconds} s)...").format(seconds=f"{timeout:g}"))
                data, timing = capture(conn, timeout, idle)
                if data:
                    w.say(_("Data received ({count} bytes).").format(count=len(data)))
                else:
                    w.say(_("No data received. Check the cable and the device's PC output "
                            "setting.") + "\n" +
                          _("To try another speed: tartim report --baud 19200"))
                report["measurements"].append(_measurement_entry(
                    w, data, timing, source=f"serial:{port}", detailed=detailed))
        finally:
            conn.close()

    if detailed:
        report["notes"] = w.ask("\n" + _("Anything you want to add (problems, device settings "
                                         "etc.)"))
    path = save_report(report, output)
    w.say("\n" + _("Report saved: {path}").format(path=path.resolve()))
    if send is None:
        return path
    options = SEND_OPTIONS if report_server() else SEND_OPTIONS[1:]
    w.say("\n" + _("How would you like to send the report?"))
    choice = options[w.choose(_("Your choice"), [_(label) for label, _key in options])][1]
    if choice == "server":
        if not w.yes(_("Does this measurement belong to you or a test person (not a real "
                       "client)?"), default=False):
            w.say(_("Measurements of real clients are not sent. Please take a new measurement "
                    "of yourself or a test person."))
            return path
        note = report.get("notes") or w.ask(_("A short note (optional)"))
        try:
            result = send(report, note=note)
        except RuntimeError as exc:
            w.say(_("Could not send: {error}").format(error=exc) + "\n" +
                  _("To try again later: tartim send-report {path}").format(path=path))
        else:
            w.say(_("Sent, thank you! Your report number: {id}").format(id=result.get("id")))
    elif choice == "github":
        w.say(_("Open the form at this address and drag the file into the “Report file” box:")
              + f"\n{REPORT_FORM_URL}")
    else:
        w.say(_("The report stays on your computer. To send it later:") +
              f"\n  tartim send-report {path}\n" +
              _("or send the file with the GitHub form: {url}").format(url=REPORT_FORM_URL))
    return path


def send_saved(path: str, note: str = "", w: Wizard | None = None) -> int:
    """Sends a previously saved report file to the server."""
    w = w or Wizard()
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(_("Could not read the report file: {error}").format(error=exc)) from exc
    if not w.yes(_("Does this measurement belong to you or a test person (not a real client)?"),
                 default=False):
        w.say(_("Measurements of real clients are not sent."))
        return 1
    try:
        result = send_report(report, note=note)
    except RuntimeError as exc:
        raise SystemExit(_("Could not send: {error}").format(error=exc)) from exc
    w.say(_("Sent, thank you! Your report number: {id}").format(id=result.get("id")))
    return 0


def main_from_args(args) -> int:
    try:
        run_wizard(Wizard(), port=args.port, baud=args.baud, timeout=args.timeout,
                   output=args.output, files=args.file, detailed=args.detailed,
                   bluetooth=args.bluetooth, send=None if args.no_send else send_report)
    except KeyboardInterrupt:
        print("\n" + _("Cancelled; no report was created."), file=sys.stderr)
        return 130
    return 0
