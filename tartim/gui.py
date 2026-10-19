"""Desktop interface (GTK 3). Runs on the GNOME and XFCE desktops of Pardus.

Start with ``tartim-arayuz`` or ``tartim gui``.
"""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import datetime
from html import escape
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, serial_io  # noqa: E402
from .fields import describe  # noqa: E402
from .i18n import _, current_language, ngettext  # noqa: E402
from .protocol import Framer, Measurement, parse  # noqa: E402
from .report import (REPORT_FORM_URL, SCREEN_FIELDS, SEND_OPTIONS, build_entry,  # noqa: E402
                     capture, compare, new_report, port_details, report_server, save_report,
                     send_report)
from .storage import Store  # noqa: E402

APP_ID = "io.github.muratgursel.Tartim"
DOCS_URL = "https://github.com/muratGursel/tartim/blob/main/docs/"
BAUDS = ["9600", "4800", "19200", "38400"]
HIDDEN_CODES = {"CS", "MO", "ID", "St"}


def help_url() -> str:
    """The user guide in the interface language."""
    return DOCS_URL + ("KULLANIM.md" if current_language() == "tr" else "USER_GUIDE.md")


def _format(m: Measurement, code: str) -> str:
    return describe(code).display(m.values[code])


def _error_text(exc: BaseException) -> str:
    # open_port reports the explanation for the user with SystemExit.
    return str(exc) or exc.__class__.__name__


def _not_connected() -> str:
    return _("Not connected. Choose the port and press “Connect”.")


class Listener(threading.Thread):
    """Listens to a serial port in the background and passes records to the main thread."""

    def __init__(self, settings: serial_io.PortSettings, on_record, on_error):
        super().__init__(daemon=True)
        self.settings = settings
        self._on_record = on_record
        self._on_error = on_error
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

    def run(self) -> None:
        try:
            port = serial_io.open_port(self.settings, timeout=0.3)
        except BaseException as exc:  # noqa: BLE001
            GLib.idle_add(self._on_error, _error_text(exc))
            return
        framer = Framer()
        try:
            while not self._stopping.is_set():
                chunk = port.read(port.in_waiting or 1)
                if chunk:
                    for record in framer.feed(chunk):
                        GLib.idle_add(self._on_record, record)
        except Exception as exc:  # noqa: BLE001
            if not self._stopping.is_set():
                GLib.idle_add(self._on_error,
                              _("Connection lost: {error}").format(error=exc))
        finally:
            port.close()


class BleListener(threading.Thread):
    """Listens to a standard Bluetooth LE scale (Weight Scale / Body Composition)."""

    def __init__(self, device, on_record, on_error, on_connected):
        super().__init__(daemon=True)
        self.device = device
        self.settings = serial_io.PortSettings(device.port)
        self._on_record = on_record
        self._on_error = on_error
        self._on_connected = on_connected
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

    def run(self) -> None:
        from . import bluetooth  # noqa: PLC0415

        model = self.device.name or "Bluetooth"
        try:
            with bluetooth.BlueZ() as bz:
                bluetooth.listen_standard(
                    bz, self.device,
                    lambda values: GLib.idle_add(
                        self._on_record, bluetooth.record_from_values(model, values)),
                    stopping=self._stopping.is_set,
                    on_connected=lambda: GLib.idle_add(self._on_connected))
        except BaseException as exc:  # noqa: BLE001
            if not self._stopping.is_set():
                GLib.idle_add(self._on_error, _error_text(exc))


def scan_bluetooth_async(seconds: float, on_done, on_error) -> None:
    """Scans for Bluetooth devices in the background; reports to the main thread."""
    def work():
        from . import bluetooth  # noqa: PLC0415

        try:
            with bluetooth.BlueZ() as bz:
                devices = bluetooth.scan(bz, seconds)
        except BaseException as exc:  # noqa: BLE001
            GLib.idle_add(on_error, _error_text(exc))
        else:
            GLib.idle_add(on_done, devices)
    threading.Thread(target=work, daemon=True).start()


