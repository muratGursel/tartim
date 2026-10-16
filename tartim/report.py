"""Cihaz raporu: tartısı olan kullanıcılardan geliştirme verisi toplamak.

``tartim rapor`` kullanıcıya birkaç kısa soru sorar, cihazdan ham ölçüm
verisini kaydeder ve cihaz ekranında okunan değerleri bu veriyle karşılaştırır.
Sonuç, proje ile paylaşılmak üzere tek bir JSON dosyasıdır. Danışan numarası
dosyaya yazılmadan önce sıfırlarla maskelenir.
"""

from __future__ import annotations

import csv
import json
import platform
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import __version__
from .fields import describe
from .protocol import Framer, parse

SCHEMA_VERSION = 1

# Cihaz ekranından okunacak sonuçlar: (soru, beklenen kod)
SCREEN_FIELDS = [
    ("Kilo (kg)", "Wk"),
    ("Yağ oranı (%)", "FW"),
    ("Yağ kütlesi (kg)", "fW"),
    ("Kas kütlesi (kg)", "mW"),
    ("Kemik kütlesi (kg)", "bW"),
    ("Toplam vücut suyu (%)", "ww"),
    ("Viseral yağ derecesi", "IF"),
    ("Bazal metabolizma hızı (kcal)", "rB"),
    ("Metabolik yaş", "rA"),
    ("BMI", "MI"),
]
# Ölçümden önce cihaza girilen bilgiler.
INPUT_FIELDS = [
    ("Cinsiyet (1: erkek, 2: kadın)", "GE"),
    ("Yaş", "AG"),
    ("Boy (cm)", "Hm"),
    ("Kıyafet ağırlığı / dara (kg)", "Pt"),
]
CONNECTIONS = ["RS-232 (USB-seri çevirici ile)", "USB (doğrudan)", "SD kart dosyası"]

_ID_RE = re.compile(rb'(\bID,"?)(\d+)')


def mask_subject_ids(data: bytes) -> tuple[bytes, int]:
    """``ID`` alanındaki danışan numaralarını aynı uzunlukta sıfırlarla değiştirir."""
    return _ID_RE.subn(lambda m: m.group(1) + b"0" * len(m.group(2)), data)


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def analyze_record(record: str) -> dict:
    """Bir kaydın öğelerini ve tanınan alanlarını çıkarır."""
    text = record.strip().lstrip("{").rstrip("}").replace("\r", "").replace("\n", "")
    try:
        tokens = next(csv.reader([text]), [])
    except csv.Error:
        tokens = text.split(",")
    m = parse(record)
    return {"raw": record, "tokens": tokens, "recognized": m.recognized, "values": m.values}


