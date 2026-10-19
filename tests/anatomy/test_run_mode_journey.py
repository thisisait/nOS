"""One journey through the removal ladder: run-mode.yml, removal-set, removal-verify, main.yml wiring.

Replaces six files that each carried its own copy of the harness (2026-10-19,
roadmap test-suite-diet). Every invariant they asserted is a named check in
CHECKS below; the journey runs ALL of them and names every one that fails.
Harness plays run once each, concurrently, gathering only the fact subsets the
layers read (env, user, platform, distribution); env-only fails _blank_dirs.

Carried over (old file -> check names):
  test_compat_shim_mapping     -> shim_*            (G-2, R7, F9, M4)
  test_run_mode_allowlist      -> allowlist_*, tuple_*, tags_removal_fails_R4,
                                  bare_leave_fails, derivation_is_filterless (G-1)
  test_removal_verify_closes_survivors -> verify_*  (G-4)
  test_uninstall_scope         -> scope_*
  test_a_removal_dry_run_needs_no_sudo -> dry_run_*
  test_a_yes_removal_asks_for_sudo_first -> sudo_*  (D4)

Harness notes kept from the originals:
- mapped shim rows force confirm=false, so they stop at the R9 end_play; their
  evidence is what prints BEFORE the stop (the notice and the REMOVE banner),
  and the absence of the trailing TUPLE proves the stop fired.
- removal rows pass confirm=true: unconfirmed they end_play inside the import.
  Safe: run-mode.yml holds asserts, stats, debug and end_play only.
- the `"none "` allowlist row is unreachable (parse_kv strips it); G-5 owns it.
- the harness imports {REPO}/tasks/run-mode.yml by absolute path; its nested
  import must stay sibling-relative or every row parse-fails.
- removal-verify plays run with HOME=<tmp>: the expected-absent set appends
  $HOME/projects/default/service-registry.json and $HOME/.nos/secrets.yml, which
  exist on a live dev box.
- ansible.cfg's yaml callback line-wraps: outputs are whitespace-collapsed.
"""
from __future__ import annotations

import os
import re
import stat as statmod
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

RUN_MODE = REPO / "tasks" / "run-mode.yml"
REMOVAL_SET = REPO / "tasks" / "removal-set.yml"
REMOVE_SOURCE = REPO / "tasks" / "remove-source.yml"
MAIN = REPO / "main.yml"
FACTS = "gather_facts: true\n  gather_subset: ['!all', '!min', 'env', 'user', 'platform', 'distribution']"

RUN_MODE_HARNESS = """\
- hosts: localhost
  connection: local
  {facts}
  vars_files:
{layers}
  tasks:
    - import_tasks: {repo}/tasks/run-mode.yml
    # blank via | bool: an explicit -e blank=<x> OUTRANKS the derived fact, and
    # every legacy read site is `blank | bool`.
    - debug:
        msg: "TUPLE {{{{ [nos_removing, nos_remove_data, nos_remove_deep, nos_remove_source, blank | bool, _flush_deep | bool] | string }}}}"
"""

VERIFY_HARNESS = """\
- hosts: localhost
  connection: local
  {facts}
  vars:
    remove: data
    docker_bin: {stub}
    nos_remove_deep: false
    nos_remove_source: false
    _blank_dirs: {dirs!r}
    _uninstall_source: []
  tasks:
    - import_tasks: {repo}/tasks/removal-verify.yml
"""

MAPPED_ROWS = [  # extra_vars -> (remove, leave) the shim must print
    ({"blank": "true"}, ("data", "False")),
    ({"blank": "yes"}, ("data", "False")),   # |bool parity
    ({"flush": "true"}, ("data", "False")),
    ({"flush": "deep"}, ("deep", "False")),
    ({"uninstall": "true"}, ("all", "True")),
    ({"uninstall": "true", "confirm_uninstall": "true"}, ("all", "True")),
]
FALSE_ROWS = [{"blank": "false"}, {"flush": "false"}, {"uninstall": "false"}]  # R7
ALL_FALSE_TUPLE = "TUPLE [False, False, False, False, False, False]"
OFF_ALLOWLIST = ["DATA", "All", "", "garbage", "deep,all"]
VALID_LEVELS = [
    ("none", "false", [False, False, False, False, False, False]),
    ("data", "true", [True, True, False, False, True, False]),
    ("deep", "true", [True, True, True, False, True, True]),
    ("all", "true", [True, True, True, True, True, True]),
]


