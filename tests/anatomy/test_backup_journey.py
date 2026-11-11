"""One journey through the backup role on the push path: the restic repo check, the
source set backup.sh renders, each dump and archive it ships, the guards that keep a
good dump alive, the pre-wipe verdict a removal waits on, and how restore.yml reads a set.
The sections that run a real ansible-playbook live in test_backup_playbook_journey.py
(nightly lane, as their source files were).

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_restic_init_check_is_cat_config, test_backup_run_now_follows_its_sources,
  test_backup_skips_disabled_dirs, test_backup_sources_are_the_installed_set,
  test_backup_covers_espocrm, test_backup_covers_invoice_incoming,
  test_the_backup_pipeline_fails_loudly, test_a_snapshot_is_opened_before_it_is_uploaded,
  test_backup_refuses_to_publish_an_empty_archive, test_a_sqlite_dump_survives_a_denied_host,
  test_a_good_dump_survives_the_next_backup, test_a_removal_without_a_survivor_stops,
  test_restore_dry_run_gathers_its_own_evidence, test_restore_templating.
Every assert of those files survives here with the same inputs and expectations.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

SCRIPT = REPO / "roles/pazny.backup/files/backup.sh"
BACKUP_DEFAULTS = REPO / "roles" / "pazny.backup" / "defaults" / "main.yml"
BACKUP_YML = REPO / "tasks/backup.yml"
PREWIPE = REPO / "tasks/pre-wipe-backup.yml"
RESTORE = REPO / "tasks/restore.yml"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """A top-level backup.sh function, from `name() {` to the first `\\n}\\n`."""
    body = _script()
    start = body.index(f"{name}() {{")
    end = body.index("\n}\n", start)
    return body[start:end]


# ── test_restic_init_check_is_cat_config ────────────────────────────────────
# S7, p=54800: `restic snapshots` took ~31s as the "is the repo initialized"
# check; `cat config` answers it. A wrong password is also rc!=0, so init must
# not read it as "uninitialized" and re-init over an existing repo.

def _backup_tasks():
    return yaml.safe_load(BACKUP_YML.read_text(encoding="utf-8"))


def _named(name: str) -> dict:
    return next(t for t in _backup_tasks() if isinstance(t, dict) and t.get("name") == name)


def _cmd(task: dict) -> str:
    return str(task.get("ansible.builtin.command") or task.get("command") or "")


def _when(task: dict) -> str:
    w = task.get("when")
    if w is None:
        return ""
    if isinstance(w, list):
        return " && ".join(str(x) for x in w)
    return str(w)


def test_restic_init_check_is_cat_config():
    cmd = _cmd(_named("[Backup] Check if restic repo is initialized"))
    assert "cat config" in cmd, f"init check must cat config, not list snapshots: {cmd}"
    assert "snapshots" not in cmd


def test_restic_init_does_not_treat_wrong_password_as_uninitialized():
    fail = _named("[Backup] Fail if restic password does not match an existing repo")
    assert "wrong password" in _when(fail)
    init = _named("[Backup] Initialize restic repo")
    when = _when(init)
    assert "restic_repo_check.rc" in when
    assert "wrong password" in when and "not in" in when, (
        f"init on rc!=0 alone would run after a wrong-password cat config: {when}"
    )


# ── test_backup_run_now_follows_its_sources ─────────────────────────────────
# 2026-10-30 blank: run-now fired inside pazny.backup before pazny.thalamus had
# created medulla_data_dir, and medulla is empty_ok, so the first backup left
# its settings out silently. Parsed from main.yml.

RUNNERS = ("ansible.builtin.command", "ansible.builtin.shell", "command", "shell")


def _role_ref(task):
    for key in ("ansible.builtin.import_role", "ansible.builtin.include_role", "import_role", "include_role"):
        if isinstance(task.get(key), dict):
            return task[key]
    return None


def _source_flags():
    return {d["flag"] for d in ni.default_config()["backup_dirs_to_dump"] if d.get("flag")}


def _runs_backup_script(tasks):
    for t in tasks or []:
        if any(_runs_backup_script(t.get(k)) for k in ("block", "rescue", "always")):
            return True
        for mod in RUNNERS:
            v = t.get(mod)
            if "backup_script_path" in str(v.get("cmd", "") if isinstance(v, dict) else v or ""):
                return True
    return False


def test_run_now_comes_after_every_role_a_backup_dir_depends_on():
    tasks = yaml.safe_load((REPO / "main.yml").read_text())[0]["tasks"]
    run_now = [i for i, t in enumerate(tasks)
               if (_role_ref(t) or {}).get("name") == "pazny.backup"
               and (_role_ref(t) or {}).get("tasks_from") == "run-now"]
    assert len(run_now) == 1, "main.yml must call pazny.backup tasks_from run-now exactly once"
    # The role's own main.yml must not run backup.sh at its import position.
    role_main = yaml.safe_load((REPO / "roles/pazny.backup/tasks/main.yml").read_text())
    assert not _runs_backup_script(role_main), "a task in pazny.backup main.yml still runs backup.sh"

    flags = _source_flags()
    # ponytail: top-level tasks only; a source role buried in an included file is not seen.
    later = [t.get("name") for t in tasks[run_now[0] + 1:]
             if _role_ref(t) and any(f in yaml.safe_dump(t.get("when", "")) for f in flags)]
    assert not later, f"roles creating backup sources run after backup_run_now: {later}"


# ── test_backup_skips_disabled_dirs ─────────────────────────────────────────
# 2026-10-04: install_mikopbx false, no data dir, and dir-mikopbx FAILED nightly
# (only gitlab had a hard-coded skip; test_backup_skips_disabled_gitlab is
# folded in here). Each backup_dirs_to_dump entry names its own install flag.

ALWAYS = {"tenants"}   # data of no single service


def _entries():
    return ni.default_config()["backup_dirs_to_dump"], ni.default_config()


def test_every_service_dir_names_an_existing_flag():
    entries, cfg = _entries()
    bad = [e["name"] for e in entries if e["name"] not in ALWAYS
           and (not e.get("flag") or e["flag"] not in cfg)]
    assert not bad, f"backup dirs without an existing install flag: {bad}"


# ── test_backup_sources_are_the_installed_set ───────────────────────────────
# Core-profile client host 2026-10-16: red-status named mariadb, dir-gitea,
# dir-n8n... as failed sources, none installed. backup.sh renders, and the
# reader reports, only what the host installed; an off dir holding data is a
# hold, and its failure stays red (ruling 2026-10-16).

NOT_ON_CORE = {"mariadb", "gitea", "vaultwarden", "n8n", "dolibarr-documents", "dolibarr-custom",
               "bookstack", "freescout", "paperclip", "openwebui"}
TOGGLES = ("backup_databases_mariadb", "backup_databases_postgresql",
           "backup_authentik_blueprints", "backup_keap_db", "backup_wing_db")


def _core():
    flags = ni.install_flags(ni.profile_layers(REPO / "profiles/core.yml"))
    cfg = ni.default_config()
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    # Each toggle resolved the way the play resolves it: its own Jinja against the flags.
    toggles = {t: env.from_string(str(cfg[t])).render(**flags) == "True" if "{{" in str(cfg[t])
               else bool(cfg[t]) for t in TOGGLES}
    return flags, cfg, env, toggles


def _red_status():
    spec = importlib.util.spec_from_file_location("red_status", REPO / "tools/red-status.py")
    red = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(red)
    return red


def test_the_rendered_source_set_is_the_core_install_set():
    flags, cfg, env, toggles = _core()
    env.globals["lookup"] = lambda kind, name, default=False: flags.get(name, default)
    text = env.from_string(_script()).render(
        backup_dirs_to_dump=cfg["backup_dirs_to_dump"], backup_encryption_enabled=False,
        backup_overwrite_same_day=True, backup_retention_daily=7, backup_retention_weekly=4,
        backup_retention_monthly=6, **toggles)
    defs = text.rsplit('\nmain "$@"', 1)[0]
    out = subprocess.run(["bash", "-c", defs + '\necho "$DO_MARIADB $DO_POSTGRES $DO_AUTHENTIK $DO_KEAP"'
                          '\nfor i in "${!DIR_NAMES[@]}"; do echo "${DIR_NAMES[$i]} ${DIR_ENABLED[$i]}"; done'],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    dbs, dirs = out[0].split(), dict(d.split() for d in out[1:] if d)
    assert dbs == ["false", "true", "true", "true"], f"mariadb/postgres/authentik/keap = {dbs}"
    # Ruling 2026-10-16: an off dir is rendered but marked off (backed up only when it holds data).
    on = {n for n, e in dirs.items() if e == "true"}
    assert not on & NOT_ON_CORE, f"core marks dirs of services it never installed as on: {on & NOT_ON_CORE}"
    assert "authentik" in on, dirs


def test_the_reader_does_not_report_a_source_this_host_never_installed(tmp_path, monkeypatch):
    red = _red_status()
    flags, *_ = _core()
    flags = {**flags, "install_backup": True, "install_rustfs": True}   # copy #1's status file
    status = tmp_path / "backup-status.json"
    names = ["mariadb", "postgres", "dir-gitea", "dir-dolibarr-documents", "dir-authentik",
             "keap-db", "nos-state"]
    status.write_text(json.dumps({"sources": [{"name": n, "success": False, "timestamp": 1} for n in names]}))
    monkeypatch.setattr(red, "BACKUP_STATUS", status)
    monkeypatch.setattr(red, "_install_flags", lambda: flags)
    assert red.backups()["failed"] == ["postgres", "dir-authentik", "keap-db", "nos-state"], (
        "an installed source that failed stays red; a never-installed one is no finding")


def test_an_off_source_backed_up_is_a_hold_and_its_failure_stays_red(tmp_path, monkeypatch):
    """Ruling 2026-10-16: an off service's dir with data is still backed up
    (`off: true` in its row). The reader names it as an intentional hold, and
    a FAILED off row is red: it was the last copy the ruling keeps."""
    red = _red_status()
    flags, *_ = _core()
    flags = {**flags, "install_backup": True, "install_rustfs": True}   # copy #1 path
    status = tmp_path / "backup-status.json"
    status.write_text(json.dumps({"sources": [
        {"name": "dir-vaultwarden", "success": True, "off": True, "timestamp": 1},
        {"name": "dir-n8n", "success": False, "off": True, "timestamp": 1},
        {"name": "dir-gitea", "success": False, "timestamp": 1}]}))
    monkeypatch.setattr(red, "BACKUP_STATUS", status)
    monkeypatch.setattr(red, "_install_flags", lambda: flags)
    bk = red.backups()
    assert bk["failed"] == ["dir-n8n"], bk
    assert bk["backed_up_while_off"] == ["dir-vaultwarden"], bk
    assert any("backed up while off: dir-vaultwarden" in h for h in red.hold_lines({"backups": bk}))


# ── test_backup_covers_espocrm ──────────────────────────────────────────────
# EspoCRM runs its own embedded MariaDB in the apps stack, which the shared
# mariadb-dump --all-databases never sees; a named-volume tar of a mysql datadir
# is not a dump. Copy #1 must dump espocrm-db by name.

ESPO_MANIFEST = REPO / "apps" / "espocrm.yml.draft"


def test_espocrm_dump_is_a_named_backup_source():
    src = _script()
    assert "run_espocrm()" in src
    main = src.split("\nmain()", 1)[1]
    assert "run_espocrm" in main
    assert "espocrm.sql.gz" in src
    defaults = BACKUP_DEFAULTS.read_text(encoding="utf-8")
    block = defaults.split("backup_espocrm_volumes:", 1)[1].split("backup_dirs_to_dump:", 1)[0]
    assert "apps_espocrm_data" in block
    assert "apps_espocrm_db" not in block
    assert "container_name: espocrm-db" in ESPO_MANIFEST.read_text(encoding="utf-8")


# ── test_backup_covers_invoice_incoming ─────────────────────────────────────
# Week-1 P3: KEAP's dump is keap.db only; invoice PDFs live under
# {nos_data_root}/tenants/.../incoming/ and ride only copy #1's whole-dir tar.
# An `--exclude` of incoming/, or a set that is only the KEAP dump, drops them.

def _code(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )


def _exclude_hits(text: str) -> list[str]:
    return [
        ln.strip()
        for ln in _code(text).splitlines()
        if re.search(r"--exclude", ln) and "incoming" in ln
    ]


def test_run_dirs_tars_the_whole_tree_and_does_not_exclude_incoming():
    """If incoming/ sits under a dumped nos_data_root path, it must ride along."""
    fn = _fn("run_dirs")
    assert "tar -czvf - ." in fn, (
        "run_dirs no longer tars the directory whole — incoming/ PDFs would "
        "need a dedicated source, which this estate does not add"
    )
    assert not _exclude_hits(fn), (
        "run_dirs excludes incoming/ — invoice PDFs would drop out of copy #1 "
        f"while keap-db still looks green: {_exclude_hits(fn)}"
    )
    assert not _exclude_hits(_script()), (
        "backup.sh gained an --exclude of incoming/"
    )


def test_keap_dump_is_the_db_not_the_pdfs():
    """Week-1 P3: the cortex dump cannot stand in for filesystem originals."""
    fn = _code(_fn("run_keap_db"))
    assert "incoming" not in fn, (
        "run_keap_db started touching incoming/ — PDFs are not in keap.db; "
        "keep the dump as the sqlite store"
    )
    assert "keap-db.gz" in fn and "KEAP_DB" in fn
    assert ".pdf" not in fn.lower()


def test_nightly_set_is_not_only_the_keap_db():
    """Filesystem originals need a dir tar; keap-db.gz is not that tar."""
    main = _fn("main")
    assert "run_dirs" in main and "run_keap_db" in main
    # The default layers only (ruling 2026-11-11, backup-dna): vars_files outrank the role default,
    # whose stale copy of backup_dirs_to_dump was dead and is gone.
    for src, text in (("the default layers", ni.default_config_text()),):
        start = text.index("backup_dirs_to_dump:")
        names = re.findall(r'\{ name: "([a-z0-9-]+)"', text[start:])
        assert names, f"{src} backup_dirs_to_dump parsed empty"
        assert "tenants" in names, (
            f"{src} dump list has no tenants entry — invoice incoming/ PDFs "
            f"are not under gitea/n8n: {names}"
        )
        assert not _exclude_hits(text), (
            f"{src} excludes incoming/ from the dump list: {_exclude_hits(text)}"
        )


# ── test_the_backup_pipeline_fails_loudly ───────────────────────────────────
# Every `rc=$?` in backup.sh follows `dump | gzip | encrypt | aws s3 cp`; without
# `set -o pipefail` it reads aws's status and a failed dump uploads empty, logged
# OK. 2026-09-01 a review called pipefail missing while the snapshot gate's own
# docstring said so; pinned here, behaviour and string both.

def test_pipefail_is_set_before_any_pipeline_rc() -> None:
    body = _script()
    m = re.search(r"^set\s+.*-o\s+pipefail", body, re.M)
    assert m, (
        "backup.sh no longer sets `-o pipefail`. Every `rc=$?` in this file "
        "follows a pipeline ending in `aws s3 cp`, so without it a failed "
        "dump uploads an empty artifact and is logged OK — silently, nightly.")

    first_rc = body.index("rc=$?") if "rc=$?" in body else len(body)
    assert m.start() < first_rc, (
        "`pipefail` is set AFTER the first `rc=$?`, so the reads above it are "
        "still the last command's status")


def test_the_shell_actually_behaves_that_way() -> None:
    """Assert the behaviour, not the string — the string is only a proxy for it."""
    with_pf = subprocess.run(
        ["bash", "-c", "set -u -o pipefail; false | gzip -c | cat >/dev/null; echo $?"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    without = subprocess.run(
        ["bash", "-c", "set -u; false | gzip -c | cat >/dev/null; echo $?"],
        capture_output=True, text=True, timeout=30).stdout.strip()
    assert with_pf == "1", f"pipefail did not propagate the failure: rc={with_pf!r}"
    assert without == "0", (
        f"a failing head-of-pipe reported rc={without!r} WITHOUT pipefail — if this "
        "ever becomes non-zero the gate above is guarding something that no "
        "longer matters, and should be re-read rather than trusted")


def test_the_sibling_gate_does_not_still_deny_it() -> None:
    """A gate that documents the opposite makes deleting the line look safe.
    The snapshot gate now lives in this file, so this file is what is read."""
    sibling = Path(__file__)
    if not sibling.is_file():
        return
    text = sibling.read_text(encoding="utf-8")
    # Built from parts: written literally, this check would trip on itself.
    denial = "does not " + "`set -o pipefail`"
    assert denial not in text, (
        "the snapshot section (test_a_snapshot_is_opened_before_it_is_uploaded) "
        "still states that backup.sh does not set pipefail. It does, on line 8, and "
        "the whole file's error handling rests on it. A stale claim inside a gate is "
        "the one place a reader will not think to check.")


# ── test_a_snapshot_is_opened_before_it_is_uploaded ─────────────────────────
# 2026-08-13 and 08-30: the keap-db node backup died mid-copy, and both truncated
# files shipped as `keap-db: OK` because the upload branched on `test -s` and the
# pipeline's rc belonged to a `while`. The drill found the second. The snapshot
# is opened and counted before it ships (effect measured live on iiab-keap-1).

def _keap_step() -> str:
    """`run_keap_db` only — bounded at the next top-level function."""
    src = _script()
    start = src.index("run_keap_db() {")
    nxt = re.search(r"\n[a-z_]+\(\) \{", src[start + 1:])
    return src[start:start + 1 + nxt.start()] if nxt else src[start:]


def _upload_branch(step: str) -> str:
    """The `if` that decides whether to ship — the one asking `test -s`, not
    the earlier probe that asks whether the container is up at all."""
    m = re.search(r"if docker exec[^\n]*test -s.*?; then", step, re.S)
    assert m, "the upload branch no longer asks `test -s` at all — re-read this gate"
    return m.group(0)


def test_a_verifier_exists_and_opens_the_file() -> None:
    """`stat` answers "is there a file". Only opening it answers "is it a
    database", and that is the difference the two bad nights turned on."""
    src = _script()
    assert "keap_verify_js()" in src, "the snapshot verifier is gone"
    verifier = src[src.index("keap_verify_js()"):src.index("KEAPVERIFYJS\n}")]
    assert "DatabaseSync" in verifier and "count(*)" in verifier, (
        "the verifier no longer opens the snapshot and counts rows — a check "
        "that only stats the file is the one that shipped a truncated backup")
    assert "process.exit(1)" in verifier, "it cannot fail, so it is not a check"


