"""Tanita anahtar-değer kayıtlarındaki alan kodlarının anlamları.

Tanita profesyonel cihazları (MC-780, MC-980, BC-418, DC-360 ...) ve SD kart
kullanan modeller ölçüm sonucunu ``KOD,DEĞER,KOD,DEĞER,...`` biçiminde gönderir.
Kodlar büyük/küçük harfe duyarlıdır: ``FW`` yağ yüzdesi, ``fW`` yağ kütlesidir.

``confirmed`` alanı, kodun anlamının gerçek bir cihaz çıktısıyla doğrulanıp
doğrulanmadığını gösterir. Şimdilik kaynaklar kılavuzlar ve topluluk
çalışmalarıdır (bkz. docs/PROTOKOL.md). Gerçek cihazla doğruladığınız her kod
için ``confirmed=True`` yapıp PR gönderin.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    code: str
    label: str
    unit: str = ""
    kind: str = "float"  # float | int | str
    confirmed: bool = False
    choices: tuple[tuple[int, str], ...] = ()

    def display(self, value: object) -> str:
        """Değeri birimiyle ya da anlamıyla (ör. cinsiyet: Kadın) yazar."""
        for code, name in self.choices:
            if value == code:
                return name
        return f"{value} {self.unit}".rstrip()


_FIELDS = [
    # Kimlik ve ölçüm bilgileri
    Field("MO", "Cihaz modeli", kind="str"),
    Field("ID", "Danışan numarası", kind="str"),
    Field("St", "Durum", kind="str"),
    Field("Da", "Tarih", kind="str"),
    Field("DT", "Tarih", kind="str"),
    Field("TI", "Saat", kind="str"),
    Field("Ti", "Saat", kind="str"),
    # Girdi bilgileri
    Field("Bt", "Vücut tipi", kind="int", choices=((0, "Standart"), (2, "Atletik"))),
    Field("GE", "Cinsiyet", kind="int", choices=((1, "Erkek"), (2, "Kadın"))),
    Field("AG", "Yaş", "yıl", kind="int"),
    Field("Hm", "Boy", "cm"),
    Field("Pt", "Kıyafet ağırlığı (dara)", "kg"),
    Field("AL", "Aktivite düzeyi", kind="int"),
    # Tüm vücut analizi
    Field("Wk", "Kilo", "kg"),
    Field("MI", "Vücut kitle indeksi (BMI)"),
    Field("FW", "Yağ oranı", "%"),
    Field("fW", "Yağ kütlesi", "kg"),
    Field("MW", "Yağsız kütle (FFM)", "kg"),
    Field("mW", "Kas kütlesi", "kg"),
    Field("bW", "Kemik kütlesi", "kg"),
    Field("ww", "Toplam vücut suyu oranı", "%"),
    Field("wW", "Toplam vücut suyu", "kg"),
    Field("wI", "Hücre içi su", "kg"),
    Field("wO", "Hücre dışı su", "kg"),
    Field("IF", "Viseral yağ derecesi", kind="int"),
    Field("rB", "Bazal metabolizma hızı (BMR)", "kcal", kind="int"),
    Field("rA", "Metabolik yaş", "yıl", kind="int"),
    Field("LP", "Bacak kas skoru", kind="int"),
    # Standart Bluetooth tartıların ek alanları (tartim'e özgü kodlar)
    Field("mP", "Kas oranı", "%", confirmed=True),
    Field("sL", "Yumuşak yağsız kütle", "kg", confirmed=True),
    Field("Im", "Empedans", "Ω", confirmed=True),
    # Segmental analiz: R sağ kol, L sol kol, r sağ bacak, l sol bacak, T gövde
    Field("FR", "Yağ oranı - sağ kol", "%"),
    Field("FL", "Yağ oranı - sol kol", "%"),
    Field("Fr", "Yağ oranı - sağ bacak", "%"),
    Field("Fl", "Yağ oranı - sol bacak", "%"),
    Field("FT", "Yağ oranı - gövde", "%"),
    Field("mR", "Kas kütlesi - sağ kol", "kg"),
    Field("mL", "Kas kütlesi - sol kol", "kg"),
    Field("mr", "Kas kütlesi - sağ bacak", "kg"),
    Field("ml", "Kas kütlesi - sol bacak", "kg"),
    Field("mT", "Kas kütlesi - gövde", "kg"),
    # Kayıt sonu
    Field("CS", "Sağlama değeri", kind="str"),
]

FIELDS: dict[str, Field] = {f.code: f for f in _FIELDS}


def describe(code: str) -> Field:
    """Bilinmeyen kodlar için de bir Field döndürür; hiçbir veri kaybolmaz."""
    return FIELDS.get(code) or Field(code, f"Bilinmeyen alan ({code})", kind="str")
