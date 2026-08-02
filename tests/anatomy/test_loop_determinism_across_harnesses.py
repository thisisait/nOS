"""Anatomy gate — one tree, one verdict, whichever harness asks.

Contract: ``docs/idea/11-agentic-loop-contract.md`` — DECISION 6 (HTTP is the
only implementation, the CLI is a thin client over it), §3.5 (constraint B),
§8.2 (constraint D), §1 + §6.1 (constraint E), §11 (replay is the guarantee).

WHY THIS FILE EXISTS
--------------------
The engine lives ON THE DEVICE and not inside one harness. Claude Code, Hermes,
AgentKit and the planned Rust brain all reach the same judge; a Pulse job at
03:00 reaches it with no human in the loop. That arrangement buys exactly one
thing — a verdict that means the same thing everywhere — and it buys it only if
the verdict is a function of ``(tree, gate set)`` and of nothing else. If the
answer moves with the caller, the loop has four oracles wearing one name, and
§11's replay ("re-run the recorded argv against the recorded tree and reproduce
the recorded exit_code, work_count and stdout_sha") becomes a coin toss.

``test_loop_judge_runner.py`` already pins that two runs *in one process* agree.
That is the easy half. This file pins the half that is assumed everywhere and
tested nowhere: two runs in DIFFERENT PROCESSES, under different working
directories, different environments, inside an event loop versus on a bare
call stack, must agree — byte for byte, down to the digest and the sealed
ledger row.

WHAT IS ACTUALLY MEASURED, so nobody reads more into a green than it holds
--------------------------------------------------------------------------
The same REAL judge (``python3 tools/genome-codegen.py --check`` — the one
judge that is pure repo I/O and 0.1 s) is run three ways:

  H1  in-process, synchronous            — the shape a Pulse job or the future
                                           ``loop.py`` route body uses
  H2  over HTTP, through the REAL         — a FastAPI app + starlette TestClient,
      ``loopauth.require_loop_scope``      the request served on the threadpool,
      dependency and a real bearer token   the caller holding the evaluator token
  H3  in a separate interpreter,          — this file, run as a script, from a
      different cwd, perturbed env         different directory with TERM/FORCE_COLOR/
                                           LC_ALL/COLUMNS/HOME/PYTHONHASHSEED all
                                           changed underneath it

H2's route body is one line — it hands a gate-set NAME to ``run_harness`` and
returns what came back. That is a fixture, not production code, and it is
declared as such: the route that will hold it (``POST /api/v1/loop/judge``) is
build-order step 1b and is not mounted yet. The precedent for exercising an
identity boundary before its routes exist is ``tests/bone_loop/test_loop_auth.py``.
So §3 below carries the STRUCTURAL half of the claim — that there is exactly one
implementation of judgment in the estate, that nothing outside Bone may import
it, and that any judge route which does land must delegate to it — because a
parity that holds today by accident is not a property, it is a coincidence.

H3 models the CLI's *process context*, not the CLI's *shape*: DECISION 6 forbids
a CLI that imports the engine, and nothing here endorses one. What H3 proves is
narrower and is the thing at issue — that leaving the daemon's process, cwd and
environment does not move the verdict.

A MEASURED CEILING, recorded rather than papered over
-----------------------------------------------------
The cross-harness mutex (``exclusive_resource: nos_entity``, M7) is a lock file
under ``tempfile.gettempdir()``. Its NAME is harness-independent and that is
pinned below — but its DIRECTORY follows ``$TMPDIR``. Two harnesses that do not
share ``$TMPDIR`` therefore do not share the lock, and ``genome-codegen`` and
``pytest-anatomy`` would be free to corrupt each other's ``nos_entity.py``.
Under launchd and a login shell of the same user this holds today (same per-user
folder); under a systemd unit with ``PrivateTmp=`` or a container it would not.
That is a real ceiling on this file's claim and it belongs in the docstring of
the gate that would otherwise be read as covering it.

CI-safe: no live estate, no Docker, no network. The judge subprocess is repo
I/O; the ledger is sqlite in a tmp dir.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files" / "anatomy" / "bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import judges  # noqa: E402  — same loader pattern as tests/anatomy/test_loop_ledger.py
import ledger  # noqa: E402
import loopauth  # noqa: E402
import weaknesses  # noqa: E402  — the only loop router mounted today

JUDGES_PY = BONE / "judges.py"
MANIFEST = REPO / "state" / "manifest.yml"
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"
BONE_PLIST = REPO / "roles" / "pazny.bone" / "templates" / "bone.plist.j2"
BONE_TASKS = REPO / "roles" / "pazny.bone" / "tasks" / "main.yml"

#: The one real judge cheap enough to run three times inside the anatomy suite.
#: Its SPEC is the committed one — the gate set is narrowed, the judge is not.
#: (`ansible-lint` is 55 s and `pytest-anatomy` is 190 s and sandboxed.)
JUDGE = "genome-codegen"
SOLO = "solo"

LOOP_TOKEN_KEYS = ("loop_propose_token", "loop_judge_token")
JUDGE_TOKEN = "j" * 64
PROPOSE_TOKEN = "p" * 64


# ─────────────────────────────────────────────────────────────────────────────
# The harness body — identical code in all three contexts
# ─────────────────────────────────────────────────────────────────────────────


def _solo_registry(repo_root: Path):
    """The committed spec for one judge, in a one-judge gate set."""
    reg = judges.load_registry(repo_root)
    return judges.Registry(
        judges={JUDGE: reg.judges[JUDGE]},
        gate_sets={SOLO: judges.GateSetSpec(name=SOLO, judges=(JUDGE,))},
    )


def _tree_sha(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root), capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _ensure_db(path: Path) -> None:
    """`clients/wing.py::_open` requires the file to exist before it connects."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()