def test_the_upload_does_not_branch_on_test_s_alone() -> None:
    step = _keap_step()
    branch = _upload_branch(step)
    assert "keap_verify_js" in branch, (
        "the snapshot is uploaded on `test -s` alone. That accepted a "
        "truncated file on 2 of 29 nights and logged `keap-db: OK` for both.")


#: A pipeline's rc is its LAST stage. Anything here at the end of the verify
#: pipeline swallows the verdict — `tee` and `cat` always succeed, a `while`
#: reports the loop. The first draft of the FIX ended in `| tee -a LOG_FILE`.
RC_SWALLOWERS = ("tee", "while", "cat", "true", "sed", "awk", "grep")


def test_the_verify_pipeline_ends_where_its_exit_code_is_read() -> None:
    """THE ROOT CAUSE, pinned — and the trap the fix itself fell into once.

    A verifier whose pipeline ends in anything that always succeeds is
    decoration. The branch must end at the command that carries node's verdict.
    CORRECTED 2026-09-01: this used to claim backup.sh lacked pipefail; it has
    it (line 8), pinned now by the pipeline-fails-loudly section above.
    """
    branch = _upload_branch(_keap_step())
    # Take everything after the last `docker exec` and look at what follows it.
    after = branch.rsplit("docker exec", 1)[-1]
    # The command NAME only: a stage can end `cat)"; then`.
    stages = [re.match(r"[a-z_]+", seg.strip().lstrip("\\ ")) for seg in after.split("|")[1:]]
    offenders = [m.group(0) for m in stages if m and m.group(0) in RC_SWALLOWERS]
    assert not offenders, (
        f"the verify pipeline continues past `docker exec` into {offenders}, "
        "whose exit code the `if` will read instead of node's — the same way "
        "the bug hid. Use a command substitution and log the output.\n" + branch)
    assert 'vout="$(' in branch or "$(keap_verify_js" in branch, (
        "the verifier's output is not captured, so either it is piped (rc lost) "
        "or it is never logged (an operator sees a failure with no reason)")


