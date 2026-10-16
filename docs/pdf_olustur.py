"""docs/KULLANIM.md dosyasından yazdırılabilir PDF kılavuz üretir.

Gerekenler: python3-markdown ve Chrome / Chromium / Edge.

    python3 docs/pdf_olustur.py            # docs/Tartim-Kullanim-Kilavuzu.pdf
    python3 docs/pdf_olustur.py --html     # yalnızca HTML (kontrol için)
"""

import argparse
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
SOURCE = DOCS / "KULLANIM.md"
OUTPUT = DOCS / "Tartim-Kullanim-Kilavuzu.pdf"

BROWSERS = [
    "chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-center { content: counter(page) " / " counter(pages); font: 9pt sans-serif; color: #667; }
  @bottom-left { content: "Tartım Kullanım Kılavuzu"; font: 9pt sans-serif; color: #667; }
}
@page :first { @bottom-center { content: none; } @bottom-left { content: none; } }
html { font-family: "Noto Sans", "DejaVu Sans", "Segoe UI", Arial, sans-serif; font-size: 10.5pt;
       color: #1d2733; line-height: 1.5; }
body { margin: 0; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center;
         page-break-after: always; }
.cover .brand { width: 26mm; height: 26mm; margin-bottom: 10mm; }
.cover h1 { font-size: 30pt; margin: 0 0 4mm; color: #1f5fa8; border: none; }
.cover p { font-size: 13pt; margin: 0 0 2mm; color: #445; }
.cover .meta { margin-top: 14mm; font-size: 10pt; color: #667; }
h1 { display: none; }
h2 { font-size: 16pt; color: #1f5fa8; border-bottom: 2px solid #d5e2f2; padding-bottom: 2mm;
     margin: 0 0 4mm; page-break-before: always; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 6mm 0 2mm; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1f5fa8; text-decoration: none; }
code { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 9pt; background: #eef2f7;
       padding: 0 1mm; border-radius: 1mm; }
pre { background: #eef2f7; padding: 3mm 4mm; border-radius: 2mm; white-space: pre-wrap;
      word-break: break-all; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
img { display: block; max-width: 100%; max-height: 120mm; margin: 3mm 0 4mm;
      border: 1px solid #c9d3df; border-radius: 2mm; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9.5pt;
        page-break-inside: avoid; }
th, td { border: 1px solid #c9d3df; padding: 1.5mm 2.5mm; vertical-align: top; text-align: left; }
th { background: #eef2f7; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; border-left: 3px solid #1f5fa8; background: #f3f7fc;
             color: #334; }
blockquote p { margin: 0; }
hr { display: none; }
.toc-title { font-size: 16pt; color: #1f5fa8; margin: 0 0 4mm; }
"""


def slugify(value: str, separator: str = "-") -> str:
    """GitHub'ın başlık bağlantılarıyla aynı biçim (Türkçe harfler korunur)."""
    value = unicodedata.normalize("NFC", value).lower()
    value = re.sub(r"[^\w\- ]", "", value)
    return value.replace(" ", separator)


LIST_ITEM = re.compile(r"^(?:[-*] |\d+\. )")


def normalize_indent(text: str) -> str:
    """GitHub 3 boşluklu liste girintisini kabul eder, Python-Markdown 4 ister."""
    out, fence = [], False
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.startswith("```"):
            fence = not fence if indent == 0 else fence
        if stripped and 0 < indent and (not fence or indent % 4):
            line = " " * (math.ceil(indent / 3) * 4) + stripped
        # Bir metin satırının hemen altında başlayan alt liste, Python-Markdown'da
        # paragrafın devamı sayılır; araya boş satır koy.
        if not fence and LIST_ITEM.match(stripped) and out and out[-1].strip()                 and not LIST_ITEM.match(out[-1].lstrip()):
            out.append("")
        out.append(line)
    return "\n".join(out)


def build_html(version: str) -> str:
    text = SOURCE.read_text(encoding="utf-8")
    # Elle yazılmış içindekiler listesi yerine PDF'te kendi listemizi koyuyoruz.
    text = re.sub(r"\*\*İçindekiler\*\*\n\n(?:\d+\. .*\n)+", "", text)
    body = markdown.markdown(normalize_indent(text),
                             extensions=["tables", "fenced_code", "toc", "sane_lists"],
                             extension_configs={"toc": {"slugify": slugify, "toc_depth": "2-2"}})
    toc = markdown.Markdown(extensions=["toc"],
                            extension_configs={"toc": {"slugify": slugify, "toc_depth": "2-2"}})
    toc.convert(normalize_indent(text))
    images = (DOCS / "ekran").resolve().as_uri()
    body = body.replace('src="ekran/', f'src="{images}/')
    icon = (ROOT / "packaging/debian/io.github.muratgursel.Tartim.svg").resolve().as_uri()
    cover = f"""
<section class="cover">
  <img class="brand" src="{icon}" alt="" style="border:none">
  <h1 style="display:block">Tartım</h1>
  <p>Vücut analiz cihazları için kullanım kılavuzu</p>
  <p>Kurulum · Kablolu ve Bluetooth bağlantı · Ölçüm · Cihaz raporu</p>
  <div class="meta">Sürüm {version} · {date.today():%d.%m.%Y}<br>
  https://github.com/muratGursel/tartim</div>
</section>
<section>
  <div class="toc-title">İçindekiler</div>
  {toc.toc}
</section>"""
    return (f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
            f"<title>Tartım Kullanım Kılavuzu</title><style>{CSS}</style></head>"
            f"<body>{cover}{body}</body></html>")


def find_browser() -> str:
    for name in BROWSERS:
        found = shutil.which(name) or (name if Path(name).exists() else None)
        if found:
            return found
    raise SystemExit("Chrome, Chromium ya da Edge bulunamadı.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", action="store_true", help="Yalnızca HTML yaz")
    parser.add_argument("--cikti", default=str(OUTPUT))
    args = parser.parse_args()
    version = re.search(r'__version__ = "(.+)"',
                        (ROOT / "tartim/__init__.py").read_text(encoding="utf-8")).group(1)
    html = build_html(version)
    if args.html:
        out = Path(args.cikti).with_suffix(".html")
        out.write_text(html, encoding="utf-8")
        print(out)
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "kilavuz.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={tmp}/profil", f"--print-to-pdf={Path(args.cikti).resolve()}",
                        page.as_uri()], check=True, capture_output=True, timeout=120)
    print(args.cikti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
