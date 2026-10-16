#!/bin/sh
# Tartım rapor sunucusunu kurar ya da günceller (Ubuntu/Debian, systemd, nginx).
#
#   sudo sh server/kur.sh /etc/nginx/sites-enabled/SITE
#
# SITE: "listen 443 ssl" bloğu olan nginx site dosyası. Betik birden çok kez
# güvenle çalıştırılabilir. nginx denetimi başarısız olursa değişiklikler geri alınır.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SITE=$(readlink -f "${1:?nginx site dosyasını verin}")
BACKUPS=/root/tartim-rapor-yedek

[ "$(id -u)" -eq 0 ] || { echo "Yönetici olarak çalıştırın (sudo)." >&2; exit 1; }
grep -q "listen 443" "$SITE" || { echo "$SITE içinde 443 bloğu yok." >&2; exit 1; }

echo "1/4 Servis dosyaları"
install -D -m 644 "$HERE/tartim_rapor_sunucusu.py" /opt/tartim-rapor/tartim_rapor_sunucusu.py
install -d -m 700 /etc/tartim-rapor
# Anahtar dosyası boş olarak oluşturulur; içine token'ı yönetici koyar (bkz. KURULUM.md).
[ -e /etc/tartim-rapor/github-token ] || install -m 600 /dev/null /etc/tartim-rapor/github-token
install -m 644 "$HERE/tartim-rapor.service" /etc/systemd/system/tartim-rapor.service

echo "2/4 Servis"
systemctl daemon-reload
systemctl enable tartim-rapor >/dev/null
systemctl restart tartim-rapor
sleep 1
systemctl is-active --quiet tartim-rapor || { journalctl -u tartim-rapor -n 20 --no-pager; exit 1; }

echo "3/4 nginx"
install -d -m 700 "$BACKUPS"
STAMP=$(date +%Y%m%d-%H%M%S)
cp -p "$SITE" "$BACKUPS/$(basename "$SITE").$STAMP"
[ -e /etc/nginx/conf.d/tartim-rapor.conf ] && had_conf=1 || had_conf=0
install -m 644 "$HERE/nginx/conf.d-tartim-rapor.conf" /etc/nginx/conf.d/tartim-rapor.conf
install -m 644 "$HERE/nginx/snippet-tartim-rapor.conf" /etc/nginx/snippets/tartim-rapor.conf
if ! grep -q "snippets/tartim-rapor.conf" "$SITE"; then
    # 443 bloğunda sertifika anahtarı satırının hemen altına eklenir.
    sed -i '/^\s*ssl_certificate_key /a\    include snippets/tartim-rapor.conf;  # Tartım rapor sunucusu' "$SITE"
fi
if ! nginx -t 2>/tmp/tartim-nginx-test; then
    cat /tmp/tartim-nginx-test >&2
    echo "nginx denetimi başarısız, değişiklikler geri alınıyor." >&2
    cp -p "$BACKUPS/$(basename "$SITE").$STAMP" "$SITE"
    [ "$had_conf" -eq 1 ] || rm -f /etc/nginx/conf.d/tartim-rapor.conf
    rm -f /etc/nginx/snippets/tartim-rapor.conf
    exit 1
fi
systemctl reload nginx

echo "4/4 Denetim"
curl -fsS http://127.0.0.1:8095/tartim/saglik && echo
if [ -s /etc/tartim-rapor/github-token ]; then
    echo "GitHub anahtarı: var"
else
    echo "GitHub anahtarı: YOK. Raporlar şimdilik yalnızca sunucuda saklanacak (KURULUM.md)."
fi
