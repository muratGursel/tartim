# tartim

**[Türkçe](README.tr.md)** · English

An open-source reader for **body composition analyzers** (Tanita-compatible
devices) on Pardus and other GNU/Linux systems.

The vendor's PC software only runs on Windows. `tartim` reads the measurement a
device sends over a serial port (RS-232 / USB) or Bluetooth, decodes it and
stores it in a local database. It can also import the CSV files written to an
SD card.

> **Status: early development.** The data format is based on manuals and
> community notes and has not been verified on a real device yet. Details:
> [docs/PROTOCOL.md](docs/PROTOCOL.md)

Tanita is a registered trademark of TANITA Corporation. This project is not
affiliated with Tanita.

The interface is available in **Turkish** and **English** and follows the
system language (`TARTIM_LANG=en` or `TARTIM_LANG=tr` overrides it).

## Installation (Pardus 23 / 25, Debian-based systems)

One command in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/muratGursel/tartim/main/install.sh | sudo sh
```

Or download `tartim_*_all.deb` from the
[Releases](https://github.com/muratGursel/tartim/releases) page and install it:

```sh
sudo apt install ./tartim_*_all.deb
```

The package also installs a udev rule that gives the logged-in user access to
USB-serial ports, so you do not need to join the `dialout` group. For an RS-232
port on the motherboard (`/dev/ttyS*`) run `sudo usermod -aG dialout $USER`.

To run from source during development: `sudo apt install python3-serial
python3-gi gir1.2-gtk-3.0` and `python3 -m tartim` in the repository folder.

## Desktop interface

After installation it appears in the application menu as **Tartım**; it can
also be started with `tartim-arayuz`.

![The Tartım interface (synthetic sample data)](docs/screenshots/en/02-measurement.png)

Step-by-step instructions: **[User guide](docs/USER_GUIDE.md)**
([PDF](docs/Tartim-User-Guide.pdf)) · Turkish: [Kullanım kılavuzu](docs/KULLANIM.md)

1. Choose the scale's port and press **Connect**.
2. Take a measurement on the device; the result appears on the left and is saved
   automatically.
3. Saved measurements are listed on the right, with **Import from SD card** and
   **Export for Excel**.
   **Result sheet (PDF)** creates a printable two-page result sheet with the
   client's progress.
4. **Device report** prepares a report for the developers in a few steps.

## Bluetooth

The Bluetooth button next to the port field searches for nearby scales
(command line: `tartim bluetooth`).

- **Standard Bluetooth scales** (with the Weight Scale / Body Composition
  service): choose one in the list and press **Connect**; measurements arrive live.
- **Classic Bluetooth serial devices**: pair them first in the system settings
  (the PIN is usually 0000 or 1234), then choose and connect.
- **Vendor-specific protocols** (e.g. Tartı FAST): cannot be read directly yet.
  If you send a **device report**, we can add support.
  Details: [docs/PROTOCOL.md](docs/PROTOCOL.md#bluetooth)

## Command line

```sh
tartim ports                           # connected serial ports
tartim listen --port /dev/ttyUSB0      # show and save measurements
tartim import /media/$USER/SD/*.CSV    # import from an SD card
tartim list --last 10
tartim export --output measurements.csv  # for Excel / LibreOffice
tartim raw --port /dev/ttyUSB0         # raw data for a new device
tartim print --name "First Last"      # printable result sheet (PDF)
```

The Turkish command names of earlier releases (`dinle`, `ice-aktar`, `rapor`, …)
keep working as aliases.

Port settings: `--baud 9600 --parity N --bytesize 8 --stopbits 1` (defaults).

Measurements are stored in `~/.local/share/tartim/tartim.db`, created readable
by you only.

## Own a scale? Send a device report

What the project needs most is real data from different devices. Plug the scale
in and run:

```sh
tartim report          # or the "Device report" button in the interface
```

It only asks for the device model and the weight shown on the display, and finds
the port by itself. It records the data while you measure and writes a
`tartim-report-MODEL-DATE.json` file; the client number is masked before
anything is written. You then choose how to send it: to the project server
(no account needed), with the
[GitHub form](https://github.com/muratGursel/tartim/issues/new?template=cihaz-raporu.yml),
or later (`tartim send-report FILE`).

- SD card file: `tartim report --file /media/$USER/SD/20261016.CSV`
- Bluetooth scales: `tartim report --bluetooth` (or "Device report → With Bluetooth…")
- To give more detail: `tartim report --detailed` (asks for device settings, the
  height/age/gender entered on the device and all values on the display, and
  shows which field matches what)

Measure yourself or a test person; never send a real client's measurement.

## Trying it without a device

```sh
socat -d -d pty,raw,echo=0,link=/tmp/scale pty,raw,echo=0,link=/tmp/pc &
python3 -m tartim listen --port /tmp/pc &
python3 -m tartim simulate --port /tmp/scale --count 3
```

The values produced by the simulator are synthetic and belong to no one.

## Tests

```sh
python3 -m unittest -v
```

The serial port test runs on Linux when `socat` and `python3-serial` are
installed. The interface tests need a display; on a headless server they run
with GTK Broadway:
`broadwayd :5 & GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 python3 -m unittest`

## Translations

Source strings are English; translations are gettext `.po` files in
[`tartim/locale/`](tartim/locale). They are compiled in memory at start-up, so
no build step is needed. A test checks that every message has a Turkish
translation and that the placeholders match. To add a language, copy `tr.po`
to `<code>.po`, translate the `msgstr` lines and send a pull request.

## Report server

Users can send device reports from the application without a GitHub account.
A small service at `https://ldow.duckdns.org/tartim/report` validates them and
forwards them to a private repository; the GitHub token stays on the server.
Installation and security model: [server/INSTALL.md](server/INSTALL.md).
Sending is optional; organisations can point the application to their own
server with `TARTIM_REPORT_URL` or switch the option off with an empty value.

## Personal data (KVKK / GDPR)

Body measurements are health data, a special category of personal data. Before
using the application in your organisation, settle consent, access rights and
retention with your data controller. Never attach real measurement records to
bug reports or to this repository.

## Roadmap

- [ ] Verify the field codes on real MC-780 / BC-418 devices
- [ ] Verify the `CS` checksum
- [ ] Remote mode: send height, age and gender from the computer to the device
- [x] Desktop interface (GTK)
- [ ] Client records and progress charts
- [x] Bluetooth: standard BLE scales, classic serial port, discovery report
- [ ] Tartı FAST protocol (waiting for a device report)
- [x] Printable result sheet (PDF) with progress charts
- [x] `.deb` package and one-command installation
- [x] Turkish and English interface and documentation
- [ ] Submission to the Pardus Store
- [ ] Plug-in structure for other brands

## Contributing

If you own a scale, the most valuable contribution is a file made with
`tartim report` (see above). Protocol details: [docs/PROTOCOL.md](docs/PROTOCOL.md).

To build the package from source: `sh packaging/build-deb.sh`

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
