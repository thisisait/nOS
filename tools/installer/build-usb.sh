#!/bin/bash
# EXPERIMENTAL (v0.18). Builds an Ubuntu Server 24.04 LTS installer disk that turns a blank PC into an
# nOS host: one confirmation at boot, then the nOS checkout is in ~/nOS (run ./bootstrap.sh there).
# Proven 2026-11-01 on a 2012 Mac mini. macOS builder only (diskutil, Homebrew xorriso).
#
#   tools/installer/build-usb.sh --host mini --user alice              # asks the password, then the disk
#   tools/installer/build-usb.sh --host mini --user alice --render-only out/   # the seed only, no ISO, no disk
#
# Options: --keys FILE (repeatable; default every ~/.ssh/*.pub) · --timezone Europe/Prague ·
#   --broadcom-wifi (Broadcom BCM43xx driver, older Macs) · --max-gb 600 (refuse a bigger target disk).
# Never stores the password: only its SHA-512 crypt hash reaches the seed. Nothing personal is in the repo.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ISO_NAME=ubuntu-24.04.5-live-server-amd64.iso
ISO_URL=https://releases.ubuntu.com/24.04.5
CACHE="${NOS_INSTALLER_CACHE:-$HOME/.cache/nos-installer}"
HOST="" USER_NAME="" TZ_NAME="Europe/Prague" RENDER_ONLY="" BROADCOM=0 MAX_GB=600 KEYS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER_NAME="$2"; shift 2 ;;
    --keys) KEYS+=("$2"); shift 2 ;;
    --timezone) TZ_NAME="$2"; shift 2 ;;
    --broadcom-wifi) BROADCOM=1; shift ;;
    --max-gb) MAX_GB="$2"; shift 2 ;;
    --render-only) RENDER_ONLY="$2"; shift 2 ;;
    *) echo "unknown option $1 (see the header of $0)" >&2; exit 64 ;;
  esac
