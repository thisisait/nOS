"""Gate: backup.sh backs up, and red-status reports, only what this host installed.

2026-10-16, a core-profile client host: red-status said `backup sources failed:
mariadb, dir-gitea, dir-vaultwarden, dir-n8n, ...` — none of them installed.
backup_databases_mariadb was a literal `true`, and an off service's dir was still
tarred when present (external-storage.yml pre-creates it empty -> FAILED).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import jinja2

REPO = Path(__file__).resolve().parents[2]
BACKUP = REPO / "roles/pazny.backup/files/backup.sh"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

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


def test_the_rendered_source_set_is_the_core_install_set():
    flags, cfg, env, toggles = _core()
    env.globals["lookup"] = lambda kind, name, default=False: flags.get(name, default)
    text = env.from_string(BACKUP.read_text(encoding="utf-8")).render(
        backup_dirs_to_dump=cfg["backup_dirs_to_dump"], backup_encryption_enabled=False,
        backup_overwrite_same_day=True, backup_retention_daily=7, backup_retention_weekly=4,
        backup_retention_monthly=6, **toggles)
    defs = text.rsplit('\nmain "$@"', 1)[0]
    out = subprocess.run(["bash", "-c", defs + '\necho "$DO_MARIADB $DO_POSTGRES $DO_AUTHENTIK $DO_KEAP"'
                          '\nprintf "%s\\n" "${DIR_NAMES[@]}"'],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    dbs, dirs = out[0].split(), {d for d in out[1:] if d}
    assert dbs == ["false", "true", "true", "true"], f"mariadb/postgres/authentik/keap = {dbs}"
    assert not dirs & NOT_ON_CORE, f"core backs up dirs of services it never installed: {dirs & NOT_ON_CORE}"
    assert "authentik" in dirs, dirs


def test_the_reader_does_not_report_a_source_this_host_never_installed(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("red_status", REPO / "tools/red-status.py")
    red = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(red)
    flags, *_ = _core()
    status = tmp_path / "backup-status.json"
    names = ["mariadb", "postgres", "dir-gitea", "dir-dolibarr-documents", "dir-authentik",
             "keap-db", "nos-state"]
    status.write_text(json.dumps({"sources": [{"name": n, "success": False, "timestamp": 1} for n in names]}))
    monkeypatch.setattr(red, "BACKUP_STATUS", status)
    monkeypatch.setattr(red, "_install_flags", lambda: flags)
    assert red.backups()["failed"] == ["postgres", "dir-authentik", "keap-db", "nos-state"], (
        "an installed source that failed stays red; a never-installed one is no finding")
