"""G-1 — the remove allowlist FAILS CLOSED, and the derivation is filter-less.

Half A drives a minimal harness play through tasks/run-mode.yml with -e rows
and asserts the RUN fails (rc != 0) for off-allowlist input — never that a
boolean derives False. Half B parses the derivation set_fact out of
tasks/run-mode.yml and evaluates each expression in a STOCK jinja2
Environment with NO ansible filters registered.

Harness path note (gate-audit defect 2): the harness playbook lives in
tmp_path and imports {REPO}/tasks/run-mode.yml by ABSOLUTE path; run-mode's
own nested import uses the SIBLING form `removal-set.yml` (resolves next to
run-mode.yml in every context). A `tasks/`-prefixed nested path would resolve
against the harness playbook dir and parse-fail every row.
"""
import subprocess
import textwrap
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

HARNESS = textwrap.dedent("""\
    - hosts: localhost
      connection: local
      gather_facts: true
      vars_files:
        - {repo}/default.config.yml
      tasks:
        - import_tasks: {repo}/tasks/run-mode.yml
        # blank via | bool: an explicit -e blank=<x> extra-var OUTRANKS the derived
        # fact (string 'false'), and every legacy read site is `blank | bool` —
        # the tuple measures what those read sites actually see.
        - debug:
            msg: "TUPLE {{{{ [nos_removing, nos_remove_data, nos_remove_deep, nos_remove_source, blank | bool, _flush_deep | bool] | string }}}}"
""")


def _play(tmp_path, extra_vars, extra_args=()):
    pb = tmp_path / "harness.yml"
    pb.write_text(HARNESS.format(repo=REPO))
    cmd = ["ansible-playbook", str(pb), "-i", "localhost,"]
    for k, v in extra_vars.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += list(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


# NOTE the dropped `"none "` row (gate-audit defect 3): ansible's parse_kv
# strips the trailing space before the playbook sees it — the row is
# unreachable from raw ansible and would be red against a CORRECT
# implementation. Whitespace/garbage at the CLI layer is G-5's exit-64 job.
@pytest.mark.parametrize("bad", ["DATA", "All", "", "garbage", "deep,all"])
def test_off_allowlist_remove_FAILS_the_run(tmp_path, bad):
    r = _play(tmp_path, {"remove": bad})
    assert r.returncode != 0, (
        f"-e remove={bad!r} must HARD-FAIL (fail closed) — it converged/ended green"
    )
    # ansible.cfg callback_result_format=yaml line-wraps long messages —
    # collapse whitespace before substring checks.
    assert "not one of none|data|deep|all" in " ".join(r.stdout.split())


# Removal rows pass confirm=true (gate-audit defect 1): unconfirmed they hit
# the R9 end_play INSIDE the import and the harness's trailing TUPLE debug
# never runs — 3 of 4 rows red forever against a CORRECT implementation.
# Safe: run-mode.yml contains no pauses and nothing destructive (asserts,
# stats, debug, end_play only); the harness play has no removal imports.
@pytest.mark.parametrize("level,confirm,tup", [
    ("none", "false", [False, False, False, False, False, False]),
    ("data", "true",  [True,  True,  False, False, True,  False]),
    ("deep", "true",  [True,  True,  True,  False, True,  True]),
    ("all",  "true",  [True,  True,  True,  True,  True,  True]),
])
def test_valid_levels_derive_documented_tuple(tmp_path, level, confirm, tup):
    r = _play(tmp_path, {"remove": level, "confirm": confirm})
    assert r.returncode == 0, r.stdout[-2000:]
    assert f"TUPLE {tup}" in " ".join(r.stdout.split()).replace("'", "")


def test_tag_restricted_removal_fails(tmp_path):
    r = _play(tmp_path, {"remove": "data"}, extra_args=["--tags", "blank"])
    assert r.returncode != 0, "remove=data + --tags must hard-fail (R4)"


def test_bare_leave_fails(tmp_path):
    r = _play(tmp_path, {"leave": "true"})
    assert r.returncode != 0, "bare leave=true must fail loudly, not no-op green"


def test_derivation_compiles_filterless():
    tasks = yaml.safe_load((REPO / "tasks/run-mode.yml").read_text())
    derive = next(t for t in tasks if "UNCONDITIONAL" in t["name"])
    env = jinja2.Environment()          # stock Jinja2, ZERO ansible filters
    for key, expr in derive["ansible.builtin.set_fact"].items():
        env.from_string(str(expr)).render(
            remove="data", confirm="true", assume_yes=False, leave=False,
            _compat_uninstall=False)    # raises on any non-stock filter
