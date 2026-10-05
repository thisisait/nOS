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
import re
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
    """...and a failure also evicts yesterday's promoted copy: stalwart's
    stale 144-byte tar sat in staging after the run that withdrew it."""
    staging = rendered.parent / "staging"
    staging.mkdir(exist_ok=True)
    (staging / "dir-gitea.tar.gz").write_bytes(b"yesterday")
    (staging / "dir-gitea-config.tar.gz").write_bytes(b"sibling")
    _run(rendered, '''
        printf 'half' | encrypt_stream "2026-09-28/dir-gitea.tar.gz" > /dev/null
        status_append dir-gitea 0 1 0
    ''')
    assert not (staging / "dir-gitea.tar.gz").exists(), "a failed source left a stale promoted copy"
    assert (staging / "dir-gitea-config.tar.gz").read_bytes() == b"sibling", "the glob reached a sibling"
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
    assert "env" not in cfg["repos"][0], "no S3 creds configured, none may be rendered"


def test_backrest_seed_passes_s3_credentials_to_an_s3_target() -> None:
    text = _env().from_string(BACKREST.read_text(encoding="utf-8")).render(
        restic_repo="s3:https://nas.lan:9000/nos-restic", restic_password="x",
        restic_s3_access_key="AK", restic_s3_secret_key="SK",
        backrest_home="/h", backrest_instance="i",
        ansible_facts={"env": {"HOME": "/home/u"}},
    )
    repo = json.loads(text)["repos"][0]
    assert repo["uri"].startswith("s3:")
    assert set(repo["env"]) == {"AWS_ACCESS_KEY_ID=AK", "AWS_SECRET_ACCESS_KEY=SK"}


def test_the_reconciler_adds_the_plan_to_a_daemon_that_predates_it(tmp_path: Path) -> None:
    """Seed-once never reaches an existing daemon (the July spike's config had 0
    plans). enable-auth.py --seed must add absent repo/plan ids and leave the
    UI-owned rest alone; a second run is UNCHANGED."""
    import subprocess
    seed = _env().from_string(BACKREST.read_text(encoding="utf-8")).render(
        restic_repo="/tmp/repo", restic_password="x", backrest_home="/h",
        backrest_instance="i", backup_staging_dir="/s",
        ansible_facts={"env": {"HOME": "/home/u"}},
    )
    (tmp_path / "seed.json").write_text(seed)
    live = tmp_path / "config.json"
    live.write_text(json.dumps({"version": 6, "instance": "i", "auth": {"disabled": True},
                                "plans": [{"id": "mine", "repo": "offsite", "paths": ["/ui"]}]}))
    script = REPO / "roles/pazny.backrest/files/enable-auth.py"
    run = lambda: subprocess.run(["python3", str(script), "--config", str(live), "--seed",
                                  str(tmp_path / "seed.json")], input="pw", text=True,
                                 capture_output=True, check=True).stdout
    assert run().startswith("CHANGED")
    cfg = json.loads(live.read_text())
    assert [p["id"] for p in cfg["plans"]] == ["mine", "nos-offsite", "nos-dumps"]
    assert cfg["plans"][0]["paths"] == ["/ui"], "a UI-owned plan was rewritten"
    assert [r["id"] for r in cfg["repos"]] == ["offsite"] and cfg["auth"]["disabled"] is False
    assert run().strip() == "UNCHANGED"


