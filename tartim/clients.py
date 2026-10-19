"""Client records: the people measured, linked to measurements by client number.

The client number is the ID entered on the device before a measurement, so
measurements are matched to a client automatically. Measurements without a
number (e.g. from Bluetooth scales) can be assigned to a client by hand.

Only what the analysis needs is kept: name, gender, birth date, height and body
type, plus a free note. These are personal data (health data together with the
measurements); they stay in the local database, readable by its owner only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from .i18n import _

MALE, FEMALE = 1, 2
STANDARD, ATHLETIC = 0, 2


def normalize_number(number: str) -> str:
    """Device numbers are zero padded ("0000000000000042"); keep the plain form ("42")."""
    text = str(number).strip()
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text


def parse_date(text: str) -> date:
    """Accepts 1977-05-01, 01.05.1977 and 01/05/1977."""
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(_("Invalid date: {text} (use e.g. 1977-05-01 or 01.05.1977)").format(
        text=text))


def age_on(birth: date, day: date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


@dataclass(frozen=True)
class Client:
    number: str
    name: str
    gender: int | None = None        # 1 male, 2 female (as on Tanita devices)
    birth_date: date | None = None
    height: float | None = None      # cm
    body_type: int = STANDARD        # 0 standard, 2 athletic
    note: str = ""

    def __post_init__(self):
        if not normalize_number(self.number):
            raise ValueError(_("The client number is required."))
        if not self.name.strip():
            raise ValueError(_("The client name is required."))
        if self.gender not in (None, MALE, FEMALE):
            raise ValueError(_("Gender must be 1 (male) or 2 (female)."))
        if self.height is not None and not 50 <= self.height <= 250:
            raise ValueError(_("Height must be between 50 and 250 cm."))
        if self.body_type not in (STANDARD, ATHLETIC):
            raise ValueError(_("Body type must be 0 (standard) or 2 (athletic)."))
        if self.birth_date is not None and self.birth_date > date.today():
            raise ValueError(_("The birth date cannot be in the future."))
        object.__setattr__(self, "number", normalize_number(self.number))
        object.__setattr__(self, "name", self.name.strip())

    def age_at(self, when: datetime | date | None = None) -> int | None:
        if self.birth_date is None:
            return None
        day = when.date() if isinstance(when, datetime) else (when or date.today())
        return age_on(self.birth_date, day)

    def with_changes(self, **changes) -> "Client":
        return replace(self, **changes)

    def to_row(self) -> dict:
        return {"number": self.number, "name": self.name, "gender": self.gender,
                "birth_date": self.birth_date.isoformat() if self.birth_date else None,
                "height": self.height, "body_type": self.body_type, "note": self.note}

    @classmethod
    def from_row(cls, row) -> "Client":
        return cls(number=row["number"], name=row["name"], gender=row["gender"],
                   birth_date=date.fromisoformat(row["birth_date"]) if row["birth_date"]
                   else None, height=row["height"], body_type=row["body_type"] or STANDARD,
                   note=row["note"] or "")

    def fill(self, values: dict, when: datetime | None) -> tuple[dict, list[str]]:
        """Completes a measurement's input values from the client record.
        Returns the values and the codes that were filled in."""
        values = dict(values)
        filled = []
        for code, value in (("GE", self.gender), ("AG", self.age_at(when)),
                            ("Hm", self.height), ("Bt", self.body_type)):
            if values.get(code) is None and value is not None:
                values[code] = value
                filled.append(code)
        return values, filled
