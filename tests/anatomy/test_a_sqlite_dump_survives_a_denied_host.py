"""A SQLite source the host may not open under launchd is dumped from a container copy.

MEASURED 2026-10-26 02:03: the nightly backup recorded thalamus-ledger FAILED, "unable to open
database …/ledger.db: authorization denied" — launchd's /bin/bash has no TCC grant for the external
volume, while the converge's run from a terminal had passed. run_dirs already reads those dirs
through the container; run_sqlite_dump now does too: copy db + WAL out, integrity_check, then dump.

Executed: the real function from roles/pazny.backup/files/backup.sh, in bash, with a sqlite3 that
refuses the original path the way launchd's TCC did, and a docker that runs the container's command
in the source dir. A row that lives only in the WAL must reach the dump.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "roles/pazny.backup/files/backup.sh"
REAL_SQLITE = shutil.which("sqlite3")


def _function() -> str:
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"^run_sqlite_dump\(\) \{\n.*?^\}\n", src, re.S | re.M)
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
{_function()}
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
    fn = _function()
    assert fn.index('sqlite3 -readonly "${path}"') < fn.index("docker run"), "the container copy must be the fallback"
