"""Cihaz olmadan geliştirme ve test için sanal tartı.

Linux'ta iki uçlu sanal seri port oluşturup bir ucuna simülatörü bağlayın::

    socat -d -d pty,raw,echo=0,link=/tmp/tarti pty,raw,echo=0,link=/tmp/pc
    tartim simule --port /tmp/tarti &
    tartim dinle --port /tmp/pc

Üretilen kayıtlar SENTETİKTİR: alan kodları gerçek cihaz biçimini taklit eder
ama değerler rastgeledir ve hiçbir kişiye ait değildir.
"""

from __future__ import annotations

import random
from datetime import datetime


def synthetic_record(subject: int = 1, rng: random.Random | None = None,
                     model: str = "MC-780", now: datetime | None = None) -> str:
    rng = rng or random.Random()
    now = now or datetime.now()
    height = round(rng.uniform(155, 190), 1)
    weight = round(rng.uniform(50, 110), 1)
    fat = round(rng.uniform(12, 38), 1)
    fat_mass = round(weight * fat / 100, 1)
    ffm = round(weight - fat_mass, 1)
    muscle = round(ffm * 0.95, 1)
    water = round(ffm * 0.73, 1)
    pairs = [
        ("MO", f'"{model}"'), ("ID", f'"{subject:016d}"'), ("St", "0"),
        ("Da", f'"{now:%d/%m/%Y}"'), ("TI", f'"{now:%H:%M}"'),
        ("Bt", "0"), ("GE", str(rng.choice((1, 2)))), ("AG", str(rng.randint(18, 70))),
        ("Hm", f"{height}"), ("Pt", "0.5"), ("Wk", f"{weight}"),
        ("MI", f"{weight / (height / 100) ** 2:.1f}"),
        ("FW", f"{fat}"), ("fW", f"{fat_mass}"), ("MW", f"{ffm}"),
        ("mW", f"{muscle}"), ("bW", f"{ffm - muscle:.1f}"),
        ("wW", f"{water}"), ("ww", f"{water / weight * 100:.1f}"),
        ("IF", str(rng.randint(1, 15))), ("rB", str(rng.randint(1200, 2200))),
    ]
    body = ",".join(f"{k},{v}" for k, v in pairs)
    return "{0,16,~0,1,~1,1,~2,1," + body + ",CS,00}\r\n"
