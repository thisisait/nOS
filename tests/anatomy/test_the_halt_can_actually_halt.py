"""A stop that nothing performs is worse than no stop at all.

THE STATE OF THIS BEFORE 2026-08-06. Three places announced that a
removal-shaped disagreement stops the organ's mirror pass:

  * `cortex-corpus-diff.py` printed "The cortex organ's fs-sync is stopped"
  * `weaknesses.py` raised a CRITICAL titled "the organ's fs-sync was stopped"
  * `cortex-base/plugin.yml` called fs-sync "the job §5.3's --halt-cmd disables"

The mechanism all three named was `--halt-cmd`, whose value came from
`CORTEX_DIFF_HALT_CMD`. That name occurred EXACTLY ONCE in the repository —
in its own default. The production job passed neither the env nor the flag,
and `cortex-fs-sync.py` read no file, so there was no second path either. The
halt had never once been able to fire, and `state["halted"] = True` was set
regardless: a marker written by code that did not attempt the thing.

Removals are the only irreversible direction in the corpus. This is the one
stop the harness has, so it is the one that must not be decorative.

WHAT MAKES IT REAL NOW: the flag the harness already writes is the halt.
`cortex-fs-sync` reads `halted` from the night ledger and refuses its pass
with exit 4. One fact, one place, one reader — and `--no-ledger` still cannot
halt anything, which is what keeps the diff usable as a judge
(`state/judge-sets.yml`, DECISION 2e).

The behavioural test below is the one that matters: it sets the flag and
watches the script refuse. It fails against the pre-fix script, which walked.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FS_SYNC = REPO / "files/anatomy/scripts/cortex-fs-sync.py"
DIFF = REPO / "files/anatomy/scripts/cortex-corpus-diff.py"
WEAKNESSES = REPO / "files/anatomy/bone/weaknesses.py"


def _argparse_default(source: str, flag: str) -> str | None:
    """The unparsed default expression of an argparse flag, or None."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", "") != "add_argument":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != flag:
            continue
        for kw in node.keywords:
            if kw.arg == "default":
                return ast.unparse(kw.value)
    return None