def compare(analysis: dict, label: str, code: str, value: float) -> dict:
    """Ekranda okunan değeri kayıttaki öğelerle eşleştirir.

    Kayıt anahtar-değer biçiminde olmasa bile değerin hangi sırada geçtiğini
    bulur; bu, bilinmeyen biçimleri çözmek için yeterli ipucunu verir.
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
    """USB kimliği gibi cihaz bilgileri. USB seri numarası bilinçli olarak alınmaz."""
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
            clock: Callable[[], float] = time.monotonic) -> tuple[bytes, list[list[int]]]:
    """İlk bayt gelene kadar en fazla ``timeout`` saniye bekler; veri geldikten
    sonra ``idle`` saniye sessizlik olunca biter. Bayt akışını ve her parçanın
    zamanlamasını (ms, bayt sayısı) döndürür."""
    start = clock()
    last = None
    data = bytearray()
    timing: list[list[int]] = []
    while True:
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
    """Soru-cevap akışı. ``ask`` ve ``say`` testlerde değiştirilebilir."""

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
                    raise SystemExit("Girdi sona erdi, rapor oluşturulmadı.") from None
                answer = ""
            answer = answer or default
            if answer or not required:
                return answer
            self.say("  Bu bilgi gerekli.")

    def ask_number(self, question: str) -> float | None:
        while True:
            answer = self.ask(question)
            if not answer:
                return None
            value = _number(answer)
            if value is not None:
                return value
            self.say("  Sayı girin (boş bırakmak için Enter).")

    def choose(self, question: str, options: list[str], default: int = 1) -> int:
        for i, option in enumerate(options, 1):
            self.say(f"  {i}) {option}")
        while True:
            answer = self.ask(question, str(default))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return int(answer) - 1
            self.say(f"  1 ile {len(options)} arasında bir sayı girin.")

    def yes(self, question: str, default: bool = True) -> bool:
        answer = self.ask(f"{question} (e/h)", "e" if default else "h").lower()
        return answer.startswith("e")


def _measurement_entry(w: Wizard, data: bytes, timing: list, source: str,
                       detailed: bool) -> dict:
    masked, count = mask_subject_ids(data)
    framer = Framer()
    records = framer.feed(masked) + framer.flush()
    analyses = [analyze_record(r) for r in records]
    entry = {"source": source, "summary": stream_summary(masked), "timing_ms": timing,
             "raw_hex": masked.hex(), "raw_text": masked.decode("latin-1"),
             "subject_ids_masked": count, "records": analyses,
             "inputs": [], "screen": []}
    measured = [a for a in analyses if a["tokens"]]
    if not measured:
        return entry
    target = next((a for a in measured if a["recognized"]), measured[-1])
    if not detailed:
        # Hızlı kip: yalnızca kilo sorulur; kaydı doğrulamak için bu yeterli bir ipucu.
        label, code = SCREEN_FIELDS[0]
        value = w.ask_number("Ekranda görünen kilo (boş geçebilirsiniz)")
        if value is not None:
            entry["screen"].append(compare(target, label, code, value))
        return entry

    if target["recognized"]:
        w.say("\nÇözülen değerler:")
        for code, value in target["values"].items():
            if code not in ("CS", "ID"):
                w.say(f"  {describe(code).label:<38} {value}")
    else:
        w.say("\nKayıt bilinen biçimde değil. Ekrandaki değerler biçimi çözmemize yardım edecek.")
    w.say("\nÖlçümden önce cihaza girdiğiniz bilgiler (bilmiyorsanız boş bırakın):")
    for label, code in INPUT_FIELDS:
        value = w.ask_number(f"  {label}")
        if value is not None:
            entry["inputs"].append(compare(target, label, code, value))
    w.say("\nCihaz ekranında (ya da çıktıda) gördüğünüz sonuçlar (boş bırakılabilir):")
    for label, code in SCREEN_FIELDS:
        value = w.ask_number(f"  {label}")
        if value is not None:
            entry["screen"].append(compare(target, label, code, value))
    checks = entry["inputs"] + entry["screen"]
    if checks:
        ok = sum(c["matches_expected"] for c in checks)
        w.say(f"\nKarşılaştırma: {len(checks)} değerden {ok} tanesi beklenen alanla eşleşti.")
    return entry


def _pick_port(w: Wizard, ports: list[tuple[str, str]], detailed: bool) -> str:
    """Tek bir USB-seri port varsa (hızlı kipte) onu seçer, yoksa kullanıcıya sorar."""
    usb = [dev for dev, _ in ports if "ttyUSB" in dev or "ttyACM" in dev]
    if len(usb) == 1 and not detailed:
        w.say(f"Port: {usb[0]}")
        return usb[0]
    if ports:
        w.say("\nBulunan seri portlar:")
        for i, (dev, desc) in enumerate(ports, 1):
            w.say(f"  {i}) {dev}  {desc}")
    else:
        w.say("\nSeri port bulunamadı. Kabloyu takıp 'lsusb' ile kontrol edin.")
    answer = w.ask("Port (numara ya da yol, ör. /dev/ttyUSB0)", required=True)
    if answer.isdigit() and 0 < int(answer) <= len(ports):
        return ports[int(answer) - 1][0]
    return answer


def run_wizard(w: Wizard, port_opener: Callable | None = None, port: str | None = None,
               baud: int | None = None, timeout: float = 180.0,
               output: str | None = None, idle: float = 2.0,
               files: list[str] | None = None, detailed: bool = False,
               ports: list[tuple[str, str]] | None = None) -> Path:
    w.say("=== tartim cihaz raporu ===\n"
          "Cihazınızın veri biçimini öğrenmemiz için bir rapor dosyası hazırlanacak.\n"
          "Danışan numarası maskelenir. Ölçümü kendinizle ya da bir test kişisiyle yapın.\n")

    device = {"brand": "Tanita",
              "model": w.ask("Cihaz modeli (etikette yazar, ör. MC-780MA)", required=True)}
    if detailed:
        device["brand"] = w.ask("Marka", "Tanita")
        device["software_version"] = w.ask("Cihaz yazılım sürümü (biliyorsanız)")
        device["output_setting"] = w.ask(
            "PC veri çıkış ayarı (biliyorsanız, ör. 'varsayılan' ya da 'BC-418')")
        if not files and not port:
            w.say("\nBağlantı türü:")
            if w.choose("Seçiminiz", CONNECTIONS) == 2:
                files = [w.ask("SD karttaki dosyanın yolu", required=True)]
    device["connection"] = "SD kart dosyası" if files else "seri port"

    report: dict = {"schema": SCHEMA_VERSION,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "mode": "ayrintili" if detailed else "hizli",
                    "system": system_info(), "device": device, "measurements": []}

    if files:
        for path in files:
            try:
                data = Path(path).read_bytes()[:256 * 1024]
            except OSError as exc:
                w.say(f"{path} okunamadı: {exc}")
                continue
            w.say(f"{Path(path).name} okundu.")
            report["measurements"].append(_measurement_entry(
                w, data, [], source=f"dosya:{Path(path).name}", detailed=detailed))
    else:
        from . import serial_io  # noqa: PLC0415

        if not port:
            port = _pick_port(w, serial_io.list_ports() if ports is None else ports, detailed)
        if not baud:
            baud = int(w.ask("Baud hızı", "9600")) if detailed else 9600
        settings = serial_io.PortSettings(port, baud)
        report["port"] = {**port_details(port), "baudrate": baud, "bytesize": settings.bytesize,
                          "parity": settings.parity, "stopbits": settings.stopbits}
        count = int(w.ask("Kaç ölçüm kaydedilsin?", "1")) if detailed else 1
        conn = (port_opener or serial_io.open_port)(settings)
        try:
            for i in range(count):
                prefix = f"[{i + 1}/{count}] " if count > 1 else ""
                w.say(f"\n{prefix}Şimdi cihazda ölçüm yapın. "
                      f"Bekleniyor (en fazla {timeout:g} sn)...")
                data, timing = capture(conn, timeout, idle)
                if data:
                    w.say(f"Veri alındı ({len(data)} bayt).")
                else:
                    w.say("Hiç veri gelmedi. Kabloyu ve cihazın PC çıkış ayarını kontrol edin.\n"
                          "Farklı bir hız denemek için: tartim rapor --baud 19200")
                report["measurements"].append(_measurement_entry(
                    w, data, timing, source=f"seri:{port}", detailed=detailed))
        finally:
            conn.close()

    if detailed:
        report["notes"] = w.ask("\nEklemek istediğiniz not (sorunlar, cihaz ayarları vb.)")
    model = re.sub(r"[^A-Za-z0-9-]+", "", device["model"]) or "cihaz"
    path = Path(output or f"tartim-rapor-{model}-{datetime.now():%Y%m%d-%H%M%S}.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    w.say(f"\nRapor hazır: {path.resolve()}\n"
          "Bu dosyayı şu adresteki 'Cihaz raporu' formuna ekleyerek gönderebilirsiniz:\n"
          "https://github.com/muratGursel/tartim/issues/new?template=cihaz-raporu.yml")
    return path


def main_from_args(args) -> int:
    try:
        run_wizard(Wizard(), port=args.port, baud=args.baud, timeout=args.sure,
                   output=args.cikti, files=args.dosya, detailed=args.ayrintili)
    except KeyboardInterrupt:
        print("\nİptal edildi, rapor oluşturulmadı.", file=sys.stderr)
        return 130
    return 0