def _seal(verdict, *, registry) -> dict:
    """Persist the runs and seal the verdict, reading ``WING_DB_PATH`` from env.

    NOTE, so this is not mistaken for the production sequence: constraint B
    requires the run row to be opened BEFORE the subprocess starts, and that
    ordering is `loop.py`'s job and is pinned in `test_loop_ledger.py`. This
    harness only needs the SEALED ROW to compare across processes, so it
    records after the fact. It is a comparison fixture, not a model.

    The registry is passed at CONSTRUCTION because `seal_verdict` derives the
    set's membership rather than being told it — and this harness runs a
    narrowed one-judge set that the committed registry does not declare. The
    `tree_sha` is not passed at all: it comes off the runs, which read it out of
    the sandbox they ran in.
    """
    led = ledger.open_ledger("evaluator", registry=registry)
    try:
        for run in verdict.runs:
            u = led.begin_judge_run(
                gate_set=verdict.gate_set, judge_name=run.judge_name, argv=run.argv
            )
            led.finish_judge_run(u, run=run)
        return led.seal_verdict(gate_set=verdict.gate_set)
    finally:
        led.close()


def run_harness(*, gate_set: str, repo_root: Path, lock_dir: Path, seal: bool) -> dict:
    """Run a gate set and (optionally) seal it. The whole harness body.

    The ONLY inputs are a gate-set name and where the tree and the lock live.
    Nothing here supplies, hints at, or overrides a result — that is
    `run_gate_set`'s guarantee and `test_no_seam_can_supply_a_result` pins it.
    """
    registry = _solo_registry(repo_root)
    verdict = judges.run_gate_set(
        gate_set, registry=registry, repo_root=repo_root, lock_dir=lock_dir
    )
    out: dict = {"verdict": verdict.to_dict(), "sealed": None}
    if seal:
        row = _seal(verdict, registry=registry)
        out["sealed"] = {k: row[k] for k in ("gate_set", "result", "actor", "tree_sha", "evidence")}
    return out


