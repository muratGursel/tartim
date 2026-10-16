#!/bin/sh
# tartim kurulum betiği (Pardus ve Debian tabanlı sistemler).
#
#   curl -fsSL https://raw.githubusercontent.com/muratGursel/tartim/main/install.sh | sudo sh
#
# GitHub'daki son sürümün .deb paketini indirir ve bağımlılıklarıyla kurar.
set -eu

REPO="muratGursel/tartim"

if [ "$(id -u)" -ne 0 ]; then
    echo "Bu betik yönetici yetkisi ister. Şöyle çalıştırın: ... | sudo sh" >&2
    exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
    echo "Bu betik Pardus ve Debian tabanlı sistemler içindir (apt bulunamadı)." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    apt-get update -q && apt-get install -y -q curl
fi

echo "Son sürüm aranıyor..."
URL=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"browser_download_url": *"\([^"]*_all\.deb\)".*/\1/p' | head -n 1)
if [ -z "$URL" ]; then
    echo "İndirilecek paket bulunamadı: https://github.com/$REPO/releases" >&2
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
DEB="$TMP/$(basename "$URL")"
echo "İndiriliyor: $URL"
curl -fsSL -o "$DEB" "$URL"
chmod 644 "$DEB"

apt-get update -q
apt-get install -y -q "$DEB"

echo
echo "tartim kuruldu: $(tartim --surum)"
echo "Tartıyı takıp deneyin:  tartim portlar"
echo "Cihaz raporu için:      tartim rapor"
