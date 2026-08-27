"""`brew-pin-status.py` and `snapshot-status.py` report, and can never act.

WHY THIS IS A GATE, and why it is a different temptation for each of the two.

`tools/brew-pin-status.py` exists because the ollama pin guard fired three
times and every time the record followed brew after a failed converge — the
last one adopting a formula that had been out for **one day**. The tool answers
"is this version old enough to adopt". The obvious next thought is "and if it
is, it may as well `brew upgrade`" — which would make the reader the thing that
performs the adoption it is meant to advise on, and hand the estate the same
shape it is trying to leave: nobody deciding, something upgrading.

`tools/snapshot-status.py` exists because nothing said whether a net was under
the next converge. Its temptation is sharper: to answer "can this host take a
snapshot" by TAKING one. That is a side effect a reader may not have, and it
would leave real snapshots behind on a machine whose Time Machine has no
destination — probing a capability by exercising it. It must probe with
`tmutil destinationinfo` and report, including reporting UNKNOWN.

The shared third rule is the estate's oldest: **an unreadable source is
UNKNOWN, never green.** `docs/hidden_fees/08` is what that costs — a STRICT
health probe passing an empty stack as `0/0 ready`, for weeks. Both tools have
a three-state verdict (`None` for unreadable) and neither may collapse it to a
boolean, which is why `snapshottable` is `True | False | None` and not a flag.

WHAT IS PINNED. No mutating brew, tmutil, diskutil or git verb. No filesystem
write. Exit 0 on every path. UNKNOWN survives as a distinct state in both.

WHAT IT CANNOT SEE. Whether the readings are CORRECT — whether homebrew-core's
history really dates a version, whether diskutil named the filesystem right.
That is the network's and the OS's business. This checks only that asking never
becomes doing.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
READERS = {
    "brew": REPO / "tools/brew-pin-status.py",
    "snapshot": REPO / "tools/snapshot-status.py",
}

#: Verbs that CHANGE something, per tool family. Matched against the argv
#: literals the source builds, never against prose — a comment naming
#: `brew upgrade` as the thing avoided must not fail the gate that avoids it.
FORBIDDEN = {
    "brew": {"install", "upgrade", "uninstall", "reinstall", "pin", "unpin",
             "untap", "tap", "cleanup"},
    "tmutil": {"localsnapshot", "snapshot", "deletelocalsnapshots", "restore",
               "setdestination", "enable", "disable", "startbackup"},
    "diskutil": {"eraseVolume", "apfs", "unmount", "mount", "repairVolume"},
    "git": {"commit", "push", "add", "checkout", "reset"},
}

WRITE_MODES = re.compile(r"""["'](?:w|a|w\+|a\+|r\+|wb|ab)["']""")


def _argv_literals(path: pathlib.Path) -> list[list[str]]:
    """Every list-of-strings literal in the file — the shape a subprocess argv
    takes here. Reading the AST rather than the text is the whole point: this
    tree's most repeated defect is a detector that matches a description."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [e.value for e in node.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if items:
                out.append(items)
    return out


@pytest.mark.parametrize("key", sorted(READERS))
def test_the_reader_runs_no_mutating_command(key):
    path = READERS[key]
    for argv in _argv_literals(path):
        head = argv[0].rsplit("/", 1)[-1]
        forbidden = FORBIDDEN.get(head)
        if not forbidden:
            continue
        bad = sorted(set(argv[1:]) & forbidden)
        assert not bad, (
            f"{path.name} builds `{head} {' '.join(argv[1:])}` — {bad} changes "
            f"state. A reader that acts on what it finds certifies its own work; "
            f"the adoption belongs to a commit and the snapshot to the playbook.")


@pytest.mark.parametrize("key", sorted(READERS))
def test_the_reader_opens_nothing_for_writing(key):
    path = READERS[key]
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            # UNAMBIGUOUS names only. `replace`/`rename`/`chmod` are also str
            # methods — a bare-attribute match fails on
            # `when.replace("Z", "+00:00")`, a timestamp parse, not a file
            # move. Those three are caught below, receiver-qualified.
            if name in ("write_text", "write_bytes", "mkdir", "rmtree", "touch",
                        "unlink"):
                raise AssertionError(
                    f"{path.name} calls {name}() — a reader writes nothing. "
                    "If a record is wanted, a separate writer owns it.")
            recv = getattr(fn, "value", None)
            recv_name = getattr(recv, "id", None)
            if recv_name in ("os", "shutil", "pathlib") and name in (
                    "replace", "rename", "remove", "chmod", "makedirs", "move"):
                raise AssertionError(
                    f"{path.name} calls {recv_name}.{name}() — a reader writes nothing.")
            if name == "open":
                mode = [a for a in node.args[1:2]] or [
                    k.value for k in node.keywords if k.arg == "mode"]
                for m in mode:
                    if isinstance(m, ast.Constant) and WRITE_MODES.match(f'"{m.value}"'):
                        raise AssertionError(
                            f"{path.name} opens a file with mode {m.value!r}")


@pytest.mark.parametrize("key", sorted(READERS))
def test_the_reader_always_exits_zero(key):
    """A reporter that exits non-zero is a gate wearing a reader's name — and
    something downstream will eventually branch on that code."""
    src = READERS[key].read_text(encoding="utf-8")
    codes = set(re.findall(r"return\s+(\d+)\s*$", src, re.M))
    assert codes <= {"0"}, (
        f"{READERS[key].name} has `return {sorted(codes - {'0'})}` at statement "
        "level — every exit path must be 0. Report the finding in the text.")


def test_unknown_is_a_state_not_a_falsey_flag():
    """`snapshottable` must be True | False | None. Collapsing it to a boolean
    is exactly how `docs/hidden_fees/08` read an empty stack as ready: the
    unreadable case and the negative case became the same value."""
    src = READERS["snapshot"].read_text(encoding="utf-8")
    assert 'row["snapshottable"] = None' in src, (
        "the snapshot reader no longer has an UNKNOWN branch for its volume "
        "verdict — an unnamed filesystem would then read as 'not snapshottable', "
        "which is a claim it has not earned")
    assert '{True: "COVERED  ", False: "UNCOVERED", None: "UNKNOWN  "}' in src, (
        "the render collapsed three states into two; UNKNOWN must reach the "
        "operator as its own word")


def test_the_brew_reader_refuses_a_non_version():
    """The comparison must decline rather than guess, the same discipline
    UpgradeRepository::compareVersions carries — a build id like `sha-b9a80dc`
    is not below or above anything."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bps", READERS["brew"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._cmp("latest", "1.2.3") is None
    assert mod._cmp("sha-b9a80dc", "sha-c1f2e3d") is None
    assert mod._cmp("0.32.15", "0.33.0") < 0
    assert mod._cmp("0.33.0", "0.33.0") == 0
    assert mod._cmp("16.15-alpine", "16") > 0


def test_the_exemption_carries_its_reason():
    """A formula deliberately left on `state: latest` must say why, in the
    reader's own output. An exemption nobody can see is a gap."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bps2", READERS["brew"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.EXEMPT, "the exemption table is empty; nginx's REM-134 floor is real"
    for formula, reason in mod.EXEMPT.items():
        assert len(reason) > 40 and ("REM-" in reason or "CVE-" in reason), (
            f"{formula}'s exemption reason does not cite the finding that "
            f"justifies it: {reason!r}")