done
[[ "$HOST" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || { echo "--host must be a hostname (a-z, 0-9, -)" >&2; exit 64; }
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "--user must be a unix user name" >&2; exit 64; }
[ ${#KEYS[@]} -gt 0 ] || for k in "$HOME"/.ssh/*.pub; do [ -f "$k" ] && KEYS+=("$k"); done
[ ${#KEYS[@]} -gt 0 ] || { echo "no ssh public key (--keys FILE, or one in ~/.ssh/*.pub)" >&2; exit 64; }

echo "== 1/5 the seed for $USER_NAME@$HOST"
if [ -n "${NOS_INSTALLER_PASSWORD_HASH:-}" ]; then
  HASH="$NOS_INSTALLER_PASSWORD_HASH"          # tests only: a hash, never a password
else
  read -rsp "password for $USER_NAME (typed twice, only its hash is kept): " P1; echo
  read -rsp "again: " P2; echo
  [ -n "$P1" ] && [ "$P1" = "$P2" ] || { echo "empty or not the same — refusing" >&2; exit 1; }
  OPENSSL="$(brew --prefix openssl@3 2>/dev/null)/bin/openssl"; [ -x "$OPENSSL" ] || OPENSSL=openssl
  HASH="$(printf '%s' "$P1" | "$OPENSSL" passwd -6 -stdin)"; unset P1 P2
fi
OUT="${RENDER_ONLY:-$CACHE/build}"
mkdir -p "$OUT/nocloud"
KEYS_YAML="$(for k in "${KEYS[@]}"; do while read -r line; do [ -n "$line" ] && printf '      - %s\n' "$line"; done < "$k"; done)"
LATE=""; [ "$BROADCOM" = 1 ] && LATE="    - curtin in-target -- apt-get install -y bcmwl-kernel-source || true"
python3 - "$HERE/user-data.tmpl" "$OUT/nocloud/user-data" <<PY
import sys
t = open(sys.argv[1]).read()
for k, v in {"__TIMEZONE__": """$TZ_NAME""", "__HOSTNAME__": """$HOST""", "__USERNAME__": """$USER_NAME""",
             "__PASSWORD_HASH__": """$HASH""", "__KEYS__": """$KEYS_YAML""", "__EXTRA_LATE__": """$LATE"""}.items():
    t = t.replace(k, v)
t = "\n".join(l for l in t.splitlines() if l.strip()) + "\n"
assert "__" not in t, "a placeholder is left in the seed"
open(sys.argv[2], "w").write(t)
PY
: > "$OUT/nocloud/meta-data"
[ -n "$RENDER_ONLY" ] && { echo "seed written to $OUT/nocloud (render only)"; exit 0; }

echo "== 2/5 the official ISO, verified against Ubuntu's signed SHA256SUMS"
mkdir -p "$CACHE"; cd "$CACHE"
[ -f "$ISO_NAME" ] || curl -fL -o "$ISO_NAME" "$ISO_URL/$ISO_NAME"
curl -fsSL -o SHA256SUMS "$ISO_URL/SHA256SUMS"; curl -fsSL -o SHA256SUMS.gpg "$ISO_URL/SHA256SUMS.gpg"
command -v gpg >/dev/null || { echo "gpg is needed to check Ubuntu's signature (brew install gnupg)" >&2; exit 1; }
# Ubuntu CD image signing key (https://ubuntu.com/tutorials/how-to-verify-ubuntu).
gpg --keyserver hkps://keyserver.ubuntu.com --recv-keys 843938DF228D22F7B3742BC0D94AA3F0EFE21092 >/dev/null 2>&1 || true
gpg --verify SHA256SUMS.gpg SHA256SUMS 2>&1 | grep -q "Good signature" || { echo "SHA256SUMS signature is not good — refusing" >&2; exit 1; }
grep " \*\?$ISO_NAME\$" SHA256SUMS | shasum -a 256 -c - || { echo "ISO hash mismatch — refusing" >&2; exit 1; }

echo "== 3/5 xorriso"
command -v xorriso >/dev/null || brew install xorriso

echo "== 4/5 remaster: the seed on the disk, grub pointing at it"
rm -f "$OUT/grub.cfg" "$CACHE/nos-$HOST.iso"
xorriso -osirrox on -indev "$ISO_NAME" -extract /boot/grub/grub.cfg "$OUT/grub.cfg" 2>/dev/null
chmod u+w "$OUT/grub.cfg"
sed -i '' -e 's|/casper/vmlinuz  *---|/casper/vmlinuz ds=nocloud\\;s=/cdrom/nocloud/ ---|' -e 's|^set timeout=.*|set timeout=5|' "$OUT/grub.cfg"
grep -q 'ds=nocloud' "$OUT/grub.cfg" || { echo "grub.cfg not patched — refusing" >&2; exit 1; }
xorriso -indev "$ISO_NAME" -outdev "nos-$HOST.iso" -map "$OUT/nocloud" /nocloud -map "$OUT/grub.cfg" /boot/grub/grub.cfg -boot_image any replay 2>&1 | tail -2

echo "== 5/5 write it to an external disk"
diskutil list external physical
read -rp "disk to ERASE (e.g. disk4): " D
INFO="$(diskutil info "$D")"
echo "$INFO" | grep -q 'Device Location:.*External' || { echo "$D is not external — refusing" >&2; exit 1; }
BYTES="$(echo "$INFO" | sed -n 's/.*Disk Size:.*(\([0-9]*\) Bytes).*/\1/p')"
[ "${BYTES:-0}" -gt 4000000000 ] && [ "$BYTES" -lt $((MAX_GB * 1000000000)) ] \
  || { echo "$D is $BYTES bytes: not 4 GB .. ${MAX_GB} GB (a backup disk?) — refusing (--max-gb to change)" >&2; exit 1; }
read -rp "type ERASE to overwrite $D ($BYTES bytes): " OK; [ "$OK" = ERASE ] || exit 1
diskutil unmountDisk "/dev/$D"
sudo dd if="nos-$HOST.iso" of="/dev/r$D" bs=4m status=progress
sync; diskutil eject "/dev/$D"
echo "done: unplug every other large disk from the target, plug this one and the network cable, boot from it."
