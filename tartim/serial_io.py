"""Seri port (RS-232 / USB-seri) üzerinden cihaz okuma.

pyserial yalnızca bu modülde kullanılır; çözümleme ve depolama onsuz çalışır.
Pardus'ta: ``sudo apt install python3-serial``
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

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
        raise SystemExit(
            "pyserial bulunamadı. Pardus'ta kurmak için: sudo apt install python3-serial"
        ) from exc
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
        hint = ""
        if "Permission denied" in str(exc) or "İzin" in str(exc):
            hint = ("\nPorta erişim izniniz yok. Kullanıcınızı dialout grubuna ekleyin:"
                    "\n  sudo usermod -aG dialout $USER   (ardından oturumu kapatıp açın)")
        raise SystemExit(f"{settings.port} açılamadı: {exc}{hint}") from exc


def read_records(port, on_raw: Callable[[bytes], None] | None = None) -> Iterator[str]:
    """Port kapanana ya da Ctrl+C'ye kadar tam kayıtları üretir."""
    framer = Framer()
    while True:
        chunk = port.read(port.in_waiting or 1)
        if not chunk:
            continue
        if on_raw:
            on_raw(chunk)
        yield from framer.feed(chunk)