def test_the_dir_arrays_render_in_lockstep() -> None:
    """DIR_NAMES / DIR_PATHS / DIR_EMPTY_OK are parallel bash arrays indexed by
    one `i`; a filter applied to one and not the others silently pairs a name
    with the wrong path or verdict. Rendered with the gitlab skip active."""
    import subprocess
    env = _env()
    env.globals["lookup"] = lambda kind, name, default=False: {"install_gitlab": False}.get(name, True)
    text = env.from_string(BACKUP.read_text(encoding="utf-8")).render(
        backup_dirs_to_dump=[
            {"name": "gitea", "path": "/g", "flag": "install_gitea"},
            {"name": "gitlab", "path": "/gl", "flag": "install_gitlab"},   # skipped: flag off
            {"name": "outline", "path": "/o", "empty_ok": True},
        ],
        backup_encryption_enabled=False, backup_overwrite_same_day=True,
        backup_retention_daily=7, backup_retention_weekly=4, backup_retention_monthly=6,
    )
    defs = text.rsplit('\nmain "$@"', 1)[0]
    out = subprocess.run(["bash", "-c", defs + '\necho "${#DIR_NAMES[@]} ${#DIR_PATHS[@]} ${#DIR_EMPTY_OK[@]} ${#DIR_ENABLED[@]} '
                          '${DIR_NAMES[1]} ${DIR_PATHS[1]} ${DIR_ENABLED[1]} ${DIR_EMPTY_OK[2]}"'],
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["3", "3", "3", "3", "gitlab", "/gl", "false", "true"], out


def test_an_off_service_dir_is_skipped_only_when_absent(tmp_path) -> None:
    """Review 2026-10-04: filtering on the flag alone dropped an off service's
    leftover data from the nightly set, silently, until retention aged it out.
    Runs the real run_dirs loop with tar/S3 stubbed out."""
    import subprocess
    present = tmp_path / "vault"
    present.mkdir()
    (present / "db.sqlite").write_text("x")
    env = _env()
    flags = {"install_vaultwarden": False, "install_mikopbx": False, "install_gitea": True}
    env.globals["lookup"] = lambda kind, name, default=False: flags.get(name, default)
    text = env.from_string(BACKUP.read_text(encoding="utf-8")).render(
        backup_dirs_to_dump=[
            {"name": "mikopbx", "path": str(tmp_path / "none"), "flag": "install_mikopbx"},  # off, absent
            {"name": "gitea", "path": str(tmp_path / "gone"), "flag": "install_gitea"},     # on, absent
            {"name": "vaultwarden", "path": str(present), "flag": "install_vaultwarden"},  # off, present: last
        ],
        backup_encryption_enabled=False, backup_overwrite_same_day=True,
        backup_retention_daily=7, backup_retention_weekly=4, backup_retention_monthly=6,
    )
    defs = text.rsplit('\nmain "$@"', 1)[0]
    probe = ('\nlog() { echo "LOG $*"; }\nstatus_append() { echo "STATUS $1 $4"; }\n'
             'docker() { return 1; }\naws() { return 1; }\nrun_dirs 2>/dev/null; true')
    out = subprocess.run(["bash", "-c", defs + probe], capture_output=True, text=True).stdout
    assert "STATUS dir-mikopbx" not in out, "off and absent must be skipped"
    assert "STATUS dir-gitea 0" in out, "on and absent must be FAILED"
    assert "dir/vaultwarden: service off" not in out and "vaultwarden" in out, (
        "off but present must still be attempted, not skipped")


def test_a_directories_only_archive_counts_as_empty() -> None:
    """The member count that decides "captured nothing" must count FILES: a
    tree of bare directories listed 3 members and passed (stalwart, 2026-09-28)."""
    text = BACKUP.read_text(encoding="utf-8")
    m = re.search(r"tar_members=\$\(grep -c '([^']+)'", text)
    assert m, "the tar member count moved — re-point this gate"
    pat = m.group(1)
    listing = ["./", "./etc/", "./var/"]
    assert sum(bool(re.match(pat, ln)) for ln in listing) == 0, pat
    assert sum(bool(re.match(pat, ln)) for ln in listing + ["./var/db.sqlite"]) == 1, pat


def test_the_member_count_is_a_number_when_nothing_matches(rendered: Path) -> None:
    """Runs the counting lines lifted from run_dirs against a dirs-only
    listing: the result must be the integer 0, not "0\\n0" (grep -c prints 0
    AND exits 1; an `|| echo 0` fallback doubled it and `-le` choked)."""
    import subprocess
    text = BACKUP.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("tar_members=")]
    assert len(lines) == 2, lines
    script = 'tar_list=$(mktemp); printf "./\\n./etc/\\n./var/\\n" > "$tar_list"\n' + "\n".join(lines) + \
             '\n[[ "$tar_members" -le 0 ]] && echo "empty:$tar_members"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert out.stdout.strip() == "empty:0" and out.stderr == "", (out.stdout, out.stderr)