def test_the_failure_message_says_what_was_wrong() -> None:
    """`produced nothing` is what it used to say, and it was wrong twice: the
    file existed both times. An operator reading the log has to be able to tell
    "missing" from "corrupt"."""
    step = _keap_step()
    assert "NOT A READABLE DATABASE" in step, (
        "the fallback message still claims the snapshot was absent, which is "
        "not what a failed verify means")


def test_the_scratch_files_are_all_cleaned_up() -> None:
    """Three temp paths in the container now, not two. A leaked verifier
    script is a stale copy of a check, which is worse than none."""
    # `docker exec … rm -f` only; the host-sqlite3 fallback removes its own `${tmp}`.
    removals = re.findall(r'docker exec [^\n]*rm -f ([^\n]*)', _keap_step())
    assert removals, "nothing is cleaned up inside the container"
    for line in removals:
        for path in ("${ctmp}", "${cjs}", "${cvjs}"):
            assert path in line, (
                f"a container cleanup forgets {path}: {line.strip()}")


# ── test_backup_refuses_to_publish_an_empty_archive ─────────────────────────
# Live bucket 2026-08-03: six of eight dir sources had shipped a one-entry `./`
# archive every night — the host tar cannot read nos_data_root, and the stream
# reached S3 before tar's rc was known. Pre-flight count, in-container tar, and
# a member-count post-check that withdraws the object; absent stays FAILED.

