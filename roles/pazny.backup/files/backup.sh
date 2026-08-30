#!/bin/bash
# ============================================================================
# nOS nightly backup entrypoint
# Rendered from roles/pazny.backup/files/backup.sh by Ansible.
# DO NOT EDIT BY HAND — changes are overwritten on the next playbook run.
# ============================================================================
# shellcheck disable=SC2034,SC2155
set -u -o pipefail

# ---- Configuration (baked in by Ansible template) --------------------------
export AWS_ACCESS_KEY_ID="{{ backup_target_access_key }}"
export AWS_SECRET_ACCESS_KEY="{{ backup_target_secret_key }}"
export AWS_DEFAULT_REGION="{{ backup_target_region }}"

S3_ENDPOINT="{{ backup_target_endpoint }}"
S3_BUCKET="{{ backup_target_bucket }}"

MARIADB_CONTAINER="{{ backup_mariadb_container }}"
MARIADB_USER="{{ backup_mariadb_user }}"
MARIADB_PASSWORD="{{ backup_mariadb_password }}"
DO_MARIADB="{{ 'true' if backup_databases_mariadb else 'false' }}"

PG_CONTAINER="{{ backup_postgresql_container }}"
PG_USER="{{ backup_postgresql_user }}"
PG_PASSWORD="{{ backup_postgresql_password }}"
DO_POSTGRES="{{ 'true' if backup_databases_postgresql else 'false' }}"

AUTHENTIK_URL="{{ backup_authentik_url }}"
AUTHENTIK_TOKEN="{{ backup_authentik_token }}"
DO_AUTHENTIK="{{ 'true' if backup_authentik_blueprints else 'false' }}"

VOLUMES=({% for v in backup_volumes_to_dump %}"{{ v }}" {% endfor %})

# Host-bind service data dirs (gitea/gitlab repos, etc.) — name|path pairs.
# These hold filesystem state that NO logical DB dump can reconstruct (git
# repos, uploads). Tarred whole and restored back to the same host path.
DIR_NAMES=({% for d in backup_dirs_to_dump %}"{{ d.name }}" {% endfor %})
DIR_PATHS=({% for d in backup_dirs_to_dump %}"{{ d.path }}" {% endfor %})

# Wing SQLite store (security findings, audit hash-chain, agent sessions) — a
# host file, NOT a container. Dumped with `sqlite3 .dump` for portability.
WING_DB_PATH="{{ backup_wing_db_path }}"
DO_WING="{{ 'true' if backup_wing_db else 'false' }}"

# KEAP cortex libSQL store (taxonomy, curated descriptions/briefs, data-table
# registry + rows, and the libSQL vector embeddings corpus) — a host file
# under the container's bind-mounted data dir. Backed up with sqlite3 online
# `.backup` (NOT `.dump`): WAL-consistent, and the vector index uses
# libsql_vector_idx() which a plain `.dump`/replay cannot reconstruct on host
# sqlite3. A binary page copy sidesteps that and stays crash-consistent.
KEAP_DB_PATH="{{ backup_keap_db_path }}"
KEAP_CONTAINER="{{ backup_keap_container }}"
KEAP_DB_IN_CONTAINER="{{ backup_keap_db_container_path }}"
DO_KEAP="{{ 'true' if backup_keap_db else 'false' }}"

# Runtime state side-car: ~/.nos/{secrets,state}.yml (encryption keys, tokens,
# upgrades_applied history). Tarred; status/log artifacts excluded.
NOS_STATE_DIR="{{ backup_home_dir }}"
DO_STATE="{{ 'true' if backup_nos_state else 'false' }}"

# OpenTofu Authentik state (ADR-0001 Phase 1): terraform.tfstate (+ .backup
# sibling) and the rendered nos.auto.tfvars.json carry provider client_secrets
# + outpost tokens, gitignored in the repo checkout — disk loss orphans the
# tenant from tofu state unless they ride the nightly encrypted set.
TOFU_STATE_DIR="{{ backup_tofu_state_dir }}"
DO_TOFU_STATE="{{ 'true' if backup_tofu_state else 'false' }}"

# Alpine image for volume/dir tar streaming — MUST match tasks/_restore_volume.yml
# (a tag mismatch is a latent restore-extract drift). Single source: backup_alpine_image.
ALPINE_IMAGE="{{ backup_alpine_image }}"

# `tar -C path .` always emits `./` as its first member, so an archive with
# one member captured nothing. Measured 2026-08-03: six sources under
# nos_data_root produced exactly this, every night, for the life of the bucket.
# Deliberately a MEMBER count, not a byte size — tar pads to a 10240-byte
# minimum, so an empty archive and a three-small-file archive weigh the same
# and a size floor would withdraw real backups.
EMPTY_ARCHIVE_MEMBERS=1

RETAIN_DAILY={{ backup_retention_daily }}
RETAIN_WEEKLY={{ backup_retention_weekly }}
RETAIN_MONTHLY={{ backup_retention_monthly }}

# Client-side encryption: AES-256-CBC/pbkdf2 over every dump before upload.
ENCRYPT="{{ 'true' if backup_encryption_enabled | default(true) else 'false' }}"
ENC_PASSPHRASE="{{ backup_encryption_passphrase }}"
OPENSSL_BIN=""
ENC_SUFFIX=""

STATUS_FILE="{{ backup_status_file }}"
LOG_FILE="{{ backup_log_file }}"
OVERWRITE_SAME_DAY="{{ 'true' if backup_overwrite_same_day else 'false' }}"

