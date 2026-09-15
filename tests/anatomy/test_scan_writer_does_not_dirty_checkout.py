"""The nightly scan must not dirty the converge checkout.

SHIPPED plat-deploy-sync made leftover scan JSON cheap to reconcile. It did
not stop the Pulse job writing remediation-queue.json + scan-state.json into
the DEPLOY tree. The live notebook is ~/.nos/security/; git copies are the
last promotion.

Retro-red: on the pre-fix tree this fails because (1) Pulse still aims
VULNSCAN_SECURITY_DIR at playbook_dir/docs/llm/security, so a simulated stamp
shows those two paths in `git status --porcelain`, and (2) rem-status.py reads
the git file even when the runtime notebook is absent, so missing live state
looks like a healthy tally instead of UNKNOWN.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "files/vuln-scan/scan-runner.sh"
PULSE = REPO / "files/anatomy/agents/conductor/agent.yml"
REM = REPO / "tools/rem-status.py"
DIRTY = (
    "docs/llm/security/remediation-queue.json",
    "docs/llm/security/scan-state.json",
)
_GIT = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=_GIT,
    )


def _pulse_security_dir(playbook_dir: Path, home: Path) -> Path:
    """Where the Pulse job tells the scan to write — the 02:00 path."""
    src = PULSE.read_text(encoding="utf-8")
    block = src[src.index("- name: vulnerability-scan"):]
    cut = block.find("\n    - name:")
    if cut == -1:
        cut = block.find("\ntask_types:")
    block = block[:cut]
    m = re.search(r'VULNSCAN_SECURITY_DIR:\s*"([^"]+)"', block)
    assert m, "Pulse vulnerability-scan no longer sets VULNSCAN_SECURITY_DIR"
    raw = m.group(1)
    raw = raw.replace("{{ playbook_dir }}", str(playbook_dir))
    raw = raw.replace("{{ ansible_facts['env']['HOME'] }}", str(home))
    raw = raw.replace("{{ ansible_env.HOME }}", str(home))
    raw = raw.replace("~", str(home))
    return Path(raw)


def _checkout(tmp: Path) -> Path:
    repo = tmp / "checkout"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    sec = repo / "docs/llm/security"
    sec.mkdir(parents=True)
    (sec / "scan-state.json").write_text('{"scan_cycle":1,"components":{}}\n')
    (sec / "remediation-queue.json").write_text('{"items":[]}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    return repo


def _stamp_notebook(target: Path) -> None:
    """The scan-runner's write: update both JSON files in SECURITY_DIR."""
    target.mkdir(parents=True, exist_ok=True)
    (target / "scan-state.json").write_text(
        json.dumps({"scan_cycle": 99, "last_full_scan": "2026-09-15T00:00:00Z"}) + "\n"
    )
    (target / "remediation-queue.json").write_text(
        json.dumps({"items": [{"id": "REM-SIM", "status": "pending", "severity": "HIGH"}]}) + "\n"
    )


def test_runner_default_is_the_runtime_notebook_not_the_checkout():
    src = RUNNER.read_text(encoding="utf-8")
    assign = next((ln for ln in src.splitlines() if ln.startswith("SECURITY_DIR=")), "")
    assert assign, "scan-runner.sh no longer assigns SECURITY_DIR"
    assert ".nos/security" in assign, (
        "scan-runner.sh default SECURITY_DIR is not ~/.nos/security — the nightly "
        "job will write into whichever checkout Pulse started from"
    )
    assert "docs/llm/security" not in assign, (
        "scan-runner.sh still defaults SECURITY_DIR into the repo tree"
    )


def test_pulse_job_does_not_aim_the_writer_at_the_checkout():
    src = PULSE.read_text(encoding="utf-8")
    block = src[src.index("- name: vulnerability-scan"):]
    m = re.search(r'VULNSCAN_SECURITY_DIR:\s*"([^"]+)"', block)
    assert m, "Pulse vulnerability-scan no longer sets VULNSCAN_SECURITY_DIR"
    assert "playbook_dir" not in m.group(1), (
        "Pulse still aims VULNSCAN_SECURITY_DIR at playbook_dir — that is the "
        "deploy checkout the nightly scan must not dirty"
    )
    assert ".nos/security" in m.group(1)


def test_scan_pulse_simulation_does_not_dirty_checkout(tmp_path):
    """After a scan stamp, porcelain must not list the two promotion JSON paths."""
    repo = _checkout(tmp_path)
    home = tmp_path / "home"
    target = _pulse_security_dir(repo, home)
    _stamp_notebook(target)
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    listed = {ln[3:].strip() for ln in porcelain.splitlines() if ln.strip()}
    for rel in DIRTY:
        assert rel not in listed, (
            f"scan pulse simulation dirtied {rel} (porcelain={porcelain!r}). "
            f"Writer target was {target}"
        )


def test_the_gate_goes_red_when_the_writer_still_targets_the_checkout(tmp_path):
    """Positive control: a repo-path write DOES show in porcelain.

    A gate that cannot fail on the broken tree pins nothing. This is that
    broken write, kept as a monkeypatch so the assertion above has teeth.
    """
    repo = _checkout(tmp_path)
    _stamp_notebook(repo / "docs/llm/security")
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout
    listed = {ln[3:].strip() for ln in porcelain.splitlines() if ln.strip()}
    assert DIRTY[0] in listed and DIRTY[1] in listed, (
        "stamping the git paths no longer dirties porcelain; this gate would "
        f"go green on the broken tree. porcelain={porcelain!r}"
    )


def test_missing_runtime_queue_is_unknown_not_green(tmp_path):
    missing = tmp_path / "no-such-notebook"
    env = {
        **os.environ,
        "NOS_SECURITY_DIR": str(missing),
        "VULNSCAN_SECURITY_DIR": str(missing),
    }
    proc = subprocess.run(
        [sys.executable, str(REM)], env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"rem-status.py must exit 0 even when the notebook is absent "
        f"(got {proc.returncode})\n{proc.stderr}"
    )
    out = proc.stdout + proc.stderr
    assert "UNKNOWN" in out, (
        "a missing runtime queue must read UNKNOWN, not a git-file tally that "
        f"looks like health. output:\n{out}"
    )
    assert re.search(r"\b0 rows\b", out) is None, (
        "an absent notebook rendered as 0 rows — absence read as green:\n" + out
    )


def test_the_writer_logs_the_runtime_path_it_wrote():
    src = RUNNER.read_text(encoding="utf-8")
    assert "security_dir" in src, (
        "scan-runner.sh does not log the runtime path it wrote (structured)"
    )
    # A success stamp written by the writer is the defect this estate forbids.
    # rem-status.py is the reader.
    assert "write_ok" not in src and 'status = "written"' not in src
