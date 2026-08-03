"""Anatomy gate — a judge never runs inside the daemon's private venv, and the
record says WHAT ran, not just what was typed.

Closes A3 + A4 of the 2026-08-03 adversarial review, both MEASURED against the
deployed daemon:

  A3  Bone's launchd PATH put ~/bone/venv/bin first; the committed argv
      `python3 -m pytest` therefore resolved to the daemon's own interpreter,
      which has no pytest ("No module named pytest"). The pytest adapter
      correctly answered INDETERMINATE — so gate sets `repo` and `full` could
      NEVER reach a verdict, on any tree, forever. The fix is engine-side:
      `judges.judge_spawn_env` filters the daemon's private interpreter bin
      dirs out of the PATH every judge is spawned with. (The plist reorder
      ships too, but a fix that only lives in deployment is untestable here
      and silently lost on the next PATH edit.)

  A4  `JudgeRun.identity()` recorded argv LITERALLY ("python3"), never what it
      resolved to or what that binary was. The same argv on the same tree_sha
      yielded "2488 tests collected" under the dev pyenv and "No module named
      pytest" under Bone's venv — two worlds, one identity — so a §11 replay
      could not tell "same result" from "same mistake".

THE GATES HERE RUN THE REAL MACHINERY. The A3 gate builds an actual venv (the
daemon's exact shape), imports judges.py under it, and runs a real subprocess
judge end-to-end — a hand-revert of `real_spawn`'s env plumbing turns it red.
The A4 gate resolves one literal argv under two PATHs through the real spawn
path and demands the identities differ — under the old argv-literal identity
the two dicts are equal, red again. Both were verified red against the
pre-fix judges.py before this file was committed.

CI-safe: no network, no Docker, no daemon. The venv build is stdlib-only
(--system-site-packages, no pip).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
JUDGES_PY = REPO / "files" / "anatomy" / "bone" / "judges.py"
BONE = REPO / "files" / "anatomy" / "bone"


def _load_judges():
    spec = importlib.util.spec_from_file_location("nos_loop_judges_env", JUDGES_PY)
    assert spec and spec.loader, f"cannot load {JUDGES_PY}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["nos_loop_judges_env"] = module
    spec.loader.exec_module(module)
    return module


J = _load_judges()


def _fake_tool(dirpath: Path, version: str) -> Path:
    """An executable that answers --version and does trivial 'work'."""
    exe = dirpath / "fakejudge"
    exe.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        f'  echo "fakejudge {version}"\n'
        "  exit 0\n"
        "fi\n"
        'echo "checked 3 things"\n'
    )
    exe.chmod(0o755)
    return exe


def _fake_spec():
    return J.JudgeSpec(
        name="fakejudge",
        argv=("fakejudge",),
        adapter="exit_zero",
        pass_exit=(0,),
        fail_exit=(1,),
        work_regex=r"checked (\d+)",
        min_work=1,
    )


def _solo_registry(spec):
    return J.Registry(
        judges={spec.name: spec},
        gate_sets={"solo": J.GateSetSpec(name="solo", judges=(spec.name,))},
    )


def _entries(path_value: str) -> set[str]:
    return {os.path.realpath(p) for p in path_value.split(os.pathsep) if p}


# ── A3 — the daemon's venv is filtered out of every judge's PATH ────────────


def test_a_venv_daemon_cannot_leak_its_own_bin_onto_a_judges_path(tmp_path):
    """End-to-end, in the deployed topology: a venv interpreter (Bone's exact
    shape) runs `run_gate_set` with the REAL spawn, and the judge subprocess
    reports the PATH it actually received. The venv's own bin dir — first on
    the daemon's PATH, exactly as bone.plist.j2 had it — must not reach the
    child. Old behaviour (spawn env inherited unchanged) fails this.

    Built as a real venv rather than a mock of one because the filter keys on
    `sys.prefix != sys.base_prefix`: the property under test IS "a private
    interpreter recognises itself", and only a private interpreter can show it.
    """
    venv_dir = tmp_path / "daemon-venv"
    built = subprocess.run(
        # --system-site-packages so the venv python sees the harness's yaml
        # (judges.py imports it) without any pip/network.
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
        capture_output=True, text=True, timeout=300,
    )
    assert built.returncode == 0, built.stderr
    venv_python = venv_dir / "bin" / "python3"
    assert venv_python.exists(), "venv did not produce a bin/python3"

    script = textwrap.dedent(
        f"""
        import importlib.util, json, os, sys
        spec = importlib.util.spec_from_file_location("j", {str(JUDGES_PY)!r})
        J = importlib.util.module_from_spec(spec)
        sys.modules["j"] = J  # dataclasses resolves cls.__module__ at class build
        spec.loader.exec_module(J)
        assert sys.prefix != sys.base_prefix, "harness error: not a venv"
        judge = J.JudgeSpec(
            name="pathspy",
            argv=("/bin/sh", "-c", 'echo "NOSPATH=$PATH"'),
            adapter="exit_zero", pass_exit=(0,), fail_exit=(1,),
        )
        registry = J.Registry(
            judges={{"pathspy": judge}},
            gate_sets={{"solo": J.GateSetSpec(name="solo", judges=("pathspy",))}},
        )
        verdict = J.run_gate_set(
            "solo", registry=registry, repo_root={str(REPO)!r},
            sandbox_factory=lambda root: (root, "sha-fake", lambda: None),
        )
        run = verdict.runs[0]
        print(json.dumps({{
            "own_bin": os.path.dirname(sys.executable),
            "daemon_path": os.environ.get("PATH", ""),
            "status": run.status,
            "stdout_head": run.stdout_head,
        }}))
        """
    )
    env = dict(os.environ)
    # The deployed defect's topology: the daemon's own venv bin FIRST.
    env["PATH"] = f"{venv_dir / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("VIRTUAL_ENV", None)
    proc = subprocess.run(
        [str(venv_python), "-c", script],
        capture_output=True, text=True, timeout=300, env=env,
    )
    assert proc.returncode == 0, f"harness subprocess failed:\n{proc.stderr[-4000:]}"
    payload = json.loads(proc.stdout)

    own_bin = os.path.realpath(payload["own_bin"])
    # Guard the guard: the defect topology really was present at daemon level.
    assert own_bin in _entries(payload["daemon_path"]), (
        "harness error: the venv bin never made it onto the daemon PATH, so "
        "nothing was measured"
    )
    assert payload["status"] == "exited", payload
    marker = payload["stdout_head"].split("NOSPATH=", 1)
    assert len(marker) == 2, f"the judge never reported its PATH: {payload}"
    judge_path = _entries(marker[1].split("\n", 1)[0].strip().strip('"'))
    assert own_bin not in judge_path, (
        "the daemon's own venv bin reached a judge's PATH — `python3 -m pytest` "
        "resolves to the pytest-less daemon interpreter again and `repo`/`full` "
        "can never verdict (A3)"
    )
    # Counterweight: the filter removed the PRIVATE dir, not the toolchain.
    assert os.path.realpath("/usr/bin") in judge_path, (
        f"the judge PATH lost the system toolchain too: {sorted(judge_path)}"
    )


def test_judge_spawn_env_always_drops_the_venv_advertisement():
    """VIRTUAL_ENV names the daemon's venv to any child launcher that consults
    it; it must never survive into a judge's environment."""
    out = J.judge_spawn_env(base={"PATH": "/usr/bin", "VIRTUAL_ENV": "/x/venv"})
    assert "VIRTUAL_ENV" not in out
    assert out["PATH"], "the env builder emptied PATH"