def _run_dirs() -> str:
    return _fn("run_dirs")


def test_the_source_is_checked_before_anything_is_uploaded():
    """Pre-flight. The only moment at which refusing is still possible."""
    fn = _run_dirs()
    upload_at = fn.index("aws ")
    guard = re.search(r"ls -A .*\| wc -l", fn)
    assert guard, (
        "run_dirs no longer counts entries in the source directory before "
        "tarring it. Six services backed up nothing for weeks because a "
        "readable-but-empty path tars cleanly and uploads cleanly."
    )
    assert guard.start() < upload_at, (
        "the emptiness check sits AFTER the upload — by then the empty object "
        "is already in the bucket and listing like a backup"
    )


def test_an_empty_archive_is_withdrawn_rather_than_reported():
    """Post-check, for the source that lists entries and still tars to nothing."""
    fn = _run_dirs()
    assert "EMPTY_ARCHIVE_MEMBERS" in fn, (
        "the member-count check is gone — a partial permission failure would "
        "upload a padding-only archive and report OK"
    )
    assert re.search(r"s3 rm .*\$\{key\}", fn), (
        "an archive found to be empty is no longer REMOVED from the bucket. "
        "Leaving it there is worse than the failure: it occupies the day's slot "
        "and the rotation will keep it as though it held something."
    )


