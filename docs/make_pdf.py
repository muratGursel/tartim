"""Builds the printable PDF user guides from the Markdown guides.

Needs python3-markdown and Chrome / Chromium / Edge.

    python3 docs/make_pdf.py              # both languages
    python3 docs/make_pdf.py --lang en    # docs/Tartim-User-Guide.pdf only
    python3 docs/make_pdf.py --html       # HTML only (for checking)
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

LANGUAGES = {
    "tr": {
        "source": "KULLANIM.md", "output": "Tartim-Kullanim-Kilavuzu.pdf",
        "title": "Tartım Kullanım Kılavuzu", "contents": "İçindekiler", "contents_md": "İçindekiler",
        "subtitle": "Vücut analiz cihazları için kullanım kılavuzu",
        "topics": "Kurulum · Kablolu ve Bluetooth bağlantı · Ölçüm · Cihaz raporu",
        "version": "Sürüm", "date": "%d.%m.%Y",
    },
    "en": {
        "source": "USER_GUIDE.md", "output": "Tartim-User-Guide.pdf",
        "title": "Tartım User Guide", "contents": "Contents", "contents_md": "Contents",
        "subtitle": "User guide for body composition analyzers",
        "topics": "Installation · Wired and Bluetooth connection · Measurements · Device report",
        "version": "Version", "date": "%Y-%m-%d",
    },
}

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
  @bottom-left { content: "@FOOTER@"; font: 9pt sans-serif; color: #667; }
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
img { display: block; max-width: 100%; max-height: 95mm; margin: 3mm 0 4mm;
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
    """Same format as GitHub's heading anchors (Turkish letters are kept)."""
    value = unicodedata.normalize("NFC", value).lower()
    value = re.sub(r"[^\w\- ]", "", value)
    return value.replace(" ", separator)


LIST_ITEM = re.compile(r"^(?:[-*] |\d+\. )")


def normalize_indent(text: str) -> str:
    """GitHub accepts three-space list indentation; Python-Markdown wants four."""
    out, fence = [], False
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.startswith("```"):
            fence = not fence if indent == 0 else fence
        if stripped and 0 < indent and (not fence or indent % 4):
            line = " " * (math.ceil(indent / 3) * 4) + stripped
        # A list that starts right below a line of text counts as part of the
        # paragraph in Python-Markdown; put an empty line in between.
        if not fence and LIST_ITEM.match(stripped) and out and out[-1].strip() \
                and not LIST_ITEM.match(out[-1].lstrip()):
            out.append("")
        out.append(line)
    return "\n".join(out)


def build_html(language: str, version: str) -> str:
    cfg = LANGUAGES[language]
    text = (DOCS / cfg["source"]).read_text(encoding="utf-8")
    # The PDF gets its own table of contents instead of the hand-written one.
    text = re.sub(r"\*\*" + cfg["contents_md"] + r"\*\*\n\n(?:\d+\. .*\n)+", "", text)
    # The PDF download link only makes sense on GitHub.
    text = re.sub(r"^📄.*\n", "", text, flags=re.M)
    config = {"toc": {"slugify": slugify, "toc_depth": "2-2"}}
    body = markdown.markdown(normalize_indent(text),
                             extensions=["tables", "fenced_code", "toc", "sane_lists"],
                             extension_configs=config)
    toc = markdown.Markdown(extensions=["toc"], extension_configs=config)
    toc.convert(normalize_indent(text))
    shots = (DOCS / "screenshots").resolve().as_uri()
    body = body.replace('src="screenshots/', f'src="{shots}/')
    icon = (ROOT / "packaging/debian/io.github.muratgursel.Tartim.svg").resolve().as_uri()
    cover = f"""
<section class="cover">
  <img class="brand" src="{icon}" alt="" style="border:none">
  <h1 style="display:block">Tartım</h1>
  <p>{cfg["subtitle"]}</p>
  <p>{cfg["topics"]}</p>
  <div class="meta">{cfg["version"]} {version} · {date.today():{cfg["date"]}}<br>
  https://github.com/muratGursel/tartim</div>
</section>
<section>
  <div class="toc-title">{cfg["contents"]}</div>
  {toc.toc}
</section>"""
    css = CSS.replace("@FOOTER@", cfg["title"])
    return (f"<!doctype html><html lang='{language}'><head><meta charset='utf-8'>"
            f"<title>{cfg['title']}</title><style>{css}</style></head>"
            f"<body>{cover}{body}</body></html>")


def find_browser() -> str:
    for name in BROWSERS:
        found = shutil.which(name) or (name if Path(name).exists() else None)
        if found:
            return found
    raise SystemExit("Chrome, Chromium or Edge was not found.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=sorted(LANGUAGES), action="append",
                        help="Language (default: all)")
    parser.add_argument("--html", action="store_true", help="Write HTML only")
    args = parser.parse_args()
    version = re.search(r'__version__ = "(.+)"',
                        (ROOT / "tartim/__init__.py").read_text(encoding="utf-8")).group(1)
    for language in args.lang or sorted(LANGUAGES):
        html = build_html(language, version)
        output = DOCS / LANGUAGES[language]["output"]
        if args.html:
            out = output.with_suffix(".html")
            out.write_text(html, encoding="utf-8")
            print(out)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "guide.html"
            page.write_text(html, encoding="utf-8")
            subprocess.run([find_browser(), "--headless=new", "--disable-gpu",
                            "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
                            f"--print-to-pdf={output.resolve()}", page.as_uri()],
                           check=True, capture_output=True, timeout=120)
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
