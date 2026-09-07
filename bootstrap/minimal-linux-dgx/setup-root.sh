#!/usr/bin/env bash
# =============================================================================
# nos-dgx setup — the ROOT half. Idempotent; re-run freely.
#
#   sudo bash <nOS checkout>/bootstrap/minimal-linux-dgx/setup-root.sh
#
# What it does, in order: packages · groups + users (tester) · /srv layout
# (runtime checkout, seed repo, config) · secrets in /etc/nos · mkcert TLS ·
# nginx + PAM · native Ollama as a system service (models migrated from the old
# bundle volume) · per-user shelves · compose up + knowledge ingest + tables (as admin).
# =============================================================================
set -euo pipefail

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # this recipe dir (bootstrap/minimal-linux-dgx in the nOS checkout)
RT=/srv/nos-dgx
SRC=/srv/nos
SEED=/srv/nos-seed.git
DEV_CHECKOUT=/home/admin/projects/nOS
DEV_BRANCH=feat/minimal-linux-dgx
KEAP_REPO=https://github.com/thisisait/nos-keap.git
KEAP_PIN=v1.44.0            # mirrors default.config.yml keap_version
# The name is read LIVE: rename the box (DGX dashboard → reboot), re-run this
# script, and every hostname-bearing file is re-rendered from the templates,
# the leaf certificate re-issued (same CA — nobody re-imports anything), nginx
# and the compose stack restarted with the new origin.
SHORT="$(hostname -s)"
HOST="$SHORT.local"
MAINTAINERS="admin"
# Per-user ceilings (systemd user-<uid>.slice): a developer's build, Lab or
# rootless containers all live in that slice, so one cap covers them all and
# none of them can starve Ollama/KEAP. 121 GB box: 32G / 10 cores per user.
NOS_USER_MEM_MAX="${NOS_USER_MEM_MAX:-32G}"
NOS_USER_CPU_QUOTA="${NOS_USER_CPU_QUOTA:-1000%}"
# Every member of nos-users gets a shelf — the group is the roster, not this file.
USERS_ALL=""

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx libnginx-mod-http-auth-pam mkcert libnss3-tools \
  python3-yaml python3-markdown sqlite3 rsync curl git \
  docker-ce-rootless-extras uidmap passt fuse-overlayfs restic >/dev/null

say "groups + users"
groupadd -f nos-users
groupadd -f nos-maintainers
for u in $MAINTAINERS; do usermod -aG nos-users,nos-maintainers "$u"; done
if ! id tester >/dev/null 2>&1; then
  useradd -m -s /bin/bash -G nos-users -c "nOS feature tester (minimal rights)" tester
  pw="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)"
  echo "tester:$pw" | chpasswd
  install -m 0600 /dev/null /root/nos-tester.initial-password
  echo "$pw" > /root/nos-tester.initial-password
  echo "created user tester — initial password in /root/nos-tester.initial-password (0600)"
else
  usermod -aG nos-users tester
  echo "user tester exists"
fi
# tester: NOT in docker, NOT in sudo — that is the point.
gpasswd -d tester docker >/dev/null 2>&1 || true
gpasswd -d tester sudo   >/dev/null 2>&1 || true
USERS_ALL="$(getent group nos-users | cut -d: -f4 | tr , " ")"

say "developer substrate: linger, per-user ceilings, rootless-docker prerequisites"
# linger: the user's systemd instance (and with it rootless dockerd, dev
# servers, JupyterLab kernels) runs without a login session and after logout.
for u in $USERS_ALL; do loginctl enable-linger "$u"; done
install -d /etc/systemd/system/user-.slice.d
cat > /etc/systemd/system/user-.slice.d/50-nos-dgx.conf <<EOF
# nos-dgx: ceilings for EVERY user slice (setup-root.sh, NOS_USER_MEM_MAX / NOS_USER_CPU_QUOTA)
[Slice]
MemoryMax=$NOS_USER_MEM_MAX
CPUQuota=$NOS_USER_CPU_QUOTA
EOF
systemctl daemon-reload
# Ubuntu 24.04 restricts unprivileged user namespaces to AppArmor-profiled
# binaries; rootlesskit needs the userns permission or every rootless dockerd
# dies at start. Idempotent: written only when no profile names the binary.
if ! grep -rqs '/usr/bin/rootlesskit' /etc/apparmor.d/ 2>/dev/null; then
  cat > /etc/apparmor.d/usr.bin.rootlesskit <<'EOF'