def _cmd(pb: Path, extra: dict, args=()) -> list[str]:
    cmd = ["ansible-playbook", str(pb), "-i", "localhost,"]
    for k, v in extra.items():
        cmd += ["-e", f"{k}={v}"]
    return cmd + list(args)


def _plays(tmp: Path) -> dict[str, tuple[list[str], dict | None]]:
    """name -> (argv, env). One run-mode harness file serves every row."""
    pb = tmp / "harness.yml"
    pb.write_text(RUN_MODE_HARNESS.format(
        facts=FACTS, repo=REPO, layers="\n".join(f"    - {p}" for p in ni.default_layers())))
    plays = {}
    for i, (extra, _) in enumerate(MAPPED_ROWS):
        plays[f"mapped{i}"] = (_cmd(pb, dict(extra, confirm="false")), None)
    for i, extra in enumerate(FALSE_ROWS):
        plays[f"false{i}"] = (_cmd(pb, extra), None)
    plays["f9"] = (_cmd(pb, {"blank": "true", "remove": "none"}), None)
    plays["m4"] = (_cmd(pb, {"blank": "false", "remove": "data", "confirm": "true"}), None)
    for bad in OFF_ALLOWLIST:
        plays[f"off:{bad}"] = (_cmd(pb, {"remove": bad}), None)
    for level, confirm, _ in VALID_LEVELS:
        plays[f"level:{level}"] = (_cmd(pb, {"remove": level, "confirm": confirm}), None)
    plays["tags"] = (_cmd(pb, {"remove": "data"}, ["--tags", "blank"]), None)
    plays["leave"] = (_cmd(pb, {"leave": "true"}), None)

    def verify(name, dirs, docker_stdout, docker_rc=0):
        home = tmp / name
        home.mkdir()
        stub = home / "docker"
        stub.write_text(f"#!/bin/sh\necho '{docker_stdout}'\nexit {docker_rc}\n")
        stub.chmod(stub.stat().st_mode | statmod.S_IEXEC)
        vpb = home / "h.yml"
        vpb.write_text(VERIFY_HARNESS.format(facts=FACTS, stub=stub, dirs=[str(home / d) for d in dirs], repo=REPO))
        plays[name] = (_cmd(vpb, {"flush_ollama": "false"}), dict(os.environ, HOME=str(home)))

    verify("v_survivor", ["survivor", "gone"], "")
    (tmp / "v_survivor" / "survivor").mkdir()
    verify("v_absent", ["gone1", "gone2"], "")
    verify("v_volume", ["gone"], "mariadb_data")
    verify("v_docker", ["gone"], "", docker_rc=1)
    return plays


class Run:
    def __init__(self, p: subprocess.CompletedProcess):
        self.rc, self.raw = p.returncode, p.stdout
        self.out = " ".join(p.stdout.split())


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, Run]:
    tmp = tmp_path_factory.mktemp("run_mode_journey")
    plays = _plays(tmp)

    def go(item):
        name, (argv, env) = item
        return name, Run(subprocess.run(argv, capture_output=True, text=True, timeout=300, env=env))

    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        return dict(pool.map(go, plays.items()))


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _main_play() -> dict:
    return yaml.safe_load(_text(MAIN))[0]


# ── shim (was test_compat_shim_mapping) ──────────────────────────────────────

def shim_mapped_rows_print_the_mapping(r):
    for i, (extra, (remove, leave)) in enumerate(MAPPED_ROWS):
        run = r[f"mapped{i}"]
        assert run.rc == 0, (extra, run.raw[-2000:])
        assert f"Mapping applied: remove={remove} leave={leave}" in run.out, extra
        assert f"REMOVE = {remove}" in run.out, extra
        assert "TUPLE" not in run.raw, (extra, "dry-run stop did not fire")


