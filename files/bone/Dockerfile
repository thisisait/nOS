# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Bone — local FastAPI organ for nOS (state / migrations / dispatcher).
#
# This image bundles ansible-core because most Bone endpoints
# (/api/run-tag, /api/migrations/*, /api/upgrades/*, /api/patches/*,
# /api/coexistence/*) shell out to `ansible-playbook` as a subprocess.
#
# The image is for Docker-orchestration tags only. Tasks that mutate the
# host machine (Homebrew, launchctl, /opt/homebrew/etc/nginx, ~/Library)
# can't reach out of the container and will fail when invoked from inside.
# Run `ansible-playbook -K` from the host CLI for those tags. A future
# host-runner sidecar will close this gap; for now the limit is by design.
#
# Required mounts at runtime (compose handles this):
#   /state                       → ~/.nos                          rw
#   /playbook                    → ~/nOS                           rw  (ansible writes back to state/, etc.)
#   /wing-db                     → wing.db parent dir              rw
#   /service-registry.json       → ~/projects/default/.../...json  ro
#   /var/run/docker.sock         → host docker socket              rw  (compose-up from inside)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# System packages:
#   tini    — proper PID 1 (signals + zombie reaping)
#   curl    — HEALTHCHECK probe + ad-hoc debugging
#   git     — pulled by some ansible roles via galaxy
#   openssh-client — ansible's connection plugin needs ssh on PATH even for
#                    local connections (it probes for the binary at startup)
#   ca-certificates — TLS for httpx + galaxy + git
#   docker-cli — `docker compose` invoked from ansible roles. The socket is
#                bind-mounted from the host; we just need the client.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tini curl git openssh-client ca-certificates gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && chmod a+r /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
         https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
 && apt-get purge -y --auto-remove gnupg \
 && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. uid/gid 10001 is unlikely to collide with host users.
RUN groupadd --system --gid 10001 bone \
 && useradd  --system --uid 10001 --gid bone --home /app --shell /bin/bash bone

WORKDIR /app

# Install Python deps + ansible-core in one cached layer.
# ansible-core (no community.* collections by default) — roles install what
# they need via `ansible-galaxy collection install` at runtime, mirroring the
# host pattern.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir 'ansible-core>=2.18,<2.20'

# Copy every Python module in files/bone/. Keep this list explicit — adding a
# new module to the role means adding it here too.
COPY main.py        /app/main.py
COPY events.py      /app/events.py
COPY state.py       /app/state.py
COPY migrations.py  /app/migrations.py
COPY upgrades.py    /app/upgrades.py
COPY coexistence.py /app/coexistence.py
COPY patches.py     /app/patches.py

# Default mount points. Bone expects these to be bind-mounted from the host
# (or from named volumes when run under compose). Listed here so a `docker
# image inspect` reveals the contract at a glance.
ENV NOS_STATE_PATH=/state/state.yml \
    PLAYBOOK_DIR=/playbook \
    NOS_MIGRATIONS_DIR=/playbook/migrations \
    NOS_UPGRADES_DIR=/playbook/upgrades \
    NOS_PATCHES_DIR=/playbook/patches \
    WING_DB_PATH=/wing-db/wing.db \
    SERVICE_REGISTRY_PATH=/service-registry.json \
    ANSIBLE_HOST_KEY_CHECKING=False \
    ANSIBLE_RETRY_FILES_ENABLED=False \
    ANSIBLE_LOCAL_TEMP=/tmp/ansible/local \
    ANSIBLE_REMOTE_TMP=/tmp/ansible/remote \
    HOME=/app

# Fix ownership now that all source is in place. /app is the bone user's home;
# ansible writes facts cache + tmp paths under HOME by default unless the env
# vars above redirect them. /tmp/ansible is created by ansible itself on first
# run.
RUN chown -R bone:bone /app

USER bone

EXPOSE 8099

# /api/health is unauthenticated and cheap. 30s start period gives uvicorn
# time to bind on slow hosts (e.g. ARM emulation under qemu).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8099/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8099"]
