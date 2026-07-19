"""Uninstall contract — pins the destructive-op-safety invariants of the
`uninstall` path (tasks/uninstall.yml + main.yml wiring).

Uninstall is the OPPOSITE of blank: blank resets DERIVED state and PRESERVES the
user SOURCE (nos_data_root/tenants) then reinstalls; uninstall removes the source
too and STOPS. Because it deletes user files, it MUST be dry-run-by-default and
gated behind an explicit confirm — this test guards exactly that so a refactor
can't silently turn it into a no-confirm "delete button".
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
UNINSTALL = ROOT / "tasks" / "uninstall.yml"
MAIN = ROOT / "main.yml"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_uninstall_task_file_exists_and_parses():
    assert UNINSTALL.is_file(), "tasks/uninstall.yml is missing"
    tasks = yaml.safe_load(_text(UNINSTALL))
    assert isinstance(tasks, list) and tasks, "uninstall.yml must be a non-empty task list"


def test_uninstall_removes_the_source_tree():
    """The whole point: uninstall removes nos_data_root (source) — blank never does."""
    txt = _text(UNINSTALL)
    assert "nos_data_root" in txt, "uninstall must target nos_data_root (the user source tree)"
    # And the ~/.nos runtime side-car.
    assert "/.nos" in txt or "bone_state_dir" in txt, "uninstall must remove the ~/.nos side-car"
    # blank-reset must NOT remove the whole source tree (that's the blank≠uninstall split).
    blank = _text(ROOT / "tasks" / "blank-reset.yml")
    assert not re.search(
        r"state:\s*absent[\s\S]{0,200}\{\{\s*nos_data_root\s*\}\}\s*$",
        blank,
        re.MULTILINE,
    ), "blank must PRESERVE nos_data_root (source) — only uninstall removes it"


def test_uninstall_is_dry_run_by_default():
    """The removal (file: state=absent + the blank import) must be gated on
    confirm_uninstall, so a bare `-e uninstall=true` only reports."""
    tasks = yaml.safe_load(_text(UNINSTALL))
    # Find the execute block.
    exec_blocks = [t for t in tasks if isinstance(t, dict) and "block" in t]
    assert exec_blocks, "uninstall.yml must wrap its destructive work in a block"
    gated = [
        b
        for b in exec_blocks
        if "confirm_uninstall" in str(b.get("when", ""))
    ]
    assert gated, "the destructive block must be gated on `when: confirm_uninstall`"
    # The source-removal `file: state=absent` must live INSIDE a confirm-gated block,
    # never at top level.
    for t in tasks:
        if isinstance(t, dict) and t.get("file", {}).get("state") == "absent":
            raise AssertionError(
                "a top-level `file: state=absent` in uninstall.yml is not confirm-gated"
            )


def test_uninstall_reuses_blank_teardown():
    """DRY: uninstall imports the blank teardown rather than duplicating it."""
    txt = _text(UNINSTALL)
    assert "tasks/blank-reset.yml" in txt, "uninstall should import the blank teardown (DRY)"


def test_main_wires_uninstall_with_end_play():
    """main.yml must run uninstall AND end_play (no reinstall), both gated on uninstall."""
    txt = _text(MAIN)
    assert "tasks/uninstall.yml" in txt, "main.yml must import tasks/uninstall.yml"
    assert "end_play" in txt, "main.yml must end_play after uninstall (no reinstall)"
    # The end_play must be conditioned on `uninstall` so a normal run isn't cut short.
    m = re.search(r"meta:\s*end_play\s*\n\s*when:\s*uninstall", txt)
    assert m, "meta: end_play must be `when: uninstall | default(false)`"
