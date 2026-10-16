"""Puts the interface through the states shown in the user guides, step by step.

The screenshots use synthetic measurements and made-up Bluetooth devices. On a
headless machine run the interface with GTK Broadway and capture it from a browser:

    broadwayd --address 127.0.0.1 --port 8085 :5 &
    GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 python3 docs/screenshots/make.py /tmp/step tr

Writing the number of the next step to ``/tmp/step`` moves the interface to that
step (e.g. ``echo 3 > /tmp/step``). The steps are listed in ``steps`` below and
match the file names in docs/screenshots/<language>/. The language is ``tr`` or ``en``.
"""

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tartim import i18n  # noqa: E402

LANGUAGE = sys.argv[2] if len(sys.argv) > 2 else "tr"
i18n.setup(LANGUAGE)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from tartim import gui  # noqa: E402
from tartim.bluetooth import SPP_UUID, WEIGHT_SCALE_SERVICE, BtDevice  # noqa: E402
from tartim.i18n import _  # noqa: E402
from tartim.protocol import parse  # noqa: E402
from tartim.report import build_entry  # noqa: E402
from tartim.simulator import synthetic_record  # noqa: E402
from tartim.storage import Store  # noqa: E402

# Example texts that depend on the language of the screenshots.
EXAMPLES = {
    "tr": {"smart_scale": "Akıllı Tartı", "weight": "72,4",
           "report_path": "/home/kullanici/Belgeler/tartim-report-MC780MA-20261016-104512.json",
           "note": "Cihaz ekranında yağ oranı 24,1 görünüyordu"},
    "en": {"smart_scale": "Smart Scale", "weight": "72.4",
           "report_path": "/home/user/Documents/tartim-report-MC780MA-20261016-104512.json",
           "note": "The device display showed 24.1 % body fat"},
}[LANGUAGE]

DEVICES = [
    BtDevice("/x/1", "00:11:22:33:44:01", "Tartı FAST", -48, []),
    BtDevice("/x/2", "00:11:22:33:44:02", EXAMPLES["smart_scale"], -60, [WEIGHT_SCALE_SERVICE]),
    BtDevice("/x/3", "00:11:22:33:44:03", "MC-780 BT", -71, [SPP_UUID]),
]

state = {"step": -1}


def main():
    step_file = Path(sys.argv[1])
    step_file.write_text("0")
    store = Store(Path(tempfile.mkdtemp()) / "example.db")
    rng = random.Random(4)
    records = [synthetic_record(subject=i, rng=rng) for i in (12, 7, 3)]

    app = Gtk.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
    ctx: dict = {}

    def listening_look(win, text):
        win.connect_button.set_label(_("Disconnect"))
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

    def step_0():  # 01-main-window: empty main window
        win = gui.MainWindow(app, store, port="/dev/ttyUSB0")
        win.move(16, 16)
        win.show_all()
        ctx["win"] = win

    def step_1():  # 02-measurement: measurements received
        win = ctx["win"]
        for r in records:
            win.on_record(r)
        win.history_view.get_selection().unselect_all()
        win.show_measurement(parse(records[-1]))
        listening_look(win, _("Listening on {port}. Last measurement received at {time}.")
                       .format(port="/dev/ttyUSB0", time="10:42:15"))

    def step_2():  # 03-bluetooth-list: list open after a Bluetooth scan
        win = ctx["win"]
        win.stop_listening()
        win.set_status("")
        win._bt_scanned(DEVICES)
        win.port_combo.popup()

    def step_3():  # 04-bluetooth-connected: Bluetooth device chosen and connected
        win = ctx["win"]
        win.port_combo.popdown()
        win.port_combo.get_child().set_text(gui._bt_label(DEVICES[1]))
        listening_look(win, _("{name} connected. Take a measurement on the device.")
                       .format(name=DEVICES[1].name))

    def step_4():  # 05-report-start
        win = ctx["win"]
        win.stop_listening()
        win.port_combo.get_child().set_text("/dev/ttyUSB0")
        win.set_status(_("Preparing a device report; listening continues afterwards."))
        report_dialog("start")

    def step_5():  # 06-report-bluetooth
        dialog = report_dialog("bluetooth")
        dialog._bt_listed(DEVICES)
        dialog.bt_list.select_row(dialog.bt_list.get_row_at_index(0))

    def step_6():  # 07-report-wait
        report_dialog("wait")

    def step_7():  # 08-report-weight
        dialog = report_dialog("weight")
        data = records[0].encode()
        entry, target = build_entry(data, [], "serial:/dev/ttyUSB0")
        dialog._show_weight_page(entry, target, i18n.ngettext(
            "{n} byte of data received from the device.",
            "{n} bytes of data received from the device.", len(data)).format(n=len(data)))
        dialog.weight_entry.set_text(EXAMPLES["weight"])

    def step_8():  # 09-report-done: send options
        dialog = report_dialog("done")
        dialog.saved = Path(EXAMPLES["report_path"])
        dialog.done_info.set_text(_("The report was saved to:") + f"\n{dialog.saved}")
        dialog.consent.set_active(True)
        dialog.note_entry.set_text(EXAMPLES["note"])
        dialog._update_send_ui()

    steps = [step_0, step_1, step_2, step_3, step_4, step_5, step_6, step_7, step_8]

    def write_geometry():
        """Writes where the window to capture is (for cropping the screenshot)."""
        target = ctx.get("dialog") if state["step"] >= 4 else ctx["win"]
        x, y = target.get_position()
        width, height = target.get_size()
        Path(f"{step_file}.geometry{state['step']}").write_text(
            f'{{"step": {state["step"]}, "x": {x}, "y": {y}, "width": {width}, '
            f'"height": {height}}}')
        return False

    def poll():
        try:
            wanted = int(step_file.read_text().strip() or 0)
        except (OSError, ValueError):
            return True
        changed = False
        while state["step"] < wanted and state["step"] + 1 < len(steps):
            state["step"] += 1
            steps[state["step"]]()
            changed = True
        if changed:
            GLib.timeout_add(600, write_geometry)
        return True

    def on_activate(_app):
        poll()
        GLib.timeout_add(300, poll)

    app.connect("activate", on_activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