# A9 notification (W6.1, 2026-06-10): backup result lands in the Wing inbox —
# failures as HIGH, success as a daily INFO heartbeat. Same HMAC scheme as the
# events pipeline; empty secret (fresh install pre-regen) disables silently.
BONE_NOTIFY_URL="{{ backup_notify_url | default('http://127.0.0.1:8099/api/v1/notifications') }}"
NOTIFY_HMAC_SECRET="{{ wing_events_hmac_secret | default('') }}"
DO_NOTIFY="{{ 'true' if (backup_notify_enabled | default(true)) else 'false' }}"

AWS_OPTS=(--endpoint-url "${S3_ENDPOINT}" --region "${AWS_DEFAULT_REGION}")

# ---- Helpers ---------------------------------------------------------------
log() {
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[${ts}] $*" | tee -a "${LOG_FILE}"
}

die() {
    log "FATAL: $*"
    exit 1
}

now_ms() {
    # GNU-date-free millisecond clock (macOS)
    python3 -c 'import time; print(int(time.time() * 1000))'
}

# Resolve an openssl that supports `enc -pbkdf2`. launchd runs with a
# restricted PATH (no Homebrew); older macOS system LibreSSL lacks -pbkdf2.
# Probe each candidate so the cipher matches tasks/restore.yml exactly.
resolve_openssl() {
    local cand
    for cand in openssl /opt/homebrew/opt/openssl@3/bin/openssl \
                /usr/local/opt/openssl@3/bin/openssl /usr/bin/openssl; do
        command -v "${cand}" >/dev/null 2>&1 || continue
        if printf 'x' | "${cand}" enc -aes-256-cbc -pbkdf2 -iter 1 -salt \
               -pass pass:probe >/dev/null 2>&1; then
            OPENSSL_BIN="${cand}"
            return 0
        fi
    done
    return 1
}

# Fail closed if encryption is requested but unusable — never silently ship
# cleartext PII to object storage. Sets ENC_SUFFIX + exports NOS_BACKUP_PASS.
setup_encryption() {
    if [[ "${ENCRYPT}" != "true" ]]; then
        log "encryption: OFF (backup_encryption_enabled=false) — dumps stored as plaintext"
        return 0
    fi
    [[ -n "${ENC_PASSPHRASE}" ]] || die "encryption enabled but backup_encryption_passphrase is empty"
    resolve_openssl || die "encryption enabled but no -pbkdf2-capable openssl found on PATH"
    export NOS_BACKUP_PASS="${ENC_PASSPHRASE}"
    ENC_SUFFIX=".enc"
    log "encryption: ON (AES-256-CBC/pbkdf2 via ${OPENSSL_BIN})"
}

# Stream filter: AES-256 when enabled, passthrough otherwise. Used as the last
# pipe stage before `aws s3 cp -`. Decryption mirror lives in tasks/restore.yml.
encrypt_stream() {
    if [[ "${ENCRYPT}" == "true" ]]; then
        "${OPENSSL_BIN}" enc -aes-256-cbc -md sha512 -pbkdf2 -iter 100000 \
            -salt -pass env:NOS_BACKUP_PASS
    else
        cat
    fi
}

# Append a source entry to the status JSON. Args: name size_bytes duration_ms success(0/1)
status_append() {
    local name="$1" size="$2" duration="$3" success="$4"
    python3 - <<PY
import json, os, time
path = os.path.expanduser("${STATUS_FILE}")
try:
    with open(path) as f:
        s = json.load(f)
except Exception:
    s = {"last_run": 0, "sources": []}
if not isinstance(s.get("sources"), list):
    s["sources"] = []
s["sources"].append({
    "name": "${name}",
    "size_bytes": int("${size}" or 0),
    "duration_ms": int("${duration}" or 0),
    "success": bool(int("${success}" or 0)),
    "timestamp": int(time.time()),
})
with open(path, "w") as f:
    json.dump(s, f, indent=2)
PY
}

status_reset() {
    python3 - <<PY
import json, os
path = os.path.expanduser("${STATUS_FILE}")
with open(path, "w") as f:
    json.dump({"last_run": 0, "sources": [], "in_progress": True}, f)
PY
}

