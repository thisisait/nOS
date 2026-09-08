#!/usr/bin/env bash
# =============================================================================
# nos-dgx setup — the ROOT half. Idempotent; re-run freely.
#
#   sudo bash <nOS checkout>/bootstrap/minimal-linux-dgx/setup-root.sh
#
# What it does, in order: packages · groups + users · developer substrate
# (linger, slice ceilings, rootless-docker prerequisites) · /srv layout (rendered
# recipe, KEAP clone + image, runtime checkout, seed repo, KB build) · secrets in
# /etc/nos · mkcert TLS · mDNS · firewall · nginx + PAM · native Ollama ·
# per-user shelves · JupyterHub · backup disk + restic + verifier · Backrest ·
# NemoClaw (agent sandbox on Ollama) · mcpo + the nOS Assistant knowledge ·
# compose up + KEAP ingest + tables.
# Services are RELOADED/RESTARTED only when their unit or config changed.
# =============================================================================
set -euo pipefail

STAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # this recipe dir (bootstrap/minimal-linux-dgx in the nOS checkout)
RT=/srv/nos-dgx
SRC=/srv/nos
SEED=/srv/nos-seed.git
# The operator account owns /srv (uid 1000 on this box — KEAP's container runs
# as uid 1000 and writes keap/data, so keep the operator at uid 1000 or chown
# keap/data to 1000 yourself). The nOS checkout is the one this script lives in.
OPERATOR="${NOS_OPERATOR:-admin}"
DEV_CHECKOUT="$(cd "$STAGE/../.." && pwd)"
DEV_BRANCH="$(git -C "$DEV_CHECKOUT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo feat/minimal-linux-dgx)"
KEAP_REPO=https://github.com/thisisait/nos-keap.git
KEAP_PIN=v1.44.0            # mirrors default.config.yml keap_version
# The name is read LIVE: rename the box (DGX dashboard → reboot), re-run this
# script, and every hostname-bearing file is re-rendered from the templates,
# the leaf certificate re-issued (same CA — nobody re-imports anything), nginx
# and the compose stack restarted with the new origin.
SHORT="$(hostname -s)"
HOST="$SHORT.local"
MAINTAINERS="$OPERATOR"
# Per-user ceilings (systemd user-<uid>.slice): a developer's build, Lab or
# rootless containers all live in that slice, so one cap covers them all and
# none of them can starve Ollama/KEAP. 121 GB box: 32G / 10 cores per user.
NOS_USER_MEM_MAX="${NOS_USER_MEM_MAX:-32G}"
NOS_USER_CPU_QUOTA="${NOS_USER_CPU_QUOTA:-1000%}"
# Every member of nos-users gets a shelf — the group is the roster, not this file.
USERS_ALL=""

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
# put <src> <dst> [mode] — install, and return 0 only when the content CHANGED,
# so a service is bounced only when there is a reason to (a recipe re-run must
# not unload the models or drop every user's notebook connection).
put() { local m="${3:-0644}"; if [ -f "$2" ] && cmp -s "$1" "$2"; then chmod "$m" "$2"; return 1; fi; install -m "$m" "$1" "$2"; return 0; }
CHANGED_UNITS=0
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx libnginx-mod-http-auth-pam mkcert libnss3-tools \
  python3-yaml python3-markdown sqlite3 rsync curl git \
  docker-ce-rootless-extras uidmap passt fuse-overlayfs restic binutils >/dev/null

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
# Humans only (uid >= 1000): service accounts such as nos-mcpo sit in nos-users
# for the READ token but get no shelf, no linger, no home.
# (`if`, not `[ ] &&`: under set -e a command substitution whose LAST member
# fails the test ends the whole run — measured, the last member was nos-mcpo.)
USERS_ALL="$(for u in $(getent group nos-users | cut -d: -f4 | tr , " "); do if [ "$(id -u "$u")" -ge 1000 ]; then printf '%s ' "$u"; fi; done)"
for u in $(getent group nos-users | cut -d: -f4 | tr , " "); do
  if [ "$(id -u "$u")" -lt 1000 ]; then loginctl disable-linger "$u" 2>/dev/null || true; fi
done

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
  sudo -u "$OPERATOR" git clone -q --branch "$KEAP_PIN" --depth 1 "$KEAP_REPO" "$RT/keap/src"
  echo "cloned nos-keap $KEAP_PIN"
