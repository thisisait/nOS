"""`tools/deploy-sync.sh` resets the deploy checkout to upstream before a
converge — a `git reset --hard`. Its one load-bearing safety property is that
it discards ONLY the two scan-output files; anything else (a real edit, a real
commit) must STOP it. And its scan-path allow-list must stay identical to
`scan-state-snapshot.py`'s — a file the snapshot tool preserves but deploy-sync
does not recognise would be treated as "real work" and re-introduce the very
reconcile dance this tool removes.
"""
import re
import subprocess
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
SYNC = REPO / "tools" / "deploy-sync.sh"
SNAP = REPO / "tools" / "scan-state-snapshot.py"


def _sync_scan_paths() -> set[str]:
    txt = SYNC.read_text(encoding="utf-8")
    block = re.search(r"SCAN_PATHS=\((.*?)\)", txt, re.S).group(1)
    return set(re.findall(r'"([^"]+)"', block))


def _snapshot_scan_paths() -> set[str]:
    # The allow-list literal in scan-state-snapshot.py (the plumbing tool's
    # hardcoded paths — see its "read-tree / update-index" safety note).
    txt = SNAP.read_text(encoding="utf-8")
    return set(re.findall(r'"(docs/llm/security/[^"]+\.json)"', txt))


def test_the_two_tools_agree_on_what_scan_output_is():
    assert _sync_scan_paths() == _snapshot_scan_paths(), (
        "deploy-sync.sh and scan-state-snapshot.py disagree on the scan-output "
        "path set; a file one preserves and the other does not know is a file "
        "deploy-sync would refuse to drop, bringing the reconcile dance back"
    )


def test_syntax_is_valid():
    assert subprocess.run(["bash", "-n", str(SYNC)]).returncode == 0


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, env=_ENV)


import os
_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def test_a_non_scan_dirty_file_refuses(tmp_path):
    """The core guard: a working-tree change that is NOT scan output stops the
    tool (exit 2) rather than being reset away. Exercised via --dry-run, which
    reaches the dirty-path check before touching anything."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(["init", "--bare", "-b", "dev", str(origin)], tmp_path)
    _git(["clone", str(origin), str(work)], tmp_path)
    (work / "seed").write_text("x")
    _git(["add", "seed"], work)
    _git(["commit", "-m", "seed"], work)
    _git(["push", "origin", "dev"], work)
    # a real, non-scan edit sitting in the tree
    (work / "real_code.py").write_text("print('mine')\n")
    _git(["add", "real_code.py"], work)

    r = subprocess.run(["bash", str(SYNC), "--dry-run"], cwd=work,
                       capture_output=True, text=True, env=_ENV)
    assert r.returncode == 2, f"expected refusal (2), got {r.returncode}\n{r.stderr}"
    assert "real_code.py" in r.stderr and "not scan output" in r.stderr
