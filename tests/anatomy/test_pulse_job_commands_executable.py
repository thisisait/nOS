"""Anatomy gate — every pulse job's command must be executable IN GIT.

Wing's pulse_jobs API requires an absolute command path with no leading
interpreter word, so the script is exec'd directly and its shebang does the rest.
That makes the executable bit load-bearing, and it is carried by git's file mode,
which nothing else in the tree checks.

`keap-features-sync.py` was committed 100644 on 2026-07-14 and failed on every
single fire for twelve days with `PermissionError: [Errno 13]`. It cost nothing
and produced nothing: `node_features` stayed at 0 rows the whole time. The
failure was recorded faithfully in Wing's `pulse_runs` (exit_code 255) and never
looked at, because until 2026-07-26 no screen rendered it.

Two defences landed together: Wing's /pulse view (so a failing job is visible)
and this test (so the specific cause cannot recur silently). This one is the
cheaper of the two — it fails in CI, before a converge, on a diff.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files" / "anatomy" / "plugins"

# `command:` is a Jinja template; the only part we can resolve statically is the
# repo-relative tail after {{ playbook_dir }}.
_PLAYBOOK_DIR = re.compile(r"\{\{\s*playbook_dir\s*\}\}/")


def _plugin_job_commands() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for manifest in sorted(PLUGINS.glob("*/plugin.yml")):
        doc = yaml.safe_load(manifest.read_text()) or {}
        for job in (doc.get("pulse") or {}).get("jobs") or []:
            command = str(job.get("command", ""))
            if not _PLAYBOOK_DIR.search(command):
                continue  # not a repo-local script (absolute host path, or a binary)
            rel = _PLAYBOOK_DIR.sub("", command).strip()
            out.append((manifest.parent.name, str(job.get("name", "?")), rel))
    return out


CASES = _plugin_job_commands()


def test_there_are_jobs_to_check():
    """Guard the guard: a parser that silently matches nothing always passes."""
    assert CASES, "no repo-local pulse job commands found — the parser is broken"


@pytest.mark.parametrize("plugin,job,rel", CASES, ids=[f"{p}:{j}" for p, j, _ in CASES])
def test_pulse_job_command_is_executable_in_git(plugin: str, job: str, rel: str):
    path = REPO / rel
    assert path.exists(), f"{plugin}:{job} points at a missing script: {rel}"

    mode = subprocess.run(
        ["git", "ls-files", "-s", "--", rel],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert mode, f"{rel} is not tracked by git — a converge would deploy an untracked file"
    assert mode[0] == "100755", (
        f"{plugin}:{job} runs {rel}, which git has as mode {mode[0]}. Pulse execs the "
        f"path directly, so a non-executable script fails with PermissionError on EVERY "
        f"fire and produces nothing. Fix with: git update-index --chmod=+x {rel}"
    )
