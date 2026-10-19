"""Printable result sheet (PDF) of a measurement.

Page 1 analyses one measurement (body composition, segmental analysis,
metabolism, assessment against reference ranges, mass analysis). Page 2 shows
the client's progress: a difference table and chart of earlier measurements.

The sheet carries no device vendor's or dealer's branding: it identifies the
open-source project instead. It needs ReportLab (``sudo apt install
python3-reportlab``) and a TrueType font with Turkish letters (DejaVu Sans on
Pardus).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__, reference
from .i18n import N_, _, current_language
from .protocol import Measurement, parse

PROJECT_URL = "github.com/muratGursel/tartim"
BLUE = "#1f5fa8"
LIGHT = "#e8eff8"
GRID = "#9fb3c8"

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    (r"C:\Windows\Fonts\DejaVuSans.ttf", r"C:\Windows\Fonts\DejaVuSans-Bold.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
]

# Segment columns: (label, fat % code, muscle kg code)
SEGMENTS = [
    (N_("Right arm"), "FR", "mR"),
    (N_("Left arm"), "FL", "mL"),
    (N_("Right leg"), "Fr", "mr"),
    (N_("Left leg"), "Fl", "ml"),
    (N_("Trunk"), "FT", "mT"),
]


@dataclass
class Entry:
    """One stored measurement with its record number and time."""
    record_id: int
    when: datetime
    m: Measurement

    @classmethod
    def from_row(cls, row) -> "Entry":
        m = parse(row["raw"])
        when = m.measured_at() or datetime.fromisoformat(row["measured_at"] or row["received_at"])
        return cls(row["id"], when, m)

    def get(self, code: str) -> float | None:
        value = self.m.values.get(code)
        return value if isinstance(value, (int, float)) else None


def entries(store, record_id: int | None = None,
            subject_id: str | None = None) -> tuple[Entry, list[Entry]]:
    """The measurement to print and the client's history (oldest first, including it)."""
    if record_id is not None:
        row = store.get(record_id)
        if row is None:
            raise LookupError(_("No measurement with number {number}.").format(number=record_id))
    else:
        rows = store.list(limit=1, subject_id=subject_id)
        if not rows:
            raise LookupError(_("There are no saved measurements to print."))
        row = rows[0]
    current = Entry.from_row(row)
    if current.m.subject_id is None:
        return current, [current]
    history = [Entry.from_row(r) for r in store.list(subject_id=current.m.subject_id)
               if r["id"] <= current.record_id and parse(r["raw"]).recognized]
    history.sort(key=lambda e: (e.when, e.record_id))
    return current, history


# --- Formatting ----------------------------------------------------------------

