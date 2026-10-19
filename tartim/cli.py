"""Command line interface: ``tartim <command>``.

Commands and options are English; the Turkish names of earlier releases keep
working as aliases (e.g. ``tartim dinle`` = ``tartim listen``).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime

from . import __version__
from .clients import ATHLETIC, FEMALE, MALE, STANDARD, Client, parse_date
from .fields import describe
from .i18n import _, ngettext
from .protocol import Measurement, parse
from .storage import Store


def _print_measurement(m: Measurement, out=sys.stdout) -> None:
    if not m.recognized:
        print(_("[unrecognized record] {raw}").format(raw=m.raw), file=out)
        print("  " + _("We do not know this format. Please share the output of "
                       "'tartim raw' with the project."), file=out)
        return
    print("--- " + _("Measurement: {model}  client: {client}").format(
        model=m.model or "?", client=m.subject_id or "-") + " ---", file=out)
    for code, value in m.values.items():
        if code == "CS":
            continue
        f = describe(code)
        mark = "" if f.confirmed else " *"
        print(f"  {f.name:<38} {f.display(value)}{mark}", file=out)
    print("  " + _("(* the meaning of this field has not been verified on a real device yet)"),
          file=out)


def _port_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", required=True, help=_("e.g. /dev/ttyUSB0"))
    p.add_argument("--baud", type=int, default=9600, help=_("default: {value}").format(value=9600))
    p.add_argument("--parity", "--parite", choices="NEO", default="N",
                   help=_("default: {value}").format(value="N"))
    p.add_argument("--bytesize", "--veri-biti", type=int, choices=(7, 8), default=8)
    p.add_argument("--stopbits", "--dur-biti", type=float, choices=(1, 2), default=1)


def _open(args):
    from .serial_io import PortSettings, open_port  # noqa: PLC0415

    return open_port(PortSettings(args.port, args.baud, args.bytesize, args.parity,
                                  args.stopbits))


def cmd_ports(args) -> int:
    from .serial_io import list_ports  # noqa: PLC0415

    ports = list_ports()
    if not ports:
        print(_("No serial port found. Plug in the USB-serial adapter and check with 'lsusb'."))
    for device, desc in ports:
        print(f"{device}\t{desc}")
    return 0


def cmd_listen(args) -> int:
    from .serial_io import read_records  # noqa: PLC0415

    store = None if args.no_save else Store(args.database)
    raw_log = open(args.raw_file, "ab") if args.raw_file else None
    port = _open(args)
    print(_("Listening on {port} ({settings}). Press Ctrl+C to quit.").format(
        port=args.port, settings=f"{args.baud} {args.bytesize}{args.parity}{args.stopbits:g}"),
        file=sys.stderr)
    count = 0
    try:
        for record in read_records(port, raw_log.write if raw_log else None):
            m = parse(record)
            _print_measurement(m)
            if store:
                store.add(m, source=f"serial:{args.port}")
            count += 1
            if args.count and count >= args.count:
                break
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        if raw_log:
            raw_log.close()
        if store:
            store.close()
    return 0


def cmd_raw(args) -> int:
    """Protocol discovery: prints every incoming chunk with a time stamp, as hex and text."""
    port = _open(args)
    out = open(args.output, "a", encoding="utf-8") if args.output else sys.stdout
    print(_("Recording raw data. Take a measurement on the device; press Ctrl+C to quit."),
          file=sys.stderr)
    try:
        while True:
            chunk = port.read(port.in_waiting or 1)
            if not chunk:
                continue
            text = chunk.decode("latin-1").replace("\r", "\\r").replace("\n", "\\n")
            print(f"{datetime.now():%H:%M:%S.%f}  {chunk.hex(' ')}  |{text}|", file=out, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        if out is not sys.stdout:
            out.close()
    return 0


def cmd_import(args) -> int:
    """Imports measurements from SD card files or raw capture files."""
    with Store(args.database) as store:
        added, skipped, unknown = store.import_files(args.files)
    print(", ".join([
        ngettext("{n} measurement added", "{n} measurements added", added).format(n=added),
        ngettext("{n} duplicate skipped", "{n} duplicates skipped", skipped).format(n=skipped),
        ngettext("{n} record not recognized", "{n} records not recognized",
                 unknown).format(n=unknown),
    ]) + ".")
    return 0


def cmd_list(args) -> int:
    with Store(args.database) as store:
        rows = store.list(limit=args.last, subject_id=args.client)
        names = {c.number: c.name for c in store.clients()}
    if args.json:
        print(json.dumps([{**dict(r), "values_json": json.loads(r["values_json"])} for r in rows],
                         ensure_ascii=False, indent=2))
        return 0
    print(f"{_('No'):>5}  {_('Measured at'):<19}  {_('Model'):<8}  {_('Client'):<10}  "
          f"{_('Weight'):>6}  {_('Name')}")
    for r in rows:
        when = r["measured_at"] or r["received_at"]
        weight = f"{r['weight']:.1f}" if r["weight"] is not None else "-"
        print(f"{r['id']:>5}  {when:<19}  {r['model'] or '-':<8}  "
              f"{r['subject_id'] or '-':<10}  {weight:>6}  {names.get(r['subject_id'], '')}")
    return 0


def cmd_export(args) -> int:
    with Store(args.database) as store:
        count = store.export_csv(args.output, subject_id=args.client)
    print(ngettext("{n} measurement written to {path}.", "{n} measurements written to {path}.",
                   count).format(n=count, path=args.output))
    return 0


def cmd_bluetooth(args) -> int:
    from .bluetooth import BluetoothError, BlueZ, scan  # noqa: PLC0415

    print(_("Scanning ({seconds} s)... Make sure the scale is turned on.").format(
        seconds=f"{args.timeout:g}"), file=sys.stderr)
    with BlueZ() as bz:
        try:
            devices = scan(bz, args.timeout)
        except BluetoothError as exc:
            raise SystemExit(str(exc)) from exc
    if not devices:
        print(_("No device found."))
    for d in devices:
        rssi = f"{d.rssi} dBm" if d.rssi is not None else ""
        print(f"{d.port:<21}  {d.name or _('(no name)'):<24}  {d.kind:<22}  {rssi}")
    if any(d.classic_serial for d in devices):
        print("\n" + _("Classic (serial port) devices can be read directly: "
                       "tartim listen --port bt:ADDRESS"))
    return 0


def cmd_gui(args) -> int:
    from .gui import main as gui_main  # noqa: PLC0415

    argv = (["--database", args.database] if args.database else []) + \
        (["--port", args.port] if args.port else [])
    return gui_main(argv)


def cmd_report(args) -> int:
    from .report import main_from_args  # noqa: PLC0415

    return main_from_args(args)


def cmd_send_report(args) -> int:
    from .report import send_saved  # noqa: PLC0415

    return send_saved(args.file, note=args.note)


def cmd_print(args) -> int:
    from . import printout  # noqa: PLC0415

    with Store(args.database) as store:
        try:
            current, history = printout.entries(store, record_id=args.record,
                                                subject_id=args.client)
            path = printout.write_pdf(args.output or printout.default_name(current), current,
                                      history, client_name=args.name)
        except (LookupError, RuntimeError) as exc:
            raise SystemExit(str(exc)) from exc
    print(_("Result sheet written: {path}").format(path=path))
    return 0


def _gender(text: str) -> int:
    value = text.strip().lower()
    if value in ("1", "m", "male", "e", "erkek"):
        return MALE
    if value in ("2", "f", "female", "k", "kadin", "kadın"):
        return FEMALE
    raise argparse.ArgumentTypeError(_("use male or female"))


def _body_type(text: str) -> int:
    value = text.strip().lower()
    if value in ("0", "standard", "standart"):
        return STANDARD
    if value in ("2", "athletic", "atletik"):
        return ATHLETIC
    raise argparse.ArgumentTypeError(_("use standard or athletic"))


def _birth(text: str):
    try:
        return parse_date(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _client_line(c: Client) -> str:
    gender = describe("GE").display(c.gender) if c.gender else "-"
    birth = c.birth_date.isoformat() if c.birth_date else "-"
    age = c.age_at()
    height = f"{c.height:g}" if c.height else "-"
    return (f"{c.number:>8}  {c.name:<28}  {gender:<7}  {birth:<10} "
            f"{'' if age is None else age:>4}  {height:>6}  {c.note}")


def cmd_client_list(args) -> int:
    with Store(args.database) as store:
        clients = store.clients(args.search or "")
    if not clients:
        print(_("No client found."))
        return 0
    print(f"{_('Number'):>8}  {_('Name'):<28}  {_('Gender'):<7}  {_('Born'):<10} "
          f"{_('Age'):>4}  {_('Height'):>6}  {_('Note')}")
    for c in clients:
        print(_client_line(c))
    return 0


def cmd_client_save(args) -> int:
    with Store(args.database) as store:
        old = store.client(args.number)
        try:
            if args.client_command == "add":
                if old:
                    raise ValueError(_("Client number {number} is already used.").format(
                        number=old.number))
                client = Client(args.number, args.name or "", args.gender, args.birth,
                                args.height, args.body_type or STANDARD, args.note or "")
            else:
                if old is None:
                    raise LookupError(_("No client with number {number}.").format(
                        number=args.number))
                changes = {key: value for key, value in (
                    ("number", args.new_number), ("name", args.name), ("gender", args.gender),
                    ("birth_date", args.birth), ("height", args.height),
                    ("body_type", args.body_type), ("note", args.note)) if value is not None}
                client = old.with_changes(**changes)
            store.save_client(client, replace_number=old.number if old else None)
        except (ValueError, LookupError) as exc:
            raise SystemExit(str(exc)) from exc
    print(_("Client saved:"))
    print(_client_line(client))
    return 0


def cmd_client_delete(args) -> int:
    with Store(args.database) as store:
        client = store.client(args.number)
        if client is None:
            raise SystemExit(_("No client with number {number}.").format(number=args.number))
        deleted = store.delete_client(client.number, with_measurements=args.with_measurements)
    print(_("Client {number} deleted.").format(number=client.number))
    if args.with_measurements:
        print(ngettext("{n} measurement deleted.", "{n} measurements deleted.",
                       deleted).format(n=deleted))
    return 0


def cmd_assign(args) -> int:
    if args.none:
        args.client = None
    with Store(args.database) as store:
        if args.client is not None and store.client(args.client) is None:
            raise SystemExit(_("No client with number {number}. Add it first: "
                               "tartim client add {number} --name \"...\"").format(
                number=args.client))
        try:
            store.assign(args.record, args.client)
        except LookupError as exc:
            raise SystemExit(str(exc)) from exc
    if args.client is None:
        print(_("Measurement {record} is no longer linked to a client.").format(
            record=args.record))
    else:
        print(_("Measurement {record} assigned to client {number}.").format(
            record=args.record, number=args.client))
    return 0


def cmd_simulate(args) -> int:
    from .simulator import synthetic_record  # noqa: PLC0415

    port = _open(args)
    rng = random.Random(args.seed)
    try:
        for i in range(args.count):
            port.write(synthetic_record(subject=i + 1, rng=rng, model=args.model).encode("ascii"))
            port.flush()
            print(_("Synthetic measurement {i}/{count} sent.").format(i=i + 1, count=args.count),
                  file=sys.stderr)
            if i + 1 < args.count:
                time.sleep(args.interval)
    finally:
        port.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tartim", description=_("Body composition analyzer reader"))
    p.add_argument("--version", "--surum", action="version", version=f"tartim {__version__}")
    p.add_argument("--database", "--veritabani",
                   help=_("SQLite file (default: ~/.local/share/tartim/tartim.db)"))
    sub = p.add_subparsers(dest="command", required=True, metavar=_("COMMAND"))

    s = sub.add_parser("ports", aliases=["portlar"], help=_("List serial ports"))
    s.set_defaults(func=cmd_ports)

    s = sub.add_parser("listen", aliases=["dinle"],
                       help=_("Listen to the device, show and save measurements"))
    _port_args(s)
    s.add_argument("--no-save", "--kaydetme", action="store_true",
                   help=_("Do not write to the database"))
    s.add_argument("--raw-file", "--ham-dosya", help=_("Also append the raw bytes to this file"))
    s.add_argument("--count", "--adet", type=int, help=_("Quit after this many records"))
    s.set_defaults(func=cmd_listen)

    s = sub.add_parser("raw", aliases=["ham"], help=_("Record raw data for protocol discovery"))
    _port_args(s)
    s.add_argument("--output", "--cikti", help=_("Output file (default: screen)"))
    s.set_defaults(func=cmd_raw)

    s = sub.add_parser("import", aliases=["ice-aktar"], help=_("Import SD card CSV files"))
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("list", aliases=["listele"], help=_("List saved measurements"))
    s.add_argument("--last", "--son", type=int, default=20)
    s.add_argument("--client", "--danisan", help=_("Client number"))
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("export", aliases=["disa-aktar"],
                       help=_("Export measurements as CSV (opens in Excel)"))
    s.add_argument("--output", "--cikti", required=True)
    s.add_argument("--client", "--danisan")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("bluetooth", help=_("List nearby Bluetooth devices"))
    s.add_argument("--timeout", "--sure", type=float, default=10, help=_("Scan time, seconds"))
    s.set_defaults(func=cmd_bluetooth)

    s = sub.add_parser("gui", aliases=["arayuz"], help=_("Open the desktop interface"))
    s.add_argument("--port", help=_("Port selected at start-up"))
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("report", aliases=["rapor"],
                       help=_("Prepare a device report for the developers"))
    s.add_argument("--port", help=_("Found automatically if not given"))
    s.add_argument("--baud", type=int, help=_("default: {value}").format(value=9600))
    s.add_argument("--timeout", "--sure", type=float, default=180,
                   help=_("How long to wait for a measurement, seconds"))
    s.add_argument("--output", "--cikti",
                   help=_("Report file (default: tartim-report-MODEL-DATE.json)"))
    s.add_argument("--file", "--dosya", nargs="+", help=_("Use SD card files instead of a port"))
    s.add_argument("--bluetooth", action="store_true", help=_("Find the scale over Bluetooth"))
    s.add_argument("--no-send", "--gonderme", action="store_true",
                   help=_("Only save the report, do not offer to send it"))
    s.add_argument("--detailed", "--ayrintili", action="store_true",
                   help=_("Ask more questions (device settings, all values on the display)"))
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("send-report", aliases=["rapor-gonder"],
                       help=_("Send a saved report to the project server"))
    s.add_argument("file")
    s.add_argument("--note", "--not", default="", help=_("Short note (optional)"))
    s.set_defaults(func=cmd_send_report)

    s = sub.add_parser("print", aliases=["yazdir"],
                       help=_("Create the result sheet (PDF) of a measurement"))
    s.add_argument("--record", "--kayit", type=int,
                   help=_("Record number (default: the latest measurement)"))
    s.add_argument("--client", "--danisan",
                   help=_("Client number (default: the client of the latest measurement)"))
    s.add_argument("--name", "--ad", default="",
                   help=_("Name to print on the sheet (default: from the client record)"))
    s.add_argument("--output", "--cikti", help=_("PDF file (default: result-CLIENT-DATE.pdf)"))
    s.set_defaults(func=cmd_print)

    s = sub.add_parser("client", aliases=["danisan"],
                       help=_("Client records (name, gender, birth date, height)"))
    csub = s.add_subparsers(dest="client_command", required=True, metavar=_("COMMAND"))
    c = csub.add_parser("list", aliases=["listele"], help=_("List clients"))
    c.add_argument("search", nargs="?", help=_("Part of a name or number"))
    c.set_defaults(func=cmd_client_list)
    for name, alias, text in (("add", "ekle", _("Add a client")),
                              ("edit", "duzenle", _("Change a client's details"))):
        c = csub.add_parser(name, aliases=[alias], help=text)
        c.add_argument("number", help=_("Client number, as entered on the device"))
        c.add_argument("--name", "--ad", required=name == "add", help=_("First and last name"))
        c.add_argument("--gender", "--cinsiyet", type=_gender, help=_("male or female"))
        c.add_argument("--birth", "--dogum", type=_birth,
                       help=_("Birth date, e.g. 1977-05-01 or 01.05.1977"))
        c.add_argument("--height", "--boy", type=float, help=_("Height in cm"))
        c.add_argument("--body-type", "--vucut-tipi", type=_body_type,
                       help=_("standard or athletic"))
        c.add_argument("--note", "--not", help=_("Short note (optional)"))
        if name == "edit":
            c.add_argument("--new-number", "--yeni-numara",
                           help=_("Change the client number (measurements follow)"))
        else:
            c.set_defaults(new_number=None)
        c.set_defaults(func=cmd_client_save, client_command=name)
    c = csub.add_parser("delete", aliases=["sil"], help=_("Delete a client record"))
    c.add_argument("number")
    c.add_argument("--with-measurements", "--olcumlerle", action="store_true",
                   help=_("Also delete the client's measurements"))
    c.set_defaults(func=cmd_client_delete)

    s = sub.add_parser("assign", aliases=["ata"],
                       help=_("Link a measurement to a client"))
    s.add_argument("--record", "--kayit", type=int, required=True, help=_("Record number"))
    group = s.add_mutually_exclusive_group(required=True)
    group.add_argument("--client", "--danisan", help=_("Client number"))
    group.add_argument("--none", "--hicbiri", action="store_true", help=_("Remove the link"))
    s.set_defaults(func=cmd_assign)

    s = sub.add_parser("simulate", aliases=["simule"],
                       help=_("Virtual scale: send synthetic measurements to a port"))
    _port_args(s)
    s.add_argument("--count", "--adet", type=int, default=3)
    s.add_argument("--interval", "--aralik", type=float, default=2.0, help=_("seconds"))
    s.add_argument("--model", default="MC-780")
    s.add_argument("--seed", "--tohum", type=int, help=_("For repeatable values"))
    s.set_defaults(func=cmd_simulate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
