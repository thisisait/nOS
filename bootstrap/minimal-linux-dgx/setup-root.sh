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
  python3-yaml sqlite3 rsync curl git \
  docker-ce-rootless-extras uidmap passt fuse-overlayfs >/dev/null

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
  for p in 443 8443 8444 8445; do ufw allow $p/tcp >/dev/null; done
  ufw allow 5353/udp >/dev/null
  ufw status | grep -E '^(443|8443|8444|8445|5353)' | sed 's/^/  /'
fi

say "nginx + PAM"
install -m 0644 "$RT/nginx/pam-nginx" /etc/pam.d/nginx
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