def _registry_digest(reg) -> str:
    """A hash over every field of every judge — what both harnesses must read."""
    blob = json.dumps(
        {name: dataclasses.asdict(spec) for name, spec in sorted(reg.judges.items())},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# H3 — this file, run as a script, in another process
# ─────────────────────────────────────────────────────────────────────────────

#: Deliberately hostile to a judge that colours, wraps or localises its output:
#: a coloured `1400 files processed` line parses differently, and a different
#: stdout is a different `stdout_sha`, and a different `stdout_sha` is an
#: unreplayable verdict. `NO_COLOR` is REMOVED rather than set, so nothing here
#: is quietly doing the suppression for the engine.
PERTURBED_ENV = {
    "TERM": "xterm-256color",
    "FORCE_COLOR": "1",
    "CLICOLOR_FORCE": "1",
    "LC_ALL": "C",
    "LANG": "C",
    "COLUMNS": "40",
    "PYTHONHASHSEED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _subprocess_harness(*, emit: str, cwd: Path, lock_dir: Path | None = None,
                        db: Path | None = None, home: Path | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    env.update(PERTURBED_ENV)
    if home is not None:
        env["HOME"] = str(home)
    if db is not None:
        env["WING_DB_PATH"] = str(db)
    argv = [sys.executable, str(Path(__file__).resolve()), "--emit", emit]
    if lock_dir is not None:
        argv += ["--lock", str(lock_dir)]
    if db is not None:
        argv += ["--seal"]
    proc = subprocess.run(
        argv, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=900
    )
    assert proc.returncode == 0, (
        f"the subprocess harness failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
    )
    return json.loads(proc.stdout)


def _driver_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="loop-harness-driver")
    ap.add_argument("--emit", choices=("probe", "judge"), required=True)
    ap.add_argument("--lock", default=None)
    ap.add_argument("--seal", action="store_true")
    args = ap.parse_args(argv)

    if args.emit == "probe":
        payload = {
            "cwd": os.getcwd(),
            "repo_root": str(judges._default_repo_root()),
            "registry_digest": _registry_digest(judges.load_registry()),
            "default_lock_path": str(
                judges._FileLock("nos_entity", Path(tempfile.gettempdir())).path
            ),
        }
    else:
        payload = run_harness(
            gate_set=SOLO,
            repo_root=REPO,
            lock_dir=Path(args.lock) if args.lock else Path(tempfile.gettempdir()),
            seal=args.seal,
        )
    print(json.dumps(payload, sort_keys=True))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def loop_tokens(monkeypatch):
    monkeypatch.setenv("BONE_LOOP_JUDGE_TOKEN", JUDGE_TOKEN)
    monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", PROPOSE_TOKEN)


def _http_app(*, repo_root: Path, lock_dir: Path, seal: bool) -> FastAPI:
    """A FIXTURE app standing in for `POST /api/v1/loop/judge` (step 1b).

    The dependency is the REAL one. The body is the single delegating line the
    contract's DECISION 6 requires the real route to be: a gate-set NAME in,
    whatever the runner returned out. There is no parameter here that a caller
    could use to influence a result, because there is none in `run_gate_set`.
    """
    app = FastAPI()

    @app.post("/api/v1/loop/judge")
    def judge(gate_set: str, _=Depends(loopauth.require_loop_scope("judge"))):
        return run_harness(
            gate_set=gate_set, repo_root=repo_root, lock_dir=lock_dir, seal=seal
        )

    return app


def _run_identity(payload: dict) -> dict:
    """The part of a harness's answer that must be identical everywhere."""
    v = payload["verdict"]
    return {
        "gate_set": v["gate_set"],
        "result": v["result"],
        "digest": v["digest"],
        "runs": v["runs"],
    }


def _sealed_identity(sealed: dict) -> dict:
    """The sealed row minus what is random or clock-driven BY CONSTRUCTION.

    `uuid`, `created_at`, `prev_hash` and `row_hash` differ between two runs of
    the SAME harness; comparing them would be comparing the chain, not the
    verdict. `judge_runs` are per-run uuids for the same reason.
    """
    evidence = json.loads(sealed["evidence"])
    evidence.pop("judge_runs", None)
    return {
        "gate_set": sealed["gate_set"],
        "result": sealed["result"],
        "actor": sealed["actor"],
        "tree_sha": sealed["tree_sha"],
        "evidence": evidence,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 0. Guard the guard
# ─────────────────────────────────────────────────────────────────────────────


def test_the_parity_harness_really_runs_a_real_judge(tmp_path):
    """Three INDETERMINATE answers also agree with each other.

    Without this, every parity assertion below could be satisfied by a judge
    that never ran — which is the exact false green (`docs/hidden_fees/08`) the
    engine exists to refuse, rebuilt inside its own gate.
    """
    payload = run_harness(gate_set=SOLO, repo_root=REPO, lock_dir=tmp_path, seal=False)
    run = payload["verdict"]["runs"][0]
    assert run["judge"] == JUDGE
    assert run["status"] == "exited", f"the judge did not run: {payload['verdict']}"
    assert run["result"] in ("pass", "fail"), payload["verdict"]
    assert run["exit_code"] is not None
    assert isinstance(run["work"], int) and run["work"] >= 1
    assert run["stdout_sha"], "no evidence hash — nothing to be deterministic about"


# ─────────────────────────────────────────────────────────────────────────────
# 1. The headline: same tree, same verdict, three harnesses
# ─────────────────────────────────────────────────────────────────────────────


def test_the_same_tree_yields_the_same_verdict_from_every_harness(
    tmp_path, monkeypatch, loop_tokens
):
    """In-process, over HTTP, and from another process with a hostile env.

    If these ever disagree, a verdict stops being a property of the tree and
    becomes a property of whoever asked — and every `--replay` in §11 is then
    a coin toss.
    """
    lock = tmp_path / "locks"
    lock.mkdir()

    h1 = run_harness(gate_set=SOLO, repo_root=REPO, lock_dir=lock, seal=False)

    app = _http_app(repo_root=REPO, lock_dir=lock, seal=False)
    with TestClient(app, client=("127.0.0.1", 51234)) as client:
        resp = client.post(
            "/api/v1/loop/judge",
            params={"gate_set": SOLO},
            headers={"Authorization": f"Bearer {JUDGE_TOKEN}"},
        )
        # ...and the HTTP harness is genuinely BEHIND the boundary, not merely
        # decorated with it: the proposer's token reaches the same route and is
        # refused. Without this, "over HTTP" would be a claim about a fixture.
        refused = client.post(
            "/api/v1/loop/judge",
            params={"gate_set": SOLO},
            headers={"Authorization": f"Bearer {PROPOSE_TOKEN}"},
        )
    assert resp.status_code == 200, resp.text
    assert refused.status_code == 403, "the proposer triggered a judge run"
    h2 = resp.json()

    home = tmp_path / "elsewhere-home"
    home.mkdir()
    h3 = _subprocess_harness(
        emit="judge", cwd=Path(tempfile.gettempdir()), lock_dir=lock, home=home
    )

    assert _run_identity(h1) == _run_identity(h2), "in-process and HTTP disagree"
    assert _run_identity(h1) == _run_identity(h3), "in-process and subprocess disagree"
    assert h1["verdict"]["digest"] == h2["verdict"]["digest"] == h3["verdict"]["digest"]


def test_the_sealed_verdict_agrees_across_processes(tmp_path, monkeypatch):
    """Parity of the RECORDED verdict, not just the in-memory one.

    The ledger row is what a later `--replay` is checked against and what the
    hash chain covers. Two harnesses, two databases, one answer.
    """
    lock = tmp_path / "locks"
    lock.mkdir()
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-harness-parity")

    db1 = tmp_path / "inprocess.db"
    db2 = tmp_path / "subprocess.db"
    _ensure_db(db1)
    _ensure_db(db2)

    monkeypatch.setenv("WING_DB_PATH", str(db1))
    h1 = run_harness(gate_set=SOLO, repo_root=REPO, lock_dir=lock, seal=True)
    h2 = _subprocess_harness(
        emit="judge", cwd=Path(tempfile.gettempdir()), lock_dir=lock, db=db2
    )

    assert h1["sealed"] and h2["sealed"], "one of the harnesses sealed nothing"
    assert _sealed_identity(h1["sealed"]) == _sealed_identity(h2["sealed"])
    assert h1["sealed"]["actor"] == ledger.ENGINE_ACTOR
    assert h1["sealed"]["result"] in ledger.RESULTS

    # Guard the guard: two EMPTY evidence blobs also compare equal.
    evidence = _sealed_identity(h1["sealed"])["evidence"]
    assert evidence["outcomes"].get(JUDGE) in ("pass", "fail"), evidence
    assert evidence["missing_judges"] == [], evidence


# ─────────────────────────────────────────────────────────────────────────────
# 2. WHY parity holds — the invariants underneath it
# ─────────────────────────────────────────────────────────────────────────────


def test_the_judge_runs_in_the_tree_it_was_given_not_the_callers_cwd(tmp_path):
    """A harness's own working directory must not reach the judge.

    Bone runs with launchd's cwd; a shell harness runs with the operator's. If
    that leaked, the same gate set would judge two different trees.
    """
    done = judges.real_spawn(
        [sys.executable, "-c", "import os; print(os.getcwd())"], str(tmp_path), 60
    )
    assert done.exit_code == 0, done.stderr
    assert Path(done.stdout.strip()).resolve() == tmp_path.resolve()


def test_no_judge_is_ever_handed_a_terminal(tmp_path):
    """Piped, always — a TTY would colour the very lines the work parser reads.

    `ansible-lint`'s work count comes out of a terminal line and corpus-diff's
    verdict comes out of stdout JSON. A CLI harness that let a judge inherit a
    terminal would get ANSI escapes in both, a different `stdout_sha`, and a
    verdict that cannot be replayed from the daemon.
    """
    done = judges.real_spawn(
        [sys.executable, "-c", "import sys; print(sys.stdout.isatty(), sys.stderr.isatty())"],
        str(tmp_path), 60,
    )
    assert done.stdout.strip() == "False False"

    src = JUDGES_PY.read_text(encoding="utf-8")
    assert "capture_output=True" in src, "the judge's output must never be inherited"
    assert "shell=True" not in src, "a shell would let the harness's env rewrite argv"


def test_both_harnesses_resolve_the_same_registry_from_the_source_not_the_cwd(tmp_path):
    """`state/judge-sets.yml` must mean the same thing from any directory.

    §2.1 puts the registry in the repo precisely so a gate set means one thing
    in CI, on the Mac and at 03:00. Resolving it relative to the CALLER's cwd
    would hand that promise back to whoever invoked the judge.
    """
    probe = _subprocess_harness(emit="probe", cwd=tmp_path)
    assert Path(probe["cwd"]).resolve() == tmp_path.resolve(), "the probe did not move"
    assert Path(probe["repo_root"]) == REPO
    assert probe["registry_digest"] == _registry_digest(judges.load_registry(REPO))


def test_the_registry_is_committed_and_not_runtime_state():
    """A registry under `~/.nos` drifts per host; a committed one is diffable."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "state/judge-sets.yml"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert tracked.returncode == 0, "state/judge-sets.yml is not tracked by git"
    assert judges.REGISTRY_RELPATH == "state/judge-sets.yml"
    src = JUDGES_PY.read_text(encoding="utf-8")
    assert "~/.nos" not in src and "NOS_LOOP_REGISTRY" not in src, (
        "the registry path became overridable — two harnesses could then read "
        "two different registries and both call the answer a verdict"
    )


def test_both_harnesses_name_the_same_exclusive_lock(tmp_path):
    """M7's mutex only excludes if the two harnesses name the same file.

    genome-codegen WRITES `nos_entity.py` and pytest-anatomy MUTATES it. If the
    lock path were per-process (a mkdtemp, a pid, a uuid), the mutex would be a
    no-op across harnesses and the two judges would corrupt each other's tree.

    CEILING, measured and stated: the DIRECTORY is `$TMPDIR`, so harnesses that
    do not share `$TMPDIR` do not share the lock. See this module's docstring.
    """
    probe = _subprocess_harness(emit="probe", cwd=tmp_path)
    here = str(judges._FileLock("nos_entity", Path(tempfile.gettempdir())).path)
    assert probe["default_lock_path"] == here
    assert Path(here).name == "nos-loop-nos_entity.lock", (
        "the lock file name must be a pure function of the resource name"
    )

    # ...and the runner must actually DEFAULT to that shared directory. A
    # `mkdtemp()` here would be per-process, unique, and would silently turn the
    # mutex into a no-op that every harness passes.
    tree = ast.parse(JUDGES_PY.read_text(encoding="utf-8"))
    runner = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "run_gate_set"
    )
    called = _called_names(runner)
    assert "tempfile.gettempdir" in called, "the runner's default lock dir moved"
    assert "tempfile.mkdtemp" not in called, "the runner's default lock dir is per-process"


def test_the_verdict_identity_excludes_every_harness_varying_field(tmp_path):
    """What the digest covers is what replay compares.

    Wall-clock times, the sandbox path, the pid and the cwd differ between two
    correct runs; evidence does not. A digest that included the first set would
    make cross-harness parity impossible, and one that excluded the second
    would make it meaningless.
    """
    payload = run_harness(gate_set=SOLO, repo_root=REPO, lock_dir=tmp_path, seal=False)
    blob = json.dumps(payload["verdict"], sort_keys=True)
    for varying in ("started_at", "finished_at", "sandbox_path", "cwd", "pid", "hostname"):
        assert varying not in blob, f"the verdict identity carries {varying}"
    run = payload["verdict"]["runs"][0]
    for evidence in ("exit_code", "work", "min_work", "stdout_sha", "argv", "result"):
        assert evidence in run, f"the verdict identity dropped {evidence}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. One implementation, reached by every harness (DECISION 6)
# ─────────────────────────────────────────────────────────────────────────────


def _bone_modules() -> list[Path]:
    return sorted(p for p in BONE.glob("*.py") if p.name != "judges.py")


def _called_names(tree: ast.AST) -> set[str]:
    """Dotted names of everything actually CALLED. Comments and docstrings
    cannot appear here, which is the whole reason this is an AST walk."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        parts = []
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(func.id)
        if parts:
            names.add(".".join(reversed(parts)))
    return names


SECOND_IMPLEMENTATION = (
    re.compile(r"^\s*ADAPTERS\s*[:=]", re.M),
    re.compile(r"^\s*def\s+_adapt", re.M),
    re.compile(r"\bGateSetVerdict\("),
    re.compile(r"\bResult\.PASS\b"),
)


def test_judgment_has_exactly_one_implementation_in_the_estate():
    """A second adapter table is a second oracle wearing the first one's name."""
    offenders = []
    for path in _bone_modules():
        text = path.read_text(encoding="utf-8")
        for pattern in SECOND_IMPLEMENTATION:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO)}: {pattern.pattern}")
    assert not offenders, (
        "a verdict is computed outside judges.py — two harnesses can then "
        "disagree while both are 'correct':\n  " + "\n  ".join(offenders)
    )


