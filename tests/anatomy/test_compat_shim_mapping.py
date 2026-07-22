"""G-2 — the compat shim maps every legacy row exactly; false rows map to
NOTHING; disagreeing mixed vocabulary hard-fails.

Gate-audit hole closed: mapped rows (forced confirm=false) hit the R9
end_play, so the harness's trailing TUPLE debug is unreachable for them —
rc==0 alone would be green over a fully broken shim (a broken shim just
converges the harness green). The executed half therefore asserts on output
PRINTED BEFORE the end_play, produced BY the shimmed values themselves:
  - the deprecation notice: "Mapping applied: remove=<x> leave=<y>"
  - the inventory banner header: "REMOVE = <x>   leave = <y>"
A typoed set_fact key (remove:->removed:) prints remove=none and goes red.
The parse half asserts the set_fact PAYLOAD (keys AND values), not just task
names / when-shape."""
import subprocess
import textwrap
from pathlib import Path

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


def _play(tmp_path, extra_vars):
    pb = tmp_path / "harness.yml"
    pb.write_text(HARNESS.format(repo=REPO))
    cmd = ["ansible-playbook", str(pb), "-i", "localhost,"]
    for k, v in extra_vars.items():
        cmd += ["-e", f"{k}={v}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


MAPPED_ROWS = [  # extra_vars -> (remove, leave) the shim must print
    ({"blank": "true"},                          ("data", "False")),
    ({"blank": "yes"},                           ("data", "False")),   # |bool parity
    ({"flush": "true"},                          ("data", "False")),
    ({"flush": "deep"},                          ("deep", "False")),
    ({"uninstall": "true"},                      ("all",  "True")),
    ({"uninstall": "true", "confirm_uninstall": "true"}, ("all", "True")),
]
FALSE_ROWS = [{"blank": "false"}, {"flush": "false"}, {"uninstall": "false"}]  # R7
ALL_FALSE_TUPLE = "TUPLE [False, False, False, False, False, False]"


def test_mapped_rows_print_the_mapping(tmp_path):
    for extra, (remove, leave) in MAPPED_ROWS:
        # confirm=false FORCED so mapped rows stop at the dry-run gate instead
        # of pausing — extra-var outranks the shim's confirm=true set_fact.
        r = _play(tmp_path, dict(extra, confirm="false"))
        assert r.returncode == 0, (extra, r.stdout[-2000:])
        # ansible.cfg callback_result_format=yaml line-wraps long messages —
        # collapse whitespace before substring checks.
        out = " ".join(r.stdout.split())
        # substance printed BEFORE the end_play — measures the live set_fact:
        assert f"Mapping applied: remove={remove} leave={leave}" in out, extra
        assert f"REMOVE = {remove}" in out, extra
        # and the end_play DID fire (no TUPLE debug after the stop):
        assert "TUPLE" not in r.stdout, (extra, "dry-run stop did not fire")


def test_false_rows_map_to_nothing(tmp_path):
    for extra in FALSE_ROWS:
        r = _play(tmp_path, extra)
        assert r.returncode == 0, (extra, r.stdout[-2000:])
        assert ALL_FALSE_TUPLE in " ".join(r.stdout.split()).replace("'", ""), (
            extra, "false-valued legacy switch must derive the all-False tuple (R7)")
        assert "Mapping applied" not in r.stdout, (extra, "shim fired on a false value")


def test_mixed_vocabulary_disagreeing_fails(tmp_path):
    r = _play(tmp_path, {"blank": "true", "remove": "none"})
    assert r.returncode != 0, "-e blank=true -e remove=none must HARD-FAIL (F9)"
    assert "Use ONE vocabulary" in " ".join(r.stdout.split())


def test_falsy_blank_mixed_with_removal_fails(tmp_path):
    r = _play(tmp_path, {"blank": "false", "remove": "data", "confirm": "true"})
    assert r.returncode != 0, (
        "-e blank=false -e remove=data would shadow X1's gate — must HARD-FAIL (M4)")
    assert "shadow the derived execution gate" in " ".join(r.stdout.split())


def test_shim_setfact_payloads_in_file():
    tasks = yaml.safe_load((REPO / "tasks/run-mode.yml").read_text())
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
        assert ("in [true, 'true'" in when or "in ['true', 'deep']" in when), \
            f"{frag} mapping is not VALUE-gated: {when}"