def shim_false_rows_map_to_nothing_R7(r):
    for i, extra in enumerate(FALSE_ROWS):
        run = r[f"false{i}"]
        assert run.rc == 0, (extra, run.raw[-2000:])
        assert ALL_FALSE_TUPLE in run.out.replace("'", ""), (extra, "false legacy switch must derive the all-False tuple")
        assert "Mapping applied" not in run.raw, (extra, "shim fired on a false value")


def shim_mixed_vocabulary_fails_F9(r):
    assert r["f9"].rc != 0, "-e blank=true -e remove=none must HARD-FAIL (F9)"
    assert "Use ONE vocabulary" in r["f9"].out


def shim_falsy_blank_with_removal_fails_M4(r):
    assert r["m4"].rc != 0, "-e blank=false -e remove=data would shadow X1's gate — must HARD-FAIL (M4)"
    assert "shadow the derived execution gate" in r["m4"].out


def shim_setfact_payloads_are_value_gated(_r):
    tasks = yaml.safe_load(_text(RUN_MODE))
    by_name = {t["name"]: t for t in tasks if isinstance(t, dict) and "name" in t}

    def _task(frag):
        hits = [n for n in by_name if frag in n]
        assert hits, f"compat mapping for {frag} MISSING from run-mode.yml (absence=failure)"
        return by_name[hits[0]]

    blank = _task("blank=true")["ansible.builtin.set_fact"]
    assert blank["remove"] == "data" and blank["confirm"] is True
    flush = _task("flush=true|deep")["ansible.builtin.set_fact"]
    assert "'deep' if" in str(flush["remove"]) and flush["confirm"] is True
    uni = _task("uninstall=true")["ansible.builtin.set_fact"]
    assert uni["remove"] == "all" and uni["leave"] is True
    assert uni["confirm"] is True and uni["_compat_uninstall"] is True
    for frag in ("blank=true", "flush=true|deep", "uninstall=true"):
        when = str(_task(frag)["when"])
        assert ("in [true, 'true'" in when or "in ['true', 'deep']" in when), f"{frag} mapping is not VALUE-gated: {when}"


# ── allowlist (was test_run_mode_allowlist, G-1) ─────────────────────────────

def allowlist_off_values_fail_the_run(r):
    for bad in OFF_ALLOWLIST:
        run = r[f"off:{bad}"]
        assert run.rc != 0, f"-e remove={bad!r} must HARD-FAIL (fail closed) — it converged/ended green"
        assert "not one of none|data|deep|all" in run.out, bad


def tuple_valid_levels_derive_documented_tuple(r):
    for level, _, tup in VALID_LEVELS:
        run = r[f"level:{level}"]
        assert run.rc == 0, (level, run.raw[-2000:])
        assert f"TUPLE {tup}" in run.out.replace("'", ""), level


def tags_removal_fails_R4(r):
    assert r["tags"].rc != 0, "remove=data + --tags must hard-fail (R4)"


def bare_leave_fails(r):
    assert r["leave"].rc != 0, "bare leave=true must fail loudly, not no-op green"


def derivation_is_filterless(_r):
    tasks = yaml.safe_load(_text(RUN_MODE))
    derive = next(t for t in tasks if "UNCONDITIONAL" in t["name"])
    env = jinja2.Environment()  # stock Jinja2, ZERO ansible filters
    for expr in derive["ansible.builtin.set_fact"].values():
        env.from_string(str(expr)).render(
            remove="data", confirm="true", assume_yes=False, leave=False, _compat_uninstall=False)


# ── removal-verify (was test_removal_verify_closes_survivors, G-4) ──────────

def verify_sits_after_removals_before_leave(_r):
    src = _text(MAIN)
    order = [src.index("tasks/blank-reset.yml"), src.index("tasks/flush-deep.yml"),
             src.index("tasks/remove-source.yml"), src.index("tasks/removal-verify.yml"),
             src.index("Leave — end the play")]
    assert order == sorted(order), "verify must sit after ALL removal imports and before the leave end_play"
    block = src[src.index("tasks/removal-verify.yml"):src.index("Leave — end the play")]
    assert "tags: ['always']" in block, "verify import must carry tags: ['always']"


