"""The operator's own tool must not be reinstallable by a runtime migration.

MEASURED 2026-08-04, from a live symptom: the operator's interactive Claude
Code session died several times a day with

    Couldn't restart the background service — spawn background service:
    EACCES: permission denied, posix_spawn
    '…/.nvm/versions/node/v24.18.0/…/@anthropic-ai/claude-code/…'

The chain, in the order it was found:

  * `node_nvm_version` is `lts/*`. Every converge runs `nvm install lts/*` and
    `nvm alias default lts/*`, so a new upstream LTS silently creates a node
    tree under the operator. Six had accumulated; the newest was created at
    19:16 DURING that day's converge.
  * `tasks/node.yml` re-pointed `{{ homebrew_prefix }}/bin/claude` at whatever
    `nvm use default` then resolved — so the bridge FOLLOWED the float.
  * Five claude-code installs existed, 211–270 MB each, one per node version,
    each running its own auto-updater. Two were rewritten on the same day, 35
    minutes apart.
  * The live session executes an absolute path (`CLAUDE_CODE_EXECPATH`). When
    an updater rewrote THAT binary underneath it, a spawn landing before the
    final chmod got EACCES.

WHAT THIS GATE HOLDS. Not "the bug is fixed" — the fix is that the CLI is a
native build outside NVM. This holds the SHAPE that made it possible: no task
may point the launchd PATH-bridge at a path inside the NVM tree. That is the
one line whose reintroduction would rebuild the whole chain, and it would look
perfectly reasonable while doing it — the original was written to solve a real
launchd PATH failure and was correct about everything except the target.

Run this against the tree as it stood before 2026-08-04 and it fails on
`tasks/node.yml`'s `Symlink claude into homebrew_prefix/bin`.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks"
CLAUDE_CLI = TASKS / "claude-cli.yml"


def _tasks_in(path: Path):
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError:
        return []
    return [t for t in loaded if isinstance(t, dict)]


def _bridge_targets():
    """Every task that writes a `claude` symlink, with the src it points at."""
    found = []
    for task_file in sorted(TASKS.glob("*.yml")):
        for task in _tasks_in(task_file):
            spec = task.get("ansible.builtin.file") or task.get("file")
            if not isinstance(spec, dict) or spec.get("state") != "link":
                continue
            dest = str(spec.get("dest", ""))
            if not dest.endswith("/claude"):
                continue
            found.append((task_file.name, task.get("name", "<unnamed>"),
                          str(spec.get("src", ""))))
    return found


def test_the_claude_bridge_exists_at_all():
    """A missing bridge is its own outage — launchd's PATH cannot find claude.

    Without this, every other assertion here is satisfied by deleting the
    bridge, which would silently break `pulse-run-agent.sh` exactly the way it
    broke on 2026-05-07.
    """
    assert _bridge_targets(), (
        "no task links a `claude` binary into the PATH any more. Pulse forks "
        "pulse-run-agent.sh under launchd's minimal PATH, where `command -v "
        "claude` fails and the runner exits rc=2 before any Wing event lands."
    )


def test_no_bridge_points_into_the_nvm_tree():
    """The defect itself, as the thing that must stay false."""
    offenders = [
        (f, n, src) for f, n, src in _bridge_targets()
        if ".nvm" in src or "node_modules" in src or "_claude_path" in src
    ]
    assert not offenders, (
        "these tasks point the claude PATH-bridge back inside NVM:\n  "
        + "\n  ".join(f"{f}: {n} → {src}" for f, n, src in offenders)
        + "\nWith `node_nvm_version: lts/*` that target MOVES on every "
        "converge, giving each node version its own claude-code install and "
        "its own auto-updater. One of those rewrote the 270 MB binary a live "
        "session was executing, and the session died with EACCES."
    )


def test_the_native_install_is_what_gets_bridged():
    """Positive half: the bridge has to point somewhere node cannot reach."""
    srcs = [src for _, _, src in _bridge_targets()]
    assert any(".local/bin" in s or "_claude_native_bin" in s for s in srcs), (
        f"the claude bridge points at {srcs!r}, none of which is the native "
        f"build outside NVM. tasks/claude-cli.yml installs it there precisely "
        f"so a Node runtime migration cannot reinstall the operator's tool."
    )


def test_pruning_the_duplicates_is_opt_in_and_refuses_while_in_use():
    """Deleting a copy a live session holds turns EACCES into ENOENT.

    macOS keeps the inode of a running executable, so the process survives —
    but the next background-service spawn resolves the PATH and finds nothing.
    Same crash, worse diagnosis. The removal must therefore be both opt-in and
    guarded on nothing running.
    """
    text = CLAUDE_CLI.read_text(encoding="utf-8")
    removal = [t for t in _tasks_in(CLAUDE_CLI)
               if (t.get("ansible.builtin.file") or {}).get("state") == "absent"]
    assert removal, "the duplicate-copy cleanup task is gone"

    conditions = " ".join(str(c) for t in removal for c in
                          (t.get("when") if isinstance(t.get("when"), list) else [t.get("when")]))
    assert "claude_cli_prune_nvm_copies" in conditions, (
        "the cleanup removes copies without an explicit opt-in var"
    )
    assert "_claude_running" in conditions, (
        "the cleanup does not check whether a claude process is holding a copy"
    )
    assert re.search(r"claude_cli_prune_nvm_copies\s*\|\s*default\(false\)", text), (
        "the prune flag must default to FALSE — a destructive default here "
        "deletes the operator's running tool during an ordinary converge"
    )
