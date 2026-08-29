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
    # `set-option` is the ONE exception, and it is tmux's, not ours: it resolves
    # `-t` as a PANE and rejects `=name` outright. Anchoring it produced
    # `no such session: =nos-cc` four times into a stderr nobody read, and the
    # status bar was silently never set. The exception is safe on its own terms
    # — a prefix match there writes a status bar, which closing the session
    # undoes; the anchored commands are the ones where a prefix match costs
    # someone their work.
    set_option_targets = set(re.findall(r'set-option\s+-t\s+"([^"]+)"', code))
    unanchored = [
        t for t in targets
        # `$SESSION:window` forms address a window INSIDE the session and are
        # already scoped by it; only bare session targets need the anchor.
        if not t.startswith("=") and ":" not in t and t not in set_option_targets
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


def test_ops_leaves_a_free_prompt_and_starts_no_agent():
    """The ops window carries TWO shells: one the operator drives an agent
    session in (claude / hermes / opencode), one for the ordinary shell work
    that watching produces. Neither may be started FOR them.

    This is the same rule as the converge window, applied where it is easiest to
    break: a pane that launches an agent is a pane that keeps one alive, and a
    persistent agent is a runaway with a nicer name. What persists here is the
    VIEW of agent runs (`tools/agent-status.py`), never a run itself."""
    code = _code(CC)
    typed_into = set(re.findall(r'send-keys\s+-t\s+"\$SESSION:ops\.(\d+)"', code))
    assert typed_into, "no ops pane is addressed by index — this gate stopped seeing them"
    # ops.5 since 2026-08-29: the `awaiting you` reader took an index and the
    # free prompts moved down. ops.4 IS typed into — one line that prints
    # elsewhere-status and clears — so the LAST index is the free one.
    assert "5" not in typed_into, (
        "ops.5 is typed into. It is the free prompt the operator starts their "
        "own agent session in; a setup script that fills it has taken the "
        "decision away from them."
    )
    for launcher in ("claude", "hermes", "opencode"):
        assert not re.search(rf"send-keys[^\n]*\b{launcher}\b", code), (
            f"the layout types `{launcher}` into a pane. No pane here starts an "
            "agent — agent runs are bounded on purpose, and a pane that keeps "
            "one alive defeats the bound."
        )


def test_every_reader_pane_is_a_reader_not_a_one_shot():
    """A pane that runs its command once shows an answer that ages silently —
    the scrollback lie wearing a different hat. Every INFORMATIVE pane re-reads;
    the shells are the exception, and they are exceptions because they are
    prompts, not answers.

    TWO MECHANISMS SINCE 2026-08-29, and the gate must accept both or it pins
    the implementation rather than the rule. `nos-watch.sh --interval N` re-runs
    a plain command; `tools/nos-pane.py <id>` is a TUI whose pane declares
    REFRESH and re-reads on a timer. The first version of that TUI read once
    and sat there — this assertion is what caught it, so the interval half is
    checked at the pane modules, not taken on the launcher's word.
    """
    code = _code(CC)
    watched = re.findall(r"\$W --interval (\d+)", code)
    panes = re.findall(r"tools/nos-pane\.py (\w+)", code)
    assert len(watched) + len(panes) >= 3, (
        f"only {len(watched) + len(panes)} pane(s) re-read; the ops window "
        "alone should carry red, agents and the history glance."
    )
    assert all(int(i) > 0 for i in watched), "a reader interval is not positive"

    if panes:
        import sys
        sys.path.insert(0, str(REPO / "tools"))
        from cc import panes as registry
        from cc.app import ControlCentreApp

        known = registry.all_panes()
        for pane_id in panes:
            assert pane_id in known, f"nos-cc.sh opens `{pane_id}`, which no module declares"
            secs = getattr(known[pane_id], "REFRESH", ControlCentreApp.DEFAULT_REFRESH)
            assert isinstance(secs, (int, float)) and secs > 0, (
                f"pane `{pane_id}` has no positive REFRESH, so it reads once and "
                "then shows an answer that ages silently"
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
    import shutil
    import tempfile

    if subprocess.run(["which", "tmux"], capture_output=True).returncode != 0:
        import pytest

        pytest.skip("tmux not installed")

    # A PRIVATE TMUX SERVER, via TMUX_TMPDIR (2026-08-23). Until today this
    # test built its throwaway session on the OPERATOR'S live tmux server: a
    # test whose actions are visible in the environment it is testing, and
    # whose result depends on it. It was careful — anchored targets, kills only
    # its own session — and careful is not the same as isolated. Isolation is
    # structural; carefulness is a promise re-made on every edit.
    #
    # The default-socket `tmux ls` before/after check is KEPT below, and with
    # this isolation it should be trivially unchanged. That is the point: it
    # now proves the isolation rather than the carefulness.
    # SHORT PATH, deliberately: a unix socket path is capped near 104 bytes and
    # pytest's tmp_path on macOS (/private/var/folders/wm/…/pytest-N/…) blows
    # past it — the first cut of this isolation failed with `error connecting
    # to …`, which reads like a tmux fault and is a path-length one.
    tmux_tmpdir = tempfile.mkdtemp(prefix="nosccT", dir="/tmp")
    env = dict(os.environ, NOS_CC_SESSION="nos-cc-selftest",
               TMUX_TMPDIR=tmux_tmpdir)
    iso = ["tmux", "-L", "default"]          # resolved inside TMUX_TMPDIR
    before = subprocess.run(["tmux", "ls"], capture_output=True, text=True).stdout

    try:
        built = subprocess.run(
            ["bash", str(CC), "--no-attach"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert built.returncode == 0, built.stderr[-500:]

        windows = subprocess.run(
            [*iso, "list-windows", "-t", "=nos-cc-selftest", "-F", "#{window_name}"],
            capture_output=True, text=True, env=env,
        ).stdout.split()
        assert "ops" in windows, f"no ops window; got {windows}"

        # The layout ACTUALLY built, not the one the code reads like. tmux
        # renumbers panes by position on every split, so a send-keys interleaved
        # between splits lands somewhere else entirely — a mistake that is
        # invisible in a diff and obvious on screen.
        panes = subprocess.run(
            [*iso, "list-panes", "-t", "=nos-cc-selftest:ops",
             "-F", "#{pane_index} #{pane_top}"],
            capture_output=True, text=True, env=env,
        ).stdout.split("\n")
        panes = [p for p in panes if p.strip()]
        assert len(panes) == 6, (
            f"ops has {len(panes)} pane(s), expected 6 — four readers above "
            f"two free shells; got {panes}\n"
            f"script stderr: {built.stderr[-600:]!r}\n"
            "(the script now exits 3 on a refused split and says which one; if "
            "this stderr is empty the splits SUCCEEDED and the panes went "
            "somewhere else)"
        )
        tops = [int(p.split()[1]) for p in panes]
        assert len(set(tops)) >= 2, (
            f"every ops pane starts at the same row, so nothing is stacked "
            f"above anything; got tops={tops}"
        )

        # Running it again must attach/report, never rebuild.
        again = subprocess.run(
            ["bash", str(CC), "--no-attach"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert "already exists" in again.stdout, (
            "a second run did not detect the existing session — it would "
            "rebuild over live panes"
        )
        # THE BAR MUST ACTUALLY BE SET. It was not, for the first version of
        # this script, because tmux refused the target and the script did not
        # look. A layout test that never reads back an option cannot see that.
        bar = subprocess.run(
            [*iso, "show-options", "-t", "nos-cc-selftest", "status-right"],
            capture_output=True, text=True, env=env,
        ).stdout
        assert "nos-statusline.sh" in bar, (
            f"the session's status-right does not call the reader; got {bar!r}. "
            "tmux reports a rejected target on stderr and exits non-zero — if "
            "the script does not check, the bar is silently absent."
        )
    finally:
        # Kill the whole private SERVER, not just the session: an orphaned
        # tmux server on a stale socket is what /tmp/nosccrev-46472.sock has
        # been since 2026-08-18, five days and still running.
        subprocess.run([*iso, "kill-server"], capture_output=True, env=env)
        shutil.rmtree(tmux_tmpdir, ignore_errors=True)

    after = subprocess.run(["tmux", "ls"], capture_output=True, text=True).stdout
    before_names = {l.split(":")[0] for l in before.splitlines() if l.strip()}
    after_names = {l.split(":")[0] for l in after.splitlines() if l.strip()}
    assert before_names <= after_names, (
        f"sessions disappeared while building the control centre: "
        f"{sorted(before_names - after_names)}"
    )