def _bt_label(device) -> str:
    return f"{device.port}  ({device.name or _('no name')}, {device.kind})"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, store: Store, port: str | None = None):
        super().__init__(application=app, title="Tartım")
        self.set_default_size(980, 620)
        self.set_icon_name(APP_ID)
        self.store = store
        self.listener: Listener | BleListener | None = None
        self.bt_devices: dict = {}
        self.connect("destroy", lambda *args: self.stop_listening())

        header = Gtk.HeaderBar(show_close_button=True, title="Tartım",
                               subtitle=_("Body composition analyzer reader"))
        report_button = Gtk.Button(label=_("Device report"))
        report_button.set_tooltip_text(_("Prepare a device report for the developers"))
        report_button.connect("clicked", self.on_report)
        header.pack_end(report_button)
        help_button = Gtk.Button(label=_("Help"))
        help_button.set_tooltip_text(_("Open the user guide"))
        help_button.connect("clicked", lambda *args: self.open_uri(help_url()))
        header.pack_end(help_button)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=12)
        self.add(root)
        root.pack_start(self._build_connection_bar(), False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True)
        paned.pack1(self._build_measurement_panel(), resize=True, shrink=False)
        paned.pack2(self._build_history_panel(), resize=True, shrink=False)
        paned.set_position(440)
        root.pack_start(paned, True, True, 0)

        self.refresh_ports(preferred=port)
        self.refresh_history()
        self.show_placeholder()

    # --- Widgets -----------------------------------------------------------

    def _build_connection_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=8)
        bar.pack_start(Gtk.Label(label=_("Port:")), False, False, 0)
        self.port_combo = Gtk.ComboBoxText.new_with_entry()
        self.port_combo.set_tooltip_text(_("The port the scale is connected to. You can type it "
                                           "if it is not in the list."))
        bar.pack_start(self.port_combo, True, True, 0)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text(_("Scan the ports again"))
        refresh.connect("clicked", lambda *args: self.refresh_ports())
        bar.pack_start(refresh, False, False, 0)

        self.bt_button = Gtk.Button.new_from_icon_name("bluetooth-active-symbolic",
                                                       Gtk.IconSize.BUTTON)
        self.bt_button.set_tooltip_text(_("Search for Bluetooth scales"))
        self.bt_button.connect("clicked", self.on_bt_scan)
        bar.pack_start(self.bt_button, False, False, 0)

        bar.pack_start(Gtk.Label(label=_("Speed:")), False, False, 0)
        self.baud_combo = Gtk.ComboBoxText()
        for baud in BAUDS:
            self.baud_combo.append_text(baud)
        self.baud_combo.set_active(0)
        self.baud_combo.set_tooltip_text(_("Baud rate. Leave it at 9600 if unsure."))
        bar.pack_start(self.baud_combo, False, False, 0)

        self.connect_button = Gtk.Button(label=_("Connect"))
        self.connect_button.get_style_context().add_class("suggested-action")
        self.connect_button.connect("clicked", self.on_connect_clicked)
        bar.pack_start(self.connect_button, False, False, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.pack_start(bar, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        outer.pack_start(self.status, False, False, 0)
        self.set_status(_not_connected())
        return outer

    def _build_measurement_panel(self) -> Gtk.Widget:
        frame = Gtk.Frame(label=" " + _("Last measurement") + " ")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        frame.add(box)
        self.headline = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.headline, False, False, 0)

        self.detail_model = Gtk.ListStore(str, str)
        view = Gtk.TreeView(model=self.detail_model, headers_visible=True)
        for i, title in enumerate((_("Measurement"), _("Value"))):
            renderer = Gtk.CellRendererText()
            if i == 1:
                renderer.set_property("xalign", 1.0)
            column = Gtk.TreeViewColumn(title, renderer, text=i)
            column.set_expand(i == 0)
            view.append_column(column)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        return frame

    def _build_history_panel(self) -> Gtk.Widget:
        frame = Gtk.Frame(label=" " + _("Saved measurements") + " ")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        frame.add(box)

        # No, time, model, client, weight, raw record (hidden)
        self.history_model = Gtk.ListStore(int, str, str, str, str, str)
        self.history_view = Gtk.TreeView(model=self.history_model)
        titles = (_("No"), _("Time"), _("Model"), _("Client"), _("Weight (kg)"))
        for i, title in enumerate(titles):
            renderer = Gtk.CellRendererText()
            if i in (0, 4):
                renderer.set_property("xalign", 1.0)
            column = Gtk.TreeViewColumn(title, renderer, text=i)
            column.set_sort_column_id(i)
            self.history_view.append_column(column)
        self.history_view.get_selection().connect("changed", self.on_history_selected)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(self.history_view)
        box.pack_start(scroll, True, True, 0)

        buttons = Gtk.Box(spacing=8)
        sd = Gtk.Button(label=_("Import from SD card…"))
        sd.connect("clicked", self.on_import)
        export = Gtk.Button(label=_("Export for Excel…"))
        export.set_tooltip_text(_("Write all measurements to a CSV file that Excel and "
                                  "LibreOffice can open"))
        export.connect("clicked", self.on_export)
        self.print_button = Gtk.Button(label=_("Result sheet (PDF)…"))
        self.print_button.set_tooltip_text(_("Create a printable result sheet of the selected "
                                             "measurement (or the latest one)"))
        self.print_button.connect("clicked", self.on_print)
        buttons.pack_start(sd, False, False, 0)
        buttons.pack_end(export, False, False, 0)
        buttons.pack_end(self.print_button, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        return frame

    # --- Helpers -----------------------------------------------------------

    def set_status(self, text: str) -> None:
        self.status.set_text(text)

    def selected_port(self) -> str:
        text = self.port_combo.get_child().get_text().strip()
        return text.split()[0] if text else ""

    def selected_baud(self) -> int:
        return int(self.baud_combo.get_active_text() or 9600)

    def refresh_ports(self, preferred: str | None = None) -> None:
        current = preferred or self.selected_port()
        self.port_combo.remove_all()
        try:
            ports = serial_io.list_ports()
        except SystemExit as exc:
            self.set_status(str(exc))
            ports = []
        # USB-serial adapters first; scales are usually connected with one.
        ports.sort(key=lambda p: (not ("ttyUSB" in p[0] or "ttyACM" in p[0]), p[0]))
        for device, _desc in ports:
            self.port_combo.append(device, device)
        if current:
            self.port_combo.get_child().set_text(current)
        elif ports:
            self.port_combo.set_active(0)

    def refresh_history(self) -> None:
        self.history_model.clear()
        for row in self.store.list(limit=500):
            when = (row["measured_at"] or row["received_at"]).replace("T", " ")[:16]
            weight = f"{row['weight']:.1f}" if row["weight"] is not None else "-"
            self.history_model.append([row["id"], when, row["model"] or "-",
                                       row["subject_id"] or "-", weight, row["raw"]])

    def show_placeholder(self) -> None:
        self.headline.set_markup(
            f"<span size='large'>{escape(_('No measurements yet.'))}</span>\n" +
            escape(_("Connect to the scale and take a measurement on the device; the result "
                     "appears here.")))
        self.detail_model.clear()

    def show_measurement(self, m: Measurement, note: str = "") -> None:
        self.detail_model.clear()
        if not m.recognized:
            self.headline.set_markup(
                f"<span size='x-large' weight='bold'>{escape(_('Unrecognized record'))}</span>\n"
                + escape(_("We do not know this device's format yet. If you prepare a report "
                           "with the “Device report” button and send it, we can add support.")))
            self.detail_model.append([_("Raw data"), m.raw[:200]])
            return
        weight = f"{m.weight:.1f} kg" if m.weight is not None else "-"
        client = _("Client {number}").format(number=m.subject_id) if m.subject_id else ""
        info = " · ".join(filter(None, [m.model, client, note]))
        self.headline.set_markup(f"<span size='xx-large' weight='bold'>{escape(weight)}</span>\n"
                                 f"{escape(info)}")
        for code in m.values:
            if code not in HIDDEN_CODES and code != "Wk":
                self.detail_model.append([describe(code).name, _format(m, code)])

    def open_uri(self, uri: str) -> None:
        try:
            Gtk.show_uri_on_window(self, uri, Gdk.CURRENT_TIME)
        except GLib.Error as exc:
            self.show_message(Gtk.MessageType.ERROR, _("Could not open"), f"{uri}\n{exc.message}")

    def show_message(self, kind: Gtk.MessageType, title: str, text: str) -> None:
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=kind,
                                   buttons=Gtk.ButtonsType.OK, text=title)
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    # --- Connection ---------------------------------------------------------

    def start_listening(self) -> bool:
        port = self.selected_port()
        if not port:
            self.show_message(Gtk.MessageType.WARNING, _("No port selected"),
                              _("Choose the port the scale is connected to. If the list is "
                                "empty, plug in the cable and press the refresh button."))
            return False
        device = self.bt_device_for(port)
        if device is not None and not device.classic_serial:
            name = device.name or port
            self.listener = BleListener(
                device, self.on_record, self.on_listen_error,
                lambda: self.set_status(_("{name} connected. Take a measurement on the device.")
                                        .format(name=name)))
            status = _("Connecting to {name} over Bluetooth...").format(name=name)
        else:
            self.listener = Listener(serial_io.PortSettings(port, self.selected_baud()),
                                     self.on_record, self.on_listen_error)
            status = _("Listening on {port}. Take a measurement on the device.").format(port=port)
        self.listener.start()
        self.connect_button.set_label(_("Disconnect"))
        ctx = self.connect_button.get_style_context()
        ctx.remove_class("suggested-action")
        ctx.add_class("destructive-action")
        self.port_combo.set_sensitive(False)
        self.baud_combo.set_sensitive(False)
        self.bt_button.set_sensitive(False)
        self.set_status(status)
        return True

    def bt_device_for(self, port: str):
        if not port.lower().startswith("bt:"):
            return None
        from .bluetooth import parse_bt_port  # noqa: PLC0415

        return self.bt_devices.get(parse_bt_port(port)[0])

    def on_bt_scan(self, *args):
        self.bt_button.set_sensitive(False)
        self.set_status(_("Searching for Bluetooth devices (10 s)... Make sure the scale is on."))
        scan_bluetooth_async(10, self._bt_scanned, self._bt_failed)

    def _bt_scanned(self, devices) -> bool:
        self.bt_button.set_sensitive(self.listener is None)
        # Found devices go to the top of the list, strongest signal first.
        for device in reversed(devices):
            if device.address not in self.bt_devices:
                self.port_combo.prepend(device.port, _bt_label(device))
            self.bt_devices[device.address] = device
        if devices:
            self.port_combo.get_child().set_text(_bt_label(devices[0]))
            self.set_status(ngettext(
                "{n} Bluetooth device found. Choose your scale in the list and press “Connect”.",
                "{n} Bluetooth devices found. Choose your scale in the list and press “Connect”.",
                len(devices)).format(n=len(devices)))
        else:
            self.set_status(_("No Bluetooth device found. Turn the scale on and try again."))
        return False

    def _bt_failed(self, message: str) -> bool:
        self.bt_button.set_sensitive(self.listener is None)
        self.set_status(_("The Bluetooth scan failed."))
        self.show_message(Gtk.MessageType.ERROR, "Bluetooth", message)
        return False

    def stop_listening(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=2)
            self.listener = None
        self.connect_button.set_label(_("Connect"))
        ctx = self.connect_button.get_style_context()
        ctx.remove_class("destructive-action")
        ctx.add_class("suggested-action")
        self.port_combo.set_sensitive(True)
        self.baud_combo.set_sensitive(True)
        self.bt_button.set_sensitive(True)

    def on_connect_clicked(self, *args):
        if self.listener:
            self.stop_listening()
            self.set_status(_("Disconnected."))
        else:
            self.start_listening()

    def on_record(self, record: str) -> bool:
        m = parse(record)
        port = self.listener.settings.port if self.listener else "?"
        self.store.add(m, source=f"serial:{port}")
        self.show_measurement(m)
        self.refresh_history()
        self.set_status(_("Listening on {port}. Last measurement received at {time}.").format(
            port=port, time=f"{datetime.now():%H:%M:%S}"))
        return False

    def on_listen_error(self, message: str) -> bool:
        self.stop_listening()
        self.set_status(_("Not connected."))
        self.show_message(Gtk.MessageType.ERROR, _("Could not connect to the scale"), message)
        return False

    # --- History, import and export ----------------------------------------

    def on_history_selected(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        if it is not None:
            self.show_measurement(parse(model[it][5]),
                                  note=_("record {number}").format(number=model[it][0]))

    def _file_dialog(self, title: str, action: Gtk.FileChooserAction, button: str):
        return Gtk.FileChooserNative(title=title, transient_for=self, action=action,
                                     accept_label=button, cancel_label=_("Cancel"))

    def on_import(self, *args):
        dialog = self._file_dialog(_("Choose the SD card files"), Gtk.FileChooserAction.OPEN,
                                   _("Import"))
        dialog.set_select_multiple(True)
        csv_filter = Gtk.FileFilter()
        csv_filter.set_name(_("Scale files (CSV)"))
        csv_filter.add_pattern("*.csv")
        csv_filter.add_pattern("*.CSV")
        dialog.add_filter(csv_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name(_("All files"))
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            paths = [f.get_path() for f in dialog.get_files()]
            try:
                added, skipped, unknown = self.store.import_files(paths)
            except OSError as exc:
                self.show_message(Gtk.MessageType.ERROR, _("Could not read the file"), str(exc))
            else:
                self.refresh_history()
                self.show_message(Gtk.MessageType.INFO, _("Import finished"), ", ".join([
                    ngettext("{n} measurement added", "{n} measurements added",
                             added).format(n=added),
                    ngettext("{n} was already saved", "{n} were already saved",
                             skipped).format(n=skipped),
                    ngettext("{n} record not recognized", "{n} records not recognized",
                             unknown).format(n=unknown)]) + ".")
        dialog.destroy()

    def selected_record(self) -> int | None:
        model, it = self.history_view.get_selection().get_selected()
        return model[it][0] if it is not None else None

    def ask_client_name(self) -> str | None:
        """Asks for the name to print on the sheet; None if cancelled. Not saved."""
        dialog = Gtk.Dialog(title=_("Result sheet"), transient_for=self, modal=True)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL,
                           _("Create PDF"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.add(Gtk.Label(label=_("Client name to print on the sheet (optional). It is only "
                                  "printed, not saved."), xalign=0, wrap=True,
                          max_width_chars=50))
        entry = Gtk.Entry(activates_default=True)
        box.add(entry)
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        return name if response == Gtk.ResponseType.OK else None

    def on_print(self, *args):
        from . import printout  # noqa: PLC0415

        try:
            current, history = printout.entries(self.store, record_id=self.selected_record())
        except LookupError as exc:
            self.show_message(Gtk.MessageType.INFO, _("Result sheet"), str(exc))
            return
        name = self.ask_client_name()
        if name is None:
            return
        dialog = self._file_dialog(_("Save the result sheet"), Gtk.FileChooserAction.SAVE,
                                   _("Save"))
        dialog.set_do_overwrite_confirmation(True)
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        if docs and Path(docs).is_dir():
            dialog.set_current_folder(docs)
        dialog.set_current_name(printout.default_name(current))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            try:
                path = printout.write_pdf(dialog.get_filename(), current, history,
                                          client_name=name)
            except (RuntimeError, OSError) as exc:
                self.show_message(Gtk.MessageType.ERROR, _("Could not create the result sheet"),
                                  str(exc))
            else:
                self.set_status(_("Result sheet written: {path}").format(path=path))
                self.open_uri(path.resolve().as_uri())
        dialog.destroy()

    def on_export(self, *args):
        dialog = self._file_dialog(_("Export measurements"), Gtk.FileChooserAction.SAVE,
                                   _("Save"))
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(_("measurements") + f"-{datetime.now():%Y%m%d}.csv")
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_filename()
            try:
                count = self.store.export_csv(path)
            except OSError as exc:
                self.show_message(Gtk.MessageType.ERROR, _("Could not write the file"), str(exc))
            else:
                self.show_message(Gtk.MessageType.INFO, _("Exported"), ngettext(
                    "{n} measurement written to {path}.", "{n} measurements written to {path}.",
                    count).format(n=count, path=path))
        dialog.destroy()

    def on_report(self, *args):
        was_listening = self.listener is not None
        if was_listening:
            self.stop_listening()
            self.set_status(_("Preparing a device report; listening continues afterwards."))
        dialog = ReportDialog(self, self.selected_port(), self.selected_baud(),
                              self.bt_device_for(self.selected_port()))
        dialog.run()
        dialog.close_dialog()
        if was_listening:
            self.start_listening()
        else:
            self.set_status(_not_connected())


class ReportDialog(Gtk.Dialog):
    """Device report in a few steps: model → measurement → weight on the display → send."""

    def __init__(self, parent: MainWindow, port: str, baud: int, bt_device=None):
        super().__init__(title=_("Device report"), transient_for=parent, modal=True)
        self.set_default_size(520, 360)
        self.parent_window = parent
        self.port, self.baud = port, baud
        self.bt_device = bt_device
        self.bt_devices: list = []
        self.entry: dict | None = None
        self.target: dict | None = None
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT,
                               margin=18, vexpand=True)
        self.get_content_area().add(self.stack)
        self.stack.add_named(self._page_start(), "start")
        self.stack.add_named(self._page_bluetooth(), "bluetooth")
        self.stack.add_named(self._page_wait(), "wait")
        self.stack.add_named(self._page_weight(), "weight")
        self.stack.add_named(self._page_done(), "done")
        self.show_all()

    def _page(self, title: str, text: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        heading = Gtk.Label(xalign=0)
        heading.set_markup(f"<span size='large' weight='bold'>{escape(title)}</span>")
        box.pack_start(heading, False, False, 0)
        body = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=60)
        box.pack_start(body, False, False, 0)
        return box

    def _page_start(self) -> Gtk.Widget:
        box = self._page(
            _("Tell us about your device"),
            _("This report helps us learn your device's data format. The client number is "
              "removed before the report is written. Measure yourself or a test person."))
        self.model_entry = Gtk.Entry(placeholder_text=_("Device model, e.g. MC-780MA"))
        self.model_entry.set_tooltip_text(_("Printed on the label under the device"))
        self.model_entry.connect("changed", lambda e: self.start_button.set_sensitive(
            bool(e.get_text().strip())))
        box.pack_start(self.model_entry, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.start_button = Gtk.Button(label=_("Start measurement"), sensitive=False)
        self.start_button.get_style_context().add_class("suggested-action")
        self.start_button.connect("clicked", self.on_start)
        sd = Gtk.Button(label=_("From an SD card file…"))
        sd.connect("clicked", self.on_sd_file)
        self.bt_start = Gtk.Button(label=_("With Bluetooth…"), sensitive=False)
        self.bt_start.connect("clicked", self.on_bluetooth)
        self.model_entry.connect("changed", lambda e: self.bt_start.set_sensitive(
            bool(e.get_text().strip())))
        buttons.pack_end(self.start_button, False, False, 0)
        buttons.pack_end(self.bt_start, False, False, 0)
        buttons.pack_end(sd, False, False, 0)
        box.pack_end(buttons, False, False, 0)
        box.pack_end(Gtk.Label(label=_("Port: {port} · Speed: {baud}").format(
            port=self.port or _("not selected"), baud=self.baud), xalign=0), False, False, 0)
        return box

    def _page_bluetooth(self) -> Gtk.Widget:
        box = self._page(_("Choose the Bluetooth device"),
                         _("Turn the scale on. Searching for nearby devices; choose your scale "
                           "in the list."))
        self.bt_spinner = Gtk.Spinner()
        box.pack_start(self.bt_spinner, False, False, 0)
        self.bt_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.bt_list.connect("row-selected", lambda _list, row: self.bt_choose.set_sensitive(
            row is not None and row.get_index() < len(self.bt_devices)))
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(self.bt_list)
        box.pack_start(scroll, True, True, 0)
        row = Gtk.Box(spacing=8)
        back = Gtk.Button(label=_("Back"))
        back.connect("clicked", lambda *args: self.stack.set_visible_child_name("start"))
        again = Gtk.Button(label=_("Search again"))
        again.connect("clicked", lambda *args: self._bt_rescan())
        self.bt_choose = Gtk.Button(label=_("Choose and start measuring"), sensitive=False)
        self.bt_choose.get_style_context().add_class("suggested-action")
        self.bt_choose.connect("clicked", self.on_bt_chosen)
        row.pack_start(back, False, False, 0)
        row.pack_end(self.bt_choose, False, False, 0)
        row.pack_end(again, False, False, 0)
        box.pack_end(row, False, False, 0)
        return box

    def _page_wait(self) -> Gtk.Widget:
        box = self._page(_("Take a measurement on the device now"),
                         _("Step on the scale and complete the measurement. When data arrives "
                           "the next step opens automatically (waiting up to 3 minutes)."))
        spinner = Gtk.Spinner(active=True)
        spinner.set_size_request(48, 48)
        box.pack_start(spinner, True, True, 0)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *args: self.cancel.set())
        box.pack_end(cancel, False, False, 0)
        return box

    def _page_weight(self) -> Gtk.Widget:
        box = self._page(_("Weight on the display"), "")
        self.weight_info = box.get_children()[1]
        self.weight_entry = Gtk.Entry(
            placeholder_text=_("Weight shown on the display, e.g. 72.4 (optional)"))
        self.weight_entry.connect("activate", self.on_save)
        box.pack_start(self.weight_entry, False, False, 0)
        save = Gtk.Button(label=_("Save report"))
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self.on_save)
        row = Gtk.Box()
        row.pack_end(save, False, False, 0)
        box.pack_end(row, False, False, 0)
        return box

    def _page_done(self) -> Gtk.Widget:
        box = self._page(_("Report ready"), "")
        self.done_info = box.get_children()[1]

        question = Gtk.Label(xalign=0)
        question.set_markup(f"<b>{escape(_('How would you like to send the report?'))}</b>")
        box.pack_start(question, False, False, 0)
        # The consent box and note of the server option sit right below that option.
        self.server_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                                  margin_start=24, margin_bottom=4)
        self.consent = Gtk.CheckButton(label=_("This measurement does not belong to a real "
                                               "client"))
        self.consent.set_tooltip_text(_("Tick this if you measured yourself or a test person"))
        self.consent.connect("toggled", lambda *args: self._update_send_ui())
        self.note_entry = Gtk.Entry(placeholder_text=_("Short note (optional)"))
        self.server_box.pack_start(self.consent, False, False, 0)
        self.server_box.pack_start(self.note_entry, False, False, 0)

        self.send_choices: dict[str, Gtk.RadioButton] = {}
        group = None
        for label, key in SEND_OPTIONS:
            if key == "server" and not report_server():
                continue  # the organisation disabled sending to a server
            radio = Gtk.RadioButton.new_with_label_from_widget(group, _(label))
            group = group or radio
            radio.connect("toggled", lambda *args: self._update_send_ui())
            self.send_choices[key] = radio
            box.pack_start(radio, False, False, 0)
            if key == "server":
                box.pack_start(self.server_box, False, False, 0)
        self.send_status = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        box.pack_start(self.send_status, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.action = Gtk.Button()
        self.action.get_style_context().add_class("suggested-action")
        self.action.connect("clicked", self.on_send_action)
        folder = Gtk.Button(label=_("Open folder"))
        folder.connect("clicked", lambda *args: self._open_uri(self.saved.parent.as_uri()))
        close = Gtk.Button(label=_("Close"))
        close.connect("clicked", lambda *args: self.response(Gtk.ResponseType.CLOSE))
        buttons.pack_end(self.action, False, False, 0)
        buttons.pack_end(folder, False, False, 0)
        buttons.pack_start(close, False, False, 0)
        box.pack_end(buttons, False, False, 0)
        self._update_send_ui()
        return box

    def _send_choice(self) -> str:
        return next(key for key, radio in self.send_choices.items() if radio.get_active())

    def _update_send_ui(self) -> None:
        choice = self._send_choice()
        self.server_box.set_visible(choice == "server")
        self.server_box.set_no_show_all(choice != "server")
        self.action.set_label({"server": _("Send"), "github": _("Open the GitHub form"),
                               "later": _("OK")}[choice])
        self.action.set_sensitive(choice != "server" or self.consent.get_active())

    def on_send_action(self, *args):
        choice = self._send_choice()
        if choice == "github":
            self._open_uri(REPORT_FORM_URL)
            self.send_status.set_text(_("In the form, type the device model and drag the report "
                                        "file into the “Report file” box."))
        elif choice == "later":
            self.response(Gtk.ResponseType.CLOSE)
        else:
            self.action.set_sensitive(False)
            self.send_status.set_text(_("Sending..."))
            note = self.note_entry.get_text().strip()
            threading.Thread(target=self._send_to_server, args=(note,), daemon=True).start()

    def _send_to_server(self, note: str) -> None:
        try:
            result = send_report(self.report, note=note)
        except RuntimeError as exc:
            GLib.idle_add(self._sent, None, str(exc))
        else:
            GLib.idle_add(self._sent, result.get("id"), None)

    def _sent(self, report_id, error) -> bool:
        if error:
            self.send_status.set_markup(f"<b>{escape(_('Could not send:'))}</b> {escape(error)}")
            self._update_send_ui()
        else:
            self.send_status.set_markup(
                f"<b>{escape(_('Sent, thank you!'))}</b> " +
                escape(_("Your report number: {id}").format(id=report_id)))
            for radio in self.send_choices.values():
                radio.set_sensitive(False)
            self.server_box.set_sensitive(False)
            self.action.set_label(_("OK"))
            self.action.set_sensitive(True)
            self.send_choices["later"].set_active(True)
        return False

    # --- Flow --------------------------------------------------------------

    def device(self) -> dict:
        return {"brand": "Tanita", "model": self.model_entry.get_text().strip()}

    def on_bluetooth(self, *args):
        self.stack.set_visible_child_name("bluetooth")
        self._bt_rescan()

    def _bt_rescan(self) -> None:
        for child in self.bt_list.get_children():
            self.bt_list.remove(child)
        self.bt_devices = []
        self.bt_spinner.start()
        self.bt_choose.set_sensitive(False)
        scan_bluetooth_async(10, self._bt_listed, self._bt_list_failed)

    def _bt_listed(self, devices) -> bool:
        self.bt_spinner.stop()
        self.bt_devices = devices
        for device in devices:
            label = Gtk.Label(xalign=0, margin=8)
            rssi = f" · {device.rssi} dBm" if device.rssi is not None else ""
            label.set_markup(f"<b>{escape(device.name or _('Unnamed device'))}</b>\n"
                             f"<small>{escape(device.kind)}{rssi}</small>")
            self.bt_list.add(label)
        if not devices:
            self.bt_list.add(Gtk.Label(
                label=_("No device found. Turn the scale on and press “Search again”."),
                margin=12))
        self.bt_list.show_all()
        return False

    def _bt_list_failed(self, message: str) -> bool:
        self.bt_spinner.stop()
        self.stack.set_visible_child_name("start")
        self.parent_window.show_message(Gtk.MessageType.ERROR, "Bluetooth", message)
        return False

    def on_bt_chosen(self, *args):
        row = self.bt_list.get_selected_row()
        if row is None or row.get_index() >= len(self.bt_devices):
            return
        self.bt_device = self.bt_devices[row.get_index()]
        self.parent_window.bt_devices[self.bt_device.address] = self.bt_device
        self.port = self.bt_device.port
        self.on_start()

    def _capture_ble(self) -> None:
        from . import bluetooth  # noqa: PLC0415
        from .report import ble_entry  # noqa: PLC0415

        try:
            with bluetooth.BlueZ() as bz:
                result = bluetooth.capture_ble(bz, self.bt_device, timeout=180,
                                               cancelled=self.cancel.is_set)
        except BaseException as exc:  # noqa: BLE001
            GLib.idle_add(self._capture_failed, _error_text(exc))
            return
        entry, target = ble_entry(self.bt_device, result)
        count = len(result["notifications"])
        received = ngettext("{n} Bluetooth notification received from the device.",
                            "{n} Bluetooth notifications received from the device.",
                            count).format(n=count) if count else None
        GLib.idle_add(self._show_weight_page, entry, target, received)

    def on_start(self, *args):
        if not self.port:
            self.parent_window.show_message(Gtk.MessageType.WARNING, _("No port selected"),
                                            _("Choose the scale's port in the main window."))
            return
        ble = self.bt_device is not None and not self.bt_device.classic_serial
        connection = f"bluetooth ({self.bt_device.kind_code})" if self.bt_device \
            else "serial-port"
        self.report = new_report({**self.device(), "connection": connection}, "gui")
        self.report["port"] = port_details(self.port) if self.bt_device else {
            **port_details(self.port), "baudrate": self.baud, "bytesize": 8, "parity": "N",
            "stopbits": 1}
        self.stack.set_visible_child_name("wait")
        self.thread = threading.Thread(target=self._capture_ble if ble else self._capture,
                                       daemon=True)
        self.thread.start()

    def _capture(self) -> None:
        try:
            port = serial_io.open_port(serial_io.PortSettings(self.port, self.baud))
        except BaseException as exc:  # noqa: BLE001
            GLib.idle_add(self._capture_failed, _error_text(exc))
            return
        try:
            data, timing = capture(port, timeout=180, cancelled=self.cancel.is_set)
        finally:
            port.close()
        GLib.idle_add(self._captured, data, timing, f"serial:{self.port}")

    def _capture_failed(self, message: str) -> bool:
        self.stack.set_visible_child_name("start")
        self.parent_window.show_message(Gtk.MessageType.ERROR, _("Could not connect to the scale"),
                                        message)
        return False

    def _captured(self, data: bytes, timing: list, source: str) -> bool:
        entry, target = build_entry(data, timing, source)
        received = ngettext("{n} byte of data received from the device.",
                            "{n} bytes of data received from the device.",
                            len(data)).format(n=len(data)) if data else None
        return self._show_weight_page(entry, target, received)

    def _show_weight_page(self, entry: dict, target, received: str | None) -> bool:
        if self.cancel.is_set():
            self.cancel.clear()
            self.stack.set_visible_child_name("start")
            return False
        self.entry, self.target = entry, target
        if received:
            self.weight_info.set_text(received + " " + _(
                "If you type the weight shown on the device display, verifying the data is "
                "much easier."))
        else:
            self.weight_info.set_text(_(
                "No data arrived from the device. You can still send the report; the device "
                "structure has been added to it. For wired devices check the cable and the "
                "speed setting; Bluetooth devices may wait for a command from the vendor's app "
                "before sending data."))
        self.stack.set_visible_child_name("weight")
        self.weight_entry.grab_focus()
        return False

    def on_sd_file(self, *args):
        if not self.model_entry.get_text().strip():
            self.model_entry.grab_focus()
            return
        dialog = Gtk.FileChooserNative(title=_("Choose the SD card file"), transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN,
                                       accept_label=_("Choose"), cancel_label=_("Cancel"))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = Path(dialog.get_filename())
            try:
                data = path.read_bytes()[:256 * 1024]
            except OSError as exc:
                self.parent_window.show_message(Gtk.MessageType.ERROR,
                                                _("Could not read the file"), str(exc))
            else:
                self.report = new_report({**self.device(), "connection": "sd-card-file"}, "gui")
                self._captured(data, [], f"file:{path.name}")
        dialog.destroy()

    def on_save(self, *args):
        text = self.weight_entry.get_text().strip().replace(",", ".")
        if text and self.target is not None:
            try:
                value = float(text)
            except ValueError:
                self.weight_entry.grab_focus()
                return
            label, code = SCREEN_FIELDS[0]
            self.entry["screen"].append(compare(self.target, label, code, value))
        self.report["measurements"].append(self.entry)
        docs = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        directory = Path(docs) if docs and Path(docs).is_dir() else Path.home()
        try:
            self.saved = save_report(self.report, directory=directory)
        except OSError as exc:
            self.parent_window.show_message(Gtk.MessageType.ERROR,
                                            _("Could not save the report"), str(exc))
            return
        self.done_info.set_text(_("The report was saved to:") + f"\n{self.saved}")
        self.stack.set_visible_child_name("done")
        self._update_send_ui()

    def _open_uri(self, uri: str) -> None:
        try:
            Gtk.show_uri_on_window(self, uri, Gdk.CURRENT_TIME)
        except GLib.Error as exc:
            self.parent_window.show_message(Gtk.MessageType.ERROR, _("Could not open"),
                                            exc.message)

    def close_dialog(self) -> None:
        self.cancel.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tartim-arayuz", description=_("Tartım desktop interface"))
    parser.add_argument("--port", help=_("Port selected at start-up"))
    parser.add_argument("--database", "--veritabani", help=_("SQLite file"))
    parser.add_argument("--version", "--surum", action="version", version=f"tartim {__version__}")
    args = parser.parse_args(argv)

    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
    store = Store(args.database)

    def on_activate(application: Gtk.Application) -> None:
        window = application.get_active_window()
        if window is None:
            window = MainWindow(application, store, args.port)
            window.show_all()
        window.present()

    app.connect("activate", on_activate)
    try:
        return app.run([sys.argv[0]])
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