# POST the run result to Bone /api/v1/notifications (A9, W6.1 2026-06-10).
# Reads the per-source success flags status_append accumulated. Best-effort:
# a Bone outage must never fail the backup itself. Python (stdlib-only) does
# JSON + HMAC + HTTP — no jq/curl deps, and no bash array-length syntax that
# would trip the Jinja brace-hash trap in this template-rendered file.
notify_result() {
    [[ "${DO_NOTIFY}" != "true" ]] && return 0
    [[ -z "${NOTIFY_HMAC_SECRET}" ]] && { log "notify: HMAC secret empty — skipping"; return 0; }
    python3 - <<PY >> "${LOG_FILE}" 2>&1 || log "notify: POST failed (non-fatal)"
import hashlib, hmac, json, os, time, urllib.request
path = os.path.expanduser("${STATUS_FILE}")
try:
    with open(path) as f:
        s = json.load(f)
except Exception:
    s = {"sources": []}
sources = s.get("sources") or []
failed = [x.get("name", "?") for x in sources if not x.get("success")]
total_mb = sum(int(x.get("size_bytes") or 0) for x in sources) / 1048576.0
if failed:
    sev = "high"
    title = "Backup FAILED for %d source(s): %s" % (len(failed), ", ".join(failed[:10]))
elif not sources:
    sev = "high"
    title = "Backup ran but recorded ZERO sources (check gates/log)"
else:
    sev = "info"
    title = "Backup OK - %d sources, %.1f MB" % (len(sources), total_mb)
lines = ["%s: %s (%.1f MB)" % (x.get("name", "?"),
                               "ok" if x.get("success") else "FAIL",
                               int(x.get("size_bytes") or 0) / 1048576.0)
         for x in sources]
payload = {
    "severity": sev,
    "title": title,
    "body": "\n".join(lines) or "(no sources ran)",
    "actor_id": "backup",
    "origin_plugin": "backup",
    # A nightly result REPLACES the previous nightly result. 19 unread rows, oldest 18 days, every one made false by the next night's run.
    # This does NOT mark anything read — nobody read them; it is a
    # third state, and the row stays reachable via include_superseded.
    "supersede_key": "backup-nightly-result",
    "metadata": {"failed": failed, "source_count": len(sources)},
}
raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
ts = str(int(time.time()))
sig = hmac.new("${NOTIFY_HMAC_SECRET}".encode("utf-8"),
               ts.encode("utf-8") + b"." + raw, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "${BONE_NOTIFY_URL}", data=raw, method="POST",
    headers={"Content-Type": "application/json",
             "X-Wing-Timestamp": ts,
             "X-Wing-Signature": sig})
with urllib.request.urlopen(req, timeout=10) as resp:
    print("notify: HTTP %s" % resp.status)
PY
}

status_finalize() {
    python3 - <<PY
import json, os, time
path = os.path.expanduser("${STATUS_FILE}")
try:
    with open(path) as f:
        s = json.load(f)
except Exception:
    s = {"sources": []}
s["last_run"] = int(time.time())
s["in_progress"] = False
with open(path, "w") as f:
    json.dump(s, f, indent=2)
PY
}

# Get object size from S3 (0 if missing).
s3_size() {
    local key="$1"
    aws "${AWS_OPTS[@]}" s3api head-object \
        --bucket "${S3_BUCKET}" \
        --key "${key}" \
        --query ContentLength \
        --output text 2>/dev/null || echo 0
}

# Ensure bucket exists (RustFS: create-bucket is idempotent enough; ignore conflict).
ensure_bucket() {
    aws "${AWS_OPTS[@]}" s3api head-bucket --bucket "${S3_BUCKET}" 2>/dev/null && return 0
    log "Creating bucket s3://${S3_BUCKET}"
    aws "${AWS_OPTS[@]}" s3api create-bucket --bucket "${S3_BUCKET}" \
        >/dev/null 2>&1 || log "create-bucket returned non-zero (already exists?) — continuing"
}

# Skip a source if OVERWRITE_SAME_DAY=false and today already has the prefix.
already_exists_today() {
    local prefix="$1"
    local count
    count=$(aws "${AWS_OPTS[@]}" s3 ls "s3://${S3_BUCKET}/${prefix}" 2>/dev/null | wc -l | tr -d ' ')
    [[ "${count}" -gt 0 ]]
}

# ---- Source steps ----------------------------------------------------------
run_mariadb() {
    [[ "${DO_MARIADB}" != "true" ]] && return 0
    local date_str key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    # Canonical contract (docs/restore-runbook.md §3 + tasks/restore.yml):
    # ONE fixed object per source per day — NO timestamp. backup_overwrite_same_day
    # then genuinely overwrites (a timestamp made "overwrite" silently "add another"
    # AND broke restore, whose source selector can't match a timestamped stem).
    key="${date_str}/mariadb.sql.gz${ENC_SUFFIX}"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/mariadb.sql.gz"; then
        log "mariadb: today's dump already exists, skipping"
        status_append "mariadb" 0 0 1
        return 0
    fi

    log "mariadb: dumping via docker exec ${MARIADB_CONTAINER}"
    start=$(now_ms)
    docker exec -i "${MARIADB_CONTAINER}" \
        mariadb-dump \
          --all-databases \
          --single-transaction \
          --quick \
          --routines \
          --triggers \
          "-u${MARIADB_USER}" \
          "-p${MARIADB_PASSWORD}" \
      | gzip -c \
      | encrypt_stream \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "mariadb: OK (${size} bytes in ${dur}ms) → s3://${S3_BUCKET}/${key}"
        status_append "mariadb" "${size}" "${dur}" 1
    else
        log "mariadb: FAILED (rc=${rc})"
        status_append "mariadb" 0 "${dur}" 0
    fi
}

run_postgres() {
    [[ "${DO_POSTGRES}" != "true" ]] && return 0
    local date_str key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    # Canonical stem is `postgres` (NOT postgresql) — restore.yml selects on it.
    key="${date_str}/postgres.sql.gz${ENC_SUFFIX}"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/postgres.sql.gz"; then
        log "postgresql: today's dump already exists, skipping"
        status_append "postgres" 0 0 1
        return 0
    fi

    log "postgresql: pg_dumpall via docker exec ${PG_CONTAINER}"
    start=$(now_ms)
    docker exec -i -e "PGPASSWORD=${PG_PASSWORD}" "${PG_CONTAINER}" \
        pg_dumpall -U "${PG_USER}" \
      | gzip -c \
      | encrypt_stream \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "postgresql: OK (${size} bytes in ${dur}ms) → s3://${S3_BUCKET}/${key}"
        status_append "postgres" "${size}" "${dur}" 1
    else
        log "postgresql: FAILED (rc=${rc})"
        status_append "postgres" 0 "${dur}" 0
    fi
}