#: Directories that are not this repo's source: virtualenvs, caches, vendored
#: trees. `.ci-venv/` alone holds ~2800 .py files.
_NOT_SOURCE = {"node_modules", "__pycache__", "vendor", "site-packages", "tests"}


def _repo_python_sources() -> list[Path]:
    out = []
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if any(p.startswith(".") or p in _NOT_SOURCE for p in rel.parts):
            continue
        if str(rel).startswith("files/anatomy/bone/"):
            continue
        out.append(path)
    return out


def test_nothing_outside_bone_imports_the_judge_runner():
    """DECISION 6: HTTP is the only implementation, and the CLI is a client.

    An importer outside Bone is a second harness with its own in-process copy of
    the judgment — the "shared library, ever" the contract forbids, ported four
    ways for four runtimes and drifting four ways.

    Parsed, not grepped, for a reason this test learned about itself: the
    retro-verification harness CONTAINS the string `import judges` as mutation
    data. A text scan read that catalogue entry as an import and went red
    against a clean tree — a gate failing on a description of the defect rather
    than the defect.
    """
    offenders = []
    for path in _repo_python_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "judges" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:  # not importable anyway
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "judges" for a in node.names):
                offenders.append(str(path.relative_to(REPO)))
            elif isinstance(node, ast.ImportFrom) and node.module == "judges":
                offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "the judge runner is imported outside Bone: " + ", ".join(sorted(set(offenders)))
    )


