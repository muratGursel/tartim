# Device protocol notes

This document records what we know about the data format of supported devices
and where we learned it. Anything not verified is marked as such.

## Connection

| Model | Interface | Known settings | Source | Status |
|---|---|---|---|---|
| MC-780MA | RS-232C, USB-B, SD card | 9600 baud, no flow control | GMON manual (same setting listed for MC-180) | Not verified |
| MC-780MA | — | Setting 30: PC output format `0` default, `1` BC-418 format | MC-780 instruction manual, p. 11 | In the manual |
| MC-780MA | — | RS-232C and USB cannot be used at the same time | MC-780 instruction manual | In the manual |
| MC-780MA | SD card | One CSV file per day named `YYYYMMDD` | MC-780 instruction manual, p. 21 | In the manual |
| BC-418 | RS-232C | "Standard" (device sends) and "remote" (PC sends commands) modes | GMON manual | Not verified |

Only **standard mode** is supported for now: the device sends a record by
itself after every measurement and `tartim` listens.

## Record format

```
{0,16,~0,1,~1,1,~2,1,MO,"MC-780",ID,"0000000000000001",...,Wk,70.4,FW,21.3,...,CS,3A}
```

- A record ends with CR LF.
- The leading `0,16,~0,1,~1,1,~2,1` is a format header and is skipped.
- Then come `CODE,VALUE` pairs. Codes are case sensitive.
- `CS` is a checksum. The algorithm is unknown, so it is not verified yet.

The meanings of the field codes are in `tartim/fields.py`. The source is
community notes that decode the MC-780 Bluetooth protocol
(<https://gist.github.com/zapkub/350bb90a0aa70d7c3685522e0b83736c>), so they are
all marked `confirmed=False`.

## Bluetooth

`tartim` talks to BlueZ over D-Bus (no extra package needed).

| Device type | Support |
|---|---|
| Classic Bluetooth serial port (SPP) | After pairing, use `bt:AA:BB:CC:DD:EE:FF` as the port; it is read exactly like a wired device. RFCOMM channels 1–5 are tried; use `bt:ADDRESS@CHANNEL` if needed. |
| BLE, standard scale services (Weight Scale 0x181D, Body Composition 0x181B) | Read directly and live. The packet format comes from the Bluetooth SIG specification; weight and body composition packets are merged. Not verified on a real device yet. |
| BLE, vendor-specific services (Tartı FAST may be one) | Cannot be read yet. `tartim report --bluetooth` records the service structure, the readable information fields (model, software version; never the serial number) and every notification received during a measurement. Nothing is written to the device. |

Reports keep only the first three bytes (vendor prefix) of the Bluetooth address.

### When the device waits for a command from its app

Some scales (e.g. the Tanita MC-780 Bluetooth module) wait for height, age,
gender and a start command from their app before sending a measurement. Then
no notifications appear in the report. To decode the protocol, the traffic
between the vendor's phone app and the device has to be recorded:

1. On an Android phone, tap **Settings → About phone → Build number** seven
   times to enable the developer options.
2. Turn on **Developer options → Enable Bluetooth HCI snoop log**, then switch
   Bluetooth off and on.
3. Take a measurement of a test person with the vendor's app.
4. Get the log: `adb bugreport report.zip` on a computer (the file
   `btsnoop_hci.log` is inside). It opens in Wireshark.
5. Send the file together with a device report. The log may also contain
   traffic of other Bluetooth devices on the phone; if possible, record while
   only the scale is connected.

## How do we verify a new device?

1. Connect the device and find its port: `tartim ports`
2. Record raw data: `tartim raw --port /dev/ttyUSB0 --output raw.txt`
3. Take a measurement on the device. Note the values shown on the display and
   the printout next to each other (weight, body fat etc.).
4. If nothing arrives, change the baud rate (`--baud 4800`, `19200`, `38400`)
   and check the device's PC output setting.
5. Match the codes with the values on the display, set `confirmed=True` in
   `fields.py` and add the raw record as a test.

**Important:** raw records contain the client number, age, gender and body
measurements. Measure a test person before sharing, or change the identity
fields.
