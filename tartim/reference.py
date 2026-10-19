"""Reference ranges used to classify a measurement as low / normal / high.

Only published, widely used ranges are used; device vendors' own formulas
(protein mass, body density, ...) are not reproduced because they are not
published.

* BMI: World Health Organization adult classification (18.5 / 25 / 30).
* Body fat %: Gallagher et al. 2000 (Am J Clin Nutr 72:694), the ranges
  Tanita also publishes in its body fat charts, by gender and age.
* Total body water %: Tanita's published healthy ranges (male 50–65 %,
  female 45–60 %).
* Visceral fat rating: Tanita scale, 1–12 healthy, 13–59 excess.

The ranges are for adults (18+); for younger people no classification is made.
"""

from __future__ import annotations

from dataclasses import dataclass

LOW, NORMAL, HIGH = "low", "normal", "high"


@dataclass(frozen=True)
class Range:
    low: float   # values below are "low"
    high: float  # values above are "high"

    def classify(self, value: float) -> str:
        if value < self.low:
            return LOW
        if value > self.high:
            return HIGH
        return NORMAL


BMI = Range(18.5, 24.9)
VISCERAL = Range(1, 12)

# (min age, max age) -> (healthy from, healthy to); above "to" is over-fat.
_FAT = {
    1: [((18, 39), (8, 20)), ((40, 59), (11, 22)), ((60, 120), (13, 25))],   # male
    2: [((18, 39), (21, 33)), ((40, 59), (23, 34)), ((60, 120), (24, 36))],  # female
}
_WATER = {1: Range(50, 65), 2: Range(45, 60)}


def fat_range(gender: int | None, age: int | None) -> Range | None:
    if gender not in _FAT or age is None or age < 18:
        return None
    for (low_age, high_age), (low, high) in _FAT[gender]:
        if low_age <= age <= high_age:
            return Range(low, high)
    return None


def water_range(gender: int | None, age: int | None) -> Range | None:
    if age is not None and age < 18:
        return None
    return _WATER.get(gender)


def bmi(weight: float | None, height_cm: float | None) -> float | None:
    if not weight or not height_cm:
        return None
    return weight / (height_cm / 100) ** 2


def weight_range(height_cm: float | None) -> tuple[float, float, float] | None:
    """(lower, ideal, upper) weight for the normal BMI range; ideal = BMI 22."""
    if not height_cm:
        return None
    square = (height_cm / 100) ** 2
    return BMI.low * square, 22 * square, BMI.high * square
