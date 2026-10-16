# Cihaz protokolü notları

Bu belge, desteklenen cihazların veri biçimi hakkında bildiklerimizi ve
bunları nereden öğrendiğimizi tutar. Doğrulanmamış her bilgi öyle işaretlenir.

## Bağlantı

| Model | Arayüz | Bilinen ayarlar | Kaynak | Durum |
|---|---|---|---|---|
| MC-780MA | RS-232C, USB-B, SD kart | 9600 baud, akış kontrolü yok | GMON kılavuzu (MC-180 için aynı ayar) | Doğrulanmadı |
| MC-780MA | — | Ayar 30: PC çıkış biçimi `0` varsayılan, `1` BC-418 biçimi | MC-780 kullanım kılavuzu, s. 11 | Kılavuzda |
| MC-780MA | — | RS-232C ve USB aynı anda kullanılamaz | MC-780 kullanım kılavuzu | Kılavuzda |
| MC-780MA | SD kart | Her gün için `YYYYMMDD` adlı bir CSV dosyası | MC-780 kullanım kılavuzu, s. 21 | Kılavuzda |
| BC-418 | RS-232C | "Standart" (cihaz gönderir) ve "uzak" (PC komut verir) kip | GMON kılavuzu | Doğrulanmadı |

Şu an yalnızca **standart kip** destekleniyor: cihaz her ölçümden sonra kaydı
kendiliğinden gönderir, `tartim` dinler.

## Kayıt biçimi

```
{0,16,~0,1,~1,1,~2,1,MO,"MC-780",ID,"0000000000000001",...,Wk,70.4,FW,21.3,...,CS,3A}
```

- Kayıt CR LF ile biter.
- Baştaki `0,16,~0,1,~1,1,~2,1` biçim başlığıdır, atlanır.
- Ardından `KOD,DEĞER` çiftleri gelir. Kodlar büyük/küçük harfe duyarlıdır.
- `CS` bir sağlama değeridir. Hesaplama yöntemi bilinmediği için şimdilik
  doğrulanmıyor.

Alan kodlarının anlamları `tartim/fields.py` dosyasındadır. Kaynak, MC-780
Bluetooth protokolünü çözen topluluk notlarıdır
(<https://gist.github.com/zapkub/350bb90a0aa70d7c3685522e0b83736c>); bu
yüzden hepsi `confirmed=False` olarak işaretli.

## Bluetooth

`tartim` BlueZ'e D-Bus üzerinden bağlanır (ek paket gerekmez).

| Cihaz türü | Destek |
|---|---|
| Klasik Bluetooth seri port (SPP) | Eşleştirdikten sonra port olarak `bt:AA:BB:CC:DD:EE:FF` yazın; kablolu cihazlarla aynı şekilde okunur. RFCOMM kanalı 1–5 arasında denenir, gerekirse `bt:ADRES@KANAL`. |
| BLE, standart tartı servisleri (Weight Scale 0x181D, Body Composition 0x181B) | Doğrudan ve canlı okunur. Paket biçimi Bluetooth SIG spesifikasyonundan; ağırlık ve vücut kompozisyonu paketleri birleştirilir. Gerçek bir cihazla henüz doğrulanmadı. |
| BLE, üreticiye özel servisler (ör. Tartı FAST olabilir) | Henüz okunamaz. `tartim rapor --bluetooth` cihazın servis yapısını, okunabilir bilgi alanlarını (model, yazılım sürümü; seri numarası hariç) ve ölçüm sırasında gelen tüm bildirimleri kaydeder. Cihaza hiçbir şey yazılmaz. |

Raporda Bluetooth adresinin yalnızca ilk üç baytı (üretici kodu) tutulur.

### Cihaz, uygulamadan komut bekliyorsa

Bazı tartılar (ör. Tanita MC-780 Bluetooth modülü) ölçüm göndermeden önce
uygulamadan boy, yaş, cinsiyet gibi bilgileri ve bir başlat komutu bekler. Bu
durumda raporda bildirim görünmez. Protokolü çözmek için üreticinin telefon
uygulamasıyla cihaz arasındaki trafiği kaydetmek gerekir:

1. Android telefonda **Ayarlar → Telefon hakkında → Yapı numarası**'na yedi kez
   dokunarak geliştirici seçeneklerini açın.
2. **Geliştirici seçenekleri → Bluetooth HCI izleme günlüğünü etkinleştir**'i açın,
   Bluetooth'u kapatıp açın.
3. Üreticinin uygulamasıyla bir test kişisi üzerinde ölçüm yapın.
4. Günlüğü alın: bilgisayardan `adb bugreport rapor.zip` (dosya içinde
   `btsnoop_hci.log`). Wireshark ile açılabilir.
5. Dosyayı cihaz raporuyla birlikte gönderin. Günlükte telefondaki diğer
   Bluetooth cihazlarının trafiği de bulunabilir; mümkünse yalnızca tartı
   bağlıyken kaydedin.

## Yeni bir cihazı nasıl doğrularız?

1. Cihazı bağlayın, portu bulun: `tartim portlar`
2. Ham veriyi kaydedin: `tartim ham --port /dev/ttyUSB0 --cikti ham.txt`
3. Cihazda bir ölçüm yapın. Ekranda ve çıktıda görünen değerleri yan yana
   not edin (kilo, yağ oranı vb.).
4. Hiçbir şey gelmiyorsa baud hızını değiştirin (`--baud 4800`, `19200`,
   `38400`) ve cihazın PC çıkış ayarını kontrol edin.
5. Kodları cihazın ekranındaki değerlerle eşleştirin, `fields.py` dosyasında
   `confirmed=True` yapın ve ham kaydı test olarak ekleyin.

**Önemli:** Ham kayıtlarda danışan numarası, yaş, cinsiyet ve vücut ölçüleri
vardır. Paylaşmadan önce bir test kişisiyle ölçüm yapın ya da kimlik
alanlarını değiştirin.
