# Rapor sunucusu

Uygulamadaki **Cihaz raporu → Proje sunucusuna gönder** seçeneği raporları bu
sunucuya yollar. Sunucu raporu denetler, diske kaydeder ve GitHub'daki **özel**
bir depoda kayıt (issue) olarak açar. Böylece rapor gönderenlerin GitHub hesabı
olması gerekmez ve hiçbir anahtar uygulamaya ya da bu depoya girmez.

```
Tartım uygulaması ──HTTPS──▶ nginx (/tartim/) ──▶ tartim-rapor servisi (127.0.0.1:8095)
                                                     │  diske kaydet (0600)
                                                     └──▶ GitHub API (özel depo, issue)
```

Proje sunucusu: `https://ldow.duckdns.org/tartim/rapor`. Kendi sunucusunu
kullanmak isteyen kurumlar uygulamada `TARTIM_RAPOR_ADRESI` ortam değişkenini
kendi adreslerine ayarlar; boş bırakırlarsa sunucuya gönderim seçeneği kapanır.

## Güvenlik modeli

Açık kaynak bir uygulamada uygulamanın içine konan her "gizli" değer herkese
açıktır. Bu yüzden uygulamayı kimlik doğrulamayla ayırt etmeye çalışmıyoruz;
bunun yerine uç noktanın kötüye kullanılmasının **zararsız ve pahalı** olmasını
sağlıyoruz:

| Katman | Önlem |
|---|---|
| Taşıma | Yalnızca HTTPS (Let's Encrypt). Servis yalnızca `127.0.0.1`'i dinler, dışarıya sadece nginx'teki `/tartim/` yolu açıktır. |
| İstek sınırı | nginx: IP başına dakikada 10 istek (kısa ani artışa 5). Servis: IP başına saatte 5 rapor, sunucu geneli günde 200 rapor. Reddedilen denemeler de sayılır. |
| Boyut ve biçim | En fazla 2 MB; yalnızca JSON; `schema: 1`, model adı, en fazla 10 ölçüm, not en fazla 2000 karakter. Kullanıcının "gerçek danışana ait değildir" onayı zorunlu. |
| Disk | İletilmeyi bekleyen rapor sayısı 500 ile sınırlı; dosya adlarını sunucu üretir, istemciden dosya yolu alınmaz. |
| GitHub'a giden içerik | Özel depoya gider, herkese açık olmaz. Kullanıcı notu kod bloğu içine konur (Markdown/bahsetme etkisizleşir), başlıktaki model adı güvenli karakterlere indirgenir. |
| Anahtar | Fine-grained token: **yalnızca** `tartim-raporlar` deposu, **yalnızca** "Issues: Read and write" izni, süreli. Root'a ait 0600 dosyada durur; servise systemd `LoadCredential` ile verilir (ortam değişkeninde ve günlükte görünmez). |
| Servis yalıtımı | `DynamicUser`, `ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`, boş yetki kümesi, bellek sınırı 96 MB. `systemd-analyze security tartim-rapor` puanı: 3.4 (OK). |
| Günlük | Rapor içeriği ve IP adresleri günlüğe yazılmaz; yalnızca rapor numaraları. |

**En kötü durum:** biri sınırları zorlayarak sahte rapor gönderirse özel depoda
birkaç gereksiz kayıt oluşur; bunlar silinir. Anahtar sızsa bile yalnızca o özel
depoda issue açabilir; başka depoya, koda ya da hesaba erişemez. Şüphe halinde
token GitHub'dan tek tıkla iptal edilir.

Daha sıkı bir kurulum isteyen kurumlar (yalnızca kendi personeli gönderebilsin)
uç noktayı internete açmak yerine yalnızca Tailscale/VPN adresinden
yayınlayabilir.

## Kurulum

Gerekenler: Ubuntu/Debian, systemd, nginx ve "listen 443 ssl" bloğu olan bir site.

```sh
git clone https://github.com/muratGursel/tartim.git
sudo sh tartim/server/kur.sh /etc/nginx/sites-enabled/SITE
```

Betik servisi kurar, nginx yapılandırmasını yedekleyip (`/root/tartim-rapor-yedek/`)
`include snippets/tartim-rapor.conf;` satırını ekler, `nginx -t` başarısız olursa
her şeyi geri alır. Tekrar çalıştırmak güvenlidir (güncelleme için de kullanılır).

## GitHub anahtarını eklemek

1. GitHub → **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**
   - **Token name:** `tartim-rapor-sunucusu`
   - **Expiration:** 1 yıl (takvime yenileme hatırlatması koyun)
   - **Repository access:** *Only select repositories* → `tartim-raporlar`
   - **Permissions → Repository permissions → Issues:** *Read and write*
     (Metadata: Read-only otomatik gelir; başka izin vermeyin)
2. Token'ı kopyalayın ve **kendi uçbiriminizde** şu komutu çalıştırın.
   Token'ı herhangi bir sohbete, e-postaya ya da dosyaya yapıştırmayın:

   ```sh
   ssh -t SUNUCU 'read -rsp "Token: " T; echo; printf %s "$T" | sudo tee /etc/tartim-rapor/github-token >/dev/null; unset T; sudo systemctl restart tartim-rapor; sudo journalctl -u tartim-rapor -n 3 --no-pager'
   ```

   Token yazarken ekranda görünmez. Son satırda `GitHub iletimi: açık` yazmalı.
   Anahtar yokken gelen raporlar sunucuda bekler ve anahtar eklenince iletilir.

## İşletim

```sh
systemctl status tartim-rapor                 # durum
journalctl -u tartim-rapor -f                 # günlük
sudo ls /var/lib/private/tartim-rapor/gelen     # iletilmeyi bekleyenler
sudo ls /var/lib/private/tartim-rapor/iletildi  # iletilenler (issue adresiyle)
curl https://SUNUCU/tartim/saglik             # {"ok": true}
```

**Anahtarı iptal etmek:** GitHub'da token'ı silin ve sunucuda
`sudo truncate -s0 /etc/tartim-rapor/github-token && sudo systemctl restart tartim-rapor`.

**Kaldırmak:** `sudo systemctl disable --now tartim-rapor`, site dosyasındaki
`include snippets/tartim-rapor.conf;` satırını silip `sudo nginx -t && sudo systemctl reload nginx`.

## Kişisel veriler

Raporlar test ölçümü içindir; kullanıcı her gönderimde gerçek bir danışana ait
olmadığını onaylar. Yine de raporlarda test kişisinin yaş, boy, cinsiyet ve vücut
değerleri bulunabilir. Bu yüzden raporlar yalnızca sunucuda ve özel depoda
tutulur; herkese açık yayımlanmaz. İşi biten raporları silin.
