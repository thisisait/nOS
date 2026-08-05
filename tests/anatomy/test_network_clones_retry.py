"""A clone from the public internet must survive a transient, or it ends the run.

WHAT THIS COST, 2026-08-05. A full converge reached task 605 of an hour-long run
and died on `git ls-remote` returning HTTP 429 — GitHub rate-limiting an
unauthenticated request. Nothing was wrong with the estate, the code or the ref.
A public host said "not now" and the playbook had no answer.

Not one `git` clone in the repository had a retry. Meanwhile the Galaxy install
has carried a 6× retry loop for the same class of transient since the macOS
runner started 504-ing, and CLAUDE.md records it. The lesson existed and had
been applied to exactly one surface — the same shape as the BONE_API_URL port,
fixed twice while a third occurrence sat unnoticed.

THE DELAY MATTERS AS MUCH AS THE RETRY, which is why it is checked. A rate limit
is a COOLDOWN, not a blip: five retries at five seconds spend five more tokens
of the same exhausted bucket and fail identically, just faster. The floor below
matches the delay to the kind of transient a public git host actually produces.

WHAT THIS DOES NOT DO. It does not make a bad ref survive — `until: … is
succeeded` respects the module's own failure signal, so an unfetchable ref still
ends the run, five retries later. Retrying is for the network, not for the
truth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

# Vendored upstream roles are excluded: they are not ours to edit, and the
# playbook uses the pazny.* forks. `requirements.yml` still lists
# geerlingguy.dotfiles, but main.yml imports pazny.dotfiles.
VENDORED = ("geerlingguy.",)

# Seconds. Below this, a retry against a rate-limited host is a faster failure
# rather than a recovery.
MIN_DELAY = 20
MIN_RETRIES = 3


def _task_files() -> list[Path]:
    out: list[Path] = []
    for base in ("roles", "tasks"):
        for p in (REPO / base).rglob("*.yml"):
            if any(v in str(p) for v in VENDORED):
                continue
            out.append(p)
    return sorted(out)


def _clone_tasks() -> list[tuple[Path, dict]]:
    """Every task using the git module, in a file that parses as a task list."""
    found: list[tuple[Path, dict]] = []
    for path in _task_files():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, list):
            continue
        for task in doc:
            if not isinstance(task, dict):
                continue
            if "git" in task or "ansible.builtin.git" in task:
                found.append((path, task))
    return found


def test_there_are_clone_tasks_to_check():
    """Positive control — a rename of the module would silently empty this gate."""
    assert _clone_tasks(), (
        "no git-module tasks found at all. Either every clone moved to a shell "
        "command (in which case this gate is blind to them) or the discovery "
        "pattern has rotted."
    )


@pytest.mark.parametrize(
    "path,task",
    _clone_tasks(),
    ids=[f"{p.parts[-3]}:{t.get('name', '?')[:40]}" for p, t in _clone_tasks()],
)
def test_every_clone_retries(path, task):
    name = task.get("name", "<unnamed>")
    assert "retries" in task, (
        f"{path.relative_to(REPO)} → {name!r} clones without a retry. A public "
        f"git host answering 429 or dropping a connection then ends the entire "
        f"converge; on 2026-08-05 that happened at task 605 of an hour."
    )
    assert "until" in task, (
        f"{name!r} sets `retries` without `until`. Ansible ignores retries "
        f"unless there is an until condition — the task reads as protected and "
        f"is not, which is worse than being plainly unprotected."
    )
    assert int(task["retries"]) >= MIN_RETRIES, (
        f"{name!r} retries {task['retries']}× — too few to ride out a host "
        f"having a bad minute."
    )
    delay = int(task.get("delay", 0))
    assert delay >= MIN_DELAY, (
        f"{name!r} retries after {delay}s. A rate limit is a cooldown, not a "
        f"blip: retrying that fast spends another token of the same exhausted "
        f"bucket and fails identically, just sooner. Use {MIN_DELAY}s or more."
    )


@pytest.mark.parametrize(
    "path,task",
    _clone_tasks(),
    ids=[f"{p.parts[-3]}:{t.get('name', '?')[:40]}" for p, t in _clone_tasks()],
)
def test_a_retry_never_swallows_a_real_failure(path, task):
    """`until` must test success, not merely "we tried".

    `until: true` or a condition that ignores the result turns a retry loop into
    a way to pass a broken clone — which is the retry version of a success
    marker written by the attempting code.
    """
    until = str(task.get("until", ""))
    assert re.search(r"is\s+succeeded|rc\s*==\s*0|is\s+not\s+failed", until), (
        f"{task.get('name')!r} has `until: {until}` — that does not test whether "
        f"the clone actually worked. A loop that exits on anything but success "
        f"launders a failure into a pass."
    )