run_volumes() {
    local date_str key start dur rc size vol
    date_str="$(date -u +%Y-%m-%d)"
    # Empty-safe expansion: bash 3.2 (the launchd /bin/bash) raises "unbound
    # variable" on the bare "${arr[@]}" of an EMPTY array under set -u. The
    # ${arr[@]+...} alternation is empty-safe AND avoids the array-length form
    # (its leading brace-hash is a Jinja comment-open, which would stop backup.sh
    # from rendering — the whole script is a Jinja template). Fixed CRIT 2026-06-09.
    for vol in "${VOLUMES[@]+"${VOLUMES[@]}"}"; do
        [[ -z "${vol}" ]] && continue
        key="${date_str}/volume-${vol}.tar.gz${ENC_SUFFIX}"

        if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/volume-${vol}.tar.gz"; then
            log "volume/${vol}: today's dump already exists, skipping"
            status_append "volume-${vol}" 0 0 1
            continue
        fi

        log "volume/${vol}: tar-gz via ${ALPINE_IMAGE}"
        start=$(now_ms)
        docker run --rm -v "${vol}:/data:ro" "${ALPINE_IMAGE}" \
            sh -c 'cd /data && tar -czf - .' \
          | encrypt_stream \
          | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
        rc=$?
        dur=$(( $(now_ms) - start ))

        if [[ "${rc}" -eq 0 ]]; then
            size=$(s3_size "${key}")
            log "volume/${vol}: OK (${size} bytes in ${dur}ms)"
            status_append "volume-${vol}" "${size}" "${dur}" 1
        else
            log "volume/${vol}: FAILED (rc=${rc})"
            status_append "volume-${vol}" 0 "${dur}" 0
        fi
    done
}

run_authentik() {
    [[ "${DO_AUTHENTIK}" != "true" ]] && return 0
    [[ -z "${AUTHENTIK_TOKEN}" ]] && { log "authentik: no token — recording as FAILED"; status_append "authentik-blueprints" 0 0 0; return 0; }

    local date_str key start dur rc size tmp
    date_str="$(date -u +%Y-%m-%d)"
    # RAW .json (NOT .json.gz) — tasks/restore.yml slurps the decrypted file as
    # JSON and POSTs it verbatim; gzipping it broke that path. Encryption still
    # applies (object becomes authentik-blueprints.json.enc).
    key="${date_str}/authentik-blueprints.json${ENC_SUFFIX}"
    tmp="$(mktemp -t nos-authentik.XXXXXX.json)"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/authentik-blueprints.json"; then
        log "authentik: today's dump already exists, skipping"
        status_append "authentik-blueprints" 0 0 1
        rm -f "${tmp}"
        return 0
    fi

    log "authentik: fetching blueprints from ${AUTHENTIK_URL}"
    start=$(now_ms)
    if curl -fsS -H "Authorization: Bearer ${AUTHENTIK_TOKEN}" \
            -H "Accept: application/json" \
            "${AUTHENTIK_URL}/api/v3/managed/blueprints/" > "${tmp}"; then
        encrypt_stream < "${tmp}" \
          | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
        rc=$?
    else
        rc=1
    fi
    dur=$(( $(now_ms) - start ))
    rm -f "${tmp}"

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "authentik: OK (${size} bytes in ${dur}ms)"
        status_append "authentik-blueprints" "${size}" "${dur}" 1
    else
        log "authentik: FAILED (rc=${rc})"
        status_append "authentik-blueprints" 0 "${dur}" 0
    fi
}

run_wing_db() {
    [[ "${DO_WING}" != "true" ]] && return 0
    if ! command -v sqlite3 >/dev/null 2>&1; then
        log "wing-db: sqlite3 not on PATH — skipping (install sqlite3 to back up wing.db)"
        status_append "wing-db" 0 0 0
        return 0
    fi
    if [[ ! -f "${WING_DB_PATH}" ]]; then
        # ABSENT IS A FAILURE, NOT A SKIP. The branch four lines above (sqlite3
        # missing) already records one; this one did not, two lines apart, and
        # that asymmetry is the whole defect: notify_result derives severity
        # from the recorded set, so a source that never calls status_append is
        # neither failed nor absent-of-all and lands in the `info` branch —
        # "Backup OK - N sources". A DISABLED source (DO_WING != true) still
        # returns silently above, which is correct: nobody asked for it.
        log "wing-db: ${WING_DB_PATH} not found — recording as FAILED"
        status_append "wing-db" 0 0 0
        return 0
    fi

    local date_str key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    key="${date_str}/wing-db.sql.gz${ENC_SUFFIX}"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/wing-db.sql.gz"; then
        log "wing-db: today's dump already exists, skipping"
        status_append "wing-db" 0 0 1
        return 0
    fi

    log "wing-db: sqlite3 .dump of ${WING_DB_PATH}"
    start=$(now_ms)
    sqlite3 "${WING_DB_PATH}" .dump \
      | gzip -c \
      | encrypt_stream \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "wing-db: OK (${size} bytes in ${dur}ms)"
        status_append "wing-db" "${size}" "${dur}" 1
    else
        log "wing-db: FAILED (rc=${rc})"
        status_append "wing-db" 0 "${dur}" 0
    fi
}

