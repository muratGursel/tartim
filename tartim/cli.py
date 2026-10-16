"""Komut satırı arayüzü: ``tartim <komut>``."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime

from . import __version__
from .fields import describe
from .protocol import Measurement, parse
from .storage import Store


def _print_measurement(m: Measurement, out=sys.stdout) -> None:
    if not m.recognized:
        print(f"[tanınmayan kayıt] {m.raw}", file=out)
        print("  Bu biçimi tanımıyoruz. Lütfen 'tartim ham' çıktısını proje ile paylaşın.",
              file=out)
        return
    print(f"--- Ölçüm: {m.model or '?'}  danışan: {m.subject_id or '-'} ---", file=out)
    for code, value in m.values.items():
        if code == "CS":
            continue
        f = describe(code)
        shown = f.display(value)
        mark = "" if f.confirmed else " *"
        print(f"  {f.label:<38} {shown}{mark}", file=out)
    print("  (* alan anlamı henüz gerçek cihazla doğrulanmadı)", file=out)


def _port_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", required=True, help="ör. /dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=9600, help="varsayılan: 9600")
    p.add_argument("--parite", choices="NEO", default="N", help="varsayılan: N")
    p.add_argument("--veri-biti", type=int, choices=(7, 8), default=8)
    p.add_argument("--dur-biti", type=float, choices=(1, 2), default=1)


def _open(args):
    from .serial_io import PortSettings, open_port  # noqa: PLC0415

    return open_port(PortSettings(args.port, args.baud, args.veri_biti,
                                  args.parite, args.dur_biti))


def cmd_ports(args) -> int:
    from .serial_io import list_ports  # noqa: PLC0415

    ports = list_ports()
    if not ports:
        print("Seri port bulunamadı. USB-seri çeviriciyi takıp 'lsusb' ile kontrol edin.")
    for device, desc in ports:
        print(f"{device}\t{desc}")
    return 0


def cmd_listen(args) -> int:
    from .serial_io import read_records  # noqa: PLC0415

    store = None if args.kaydetme else Store(args.veritabani)
    raw_log = open(args.ham_dosya, "ab") if args.ham_dosya else None
    port = _open(args)
    print(f"{args.port} dinleniyor ({args.baud} {args.veri_biti}{args.parite}"
          f"{args.dur_biti:g}). Çıkmak için Ctrl+C.", file=sys.stderr)
    count = 0
    try:
        for record in read_records(port, raw_log.write if raw_log else None):
            m = parse(record)
            _print_measurement(m)
            if store:
                store.add(m, source=f"seri:{args.port}")
            count += 1
            if args.adet and count >= args.adet:
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
    """Protokol keşfi: gelen her baytı zaman damgasıyla onaltılık ve metin olarak yazar."""
    port = _open(args)
    out = open(args.cikti, "a", encoding="utf-8") if args.cikti else sys.stdout
    print("Ham veri kaydediliyor. Cihazda bir ölçüm yapın; çıkmak için Ctrl+C.",
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
    """SD karttaki ya da ham kayıt dosyalarındaki ölçümleri içe aktarır."""
    with Store(args.veritabani) as store:
        added, skipped, unknown = store.import_files(args.dosyalar)
    print(f"{added} ölçüm eklendi, {skipped} tekrar atlandı, {unknown} kayıt tanınmadı.")
    return 0


def cmd_list(args) -> int:
    with Store(args.veritabani) as store:
        rows = store.list(limit=args.son, subject_id=args.danisan)
    if args.json:
        print(json.dumps([{**dict(r), "values_json": json.loads(r["values_json"])} for r in rows],
                         ensure_ascii=False, indent=2))
        return 0
    print(f"{'No':>5}  {'Ölçüm zamanı':<19}  {'Model':<8}  {'Danışan':<10}  {'Kilo':>6}")
    for r in rows:
        when = r["measured_at"] or r["received_at"]
        weight = f"{r['weight']:.1f}" if r["weight"] is not None else "-"
        print(f"{r['id']:>5}  {when:<19}  {r['model'] or '-':<8}  "
              f"{r['subject_id'] or '-':<10}  {weight:>6}")
    return 0


def cmd_export(args) -> int:
    with Store(args.veritabani) as store:
        count = store.export_csv(args.cikti, subject_id=args.danisan)
    print(f"{count} ölçüm {args.cikti} dosyasına yazıldı.")
    return 0


def cmd_gui(args) -> int:
    from .gui import main as gui_main  # noqa: PLC0415

    argv = (["--veritabani", args.veritabani] if args.veritabani else []) + \
        (["--port", args.port] if args.port else [])
    return gui_main(argv)


def cmd_report(args) -> int:
    from .report import main_from_args  # noqa: PLC0415

    return main_from_args(args)


def cmd_simulate(args) -> int:
    from .simulator import synthetic_record  # noqa: PLC0415

    port = _open(args)
    rng = random.Random(args.tohum)
    try:
        for i in range(args.adet):
            port.write(synthetic_record(subject=i + 1, rng=rng, model=args.model).encode("ascii"))
            port.flush()
            print(f"Sentetik ölçüm {i + 1}/{args.adet} gönderildi.", file=sys.stderr)
            if i + 1 < args.adet:
                time.sleep(args.aralik)
    finally:
        port.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tartim", description="Vücut kompozisyon analizörü okuyucusu")
    p.add_argument("--surum", action="version", version=f"tartim {__version__}")
    p.add_argument("--veritabani", help="SQLite dosyası (varsayılan: ~/.local/share/tartim/tartim.db)")
    sub = p.add_subparsers(dest="komut", required=True)

    s = sub.add_parser("portlar", help="Seri portları listele")
    s.set_defaults(func=cmd_ports)

    s = sub.add_parser("dinle", help="Cihazı dinle, ölçümleri göster ve kaydet")
    _port_args(s)
    s.add_argument("--kaydetme", action="store_true", help="Veritabanına yazma")
    s.add_argument("--ham-dosya", help="Gelen ham baytları bu dosyaya da ekle")
    s.add_argument("--adet", type=int, help="Bu kadar kayıttan sonra çık")
    s.set_defaults(func=cmd_listen)

    s = sub.add_parser("ham", help="Protokol keşfi için ham veriyi kaydet")
    _port_args(s)
    s.add_argument("--cikti", help="Çıktı dosyası (varsayılan: ekran)")
    s.set_defaults(func=cmd_raw)

    s = sub.add_parser("ice-aktar", help="SD kart CSV dosyalarını içe aktar")
    s.add_argument("dosyalar", nargs="+")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("listele", help="Kayıtlı ölçümleri listele")
    s.add_argument("--son", type=int, default=20)
    s.add_argument("--danisan", help="Danışan numarası")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("disa-aktar", help="Ölçümleri CSV olarak dışa aktar (Excel uyumlu)")
    s.add_argument("--cikti", required=True)
    s.add_argument("--danisan")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("arayuz", help="Masaüstü arayüzünü aç")
    s.add_argument("--port", help="Açılışta seçili olacak port")
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("rapor", help="Geliştiricilere gönderilecek cihaz raporu hazırla")
    s.add_argument("--port", help="Belirtilmezse otomatik bulunur")
    s.add_argument("--baud", type=int, help="varsayılan: 9600")
    s.add_argument("--sure", type=float, default=180, help="Ölçüm için bekleme süresi, saniye")
    s.add_argument("--cikti", help="Rapor dosyası (varsayılan: tartim-rapor-MODEL-TARIH.json)")
    s.add_argument("--dosya", nargs="+", help="Seri port yerine SD kart dosyalarını kullan")
    s.add_argument("--ayrintili", action="store_true",
                   help="Daha fazla soru sor (cihaz ayarları, ekrandaki tüm değerler)")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("simule", help="Sanal tartı: porta sentetik ölçüm gönder")
    _port_args(s)
    s.add_argument("--adet", type=int, default=3)
    s.add_argument("--aralik", type=float, default=2.0, help="saniye")
    s.add_argument("--model", default="MC-780")
    s.add_argument("--tohum", type=int, help="Tekrarlanabilir değerler için")
    s.set_defaults(func=cmd_simulate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