def test_the_directory_is_read_from_inside_a_container():
    """The actual repair. Measured on gitea's data dir, 2026-08-03: host
    `tar -C path .` -> 1 member, rc=1; alpine `-v path:/data:ro` -> 94 members.
    Docker Desktop's VM reaches the SSD over VirtioFS without the host's Full
    Disk Access grant. Plain tar works (restic's readdir was what failed).
    Reverting to a host tar restores the silent-empty defect exactly.
    """
    fn = _run_dirs()
    assert re.search(r'docker run --rm -v "\$\{path\}:/data:ro"', fn), (
        "the directory tar is no longer taken from inside a container. The "
        "host cannot read anything under nos_data_root, and it fails by "
        "producing an EMPTY archive rather than an error the pipeline sees."
    )
    assert "ALPINE_IMAGE" in fn, (
        "the sidecar no longer uses ALPINE_IMAGE — the restore extractor pins "
        "that same tag, and a divergence is a latent restore drift"
    )
    assert "grep -c '^\\./.*[^/]$'" in fn, (
        "the member count no longer filters for tar's own `./...` FILE lines. "
        "Docker writes to the same stderr, so an unfiltered count would let an "
        "empty archive past the threshold on any run that emitted a warning; "
        "and a count that includes directories let stalwart's file-less tree "
        "(./ ./etc/ ./var/) pass as 'OK 144 bytes' on 2026-09-28."
    )


def test_the_absent_case_it_was_one_step_short_of_stays_covered():
    """The neighbouring guard that got this right, pinned so it cannot regress."""
    fn = _run_dirs()
    assert re.search(r'if \[\[ ! -d "\$\{path\}" \]\]', fn), (
        "the absent-directory guard vanished — an unmounted SSD would drop "
        "sources out of the nightly set silently"
    )


def test_emptiness_is_counted_not_weighed():
    """A byte floor (10272) was written first and caught before it shipped: tar
    pads to 10240 bytes, so three small files weigh the same as nothing and the
    floor would have DELETED real backups (`nos-state` measures 10272 exactly).
    """
    body = _script()
    m = re.search(r"^EMPTY_ARCHIVE_MEMBERS=(\d+)", body, re.M)
    assert m, "EMPTY_ARCHIVE_MEMBERS is not declared beside the other constants"
    assert int(m.group(1)) == 0, (
        "the count is FILES since 2026-09-28 (a tree of bare directories is "
        "0), so 0 is the exact boundary between 'captured nothing' and "
        "'captured something'"
    )
    assert "EMPTY_ARCHIVE_CEILING" not in body, (
        "a byte-size floor is back. Size cannot distinguish an empty archive "
        "from a small one — see this test's docstring."
    )
    fn = _run_dirs()
    assert "tar -czvf" in fn, (
        "the member list is no longer produced (`-v` dropped), so the count "
        "the withdrawal decision rests on cannot be taken"
    )


# ── test_a_sqlite_dump_survives_a_denied_host ───────────────────────────────
# Nightly 2026-10-26 02:03: thalamus-ledger FAILED "authorization denied" —
# launchd's bash has no TCC grant for the external volume. run_sqlite_dump falls
# back to a container copy (db + WAL, integrity_check, dump). Executes the real
# function with a refusing sqlite3; a row only in the WAL must reach the dump.