# The online-backup program, run INSIDE the KEAP container.
#
# Why not `VACUUM INTO`: it rebuilds every object, including the libSQL vector
# index, and stock SQLite has no `libsql_vector_idx()` — it aborts with "SQL
# logic error". `backup()` is the page-level API; it copies pages and never
# parses the schema, so the vector index rides along untouched. Verified on the
# live store: 171 821 pages, 49/49 tables identical to the source.
keap_backup_js() {
    cat <<'KEAPJS'
const { DatabaseSync, backup } = require("node:sqlite");
const fs = require("fs");
const src = process.argv[2];
const dst = process.argv[3];
try { fs.unlinkSync(dst); } catch (e) { /* first run */ }
const db = new DatabaseSync(src, { readOnly: true });
backup(db, dst)
  .then(function (pages) {
    db.close();
    const size = fs.statSync(dst).size;
    if (size === 0) { process.stderr.write("backup produced 0 bytes\n"); process.exit(1); }
    process.stderr.write("pages=" + pages + " bytes=" + size + "\n");
  })
  .catch(function (e) {
    process.stderr.write("backup failed: " + e.message + "\n");
    process.exit(1);
  });
KEAPJS
}

# A READER for the snapshot the step above just wrote — not the writer's own
# claim about it. MEASURED 2026-08-30: `test -s` (below, kept as the cheap
# first question) accepted a TRUNCATED file on 2 of 29 nights, 08-13 and
# 08-30, and both uploaded with `keap-db: OK`. The restore drill found the
# second one seven hours later with `file is not a database (26)`; the first
# was never noticed at all. On both nights node had printed no `pages=` line,
# because the pipeline that runs it ends in a `while`, so its exit code was
# never anyone's.
#
# This opens the artifact and counts the same three tables the drill counts.
# It is the last moment the estate can still fail loudly and keep yesterday's
# good object instead of overwriting the day with a bad one.
keap_verify_js() {
    cat <<'KEAPVERIFYJS'
const { DatabaseSync } = require("node:sqlite");
try {
  const db = new DatabaseSync(process.argv[2], { readOnly: true });
  const n = (t) => db.prepare("select count(*) c from " + t).get().c;
  const counts = [n("taxonomy_nodes_ext"), n("relations"), n("knowledge_objects")];
  db.close();
  if (counts.some((c) => c === 0)) {
    process.stderr.write("snapshot has an EMPTY core table: " + counts.join("/") + "\n");
    process.exit(1);
  }
  process.stderr.write("snapshot verified nodes/relations/objects=" + counts.join("/") + "\n");
} catch (e) {
  process.stderr.write("snapshot is not a readable database: " + e.message + "\n");
  process.exit(1);
}
KEAPVERIFYJS
}

run_keap_db() {
    [[ "${DO_KEAP}" != "true" ]] && return 0

    local date_str key start dur rc size ctmp cjs cvjs vout
    date_str="$(date -u +%Y-%m-%d)"
    key="${date_str}/keap-db.gz${ENC_SUFFIX}"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/keap-db.gz"; then
        log "keap-db: today's backup already exists, skipping"
        status_append "keap-db" 0 0 1
        return 0
    fi

    start=$(now_ms)
    ctmp="/tmp/nos-keap-backup.$$.db"
    cjs="/tmp/nos-keap-backup.$$.js"
    cvjs="/tmp/nos-keap-verify.$$.js"

    # PRIMARY PATH — inside the container.
    #
    # Not a stylistic choice: backup.sh runs from launchd, which has no Full
    # Disk Access for /Volumes, so a host-side read under nos_data_root fails
    # with `authorization denied` — this source reported success=false every
    # night from 2026-07-25 to 2026-07-30 and never produced an object. Docker
    # Desktop holds the grant, so reading via the container's own bind mount
    # removes the whole failure class rather than working around it.
    if docker exec "${KEAP_CONTAINER}" true >/dev/null 2>&1; then
        log "keap-db: online backup inside ${KEAP_CONTAINER} (node:sqlite backup())"
        keap_backup_js \
          | docker exec -i "${KEAP_CONTAINER}" \
              sh -c "cat > ${cjs} && node --no-warnings ${cjs} '${KEAP_DB_IN_CONTAINER}' '${ctmp}'" 2>&1 \
          | while IFS= read -r l; do log "keap-db: ${l}"; done

        # The snapshot either exists and is non-empty, or it does not. That is
        # the only claim worth branching on — the pipeline above reports rc for
        # the `while`, not for node.
        # `test -s` first (cheap), then OPEN it.
        #
        # COMMAND SUBSTITUTION, NOT A PIPE INTO tee — and the first draft of
        # this very fix got it wrong the same way the bug did. A pipeline's rc
        # is its LAST stage: `… | docker exec … | tee` reports tee, which
        # always succeeds, so the verifier's verdict would have been discarded
        # exactly like node's was. `$(…)` ends at `docker exec`, so node's exit
        # code is what the `if` reads, and the output is logged by us.
        if docker exec "${KEAP_CONTAINER}" test -s "${ctmp}" 2>/dev/null \
           && vout="$(keap_verify_js \
                | docker exec -i "${KEAP_CONTAINER}" \
                    sh -c "cat > ${cvjs} && node --no-warnings ${cvjs} '${ctmp}'" 2>&1)"; then
            log "keap-db: ${vout}"
            docker exec "${KEAP_CONTAINER}" cat "${ctmp}" \
              | gzip -c \
              | encrypt_stream \
              | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
            rc=$?
            docker exec "${KEAP_CONTAINER}" rm -f "${ctmp}" "${cjs}" "${cvjs}" >/dev/null 2>&1 || true
            dur=$(( $(now_ms) - start ))
            if [[ "${rc}" -eq 0 ]]; then
                size=$(s3_size "${key}")
                log "keap-db: OK (${size} bytes in ${dur}ms) → s3://${S3_BUCKET}/${key}"
                status_append "keap-db" "${size}" "${dur}" 1
                return 0
            fi
            log "keap-db: upload FAILED (rc=${rc}) — falling back to host sqlite3"
        else
            docker exec "${KEAP_CONTAINER}" rm -f "${ctmp}" "${cjs}" "${cvjs}" >/dev/null 2>&1 || true
            log "keap-db: in-container snapshot missing, empty or NOT A READABLE DATABASE — falling back to host sqlite3"
        fi
    else
        log "keap-db: container ${KEAP_CONTAINER} not available — falling back to host sqlite3"
    fi

    # FALLBACK — host sqlite3. Correct, and it works when the process running
    # this script HAS Full Disk Access (an interactive Terminal.app does). Kept
    # so a stopped container degrades instead of losing the source outright.
    if ! command -v sqlite3 >/dev/null 2>&1; then
        log "keap-db: FAILED — no container and sqlite3 not on PATH"
        status_append "keap-db" 0 "$(( $(now_ms) - start ))" 0
        return 0
    fi
    if [[ ! -f "${KEAP_DB_PATH}" ]]; then
        log "keap-db: FAILED — ${KEAP_DB_PATH} not found"
        status_append "keap-db" 0 "$(( $(now_ms) - start ))" 0
        return 0
    fi

    local tmp err
    log "keap-db: sqlite3 .backup of ${KEAP_DB_PATH}"
    tmp="$(mktemp -t nos-keap-XXXXXX)"
    if ! err="$(sqlite3 "${KEAP_DB_PATH}" ".backup '${tmp}'" 2>&1)"; then
        rm -f "${tmp}"
        dur=$(( $(now_ms) - start ))
        log "keap-db: FAILED (.backup rc!=0): ${err}"
        case "${err}" in
            *"authorization denied"*|*"operation not permitted"*)
                log "keap-db: ^ this is macOS TCC. The launchd context running this script"
                log "keap-db:   has no Full Disk Access for /Volumes. Grant it, or keep the"
                log "keap-db:   KEAP container running so the primary path is used."
                ;;
        esac
        status_append "keap-db" 0 "${dur}" 0
        return 0
    fi
    gzip -c "${tmp}" \
      | encrypt_stream \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    rm -f "${tmp}"
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "keap-db: OK via host fallback (${size} bytes in ${dur}ms)"
        status_append "keap-db" "${size}" "${dur}" 1
    else
        log "keap-db: FAILED (rc=${rc})"
        status_append "keap-db" 0 "${dur}" 0
    fi
}

