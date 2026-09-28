"""backup.sh tees every dump into a plaintext staging dir; Backrest snapshots it.

Increment 1 of the 2026-09-28 backup fork: the logical dumps stay the
app-consistency layer, host restic becomes the STORE, Backrest the UI. The
whole thing rides on one shared function (`encrypt_stream`, 12 call sites) and
one verdict hook (`status_append`), so this gate RUNS them instead of reading
about them — the sibling contract test never rendered backup.sh, which is how
restore stayed broken for months.

Three things are executed, not grepped:
  1. the template RENDERS (the `${#arr[@]}` brace-hash trap kills a live run,
     and `bash -n` on the unrendered file cannot see it) and the result parses;
  2. bytes piped through `encrypt_stream <key>` land in `<staging>/<name>.part`,
     and `status_append … 1` promotes it while `… 0` removes it;
  3. the Backrest seed renders to JSON with a `nos-dumps` plan over the staging
     dir that excludes `*.part` and tags the run.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[2]
BACKUP = REPO / "roles/pazny.backup/files/backup.sh"
BACKREST = REPO / "roles/pazny.backrest/templates/config.json.j2"


def _env() -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.Undefined, keep_trailing_newline=True)
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    return env


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("backup")
    text = _env().from_string(BACKUP.read_text(encoding="utf-8")).render(
        backup_staging_dir=str(tmp / "staging"),
        backup_status_file=str(tmp / "status.json"),
        backup_log_file=str(tmp / "backup.log"),
        backup_encryption_enabled=False,
        backup_overwrite_same_day=True,
        backup_retention_daily=7, backup_retention_weekly=4, backup_retention_monthly=6,
        backup_dirs_to_dump=[],
    )
    out = tmp / "backup.sh"
    out.write_text(text, encoding="utf-8")
    return out


def test_the_template_renders_and_parses(rendered: Path) -> None:
    subprocess.run(["bash", "-n", str(rendered)], check=True)
    assert "{#" not in BACKUP.read_text(encoding="utf-8"), (
        "a `{#` (bash `${#arr[@]}`) opens a Jinja comment and the live render fails"
    )


def _run(rendered: Path, script: str) -> subprocess.CompletedProcess:
    # Source the definitions only: `main "$@"` is the last line of the file.
    defs = rendered.read_text(encoding="utf-8").rsplit("\nmain \"$@\"", 1)[0]
    return subprocess.run(
        ["bash", "-c", defs + "\n" + script],
        capture_output=True, text=True, check=True,
    )


def test_a_dump_is_staged_and_promoted_on_success(rendered: Path) -> None:
    _run(rendered, '''
        ENC_SUFFIX=".enc"
        printf 'dump-bytes' | encrypt_stream "2026-09-28/mariadb.sql.gz.enc" > /dev/null
        test -f "${STAGING_DIR}/mariadb.sql.gz.part"
        status_append mariadb 10 1 1
    ''')
    staging = Path(json.loads((rendered.parent / "status.json").read_text())["sources"][0]["name"])
    staged = rendered.parent / "staging" / "mariadb.sql.gz"
    assert staging.name == "mariadb" and staged.read_bytes() == b"dump-bytes"
    assert not staged.with_suffix(".gz.part").exists()
    assert oct(os.stat(rendered.parent / "staging").st_mode & 0o777) == "0o700"


def test_a_failed_dump_never_reaches_staging(rendered: Path) -> None:
    _run(rendered, '''
        printf 'half' | encrypt_stream "2026-09-28/dir-gitea.tar.gz" > /dev/null
        status_append dir-gitea 0 1 0
    ''')
    staging = rendered.parent / "staging"
    assert not (staging / "dir-gitea.tar.gz").exists()
    assert not list(staging.glob("*.part")), "a failed dump left a .part behind"


def test_a_call_without_a_key_stages_nothing(rendered: Path) -> None:
    out = _run(rendered, 'printf x | encrypt_stream')
    assert out.stdout == "x"


def test_every_pipe_site_passes_the_key() -> None:
    text = BACKUP.read_text(encoding="utf-8")
    bare = [ln for ln in text.splitlines()
            if "encrypt_stream" in ln and "encrypt_stream()" not in ln
            and '"${key}"' not in ln and not ln.lstrip().startswith("#")]
    assert not bare, f"encrypt_stream called without the key — that dump is never staged: {bare}"


def test_backrest_seed_has_the_dumps_plan() -> None:
    text = _env().from_string(BACKREST.read_text(encoding="utf-8")).render(
        restic_repo="/tmp/repo", restic_password="x", backrest_home="/h",
        backrest_instance="i", backup_staging_dir="/home/u/backups/staging",
        ansible_facts={"env": {"HOME": "/home/u"}},
    )
    cfg = json.loads(text)
    plan = {p["id"]: p for p in cfg["plans"]}["nos-dumps"]
    assert plan["paths"] == ["/home/u/backups/staging"]
    assert "*.part" in plan["excludes"]
    assert "run=nightly" in plan["backup_flags"]
    assert plan["repo"] in {r["id"] for r in cfg["repos"]}
