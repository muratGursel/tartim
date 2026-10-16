"""Reading devices over a serial port (RS-232 / USB-serial).

pyserial is only used in this module; parsing and storage work without it.
On Pardus: ``sudo apt install python3-serial``
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .i18n import _
from .protocol import Framer


@dataclass
class PortSettings:
    port: str
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1


def _serial():
    try:
        import serial  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(_("pyserial was not found. To install it on Pardus: "
                           "sudo apt install python3-serial")) from exc
    return serial


def list_ports() -> list[tuple[str, str]]:
    _serial()
    from serial.tools import list_ports as lp  # noqa: PLC0415

    return [(p.device, p.description) for p in lp.comports()]


def open_port(settings: PortSettings, timeout: float = 0.5):
    if settings.port.lower().startswith("bt:"):
        from .bluetooth import RfcommPort, parse_bt_port  # noqa: PLC0415

        return RfcommPort(*parse_bt_port(settings.port), timeout=timeout)
    serial = _serial()
    try:
        return serial.Serial(
            settings.port,
            baudrate=settings.baudrate,
            bytesize=settings.bytesize,
            parity=settings.parity.upper(),
            stopbits=settings.stopbits,
            timeout=timeout,
        )
    except serial.SerialException as exc:
        message = _("Could not open {port}: {error}").format(port=settings.port, error=exc)
        if "Permission denied" in str(exc) or "İzin" in str(exc):
            message += "\n" + _("You do not have permission to use the port. Add your user to "
                                "the dialout group:\n  sudo usermod -aG dialout $USER   "
                                "(then log out and back in)")
        raise SystemExit(message) from exc


def read_records(port, on_raw: Callable[[bytes], None] | None = None) -> Iterator[str]:
    """Yields complete records until the port closes or Ctrl+C."""
    framer = Framer()
    while True:
        chunk = port.read(port.in_waiting or 1)
        if not chunk:
            continue
        if on_raw:
            on_raw(chunk)
        yield from framer.feed(chunk)