run_nos_state() {
    [[ "${DO_STATE}" != "true" ]] && return 0
    [[ -d "${NOS_STATE_DIR}" ]] || { log "nos-state: ${NOS_STATE_DIR} missing — recording as FAILED"; status_append "nos-state" 0 0 0; return 0; }

    local date_str key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    key="${date_str}/nos-state.tar.gz${ENC_SUFFIX}"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/nos-state.tar.gz"; then
        log "nos-state: today's dump already exists, skipping"
        status_append "nos-state" 0 0 1
        return 0
    fi

    # ONLY the durable side-car (secrets.yml + state.yml). NOT the whole ~/.nos:
    # it also holds backup.sh, logs, events.jsonl, and the upgrade-engine
    # ~/.nos/backups/ dumps — tarring "." bloated the mirror to ~116 MB (live, 2026-06-09).
    local present=""
    [[ -f "${NOS_STATE_DIR}/secrets.yml" ]] && present="${present} secrets.yml"
    [[ -f "${NOS_STATE_DIR}/state.yml" ]] && present="${present} state.yml"
    if [[ -z "${present}" ]]; then
        log "nos-state: no secrets.yml/state.yml under ${NOS_STATE_DIR} — skipping"
        return 0
    fi

    log "nos-state: tar-gz of ${NOS_STATE_DIR} (${present# })"
    start=$(now_ms)
    # shellcheck disable=SC2086  # intentional word-split of the file list
    tar -czf - -C "${NOS_STATE_DIR}" ${present} \
      | encrypt_stream \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "nos-state: OK (${size} bytes in ${dur}ms)"
        status_append "nos-state" "${size}" "${dur}" 1
    else
        log "nos-state: FAILED (rc=${rc})"
        status_append "nos-state" 0 "${dur}" 0
    fi
}

