"""Kullanım kılavuzundaki ekran görüntüleri için arayüzü sırayla hazırlar.

Görüntüler sentetik verilerle ve uydurma Bluetooth cihazlarıyla oluşturulur.
Ekransız bir makinede GTK Broadway ile çalıştırılıp tarayıcıdan çekilir:

    broadwayd --address 127.0.0.1 --port 8085 :5 &
    GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 python3 docs/ekran/olustur.py /tmp/adim

``/tmp/adim`` dosyasına bir sonraki adımın numarası yazıldıkça arayüz o adıma
geçer (ör. ``echo 3 > /tmp/adim``). Adımlar ``STEPS`` listesindedir.
"""

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from tartim import gui  # noqa: E402
from tartim.bluetooth import SPP_UUID, WEIGHT_SCALE_SERVICE, BtDevice  # noqa: E402
from tartim.protocol import parse  # noqa: E402
from tartim.report import build_entry  # noqa: E402
from tartim.simulator import synthetic_record  # noqa: E402
from tartim.storage import Store  # noqa: E402

DEVICES = [
    BtDevice("/x/1", "00:11:22:33:44:01", "Tartı FAST", -48, []),
    BtDevice("/x/2", "00:11:22:33:44:02", "Akıllı Tartı", -60, [WEIGHT_SCALE_SERVICE]),
    BtDevice("/x/3", "00:11:22:33:44:03", "MC-780 BT", -71, [SPP_UUID]),
]

state = {"step": -1}


def main():
    step_file = Path(sys.argv[1])
    step_file.write_text("0")
    tmp = tempfile.mkdtemp()
    store = Store(Path(tmp) / "ornek.db")
    rng = random.Random(4)
    records = [synthetic_record(subject=i, rng=rng) for i in (12, 7, 3)]

    app = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
    ctx: dict = {}

    def listening_look(win, text):
        win.connect_button.set_label("Bağlantıyı kes")
        style = win.connect_button.get_style_context()
        style.remove_class("suggested-action")
        style.add_class("destructive-action")
        win.port_combo.set_sensitive(False)
        win.baud_combo.set_sensitive(False)
        win.set_status(text)

    def report_dialog(page, port="/dev/ttyUSB0"):
        dialog = ctx.get("dialog")
        if dialog is None:
            dialog = gui.ReportDialog(ctx["win"], port, 9600)
            dialog.move(244, 150)
            ctx["dialog"] = dialog
        dialog.model_entry.set_text("MC-780MA")
        dialog.stack.set_visible_child_name(page)
        return dialog

    def step_0():  # 1. Boş ana pencere
        win = gui.MainWindow(app, store, port="/dev/ttyUSB0")
        win.move(16, 16)
        win.show_all()
        ctx["win"] = win

    def step_1():  # 2. Ölçüm alındı
        win = ctx["win"]
        for r in records:
            win.on_record(r)
        win.history_view.get_selection().unselect_all()
        win.show_measurement(parse(records[-1]))
        listening_look(win, "/dev/ttyUSB0 dinleniyor. Son ölçüm 10:42:15 saatinde alındı.")

    def step_2():  # 3. Bluetooth taraması sonrası liste açık
        win = ctx["win"]
        win.stop_listening()
        win.set_status("")
        win._bt_scanned(DEVICES)
        win.port_combo.popup()

    def step_3():  # 4. Bluetooth cihazı seçildi, bağlı
        win = ctx["win"]
        win.port_combo.popdown()
        win.port_combo.get_child().set_text(gui._bt_label(DEVICES[1]))
        listening_look(win, "Akıllı Tartı bağlandı. Cihazda ölçüm yapın.")

    def step_4():  # 5. Rapor: başlangıç
        win = ctx["win"]
        win.stop_listening()
        win.port_combo.get_child().set_text("/dev/ttyUSB0")
        win.set_status("Cihaz raporu hazırlanıyor; dinleme rapor bitince sürecek.")
        report_dialog("start")

    def step_5():  # 6. Rapor: Bluetooth listesi
        dialog = report_dialog("bluetooth")
        dialog._bt_listed(DEVICES)
        dialog.bt_list.select_row(dialog.bt_list.get_row_at_index(0))

    def step_6():  # 7. Rapor: ölçüm bekleniyor
        report_dialog("wait")

    def step_7():  # 8. Rapor: ekrandaki kilo
        dialog = report_dialog("weight")
        entry, target = build_entry(records[0].encode(), [], "seri:/dev/ttyUSB0")
        dialog._show_weight_page(entry, target, 212, "bayt veri")
        dialog.weight_entry.set_text("72,4")

    def step_8():  # 9. Rapor: hazır
        dialog = report_dialog("done")
        dialog.saved = Path("/home/kullanici/Belgeler/tartim-rapor-MC780MA-20261016-104512.json")
        dialog.done_info.set_text(
            f"Rapor şu dosyaya kaydedildi:\n{dialog.saved}\n\n"
            "“Gönderme formunu aç” düğmesine basın, formda cihaz modelini yazıp bu dosyayı "
            "sürükleyip bırakın. Teşekkürler!")

    steps = [step_0, step_1, step_2, step_3, step_4, step_5, step_6, step_7, step_8]

    def poll():
        try:
            wanted = int(step_file.read_text().strip() or 0)
        except (OSError, ValueError):
            return True
        while state["step"] < wanted and state["step"] + 1 < len(steps):
            state["step"] += 1
            steps[state["step"]]()
        return True

    def on_activate(_app):
        poll()
        GLib.timeout_add(300, poll)

    app.connect("activate", on_activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
