#!/bin/sh
# Installs or updates the Tartım report server (Ubuntu/Debian, systemd, nginx).
#
#   sudo sh server/install.sh /etc/nginx/sites-enabled/SITE
#
# SITE: an nginx site file with a "listen 443 ssl" block. The script is safe to
# run more than once. If the nginx check fails, the changes are rolled back.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SITE=$(readlink -f "${1:?give the nginx site file}")
BACKUPS=/root/tartim-rapor-yedek

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
grep -q "listen 443" "$SITE" || { echo "$SITE has no 443 block." >&2; exit 1; }

echo "1/4 Service files"
install -D -m 644 "$HERE/report_server.py" /opt/tartim-rapor/report_server.py
rm -f /opt/tartim-rapor/tartim_rapor_sunucusu.py  # file name before 0.6
install -d -m 700 /etc/tartim-rapor
# The token file is created empty; the administrator puts the token in it (see INSTALL.md).
[ -e /etc/tartim-rapor/github-token ] || install -m 600 /dev/null /etc/tartim-rapor/github-token
install -m 644 "$HERE/tartim-rapor.service" /etc/systemd/system/tartim-rapor.service

echo "2/4 Service"
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
    # Added right below the certificate key line of the 443 block.
    sed -i '/^\s*ssl_certificate_key /a\    include snippets/tartim-rapor.conf;  # Tartim report server' "$SITE"
fi
if ! nginx -t 2>/tmp/tartim-nginx-test; then
    cat /tmp/tartim-nginx-test >&2
    echo "nginx check failed, rolling back." >&2
    cp -p "$BACKUPS/$(basename "$SITE").$STAMP" "$SITE"
    [ "$had_conf" -eq 1 ] || rm -f /etc/nginx/conf.d/tartim-rapor.conf
    rm -f /etc/nginx/snippets/tartim-rapor.conf
    exit 1
fi
systemctl reload nginx

echo "4/4 Check"
curl -fsS http://127.0.0.1:8095/tartim/health && echo
if [ -s /etc/tartim-rapor/github-token ]; then
    echo "GitHub token: present"
else
    echo "GitHub token: MISSING. Reports are only stored on the server for now (INSTALL.md)."
fi