def number(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "–"
    text = f"{value:.{decimals}f}"
    return text.replace(".", ",") if current_language() == "tr" else text


def signed(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return ""
    return ("+" if value > 0 else "") + number(value, decimals)


def when_text(when: datetime) -> str:
    if current_language() == "tr":
        return f"{when:%d.%m.%Y %H:%M}"
    return f"{when:%Y-%m-%d %H:%M}"


def date_text(when: datetime) -> str:
    return f"{when:%d.%m.%Y}" if current_language() == "tr" else f"{when:%Y-%m-%d}"


# --- PDF ------------------------------------------------------------------------

def _require_reportlab():
    try:
        import reportlab  # noqa: F401, PLC0415
    except ImportError as exc:
        raise RuntimeError(_("Creating the result sheet needs ReportLab. To install it on "
                             "Pardus: sudo apt install python3-reportlab")) from exc


def _fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics  # noqa: PLC0415
    from reportlab.pdfbase.ttfonts import TTFont  # noqa: PLC0415

    if "Tartim" in pdfmetrics.getRegisteredFontNames():
        return "Tartim", "Tartim-Bold"
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("Tartim", regular))
            pdfmetrics.registerFont(TTFont("Tartim-Bold", bold))
            return "Tartim", "Tartim-Bold"
    raise RuntimeError(_("No font with Turkish letters was found. Install it with: "
                         "sudo apt install fonts-dejavu-core"))


class _Sheet:
    """Builds the flowables of the result sheet."""

    def __init__(self, current: Entry, history: list[Entry], client_name: str):
        from reportlab.lib import colors  # noqa: PLC0415
        from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
        from reportlab.lib.units import mm  # noqa: PLC0415

        self.colors, self.mm = colors, mm
        self.font, self.bold = _fonts()
        self.current, self.history, self.client_name = current, history, client_name
        self.width = 186 * mm
        base = dict(fontName=self.font, fontSize=8.5, leading=11)
        self.style = ParagraphStyle("body", **base)
        self.small = ParagraphStyle("small", **{**base, "fontSize": 7.5, "leading": 9.5})
        self.title = ParagraphStyle("title", **{**base, "fontName": self.bold, "fontSize": 15,
                                               "leading": 18, "textColor": colors.HexColor(BLUE)})
        self.heading = ParagraphStyle("heading", **{**base, "fontName": self.bold,
                                                   "fontSize": 10, "leading": 13,
                                                   "textColor": colors.HexColor(BLUE)})

    # Basic building blocks

    def p(self, text: str, style=None):
        from reportlab.platypus import Paragraph  # noqa: PLC0415

        return Paragraph(text, style or self.style)

    def table(self, rows, widths, header=True, align="CENTER", extra=()):
        from reportlab.platypus import Table, TableStyle  # noqa: PLC0415

        c = self.colors
        commands = [
            ("FONT", (0, 0), (-1, -1), self.font, 8),
            ("GRID", (0, 0), (-1, -1), 0.4, c.HexColor(GRID)),
            ("ALIGN", (0, 0), (-1, -1), align),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        if header:
            commands += [("BACKGROUND", (0, 0), (-1, 0), c.HexColor(LIGHT)),
                         ("FONT", (0, 0), (-1, 0), self.bold, 8)]
        table = Table(rows, colWidths=widths)
        table.setStyle(TableStyle(commands + list(extra)))
        return table

    def section(self, title: str, *content, width=None):
        """A titled box around its content."""
        from reportlab.platypus import Table, TableStyle  # noqa: PLC0415

        width = width or self.width
        rows = [[self.p(title, self.heading)]] + [[item] for item in content]
        box = Table(rows, colWidths=[width])
        box.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, self.colors.HexColor(BLUE)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, self.colors.HexColor(BLUE)),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return box

    def side_by_side(self, left, right, gap=None):
        from reportlab.platypus import Table, TableStyle  # noqa: PLC0415

        gap = gap if gap is not None else 4 * self.mm
        half = (self.width - gap) / 2
        table = Table([[left, "", right]], colWidths=[half, gap, half])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        return table

    def bar_chart(self, labels, values, width, height, decimals=1):
        from reportlab.graphics.charts.barcharts import VerticalBarChart  # noqa: PLC0415
        from reportlab.graphics.shapes import Drawing  # noqa: PLC0415

        drawing = Drawing(width, height)
        chart = VerticalBarChart()
        chart.x, chart.y = 26, 22
        chart.width, chart.height = width - 34, height - 34
        chart.data = [[v or 0 for v in values]]
        chart.categoryAxis.categoryNames = labels
        chart.categoryAxis.labels.fontName = self.font
        chart.categoryAxis.labels.fontSize = 6.5
        chart.valueAxis.labels.fontName = self.font
        chart.valueAxis.labels.fontSize = 6.5
        chart.valueAxis.valueMin = 0
        chart.valueAxis.visibleGrid = True
        chart.valueAxis.gridStrokeColor = self.colors.HexColor("#dde5ee")
        chart.bars[0].fillColor = self.colors.HexColor("#6f93bf")
        chart.bars[0].strokeColor = self.colors.HexColor(BLUE)
        chart.barLabels.fontName = self.font
        chart.barLabels.fontSize = 6.5
        chart.barLabels.nudge = 6
        chart.barLabelFormat = lambda v: number(v, decimals)
        drawing.add(chart)
        return drawing

    # Page parts

    def header(self):
        from reportlab.graphics.shapes import Drawing, Rect, String  # noqa: PLC0415
        from reportlab.platypus import Table, TableStyle  # noqa: PLC0415

        c, mm = self.colors, self.mm
        icon = Drawing(16 * mm, 16 * mm)
        icon.add(Rect(0, 0, 16 * mm, 16 * mm, rx=3 * mm, ry=3 * mm,
                      fillColor=c.HexColor(BLUE), strokeColor=None))
        icon.add(Rect(2 * mm, 2 * mm, 12 * mm, 12 * mm, rx=2 * mm, ry=2 * mm,
                      fillColor=c.HexColor("#f4f7fb"), strokeColor=None))
        icon.add(Rect(3.6 * mm, 9 * mm, 8.8 * mm, 3.6 * mm, rx=0.8 * mm, ry=0.8 * mm,
                      fillColor=c.HexColor("#16324f"), strokeColor=None))
        icon.add(String(8 * mm, 9.9 * mm, "72.4", fontName=self.bold, fontSize=6.5,
                        fillColor=c.HexColor("#7fe0a0"), textAnchor="middle"))
        model = self.current.m.model or _("Body composition analyzer")
        title = [self.p(_("SEGMENTAL BODY COMPOSITION ANALYSIS"), self.title),
                 self.p(_("Device: {model} · tartim {version}").format(
                     model=model, version=__version__), self.small)]
        info = self.table([[_("Measured at")], [when_text(self.current.when)],
                           [_("Record no: {number}").format(number=self.current.record_id)]],
                          [42 * mm], header=True)
        table = Table([[icon, title, info]], colWidths=[20 * mm, 124 * mm, 42 * mm])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        return table

    def client_row(self):
        from .fields import describe  # noqa: PLC0415

        e, mm = self.current, self.mm
        bmi = e.get("MI") or reference.bmi(e.get("Wk"), e.get("Hm"))
        gender = describe("GE").display(e.get("GE")) if e.get("GE") is not None else "–"
        body = describe("Bt").display(e.get("Bt")) if e.get("Bt") is not None else "–"
        name = self.client_name or (_("Client {number}").format(number=e.m.subject_id)
                                    if e.m.subject_id else "–")
        rows = [[_("Name"), _("Gender"), _("Body type"), _("Age"), _("Height"), _("Weight"),
                 "BMI", _("Body fat %")],
                [name, gender, body, number(e.get("AG"), 0), number(e.get("Hm"), 1),
                 number(e.get("Wk")), number(bmi), number(e.get("FW"))]]
        return self.table(rows, [52 * mm, 20 * mm, 22 * mm, 14 * mm, 18 * mm, 20 * mm, 18 * mm,
                                 22 * mm])

    def has_segments(self) -> bool:
        return any(self.current.get(code) is not None
                   for _label, fat, muscle in SEGMENTS for code in (fat, muscle))

    def composition(self, width, height):
        e = self.current
        labels = [_("Weight"), _("Fat"), _("Water"), _("Fat-free"), _("Muscle"), _("Bone")]
        values = [e.get("Wk"), e.get("fW"), e.get("wW"), e.get("MW"), e.get("mW"), e.get("bW")]
        chart = self.bar_chart(labels, values, width - 8, height)
        return self.section(_("Body composition (kg)"), chart, width=width)

    def silhouette(self, width):
        """A simple body figure with each segment's muscle mass and fat percentage."""
        from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String  # noqa: PLC0415

        c, e = self.colors, self.current
        w, h = width - 8, 62 * self.mm
        drawing = Drawing(w, h)
        body = dict(fillColor=c.HexColor("#c9d8ea"), strokeColor=c.HexColor("#6f93bf"),
                    strokeWidth=0.8, strokeLineJoin=1)
        # The figure is drawn on a grid of 100 x 180 units: dx from the centre line,
        # dy downwards from the top of the head; it is scaled to the box height.
        cx, top, scale = w / 2, h - 3, (h - 6) / 180

        def at(dx, dy):
            return cx + dx * scale, top - dy * scale

        def shape(points, mirrored=False):
            flat = []
            for dx, dy in points:
                flat.extend(at(-dx if mirrored else dx, dy))
            return Polygon(flat, **body)

        arm = [(-27, 33), (-34, 37), (-38, 50), (-41, 76), (-45, 102), (-44, 109),
               (-37, 110), (-36, 102), (-33, 78), (-29, 56)]
        leg = [(-22, 103), (-1, 103), (-3, 140), (-4, 169), (-2, 176), (-15, 178),
               (-16, 169), (-18, 140)]
        torso = [(-11, 27), (11, 27), (25, 32), (30, 41), (26, 68), (21, 90), (23, 104),
                 (-23, 104), (-21, 90), (-26, 68), (-30, 41), (-25, 32)]
        for points in (arm, leg):
            drawing.add(shape(points))
            drawing.add(shape(points, mirrored=True))
        for side in (-1, 1):
            drawing.add(Circle(*at(side * 41, 112), 4.5 * scale, **body))            # hands
        drawing.add(shape([(-5, 20), (5, 20), (6, 30), (-6, 30)]))                    # neck
        drawing.add(shape(torso))
        drawing.add(Circle(*at(0, 11), 11 * scale, **body))                           # head

        muscle_colour, fat_colour = c.HexColor(BLUE), c.HexColor("#e8a33d")
        lead = dict(strokeColor=c.HexColor("#16324f"), strokeWidth=0.6)
        label_width = 46

        def label(lx, ly, name, muscle, fat, target, left_side):
            drawing.add(String(lx, ly, name, fontName=self.bold, fontSize=7))
            for i, (colour, text) in enumerate([(muscle_colour, f"{number(muscle)} kg"),
                                                (fat_colour, f"{number(fat)} %")]):
                row = ly - 10 - i * 9
                drawing.add(Rect(lx, row - 1, 6, 6, fillColor=colour, strokeColor=None))
                drawing.add(String(lx + 9, row, text, fontName=self.font, fontSize=7))
            start_x = lx + label_width if left_side else lx - 3
            drawing.add(Line(start_x, ly - 7, *at(*target), **lead))

        # The figure faces the reader: its right side is on the reader's left.
        right_x, left_x = 4, w - label_width
        values = {fat: (e.get(muscle), e.get(fat)) for _label, fat, muscle in SEGMENTS}
        arm_y, leg_y = at(0, 62)[1], at(0, 128)[1]
        label(right_x, arm_y, _("Right arm"), *values["FR"], (-38, 70), True)
        label(left_x, arm_y, _("Left arm"), *values["FL"], (38, 70), False)
        label(right_x, leg_y, _("Right leg"), *values["Fr"], (-10, 135), True)
        label(left_x, leg_y, _("Left leg"), *values["Fl"], (10, 135), False)
        label(left_x, at(0, 12)[1], _("Trunk"), *values["FT"], (8, 62), False)
        # Legend
        for i, (colour, text) in enumerate([(muscle_colour, _("Muscle (kg)")),
                                            (fat_colour, _("Fat (%)"))]):
            row = at(0, 6)[1] - i * 10
            drawing.add(Rect(right_x, row - 1, 6, 6, fillColor=colour, strokeColor=None))
            drawing.add(String(right_x + 9, row, text, fontName=self.font, fontSize=7))
        return self.section(_("Segmental distribution"), drawing, width=width)

    def left_column(self, width):
        """Body composition, with the body figure below it when segments are known."""
        from reportlab.platypus import Spacer, Table, TableStyle  # noqa: PLC0415

        if not self.has_segments():
            return self.composition(width, 84 * self.mm)
        column = Table([[self.composition(width, 44 * self.mm)], [Spacer(1, 3 * self.mm)],
                        [self.silhouette(width)]], colWidths=[width])
        column.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return column

    def segmental(self, width):
        e, mm = self.current, self.mm
        has_fat = any(e.get(f) is not None for _label, f, _m in SEGMENTS)
        has_muscle = any(e.get(m) is not None for _label, _f, m in SEGMENTS)
        if not (has_fat or has_muscle):
            return self.section(_("Segmental analysis"), self.p(
                _("This device does not report segmental values."), self.small), width=width)
        labels = [_(label) for label, _f, _m in SEGMENTS]
        column = (width - 8 - 22 * mm) / 5
        rows = [[""] + labels]
        if has_fat:
            rows.append([_("Fat (%)")] + [number(e.get(f)) for _l, f, _m in SEGMENTS])
        if has_muscle:
            rows.append([_("Muscle (kg)")] + [number(e.get(m)) for _l, _f, m in SEGMENTS])
        content = [self.table(rows, [22 * mm] + [column] * 5,
                              extra=[("FONT", (0, 0), (-1, 0), self.bold, 6.5)])]
        short = [_("R arm"), _("L arm"), _("R leg"), _("L leg"), _("Trunk")]
        if has_muscle:
            content.append(self.p(_("Segmental muscle (kg)"), self.small))
            content.append(self.bar_chart(short, [e.get(m) for _l, _f, m in SEGMENTS],
                                          width - 8, 28 * mm))
        if has_fat:
            content.append(self.p(_("Segmental fat (%)"), self.small))
            content.append(self.bar_chart(short, [e.get(f) for _l, f, _m in SEGMENTS],
                                          width - 8, 28 * mm))
        return self.section(_("Segmental analysis"), *content, width=width)

    def metabolism(self):
        e, mm = self.current, self.mm
        bmr = e.get("rB")
        weight = e.get("Wk")
        rows = [[_("Metabolic age"), _("Basal metabolic rate"), "", _("BMR / kg"),
                 _("Visceral fat rating")],
                [number(e.get("rA"), 0), f"{number(bmr, 0)} kcal",
                 f"{number(bmr * 4.184 if bmr else None, 0)} kJ",
                 number(bmr / weight if bmr and weight else None, 1), number(e.get("IF"), 0)]]
        table = self.table(rows, [36 * mm, 34 * mm, 34 * mm, 36 * mm, 38 * mm],
                           extra=[("SPAN", (1, 0), (2, 0))])
        return self.section(_("Metabolism"), table)

    def metabolism_compact(self, width):
        """The metabolism values as a label / value list for a half-width column."""
        e = self.current
        bmr, weight = e.get("rB"), e.get("Wk")
        rows = [[_("Metabolic age"), number(e.get("rA"), 0)],
                [_("Basal metabolic rate"), f"{number(bmr, 0)} kcal · "
                                            f"{number(bmr * 4.184 if bmr else None, 0)} kJ"],
                [_("BMR / kg"), number(bmr / weight if bmr and weight else None, 1)],
                [_("Visceral fat rating"), number(e.get("IF"), 0)]]
        inner = width - 8
        table = self.table(rows, [inner * 0.55, inner * 0.45], header=False,
                           extra=[("ALIGN", (0, 0), (0, -1), "LEFT")])
        return self.section(_("Metabolism"), table, width=width)

    def right_column(self, width):
        from reportlab.platypus import Spacer, Table, TableStyle  # noqa: PLC0415

        column = Table([[self.segmental(width)], [Spacer(1, 3 * self.mm)],
                        [self.metabolism_compact(width)]], colWidths=[width])
        column.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        return column

    def scale(self, title: str, value: str, rng: reference.Range | None, raw: float | None,
              unit: str, width):
        """Low / normal / high boxes with an X under the matching one."""
        mm = self.mm
        if rng is None or raw is None:
            return self.section(f"{title}: {value}", self.p(
                _("No reference range for this measurement (adults, gender and age needed)."),
                self.small), width=width)
        cls = rng.classify(raw)
        low = f"{_('Low')} < {number(rng.low)}{unit}"
        normal = f"{_('Normal')} ({number(rng.low)} – {number(rng.high)}{unit})"
        high = f"{_('High')} > {number(rng.high)}{unit}"
        marks = ["X" if cls == key else "" for key in (reference.LOW, reference.NORMAL,
                                                        reference.HIGH)]
        inner = width - 8
        table = self.table([[low, normal, high], marks], [inner * 0.28, inner * 0.44, inner * 0.28],
                           extra=[("FONT", (0, 0), (-1, 0), self.bold, 6.5),
                                  ("FONT", (0, 1), (-1, 1), self.bold, 10)])
        return self.section(f"{title}: {value}", table, width=width)

    def assessment(self):
        e, mm = self.current, self.mm
        gender, age = e.get("GE"), e.get("AG")
        bmi = e.get("MI") or reference.bmi(e.get("Wk"), e.get("Hm"))
        half = (self.width - 4 * mm) / 2
        water_pct = e.get("ww")
        if water_pct is None and e.get("wW") and e.get("Wk"):
            water_pct = e.get("wW") / e.get("Wk") * 100
        blocks = [
            self.scale("BMI", number(bmi), reference.BMI, bmi, "", half),
            self.scale(_("Body fat"), f"{number(e.get('fW'))} kg · {number(e.get('FW'))} %",
                       reference.fat_range(gender, age), e.get("FW"), "%", half),
            self.scale(_("Body water"), f"{number(e.get('wW'))} kg · {number(water_pct)} %",
                       reference.water_range(gender, age), water_pct, "%", half),
            self.scale(_("Visceral fat rating"), number(e.get("IF"), 0), reference.VISCERAL,
                       e.get("IF"), "", half),
        ]
        items = [self.side_by_side(blocks[0], blocks[1]), self.side_by_side(blocks[2], blocks[3])]
        weights = reference.weight_range(e.get("Hm"))
        if weights:
            lower, ideal, upper = weights
            items.insert(0, self.p(_("Ideal weight (BMI 22): {ideal} kg · normal range "
                                     "{lower} – {upper} kg").format(
                ideal=number(ideal), lower=number(lower), upper=number(upper))))
        return items

    def mass_analysis(self):
        e, mm = self.current, self.mm
        ecw, tbw = e.get("wO"), e.get("wW")
        items = [(label, f"{number(value)} kg") for label, value in [
            (_("Muscle mass"), e.get("mW")), (_("Fat-free mass (FFM)"), e.get("MW")),
            (_("Bone mass"), e.get("bW")), (_("Total body water mass"), tbw),
            (_("Intracellular water"), e.get("wI")), (_("Extracellular water"), ecw),
        ] if value is not None]
        if ecw and tbw:
            items.append((_("Extracellular / total water"), number(ecw / tbw, 3)))
        if not items:
            items.append((_("No values"), "–"))
        if len(items) % 2:
            items.append(("", ""))
        half = len(items) // 2
        rows = [[a[0], a[1], b[0], b[1]] for a, b in zip(items[:half], items[half:])]
        table = self.table(rows, [62 * mm, 27 * mm, 62 * mm, 27 * mm], header=False,
                           extra=[("ALIGN", (0, 0), (0, -1), "LEFT"),
                                  ("ALIGN", (2, 0), (2, -1), "LEFT")])
        return self.section(_("Mass analysis"), table)

    def progress(self):
        """Page 2: difference table and chart of the client's measurements."""
        from reportlab.graphics.charts.legends import Legend  # noqa: PLC0415
        from reportlab.graphics.charts.linecharts import HorizontalLineChart  # noqa: PLC0415
        from reportlab.graphics.shapes import Drawing  # noqa: PLC0415

        mm, c = self.mm, self.colors
        series = [(_("Weight"), "Wk"), (_("Fat kg"), "fW"), (_("Muscle kg"), "mW"),
                  (_("Water kg"), "wW"), (_("Fat-free kg"), "MW"), (_("Body fat %"), "FW")]
        header = [_("Measured at")]
        for label, _code in series:
            header += [label, _("Diff.")]
        rows = [header]
        newest_first = list(reversed(self.history))
        for i, e in enumerate(newest_first):
            older = newest_first[i + 1] if i + 1 < len(newest_first) else None
            row = [when_text(e.when)]
            for _label, code in series:
                value = e.get(code)
                diff = value - older.get(code) if older and value is not None \
                    and older.get(code) is not None else None
                row += [number(value), signed(diff)]
            rows.append(row)
        widths = [26 * mm] + [14 * mm, 11 * mm] * 6
        table = self.table(rows, widths, extra=[("FONT", (0, 0), (-1, -1), self.font, 6.5),
                                                ("FONT", (0, 0), (-1, 0), self.bold, 6.5)])

        recent = self.history[-10:]
        drawing = Drawing(self.width - 8, 95 * mm)
        chart = HorizontalLineChart()
        chart.x, chart.y = 28, 26
        chart.width, chart.height = self.width - 8 - 120, 95 * mm - 40
        plotted = [(label, code) for label, code in series[:4]
                   if any(e.get(code) is not None for e in recent)]
        chart.data = [[e.get(code) or 0 for e in recent] for _label, code in plotted]
        chart.categoryAxis.categoryNames = [f"{date_text(e.when)} ({i + 1})"
                                            for i, e in enumerate(recent)]
        for axis in (chart.categoryAxis.labels, chart.valueAxis.labels):
            axis.fontName, axis.fontSize = self.font, 6.5
        chart.categoryAxis.labels.angle = 20
        chart.categoryAxis.labels.dy = -6
        chart.valueAxis.valueMin = 0
        chart.valueAxis.visibleGrid = True
        chart.valueAxis.gridStrokeColor = c.HexColor("#dde5ee")
        palette = ["#1f5fa8", "#c0392b", "#2e8b57", "#d68910"]
        for i in range(len(plotted)):
            chart.lines[i].strokeColor = c.HexColor(palette[i])
            chart.lines[i].strokeWidth = 1.6
        chart.lineLabelFormat = lambda v: number(v)
        chart.lineLabels.fontName = self.font
        chart.lineLabels.fontSize = 6
        drawing.add(chart)
        legend = Legend()
        legend.x, legend.y = self.width - 8 - 80, 95 * mm - 20
        legend.fontName, legend.fontSize = self.font, 7.5
        legend.columnMaximum = 4
        legend.alignment = "right"
        legend.colorNamePairs = [(c.HexColor(palette[i]), label)
                                 for i, (label, _code) in enumerate(plotted)]
        drawing.add(legend)
        return [self.section(_("Difference analysis"), table),
                self.section(_("Progress chart (kg)"), drawing)]

    def story(self):
        from reportlab.platypus import PageBreak, Spacer  # noqa: PLC0415

        mm = self.mm
        gap = Spacer(1, 3 * mm)
        half = (self.width - 4 * mm) / 2
        story = [self.header(), gap, self.client_row(), gap,
                 ]
        if self.has_segments():
            # The body figure makes the left column taller; metabolism moves to the right.
            story += [self.side_by_side(self.left_column(half), self.right_column(half)), gap]
        else:
            story += [self.side_by_side(self.left_column(half), self.segmental(half)), gap,
                      self.metabolism(), gap]
        story += self.assessment()
        story += [gap, self.mass_analysis()]
        if len(self.history) >= 2:
            story += [PageBreak(), self.header(), gap, self.client_row(), gap]
            story += self.progress()
        return story


def write_pdf(path: str | Path, current: Entry, history: list[Entry],
              client_name: str = "") -> Path:
    """Writes the result sheet and returns its path."""
    _require_reportlab()
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import SimpleDocTemplate  # noqa: PLC0415

    sheet = _Sheet(current, history, client_name.strip())
    printed = datetime.now()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColorRGB(0.12, 0.37, 0.66)
        canvas.line(12 * mm, 16 * mm, 198 * mm, 16 * mm)
        canvas.setFont(sheet.bold, 7.5)
        canvas.drawString(12 * mm, 12 * mm, _("tartim · open-source software (GPL-3.0-or-later)"))
        canvas.setFont(sheet.font, 7.5)
        canvas.drawString(12 * mm, 8.5 * mm, PROJECT_URL)
        canvas.drawCentredString(105 * mm, 12 * mm, _("Report printed: {when}").format(
            when=when_text(printed)))
        canvas.drawCentredString(105 * mm, 8.5 * mm, _("Record no: {number}").format(
            number=current.record_id))
        canvas.drawRightString(198 * mm, 12 * mm, _("Not a medical diagnosis."))
        canvas.drawRightString(198 * mm, 8.5 * mm, _("Page {page}").format(page=doc.page))
        canvas.restoreState()

    path = Path(path)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=10 * mm, bottomMargin=20 * mm,
                            title=_("Body composition analysis"), author="tartim",
                            creator=f"tartim {__version__} ({PROJECT_URL})")
    doc.build(sheet.story(), onFirstPage=footer, onLaterPages=footer)
    return path


def default_name(current: Entry) -> str:
    client = current.m.subject_id or "0"
    return _("result") + f"-{client}-{current.when:%Y%m%d-%H%M}.pdf"
