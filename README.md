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

Uçbirimde tek komut:

```sh
curl -fsSL https://raw.githubusercontent.com/muratGursel/tartim/main/install.sh | sudo sh
```

Ya da [Sürümler](https://github.com/muratGursel/tartim/releases) sayfasından
`tartim_*_all.deb` dosyasını indirip kurun:

```sh
sudo apt install ./tartim_0.2.0_all.deb
```

Paket, oturum açmış kullanıcıya USB-seri portlara erişim izni veren bir udev
kuralı da kurar; `dialout` grubuna eklenmeniz gerekmez. RS-232 portu doğrudan
anakartta ise (`/dev/ttyS*`) `sudo usermod -aG dialout $USER` gerekir.

Geliştirme için kaynaktan çalıştırmak: `sudo apt install python3-serial` ve
depo klasöründe `python3 -m tartim`.

## Kullanım

```sh
tartim portlar                         # bağlı seri portlar
tartim dinle --port /dev/ttyUSB0       # ölçümleri göster ve kaydet
tartim ice-aktar /media/$USER/SD/*.CSV # SD karttan içe aktar
tartim listele --son 10
tartim disa-aktar --cikti olcumler.csv # Excel / LibreOffice için
tartim ham --port /dev/ttyUSB0         # yeni cihaz için ham veri
```

## Tartınız mı var? Cihaz raporu gönderin

Projenin gelişmesi için en çok ihtiyaç duyduğumuz şey farklı cihazlardan
gerçek ölçüm verisi. Tartıyı bilgisayara takın ve şunu çalıştırın:

```sh
tartim rapor
```

Program yalnızca cihaz modelini ve ekranda gördüğünüz kiloyu sorar, portu
kendisi bulur. Siz ölçüm yaptığınızda gelen veriyi kaydeder ve bir
`tartim-rapor-MODEL-TARIH.json` dosyası oluşturur. Danışan numarası dosyaya
yazılmadan maskelenir. Bu dosyayı
[Cihaz raporu formuyla](https://github.com/muratGursel/tartim/issues/new?template=cihaz-raporu.yml)
gönderin.

- SD kart dosyası için: `tartim rapor --dosya /media/$USER/SD/20261016.CSV`
- Daha fazla bilgi vermek isterseniz: `tartim rapor --ayrintili` (cihaz
  ayarlarını, cihaza girilen boy/yaş/cinsiyeti ve ekrandaki tüm değerleri
  sorar; değerleri veriyle karşılaştırıp hangi alanın neye karşılık geldiğini
  gösterir)

Ölçümü kendinizle ya da bir test kişisiyle yapın; gerçek bir danışanın
ölçümünü göndermeyin.

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
- [x] `.deb` paketi ve tek komutla kurulum
- [ ] Pardus Mağazası'na başvuru
- [ ] Diğer markalar için eklenti yapısı

## Katkı

Elinizde bir tartı varsa en değerli katkı `tartim rapor` ile hazırlanan
dosyadır (yukarıya bakın). Protokol ayrıntıları:
[docs/PROTOKOL.md](docs/PROTOKOL.md).

Paketi kaynaktan derlemek için: `sh packaging/build-deb.sh`

## Lisans

GPL-3.0-or-later. Bkz. [LICENSE](LICENSE).
