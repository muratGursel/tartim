"""Masaüstü arayüzü (GTK 3). Pardus'un GNOME ve XFCE masaüstlerinde çalışır.

Başlatmak için: ``tartim-arayuz`` ya da ``tartim arayuz``.
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
from .protocol import Framer, Measurement, parse  # noqa: E402
from .report import (REPORT_FORM_URL, SCREEN_FIELDS, build_entry, capture,  # noqa: E402
                     compare, new_report, port_details, save_report)
from .storage import Store  # noqa: E402

APP_ID = "io.github.muratgursel.Tartim"
BAUDS = ["9600", "4800", "19200", "38400"]
HIDDEN_CODES = {"CS", "MO", "ID", "St"}


def _format(m: Measurement, code: str) -> str:
    return describe(code).display(m.values[code])


def _error_text(exc: BaseException) -> str:
    # open_port, kullanıcıya gösterilecek açıklamayı SystemExit ile verir.
    return str(exc) or exc.__class__.__name__


class Listener(threading.Thread):
    """Seri portu arka planda dinler; kayıtları ana iş parçacığına iletir."""

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
                GLib.idle_add(self._on_error, f"Bağlantı koptu: {exc}")
        finally:
            port.close()


class BleListener(threading.Thread):
    """Standart Bluetooth LE tartıyı dinler (Weight Scale / Body Composition)."""

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

        model = self.device.name or "Bluetooth tartı"
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
    """Bluetooth taramasını arka planda yapar; sonucu ana iş parçacığına verir."""
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
    return f"{device.port}  ({device.name or 'adsız'}, {device.kind})"


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, store: Store, port: str | None = None):
        super().__init__(application=app, title="Tartım")
        self.set_default_size(980, 620)
        self.set_icon_name(APP_ID)
        self.store = store
        self.listener: Listener | BleListener | None = None
        self.bt_devices: dict = {}
        self.connect("destroy", lambda *_: self.stop_listening())

        header = Gtk.HeaderBar(show_close_button=True, title="Tartım",
                               subtitle="Vücut analizörü okuyucusu")
        report_button = Gtk.Button(label="Cihaz raporu")
        report_button.set_tooltip_text("Geliştiricilere gönderilecek cihaz raporunu hazırla")
        report_button.connect("clicked", self.on_report)
        header.pack_end(report_button)
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

    # --- Arayüz parçaları -------------------------------------------------

    def _build_connection_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=8)
        bar.pack_start(Gtk.Label(label="Port:"), False, False, 0)
        self.port_combo = Gtk.ComboBoxText.new_with_entry()
        self.port_combo.set_tooltip_text("Tartının bağlı olduğu port. Listede yoksa yazabilirsiniz.")
        bar.pack_start(self.port_combo, True, True, 0)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Portları yeniden tara")
        refresh.connect("clicked", lambda *_: self.refresh_ports())
        bar.pack_start(refresh, False, False, 0)

        self.bt_button = Gtk.Button.new_from_icon_name("bluetooth-active-symbolic",
                                                       Gtk.IconSize.BUTTON)
        self.bt_button.set_tooltip_text("Bluetooth tartıları ara")
        self.bt_button.connect("clicked", self.on_bt_scan)
        bar.pack_start(self.bt_button, False, False, 0)

        bar.pack_start(Gtk.Label(label="Hız:"), False, False, 0)
        self.baud_combo = Gtk.ComboBoxText()
        for baud in BAUDS:
            self.baud_combo.append_text(baud)
        self.baud_combo.set_active(0)
        self.baud_combo.set_tooltip_text("Baud hızı. Emin değilseniz 9600 bırakın.")
        bar.pack_start(self.baud_combo, False, False, 0)

        self.connect_button = Gtk.Button(label="Bağlan")
        self.connect_button.get_style_context().add_class("suggested-action")
        self.connect_button.connect("clicked", self.on_connect_clicked)
        bar.pack_start(self.connect_button, False, False, 0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.pack_start(bar, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        outer.pack_start(self.status, False, False, 0)
        self.set_status("Bağlı değil. Portu seçip “Bağlan”a basın.")
        return outer

    def _build_measurement_panel(self) -> Gtk.Widget:
        frame = Gtk.Frame(label=" Son ölçüm ")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        frame.add(box)
        self.headline = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.headline, False, False, 0)

        self.detail_model = Gtk.ListStore(str, str)
        view = Gtk.TreeView(model=self.detail_model, headers_visible=True)
        for i, title in enumerate(("Ölçüm", "Değer")):
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
        frame = Gtk.Frame(label=" Kayıtlı ölçümler ")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        frame.add(box)

        # No, zaman, model, danışan, kilo, ham kayıt (gizli)
        self.history_model = Gtk.ListStore(int, str, str, str, str, str)
        self.history_view = Gtk.TreeView(model=self.history_model)
        for i, title in enumerate(("No", "Zaman", "Model", "Danışan", "Kilo (kg)")):
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
        sd = Gtk.Button(label="SD karttan içe aktar…")
        sd.connect("clicked", self.on_import)
        export = Gtk.Button(label="Excel için dışa aktar…")
        export.set_tooltip_text("Tüm ölçümleri Excel / LibreOffice'in açabileceği CSV dosyasına yaz")
        export.connect("clicked", self.on_export)
        buttons.pack_start(sd, False, False, 0)
        buttons.pack_end(export, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        return frame

    # --- Yardımcılar -------------------------------------------------------

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
        # USB-seri çeviriciler önce gelsin; tartılar çoğunlukla bunlarla bağlanır.
        ports.sort(key=lambda p: (not ("ttyUSB" in p[0] or "ttyACM" in p[0]), p[0]))
        for device, desc in ports:
            label = device if not desc or desc == "n/a" else f"{device}"
            self.port_combo.append(device, label)
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
            "<span size='large'>Henüz ölçüm yok.</span>\n"
            "Tartıya bağlanın ve cihazda bir ölçüm yapın; sonuç burada görünür.")
        self.detail_model.clear()

    def show_measurement(self, m: Measurement, note: str = "") -> None:
        self.detail_model.clear()
        if not m.recognized:
            self.headline.set_markup(
                "<span size='x-large' weight='bold'>Tanınmayan kayıt</span>\n"
                "Bu cihazın biçimini henüz tanımıyoruz. “Cihaz raporu” düğmesiyle "
                "bir rapor hazırlayıp bize gönderirseniz destek ekleyebiliriz.")
            self.detail_model.append(["Ham veri", m.raw[:200]])
            return
        weight = f"{m.weight:.1f} kg" if m.weight is not None else "-"
        info = " · ".join(filter(None, [m.model, f"Danışan {m.subject_id}" if m.subject_id else "",
                                        note]))
        self.headline.set_markup(f"<span size='xx-large' weight='bold'>{escape(weight)}</span>\n"
                                 f"{escape(info)}")
        for code in m.values:
            if code not in HIDDEN_CODES and code != "Wk":
                self.detail_model.append([describe(code).label, _format(m, code)])

    def show_message(self, kind: Gtk.MessageType, title: str, text: str) -> None:
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=kind,
                                   buttons=Gtk.ButtonsType.OK, text=title)
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()

    # --- Bağlantı ----------------------------------------------------------

    def start_listening(self) -> bool:
        port = self.selected_port()
        if not port:
            self.show_message(Gtk.MessageType.WARNING, "Port seçilmedi",
                              "Tartının bağlı olduğu portu seçin. Liste boşsa kabloyu takıp "
                              "yenile düğmesine basın.")
            return False
        device = self.bt_device_for(port)
        if device is not None and not device.classic_serial:
            name = device.name or port
            self.listener = BleListener(
                device, self.on_record, self.on_listen_error,
                lambda: self.set_status(f"{name} bağlandı. Cihazda ölçüm yapın."))
            status = f"{name} cihazına Bluetooth ile bağlanılıyor..."
        else:
            self.listener = Listener(serial_io.PortSettings(port, self.selected_baud()),
                                     self.on_record, self.on_listen_error)
            status = f"{port} dinleniyor. Cihazda ölçüm yapın."
        self.listener.start()
        self.connect_button.set_label("Bağlantıyı kes")
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

    def on_bt_scan(self, *_):
        self.bt_button.set_sensitive(False)
        self.set_status("Bluetooth cihazları aranıyor (10 sn)... Tartının açık olduğundan emin olun.")
        scan_bluetooth_async(10, self._bt_scanned, self._bt_failed)

    def _bt_scanned(self, devices) -> bool:
        self.bt_button.set_sensitive(self.listener is None)
        for device in devices:
            if device.address not in self.bt_devices:
                self.port_combo.append(device.port, _bt_label(device))
            self.bt_devices[device.address] = device
        if devices:
            self.port_combo.get_child().set_text(_bt_label(devices[0]))
            self.set_status(f"{len(devices)} Bluetooth cihazı bulundu. Listeden tartınızı seçip "
                            "“Bağlan”a basın.")
        else:
            self.set_status("Bluetooth cihazı bulunamadı. Tartıyı açıp tekrar deneyin.")
        return False

    def _bt_failed(self, message: str) -> bool:
        self.bt_button.set_sensitive(self.listener is None)
        self.set_status("Bluetooth taraması yapılamadı.")
        self.show_message(Gtk.MessageType.ERROR, "Bluetooth", message)
        return False

    def stop_listening(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=2)
            self.listener = None
        self.connect_button.set_label("Bağlan")
        ctx = self.connect_button.get_style_context()
        ctx.remove_class("destructive-action")
        ctx.add_class("suggested-action")
        self.port_combo.set_sensitive(True)
        self.baud_combo.set_sensitive(True)
        self.bt_button.set_sensitive(True)

    def on_connect_clicked(self, *_):
        if self.listener:
            self.stop_listening()
            self.set_status("Bağlantı kesildi.")
        else:
            self.start_listening()

    def on_record(self, record: str) -> bool:
        m = parse(record)
        port = self.listener.settings.port if self.listener else "?"
        self.store.add(m, source=f"seri:{port}")
        self.show_measurement(m)
        self.refresh_history()
        self.set_status(f"{port} dinleniyor. Son ölçüm {datetime.now():%H:%M:%S} saatinde alındı.")
        return False

    def on_listen_error(self, message: str) -> bool:
        self.stop_listening()
        self.set_status("Bağlı değil.")
        self.show_message(Gtk.MessageType.ERROR, "Tartıya bağlanılamadı", message)
        return False

    # --- Geçmiş, içe ve dışa aktarma ----------------------------------------

    def on_history_selected(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        if it is not None:
            self.show_measurement(parse(model[it][5]), note=f"kayıt no {model[it][0]}")

    def _file_dialog(self, title: str, action: Gtk.FileChooserAction, button: str):
        dialog = Gtk.FileChooserNative(title=title, transient_for=self, action=action,
                                       accept_label=button, cancel_label="Vazgeç")
        return dialog

    def on_import(self, *_):
        dialog = self._file_dialog("SD kart dosyalarını seçin", Gtk.FileChooserAction.OPEN, "İçe aktar")
        dialog.set_select_multiple(True)
        csv_filter = Gtk.FileFilter()
        csv_filter.set_name("Tartı dosyaları (CSV)")
        csv_filter.add_pattern("*.csv")
        csv_filter.add_pattern("*.CSV")
        dialog.add_filter(csv_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("Tüm dosyalar")
        all_filter.add_pattern("*")
        dialog.add_filter(all_filter)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            paths = [f.get_path() for f in dialog.get_files()]
            try:
                added, skipped, unknown = self.store.import_files(paths)
            except OSError as exc:
                self.show_message(Gtk.MessageType.ERROR, "Dosya okunamadı", str(exc))
            else:
                self.refresh_history()
                self.show_message(Gtk.MessageType.INFO, "İçe aktarma tamamlandı",
                                  f"{added} ölçüm eklendi, {skipped} tanesi zaten kayıtlıydı, "
                                  f"{unknown} kayıt tanınmadı.")
        dialog.destroy()

    def on_export(self, *_):
        dialog = self._file_dialog("Ölçümleri dışa aktar", Gtk.FileChooserAction.SAVE, "Kaydet")
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(f"olcumler-{datetime.now():%Y%m%d}.csv")
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = dialog.get_filename()
            try:
                count = self.store.export_csv(path)
            except OSError as exc:
                self.show_message(Gtk.MessageType.ERROR, "Dosya yazılamadı", str(exc))
            else:
                self.show_message(Gtk.MessageType.INFO, "Dışa aktarıldı",
                                  f"{count} ölçüm {path} dosyasına yazıldı.")
        dialog.destroy()

    def on_report(self, *_):
        was_listening = self.listener is not None
        if was_listening:
            self.stop_listening()
            self.set_status("Cihaz raporu hazırlanıyor; dinleme rapor bitince sürecek.")
        dialog = ReportDialog(self, self.selected_port(), self.selected_baud(),
                              self.bt_device_for(self.selected_port()))
        dialog.run()
        dialog.close_dialog()
        if was_listening:
            self.start_listening()
        else:
            self.set_status("Bağlı değil. Portu seçip “Bağlan”a basın.")


class ReportDialog(Gtk.Dialog):
    """Üç adımlı cihaz raporu: model → ölçüm → ekrandaki kilo."""

    def __init__(self, parent: MainWindow, port: str, baud: int, bt_device=None):
        super().__init__(title="Cihaz raporu", transient_for=parent, modal=True)
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
            "Cihazınızı tanıtın",
            "Bu rapor, cihazınızın veri biçimini öğrenmemize yardım eder. Danışan numarası "
            "rapora yazılmadan silinir. Ölçümü kendinizle ya da bir test kişisiyle yapın.")
        self.model_entry = Gtk.Entry(placeholder_text="Cihaz modeli, ör. MC-780MA")
        self.model_entry.set_tooltip_text("Cihazın altındaki etikette yazar")
        self.model_entry.connect("changed", lambda e: self.start_button.set_sensitive(
            bool(e.get_text().strip())))
        box.pack_start(self.model_entry, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        self.start_button = Gtk.Button(label="Ölçümü başlat", sensitive=False)
        self.start_button.get_style_context().add_class("suggested-action")
        self.start_button.connect("clicked", self.on_start)
        sd = Gtk.Button(label="SD kart dosyasından…")
        sd.connect("clicked", self.on_sd_file)
        self.bt_start = Gtk.Button(label="Bluetooth ile…", sensitive=False)
        self.bt_start.connect("clicked", self.on_bluetooth)
        self.model_entry.connect("changed", lambda e: self.bt_start.set_sensitive(
            bool(e.get_text().strip())))
        buttons.pack_end(self.start_button, False, False, 0)
        buttons.pack_end(self.bt_start, False, False, 0)
        buttons.pack_end(sd, False, False, 0)
        box.pack_end(buttons, False, False, 0)
        port_text = self.port or "seçilmedi"
        box.pack_end(Gtk.Label(label=f"Port: {port_text} · Hız: {self.baud}", xalign=0), False,
                     False, 0)
        return box

    def _page_bluetooth(self) -> Gtk.Widget:
        box = self._page("Bluetooth cihazını seçin",
                         "Tartıyı açın. Yakındaki cihazlar aranıyor; listeden tartınızı seçin.")
        self.bt_spinner = Gtk.Spinner()
        box.pack_start(self.bt_spinner, False, False, 0)
        self.bt_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.bt_list.connect("row-selected", lambda _l, row: self.bt_choose.set_sensitive(
            row is not None and row.get_index() < len(self.bt_devices)))
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(self.bt_list)
        box.pack_start(scroll, True, True, 0)
        row = Gtk.Box(spacing=8)
        back = Gtk.Button(label="Geri")
        back.connect("clicked", lambda *_: self.stack.set_visible_child_name("start"))
        again = Gtk.Button(label="Yeniden ara")
        again.connect("clicked", lambda *_: self._bt_rescan())
        self.bt_choose = Gtk.Button(label="Seç ve ölçüme başla", sensitive=False)
        self.bt_choose.get_style_context().add_class("suggested-action")
        self.bt_choose.connect("clicked", self.on_bt_chosen)
        row.pack_start(back, False, False, 0)
        row.pack_end(self.bt_choose, False, False, 0)
        row.pack_end(again, False, False, 0)
        box.pack_end(row, False, False, 0)
        return box

    def _page_wait(self) -> Gtk.Widget:
        box = self._page("Şimdi cihazda ölçüm yapın",
                         "Tartıya çıkıp ölçümü tamamlayın. Veri gelince otomatik olarak "
                         "sonraki adıma geçilir (en fazla 3 dakika beklenir).")
        spinner = Gtk.Spinner(active=True)
        spinner.set_size_request(48, 48)
        box.pack_start(spinner, True, True, 0)
        cancel = Gtk.Button(label="Vazgeç")
        cancel.connect("clicked", lambda *_: self.cancel.set())
        box.pack_end(cancel, False, False, 0)
        return box

    def _page_weight(self) -> Gtk.Widget:
        box = self._page("Ekrandaki kilo", "")
        self.weight_info = box.get_children()[1]
        self.weight_entry = Gtk.Entry(placeholder_text="Ekranda görünen kilo, ör. 72,4 (isteğe bağlı)")
        self.weight_entry.connect("activate", self.on_save)
        box.pack_start(self.weight_entry, False, False, 0)
        save = Gtk.Button(label="Raporu kaydet")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self.on_save)
        row = Gtk.Box()
        row.pack_end(save, False, False, 0)
        box.pack_end(row, False, False, 0)
        return box

    def _page_done(self) -> Gtk.Widget:
        box = self._page("Rapor hazır", "")
        self.done_info = box.get_children()[1]
        buttons = Gtk.Box(spacing=8)
        form = Gtk.Button(label="Gönderme formunu aç")
        form.get_style_context().add_class("suggested-action")
        form.connect("clicked", lambda *_: self._open_uri(REPORT_FORM_URL))
        folder = Gtk.Button(label="Klasörü aç")
        folder.connect("clicked", lambda *_: self._open_uri(self.saved.parent.as_uri()))
        close = Gtk.Button(label="Kapat")
        close.connect("clicked", lambda *_: self.response(Gtk.ResponseType.CLOSE))
        buttons.pack_end(form, False, False, 0)
        buttons.pack_end(folder, False, False, 0)
        buttons.pack_start(close, False, False, 0)
        box.pack_end(buttons, False, False, 0)
        return box

    # --- Akış --------------------------------------------------------------

    def device(self) -> dict:
        return {"brand": "Tanita", "model": self.model_entry.get_text().strip()}

    def on_bluetooth(self, *_):
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
            label.set_markup(f"<b>{escape(device.name or 'Adsız cihaz')}</b>\n"
                             f"<small>{escape(device.kind)}{rssi}</small>")
            self.bt_list.add(label)
        if not devices:
            self.bt_list.add(Gtk.Label(
                label="Cihaz bulunamadı. Tartıyı açıp “Yeniden ara”ya basın.", margin=12))
        self.bt_list.show_all()
        return False

    def _bt_list_failed(self, message: str) -> bool:
        self.bt_spinner.stop()
        self.stack.set_visible_child_name("start")
        self.parent_window.show_message(Gtk.MessageType.ERROR, "Bluetooth", message)
        return False

    def on_bt_chosen(self, *_):
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
        GLib.idle_add(self._show_weight_page, entry, target, len(result["notifications"]),
                      "Bluetooth bildirimi")

    def on_start(self, *_):
        if not self.port:
            self.parent_window.show_message(Gtk.MessageType.WARNING, "Port seçilmedi",
                                            "Ana penceredeki listeden tartının portunu seçin.")
            return
        ble = self.bt_device is not None and not self.bt_device.classic_serial
        connection = f"bluetooth ({self.bt_device.kind})" if self.bt_device else "seri port"
        self.report = new_report({**self.device(), "connection": connection}, "arayuz")
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
        GLib.idle_add(self._captured, data, timing, f"seri:{self.port}")

    def _capture_failed(self, message: str) -> bool:
        self.stack.set_visible_child_name("start")
        self.parent_window.show_message(Gtk.MessageType.ERROR, "Tartıya bağlanılamadı", message)
        return False

    def _captured(self, data: bytes, timing: list, source: str) -> bool:
        entry, target = build_entry(data, timing, source)
        return self._show_weight_page(entry, target, len(data), "bayt veri")

    def _show_weight_page(self, entry: dict, target, amount: int, unit: str) -> bool:
        if self.cancel.is_set():
            self.cancel.clear()
            self.stack.set_visible_child_name("start")
            return False
        self.entry, self.target = entry, target
        if amount:
            self.weight_info.set_text(
                f"Cihazdan {amount} {unit} alındı. Cihaz ekranında gördüğünüz kiloyu "
                "yazarsanız veriyi doğrulamamız kolaylaşır.")
        else:
            self.weight_info.set_text(
                "Cihazdan hiç veri gelmedi. Yine de raporu gönderebilirsiniz; cihazın yapısı "
                "rapora eklendi. Kablolu cihazlarda kabloyu ve hız ayarını kontrol edin; "
                "Bluetooth cihazlar veri göndermeden önce üreticinin uygulamasından komut "
                "bekliyor olabilir.")
        self.stack.set_visible_child_name("weight")
        self.weight_entry.grab_focus()
        return False

    def on_sd_file(self, *_):
        if not self.model_entry.get_text().strip():
            self.model_entry.grab_focus()
            return
        dialog = Gtk.FileChooserNative(title="SD kart dosyasını seçin", transient_for=self,
                                       action=Gtk.FileChooserAction.OPEN,
                                       accept_label="Seç", cancel_label="Vazgeç")
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            path = Path(dialog.get_filename())
            try:
                data = path.read_bytes()[:256 * 1024]
            except OSError as exc:
                self.parent_window.show_message(Gtk.MessageType.ERROR, "Dosya okunamadı", str(exc))
            else:
                self.report = new_report({**self.device(), "connection": "SD kart dosyası"},
                                         "arayuz")
                self._captured(data, [], f"dosya:{path.name}")
        dialog.destroy()

    def on_save(self, *_):
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
            self.parent_window.show_message(Gtk.MessageType.ERROR, "Rapor kaydedilemedi", str(exc))
            return
        self.done_info.set_text(
            f"Rapor şu dosyaya kaydedildi:\n{self.saved}\n\n"
            "“Gönderme formunu aç” düğmesine basın, formda cihaz modelini yazıp bu dosyayı "
            "sürükleyip bırakın. Teşekkürler!")
        self.stack.set_visible_child_name("done")

    def _open_uri(self, uri: str) -> None:
        try:
            Gtk.show_uri_on_window(self, uri, Gdk.CURRENT_TIME)
        except GLib.Error as exc:
            self.parent_window.show_message(Gtk.MessageType.ERROR, "Açılamadı", exc.message)

    def close_dialog(self) -> None:
        self.cancel.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tartim-arayuz", description="Tartım masaüstü arayüzü")
    parser.add_argument("--port", help="Açılışta seçili olacak port")
    parser.add_argument("--veritabani", help="SQLite dosyası")
    parser.add_argument("--surum", action="version", version=f"tartim {__version__}")
    args = parser.parse_args(argv)

    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
    store = Store(args.veritabani)

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