def _route_paths(tree: ast.AST) -> list[str]:
    """Mounted routes, read from the DECORATORS — a docstring cannot mount one."""
    paths = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr not in ("get", "post", "put", "delete", "patch"):
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant):
                paths.append(str(dec.args[0].value))
    return paths


def test_any_mounted_judge_route_delegates_rather_than_deciding():
    """Binds now to whatever exists, and to the real route the day it lands.

    Not vacuous while the route is missing: in that state it asserts the
    stronger thing — that NO Bone module RUNS a gate set at all, which is what
    `test_judgment_has_exactly_one_implementation_in_the_estate` measures file
    by file and this one measures at the route surface.

    Read from the AST, not from text: `ledger.py`'s docstring NAMES
    `judges.run_gate_set()` while calling nothing, and an earlier draft of this
    test read that sentence as the behaviour it describes — the same
    documentation-as-evidence mistake §0 of the contract exists to refuse.
    """
    routed, callers = [], []
    for path in _bone_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        routed += [(path, r) for r in _route_paths(tree) if "judge" in r]
        if {"run_gate_set", "judges.run_gate_set"} & _called_names(tree):
            callers.append(path)

    if not routed:
        assert not callers, (
            "a Bone module runs gate sets but mounts no judge route — say which "
            f"is true: {[str(p.name) for p in callers]}"
        )
        return

    for path, route in routed:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert {"run_gate_set", "judges.run_gate_set"} & _called_names(tree), (
            f"{path.name} mounts {route} without delegating to the runner"
        )
        assert not re.search(
            r"\bresult\s*[:=]\s*(?:body|payload|request)",
            path.read_text(encoding="utf-8"),
        ), f"{path.name} reads a result out of a request — §3.1 deleted that route"


