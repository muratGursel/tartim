"""Meaning of the field codes in Tanita key-value records.

Tanita professional devices (MC-780, MC-980, BC-418, DC-360 ...) and the models
that write SD cards send a measurement as ``CODE,VALUE,CODE,VALUE,...``. Codes
are case sensitive: ``FW`` is fat percentage, ``fW`` is fat mass.

``confirmed`` tells whether the meaning of a code has been verified against a
real device. For now the sources are manuals and community notes (see
docs/PROTOCOL.md). Set ``confirmed=True`` for every code you verify on a real
device and send a pull request.

Labels are English source strings; ``Field.name`` returns the translation.
"""

from dataclasses import dataclass

from .i18n import N_, _


@dataclass(frozen=True)
class Field:
    code: str
    label: str
    unit: str = ""
    kind: str = "float"  # float | int | str
    confirmed: bool = False
    choices: tuple[tuple[int, str], ...] = ()
    known: bool = True

    @property
    def name(self) -> str:
        if not self.known:
            return _("Unknown field ({code})").format(code=self.code)
        return _(self.label)

    def display(self, value: object) -> str:
        """The value with its unit, or its meaning (e.g. gender: Female)."""
        for code, name in self.choices:
            if value == code:
                return _(name)
        unit = _(self.unit) if self.unit == YEARS else self.unit
        return f"{value} {unit}".rstrip()


YEARS = N_("years")

_FIELDS = [
    # Identity and measurement details
    Field("MO", N_("Device model"), kind="str"),
    Field("ID", N_("Client number"), kind="str"),
    Field("St", N_("Status"), kind="str"),
    Field("Da", N_("Date"), kind="str"),
    Field("DT", N_("Date"), kind="str"),
    Field("TI", N_("Time"), kind="str"),
    Field("Ti", N_("Time"), kind="str"),
    # Input values
    Field("Bt", N_("Body type"), kind="int",
          choices=((0, N_("Standard")), (2, N_("Athletic")))),
    Field("GE", N_("Gender"), kind="int", choices=((1, N_("Male")), (2, N_("Female")))),
    Field("AG", N_("Age"), YEARS, kind="int"),
    Field("Hm", N_("Height"), "cm"),
    Field("Pt", N_("Clothes weight (tare)"), "kg"),
    Field("AL", N_("Activity level"), kind="int"),
    # Whole-body analysis
    Field("Wk", N_("Weight"), "kg"),
    Field("MI", N_("Body mass index (BMI)")),
    Field("FW", N_("Body fat"), "%"),
    Field("fW", N_("Fat mass"), "kg"),
    Field("MW", N_("Fat-free mass (FFM)"), "kg"),
    Field("mW", N_("Muscle mass"), "kg"),
    Field("bW", N_("Bone mass"), "kg"),
    Field("ww", N_("Total body water"), "%"),
    Field("wW", N_("Total body water mass"), "kg"),
    Field("wI", N_("Intracellular water"), "kg"),
    Field("wO", N_("Extracellular water"), "kg"),
    Field("IF", N_("Visceral fat rating"), kind="int"),
    Field("rB", N_("Basal metabolic rate (BMR)"), "kcal", kind="int"),
    Field("rA", N_("Metabolic age"), YEARS, kind="int"),
    Field("LP", N_("Leg muscle score"), kind="int"),
    # Extra fields of standard Bluetooth scales (codes specific to tartim)
    Field("mP", N_("Muscle percentage"), "%", confirmed=True),
    Field("sL", N_("Soft lean mass"), "kg", confirmed=True),
    Field("Im", N_("Impedance"), "Ω", confirmed=True),
    # Segmental analysis: R right arm, L left arm, r right leg, l left leg, T trunk
    Field("FR", N_("Body fat - right arm"), "%"),
    Field("FL", N_("Body fat - left arm"), "%"),
    Field("Fr", N_("Body fat - right leg"), "%"),
    Field("Fl", N_("Body fat - left leg"), "%"),
    Field("FT", N_("Body fat - trunk"), "%"),
    Field("mR", N_("Muscle mass - right arm"), "kg"),
    Field("mL", N_("Muscle mass - left arm"), "kg"),
    Field("mr", N_("Muscle mass - right leg"), "kg"),
    Field("ml", N_("Muscle mass - left leg"), "kg"),
    Field("mT", N_("Muscle mass - trunk"), "kg"),
    # End of record
    Field("CS", N_("Checksum"), kind="str"),
]

FIELDS: dict[str, Field] = {f.code: f for f in _FIELDS}


def describe(code: str) -> Field:
    """Returns a Field for unknown codes too, so no data is ever lost."""
    return FIELDS.get(code) or Field(code, code, kind="str", known=False)
