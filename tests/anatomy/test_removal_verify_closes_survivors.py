"""G-4 — the verify phase exists, sits in the right position, and actually
goes red on a planted survivor (executes the task file via a harness).

HOME is overridden to tmp_path for every harness run (gate-audit defect):
the expected-absent set unconditionally appends $HOME/projects/default/
service-registry.json and $HOME/.nos/secrets.yml — on a live dev box both
exist, so without isolation test_all_absent_passes is spuriously red on the
very machine the gate protects. gather_facts reads env HOME, so the override
carries into ansible_facts['env']['HOME']."""
import os
import stat as statmod
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_position_after_removals_before_leave():
    src = (REPO / "main.yml").read_text()
    order = [src.index("tasks/blank-reset.yml"), src.index("tasks/flush-deep.yml"),
             src.index("tasks/remove-source.yml"), src.index("tasks/removal-verify.yml"),
             src.index("Leave — end the play")]
    assert order == sorted(order), "verify must sit after ALL removal imports and before the leave end_play"
    verify_block = src[src.index("tasks/removal-verify.yml"):src.index("Leave — end the play")]
    # LITERAL tag list — the word "always" anywhere in the block is
    # comment-satisfiable (gate-audit minor).
    assert "tags: ['always']" in verify_block, "verify import must carry tags: ['always']"


def _harness(tmp_path, dirs, docker_stdout, docker_rc=0):
    stub = tmp_path / "docker"
    stub.write_text(f"#!/bin/sh\necho '{docker_stdout}'\nexit {docker_rc}\n")
    stub.chmod(stub.stat().st_mode | statmod.S_IEXEC)
    pb = tmp_path / "h.yml"
    pb.write_text(textwrap.dedent(f"""\
        - hosts: localhost
          connection: local
          gather_facts: true
          vars:
            remove: data
            docker_bin: {stub}
            nos_remove_deep: false
            nos_remove_source: false
            _blank_dirs: {dirs!r}
            _uninstall_source: []
          tasks:
            - import_tasks: {REPO}/tasks/removal-verify.yml
    """))
    return subprocess.run(["ansible-playbook", str(pb), "-i", "localhost,",
                           "-e", "flush_ollama=false"],
                          env=dict(os.environ, HOME=str(tmp_path)),
                          capture_output=True, text=True, timeout=300)


def test_planted_survivor_goes_red(tmp_path):
    survivor = tmp_path / "survivor"
    survivor.mkdir()
    r = _harness(tmp_path, [str(survivor), str(tmp_path / "gone")], "")
    assert r.returncode != 0 and str(survivor) in r.stdout, "survivor must fail LOUDLY, named"


def test_all_absent_passes(tmp_path):
    r = _harness(tmp_path, [str(tmp_path / "gone1"), str(tmp_path / "gone2")], "")
    assert r.returncode == 0, r.stdout[-2000:]


def test_orphan_named_volume_goes_red(tmp_path):
    r = _harness(tmp_path, [str(tmp_path / "gone")], "mariadb_data")
    assert r.returncode != 0 and "mariadb_data" in r.stdout


def test_docker_unreachable_is_a_failure(tmp_path):
    r = _harness(tmp_path, [str(tmp_path / "gone")], "", docker_rc=1)
    assert r.returncode != 0, "docker unreachable during a removal must FAIL, not skip"