def verify_planted_survivor_goes_red(r):
    run = r["v_survivor"]
    assert run.rc != 0 and "v_survivor/survivor" in run.raw, "survivor must fail LOUDLY, named"


def verify_all_absent_passes(r):
    assert r["v_absent"].rc == 0, r["v_absent"].raw[-2000:]


def verify_orphan_named_volume_goes_red(r):
    assert r["v_volume"].rc != 0 and "mariadb_data" in r["v_volume"].raw


def verify_docker_unreachable_fails(r):
    assert r["v_docker"].rc != 0, "docker unreachable during a removal must FAIL, not skip"


# ── scope (was test_uninstall_scope) ─────────────────────────────────────────

def scope_task_files_exist_and_parse(_r):
    for p in (REMOVAL_SET, REMOVE_SOURCE, RUN_MODE):
        assert p.is_file(), f"{p.name} is missing"
        tasks = yaml.safe_load(_text(p))
        assert isinstance(tasks, list) and tasks, f"{p.name} must be a non-empty task list"


def scope_source_set_covers_source_tree_and_anatomy_dirs(_r):
    txt = _text(REMOVAL_SET)
    assert "_uninstall_source" in txt, "removal-set.yml must own _uninstall_source"
    assert "nos_data_root" in txt, "remove=all must target nos_data_root (the user source tree)"
    assert "bone_state_dir" in txt, "remove=all must remove the ~/.nos side-car"
    for var in ("bone_runtime_dir", "pulse_home", "wing_home", "keap_home",
                "hermes_home", "hermes_config_dir", ".openclaw"):
        assert var in txt, f"remove=all must remove the anatomy runtime dir ({var})"


def scope_data_level_never_removes_the_source_tree(_r):
    txt = _text(REMOVAL_SET)
    blank_dirs = re.search(r"\n    _blank_dirs:\s*>-\n(?P<body>(?:(?: {6,}.*)?\n)+)", txt)
    assert blank_dirs, "could not locate the _blank_dirs set_fact in removal-set.yml"
    # keap's DERIVED data dir default derives from nos_data_root — the only sanctioned reference.
    bare = re.findall(r"\[\s*nos_data_root\s*\]|\{\{\s*nos_data_root\s*\}\}", blank_dirs.group("body"))
    assert not bare, "_blank_dirs lists nos_data_root wholesale — the data level must preserve the source tree"
    blank = _text(REPO / "tasks" / "blank-reset.yml")
    assert not re.search(r"state:\s*absent[\s\S]{0,200}\{\{\s*nos_data_root\s*\}\}\s*$", blank, re.MULTILINE), (
        "blank must PRESERVE nos_data_root (source) — only remove=all removes it")


def scope_removals_are_dry_run_by_default(_r):
    tasks = yaml.safe_load(_text(RUN_MODE))
    stops = [t for t in tasks if isinstance(t, dict) and t.get("ansible.builtin.meta") == "end_play"]
    assert stops, "run-mode.yml lost its dry-run meta: end_play stop"
    gated = []
    for t in stops:
        when = t.get("when")
        joined = " && ".join(str(c) for c in (when if isinstance(when, list) else [when]))
        if ("remove | default('none') in ['data', 'deep', 'all']" in joined
                and "confirm | default(false) in [true, 'true'" in joined
                and "not (confirm" in joined):
            gated.append(t)
    assert gated, "the dry-run stop must gate on remove-membership AND not-confirm membership"


def scope_execute_path_keeps_pause_and_become_loop(_r):
    tasks = yaml.safe_load(_text(REMOVE_SOURCE))
    pauses = [t for t in tasks if isinstance(t, dict) and "ansible.builtin.pause" in t]
    assert pauses, "remove-source.yml lost its final interactive confirmation pause"
    assert any("nos_assume_yes" in str(t.get("when", "")) for t in pauses), (
        "the pause must be gated `when: not nos_assume_yes` (only -y skips it)")
    loops = [t for t in tasks if isinstance(t, dict) and t.get("ansible.builtin.file", {}).get("state") == "absent"]
    assert loops, "remove-source.yml lost the source-removal file:state=absent loop"
    for t in loops:
        assert t.get("loop") == "{{ _uninstall_source }}", "the removal loop must consume _uninstall_source"
        assert t.get("become") is True, "source removal must escalate (become: true)"