fi
# Root reads a repo the operator owns: git's dubious-ownership guard lets that
# through only when SUDO_UID is the owner, i.e. when the OPERATOR ran sudo. Any
# other maintainer running the recipe needs the system-level exception (same
# rule as $SRC and $SEED below).
git config --system --get-all safe.directory 2>/dev/null | grep -qx "$RT/keap/src" || git config --system --add safe.directory "$RT/keap/src"
KEAP_SHA="$(git -C "$RT/keap/src" rev-parse --short HEAD)"
KEAP_TAG="nos/keap:${KEAP_PIN#v}-$KEAP_SHA"
if ! docker image inspect "$KEAP_TAG" >/dev/null 2>&1; then
  echo "building $KEAP_TAG (native $(uname -m), several minutes)…"
  docker build -q -t "$KEAP_TAG" "$RT/keap/src" >/dev/null
fi
sed -i "s|image: nos/keap:.*|image: $KEAP_TAG|" "$RT/compose.yml"
chown -R "$OPERATOR":nos-maintainers "$RT"
chmod -R g+rwX,o+rX "$RT"
find "$RT" -type d -exec chmod g+s {} +
chmod +x "$RT"/bin/* "$RT"/setup-root.sh

if [ ! -d "$SRC/.git" ]; then
  install -d -o "$OPERATOR" -g nos-maintainers -m 2775 "$SRC"
  sudo -u "$OPERATOR" git clone -q -b "$DEV_BRANCH" "$DEV_CHECKOUT" "$SRC"
  sudo -u "$OPERATOR" git -C "$SRC" remote set-url origin https://github.com/thisisait/nOS.git
  echo "cloned $DEV_CHECKOUT@$DEV_BRANCH -> $SRC (origin re-pointed to GitHub)"
else
  echo "$SRC present ($(git -C "$SRC" rev-parse --abbrev-ref HEAD))"
fi
chown -R "$OPERATOR":nos-maintainers "$SRC"
chmod -R g+rwX,o+rX "$SRC"
ln -sfn "$SRC/tools/nos" /usr/local/bin/nos
install -m 0755 -o root -g root "$RT/bin/dgx-status.sh" /usr/local/bin/dgx-status
# Both /srv repos are owned by admin; git's dubious-ownership guard refuses
# them for every other user. System-level (/etc/gitconfig) is the one place
# that reaches all of them without touching a home directory.
for d in "$SRC" "$SEED"; do
  git config --system --get-all safe.directory 2>/dev/null | grep -qx "$d" || git config --system --add safe.directory "$d"
done

if [ ! -d "$SEED" ]; then
  install -d -o "$OPERATOR" -g nos-maintainers -m 2775 "$SEED"
  sudo -u "$OPERATOR" git init -q --bare --shared=group "$SEED"
  echo "created bare seed repo $SEED"
fi
chown -R "$OPERATOR":nos-maintainers "$SEED"
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
# The identity outpost: human-door calls made AS the caller (uid → login → tier).
KEAP_IDENTITY_URL=http+unix://%2Frun%2Fnos-dgx%2Fkeap-identity.sock
EOF
# The outpost alone holds the proxy secret (its own user, its own env file).
id nos-identity >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d /nonexistent nos-identity
install -m 0640 -o root -g nos-identity /dev/null /etc/nos/keap-proxy.env
printf 'KEAP_PROXY_SHARED_SECRET=%s\nNOS_HOST=%s\n' "$KEAP_PROXY_SHARED_SECRET" "$HOST" > /etc/nos/keap-proxy.env
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
PHYS="$(ip -o link show | awk -F': ' '{print $2}' | cut -d@ -f1 | grep -vE '^(lo|docker|br-|veth|virbr|tailscale|tun|wg)' | paste -sd, -)"
if ! grep -qE "^allow-interfaces=$PHYS\$" /etc/avahi/avahi-daemon.conf; then
  sed -i '/^allow-interfaces=/d' /etc/avahi/avahi-daemon.conf
  sed -i "s/^\[server\]\$/[server]\nallow-interfaces=$PHYS/" /etc/avahi/avahi-daemon.conf
  systemctl restart avahi-daemon
fi
echo "mDNS on: $PHYS"

say "firewall: the web ports + mDNS (only if ufw is enabled)"
if ufw status | grep -q '^Status: active'; then
  for p in 443 8443 8444 8445 8446 8447; do ufw allow $p/tcp >/dev/null; done
  ufw allow 5353/udp >/dev/null
  ufw status | grep -E '^(443|8443|8444|8445|8446|8447|5353)' | sed 's/^/  /'
fi

say "nginx + PAM"
install -m 0644 "$RT/nginx/pam-nginx" /etc/pam.d/nginx
install -m 0644 "$RT/nginx/pam-nginx-admin" /etc/pam.d/nginx-admin
usermod -aG shadow www-data
put "$RT/nginx/nos-dgx-tls.conf" /etc/nginx/nos-dgx-tls.conf || true
put "$RT/nginx/nos-dgx.conf" /etc/nginx/sites-available/nos-dgx.conf || true
ln -sfn /etc/nginx/sites-available/nos-dgx.conf /etc/nginx/sites-enabled/nos-dgx.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable -q nginx
if systemctl is-active -q nginx; then systemctl reload nginx; else systemctl start nginx; fi
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
OLLAMA_BOUNCE=0
put "$RT/systemd/ollama-override.conf" /etc/systemd/system/ollama.service.d/nos-dgx.conf && OLLAMA_BOUNCE=1
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
if [ "$OLLAMA_BOUNCE" = 1 ] || ! systemctl is-active -q ollama; then systemctl restart ollama; sleep 2; fi
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
JH_BOUNCE=0
put "$RT/jupyterhub/jupyterhub_config.py" /etc/nos/jupyterhub_config.py && JH_BOUNCE=1
put "$RT/systemd/jupyterhub.service" /etc/systemd/system/jupyterhub.service && JH_BOUNCE=1
systemctl daemon-reload
systemctl enable -q jupyterhub
if [ "$JH_BOUNCE" = 1 ] || ! systemctl is-active -q jupyterhub; then systemctl restart jupyterhub; sleep 4; fi
echo "jupyterhub: $(systemctl is-active jupyterhub) — $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8010/hub/login || echo no-answer) on /hub/login"
echo "torch cuda: $("$JH/venv/bin/python" -c 'import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")' 2>&1 | tail -1)"

say "NemoClaw (OpenClaw in an OpenShell sandbox, on the native Ollama, owned by $OPERATOR)"
# NVIDIA's reference stack for a sandboxed always-on agent: the OpenShell
# gateway (a host binary, user-level systemd unit of the operator, :8080) runs
# the agent in a policy-bound container on the ROOT docker daemon; inference is
# whatever endpoint onboarding registered. NO managed vLLM here — a second 35B
# model preallocating 90 % of the unified memory would starve Ollama and the
# Lab kernels. The agent talks to the Ollama that already serves Chat, through
# the loopback door above (NemoClaw admits an unauthenticated endpoint only on
# 127.0.0.1) and gets it rewritten to host.openshell.internal:11434 inside the
# sandbox. Install is idempotent on the sandbox registry; NOS_NEMOCLAW=0 skips.
NC=/opt/nos-dgx/nemoclaw
NEMOCLAW_PIN="${NEMOCLAW_PIN:-v0.0.109}"          # what `lkg` resolved to on 2026-09-08
NEMOCLAW_MODEL="${NEMOCLAW_MODEL:-qwen3.5:35b}"    # the model Chat already runs
NEMOCLAW_SANDBOX="${NEMOCLAW_SANDBOX:-nos-agent}"
if [ "${NOS_NEMOCLAW:-1}" = 1 ]; then
  LB_BOUNCE=0
  put "$RT/systemd/nos-ollama-loopback.socket" /etc/systemd/system/nos-ollama-loopback.socket && LB_BOUNCE=1
  put "$RT/systemd/nos-ollama-loopback.service" /etc/systemd/system/nos-ollama-loopback.service && LB_BOUNCE=1
  systemctl daemon-reload
  systemctl enable -q nos-ollama-loopback.socket
  if [ "$LB_BOUNCE" = 1 ]; then systemctl restart nos-ollama-loopback.socket; fi
  systemctl is-active -q nos-ollama-loopback.socket || systemctl start nos-ollama-loopback.socket
  echo "ollama loopback: $(systemctl is-active nos-ollama-loopback.socket) — $(curl -fsS -m 5 http://127.0.0.1:8000/api/version 2>/dev/null || echo 'no answer on 127.0.0.1:8000')"
  install -d -m 0755 "$NC"
  # The bootstrap installer, fetched ONCE and kept root-owned; the ref it
  # installs is pinned by NEMOCLAW_INSTALL_TAG below, never the moving `lkg`.
  [ -f "$NC/nemoclaw.sh" ] || curl -fsSL https://www.nvidia.com/nemoclaw.sh -o "$NC/nemoclaw.sh"
  install -m 0755 -o root -g root "$RT/bin/nemoclaw-run" "$NC/run"
  sed "s/__OPERATOR__/$OPERATOR/g" "$RT/bin/nemoclaw" > /usr/local/bin/nemoclaw.new
  install -m 0755 -o root -g root /usr/local/bin/nemoclaw.new /usr/local/bin/nemoclaw; rm -f /usr/local/bin/nemoclaw.new
  cat > /etc/sudoers.d/nos-nemoclaw <<SUDO
# nos-dgx: every maintainer drives the operator's NemoClaw (root-owned runner)
%nos-maintainers ALL=($OPERATOR) NOPASSWD: $NC/run
SUDO
  chmod 0440 /etc/sudoers.d/nos-nemoclaw; visudo -cf /etc/sudoers.d/nos-nemoclaw >/dev/null
  OP_HOME="$(getent passwd "$OPERATOR" | cut -d: -f6)"; OP_UID="$(id -u "$OPERATOR")"
  # The provider settings: ONE file, read by the installer below and by every
  # later `nemoclaw` call through /opt/nos-dgx/nemoclaw/run (no secrets).
  # Why port 8000 and not 11434: NemoClaw fronts a no-auth loopback endpoint
  # with its own token proxy and refuses to start it while the same port
  # answers on any other interface (#6014) — 172.17.0.1:11434 does, on purpose,
  # for Chat / n8n / mcpo. The eligible ports are fixed (8000/11434/11435), the
  # documented NEMOCLAW_OLLAMA_PROXY_SKIP_BIND_PROBE override never reaches the
  # proxy from the CLI (its subprocess env is allow-listed), so the door is
  # the one eligible port nobody else serves: 8000, JupyterHub's hub proxy
  # having moved to 8010.
  cat > /etc/nos/nemoclaw.env <<ENV
# nos-dgx: NemoClaw provider settings — written by setup-root.sh, read by /opt/nos-dgx/nemoclaw/run
NEMOCLAW_AGENT=openclaw
NEMOCLAW_SANDBOX_NAME=$NEMOCLAW_SANDBOX
NEMOCLAW_PROVIDER=custom
NEMOCLAW_ENDPOINT_URL=http://127.0.0.1:8000/v1
NEMOCLAW_MODEL=$NEMOCLAW_MODEL
NEMOCLAW_COMPATIBLE_AUTH_MODE=none
NEMOCLAW_POLICY_MODE=suggested
ENV
  chmod 0644 /etc/nos/nemoclaw.env
  # Onboarding validates the endpoint with a real chat completion, so the model
  # must be present before it starts.
  if ! curl -fsS -m 5 http://127.0.0.1:8000/api/tags | grep -q "\"name\":\"$NEMOCLAW_MODEL\""; then
    echo "pulling $NEMOCLAW_MODEL…"; OLLAMA_HOST=http://127.0.0.1:8000 ollama pull "$NEMOCLAW_MODEL"
  fi
  if ! grep -q "\"$NEMOCLAW_SANDBOX\"" "$OP_HOME/.nemoclaw/sandboxes.json" 2>/dev/null; then
    echo "installing NemoClaw $NEMOCLAW_PIN as $OPERATOR (Node, OpenShell, CLI, sandbox $NEMOCLAW_SANDBOX — several minutes)…"
    # stdin closed: the installer must never wait on a prompt inside the recipe.
    # --fresh: this branch runs only while NO sandbox is registered, so a stale
    # session from a failed attempt is never resumed by guess.
    # shellcheck disable=SC2046
    sudo -u "$OPERATOR" -H env \
      PATH="$NODE_DIR/bin:$OP_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
      XDG_RUNTIME_DIR="/run/user/$OP_UID" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$OP_UID/bus" \
      NEMOCLAW_INSTALL_REF= NEMOCLAW_INSTALL_TAG="$NEMOCLAW_PIN" \
      NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 NEMOCLAW_NO_EXPRESS=1 \
      $(grep -v '^#' /etc/nos/nemoclaw.env | xargs) \
      bash "$NC/nemoclaw.sh" --non-interactive --yes-i-accept-third-party-software --fresh < /dev/null 2>&1 \
      | tee "$NC/install.log" | tail -n 30 | sed 's/^/  /' \
      || echo "NemoClaw install did not finish — full log: $NC/install.log (re-run the recipe, or as a maintainer: nemoclaw onboard --resume --non-interactive)"
  else
    echo "sandbox $NEMOCLAW_SANDBOX is registered for $OPERATOR"
  fi
  echo "nemoclaw: $(sudo -u "$OPERATOR" -H "$NC/run" "$NEMOCLAW_SANDBOX" status 2>&1 | grep -v '^\s*$' | head -n 6 | paste -sd' · ' -)"
  echo "dashboard (from your laptop): ssh -L 18789:127.0.0.1:18789 <you>@$HOST · then: nemoclaw $NEMOCLAW_SANDBOX dashboard-url"
fi

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
# 0711: last.json (no secrets) is readable by every user via dgx-status; stage/ stays 0700.
install -d -m 0711 /var/lib/nos-dgx/backup
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
# Root executes these (units, the Backrest hook): a ROOT-OWNED copy under /opt,
# never the maintainer-writable tree in /srv.
install -d -m 0755 /opt/nos-dgx/backup
for f in "$RT"/backup/*; do install -m 0755 -o root -g root "$f" "/opt/nos-dgx/backup/$(basename "$f")"; done
for u in nos-dgx-backup.service nos-dgx-backup.timer nos-dgx-backup-verify.service nos-dgx-backup-verify.timer; do
  put "$RT/systemd/$u" "/etc/systemd/system/$u" || true
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
# Regenerate when the file is missing, pre-dates the guid or the plan, or still
# points the hook at the maintainer-writable /srv copy (now /opt, root-owned).
if [ ! -f /etc/nos/backrest/config.json ] || ! grep -q '"guid"' /etc/nos/backrest/config.json \
   || ! grep -q '"nightly"' /etc/nos/backrest/config.json || grep -q '/srv/nos-dgx/backup/' /etc/nos/backrest/config.json; then
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
                        "actionCommand": {"command": "/opt/nos-dgx/backup/nos-dgx-backup-stage.sh"}}]}],
  "auth": {"disabled": True}}, indent=1))
PY
  )
  chmod 0600 /etc/nos/backrest/config.json
  BR_CONFIG_WRITTEN=1
fi
BR_BOUNCE=0
put "$RT/systemd/backrest.service" /etc/systemd/system/backrest.service && BR_BOUNCE=1
[ "${BR_CONFIG_WRITTEN:-0}" = 1 ] && BR_BOUNCE=1
systemctl daemon-reload
systemctl enable -q backrest
if [ "$BR_BOUNCE" = 1 ] || ! systemctl is-active -q backrest; then systemctl restart backrest; sleep 3; fi
echo "backrest: $(systemctl is-active backrest) — $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:9898/ || echo no-answer) on /"

say "Open WebUI: the DataTables tool server (mcpo) + the nOS Assistant knowledge"
MC_BOUNCE=0
# mcpo wraps the stdio MCP server as an OpenAPI tool server. Its own user, in
# nos-users only → the wrapper sources the READ token, so chat can read the
# tables and cannot write them. Bound to docker0 → reachable from the Open
# WebUI container as http://host.docker.internal:8500, never from the LAN.
# The chat tool speaks through the identity outpost as nos-mcpo: tier 2
# (nos-managers) sees the shared roadmap and every tier-2/3 table, never a
# user's private one — the agent-door leak (keap-agent-door-honours-sharing)
# no longer reaches Chat. A membership change restarts the service.
groupadd -f nos-managers
id nos-mcpo >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d /nonexistent -G nos-users,nos-managers nos-mcpo
MC_GROUPS_BEFORE="$(id -nG nos-mcpo)"
usermod -aG nos-users,nos-managers nos-mcpo
[ "$MC_GROUPS_BEFORE" = "$(id -nG nos-mcpo)" ] || MC_BOUNCE=1
MC=/opt/nos-dgx/mcpo
# mcpo 0.0.20 imports `streamablehttp_client`, which the mcp 2.x SDK renamed;
# pin the SDK below 2 (mcpo's own floor is >= 1.17) and repair an existing venv.
if [ ! -x "$MC/venv/bin/mcpo" ]; then
  python3 -m venv "$MC/venv" && "$MC/venv/bin/pip" install -q --upgrade pip && "$MC/venv/bin/pip" install -q mcpo "mcp>=1.17,<2"
elif ! "$MC/venv/bin/python" -c 'from mcp.client.streamable_http import streamablehttp_client' 2>/dev/null; then
  "$MC/venv/bin/pip" install -q "mcp>=1.17,<2"
fi
chown -R root:root "$MC"; chmod -R o+rX,go-w "$MC"
if [ ! -f /etc/nos/mcpo.env ]; then
  umask 077; printf 'MCPO_API_KEY=%s\n' "$(openssl rand -hex 24)" > /etc/nos/mcpo.env; umask 022
fi
chown root:nos-mcpo /etc/nos/mcpo.env; chmod 0640 /etc/nos/mcpo.env
put "$RT/systemd/mcpo-nos-tables.service" /etc/systemd/system/mcpo-nos-tables.service && MC_BOUNCE=1
systemctl daemon-reload; systemctl enable -q mcpo-nos-tables
if [ "$MC_BOUNCE" = 1 ] || ! systemctl is-active -q mcpo-nos-tables; then systemctl restart mcpo-nos-tables; sleep 3; fi
echo "mcpo: $(systemctl is-active mcpo-nos-tables) — $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://172.17.0.1:8500/openapi.json || echo no-answer) on /openapi.json"
# The assistant's knowledge needs an ADMIN API key from Open WebUI (Settings →
# Account → API keys). Until it is in /etc/nos/openwebui.env the sync just says so.
if [ ! -f /etc/nos/openwebui.env ]; then
  install -m 0640 -o root -g nos-maintainers /dev/null /etc/nos/openwebui.env
  printf '# Admin API key from Open WebUI (Settings → Account → API keys); then: setup-root.sh or bin/webui-kb-sync.py\nOPENWEBUI_API_KEY=\n# OPENWEBUI_BASE_MODEL=qwen3.5:35b   (default: the first Ollama model Open WebUI lists)\n' > /etc/nos/openwebui.env
fi
if grep -qE '^OPENWEBUI_API_KEY=.+' /etc/nos/openwebui.env; then
  NOS_SHORT="$SHORT" NOS_DGX_RT="$RT" NOS_SRC="$SRC" python3 "$RT/bin/webui-kb-sync.py" 2>&1 | tail -n 4 | sed 's/^/  /'
else
  echo "webui knowledge: no OPENWEBUI_API_KEY in /etc/nos/openwebui.env — the nOS Assistant is not synced yet"
fi

say "identity outpost: the shell login is the KEAP login (unix socket, SO_PEERCRED)"
install -d -m 0755 /opt/nos-dgx/identity
ID_BOUNCE=0
put "$RT/systemd/nos-keap-identity.service" /etc/systemd/system/nos-keap-identity.service && ID_BOUNCE=1
put "$RT/identity/keap-identity.py" /opt/nos-dgx/identity/keap-identity.py 0755 && ID_BOUNCE=1   # compare BEFORE install
systemctl daemon-reload; systemctl enable -q nos-keap-identity
if [ "$ID_BOUNCE" = 1 ] || ! systemctl is-active -q nos-keap-identity; then systemctl restart nos-keap-identity; sleep 2; fi
echo "identity outpost: $(systemctl is-active nos-keap-identity) — $(curl -s -o /dev/null -w '%{http_code}' -m 5 --unix-socket /run/nos-dgx/keap-identity.sock http://keap/api/tables || echo no-answer) on /api/tables as root"

say "phase C — stack up, knowledge ingest, tables (as admin)"
# cd /: the operator inherits the caller's cwd, and when another maintainer ran
# sudo that is a home the operator cannot stat — compose then fails validation.
sudo -u "$OPERATOR" -H bash -c '
  set -e
  cd /
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
echo "landing https://$HOST/   keap :8443   chat :8444   notebooks :8445   agent: nemoclaw $NEMOCLAW_SANDBOX status"
echo "tester password: /root/nos-tester.initial-password   ·   next: $RT/README.md phase D"
