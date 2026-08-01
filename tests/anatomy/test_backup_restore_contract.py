"""Anatomy CI gate — backup ↔ restore object-naming contract.

The 2026-06-09 audit found restore had NEVER worked for DBs: backup.sh had
drifted to timestamped `mariadb-all.<ts>.sql.gz` keys while tasks/restore.yml
(and docs/restore-runbook.md §3) selected on the clean stem `mariadb` — the
source never matched, so every DB dump was silently dropped from the restore
plan. This gate pins the contract so the two halves can never diverge again:

  * every source `backup.sh` writes has a handler in `restore.yml`
    (or is an explicit workdir-only source — see WORKDIR_ONLY_SOURCES)
  * no timestamp creeps back into a backup object key (the original bug)
  * the OpenTofu Authentik state artifacts (tfstate + rendered tfvars) are in
    the nightly encrypted set (ADR-0001 Phase 1 P1 custody item)
  * the alpine image is identical on the backup (tar) and restore (extract) side
  * restore decrypt resolves a -pbkdf2-capable openssl (not a bare `openssl`)
  * the dead, drifted, cleartext dump_*.yml files stay deleted
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKUP_SH = REPO / "roles" / "pazny.backup" / "files" / "backup.sh"
BACKUP_DEFAULTS = REPO / "roles" / "pazny.backup" / "defaults" / "main.yml"
RESTORE_YML = REPO / "tasks" / "restore.yml"
RESTORE_VOLUME = REPO / "tasks" / "_restore_volume.yml"

# Extension groups stripped to reduce an object key to its canonical source stem
# (mirror of the restore.yml normalization).
_EXT_RE = re.compile(r"\.(sql\.gz|tar\.gz|json\.gz|json|gz)$")

# Sources whose restore contract is DELIBERATELY download+decrypt-to-workdir
# only (the generic stage of restore.yml covers every planned object): the
# replay target is the repo git checkout, and auto-extracting over a live
# working tree is not safe to automate. Re-seating is a manual operator step.
# Anything added here MUST keep test_generic_restore_stage_covers_all_sources
# true — that gate is what makes "workdir-only" real custody, not a dropped
# source.
WORKDIR_ONLY_SOURCES = {"tofu-state"}


def _backup_key_lines() -> list[str]:
    text = BACKUP_SH.read_text()
    return [ln.strip() for ln in text.splitlines() if re.match(r'\s*key="', ln)]


def _backup_sources() -> set[str]:
    """The canonical source families backup.sh emits (volume-*/dir-* collapsed)."""
    sources: set[str] = set()
    for ln in _backup_key_lines():
        m = re.search(r'key="\$\{date_str\}/(.+?)\$\{ENC_SUFFIX\}"', ln)
        assert m, f"unparseable backup key line: {ln}"
        body = m.group(1)
        # Collapse the shell-variable families to their static prefix.
        if body.startswith("volume-"):
            sources.add("volume-*")
            continue
        if body.startswith("dir-"):
            sources.add("dir-*")
            continue
        stem = _EXT_RE.sub("", body)
        sources.add(stem)
    return sources


def _restore_handlers() -> set[str]:
    """Source identifiers tasks/restore.yml (+ includes) dispatch on."""
    text = RESTORE_YML.read_text()
    handlers: set[str] = set()
    for m in re.finditer(r"selectattr\(\s*'source'\s*,\s*'equalto'\s*,\s*'([^']+)'", text):
        handlers.add(m.group(1))
    if re.search(r"selectattr\(\s*'source'\s*,\s*'match'\s*,\s*'\^volume-'", text):
        handlers.add("volume-*")
    if re.search(r"selectattr\(\s*'source'\s*,\s*'match'\s*,\s*'\^dir-'", text):
        handlers.add("dir-*")
    return handlers


def test_every_backup_source_has_a_restore_handler():
    backup = _backup_sources()
    restore = _restore_handlers()
    # Sanity: the contract must cover the load-bearing sources.
    assert {"mariadb", "postgres", "authentik-blueprints", "volume-*"} <= backup, backup
    missing = backup - restore - WORKDIR_ONLY_SOURCES
    assert not missing, (
        f"backup.sh emits sources with NO restore handler: {sorted(missing)}.\n"
        f"backup={sorted(backup)}\nrestore={sorted(restore)}\n"
        "This is exactly the drift that left restore broken — add a handler in "
        "tasks/restore.yml (or, ONLY for repo-checkout artifacts, register the "
        "source in WORKDIR_ONLY_SOURCES with a rationale)."
    )


def test_generic_restore_stage_covers_all_sources():
    """The WORKDIR_ONLY_SOURCES carve-out is honest only while restore.yml's
    generic stage operates on the WHOLE restore_plan: list → download → decrypt
    happens for every object at the date prefix, replay-handler or not. Pin the
    plan-wide loops so a future 'download only handled sources' refactor can't
    silently turn workdir-only custody into a dropped source."""
    text = RESTORE_YML.read_text()
    # Download loop iterates the full plan…
    assert re.search(
        r's3 cp s3://\{\{ restore_s3_bucket \}\}.*?loop: "\{\{ restore_plan \}\}"', text, re.S
    ), "restore.yml download stage no longer loops over the FULL restore_plan"
    # …and decrypt covers every encrypted object in it.
    assert re.search(
        r"loop: \"\{\{ restore_plan \| selectattr\('encrypted'\) \| list \}\}\"", text
    ), "restore.yml decrypt stage no longer covers all encrypted plan objects"


def test_no_timestamp_in_backup_object_keys():
    """The original bug: `${ts}` in the key made the stem unmatchable by restore."""
    offenders = [ln for ln in _backup_key_lines() if "${ts}" in ln or re.search(r"\.\$\{ts", ln)]
    assert not offenders, (
        "backup object keys must be ONE fixed name per source per day (no timestamp) "
        f"so restore can match the stem. Offending lines:\n" + "\n".join(offenders)
    )


def test_canonical_db_stems_present():
    """Stems MUST be mariadb / postgres (not -all / postgresql) — restore selects these."""
    bodies = "\n".join(_backup_key_lines())
    assert "mariadb.sql.gz" in bodies, "expected canonical mariadb.sql.gz key"
    assert "postgres.sql.gz" in bodies, "expected canonical postgres.sql.gz key (NOT postgresql-all)"
    assert "mariadb-all" not in bodies and "postgresql-all" not in bodies, (
        "drifted -all stems are back — restore selects on the clean stem"
    )


def _alpine_image_backup() -> str:
    m = re.search(r'^backup_alpine_image:\s*"([^"]+)"', BACKUP_DEFAULTS.read_text(), re.M)
    assert m, "backup_alpine_image not declared in pazny.backup defaults"
    return m.group(1)


def test_alpine_image_parity():
    """A tar/extract image-tag skew is a silent restore-extract drift."""
    backup_img = _alpine_image_backup()
    restore_text = RESTORE_YML.read_text()
    m = re.search(r'restore_alpine_image:\s*"([^"]+)"', restore_text)
    assert m, "restore_alpine_image not set in tasks/restore.yml"
    assert m.group(1) == backup_img, (
        f"alpine image mismatch: backup={backup_img!r} restore={m.group(1)!r}"
    )
    # The volume extractor falls back to the same literal.
    vol_text = RESTORE_VOLUME.read_text()
    for fallback in re.findall(r"restore_alpine_image \| default\('([^']+)'\)", vol_text):
        assert fallback == backup_img, (
            f"_restore_volume.yml alpine fallback {fallback!r} != backup {backup_img!r}"
        )


def test_restore_decrypt_resolves_pbkdf2_openssl():
    """Bare `openssl` may be old LibreSSL without -pbkdf2 — must probe like backup.sh."""
    text = RESTORE_YML.read_text()
    assert "resolve_openssl" in text, (
        "restore decrypt must mirror backup.sh resolve_openssl() (a bare `openssl` "
        "fails on macOS LibreSSL without -pbkdf2)"
    )


def test_nos_state_backs_up_only_the_side_car():
    """nos-state must tar ONLY secrets.yml/state.yml — NOT the whole ~/.nos, which
    also holds the upgrade-engine ~/.nos/backups/ dumps (tarring '.' bloated the
    off-site mirror to ~116 MB nightly, caught on the 2026-06-09 live run)."""
    text = BACKUP_SH.read_text()
    m = re.search(r"run_nos_state\(\)\s*\{.*?\n\}", text, re.S)
    assert m, "run_nos_state() not found in backup.sh"
    body = m.group(0)
    assert "secrets.yml" in body and "state.yml" in body, (
        "nos-state must name secrets.yml + state.yml explicitly (not tar the whole dir)"
    )


def test_authentik_backup_tracks_authentik_port():
    """backup_authentik_url must follow the published host port (authentik_port,
    default 9003) — a hardcoded :9000 hits PHP-FPM (→404, blueprint backup fails)."""
    text = BACKUP_DEFAULTS.read_text()
    m = re.search(r'^backup_authentik_url:\s*"([^"]+)"', text, re.M)
    assert m, "backup_authentik_url not declared"
    url = m.group(1)
    assert "authentik_port" in url, f"backup_authentik_url must track authentik_port, got: {url}"
    assert not url.rstrip("/").endswith(":9000"), "hardcoded :9000 is PHP-FPM, not authentik"


@pytest.mark.parametrize("dead", ["dump_databases.yml", "dump_volumes.yml", "dump_authentik_blueprints.yml"])
def test_dead_drifted_dump_tasks_removed(dead):
    """These were unwired, shipped CLEARTEXT, and emitted the competing drifted contract."""
    path = REPO / "roles" / "pazny.backup" / "tasks" / dead
    assert not path.exists(), f"{dead} resurrected — it's dead code with a wrong, unencrypted contract"


def test_backup_sh_renders_as_jinja():
    """backup.sh is rendered by ansible.builtin.template — it MUST be valid Jinja2.
    The 2026-06-09 follow-up bug: a `${#arr[@]}` bash array-length guard contains
    `{#`, which Jinja reads as a comment-open → 'Missing end of comment tag' → the
    template never renders → the whole backup task fails. Parse it here so any
    Jinja-syntax trap (`{#`, orphan `{%`/`{{`) is caught offline, not on a live run.
    """
    jinja2 = pytest.importorskip("jinja2")
    try:
        jinja2.Environment().parse(BACKUP_SH.read_text())
    except jinja2.TemplateSyntaxError as e:  # pragma: no cover - failure path
        pytest.fail(f"backup.sh is not valid Jinja2: {e.message} (line {e.lineno}). "
                    f"A `${{#arr[@]}}` bash length expansion is the usual culprit ({{# = Jinja comment).")


def test_array_loops_are_empty_safe():
    """bash 3.2 (the launchd /bin/bash) raises 'unbound variable' on the BARE
    "${arr[@]}" value-form expansion of an EMPTY array under `set -u` (it aborted
    the whole backup the moment backup_volumes_to_dump went to []). Loops must use
    the empty-safe alternation `${arr[@]+"${arr[@]}"}` or the index form
    `${!arr[@]}`. NOTE: a `${#arr[@]} -eq 0` guard is NOT an allowed fix — `{#`
    breaks the Jinja render of backup.sh (see test_backup_sh_renders_as_jinja).
    """
    text = BACKUP_SH.read_text()
    # Bare value form: `for V in "${ARR[@]}"` with `[@]}` directly (the unsafe one).
    # The empty-safe form `"${ARR[@]+...}"` has `[@]+` and is not matched here.
    offenders = re.findall(r'for\s+\w+\s+in\s+"\$\{\w+\[@\]\}"', text)
    assert not offenders, (
        "bare value-form array loops crash bash-3.2 under set -u on an empty array; "
        f'use ${{arr[@]+"${{arr[@]}}"}} or ${{!arr[@]}}: {offenders}'
    )


def test_status_names_match_canonical_stems():
    """status_append names feed backup-status.json / alert $labels.source — keep them
    equal to the canonical restore stems (postgres / volume-<v> / dir-<n> / authentik-blueprints)."""
    text = BACKUP_SH.read_text()
    bad = re.findall(r'status_append "(postgresql|volume[:/][^"]*|dir[:/][^"]*|authentik)"', text)
    assert not bad, f"status_append uses non-canonical (drifted) source names: {bad}"


def test_backup_dirs_have_restore_targets():
    """S4 (2026-06-10): every backup_dirs_to_dump name must have a matching
    restore_dir_targets entry — a dir that backs up but can't restore is the
    silent half-contract the 2026-06-09 overhaul was built to kill."""
    import re

    cfg = (REPO / "default.config.yml").read_text()
    block = cfg[cfg.index("backup_dirs_to_dump:"):]
    block = block[: re.search(r"\nbackup_databases_mariadb", block).start()]
    backup_names = set(re.findall(r'\{ name: "([a-z0-9-]+)"', block))
    assert backup_names, "backup_dirs_to_dump parse came up empty"

    restore = (REPO / "tasks/restore.yml").read_text()
    tgt = restore[restore.index("restore_dir_targets:"):]
    tgt = tgt[: tgt.index("- name:")]
    restore_names = set(re.findall(r"^\s{6}([a-z0-9-]+):", tgt, re.M))

    missing = sorted(backup_names - restore_names)
    assert not missing, (
        f"backup_dirs_to_dump entries with NO restore_dir_targets mapping: "
        f"{missing} — extend tasks/restore.yml"
    )


# ── OpenTofu Authentik state custody (ADR-0001 Phase 1 P1) ────────────────────
# terraform/authentik/{terraform.tfstate,terraform.tfstate.backup,
# nos.auto.tfvars.json} are secret-bearing (provider client_secrets, outpost
# tokens), gitignored, and lived in NO custody path — disk loss orphaned the
# tenant from tofu state. These gates pin them into the nightly encrypted set
# (copy #2 rides along automatically: restic mirrors the RustFS bucket dir).

TOFU_STATE_ARTIFACTS = (
    "terraform.tfstate",
    "terraform.tfstate.backup",
    "nos.auto.tfvars.json",
)


def test_tofu_state_source_in_backup_script():
    """backup.sh must emit the tofu-state source: a dedicated run_tofu_state()
    that tars EXACTLY the secret-bearing artifacts (not the whole terraform
    dir — HCL is committed, .terraform/ is reproducible) and is wired into
    main() so it actually fires nightly."""
    text = BACKUP_SH.read_text()
    m = re.search(r"run_tofu_state\(\)\s*\{.*?\n\}", text, re.S)
    assert m, "run_tofu_state() not found in backup.sh — tofu state fell out of the backup set"
    body = m.group(0)
    for artifact in TOFU_STATE_ARTIFACTS:
        # Boundary-anchored: plain 'terraform.tfstate' is a substring of
        # 'terraform.tfstate.backup', so a naive `in` check stays green even
        # if the current-state line is deleted while the .backup sibling stays.
        assert re.search(rf"{re.escape(artifact)}(?![.\w-])", body), (
            f"run_tofu_state() no longer names {artifact!r} — the secret-bearing "
            "tofu artifact set must stay explicit (present-only, skip-if-missing)"
        )
    assert "tofu-state.tar.gz${ENC_SUFFIX}" in body, (
        "tofu-state object key drifted — restore matches the clean stem 'tofu-state'"
    )
    # Wired into main(), not just defined.
    main_m = re.search(r"\nmain\(\)\s*\{.*?\n\}", text, re.S)
    assert main_m and "run_tofu_state" in main_m.group(0), (
        "run_tofu_state is defined but NOT called from main() — dead code, no custody"
    )


def test_tofu_state_backup_defaults_declared():
    """The toggle + dir var must exist in the role defaults and point at the
    repo's terraform/authentik dir. NOTE the default.config.yml shadow trap:
    backup_* vars there WIN over role defaults — if someone later shadows
    backup_tofu_state_dir, it must still target terraform/authentik."""
    text = BACKUP_DEFAULTS.read_text()
    assert re.search(r"^backup_tofu_state:", text, re.M), (
        "backup_tofu_state toggle missing from pazny.backup defaults"
    )
    m = re.search(r'^backup_tofu_state_dir:\s*"([^"]+)"', text, re.M)
    assert m, "backup_tofu_state_dir not declared in pazny.backup defaults"
    assert m.group(1).endswith("/terraform/authentik"), (
        f"backup_tofu_state_dir must point at terraform/authentik, got: {m.group(1)}"
    )
    # Shadow guard (version-pin trap, see memory): a default.config.yml override
    # with a DIFFERENT dir would silently back up nothing (path-missing skip).
    cfg = (REPO / "default.config.yml").read_text()
    shadow = re.search(r'^backup_tofu_state_dir:\s*"([^"]+)"', cfg, re.M)
    if shadow:
        assert shadow.group(1).endswith("/terraform/authentik"), (
            "default.config.yml shadows backup_tofu_state_dir with a non-"
            f"terraform/authentik path ({shadow.group(1)}) — role default is dead, "
            "backup.sh would skip-on-missing forever"
        )