# ── A4 — identity records what RAN, not what was typed ──────────────────────


def test_the_same_literal_argv_under_two_paths_has_two_identities(tmp_path):
    """The acceptance gate, verbatim: resolve one literal argv under two
    different PATHs and demand `JudgeRun.identity()` differs. Under the old
    argv-literal identity the two dicts are equal — red on pre-fix code.

    Runs the REAL spawn (no double): the two fake tools genuinely execute, and
    both the resolution and the `--version` probe are measurements of a real
    subprocess, which is what makes the recorded fields evidence rather than
    bookkeeping.
    """
    d1, d2 = tmp_path / "world-one", tmp_path / "world-two"
    d1.mkdir(), d2.mkdir()
    _fake_tool(d1, "1.0")
    _fake_tool(d2, "2.0")
    spec = _fake_spec()
    registry = _solo_registry(spec)

    def run(world: Path):
        return J.run_gate_set(
            "solo",
            registry=registry,
            repo_root=REPO,
            judge_env={"PATH": str(world)},
            sandbox_factory=lambda root: (root, "sha-fake", lambda: None),
        )

    v1, v2 = run(d1), run(d2)
    r1, r2 = v1.runs[0], v2.runs[0]
    assert r1.status == r2.status == "exited", (r1.reason, r2.reason)
    assert r1.result is J.Result.PASS and r2.result is J.Result.PASS

    # Same literal argv, same tree label, same exit — the OLD identity is
    # equal here, which is precisely A4.
    assert list(r1.argv) == list(r2.argv) == ["fakejudge"]
    assert r1.identity() != r2.identity(), (
        "two different interpreters produced one identity — a §11 replay "
        "cannot tell 'same result' from 'same mistake' (A4)"
    )
    # Guard the guard: strip the new fields and the two runs ARE equal — i.e.
    # every pre-fix identity field (argv, exit, work, stdout_sha, tree label)
    # matches across the two worlds, so the OLD identity provably could not
    # have distinguished them and this gate is red on pre-fix code.
    strip = ("resolved_argv0", "interpreter")
    assert (
        {k: v for k, v in r1.identity().items() if k not in strip}
        == {k: v for k, v in r2.identity().items() if k not in strip}
    ), "the worlds differ in an old field too — this gate no longer isolates A4"
    assert v1.digest() != v2.digest(), "the digest does not cover the interpreter"

    # The fields are measurements, not labels.
    assert r1.resolved_argv0 == os.path.realpath(str(d1 / "fakejudge")), r1.resolved_argv0
    assert r2.resolved_argv0 == os.path.realpath(str(d2 / "fakejudge")), r2.resolved_argv0
    assert r1.interpreter == "fakejudge 1.0", r1.interpreter
    assert r2.interpreter == "fakejudge 2.0", r2.interpreter
    for key in ("resolved_argv0", "interpreter"):
        assert key in r1.identity(), f"identity() dropped {key}"