abi <abi/4.0>,
include <tunables/global>

/usr/bin/rootlesskit flags=(unconfined) {
  userns,
  include if exists <local/usr.bin.rootlesskit>
}
EOF
  systemctl restart apparmor
fi
echo "linger: $(ls /var/lib/systemd/linger | tr '\n' ' ')· slice cap $NOS_USER_MEM_MAX / $NOS_USER_CPU_QUOTA"

say "/srv layout"
mkdir -p "$RT"
rsync -a --exclude 'keap/' --exclude '*.log' --exclude '__pycache__' "$STAGE/" "$RT/"
# Render the hostname templates (__HOST__ = <short>.local, __SHORT__ = <short>).
for f in nginx/nos-dgx.conf compose.yml www/index.html; do
  sed -i "s/__HOST__/$HOST/g; s/__SHORT__/$SHORT/g" "$RT/$f"
done
echo "rendered for host $HOST"
# The knowledge base: one markdown file per page in kb/, static HTML in www/kb/.
python3 "$RT/bin/kb-build.py" --src "$RT/kb" --out "$RT/www/kb" --host "$HOST" --short "$SHORT"
mkdir -p "$RT/keap/data"
if [ ! -d "$RT/keap/src/.git" ]; then
  sudo -u admin git clone -q --branch "$KEAP_PIN" --depth 1 "$KEAP_REPO" "$RT/keap/src"
  echo "cloned nos-keap $KEAP_PIN"
fi
KEAP_SHA="$(git -C "$RT/keap/src" rev-parse --short HEAD)"
KEAP_TAG="nos/keap:${KEAP_PIN#v}-$KEAP_SHA"
if ! docker image inspect "$KEAP_TAG" >/dev/null 2>&1; then
  echo "building $KEAP_TAG (native $(uname -m), several minutes)…"
  docker build -q -t "$KEAP_TAG" "$RT/keap/src" >/dev/null