run_tofu_state() {
    [[ "${DO_TOFU_STATE}" != "true" ]] && return 0
    [[ -d "${TOFU_STATE_DIR}" ]] || { log "tofu-state: ${TOFU_STATE_DIR} missing — recording as FAILED"; status_append "tofu-state" 0 0 0; return 0; }

    local date_str key start dur rc size
    date_str="$(date -u +%Y-%m-%d)"
    key="${date_str}/tofu-state.tar.gz${ENC_SUFFIX}"

    if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/tofu-state.tar.gz"; then
        log "tofu-state: today's dump already exists, skipping"
        status_append "tofu-state" 0 0 1
        return 0
    fi

    # ONLY the secret-bearing artifacts (state + its sibling + rendered tfvars).
    # NOT the whole terraform/authentik/ dir — the HCL is committed and the
    # .terraform/ provider cache is reproducible via `tofu init`. Restore is
    # download+decrypt-to-workdir; re-seating into the git checkout is manual
    # (see tasks/restore.yml + the role defaults comment).
    local present=""
    [[ -f "${TOFU_STATE_DIR}/terraform.tfstate" ]] && present="${present} terraform.tfstate"
    [[ -f "${TOFU_STATE_DIR}/terraform.tfstate.backup" ]] && present="${present} terraform.tfstate.backup"
    [[ -f "${TOFU_STATE_DIR}/nos.auto.tfvars.json" ]] && present="${present} nos.auto.tfvars.json"
    if [[ -z "${present}" ]]; then
        log "tofu-state: no tfstate/tfvars under ${TOFU_STATE_DIR} — skipping (blueprint engine?)"
        return 0
    fi

    log "tofu-state: tar-gz of ${TOFU_STATE_DIR} (${present# })"
    start=$(now_ms)
    # shellcheck disable=SC2086  # intentional word-split of the file list
    tar -czf - -C "${TOFU_STATE_DIR}" ${present} \
      | encrypt_stream \
      | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
    rc=$?
    dur=$(( $(now_ms) - start ))

    if [[ "${rc}" -eq 0 ]]; then
        size=$(s3_size "${key}")
        log "tofu-state: OK (${size} bytes in ${dur}ms)"
        status_append "tofu-state" "${size}" "${dur}" 1
    else
        log "tofu-state: FAILED (rc=${rc})"
        status_append "tofu-state" 0 "${dur}" 0
    fi
}

run_dirs() {
    # ${!arr[@]} index form is empty-safe under set -u in bash 3.2 (verified) —
    # no array-length form here (its brace-hash would break the Jinja render).
    local date_str key start dur rc size i name path src_entries tar_list tar_members
    date_str="$(date -u +%Y-%m-%d)"
    for i in "${!DIR_NAMES[@]}"; do
        name="${DIR_NAMES[$i]}"
        path="${DIR_PATHS[$i]}"
        [[ -z "${name}" || -z "${path}" ]] && continue
        if [[ ! -d "${path}" ]]; then
            # Enabled but absent = FAILED, never a silent skip. An unmounted SSD
            # or a moved nos_data_root would otherwise drop gitea/gitlab out of
            # the nightly set while A9 still reported "Backup OK - N sources".
            log "dir/${name}: ${path} not found — recording as FAILED"
            status_append "dir-${name}" 0 0 0
            continue
        fi
        # ...and READABLE-BUT-EMPTY is the third case, measured 2026-08-03 and
        # the reason six services had no backup at all for the life of the
        # bucket. Every dir under nos_data_root (/Volumes/SSD1TB) tarred to an
        # archive containing exactly one entry, `./` — gitea, gitlab,
        # gitlab-config, authentik, vaultwarden, nodered. dir-n8n ($HOME/n8n)
        # was fine, which is the whole discriminator: the host tar below cannot
        # read the external volume, while `-d` above still passes because the
        # mount point itself is visible.
        #
        # The stream goes STRAIGHT to S3, so by the time tar's rc is known the
        # empty object is already published — a 10 KB artifact that lists like a
        # backup. Check the SOURCE before writing anything, because there is no
        # taking the object back afterwards.
        # Counted from INSIDE, because the host is the one that cannot read
        # these paths. Measured 2026-08-03 on gitea's data dir:
        #     host  `tar -C path .`  ->  1 member,  10 KB, rc=1 "not permitted"
        #     alpine -v path:/data   ->  94 members, 12.4 MB
        # Docker Desktop's VM reaches the external volume through VirtioFS
        # without the host's TCC grant, which is why the SERVICES have worked
        # from these dirs all along while the backup silently did not.
        src_entries=$(docker run --rm -v "${path}:/data:ro" "${ALPINE_IMAGE}" \
                        sh -c 'ls -A /data 2>/dev/null | wc -l' 2>/dev/null | tr -d ' ')
        if [[ -z "${src_entries}" || "${src_entries}" -eq 0 ]]; then
            log "dir/${name}: ${path} reads as EMPTY from a container too — recording as FAILED, uploading nothing"
            status_append "dir-${name}" 0 0 0
            continue
        fi

        key="${date_str}/dir-${name}.tar.gz${ENC_SUFFIX}"

        if [[ "${OVERWRITE_SAME_DAY}" != "true" ]] && already_exists_today "${date_str}/dir-${name}.tar.gz"; then
            log "dir/${name}: today's dump already exists, skipping"
            status_append "dir-${name}" 0 0 1
            continue
        fi

        # tar the dir CONTENTS (-C path .) so restore extracts straight back
        # into the target path without a doubled component.
        log "dir/${name}: tar-gz of ${path}"
        start=$(now_ms)
        # Same sidecar shape as run_volumes(), and deliberately the SAME
        # ALPINE_IMAGE — the restore extractor pins that tag, so a divergence
        # here is a latent restore drift.
        #
        # `-v` puts the member list on stderr so it can be COUNTED. Size is not
        # a usable signal: tar pads every archive to a 10240-byte minimum, so
        # an empty one and one holding three small files weigh the same, and a
        # size floor would withdraw REAL backups. That version was written,
        # caught, and replaced before it shipped.
        #
        # Count only lines the tar itself wrote (`./...`); docker's own stderr
        # would otherwise inflate an empty archive past the threshold.
        tar_list="$(mktemp -t nosbackup)"
        docker run --rm -v "${path}:/data:ro" "${ALPINE_IMAGE}" \
            sh -c 'cd /data && tar -czvf - .' 2>"${tar_list}" \
          | encrypt_stream \
          | aws "${AWS_OPTS[@]}" s3 cp - "s3://${S3_BUCKET}/${key}"
        rc=$?
        tar_members=$(grep -c '^\./' "${tar_list}" 2>/dev/null || echo 0)
        rm -f "${tar_list}"
        dur=$(( $(now_ms) - start ))

        if [[ "${rc}" -eq 0 ]]; then
            size=$(s3_size "${key}")
            # Belt to the pre-flight's braces. A source can list entries and
            # STILL tar to nothing — a per-subdirectory permission failure that
            # tar reports as a delayed error. `./` alone is one member, so an
            # archive at or under that captured no content whatever its size.
            if [[ "${tar_members}" -le "${EMPTY_ARCHIVE_MEMBERS}" ]]; then
                log "dir/${name}: archive holds ${tar_members} member(s) — nothing was captured. Withdrawing the object and recording as FAILED."
                aws "${AWS_OPTS[@]}" s3 rm "s3://${S3_BUCKET}/${key}" >/dev/null 2>&1 || true
                status_append "dir-${name}" 0 "${dur}" 0
            else
                log "dir/${name}: OK (${size} bytes in ${dur}ms)"
                status_append "dir-${name}" "${size}" "${dur}" 1
            fi
        else
            log "dir/${name}: FAILED (rc=${rc})"
            status_append "dir-${name}" 0 "${dur}" 0
        fi
    done
}

