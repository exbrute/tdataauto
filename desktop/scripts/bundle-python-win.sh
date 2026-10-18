#!/usr/bin/env bash
# Build a Windows embeddable CPython that already contains tdataauto and its wheels.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
CACHE="${ROOT}/build/cache"
DEST="${ROOT}/build/python-win"
PY_VER="3.11.9"
EMBED_URL="https://www.python.org/ftp/python/${PY_VER}/python-${PY_VER}-embed-amd64.zip"
EMBED_ZIP="${CACHE}/python-${PY_VER}-embed-amd64.zip"
WHEEL_DIR="${CACHE}/wheels-cp311"

mkdir -p "$CACHE"
rm -rf "$WHEEL_DIR"
mkdir -p "$WHEEL_DIR"
if [[ ! -f "$EMBED_ZIP" ]]; then
  curl -fsSL "$EMBED_URL" -o "$EMBED_ZIP"
fi

rm -rf "$DEST"
mkdir -p "$DEST"
unzip -q "$EMBED_ZIP" -d "$DEST"

python3 -m pip download \
  --dest "$WHEEL_DIR" \
  --only-binary=:all: \
  --platform win_amd64 \
  --python-version 3.11 \
  --implementation cp \
  "aiogram>=3.13,<4" \
  "aiofiles>=24.1" \
  "python-dotenv>=1.0" \
  "pyqt5" \
  "tgcrypto>=1.2.5" \
  "rsa" \
  "python-socks"

python3 -m pip download \
  --dest "$WHEEL_DIR" \
  --no-deps \
  --only-binary=:all: \
  --platform win_amd64 \
  --python-version 3.11 \
  --implementation cp \
  "telethon>=1.45" \
  "opentele>=1.15.1"

python3 -m pip download --dest "$WHEEL_DIR" --no-deps --no-binary=:all: pyaes

SITE="${DEST}/Lib/site-packages"
mkdir -p "$SITE"
shopt -s nullglob
for wheel in "$WHEEL_DIR"/*.whl; do
  unzip -q -o "$wheel" -d "$SITE"
done
for archive in "$WHEEL_DIR"/pyaes-*.tar.gz; do
  tmp="$(mktemp -d)"
  tar -xzf "$archive" -C "$tmp"
  src="$(find "$tmp" -type d -name pyaes | head -1)"
  if [[ -z "$src" ]]; then
    src="$(find "$tmp" -type f -name 'pyaes.py' | head -1)"
    cp "$src" "$SITE/pyaes.py"
  else
    rm -rf "$SITE/pyaes"
    cp -a "$src" "$SITE/pyaes"
  fi
  rm -rf "$tmp"
done

# Some wheels keep files under *.data/purelib or platlib.
find "$SITE" -type d \( -name purelib -o -name platlib \) | while read -r libdir; do
  cp -a "$libdir"/. "$SITE"/
done

rm -rf "$SITE/tdataauto"
mkdir -p "$SITE/tdataauto"
cp -a "$REPO/tdataauto"/. "$SITE/tdataauto/"
find "$SITE/tdataauto" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$SITE/tdataauto" -type f -name '*.pyc' -delete

PTH="$(echo "$DEST"/python*._pth)"
PY_ZIP="$(basename "$DEST"/python3*.zip)"
cat > "$PTH" <<EOF
${PY_ZIP}
.
Lib\\site-packages
import site
EOF

test -f "$DEST/python.exe"
test -d "$SITE/tdataauto"
test -d "$SITE/telethon"
test -d "$SITE/opentele"
test -d "$SITE/pyaes"
find "$SITE" -name 'tgcrypto*.pyd' -print -quit | grep -q .
echo "Windows Python runtime ready: $DEST"
