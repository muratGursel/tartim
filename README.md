# tartim

Pardus ve diğer GNU/Linux sistemlerinde **vücut kompozisyon analizörlerinden**
(Tanita uyumlu cihazlar) ölçüm almak için açık kaynak okuyucu.

Üreticinin bilgisayar yazılımı yalnızca Windows'ta çalışıyor. `tartim` cihazın
seri port (RS-232 / USB) üzerinden gönderdiği ölçümü okur, çözer ve yerel bir
veritabanına kaydeder. SD karttaki CSV dosyalarını da içe aktarabilir.

> **Durum: erken geliştirme (0.1).** Veri biçimi kılavuzlara ve topluluk
> notlarına dayanıyor, henüz gerçek bir cihazla doğrulanmadı. Ayrıntılar:
> [docs/PROTOKOL.md](docs/PROTOKOL.md)

Tanita, TANITA Corporation'ın tescilli markasıdır. Bu proje Tanita ile bağlantılı
değildir.

## Kurulum (Pardus 23 / 25)

```sh
sudo apt install python3-serial
sudo usermod -aG dialout $USER   # seri port izni; sonra oturumu kapatıp açın
git clone <depo-adresi> && cd tartim
python3 -m tartim --surum
```

## Kullanım

```sh
python3 -m tartim portlar                         # bağlı seri portlar
python3 -m tartim dinle --port /dev/ttyUSB0       # ölçümleri göster ve kaydet
python3 -m tartim ice-aktar /media/$USER/SD/*.CSV # SD karttan içe aktar
python3 -m tartim listele --son 10
python3 -m tartim disa-aktar --cikti olcumler.csv # Excel / LibreOffice için
python3 -m tartim ham --port /dev/ttyUSB0         # yeni cihaz için ham veri
```

Port ayarları: `--baud 9600 --parite N --veri-biti 8 --dur-biti 1` (varsayılan).

Ölçümler `~/.local/share/tartim/tartim.db` dosyasında saklanır. Dosya yalnızca
sizin okuyabileceğiniz izinlerle oluşturulur.

## Cihaz olmadan deneme

```sh
socat -d -d pty,raw,echo=0,link=/tmp/tarti pty,raw,echo=0,link=/tmp/pc &
python3 -m tartim dinle --port /tmp/pc &
python3 -m tartim simule --port /tmp/tarti --adet 3
```

Simülatörün ürettiği değerler sentetiktir ve hiçbir kişiye ait değildir.

## Testler

```sh
python3 -m unittest -v
```

Seri port testi Linux'ta `socat` ve `python3-serial` kuruluysa çalışır.

## Kişisel veriler (KVKK)

Vücut ölçümleri sağlık verisidir ve KVKK'ya göre özel nitelikli kişisel veri
sayılır. Kurumunuzda kullanmadan önce açık rıza, erişim yetkisi ve saklama
süresi konularını veri sorumlunuzla netleştirin. Gerçek ölçüm kayıtlarını
hata bildirimlerine ya da bu depoya eklemeyin.

## Yol haritası

- [ ] Gerçek MC-780 / BC-418 cihazlarla alan kodlarını doğrulamak
- [ ] `CS` sağlama değerini doğrulamak
- [ ] Uzak kip: boy, yaş ve cinsiyetin bilgisayardan cihaza gönderilmesi
- [ ] Danışan kaydı ve grafikli masaüstü arayüzü (GTK)
- [ ] PDF ölçüm raporu
- [ ] `.deb` paketi ve Pardus Mağazası
- [ ] Diğer markalar için eklenti yapısı

## Katkı

Elinizde farklı bir model varsa en değerli katkı, `tartim ham` ile alınmış bir
örnek kayıttır (kişisel bilgileri çıkarılmış olarak). Bkz.
[docs/PROTOKOL.md](docs/PROTOKOL.md).

## Lisans

GPL-3.0-or-later. Bkz. [LICENSE](LICENSE).
