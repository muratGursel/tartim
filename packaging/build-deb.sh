#!/bin/sh
# Builds the tartim .deb package for Pardus/Debian: dist/tartim_VERSION_all.deb
# Needs dpkg-deb (installed by default on Pardus). Usage: sh packaging/build-deb.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/tartim/__init__.py")
PYPROJECT_VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")
if [ "$VERSION" != "$PYPROJECT_VERSION" ]; then
    echo "Version mismatch: tartim/__init__.py=$VERSION, pyproject.toml=$PYPROJECT_VERSION" >&2
    exit 1
fi

BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
PKG="$BUILD/tartim"
LIB="$PKG/usr/lib/python3/dist-packages/tartim"
DOC="$PKG/usr/share/doc/tartim"

install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$LIB/locale" "$PKG/usr/lib/udev/rules.d" "$DOC" \
    "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps"

install -m 644 "$ROOT"/tartim/*.py "$LIB/"
install -m 644 "$ROOT"/tartim/locale/*.po "$LIB/locale/"
install -m 755 "$ROOT/packaging/debian/tartim" "$PKG/usr/bin/tartim"
install -m 755 "$ROOT/packaging/debian/tartim-arayuz" "$PKG/usr/bin/tartim-arayuz"
install -m 644 "$ROOT/packaging/debian/io.github.muratgursel.Tartim.desktop" \
    "$PKG/usr/share/applications/"
install -m 644 "$ROOT/packaging/debian/io.github.muratgursel.Tartim.svg" \
    "$PKG/usr/share/icons/hicolor/scalable/apps/"
install -m 644 "$ROOT/packaging/debian/70-tartim.rules" "$PKG/usr/lib/udev/rules.d/"
install -m 644 "$ROOT/README.md" "$ROOT/README.tr.md" "$ROOT/docs/PROTOCOL.md" \
    "$ROOT/docs/USER_GUIDE.md" "$ROOT/docs/KULLANIM.md" "$ROOT/docs/Tartim-User-Guide.pdf" \
    "$ROOT/docs/Tartim-Kullanim-Kilavuzu.pdf" "$DOC/"
install -m 644 "$ROOT/packaging/debian/copyright" "$DOC/copyright"
install -m 755 "$ROOT/packaging/debian/postinst" "$ROOT/packaging/debian/prerm" "$PKG/DEBIAN/"

SIZE=$(du -sk "$PKG/usr" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" \
    "$ROOT/packaging/debian/control" > "$PKG/DEBIAN/control"
(cd "$PKG" && find usr -type f -exec md5sum {} + > DEBIAN/md5sums)

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/tartim_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$PKG" "$OUT" >/dev/null
echo "$OUT"