def scope_main_wires_remove_source_and_leave_end_play(_r):
    txt = _text(MAIN)
    assert "tasks/remove-source.yml" in txt, "main.yml must import tasks/remove-source.yml"
    assert "tasks/uninstall.yml" not in txt, "tasks/uninstall.yml was deleted — main.yml must not reference it"
    assert re.search(r"import_tasks: tasks/remove-source\.yml\s*\n\s*when:\s*nos_remove_source", txt), (
        "remove-source import must be `when: nos_remove_source`")
    leave = re.search(r"meta:\s*end_play\s*\n\s*when:\s*leave \| default\(false\) in \[true", txt)
    assert leave, "main.yml must end_play on leave=true (membership idiom on the raw var)"
    assert txt.index("tasks/remove-source.yml") < leave.start(), "the leave end_play must sit AFTER the source-removal import"


# ── dry run needs no sudo (was test_a_removal_dry_run_needs_no_sudo) ────────

def dry_run_flag_is_derived_before_the_roles(_r):
    facts = [t for t in _main_play()["pre_tasks"]
             if "nos_dry_removal" in (t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})]
    assert facts, "no pre_task derives nos_dry_removal"
    expr = facts[0]["ansible.builtin.set_fact"]["nos_dry_removal"]
    for tok in ("remove", "blank", "confirm", "assume_yes"):
        assert tok in expr, f"the derivation ignores `{tok}`"
    assert "always" in facts[0].get("tags", []), "a --tags run would lose the flag and sudo-die again"


def dry_run_every_host_role_skips(_r):
    bare = [r["role"] for r in _main_play()["roles"]
            if not any("nos_dry_removal" in str(w)
                       for w in ([r.get("when")] if isinstance(r.get("when"), str) else r.get("when") or []))]
    assert not bare, f"host roles that would run (and sudo) before a dry run prints its inventory: {bare}"


# ── -y removal asks for sudo first (was test_a_yes_removal_asks_for_sudo_first, D4) ──

D4 = "[Run-mode] Refuse non-interactive removal without a sudo path (D4)"


def _pre_tasks() -> list[dict]:
    play = _main_play()
    assert "roles" in play, "main.yml has no roles: section — re-point this gate"
    return play["pre_tasks"]


def sudo_refusal_runs_before_the_roles(_r):
    names = [t.get("name", "") for t in _pre_tasks()]
    assert D4 in names
    assert names.index("[Run-mode] Probe passwordless sudo (non-interactive removal preflight)") < names.index(D4)


def sudo_nothing_before_the_refusal_escalates(_r):
    for t in _pre_tasks():
        if t.get("name") == D4:
            return
        assert not t.get("become"), f"{t.get('name')} escalates before the sudo refusal"
    raise AssertionError("refusal not found")


def sudo_refusal_accepts_either_sudo_path(_r):
    t = next(t for t in _pre_tasks() if "(D4)" in t.get("name", ""))
    cond = " ".join(t["ansible.builtin.assert"]["that"])
    assert "nos_sudo_password" in cond and "_nos_sudo_probe.rc" in cond
    assert any("assume_yes" in w for w in t["when"]), "must only fire for -y"


def sudo_run_mode_carries_no_second_copy(_r):
    assert "(D4)\"" not in _text(RUN_MODE).replace("'", '"')


CHECKS = [v for k, v in dict(globals()).items()
          if callable(v) and k.startswith(("shim_", "allowlist_", "tuple_", "tags_", "bare_", "derivation_",
                                           "verify_", "scope_", "dry_run_", "sudo_"))]


def test_the_removal_ladder_journey(runs):
    assert len(CHECKS) == 27, f"{len(CHECKS)} checks: an invariant was dropped or added without counting it"
    failed = []
    for check in CHECKS:
        try:
            check(runs)
        except Exception as e:  # a KeyError or StopIteration is a red too, and named
            failed.append(f"{check.__name__}: {type(e).__name__}: {e}")
    assert not failed, "\n".join(failed)
