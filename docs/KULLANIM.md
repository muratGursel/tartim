# Tartım Kullanım Kılavuzu

📄 **[Bu kılavuzu PDF olarak indirin](Tartim-Kullanim-Kilavuzu.pdf)** (yazdırmak için) · [English](USER_GUIDE.md)

> Kılavuzdaki ekran görüntülerinde örnek (sentetik) ölçümler ve örnek
> Bluetooth cihazları kullanılmıştır; hiçbiri gerçek bir kişiye ait değildir.

Bu kılavuz, Tartım uygulamasıyla vücut analiz cihazınızdan (tartıdan) ölçüm
almayı, ölçümleri saklamayı ve geliştiricilere cihaz raporu göndermeyi adım
adım anlatır. Bilgisayar bilgisi gerektirmez.

**İçindekiler**

1. [Kurulum](#1-kurulum)
2. [Uygulamayı açmak](#2-uygulamayı-açmak)
3. [Tartıyı kabloyla bağlamak](#3-tartıyı-kabloyla-bağlamak)
4. [Tartıyı Bluetooth ile bağlamak](#4-tartıyı-bluetooth-ile-bağlamak)
5. [Ölçüm almak](#5-ölçüm-almak)
6. [Danışan kaydı](#6-danışan-kaydı)
7. [Geçmiş ölçümler, SD kart, Excel ve sonuç çıktısı](#7-geçmiş-ölçümler-sd-kart-excel-ve-sonuç-çıktısı)
8. [Cihaz raporu hazırlamak ve göndermek](#8-cihaz-raporu-hazırlamak-ve-göndermek)
9. [Sorun giderme](#9-sorun-giderme)
10. [Kişisel verilerin korunması](#10-kişisel-verilerin-korunması)

---

## 1. Kurulum

Kurulum bir kez yapılır. Yönetici (sudo) şifresi gerekir; bilmiyorsanız bilgi
işlem biriminizden destek isteyin.

1. **Uçbirim**'i açın (uygulama menüsünde "Uçbirim" ya da "Terminal" yazın).
2. Aşağıdaki satırı kopyalayıp uçbirime yapıştırın ve **Enter**'a basın:

   ```
   curl -fsSL https://raw.githubusercontent.com/muratGursel/tartim/main/install.sh | sudo sh
   ```

3. Şifreniz sorulursa yazın (yazarken ekranda görünmez) ve **Enter**'a basın.
4. Sonunda `tartim kuruldu` yazısını gördüğünüzde kurulum tamamdır.

> Uçbirim kullanmak istemiyorsanız
> [Sürümler sayfasından](https://github.com/muratGursel/tartim/releases)
> `tartim_..._all.deb` dosyasını indirip çift tıklayarak da kurabilirsiniz.

**Güncelleme:** Aynı komutu yeniden çalıştırmanız yeterlidir.

---

## 2. Uygulamayı açmak

Uygulama menüsünü açın ve **Tartım** yazın. Simgesine tıklayın.

![Tartım ana penceresi](screenshots/tr/01-main-window.png)

Açılan pencerede:

- **Üstte:** port seçimi, yenile ve Bluetooth düğmeleri, hız ve **Bağlan**
- **Solda:** son ölçümün sonuçları
- **Sağda:** kayıtlı ölçümler, **SD karttan içe aktar**, **Danışana ata**, **Sonuç çıktısı (PDF)** ve **Excel için dışa aktar**
- **Sol üstte:** **Danışanlar** (bkz. [Danışan kaydı](#6-danışan-kaydı))
- **Sağ üstte:** **Yardım** (bu kılavuz) ve **Cihaz raporu**

---

## 3. Tartıyı kabloyla bağlamak

1. Tartıyı USB ya da RS-232 kablosuyla (USB-seri çevirici ile) bilgisayara takın
   ve tartıyı açın.
2. Tartım'da **yenile** düğmesine (dönen ok) basın.
3. **Port** listesinden tartıyı seçin. USB ile bağlanan cihazlar genellikle
   `/dev/ttyUSB0` ya da `/dev/ttyACM0` adıyla görünür ve listenin başında yer alır.
4. **Hız** alanını değiştirmeyin (9600). Yalnızca veri gelmezse değiştirin
   (bkz. [Sorun giderme](#9-sorun-giderme)).
5. **Bağlan**'a basın. Düğme kırmızı **Bağlantıyı kes**'e dönüşür ve alt satırda
   "dinleniyor" yazar.

---

## 4. Tartıyı Bluetooth ile bağlamak

Bilgisayarınızda Bluetooth olmalı ve açık olmalıdır (ekranın sağ üst köşesindeki
sistem menüsünden kontrol edebilirsiniz).

### 4.1 Tartıyı bulmak

1. Tartıyı açın. Cihazınızda bir Bluetooth ya da eşleştirme modu varsa açın
   (cihazın kendi kılavuzuna bakın).
2. Tartım'da port alanının yanındaki **Bluetooth** düğmesine basın.
3. Yaklaşık 10 saniye bekleyin. Bulunan cihazlar **Port** listesinin en üstüne
   `bt:...  (cihaz adı, tür)` şeklinde eklenir.
4. Listeyi açıp tartınızı seçin.

   ![Bluetooth cihazları port listesinde](screenshots/tr/03-bluetooth-list.png)

5. **Bağlan**'a basın. Bağlantı kurulunca alt satırda "bağlandı" yazar:

   ![Bluetooth tartıya bağlanıldı](screenshots/tr/04-bluetooth-connected.png)

Listede cihazın yanında üç türden biri yazar:

| Yazan | Anlamı | Ne yapmalıyım? |
|---|---|---|
| **BLE (standart tartı)** | Cihaz, Bluetooth'un standart tartı servisini kullanıyor. | Doğrudan **Bağlan**'a basın. Ölçümler canlı gelir. |
| **Klasik (seri port)** | Cihaz kablo gibi çalışan eski tip Bluetooth kullanıyor. | Önce eşleştirin (4.2), sonra **Bağlan**'a basın. |
| **BLE** | Cihaz üreticiye özel bir yöntem kullanıyor. | Henüz doğrudan okunamıyor. Lütfen bir **cihaz raporu** gönderin (bölüm 8); desteği bu raporla ekleyebiliriz. |

### 4.2 Klasik Bluetooth cihazı eşleştirmek

Bu işlem her cihaz için bir kez yapılır.

1. **Ayarlar → Bluetooth** bölümünü açın.
2. Listede tartınıza tıklayın.
3. PIN sorulursa cihazın kılavuzundaki kodu girin. Kılavuzda yazmıyorsa
   genellikle **0000** ya da **1234**'tür.
4. "Bağlandı" ya da "Eşleştirildi" yazısını gördükten sonra Tartım'a dönüp
   Bluetooth düğmesine yeniden basın, cihazı seçip **Bağlan**'a basın.

### 4.3 Bluetooth cihazı listede çıkmıyorsa

- Tartının açık ve bilgisayara yakın (birkaç metre içinde) olduğundan emin olun.
- Tartı başka bir telefona ya da tablete bağlıysa o cihazda Bluetooth'u kapatın;
  çoğu tartı aynı anda tek cihaza bağlanır.
- Bluetooth düğmesine bir kez daha basın; bazı cihazlar ancak ikinci taramada görünür.

---

## 5. Ölçüm almak

1. Tartıya bağlıyken (alt satırda "dinleniyor" ya da "bağlandı" yazarken)
   ölçümü cihazda her zamanki gibi yapın: danışan numarasını ve bilgilerini
   cihaza girin, danışan tartıya çıksın. Numara, ölçümü danışanın kaydına
   bağlar (bkz. [Danışan kaydı](#6-danışan-kaydı)).
2. Ölçüm bitince sonuç birkaç saniye içinde Tartım'ın sol tarafında görünür ve
   otomatik olarak kaydedilir. Ayrıca bir şey yapmanız gerekmez.

   ![Ölçüm alındı: solda sonuç, sağda kayıtlı ölçümler](screenshots/tr/02-measurement.png)
3. Sıradaki danışan için aynı şekilde devam edin. Bağlantıyı kesmenize gerek yoktur.
4. İşiniz bitince **Bağlantıyı kes**'e basabilir ya da pencereyi kapatabilirsiniz.

> Değerlerin yanında yıldız (*) görürseniz: o alanın anlamı henüz gerçek bir
> cihazla doğrulanmamıştır. Cihaz ekranındaki değerle karşılaştırarak kullanın
> ve fark görürseniz bir cihaz raporu gönderin.

---

## 6. Danışan kaydı

Danışanlarınızı bir kez kaydederseniz ölçümleri adlarıyla görür, sonuç
çıktısına adı ayrıca yazmanız gerekmez.

**Danışan eklemek:**

1. Sol üstteki **Danışanlar** düğmesine basın.

   ![Danışanlar penceresi (örnek kişiler)](screenshots/tr/13-clients.png)

2. **Ekle…**'ye basın ve bilgileri doldurun:

   ![Danışan bilgileri](screenshots/tr/14-client-form.png)

   - **Danışan numarası:** ölçümden önce cihaza girdiğiniz numara (ID). Zorunlu.
   - **Adı soyadı:** zorunlu.
   - **Cinsiyet, doğum tarihi, boy, vücut tipi:** isteğe bağlı. Doğum tarihini
     `01.05.1977` biçiminde yazın; yaş her ölçümün tarihine göre hesaplanır.
   - **Not:** isteğe bağlı kısa bir not.
3. **Kaydet**'e basın.

**Ölçümler danışana nasıl bağlanır?** Ölçümden önce cihaza danışan numarasını
girin. Cihaz bu numarayı ölçümle birlikte gönderir ve Tartım ölçümü o danışana
bağlar; kayıtlı ölçümler listesinde **Adı soyadı** sütununda adı görünür. Daha
önce kaydedilmiş ölçümler de danışanı ekler eklemez adlarıyla görünür.

**Numarasız ölçümler** (ör. danışan numarası sormayan Bluetooth tartılar ya da
numara girilmeden yapılan ölçümler): listede ölçümü seçin, **Danışana ata…**'ya
basın ve danışanı seçin. Aynı pencerede **(danışan yok)** seçerek bağlantıyı
kaldırabilirsiniz.

**Eksik bilgilerin tamamlanması:** Cihaz cinsiyet, yaş ya da boy göndermezse
(bazı Bluetooth tartılar yalnızca kiloyu gönderir) sonuç çıktısındaki
değerlendirmeler için bu bilgiler danışan kaydından alınır; çıktıda bu durum
ayrıca belirtilir. Cihazın gönderdiği değerler her zaman önceliklidir. Vücut
kompozisyonunu (yağ, kas, sıvı) yine cihaz hesaplar; Tartım bu değerleri
yeniden hesaplamaz.

**Düzenlemek ve silmek:** listede danışanı seçip **Düzenle…** ya da **Sil…**'e
basın. Danışan numarasını değiştirirseniz ölçümleri de yeni numaraya taşınır.
Silerken ölçümleri adsız olarak saklamayı ya da onlarla birlikte silmeyi
seçebilirsiniz.

Komut satırından:

```
tartim danisan ekle 42 --ad "Ad Soyad" --cinsiyet kadin --dogum 01.05.1980 --boy 165
tartim danisan listele
tartim danisan duzenle 42 --not "Haftalık takip"
tartim ata --kayit 12 --danisan 42
```

---

## 7. Geçmiş ölçümler, SD kart, Excel ve sonuç çıktısı

**Geçmiş ölçüm:** Sağdaki listede bir satıra tıklayın; ayrıntıları solda görünür.
Sütun başlıklarına tıklayarak sıralayabilirsiniz.

**SD karttan içe aktarma** (SD kartı olan cihazlar için):

1. Cihazın SD kartını bilgisayara takın.
2. **SD karttan içe aktar…** düğmesine basın.
3. Karttaki `.CSV` dosyalarını seçin (birden fazla seçebilirsiniz) ve
   **İçe aktar**'a basın.
4. Aynı ölçüm iki kez eklenmez; dosyaları tekrar tekrar aktarmanızda sakınca yoktur.

**Excel'e aktarma:**

1. **Excel için dışa aktar…** düğmesine basın.
2. Dosyaya bir ad verip **Kaydet**'e basın.
3. Dosyayı LibreOffice Calc ya da Excel ile açabilirsiniz.

**Sonuç çıktısı (PDF):** danışana verebileceğiniz, yazdırılabilir bir sonuç sayfası.

1. Sağdaki listede ölçümü seçin (seçmezseniz son ölçüm kullanılır).
2. **Sonuç çıktısı (PDF)…** düğmesine basın.
3. Danışan kayıtlıysa adı kendiliğinden gelir. Kayıtlı değilse adı burada
   yazabilirsiniz; bu ad yalnızca çıktıya yazılır, kaydedilmez. **PDF
   oluştur**'a basın.
4. Dosyaya bir ad verip **Kaydet**'e basın. PDF açılır; oradan yazdırabilirsiniz.

Çıktının ilk sayfasında ölçümün analizi bulunur: vücut kompozisyonu, segmental
kas ve yağ dağılımı, metabolizma, BMI, yağ oranı, sıvı oranı ve viseral yağ için
düşük/normal/yüksek değerlendirmesi, ideal kilo aralığı ve kütlesel analiz.
Danışanın birden fazla ölçümü varsa ikinci sayfada **fark analizi** tablosu ve
**fark grafiği** yer alır.

![Sonuç çıktısı, 1. sayfa (sentetik örnek)](screenshots/tr/12-result-sheet-1.png)

![Sonuç çıktısı, 2. sayfa: fark analizi (sentetik örnek)](screenshots/tr/12-result-sheet-2.png)

> Değerlendirmede yayımlanmış başvuru aralıkları kullanılır: BMI için Dünya
> Sağlık Örgütü, yağ oranı için cinsiyet ve yaşa göre Gallagher ve ark. (2000),
> sıvı oranı ve viseral yağ için Tanita'nın yayımladığı aralıklar. Çıktı tıbbi
> teşhis yerine geçmez.

Komut satırından: `tartim yazdir --ad "Ad Soyad"` (son ölçüm) ya da
`tartim yazdir --kayit 12`.

---

## 8. Cihaz raporu hazırlamak ve göndermek

Cihaz raporu, tartınızın bilgisayara veriyi nasıl gönderdiğini öğrenmemizi
sağlar. Özellikle şu durumlarda çok işimize yarar:

- Tartınız Tartım'da hiç görünmüyorsa ya da "Tanınmayan kayıt" yazıyorsa,
- Bluetooth listesinde tartınızın yanında yalnızca **BLE** yazıyorsa,
- Gösterilen değerler cihaz ekranıyla uyuşmuyorsa.

Rapor yaklaşık 2 dakika sürer.

> **Önemli:** Rapor için ölçümü **kendiniz ya da bir test kişisiyle** yapın.
> Gerçek bir danışanın ölçümünü kullanmayın. Danışan numarası rapordan otomatik
> silinir, ama yaş, boy, cinsiyet ve vücut değerleri raporda kalır.

### 7.1 Raporu hazırlamak

1. Kablolu bağlantıda önce **Port** listesinden tartıyı seçin.
2. Sağ üstteki **Cihaz raporu** düğmesine basın.
3. **Cihaz modeli** alanına modeli yazın. Model, cihazın altındaki ya da
   arkasındaki etikette yazar (ör. `MC-780MA`, `FAST`).

   ![Cihaz raporu: modeli yazın ve bağlantı türünü seçin](screenshots/tr/05-report-start.png)
4. Bağlantı türüne göre bir düğmeye basın:
   - **Ölçümü başlat:** tartı kabloyla bağlıysa
   - **Bluetooth ile…:** tartı Bluetooth'luysa. Açılan listeden tartınızı
     seçip **Seç ve ölçüme başla**'ya basın.

     ![Rapor için Bluetooth cihazı seçimi](screenshots/tr/06-report-bluetooth.png)
   - **SD kart dosyasından…:** cihaz ölçümleri SD karta yazıyorsa. Karttaki
     dosyayı seçin.
5. "Şimdi cihazda ölçüm yapın" yazısını görünce tartıda bir ölçüm yapın.
   Veri gelince pencere kendiliğinden sonraki adıma geçer.

   ![Ölçüm bekleniyor](screenshots/tr/07-report-wait.png)

6. Cihaz ekranında gördüğünüz **kiloyu** yazın (ör. `72,4`). Bu isteğe bağlıdır
   ama veriyi doğrulamamızı çok kolaylaştırır.

   ![Ekrandaki kiloyu yazın](screenshots/tr/08-report-weight.png)

7. **Raporu kaydet**'e basın. Rapor **Belgeler** klasörünüze
   `tartim-report-MODEL-TARİH.json` adıyla kaydedilir ve gönderim seçenekleri
   görünür (bkz. 7.2).

"Hiç veri gelmedi" yazsa bile raporu kaydedip gönderin; bu da işimize yarar.

### 7.2 Raporu göndermek

Rapor kaydedildikten sonra pencerede raporu nasıl göndermek istediğiniz sorulur.
Size uygun olanı seçin:

![Gönderim seçenekleri](screenshots/tr/09-report-done.png)

| Seçenek | Ne olur? | Kimin için? |
|---|---|---|
| **Proje sunucusuna gönder** | Rapor tek tıkla geliştiricilere ulaşır. GitHub hesabı gerekmez. Rapor herkese açık yayımlanmaz. | Çoğu kullanıcı için en kolayı |
| **GitHub formuyla kendim göndereceğim** | GitHub'daki form açılır, dosyayı siz eklersiniz. Kayıt herkese açık görünür. | GitHub hesabı olan ve süreci kendisi takip etmek isteyenler |
| **Şimdilik gönderme** | Dosya bilgisayarınızda kalır. İstediğiniz zaman ya da istediğiniz yoldan (ör. e-posta) iletebilirsiniz. | Önce kurum içinde kontrol etmek isteyenler |

#### Proje sunucusuna göndermek

1. **Proje sunucusuna gönder** seçili olsun.
2. **"Bu ölçüm gerçek bir danışana ait değildir"** kutusunu işaretleyin. İşaretlemeden
   **Gönder** düğmesi çalışmaz.
3. İsterseniz kısa bir not yazın (ör. "Cihaz ekranında yağ oranı 24,1 görünüyordu").
4. **Gönder**'e basın. "Gönderildi, teşekkürler!" yazısı ve bir **rapor numarası**
   görünür. Bize ulaşırken bu numarayı belirtebilirsiniz.

İnternet bağlantısı yoksa "Rapor sunucusuna ulaşılamadı" yazar. Dosya
bilgisayarınızda durur; daha sonra yeniden gönderebilirsiniz (bkz. 7.3).

#### GitHub formuyla göndermek

Ücretsiz bir GitHub hesabı gerekir (<https://github.com/signup>).

1. **GitHub formuyla kendim göndereceğim**'i seçip **GitHub formunu aç**'a basın.
   (Doğrudan adres:
   <https://github.com/muratGursel/tartim/issues/new?template=cihaz-raporu.yml>)
2. GitHub hesabınızla giriş yapın. "Cihaz raporu" formu açılır:

   ![GitHub'daki cihaz raporu formu](screenshots/tr/10-github-form.png)

3. Formda:
   - **Cihaz modeli:** modeli yazın.
   - **Rapor dosyası:** **Klasörü aç** düğmesiyle açılan klasördeki
     `tartim-report-....json` dosyasını sürükleyip bu kutuya bırakın. Dosya
     yüklenince kutuda bir bağlantı belirir.

     ![Rapor dosyasını bu kutuya sürükleyin](screenshots/tr/11-github-file.png)

   - **Notlar:** varsa yaşadığınız sorunları yazın (isteğe bağlı).
   - **Onay:** sayfanın altındaki "Bu ölçüm gerçek bir danışana ait değildir"
     kutusunu işaretleyin.
4. Sağ alttaki yeşil **Create** düğmesine basın.

Bu yolla gönderilen raporlar herkese açık görünür.

### 7.3 Komut satırından rapor (isteğe bağlı)

Arayüz yerine uçbirimi tercih ederseniz:

```
tartim rapor               # kablolu cihaz
tartim rapor --bluetooth   # Bluetooth cihaz
tartim rapor --dosya /media/KULLANICI/SD/20261016.CSV   # SD kart
```

Program yalnızca modeli ve ekrandaki kiloyu sorar, raporu bulunduğunuz klasöre
kaydeder ve nasıl göndermek istediğinizi sorar. Kaydedilmiş bir raporu daha sonra
sunucuya göndermek için:

```
tartim rapor-gonder tartim-report-MC780MA-20261016-104512.json
```

---

## 9. Sorun giderme

| Sorun | Çözüm |
|---|---|
| Port listesi boş | Kabloyu çıkarıp takın, **yenile**'ye basın. USB-seri çevirici kullanıyorsanız çeviricinin takılı olduğundan emin olun. |
| "Porta erişim izniniz yok" | Oturumu kapatıp açın. Sorun sürerse ve port `/dev/ttyS...` ise uçbirimde `sudo usermod -aG dialout $USER` yazıp yeniden oturum açın. |
| Bağlandı ama ölçüm gelmiyor | 1) Cihazın ayarlarında "PC'ye veri çıkışı" açık mı, kontrol edin. 2) **Bağlantıyı kes**'e basın, **Hız**'ı 4800, 19200 ya da 38400 yapıp yeniden deneyin. 3) Hâlâ gelmiyorsa bir cihaz raporu gönderin. |
| "Tanınmayan kayıt" | Cihazınızın biçimini henüz tanımıyoruz. Lütfen cihaz raporu gönderin. |
| "Bluetooth kapalı" | Sistem menüsünden Bluetooth'u açın. |
| "Bluetooth adaptörü bulunamadı" | Bilgisayarınızda Bluetooth yok ya da kapalı. Harici bir USB Bluetooth adaptörü takabilirsiniz. |
| Bluetooth'a bağlanılamadı | Tartı başka bir telefona bağlı olabilir; o cihazda Bluetooth'u kapatın. Klasik cihazlarda önce eşleştirme yapın (4.2). |
| "Bu cihaz standart Bluetooth tartı servisini kullanmıyor" | Cihaz üreticiye özel yöntem kullanıyor. Cihaz raporu gönderin (8). |

Sorununuz çözülmezse <https://github.com/muratGursel/tartim/issues> adresinden
bize yazabilirsiniz.

---

## 10. Kişisel verilerin korunması

Vücut ölçümleri sağlık verisidir ve KVKK kapsamında özel nitelikli kişisel veri
sayılır.

- Ölçümler yalnızca sizin bilgisayarınızda, yalnızca sizin kullanıcı hesabınızın
  okuyabileceği bir dosyada saklanır (`~/.local/share/tartim/tartim.db`).
  Danışan kayıtları (ad, doğum tarihi, boy, not) da aynı dosyadadır.
  Ölçümler ve danışan bilgileri hiçbir zaman internete gönderilmez.
- İnternete giden tek şey, sizin seçip onayladığınız **cihaz raporlarıdır**.
  Proje sunucusuna gönderilen raporlar yalnızca geliştiricilerin erişebildiği
  özel bir depoda tutulur; GitHub formuyla gönderilenler herkese açıktır.
  Her iki durumda da gerçek danışan ölçümü göndermeyin.
- Kurumunuz sunucuya gönderimi tamamen kapatmak isterse bilgi işlem birimi
  `TARTIM_REPORT_URL` ortam değişkenini boş bırakabilir; bu durumda seçenek
  pencerede görünmez.
- Excel'e aktardığınız dosyalar da kişisel veri içerir; güvenli bir yerde saklayın.
- Kurumunuzda kullanmadan önce açık rıza, erişim yetkisi ve saklama süresi
  konularını veri sorumlunuzla netleştirin.