REAL_SQLITE = shutil.which("sqlite3")


def _sqlite_fn() -> str:
    m = re.search(r"^run_sqlite_dump\(\) \{\n.*?^\}\n", _script(), re.S | re.M)
    assert m, "run_sqlite_dump moved"
    return m.group(0)


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.mark.skipif(not REAL_SQLITE or not shutil.which("bash"), reason="needs sqlite3 and bash")
def test_a_denied_source_is_dumped_from_a_container_copy(tmp_path):
    vol = tmp_path / "volume"
    vol.mkdir()
    db = vol / "ledger.db"
    keep = sqlite3.connect(db)
    keep.execute("PRAGMA journal_mode=WAL")
    keep.execute("PRAGMA wal_autocheckpoint=0")
    keep.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, what TEXT)")
    keep.execute("INSERT INTO events (what) VALUES ('only-in-the-wal')")
    keep.commit()  # held open: the row stays in ledger.db-wal, as a running thalamus leaves it
    assert (vol / "ledger.db-wal").stat().st_size > 0

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    # The host's sqlite3, refusing the volume like TCC; any other path is the real one.
    _exe(bin_ / "sqlite3", f'for a in "$@"; do [[ "$a" == "{db}" ]] && {{ echo "Error: unable to open database \\"$a\\": authorization denied" >&2; exit 1; }}; done\nexec {REAL_SQLITE} "$@"\n')
    # docker run --rm -v SRC:/data:ro IMAGE sh -c CMD  ->  CMD in SRC
    _exe(bin_ / "docker", 'src=""; while [[ $# -gt 0 ]]; do case "$1" in -v) src="${2%%:*}"; shift 2;; -c) cmd="$2"; shift 2;; *) shift;; esac; done\ncd "$src" && sh -c "${cmd//\\/data/$src}"\n')
    out = tmp_path / "uploaded.sql.gz"
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    harness = f"""set -o pipefail
log() {{ echo "LOG $*"; }}
status_append() {{ echo "STATUS $*"; }}
now_ms() {{ echo 0; }}
already_exists_today() {{ return 1; }}
encrypt_stream() {{ cat; }}
aws() {{ cat > {out}; }}
s3_size() {{ stat -f %z {out} 2>/dev/null || stat -c %s {out}; }}
ENC_SUFFIX=""; OVERWRITE_SAME_DAY=true; S3_BUCKET=b; AWS_OPTS=(); ALPINE_IMAGE=alpine
{_sqlite_fn()}
run_sqlite_dump thalamus-ledger {db} true
"""
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", TMPDIR=str(tmpdir))
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, env=env, timeout=60)
    keep.close()
    assert "STATUS thalamus-ledger" in r.stdout and r.stdout.strip().splitlines()[-1].endswith(" 1"), r.stdout + r.stderr
    assert "container copy" in r.stdout, r.stdout
    dump = subprocess.run(["gunzip", "-c", str(out)], capture_output=True, text=True).stdout
    assert "only-in-the-wal" in dump, "the WAL's last commit did not reach the dump"
    assert not list(tmpdir.iterdir()), "the plaintext copy was left behind"


@pytest.mark.skipif(not REAL_SQLITE, reason="needs sqlite3")
def test_the_host_path_is_tried_first():
    fn = _sqlite_fn()
    assert fn.index('sqlite3 -readonly "${path}"') < fn.index("docker run"), "the container copy must be the fallback"


# ── test_a_good_dump_survives_the_next_backup ───────────────────────────────
# 2026-10-31: the 03:00 nightly after a blank overwrote staging with empty fresh
# data (postgres-paperclip 6.2 MB -> 80 KB); the good copies survived only in
# restic. The pre-wipe step keeps a pre-blank copy (newest 2), and a dump under a
# tenth of its predecessor keeps it as .prev. docker/restic/aws stubbed to fail.

def _stub_env(tmp: Path) -> dict:
    bin_ = tmp / "stubbin"
    bin_.mkdir(exist_ok=True)
    for tool in ("docker", "restic", "aws"):
        (bin_ / tool).write_text("#!/bin/sh\necho \"stub $0 refused\" >&2\nexit 97\n")
        (bin_ / tool).chmod(0o755)
    return dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}")


def _rendered(tmp: Path) -> str:
    env = jinja2.Environment(undefined=jinja2.Undefined, keep_trailing_newline=True)
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    text = env.from_string(_script()).render(
        backup_staging_dir=str(tmp / "staging"), backup_status_file=str(tmp / "status.json"),
        backup_log_file=str(tmp / "backup.log"), backup_encryption_enabled=False,
        backup_overwrite_same_day=True, backup_dirs_to_dump=[],
        backup_retention_daily=7, backup_retention_weekly=4, backup_retention_monthly=6)
    return text.rsplit('\nmain "$@"', 1)[0]


