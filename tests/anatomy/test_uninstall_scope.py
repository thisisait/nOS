"""Removal-ladder scope contract — pins the destructive-op-safety invariants
of the `remove=all` source-removal path (tasks/removal-set.yml +
tasks/remove-source.yml + tasks/run-mode.yml + main.yml wiring).

Successor of the tasks/uninstall.yml pins (file deleted; content redistributed
in the run-mode restructure). Same behavioral claims, new anchors:

- source removal (`nos_data_root`, `~/.nos`, anatomy runtime dirs incl.
  `keap_home`) is inventoried ONCE, in removal-set.yml's `_uninstall_source`;
- a data-level removal (blank) must NEVER remove the source tree;
- removals are DRY-RUN BY DEFAULT: the run-mode `meta: end_play` stop fires
  unless confirm=true (membership idiom on the raw vars — filter-less rule);
- the execute path keeps its interactive pause and the become:true loop.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REMOVAL_SET = ROOT / "tasks" / "removal-set.yml"
REMOVE_SOURCE = ROOT / "tasks" / "remove-source.yml"
RUN_MODE = ROOT / "tasks" / "run-mode.yml"
MAIN = ROOT / "main.yml"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_removal_set_files_exist_and_parse():
    for p in (REMOVAL_SET, REMOVE_SOURCE, RUN_MODE):
        assert p.is_file(), f"{p.name} is missing"
        tasks = yaml.safe_load(_text(p))
        assert isinstance(tasks, list) and tasks, f"{p.name} must be a non-empty task list"


def test_source_set_covers_source_tree_and_anatomy_dirs():
    """The whole point of remove=all: the source tree + anatomy runtime dirs
    are removed — and the list lives in ONE place (removal-set.yml)."""
    txt = _text(REMOVAL_SET)
    assert "_uninstall_source" in txt, "removal-set.yml must own _uninstall_source"
    assert "nos_data_root" in txt, "remove=all must target nos_data_root (the user source tree)"
    assert "bone_state_dir" in txt, "remove=all must remove the ~/.nos side-car"
    for var in ("bone_runtime_dir", "pulse_home", "wing_home", "keap_home",
                "hermes_home", "hermes_config_dir", ".openclaw"):
        assert var in txt, f"remove=all must remove the anatomy runtime dir ({var})"


def test_data_level_never_removes_the_source_tree():
    """blank (remove=data) must PRESERVE nos_data_root — only remove=all's
    `_uninstall_source` may list it wholesale."""
    txt = _text(REMOVAL_SET)
    blank_dirs = re.search(
        r"\n    _blank_dirs:\s*>-\n(?P<body>(?:(?: {6,}.*)?\n)+)", txt
    )
    assert blank_dirs, "could not locate the _blank_dirs set_fact in removal-set.yml"
    body = blank_dirs.group("body")
    # keap's DERIVED data dir default derives from nos_data_root — that is the
    # only sanctioned nos_data_root reference at the data level.
    bare_root_items = re.findall(r"\[\s*nos_data_root\s*\]|\{\{\s*nos_data_root\s*\}\}", body)
    assert not bare_root_items, (
        "_blank_dirs lists nos_data_root wholesale — the data level must "
        "preserve the user source tree (blank≠uninstall split)"
    )
    blank = _text(ROOT / "tasks" / "blank-reset.yml")
    assert not re.search(
        r"state:\s*absent[\s\S]{0,200}\{\{\s*nos_data_root\s*\}\}\s*$",
        blank,
        re.MULTILINE,
    ), "blank must PRESERVE nos_data_root (source) — only remove=all removes it"


def test_removals_are_dry_run_by_default():
    """run-mode.yml must carry the meta: end_play dry-run stop whose when:
    carries BOTH the remove-membership and the not-confirm membership."""
    tasks = yaml.safe_load(_text(RUN_MODE))
    stops = [
        t for t in tasks
        if isinstance(t, dict) and t.get("ansible.builtin.meta") == "end_play"
    ]
    assert stops, "run-mode.yml lost its dry-run meta: end_play stop"
    gated = []
    for t in stops:
        when = t.get("when")
        clauses = when if isinstance(when, list) else [when]
        joined = " && ".join(str(c) for c in clauses)
        if ("remove | default('none') in ['data', 'deep', 'all']" in joined
                and "confirm | default(false) in [true, 'true'" in joined
                and "not (confirm" in joined):
            gated.append(t)
    assert gated, (
        "the dry-run stop must gate on remove-membership AND not-confirm "
        "membership (raw vars, membership idiom — meta: filter-less rule)"
    )


def test_execute_path_keeps_pause_and_become_loop():
    """remove-source.yml: interactive pause (skippable only via assume_yes)
    + the become:true removal loop over _uninstall_source."""
    tasks = yaml.safe_load(_text(REMOVE_SOURCE))
    pauses = [t for t in tasks if isinstance(t, dict) and "ansible.builtin.pause" in t]
    assert pauses, "remove-source.yml lost its final interactive confirmation pause"
    assert any("nos_assume_yes" in str(t.get("when", "")) for t in pauses), (
        "the pause must be gated `when: not nos_assume_yes` (only -y skips it)"
    )
    loops = [
        t for t in tasks
        if isinstance(t, dict)
        and t.get("ansible.builtin.file", {}).get("state") == "absent"
    ]
    assert loops, "remove-source.yml lost the source-removal file:state=absent loop"
    for t in loops:
        assert t.get("loop") == "{{ _uninstall_source }}", (
            "the removal loop must consume removal-set.yml's _uninstall_source"
        )
        assert t.get("become") is True, "source removal must escalate (become: true)"


def test_main_wires_remove_source_and_leave_end_play():
    """main.yml: remove-source import gated on nos_remove_source; the leave
    end_play sits after it (no reconverge under leave=true / legacy uninstall)."""
    txt = _text(MAIN)
    assert "tasks/remove-source.yml" in txt, "main.yml must import tasks/remove-source.yml"
    assert "tasks/uninstall.yml" not in txt, (
        "tasks/uninstall.yml was deleted — main.yml must not reference it"
    )
    m = re.search(
        r"import_tasks: tasks/remove-source\.yml\s*\n\s*when:\s*nos_remove_source", txt
    )
    assert m, "remove-source import must be `when: nos_remove_source`"
    leave = re.search(
        r"meta:\s*end_play\s*\n\s*when:\s*leave \| default\(false\) in \[true", txt
    )
    assert leave, "main.yml must end_play on leave=true (membership idiom on the raw var)"
    assert txt.index("tasks/remove-source.yml") < leave.start(), (
        "the leave end_play must sit AFTER the source-removal import"
    )
