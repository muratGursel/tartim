#!/bin/sh
# tartim installer (Pardus and Debian-based systems).
#
#   curl -fsSL https://raw.githubusercontent.com/muratGursel/tartim/main/install.sh | sudo sh
#
# Downloads the .deb package of the latest GitHub release and installs it with
# its dependencies. Messages are in Turkish on a Turkish system, otherwise English.
set -eu

REPO="muratGursel/tartim"

case "${LANGUAGE:-${LC_ALL:-${LANG:-}}}" in
    tr*) TR=1 ;;
    *) TR=0 ;;
esac

# say "English text" "Türkçe metin"
say() { if [ "$TR" -eq 1 ]; then echo "$2"; else echo "$1"; fi; }

if [ "$(id -u)" -ne 0 ]; then
    say "This script needs administrator rights. Run it like this: ... | sudo sh" \
        "Bu betik yönetici yetkisi ister. Şöyle çalıştırın: ... | sudo sh" >&2
    exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
    say "This script is for Pardus and Debian-based systems (apt not found)." \
        "Bu betik Pardus ve Debian tabanlı sistemler içindir (apt bulunamadı)." >&2
    exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
    apt-get update -q && apt-get install -y -q curl
fi

say "Looking for the latest release..." "Son sürüm aranıyor..."
URL=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"browser_download_url": *"\([^"]*_all\.deb\)".*/\1/p' | head -n 1)
if [ -z "$URL" ]; then
    say "No package found to download: https://github.com/$REPO/releases" \
        "İndirilecek paket bulunamadı: https://github.com/$REPO/releases" >&2
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
DEB="$TMP/$(basename "$URL")"
say "Downloading: $URL" "İndiriliyor: $URL"
curl -fsSL -o "$DEB" "$URL"
chmod 644 "$DEB"

apt-get update -q
apt-get install -y -q "$DEB"

echo
VERSION=$(tartim --version)
say "tartim installed: $VERSION" "tartim kuruldu: $VERSION"
say "Plug in the scale and try:  tartim ports" "Tartıyı takıp deneyin:  tartim portlar"
say "For a device report:        tartim report" "Cihaz raporu için:      tartim rapor"
