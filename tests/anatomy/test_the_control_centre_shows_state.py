"""The terminal control centre shows state, and touches only its own session.

BUILT 2026-08-18, in answer to the first bound ceremony that ever completed.
The surveyor's report named the gap as its primary finding: *"The control centre
does not exist yet — the operator needs a surface to view services, versions,
hosts, queues, jobs and failures."*

TWO PROPERTIES, and both are the kind that read as fine in a diff.

1. A PANE SHOWS STATE, NOT SCROLLBACK. `tail -f` is the obvious way to fill a
   pane and it is the wrong one: a tailed log looks healthy right up until its
   writer stops, and then it looks exactly the same — the last line just stays
   there. That is why this estate ran two days with two failing nightly jobs
   while every surface looked calm. The notifications were delivered, correctly,
   on the first night; a notification is an EVENT and red is a STATE. So every
   pane re-runs a reader through `tools/nos-watch.sh`, which replaces the pane's
   contents and says so when the reader itself fails.

2. IT OWNS ONE SESSION. The operator keeps `nos`, `converge` and `convergence`
   open with live work in them. tmux target matching is a PREFIX match unless
   anchored with `=`, so `kill-session -t nos-cc` would also match `nos-cc-old`
   — and `-t nos` would match all three of the operator's. Every target here is
   anchored. This is the one thing the script could do that is not recoverable.

WHAT THIS GATE DOES NOT DO: check that the layout is pleasant, or that the
readers say anything useful. It checks the two ways this tool could quietly
become harmful — by lying about the estate, or by eating someone's work.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
CC = REPO / "tools/nos-cc.sh"
WATCH = REPO / "tools/nos-watch.sh"
STATUSLINE = REPO / "tools/nos-statusline.sh"
AGENTS = REPO / "tools/agent-status.py"


def _cc() -> str:
    return CC.read_text(encoding="utf-8")


def _code(path: pathlib.Path) -> str:
    """Shell source with comments stripped — the prose explains what the code
    must not do, so a whole-file search fails on the explanation."""
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_pieces_this_gate_describes_exist():
    """Positive control — a renamed script makes every check below vacuous."""
    for path in (CC, WATCH, STATUSLINE, AGENTS):
        assert path.is_file(), f"{path.relative_to(REPO)} is gone"
        assert path.stat().st_mode & 0o111, f"{path.relative_to(REPO)} is not executable"


def test_every_tmux_target_is_anchored():
    """`-t nos-cc` is a PREFIX match. Unanchored, a kill could reach the
    operator's own `nos` session, which is the single unrecoverable act this
    script is capable of."""
    code = _code(CC)
    targets = re.findall(r'-t\s+"([^"]+)"', code)
    assert targets, "no tmux targets found — this gate has stopped seeing them"
    unanchored = [
        t for t in targets
        # `$SESSION:window` forms address a window INSIDE the session and are
        # already scoped by it; only bare session targets need the anchor.
        if not t.startswith("=") and ":" not in t
    ]
    assert not unanchored, (
        f"unanchored tmux session target(s): {unanchored}. tmux matches by "
        "prefix, so `-t nos-cc` can reach `nos-cc-old` and `-t nos` reaches "
        "the operator's own session. Prefix every bare session target with `=`."
    )


def test_it_kills_only_its_own_session_and_only_when_asked():
    code = _code(CC)
    kills = re.findall(r"tmux\s+kill-\S+[^\n]*", code)
    assert len(kills) <= 1, f"more than one kill in a setup script: {kills}"
    if kills:
        assert "kill-session" in kills[0], "this script kills windows or panes"
        assert '"=$SESSION"' in kills[0], "the kill is not anchored to our session"
        assert "REBUILD" in code, "the kill is no longer behind --rebuild"


def test_no_pane_tails_a_log():
    """The whole design. A tail cannot distinguish a quiet writer from a dead
    one; a re-run reader can."""
    code = _code(CC)
    assert not re.search(r"tail\s+-[fF]", code), (
        "a pane tails a log. A tailed log looks identical whether its writer is "
        "idle or dead — which is the exact failure this surface exists to end. "
        "Use tools/nos-watch.sh with a reader."
    )
    assert "nos-watch.sh" in _cc(), "no pane re-runs a reader at all"


def test_the_watcher_says_when_its_reader_failed():
    """Otherwise the pane keeps the last good answer on screen, which is the
    scrollback lie in miniature — a stale truth is worse than a blank."""
    src = WATCH.read_text(encoding="utf-8")
    assert "READER FAILED" in src, (
        "nos-watch.sh no longer marks a failed reader, so a reader that started "
        "erroring leaves its last successful render in place indefinitely."
    )
    assert re.search(r"printf '\\033\[H\\033\[2J'", src), (
        "the pane is no longer cleared between renders, so output accumulates "
        "and the pane becomes the scrollback it was built to replace."
    )


def test_the_converge_is_offered_not_executed():
    """A setup script is not the thing that decides to converge. `send-keys`
    with an empty final argument types the command and does NOT press Enter."""
    code = _code(CC)
    converge = [ln for ln in code.splitlines() if "send-keys" in ln and '"nos"' in ln]
    assert converge, "the converge window no longer offers the command at all"
    assert not any(line.rstrip().endswith("C-m") for line in converge), (
        "the converge command is submitted with C-m. Opening a terminal must "
        "not start a converge."
    )


def test_the_status_bar_cannot_freeze_at_a_comfortable_number():
    """A cached bar fed by a background refresher shows the last good numbers
    forever if the refresher dies — green because nothing is checking, which is
    this estate's signature defect. Self-refresh removes the second process."""
    src = STATUSLINE.read_text(encoding="utf-8")
    assert "TTL" in src and "refresh" in src, (
        "the status line no longer refreshes itself on a TTL"
    )
    assert "'?'" in src or '"?"' in src or "?" in src, "no unknown marker"
    assert "red-status.py" in src, "the bar no longer reads the red state"


def test_the_layout_builds_without_touching_other_sessions():
    """EXERCISED, not grepped. Builds a throwaway session, checks the windows,
    checks idempotence, and checks that the sessions it did not create are still
    there — the property the anchoring is FOR."""
    import os

    if subprocess.run(["which", "tmux"], capture_output=True).returncode != 0:
        import pytest

        pytest.skip("tmux not installed")

    env = dict(os.environ, NOS_CC_SESSION="nos-cc-selftest")
    before = subprocess.run(["tmux", "ls"], capture_output=True, text=True).stdout

    try:
        built = subprocess.run(
            ["bash", str(CC), "--no-attach"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert built.returncode == 0, built.stderr[-500:]

        windows = subprocess.run(
            ["tmux", "list-windows", "-t", "=nos-cc-selftest", "-F", "#{window_name}"],
            capture_output=True, text=True,
        ).stdout.split()
        assert "ops" in windows, f"no ops window; got {windows}"

        # Running it again must attach/report, never rebuild.
        again = subprocess.run(
            ["bash", str(CC), "--no-attach"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert "already exists" in again.stdout, (
            "a second run did not detect the existing session — it would "
            "rebuild over live panes"
        )
    finally:
        subprocess.run(["tmux", "kill-session", "-t", "=nos-cc-selftest"],
                       capture_output=True)

    after = subprocess.run(["tmux", "ls"], capture_output=True, text=True).stdout
    before_names = {l.split(":")[0] for l in before.splitlines() if l.strip()}
    after_names = {l.split(":")[0] for l in after.splitlines() if l.strip()}
    assert before_names <= after_names, (
        f"sessions disappeared while building the control centre: "
        f"{sorted(before_names - after_names)}"
    )