def test_the_resolved_identity_is_still_deterministic(tmp_path):
    """The counterweight: the new fields must not make two honest runs of the
    SAME world disagree — that would trade A4 for unreplayability."""
    world = tmp_path / "world"
    world.mkdir()
    _fake_tool(world, "1.0")
    registry = _solo_registry(_fake_spec())

    def run():
        return J.run_gate_set(
            "solo",
            registry=registry,
            repo_root=REPO,
            judge_env={"PATH": str(world)},
            sandbox_factory=lambda root: (root, "sha-fake", lambda: None),
        )

    first, second = run(), run()
    assert first.runs[0].identity() == second.runs[0].identity()
    assert first.digest() == second.digest()


# ── the record survives the database boundary ───────────────────────────────


def test_the_ledger_persists_what_actually_ran(tmp_path, monkeypatch):
    """The `reason` column lesson, applied before it recurs: a field computed
    in judges.py and dropped at the database boundary is how the skip reason
    was lost the first time. Real round-trip — begin, finish, read back."""
    if str(BONE) not in sys.path:
        sys.path.insert(0, str(BONE))
    import ledger  # noqa: PLC0415 — path set above

    db = tmp_path / "wing.db"
    import sqlite3

    sqlite3.connect(str(db)).close()
    monkeypatch.setenv("WING_DB_PATH", str(db))

    led = ledger.open_ledger("evaluator", registry=_solo_registry(_fake_spec()))
    try:
        u = led.begin_judge_run(gate_set="solo", judge_name="fakejudge", argv=("fakejudge",))
        run = J.JudgeRun(
            judge_name="fakejudge",
            gate_set="solo",
            argv=("fakejudge",),
            status="exited",
            result=J.Result.FAIL,
            reason="1 failing test(s)",
            exit_code=1,
            work=3,
            min_work=1,
            stdout_sha="0" * 64,
            tree_sha="f" * 40,
            resolved_argv0="/tmp/world-one/fakejudge",
            interpreter="fakejudge 1.0",
        )
        led.finish_judge_run(u, run=run)
        row = led.judge_run(u)
        assert row is not None
        assert row["resolved_argv0"] == "/tmp/world-one/fakejudge", (
            "resolved_argv0 was computed by the engine and thrown away at the "
            "database boundary — the reason-column defect, again"
        )
        assert row["interpreter"] == "fakejudge 1.0"
        # ...and the rehydrated run carries them back into aggregation land.
        rebuilt = ledger._as_judge_run(row)
        assert rebuilt.resolved_argv0 == "/tmp/world-one/fakejudge"
        assert rebuilt.interpreter == "fakejudge 1.0"
    finally:
        led.close()