def test_the_halt_is_obeyed_by_the_job_it_claims_to_stop(tmp_path):
    """Set the flag; the pass must refuse.

    No token check can be skipped and no network is reachable in this test, so
    a script that walked past the halt would fail on the POST with exit 2 (the
    organ unreachable) — a different number from the 4 that means "I refused".
    That distinction is the whole assertion.
    """
    ledger = tmp_path / "cortex-corpus-diff.json"
    ledger.write_text(json.dumps({"version": 2, "nights": [], "halted": True}), encoding="utf-8")

    env = dict(os.environ)
    env.update({
        "CORTEX_DIFF_STATE": str(ledger),
        "CORTEX_AGENT_TOKEN_RW": "fixture-not-a-real-token",
        # Unreachable on purpose: if the halt is ignored, the script gets here.
        "CORTEX_API_URL": "http://127.0.0.1:1",
        "NOS_NOTIFY_BIN": "",
    })
    proc = subprocess.run([sys.executable, str(FS_SYNC)], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 4, (
        f"cortex-fs-sync exited {proc.returncode} with a HALTED ledger — the "
        f"harness's one irreversible-direction stop does not stop it.\n"
        f"stderr: {proc.stderr.strip()[:400]}"
    )
    assert "HALT" in proc.stderr.upper(), "it refused without saying why"


def test_an_unhalted_ledger_does_not_refuse(tmp_path):
    """Positive control: the guard must not be the reason every pass fails.

    A test that only ever proves "it stops" would pass just as well against a
    script that stopped unconditionally.
    """
    ledger = tmp_path / "cortex-corpus-diff.json"
    ledger.write_text(json.dumps({"version": 2, "nights": [], "halted": False}), encoding="utf-8")

    env = dict(os.environ)
    env.update({
        "CORTEX_DIFF_STATE": str(ledger),
        "CORTEX_AGENT_TOKEN_RW": "fixture-not-a-real-token",
        "CORTEX_API_URL": "http://127.0.0.1:1",
        "NOS_NOTIFY_BIN": "",
    })
    proc = subprocess.run([sys.executable, str(FS_SYNC)], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 4, (
        "cortex-fs-sync refuses with no halt recorded — the guard fires on the "
        "wrong condition, and the mirror would freeze on an ordinary night"
    )


def test_a_missing_ledger_is_not_a_halt(tmp_path):
    """The flag's ABSENCE is the estate's normal state — it has never been set.

    Reading an unreadable file as "stopped" would take the mirror down on the
    first disk hiccup, which is a bigger outage than the case it guards.
    """
    env = dict(os.environ)
    env.update({
        "CORTEX_DIFF_STATE": str(tmp_path / "does-not-exist.json"),
        "CORTEX_AGENT_TOKEN_RW": "fixture-not-a-real-token",
        "CORTEX_API_URL": "http://127.0.0.1:1",
        "NOS_NOTIFY_BIN": "",
    })
    proc = subprocess.run([sys.executable, str(FS_SYNC)], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode != 4, "a missing ledger reads as a halt"


def test_the_writer_and_the_reader_name_the_same_file():
    """Two copies of a path is how a halt quietly stops being read.

    The writer would flag one file, the reader would check another, and both
    would look correct in review. Nothing else compares these two lines.
    """
    writer = _argparse_default(DIFF.read_text(encoding="utf-8"), "--state")
    assert writer, "cortex-corpus-diff no longer declares a --state default"

    reader_src = FS_SYNC.read_text(encoding="utf-8")
    tree = ast.parse(reader_src)
    reader = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "LEDGER" for t in node.targets
        ):
            reader = ast.unparse(node.value)
    assert reader, "cortex-fs-sync no longer binds LEDGER — the halt has no reader"

    # Compared as UNPARSED SOURCE, not as fragments: `ast.unparse` normalises
    # quoting and spacing, so this is a structural comparison of the two
    # expressions rather than a substring hunt that a reformat could fool.
    # The reader wraps the writer's expression in Path(...) and is otherwise
    # identical — anything else is drift.
    assert reader == f"Path({writer})", (
        f"the ledger path defaults have drifted apart:\n"
        f"  writer (cortex-corpus-diff --state): {writer}\n"
        f"  reader (cortex-fs-sync LEDGER):      {reader}\n"
        f"Expected the reader to be exactly Path(<the writer's default>)."
    )


def test_there_is_one_blessed_way_out():
    """Nothing clears the flag by itself — that is the point. So the way back
    has to exist and has to be NAMED where the operator reads the alarm."""
    diff_src = DIFF.read_text(encoding="utf-8")
    assert _argparse_default(diff_src, "--clear-halt") is None and "--clear-halt" in diff_src, (
        "cortex-corpus-diff has no --clear-halt: a halt would be permanent and "
        "the operator would be left editing JSON by hand"
    )

    halt_notice = diff_src[diff_src.find('"S2 diff: HALT'):]
    halt_notice = halt_notice[:600]
    assert "--clear-halt" in halt_notice, (
        "the halt notification does not tell the operator how to lift it"
    )

    fs_src = FS_SYNC.read_text(encoding="utf-8")
    assert "--clear-halt" in fs_src, (
        "the refusing job does not name the way out either"
    )


def test_no_place_claims_the_stop_in_the_past_tense():
    """`weaknesses.py` said "was stopped" while nothing had stopped.

    The tense is the claim: a past-tense report asserts a completed act, and
    that act is what did not happen. The present tense ("is refusing") is true
    of every pass while the flag stands, and it is falsifiable — the gate above
    falsifies it.
    """
    src = WEAKNESSES.read_text(encoding="utf-8")
    block = src[src.find('weakness_id="corpus:halted"'):]
    block = block[:600]
    assert "fs-sync was stopped" not in block, (
        "weaknesses.py still reports the halt as a completed act"
    )
    assert "title=" in block, "the corpus:halted weakness lost its title"