def test_the_verdict_to_exit_code_map_is_declared_once_and_covers_every_verdict():
    """A CLI must MAP the three values, never re-derive or collapse them.

    DECISION 6a separates INDETERMINATE from FAIL at the shell boundary so a
    wrapper cannot quietly turn "the organ was down" into "your patch is bad".
    """
    for member in judges.Result:
        assert member.value in judges.CLI_EXIT, f"{member.value} has no exit code"
    assert judges.CLI_EXIT["pass"] == 0
    assert len({judges.CLI_EXIT[r.value] for r in judges.Result}) == len(judges.Result), (
        "two verdict values share one exit code — that is the collapse 6a forbids"
    )

    declarers = [
        p.relative_to(REPO)
        for p in BONE.glob("*.py")
        if re.search(r"^\s*CLI_EXIT\s*[:=]", p.read_text(encoding="utf-8"), re.M)
    ]
    assert declarers == [Path("files/anatomy/bone/judges.py")], declarers


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONSTRAINT E — loopback only, and declared
# ─────────────────────────────────────────────────────────────────────────────

LOOP_ENGINE_MODULES = ("judges.py", "ledger.py", "loopauth.py", "weaknesses.py")


def test_no_engine_module_opens_a_socket_or_a_port():
    """Parsed, not grepped: judges.py's docstring says it binds nothing, and a
    grep would happily read that sentence as the evidence for itself."""
    forbidden_calls = {"socket.socket", "uvicorn.run", "serve_forever"}
    for name in LOOP_ENGINE_MODULES:
        tree = ast.parse((BONE / name).read_text(encoding="utf-8"))
        called = _called_names(tree)
        assert not (called & forbidden_calls), f"{name} opens a socket: {called & forbidden_calls}"
        assert not {c for c in called if c.endswith((".bind", ".listen"))}, name
        literals = {
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        assert "0.0.0.0" not in literals, f"{name} names a wildcard bind address"


def test_bone_binds_loopback_under_both_service_managers():
    """The engine adds no process, so E is Bone's bind — on macOS AND Linux."""
    plist = BONE_PLIST.read_text(encoding="utf-8")
    assert re.search(r"<string>--host</string>\s*<string>127\.0\.0\.1</string>", plist), (
        "the launchd unit no longer pins the loopback bind"
    )
    tasks = BONE_TASKS.read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in tasks, "the systemd ExecStart no longer pins loopback"
    assert "0.0.0.0" not in plist and "0.0.0.0" not in tasks


def test_every_mounted_loop_route_sits_behind_a_loop_scope_dependency():
    for route in weaknesses.router.routes:
        quals = [d.call.__qualname__ for d in route.dependant.dependencies]
        assert any(q.startswith("require_loop_scope") for q in quals), (
            f"{route.path} is mounted without a loop-scope dependency: {quals}"
        )


def test_every_mounted_loop_route_refuses_a_non_loopback_client(loop_tokens):
    """REM-144 was a service whose loopback bind was real and IRRELEVANT — the
    edge proxied around it. Bind AND check, on every route, with a VALID token
    so the refusal is about the address and nothing else."""
    app = FastAPI()
    app.include_router(weaknesses.router)
    assert weaknesses.router.routes, "no loop routes are mounted — nothing measured"
    with TestClient(app, client=("192.168.1.50", 4000)) as client:
        for route in weaknesses.router.routes:
            path = re.sub(r"\{[^}]+\}", "x", route.path)
            resp = client.get(path, headers={"Authorization": f"Bearer {PROPOSE_TOKEN}"})
            assert resp.status_code == 403, f"{path} answered {resp.status_code}"
            assert "loopback" in resp.json()["detail"]


def test_the_loop_declares_no_new_routable_surface():
    """A `state/manifest.yml` id with domain_var + port_var auto-derives a
    Traefik router. That is precisely how REM-144 happened, and §5.2 forbids the
    loop from touching that file for the same reason this test reads it."""
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    services = manifest.get("services") or []
    ids = {str(s.get("id", "")) for s in services}
    assert not {i for i in ids if i.startswith("loop") or i.startswith("nos-loop")}, (
        "the loop acquired a manifest entry — and with it an edge route"
    )
    skip = yaml.safe_load(TRAEFIK_VARS.read_text(encoding="utf-8"))["traefik_skip_ids"]
    assert "bone" in skip, (
        "bone left traefik_skip_ids — its manifest entry carries domain_var + "
        "port_var, so the loop API is now auto-routed to the edge (REM-144)"
    )


def test_the_loopback_allowlist_holds_only_loopback():
    assert loopauth.LOOPBACK_HOSTS <= {"127.0.0.1", "::1", "localhost", "testclient"}


# ─────────────────────────────────────────────────────────────────────────────
# 5. CONSTRAINT D — no new prefix-derived credential
# ─────────────────────────────────────────────────────────────────────────────


def _blast_radius_module():
    """Reuse the ratchet's own measurement rather than re-deriving it here.

    A second implementation of "what counts as derived" is exactly the drift
    this file argues against one section up.
    """
    path = REPO / "tests" / "anatomy" / "test_secret_blast_radius.py"
    spec = importlib.util.spec_from_file_location("nos_blast_radius", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_no_loop_credential_is_prefix_derived():
    """`{prefix}_pw_{svc}` is concatenation, not derivation: the rendered value
    carries the master in clear, so one leak yields the set."""
    blast = _blast_radius_module()
    declared, _, _ = blast._scan()
    assert not {n for n in declared if "loop" in n}, (
        "a loop credential is minted by concatenating the master prefix"
    )

    for key in LOOP_TOKEN_KEYS:
        for path in (REPO / "default.credentials.yml", BONE_PLIST, REPO / "templates/secrets.yml.j2"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if key in line and "global_password_prefix" in line:
                    raise AssertionError(f"{path.name}: {key} is derived — {line.strip()}")


def test_the_loop_tokens_are_minted_random_and_persisted():
    """Random is only half of it: a token regenerated every run is not a
    boundary, it is an outage. Mint AND persist, or the split is theatre."""
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    secrets = (REPO / "templates" / "secrets.yml.j2").read_text(encoding="utf-8")
    for key in LOOP_TOKEN_KEYS:
        assert re.search(rf"^\s*{key}:.*openssl rand -hex 32", main, re.M), (
            f"{key} is not in main.yml's lazy-regenerate group"
        )
        assert re.search(rf"^{key}:", secrets, re.M), (
            f"{key} is not persisted to ~/.nos/secrets.yml"
        )


def test_a_prefix_derived_loop_token_authenticates_nothing(monkeypatch):
    """The repo gate keeps the declaration honest; this keeps the RUNTIME
    honest — the kept lesson of the blast-radius file about itself."""
    derived = "changeme_pw_loop_judge" + "x" * 40
    monkeypatch.setenv("BONE_LOOP_JUDGE_TOKEN", derived)
    monkeypatch.delenv("BONE_LOOP_PROPOSE_TOKEN", raising=False)
    assert loopauth.scopes_for_token(derived) is None
    assert loopauth._configured() == {}, "a derived token was accepted as configured"


def test_the_loop_did_not_move_the_blast_radius_ratchet():
    """The ceiling is a ratchet: it may fall as the plan lands, never rise.

    If this engine's work raised it, that is a defect in this engine — not a
    ceiling to lift.
    """
    blast = _blast_radius_module()
    assert blast.BLAST_RADIUS_CEILING <= 86, (
        f"the runtime blast-radius ceiling was RAISED to "
        f"{blast.BLAST_RADIUS_CEILING}; the loop must add no derived credential"
    )
    declared, _, _ = blast._scan()
    runtime = declared - blast._lazy_regenerated()
    assert len(runtime) <= blast.BLAST_RADIUS_CEILING


if __name__ == "__main__":  # H3 — the same code, in another process
    sys.exit(_driver_main())
