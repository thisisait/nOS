#!/bin/bash
# build-app.sh <out-dir> [signing-identity-hash]: swift build -c release, assemble <out-dir>/nOS.app,
# sign it ad-hoc, or with the hash pazny.medulla mints (_thalamus_signing). FACE_URL sets NOSFaceURL.
set -euo pipefail
OUT=${1:?usage: build-app.sh <out-dir> [identity-hash]}
IDENTITY=${2:--}
FACE_URL=${FACE_URL:-https://os.dev.local/}  # face_domain's default; the role passes the resolved one
HERE=$(cd "$(dirname "$0")" && pwd)
SCRATCH=${SWIFT_SCRATCH:-$HERE/.build}  # the role keeps it off the checkout

swift build -c release --package-path "$HERE" --scratch-path "$SCRATCH" --product nOS
BIN=$(swift build -c release --package-path "$HERE" --scratch-path "$SCRATCH" --show-bin-path)/nOS

APP="$OUT/nOS.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/nOS"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>nOS</string>
  <key>CFBundleDisplayName</key><string>nOS</string>
  <key>CFBundleExecutable</key><string>nOS</string>
  <key>CFBundleIdentifier</key><string>eu.thisisait.nos.app</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NOSFaceURL</key><string>${FACE_URL}</string>
</dict>
</plist>
EOF
plutil -lint "$APP/Contents/Info.plist"
codesign -f -s "$IDENTITY" -i eu.thisisait.nos.app "$APP"
echo "$APP"