fi
sed -i "s|image: nos/keap:.*|image: $KEAP_TAG|" "$RT/compose.yml"
chown -R admin:nos-maintainers "$RT"
chmod -R g+rwX,o+rX "$RT"
find "$RT" -type d -exec chmod g+s {} +
chmod +x "$RT"/bin/* "$RT"/setup-root.sh

if [ ! -d "$SRC/.git" ]; then
  install -d -o admin -g nos-maintainers -m 2775 "$SRC"
  sudo -u admin git clone -q -b "$DEV_BRANCH" "$DEV_CHECKOUT" "$SRC"
  sudo -u admin git -C "$SRC" remote set-url origin https://github.com/thisisait/nOS.git
  echo "cloned $DEV_CHECKOUT@$DEV_BRANCH -> $SRC (origin re-pointed to GitHub)"
else
  echo "$SRC present ($(git -C "$SRC" rev-parse --abbrev-ref HEAD))"
fi
chown -R admin:nos-maintainers "$SRC"
chmod -R g+rwX,o+rX "$SRC"
ln -sfn "$SRC/tools/nos" /usr/local/bin/nos
# Both /srv repos are owned by admin; git's dubious-ownership guard refuses
# them for every other user. System-level (/etc/gitconfig) is the one place
# that reaches all of them without touching a home directory.
for d in "$SRC" "$SEED"; do
  git config --system --get-all safe.directory 2>/dev/null | grep -qx "$d" || git config --system --add safe.directory "$d"
done

if [ ! -d "$SEED" ]; then
  install -d -o admin -g nos-maintainers -m 2775 "$SEED"
  sudo -u admin git init -q --bare --shared=group "$SEED"
  echo "created bare seed repo $SEED"
fi
chown -R admin:nos-maintainers "$SEED"
chmod -R g+rwX,o+rX "$SEED"

say "secrets in /etc/nos"
mkdir -p /etc/nos
if [ ! -f /etc/nos/keap-compose.env ]; then
  umask 077
  cat > /etc/nos/keap-compose.env <<EOF
KEAP_AGENT_TOKEN_RO=$(openssl rand -hex 32)
KEAP_AGENT_TOKEN_RW=$(openssl rand -hex 32)
KEAP_AGENT_TOKEN_CAPTURE=$(openssl rand -hex 32)
KEAP_PROXY_SHARED_SECRET=$(openssl rand -hex 32)
EOF
  umask 022
  echo "generated tokens"
fi
# shellcheck disable=SC1091
. /etc/nos/keap-compose.env
chown root:nos-maintainers /etc/nos/keap-compose.env; chmod 0640 /etc/nos/keap-compose.env
# Derived, always rewritten from the one source above.
install -m 0640 -o root -g nos-users /dev/null /etc/nos/keap.env
cat > /etc/nos/keap.env <<EOF
KEAP_API_URL=http://127.0.0.1:8091
KEAP_AGENT_TOKEN_RO=$KEAP_AGENT_TOKEN_RO
NOS_ROADMAP_TABLE_ID=roadmap
EOF
install -m 0640 -o root -g nos-maintainers /dev/null /etc/nos/keap-rw.env
cat > /etc/nos/keap-rw.env <<EOF
KEAP_AGENT_TOKEN_RW=$KEAP_AGENT_TOKEN_RW
KEAP_AGENT_TOKEN_CAPTURE=$KEAP_AGENT_TOKEN_CAPTURE
KEAP_PROXY_SHARED_SECRET=$KEAP_PROXY_SHARED_SECRET
EOF
install -m 0640 -o root -g www-data /dev/null /etc/nginx/nos-keap-secret.conf
printf 'proxy_set_header x-keap-proxy-secret "%s";\n' "$KEAP_PROXY_SHARED_SECRET" > /etc/nginx/nos-keap-secret.conf
install -m 0644 "$RT/profile.d/nos.sh" /etc/profile.d/nos.sh

say "TLS (mkcert, CAROOT=/etc/nos/mkcert)"
export CAROOT=/etc/nos/mkcert
mkdir -p "$CAROOT" /etc/nginx/tls
mkcert -install >/dev/null 2>&1 || mkcert -install
# Every address a client may type: the Wi-Fi LAN IP and the USB (corporate)
# uplink IP, read live. Re-issue when a current address is missing from the cert.
IPS="$(ip -4 -o addr show scope global | awk '!/docker|br-|veth/ {print $4}' | cut -d/ -f1 | tr '\n' ' ')"
need=0
for a in $IPS; do
  openssl x509 -in /etc/nginx/tls/spark.pem -noout -text 2>/dev/null | grep -q "IP Address:$a" || need=1
done
openssl x509 -in /etc/nginx/tls/spark.pem -noout -text 2>/dev/null | grep -q "DNS:$HOST" || need=1
if [ ! -f /etc/nginx/tls/spark.pem ] || [ "$need" = 1 ]; then
  # shellcheck disable=SC2086
  mkcert -cert-file /etc/nginx/tls/spark.pem -key-file /etc/nginx/tls/spark-key.pem \
    "$HOST" "$SHORT" $IPS localhost 127.0.0.1
fi
chmod 0640 /etc/nginx/tls/spark-key.pem; chgrp www-data /etc/nginx/tls/spark-key.pem
install -m 0644 "$CAROOT/rootCA.pem" "$RT/www/nos-dgx-rootCA.pem"

say "mDNS: announce only the physical uplinks (never a docker bridge)"
# avahi otherwise answers <host>.local with 172.18.0.1 (a bridge) on this
# box; a LAN client must get the address of the interface it asked on.
if ! grep -qE '^allow-interfaces=' /etc/avahi/avahi-daemon.conf; then
  sed -i 's/^\[server\]$/[server]\nallow-interfaces=wlP9s9,enx0c37962a9dc5,enP7s7/' /etc/avahi/avahi-daemon.conf
  systemctl restart avahi-daemon
fi

say "firewall: the three web ports + mDNS (ufw is active on this DGX)"
if ufw status | grep -q '^Status: active'; then
  for p in 443 8443 8444 8445 8446 8447; do ufw allow $p/tcp >/dev/null; done
  ufw allow 5353/udp >/dev/null
  ufw status | grep -E '^(443|8443|8444|8445|8446|8447|5353)' | sed 's/^/  /'
fi

say "nginx + PAM"
install -m 0644 "$RT/nginx/pam-nginx" /etc/pam.d/nginx
install -m 0644 "$RT/nginx/pam-nginx-admin" /etc/pam.d/nginx-admin
usermod -aG shadow www-data
install -m 0644 "$RT/nginx/nos-dgx-tls.conf" /etc/nginx/nos-dgx-tls.conf
install -m 0644 "$RT/nginx/nos-dgx.conf" /etc/nginx/sites-available/nos-dgx.conf
ln -sfn /etc/nginx/sites-available/nos-dgx.conf /etc/nginx/sites-enabled/nos-dgx.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable -q nginx
systemctl restart nginx
echo "nginx: $(systemctl is-active nginx)"

say "native Ollama (system service)"
# A shell script at that path is the old `docker exec open-webui ollama`
# wrapper, not a binary — move it aside so the real install lands.
if [ -f /usr/local/bin/ollama ] && head -c 2 /usr/local/bin/ollama | grep -q '#!'; then
  mv /usr/local/bin/ollama /usr/local/bin/ollama.docker-wrapper.bak
  echo "moved the docker-exec wrapper aside: /usr/local/bin/ollama.docker-wrapper.bak"
fi
if ! [ -x /usr/local/bin/ollama ] || ! id ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
mkdir -p /etc/systemd/system/ollama.service.d
install -m 0644 "$RT/systemd/ollama-override.conf" /etc/systemd/system/ollama.service.d/nos-dgx.conf
OLD_VOL=/var/lib/docker/volumes/open-webui-ollama/_data/models
NEW_MODELS=/usr/share/ollama/.ollama/models
if [ -d "$OLD_VOL/manifests" ] && [ ! -d "$NEW_MODELS/manifests" ]; then
  echo "migrating models from the old bundle volume ($(du -sh "$OLD_VOL" | cut -f1))…"
  mkdir -p "$NEW_MODELS"
  rsync -a "$OLD_VOL/" "$NEW_MODELS/"
fi
chown -R ollama:ollama /usr/share/ollama
systemctl daemon-reload
systemctl enable -q ollama
systemctl restart ollama
sleep 2
echo "ollama: $(systemctl is-active ollama) — $(curl -fsS -m 5 http://172.17.0.1:11434/api/version 2>/dev/null || echo 'API not answering yet')"

say "Open WebUI accounts in the existing volume (for the nginx identity map)"
sqlite3 /var/lib/docker/volumes/open-webui/_data/webui.db \
  'select email, role, name from user;' 2>/dev/null || echo "(no webui.db readable)"

say "per-user shelves"
for u in $USERS_ALL; do
  uid="$(id -u "$u")"
  echo "-- $u"
  sudo -u "$u" -H env NOS_SRC="$SRC" \
    XDG_RUNTIME_DIR="/run/user/$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
    "$RT/bin/nos-user-setup" || true
done

say "JupyterHub (native, root-owned runtime; per-user Labs as the Linux user)"
JH=/opt/nos-dgx/jupyterhub
install -d -m 0755 "$JH"
install -d -m 0700 /var/lib/nos-dgx/jupyterhub
if [ ! -x "$JH/venv/bin/jupyterhub" ]; then
  python3 -m venv "$JH/venv"
  "$JH/venv/bin/pip" install -q --upgrade pip
  "$JH/venv/bin/pip" install -q jupyterhub jupyterlab notebook ipykernel ipywidgets \
    pandas matplotlib requests pyyaml
fi
# Node for the Hub's proxy: configurable-http-proxy needs >= 20, Ubuntu's apt
# nodejs is 18, and the only other Node on this box lives in admin's home
# (Hermes's private copy) — a root service must not execute a user-writable
# binary. So: the official arm64 tarball, latest 22.x LTS, root-owned under
# /opt/nos-dgx/node, on the unit's PATH only.
NODE_DIR=/opt/nos-dgx/node
if [ ! -x "$NODE_DIR/bin/node" ]; then
  tarball="$(curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | awk '/linux-arm64.tar.xz/ {print $2}')"
  curl -fsSL "https://nodejs.org/dist/latest-v22.x/$tarball" -o /tmp/node.tar.xz
  install -d "$NODE_DIR"
  tar -xJf /tmp/node.tar.xz -C "$NODE_DIR" --strip-components=1
  rm -f /tmp/node.tar.xz
  echo "node $("$NODE_DIR/bin/node" --version) installed at $NODE_DIR"
fi
if [ ! -x "$JH/chp/node_modules/.bin/configurable-http-proxy" ]; then
  PATH="$NODE_DIR/bin:$PATH" "$NODE_DIR/bin/npm" install --silent --prefix "$JH/chp" configurable-http-proxy
fi
# The GPU kernel: torch for aarch64 + CUDA 13 (GB10 is sm_121). Best-effort —
# a missing wheel must not take the Hub down with it; the reader below says.
if [ "${JUPYTER_TORCH:-1}" = 1 ] && ! "$JH/venv/bin/python" -c 'import torch' 2>/dev/null; then
  "$JH/venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cu130 \
    || echo "torch (cu130, aarch64) did not install — Lab works, GPU kernel does not"
fi
chown -R root:root "$JH" "$NODE_DIR"; chmod -R o+rX,go-w "$JH" "$NODE_DIR"
install -m 0644 -o root -g root "$RT/jupyterhub/jupyterhub_config.py" /etc/nos/jupyterhub_config.py
install -m 0644 "$RT/systemd/jupyterhub.service" /etc/systemd/system/jupyterhub.service
systemctl daemon-reload
systemctl enable -q jupyterhub
systemctl restart jupyterhub
sleep 4
echo "jupyterhub: $(systemctl is-active jupyterhub) — $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8000/hub/login || echo no-answer) on /hub/login"
echo "torch cuda: $("$JH/venv/bin/python" -c 'import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")' 2>&1 | tail -1)"

say "backup disk + restic (nightly writer, morning verifier)"
BK=/srv/backup
if [ "${NOS_BACKUP_FORMAT:-}" = yes ] && [ -n "${NOS_BACKUP_DEVICE:-}" ]; then
  # DESTRUCTIVE, explicit opt-in: wipe the device, ext4, label nos-backup.
  # The desktop automounts a plugged disk under /media/<user>/…; a file manager
  # holding it makes wipefs say "busy", so: find every mountpoint of the REAL
  # device, kill what holds it, unmount (lazily as a last resort), then format.
  BKREAL="$(readlink -f "$NOS_BACKUP_DEVICE")"
  # Mountpoints may carry spaces/UTF-8 ("/media/admin/Nový svazek"): read them
  # line by line, unescaped (-n, no -r), and unmount by DEVICE, not by path.
  # No lazy unmount here: a lazily detached filesystem keeps the block
  # device busy for wipefs as long as any holder (Nautilus) lives. Kill the
  # holders, unmount for real, or stop and say who is holding it.
  # findmnt exits 1 when nothing is mounted — that is the GOOD case, and under
  # set -e + pipefail it would end the run silently; hence the `|| true`.
  { findmnt -no TARGET "$BKREAL" 2>/dev/null || true; } | while IFS= read -r mp; do
    fuser -km "$mp" 2>/dev/null || true
    sleep 1
    umount "$mp" || { echo "REFUSING: $mp still busy:"; fuser -vm "$mp" 2>&1; exit 1; }
  done
  if findmnt -n "$BKREAL" >/dev/null 2>&1; then
    echo "REFUSING: $BKREAL is still mounted"; exit 1
  fi
  wipefs -aq "$BKREAL"
  mkfs.ext4 -q -L nos-backup "$BKREAL"
  echo "formatted $BKREAL as ext4 (label nos-backup)"
fi
BKDEV="$(blkid -L nos-backup 2>/dev/null || true)"
if [ -n "$BKDEV" ]; then
  BKUUID="$(blkid -s UUID -o value "$BKDEV")"
  install -d "$BK"
  grep -q "$BKUUID" /etc/fstab || echo "UUID=$BKUUID $BK ext4 defaults,nofail,x-systemd.device-timeout=10 0 2" >> /etc/fstab
  systemctl daemon-reload
  mountpoint -q "$BK" || mount "$BK"
  chmod 0700 "$BK"
  echo "backup disk: $BKDEV on $BK, $(df -h "$BK" | awk 'NR==2{print $4}') free"
else
  echo "backup disk: no filesystem labelled nos-backup — the timer will refuse to run (README: NOS_BACKUP_DEVICE + NOS_BACKUP_FORMAT=yes once)"
fi
install -d -m 0700 /var/lib/nos-dgx/backup
# restic: apt ships 0.16, Backrest 1.14 requires >= 0.19.1. One binary for the
# timer AND the UI, from the upstream release, on /usr/local/bin ahead of apt's.
RESTIC_WANT=0.19.1
if ! /usr/local/bin/restic version 2>/dev/null | grep -q "restic $RESTIC_WANT"; then
  curl -fsSL "https://github.com/restic/restic/releases/download/v$RESTIC_WANT/restic_${RESTIC_WANT}_linux_arm64.bz2" | bunzip2 > /usr/local/bin/restic.new
  chmod 0755 /usr/local/bin/restic.new && mv /usr/local/bin/restic.new /usr/local/bin/restic
  echo "restic $(/usr/local/bin/restic version | awk '{print $2}') installed at /usr/local/bin/restic"
fi
export PATH=/usr/local/bin:$PATH
if [ ! -f /etc/nos/restic.env ]; then
  umask 077
  printf 'RESTIC_REPOSITORY=%s/restic\nRESTIC_PASSWORD=%s\n' "$BK" "$(openssl rand -base64 30 | tr -d '/+=')" > /etc/nos/restic.env
  umask 022
  awk -F= '/^RESTIC_PASSWORD/{print $2}' /etc/nos/restic.env > /root/nos-dgx-restic.password; chmod 0600 /root/nos-dgx-restic.password
  echo "restic key generated → /etc/nos/restic.env (copy: /root/nos-dgx-restic.password — put it in a password manager)"
fi
chmod 0600 /etc/nos/restic.env
if mountpoint -q "$BK"; then
  # shellcheck disable=SC1091
  ( . /etc/nos/restic.env; export RESTIC_REPOSITORY RESTIC_PASSWORD
    [ -f "$RESTIC_REPOSITORY/config" ] || { restic init -q && echo "restic repository initialised at $RESTIC_REPOSITORY"; } )
fi
chmod +x "$RT"/backup/*.sh
for u in nos-dgx-backup.service nos-dgx-backup.timer nos-dgx-backup-verify.service nos-dgx-backup-verify.timer; do
  install -m 0644 "$RT/systemd/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
# The scheduled writer is Backrest's plan (below); the systemd backup timer
# stays installed for a manual `systemctl start nos-dgx-backup.service` and
# for a box without Backrest, but DISABLED so the repo has one scheduler.
systemctl disable -q --now nos-dgx-backup.timer 2>/dev/null || true
systemctl enable -q --now nos-dgx-backup-verify.timer
echo "verify timer: $(systemctl list-timers --no-legend 'nos-dgx-backup-verify*' | awk '{print $1" "$2}')"

say "Backrest (restic UI, maintainers only, nginx :8446)"
BR=/opt/nos-dgx/backrest
if [ ! -x "$BR/backrest" ]; then
  install -d "$BR"
  curl -fsSL "https://github.com/garethgeorge/backrest/releases/latest/download/backrest_Linux_arm64.tar.gz" | tar -xz -C "$BR" backrest
  echo "backrest $("$BR/backrest" --version 2>/dev/null | head -1) installed"
fi
install -d -m 0700 /etc/nos/backrest /var/lib/nos-dgx/backrest
# Backrest validates that a configured repo carries the repository's own
# guid (`restic cat config` → id) unless it may auto-initialise; we never let
# it initialise, so read the guid from the repo the timer writes to.
if [ ! -f /etc/nos/backrest/config.json ] || ! grep -q '"guid"' /etc/nos/backrest/config.json || ! grep -q '"nightly"' /etc/nos/backrest/config.json; then
  # shellcheck disable=SC1091
  ( . /etc/nos/restic.env; export RESTIC_REPOSITORY RESTIC_PASSWORD
    GUID="$(restic cat config 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' 2>/dev/null || true)"
    [ -n "$GUID" ] || { echo "backrest: repository guid unreadable (disk mounted? restic init done?) — config not written"; exit 0; }
    python3 - "$SHORT" "$RESTIC_REPOSITORY" "$RESTIC_PASSWORD" "$GUID" "$RT/backup/excludes.txt" <<'PY' > /etc/nos/backrest/config.json
import json, sys
excl = [l.strip() for l in open(sys.argv[5], encoding="utf-8") if l.strip() and not l.startswith("#")]
# The plan mirrors backup/nos-dgx-backup.sh: same paths, same excludes, the
# staging hook first. Backrest is the ONE scheduled writer; the verifier
# (nos-dgx-backup-verify.timer) stays an independent reader.
print(json.dumps({"modno": 1, "version": 4, "instance": sys.argv[1],
  "repos": [{"id": "local", "guid": sys.argv[4], "uri": sys.argv[2], "password": sys.argv[3],
             "env": ["RESTIC_CACHE_DIR=/var/cache/nos-dgx-restic"],
             "prunePolicy": {"schedule": {"cron": "0 5 * * 0", "clock": "CLOCK_LOCAL"}, "maxUnusedPercent": 10},
             "checkPolicy": {"schedule": {"cron": "0 6 * * 0", "clock": "CLOCK_LOCAL"}, "readDataSubsetPercent": 10}}],
  "plans": [{"id": "nightly", "repo": "local",
             "paths": ["/etc/nos", "/var/lib/nos-dgx/backup/stage", "/srv/nos-dgx/keap/data", "/srv/nos-seed.git",
                       "/var/lib/nos-dgx/jupyterhub", "/var/lib/docker/volumes/open-webui/_data",
                       "/var/lib/docker/volumes/iiab_n8n_data/_data", "/home", "/etc/nginx/tls",
                       "/etc/systemd/system/user-.slice.d"],
             "excludes": excl,
             "schedule": {"cron": "0 3 * * *", "clock": "CLOCK_LOCAL"},
             "retention": {"policyTimeBucketed": {"daily": 7, "weekly": 8}},
             "backup_flags": ["--one-file-system", "--exclude-caches"],
             "hooks": [{"conditions": ["CONDITION_SNAPSHOT_START"], "onError": "ON_ERROR_FATAL",
                        "actionCommand": {"command": "/srv/nos-dgx/backup/nos-dgx-backup-stage.sh"}}]}],
  "auth": {"disabled": True}}, indent=1))
PY
  )
  chmod 0600 /etc/nos/backrest/config.json
fi
install -m 0644 "$RT/systemd/backrest.service" /etc/systemd/system/backrest.service
systemctl daemon-reload
systemctl enable -q backrest
systemctl restart backrest
sleep 3
echo "backrest: $(systemctl is-active backrest) — $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:9898/ || echo no-answer) on /"

say "phase C — stack up, knowledge ingest, tables (as admin)"
sudo -u admin -H bash -c '
  set -e
  . /etc/profile.d/nos.sh
  docker compose -f /srv/nos-dgx/compose.yml up -d
  s=none
  for i in $(seq 1 60); do
    s=$(docker inspect -f "{{.State.Health.Status}}" iiab-keap-1 2>/dev/null || echo none)
    [ "$s" = healthy ] && break; sleep 3
  done
  echo "keap health: $s"
  out=$(docker exec iiab-keap-1 node knowledge/ingest.mjs 2>&1 | tail -5 || true)
  echo "$out"
  if echo "$out" | grep -q "\"changed\": *true"; then
    docker restart iiab-keap-1 >/dev/null
    for i in $(seq 1 60); do
      [ "$(docker inspect -f "{{.State.Health.Status}}" iiab-keap-1)" = healthy ] && break; sleep 3
    done
  fi
  /srv/nos-dgx/bin/seed-tables.py
'

say "done"
echo "landing https://$HOST/   keap :8443   chat :8444   notebooks :8445"
echo "tester password: /root/nos-tester.initial-password   ·   next: $RT/README.md phase D"