def test_a_shrunk_dump_keeps_its_predecessor(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "postgres-paperclip.sql.gz").write_bytes(b"g" * 1_048_576)
    (staging / "postgres-paperclip.sql.gz.part").write_bytes(b"e" * 1024)
    r = subprocess.run(["bash", "-c", _rendered(tmp_path) + "\nstatus_append postgres-paperclip 1024 1 1\n"
                        "status_append postgres-paperclip 0 1 0\n"],
                       capture_output=True, text=True, env=_stub_env(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr
    prev = staging / "postgres-paperclip.sql.gz.prev"
    assert prev.is_file() and prev.stat().st_size == 1_048_576, "the good dump was overwritten"
    first = json.loads((tmp_path / "status.json").read_text())["sources"][0]
    assert first["shrank"] == "from 1048576 to 1024", first
    assert prev.is_file(), "a later failed run removed the kept predecessor"


def test_a_small_or_growing_dump_is_just_promoted(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "wing-db.sql.gz").write_bytes(b"o" * 4096)  # under the floor: no .prev
    (staging / "wing-db.sql.gz.part").write_bytes(b"n" * 10)
    r = subprocess.run(["bash", "-c", _rendered(tmp_path) + "\nstatus_append wing-db 10 1 1\n"],
                       capture_output=True, text=True, env=_stub_env(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr
    assert not (staging / "wing-db.sql.gz.prev").exists()
    assert (staging / "wing-db.sql.gz").read_bytes() == b"n" * 10
    assert "shrank" not in json.loads((tmp_path / "status.json").read_text())["sources"][0]


def _shell_fn(src: str, name: str) -> str:
    m = re.search(rf"^( *){name}\(\) \{{\n.*?^\1\}}\n", src, re.S | re.M)
    assert m, f"{name} moved"
    return textwrap.dedent(m.group(0))


def test_the_direct_restic_path_uses_the_same_guard():
    assert _shell_fn(BACKUP_YML.read_text(encoding="utf-8"), "keep_if_shrunk") == _shell_fn(
        _script(), "keep_if_shrunk"), "the no-RustFS staging path lost the guard"


def _prewipe_copy_task() -> dict:
    for t in yaml.safe_load(PREWIPE.read_text(encoding="utf-8")):
        if "pre-blank" in t.get("name", "") and "ansible.builtin.shell" in t:
            return t
    raise AssertionError("pre-wipe-backup.yml has no step that keeps a pre-blank copy of staging")


def test_the_blank_keeps_its_own_copy_newest_two(tmp_path):
    task = _prewipe_copy_task()
    env_keys = task.get("environment") or {}
    assert "backup_staging_dir" in env_keys["NOS_STAGING"] and "backup_pre_blank_dir" in env_keys["NOS_PRE_BLANK"]
    src = tmp_path / "staging"
    (src / "keap-tables").mkdir(parents=True)
    (src / "postgres-paperclip.sql.gz").write_bytes(b"g" * 2048)
    (src / "keap-tables" / "manifest.json").write_text("{}")
    root = tmp_path / "pre-blank"
    env = _stub_env(tmp_path)
    for stamp in ("20261029T100000Z", "20261030T174700Z", "20261031T090000Z"):
        r = subprocess.run(["bash", "-c", task["ansible.builtin.shell"]], capture_output=True, text=True,
                           env=dict(env, NOS_STAGING=str(src), NOS_PRE_BLANK=str(root), NOS_STAMP=stamp),
                           timeout=60)
        assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in root.iterdir()) == ["20261030T174700Z", "20261031T090000Z"]
    kept = root / "20261031T090000Z"
    assert (kept / "postgres-paperclip.sql.gz").read_bytes() == b"g" * 2048
    assert (kept / "keap-tables" / "manifest.json").is_file()
    # A later overwrite of staging (mv over the name, as backup.sh promotes) leaves the copy.
    (src / "new.part").write_bytes(b"e")
    os.replace(src / "new.part", src / "postgres-paperclip.sql.gz")
    assert (kept / "postgres-paperclip.sql.gz").stat().st_size == 2048


def test_the_blank_record_names_the_copy():
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    line = re.search(r"\[Blank\] Append the open record.*?line: (.*?)\n\s+create:", main, re.S)
    assert line and "'pre_blank'" in line.group(1), "blank-runs.jsonl does not say where the pre-blank copy is"


# ── test_a_removal_without_a_survivor_stops ─────────────────────────────────
# Operator 2026-10-02 ("we must have working backups"), reversing 07-25's
# warn-only: with -y there is no pause, so a failed pre-wipe snapshot let
# remove=all delete data that existed nowhere else. The last pre-wipe step is an
# assert that stops the removal.

PREWIPE_TASKS = yaml.safe_load(PREWIPE.read_text())
VERDICT = PREWIPE_TASKS[-1]
OK = {"_prewipe_backup_sh": {"stat": {"exists": True}}, "_prewipe_copy1": {"rc": 0},
      "_prewipe_restic": {"rc": 0}, "_prewipe_snapshot": {"rc": 0}, "restic_repo": "/r"}


def _passes(ctx) -> bool:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)  # as Ansible chains
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes", "y", "on")
    return all(env.from_string("{{ (" + c + ") }}").render(**ctx) == "True"
               for c in VERDICT["ansible.builtin.assert"]["that"])


def test_the_verdict_is_last_and_on_by_default():
    assert "ansible.builtin.assert" in VERDICT, "the verdict must be the last pre-wipe step"
    assert VERDICT["when"] == "prewipe_snapshot_required | default(true) | bool"


def test_a_complete_backup_passes_and_each_missing_piece_stops():
    assert _passes(OK)
    for key, bad in (("_prewipe_snapshot", {"rc": 1}), ("_prewipe_copy1", {"rc": 2}),
                     ("_prewipe_restic", {"rc": 127}), ("_prewipe_backup_sh", {"stat": {"exists": False}})):
        assert not _passes({**OK, key: bad}), key
    assert not _passes({k: v for k, v in OK.items() if k != "_prewipe_snapshot"}), "a skipped snapshot is not a snapshot"
    assert not _passes({**OK, "restic_repo": ""}), "no repo, no survivor (review 2026-10-04)"


# ── test_restore_dry_run_gathers_its_own_evidence ───────────────────────────
# Measured 2026-09-15 under `--check`: the s3 listing (a `command`) was skipped,
# empty `restore_ls` became "No backups found" — a dry run inventing a failure
# (fee 36). The listing carries `check_mode: false`; it is a read.

def _tasks(node):
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        if any(k in node for k in ("name", "block", "when", "register")):
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _tasks(node[key])


def test_restore_list_opts_out_of_check_mode() -> None:
    """The measured invented failure: skip the list, refuse on empty stdout."""
    doc = yaml.safe_load(RESTORE.read_text(encoding="utf-8"))
    tasks = list(_tasks(doc))
    listing = next(t for t in tasks if t.get("register") == "restore_ls")
    assert listing.get("check_mode") is False, (
        "tasks/restore.yml lists backups with a check-blind command; "
        "--check skips it and the next fail: treats empty stdout as "
        "'no backups'. Add check_mode: false — aws s3 ls is a read."
    )
    bail = next(
        t for t in tasks
        if "Bail if no backups exist" in str(t.get("name", ""))
    )
    assert "restore_ls" in str(bail.get("when", "")), (
        "the no-backups refusal no longer reads restore_ls — re-scope this gate"
    )


# ── test_restore_templating ─────────────────────────────────────────────────
# First real restore 2026-09-28: folded/literal YAML scalars do not unescape, so
# `\\s` and `\\n` reached Jinja as two characters — every selection bailed "no
# files match" and the key ring joined onto one line. The contract tests never
# rendered a template; these run the real expressions on realistic input.

#: A real `aws s3 ls` line: date, time, size, key.
LS_LINES = [
    "2026-09-27 03:00:04    1650464 mariadb.sql.gz.enc",
    "2026-09-27 03:00:30   40302432 postgres.sql.gz.enc",
    "2026-09-27 03:01:59  154936608 wing-db.sql.gz.enc",
]


def _parse_pattern() -> tuple[str, str]:
    """The selection regex exactly as restore.yml carries it."""
    text = RESTORE.read_text(encoding="utf-8")
    m = re.search(r"map\('regex_replace',\s*'([^']+)',\s*'([^']+)'\)", text)
    assert m, "the filename-parsing regex is gone from restore.yml — re-point this gate"
    return m.group(1), m.group(2)


def test_filename_parsing_strips_the_aws_columns():
    """The selection bug: whole `ls` lines must become bare object keys."""
    pattern, repl = _parse_pattern()
    out = [re.sub(pattern, repl, ln) for ln in LS_LINES]
    assert out[0] == "mariadb.sql.gz.enc", (
        f"filenames still carry their aws s3 ls columns: {out}. A folded scalar "
        "does not unescape — the regex needs single backslashes."
    )
    assert not any("03:00" in o for o in out), f"time column survived: {out}"


@pytest.mark.parametrize("name,stem", [
    ("mariadb.sql.gz.enc", "mariadb"),
    ("postgres.sql.gz.enc", "postgres"),
    ("keap-db.gz.enc", "keap-db"),
    ("dir-gitea.tar.gz.enc", "dir-gitea"),
])
def test_a_key_reduces_to_its_canonical_stem(name, stem):
    """The plan bug: `.enc` and the compression extension must actually strip."""
    plain = re.sub(r"\.enc$", "", name)
    noext = re.sub(r"\.sql\.gz$|\.tar\.gz$|\.json\.gz$|\.json$|\.gz$", "", plain)
    assert noext == stem, f"{name} reduced to {noext!r}, wanted {stem!r}"
    assert not noext.endswith(".enc"), "the .enc suffix survived"


def test_the_key_ring_is_joined_on_a_real_newline():
    """The ring bug: keys must arrive one per line, or `read -r` gets one blob."""
    text = RESTORE.read_text(encoding="utf-8")
    assert "NOS_RESTORE_KEYS_RAW: |-" not in text, (
        "the key ring is built inside a `|-` literal block again. `\\n` is not a "
        "newline there, so every key lands on one line and no key decrypts — "
        "which only shows up AFTER a rotation, when the ring finally matters."
    )
    assert "join(_nos_restore_nl)" in text, (
        "the ring no longer joins on the real-newline variable; if the separator "
        "moved, make sure it is a newline YAML itself produced."
    )


def test_no_double_backslash_regex_survives_in_a_block_scalar():
    """The general rule, so the next one is caught by shape rather than by outage."""
    offenders = [
        f"{n}: {ln.strip()[:80]}"
        for n, ln in enumerate(RESTORE.read_text(encoding="utf-8").splitlines(), 1)
        if "regex_replace" in ln and "\\\\" in ln
    ]
    assert not offenders, (
        "double-backslash regex(es) inside restore.yml's block scalars — these "
        "match a literal backslash and silently do nothing:\n  " + "\n  ".join(offenders)
    )