# ---- Retention / rotation --------------------------------------------------
# Classify all YYYY-MM-DD/ prefixes as:
#   daily   — last N days kept
#   weekly  — the Sunday of each of the last N weeks kept
#   monthly — the 1st of each of the last N months kept
# Everything else is deleted.
rotate() {
    log "rotate: classifying backups (d=${RETAIN_DAILY}, w=${RETAIN_WEEKLY}, m=${RETAIN_MONTHLY})"

    local dates
    dates=$(aws "${AWS_OPTS[@]}" s3 ls "s3://${S3_BUCKET}/" 2>/dev/null \
            | awk '{print $2}' | sed 's|/$||' \
            | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -u)

    if [[ -z "${dates}" ]]; then
        log "rotate: no dated prefixes found, nothing to do"
        return 0
    fi

    local to_delete
    to_delete=$(python3 - <<PY
import datetime as dt
dates = """${dates}""".strip().splitlines()
parsed = sorted({dt.date.fromisoformat(d) for d in dates if d})
today = dt.date.today()
keep = set()

# Daily: last N days
for d in parsed:
    if (today - d).days < ${RETAIN_DAILY}:
        keep.add(d)

# Weekly: Sunday of each of last N weeks (ISO: Monday=1..Sunday=7 → use weekday()==6)
weekly_kept = []
for d in sorted(parsed, reverse=True):
    if d.weekday() == 6 and (today - d).days < ${RETAIN_WEEKLY} * 7 + 7:
        weekly_kept.append(d)
        if len(weekly_kept) >= ${RETAIN_WEEKLY}:
            break
keep.update(weekly_kept)

# Monthly: 1st of each of last N months
monthly_kept = []
for d in sorted(parsed, reverse=True):
    if d.day == 1:
        monthly_kept.append(d)
        if len(monthly_kept) >= ${RETAIN_MONTHLY}:
            break
keep.update(monthly_kept)

delete = [d.isoformat() for d in parsed if d not in keep]
print("\n".join(delete))
PY
)

    if [[ -z "${to_delete}" ]]; then
        log "rotate: nothing to delete"
        return 0
    fi

    local d
    while IFS= read -r d; do
        [[ -z "${d}" ]] && continue
        log "rotate: deleting s3://${S3_BUCKET}/${d}/"
        aws "${AWS_OPTS[@]}" s3 rm "s3://${S3_BUCKET}/${d}/" --recursive \
            >> "${LOG_FILE}" 2>&1 || log "rotate: warning, delete of ${d}/ returned non-zero"
    done <<< "${to_delete}"
}

# ---- Main ------------------------------------------------------------------
main() {
    mkdir -p "$(dirname "${LOG_FILE}")"
    touch "${LOG_FILE}"

    if [[ "${1:-}" == "--rotate-only" ]]; then
        ensure_bucket
        rotate
        exit 0
    fi

    log "==== nOS backup start ===="
    status_reset
    setup_encryption
    ensure_bucket

    run_mariadb
    run_postgres
    run_volumes
    run_dirs
    run_wing_db
    run_keap_db
    run_nos_state
    run_tofu_state
    run_authentik
    rotate

    status_finalize
    notify_result

    # Exit non-zero if ANY source failed.
    #
    # Every run_* deliberately returns 0 so one broken source cannot abort the
    # others — but that made the script as a whole indistinguishable from a
    # clean run. tasks/pre-wipe-backup.yml checks only this rc, so on
    # 2026-07-25..30 it printed "✓ copy #1 refreshed" over a bucket holding no
    # KEAP data at all, every night, while `keap-db` reported success=false in
    # the very status file this function reads. A pre-wipe gate that cannot go
    # red is not a gate.
    local failed
    failed="$(python3 - <<PY
import json, os
try:
    with open(os.path.expanduser("${STATUS_FILE}")) as f:
        s = json.load(f)
except Exception:
    print("")
else:
    print(",".join(x.get("name", "?") for x in s.get("sources", []) if not x.get("success")))
PY
)"

    if [[ -n "${failed}" ]]; then
        log "==== nOS backup done WITH FAILURES: ${failed} ===="
        return 1
    fi
    log "==== nOS backup done ===="
    return 0
}

main "$@"
