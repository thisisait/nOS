"""judges.py — the judge runner: the callable core of the agentic loop.

Contract: ``docs/idea/11-agentic-loop-contract.md`` §2 (the judge contract),
built as §10 step 1. **HTTP is deliberately not wired here.** DECISION 6 makes
HTTP the only implementation and the CLI a thin client over it; this module is
the callable core that ``POST /api/v1/loop/judge`` will mount in step 1b. It
exports no CLI for the same reason — a CLI importing this library would be the
"shared library, ever" that DECISION 6 forbids.

WHAT THIS MODULE IS
    Give it a gate set NAME. It runs that set's judges as subprocesses and
    returns a three-valued, structured verdict. That is the whole surface.

WHAT IT REFUSES TO BE (constraint A — the judge is code, the proposer is a
model, and they never share an identity)
    There is no parameter, anywhere in this module's public API, that supplies
    or influences a result. ``run_gate_set`` takes a gate set name. A verdict is
    computed from an exit code, a parsed work count and a parsed report — all of
    them read *out of a subprocess that actually ran*.

    THE ONE SEAM, STATED HONESTLY. ``spawn`` is injectable, and a test double
    passes one in. That double replaces THE PROCESS, not THE JUDGMENT: it may
    say "the command exited 2 and printed this text", exactly as a real process
    would, and the adapter then computes the verdict from that text the same way
    it does in production. A double cannot return ``Result.PASS``; the adapters
    are the only code in the estate that constructs a ``Result``, and they are
    not injectable. This is the difference between mocking a subprocess and
    mocking an oracle, and the gate
    ``test_no_seam_can_supply_a_result`` pins it.

FAIL CLOSED, EVERYWHERE (§2.4)
    Three of five judges return 0 when they did no work. That is the same defect
    as ``docs/hidden_fees/08-empty-stack-reads-as-success.md``, sitting inside
    the judges the loop depends on. Every path that cannot produce evidence of
    real work resolves to INDETERMINATE, never PASS:

      · a requirement is absent            → INDETERMINATE, judge never runs
      · the executable/script is missing   → INDETERMINATE
      · the sandbox cannot be created      → INDETERMINATE
      · the exclusive resource is held     → INDETERMINATE
      · the process was killed/timed out   → INDETERMINATE
      · the exit code is outside pass/fail → INDETERMINATE
      · the report cannot be parsed        → INDETERMINATE
      · work_count is 0, unparseable, or   → INDETERMINATE
        below the ratchet, on a PASS
      · the gate set is empty              → INDETERMINATE

    INDETERMINATE is recorded DISTINCTLY from FAIL, because conflating them
    would teach the loop to "fix" proposals in response to an unplugged organ.
    Both block acceptance.

CONSTRAINT B — a step may not record its own success
    A run record is created with ``status="running"`` BEFORE the subprocess is
    spawned, and is completed by the code that reads the process's exit — never
    by the judge. A killed judge leaves ``status="crashed"`` and its set is
    INDETERMINATE, never PASS. ``work_count`` is parsed from the subprocess's
    own stdout/stderr and is never supplied by a caller.
    Precedent: ``tests/anatomy/test_post_wiring_is_not_self_reporting.py``.

CONSTRAINT E — nothing here binds a socket, opens a port or reaches the network.
    It spawns local subprocesses and returns a value.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml

__all__ = [
    "Result",
    "JudgeSpec",
    "Completed",
    "JudgeRun",
    "GateSetVerdict",
    "ConfigError",
    "load_registry",
    "run_gate_set",
    "apply_proposal_diff",
    "judge_spawn_env",
    "probe_interpreter",
    "CLI_EXIT",
]

REGISTRY_RELPATH = "state/judge-sets.yml"

# DECISION 6a — a fixed small enum, explicitly NOT nos-smoke's exit-as-count,
# and explicitly separating INDETERMINATE from FAIL at the shell boundary so a
# wrapper cannot collapse them. Exported as data; the CLI that consumes it is an
# HTTP client and does not import this module.
CLI_EXIT = {
    "pass": 0,
    "fail": 1,
    "indeterminate": 2,
    "refused": 3,
    "config_error": 4,
}


class ConfigError(Exception):
    """The registry or the requested gate set is malformed/unknown.

    Distinct from every verdict value: a typo in a gate set name must not be
    reportable as a FAIL (which would read as "the tree is bad") nor as a PASS.
    """


class Result(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JudgeSpec:
    """One judge, exactly as declared in ``state/judge-sets.yml``.

    Every field is data a test can read (§2.1). ``argv`` includes the
    side-effect-suppressing flags (``--no-jsonl``, ``--no-ledger``) as committed
    text, so removing one is a visible diff and not a runtime surprise.
    """

    name: str
    argv: tuple[str, ...]
    adapter: str
    pass_exit: tuple[int, ...] = ()
    fail_exit: tuple[int, ...] = ()
    deterministic: bool = True
    runtime_s_p95: int = 60
    timeout_s: int = 600
    work_field: str = "work"
    work_regex: str | None = None
    work_regex_group: int = 1
    work_json_field: str | None = None
    json_field: str | None = None
    min_work: int = 1
    #: Declares that this judge WRITES tracked files. Since §2.5 was actually
    #: enforced, every judge is sandboxed, so this no longer selects behaviour —
    #: it stays as the committed reason the sandbox exists at all, and as the
    #: pairing with `exclusive_resource` (two writers of `nos_entity.py`).
    mutates_worktree: bool = False
    requires: tuple[str, ...] = ()
    exclusive_resource: str | None = None
    #: §5.1 — the paths that ARE this judge's oracle. The budget forbids them
    #: for any gate set this judge is a member of, which is why they live on the
    #: judge and not in a constant: a set that does not run pytest-anatomy has
    #: no business claiming `tests/anatomy/**`, and a set that does must.
    #: Required by `load_registry` — see the ConfigError there.
    oracle_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateSetSpec:
    name: str
    judges: tuple[str, ...]
    unattended: bool = False


@dataclass(frozen=True)
class Registry:
    judges: Mapping[str, JudgeSpec]
    gate_sets: Mapping[str, GateSetSpec]

    def gate_set(self, name: str) -> GateSetSpec:
        try:
            return self.gate_sets[name]
        except KeyError:
            raise ConfigError(
                f"unknown gate set {name!r}; known: {sorted(self.gate_sets)}"
            ) from None


def _as_int_tuple(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    return tuple(int(v) for v in value)


def load_registry(repo_root: str | os.PathLike[str] | None = None) -> Registry:
    """Read ``state/judge-sets.yml``. Raises ConfigError on anything malformed.

    Deliberately strict: an unknown adapter or a gate set naming an undeclared
    judge is a ConfigError at LOAD time, not an INDETERMINATE at run time. A
    registry that half-loads is a registry that silently shrinks a gate set,
    which is the ``min_work`` failure mode one level up.
    """
    root = Path(repo_root) if repo_root else _default_repo_root()
    path = root / REGISTRY_RELPATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"judge registry not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"judge registry is not valid YAML: {exc}") from None

    if not isinstance(raw, dict):
        raise ConfigError(f"judge registry must be a mapping: {path}")

    judges: dict[str, JudgeSpec] = {}
    for name, body in (raw.get("judges") or {}).items():
        if not isinstance(body, dict):
            raise ConfigError(f"judge {name!r} must be a mapping")
        argv = body.get("argv")
        if not argv or not isinstance(argv, list):
            raise ConfigError(f"judge {name!r} has no argv")
        adapter = body.get("adapter")
        if adapter not in ADAPTERS:
            raise ConfigError(
                f"judge {name!r} has unknown adapter {adapter!r}; "
                f"known: {sorted(ADAPTERS)}"
            )
        # §5.1, fail-closed: a judge that declares no oracle is a judge whose
        # own source the loop may edit while being graded by it. An omission
        # must therefore be LOUD at load time — the alternative is a budget
        # that silently shrinks, which is `min_work`'s failure mode moved one
        # layer out.
        oracles = body.get("oracle_paths")
        if not oracles or not isinstance(oracles, list):
            raise ConfigError(
                f"judge {name!r} declares no oracle_paths; §5.1 requires them "
                "so the budget can forbid the judge's own source"
            )
        judges[name] = JudgeSpec(
            name=name,
            argv=tuple(str(a) for a in argv),
            adapter=str(adapter),
            pass_exit=_as_int_tuple(body.get("pass_exit")),
            fail_exit=_as_int_tuple(body.get("fail_exit")),
            deterministic=bool(body.get("deterministic", True)),
            runtime_s_p95=int(body.get("runtime_s_p95", 60)),
            timeout_s=int(body.get("timeout_s", 600)),
            work_field=str(body.get("work_field", "work")),
            work_regex=body.get("work_regex"),
            work_regex_group=int(body.get("work_regex_group", 1)),
            work_json_field=body.get("work_json_field"),
            json_field=body.get("json_field"),
            min_work=int(body.get("min_work", 1)),
            mutates_worktree=bool(body.get("mutates_worktree", False)),
            requires=tuple(body.get("requires") or ()),
            exclusive_resource=body.get("exclusive_resource"),
            oracle_paths=tuple(str(p) for p in oracles),
        )

    gate_sets: dict[str, GateSetSpec] = {}
    for name, body in (raw.get("gate_sets") or {}).items():
        if not isinstance(body, dict):
            raise ConfigError(f"gate set {name!r} must be a mapping")
        members = tuple(body.get("judges") or ())
        unknown = [j for j in members if j not in judges]
        if unknown:
            raise ConfigError(f"gate set {name!r} names undeclared judges: {unknown}")
        gate_sets[name] = GateSetSpec(
            name=name,
            judges=members,
            unattended=bool(body.get("unattended", False)),
        )

    if not judges or not gate_sets:
        raise ConfigError(f"judge registry declares no judges or no gate sets: {path}")
    return Registry(judges=judges, gate_sets=gate_sets)


def _default_repo_root() -> Path:
    """Where the repo is — ASKED of the environment, never inferred from here.

    Was `Path(__file__).resolve().parents[3]`, which holds in the checkout and
    is false in the estate. Bone is DEPLOYED to a flat `~/bone/`, so those four
    parents resolve to `/` and every judge run inside the daemon died on

        unknown gate set: judge registry not found: /state/judge-sets.yml

    The reader half of the same engine never had the bug, because it asks
    `PLAYBOOK_DIR` — which the launchd plist sets to the checkout. Two modules,
    one fact, two answers; the module that inferred was the one that was wrong.

    NO TEST COULD HAVE CAUGHT IT AS WRITTEN: `load_registry()` takes the root as
    a PARAMETER and every harness passes it explicitly, so this default is
    reached only in production. That is why `test_loop_repo_root_is_asked.py`
    tests the resolver itself rather than a run that supplies its own answer.

    THE ORDER IS LOAD-BEARING, and the first repair got it wrong by falling
    back to `os.getcwd()` — which the determinism gate forbids for a good
    reason: resolving the registry against the CALLER's directory hands "a gate
    set means one thing in CI, on the Mac and at 03:00" back to whoever invoked
    the judge. So:

        1. NOS_LOOP_REPO_ROOT  — explicit override, wins
        2. PLAYBOOK_DIR        — Bone's convention; the launchd plist sets it
        3. the source location — VALIDATED by finding the registry there, which
           is true in a checkout and false once deployed, so it cannot silently
           return `/` the way the original did
        4. nothing             — a named failure, never the caller's cwd
    """
    for name in ("NOS_LOOP_REPO_ROOT", "PLAYBOOK_DIR"):
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    from_source = Path(__file__).resolve().parents[3]
    if (from_source / REGISTRY_RELPATH).is_file():
        return from_source
    raise ConfigError(
        "cannot locate the repo: NOS_LOOP_REPO_ROOT and PLAYBOOK_DIR are both "
        f"unset, and {from_source / REGISTRY_RELPATH} does not exist. This "
        "module is running from a DEPLOYED copy (Bone installs to a flat "
        "~/bone/), where its own location says nothing about where the repo is. "
        "Set PLAYBOOK_DIR — the launchd plist already does."
    )


# ─────────────────────────────────────────────────────────────────────────────
# The process boundary
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Completed:
    """What a subprocess did. NOT what it means.

    ``exit_code is None`` means the process never delivered an exit status —
    killed, timed out, or never started. That is never a PASS.
    """

    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def output(self) -> str:
        """stdout + stderr.

        MEASURED: ansible-lint writes its terminal work line
        ("… in 1400 files processed of 2979 encountered.") to STDERR. A parser
        that read stdout alone would find no work count and report every green
        ansible-lint run as INDETERMINATE.
        """
        return f"{self.stdout}\n{self.stderr}"


class ExecutableMissing(Exception):
    """argv[0] (or the script it names) is not present. A requirement, absent."""


def _private_interpreter_bins() -> frozenset[str]:
    """The bin dirs of THIS process's interpreter — but only if it is a venv.

    A virtualenv is a private, purpose-built environment (Bone's exact shape:
    the daemon runs from ~/bone/venv); it is never the estate's toolchain. A
    system, pyenv or CI-toolcache interpreter (sys.prefix == sys.base_prefix)
    IS the toolchain the judges are supposed to resolve against, so it is
    never filtered — filtering it would orphan every judge in CI.
    """
    if sys.prefix == sys.base_prefix:
        return frozenset()
    bins = {os.path.realpath(os.path.dirname(sys.executable))}
    for prefix in (sys.prefix, sys.exec_prefix):
        bins.add(os.path.realpath(os.path.join(prefix, "bin")))
    return frozenset(bins)


def judge_spawn_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment every judge subprocess runs under.

    MEASURED on the first real `repo` turn against the deployed daemon
    (2026-08-03): Bone's launchd PATH put the daemon's own venv bin first, so
    the committed argv `python3 -m pytest` resolved to ~/bone/venv/bin/python3
    — an interpreter with NO pytest ("No module named pytest") — and every gate
    set containing pytest-anatomy was permanently INDETERMINATE. The daemon's
    PRIVATE interpreter is not the estate's toolchain, so its bin dirs are
    filtered out of the judges' PATH HERE, in the engine, regardless of how any
    deployment ordered its PATH (the plist reorder ships as belt-and-braces;
    the engine must not depend on deployment).

    `VIRTUAL_ENV` is dropped for the same reason: it advertises the daemon's
    venv to child launchers that consult it.
    """
    env = dict(os.environ if base is None else base)
    env.pop("VIRTUAL_ENV", None)
    own = _private_interpreter_bins()
    if own:
        kept = [
            p for p in env.get("PATH", "").split(os.pathsep)
            if p and os.path.realpath(p) not in own
        ]
        env["PATH"] = os.pathsep.join(kept) or os.defpath
    return env


def real_spawn(
    argv: Sequence[str],
    cwd: str,
    timeout_s: int,
    env: Mapping[str, str] | None = None,
) -> Completed:
    """The production process boundary. No shell, ever.

    `env=None` inherits the caller's environment; the runner always passes the
    filtered `judge_spawn_env()` so a judge never resolves its tools inside the
    daemon's private venv. POSIX resolution of a bare argv[0] uses the PATH of
    the env PASSED here (verified empirically), so the filter reaches the
    exec itself, not just `shutil.which` bookkeeping.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — argv is committed data, never user text
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=dict(env) if env is not None else None,
        )
    except FileNotFoundError as exc:
        raise ExecutableMissing(str(exc)) from None
    except subprocess.TimeoutExpired as exc:
        return Completed(
            exit_code=None,
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr),
            timed_out=True,
        )
    return Completed(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _text(v: Any) -> str:
    if v is None:
        return ""
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


# ─────────────────────────────────────────────────────────────────────────────
# Adapters — the ONLY code that constructs a Result (§2.2)
# ─────────────────────────────────────────────────────────────────────────────


def _adapt_exit_zero(spec: JudgeSpec, done: Completed) -> tuple[Result, str]:
    """0 = pass, listed non-zero = fail, ANYTHING ELSE = INDETERMINATE.

    ansible-lint's failure code is 2. A naive ``!= 0`` is right by accident and
    a naive ``== 1`` is wrong, so both lists are explicit and the space outside
    them is unknown rather than guessed.
    """
    if done.exit_code in spec.pass_exit:
        return Result.PASS, f"exit {done.exit_code} in pass_exit"
    if done.exit_code in spec.fail_exit:
        return Result.FAIL, f"exit {done.exit_code} in fail_exit"
    return Result.INDETERMINATE, (
        f"exit {done.exit_code} is in neither pass_exit={list(spec.pass_exit)} "
        f"nor fail_exit={list(spec.fail_exit)} — unknown, not assumed"
    )


def _adapt_exit_count(spec: JudgeSpec, done: Completed) -> tuple[Result, str]:
    """nos-smoke: the exit code IS the failure count, capped at 127."""
    code = done.exit_code
    if code == 0:
        return Result.PASS, "0 failures"
    if code is not None and 1 <= code <= 126:
        return Result.FAIL, f"{code} failing probe(s)"
    return Result.INDETERMINATE, f"exit {code} is outside the 0..126 count range"


def _adapt_json_field(spec: JudgeSpec, done: Completed) -> tuple[Result, str]:
    """corpus-diff: the exit code is NOT the verdict; ``.agrees`` is.

    Under --no-ledger the script returns `3 if removalShaped else 0`, so a
    DISAGREE report exits 0. And on the "cortex unreachable" path it prints no
    JSON at all and returns 0 — an unparseable report is INDETERMINATE, which
    is what corrects the script's own `night VOID → 0`.
    """
    report = _parse_json_report(done.stdout)
    if report is None:
        return Result.INDETERMINATE, (
            "no parseable JSON report on stdout — the judge produced no verdict "
            "(organ unreachable prints nothing and still exits 0)"
        )
    if spec.json_field not in report:
        return Result.INDETERMINATE, f"report has no {spec.json_field!r} field"
    value = report[spec.json_field]
    if not isinstance(value, bool):
        return Result.INDETERMINATE, (
            f"{spec.json_field!r} is {type(value).__name__}, not a bool"
        )
    return (Result.PASS, f"{spec.json_field} is true") if value else (
        Result.FAIL,
        f"{spec.json_field} is false",
    )


_PYTEST_SUMMARY = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed)")


def _adapt_pytest_summary(spec: JudgeSpec, done: Completed) -> tuple[Result, str]:
    """pytest: exit 0 covers "all skipped" (M3), so parse the summary line.

    SKIPPED IS NOT WORK. That single decision is what closes the measured false
    green where `HOME=/tmp/emptyhome pytest test_hub_url_audit.py` reports
    "2 skipped" and exits 0.

    AND THE EXIT CODE STILL GATES THE PASS. MEASURED on this tree: SIGINT to the
    pytest child 20 s in prints `!!!! KeyboardInterrupt !!!!` and then a
    well-formed `454 passed in 19.94s`, exiting **2** — 454 of 2432 tests, a 20%
    run, with a pass-shaped summary. An adapter that read only the summary
    called that a PASS, and the work ratchet could not see it either (454 was
    above the old floor). pytest's own codes are the vocabulary: 0 = all ran and
    all passed, 1 = tests failed, 2 = INTERRUPTED, 3 = internal error, 4 = usage
    error, 5 = nothing collected. Only 0 may reach PASS. A summary reporting
    failures is still a FAIL whatever the code — a red is a red, and downgrading
    it to INDETERMINATE would hide it (the ordering rule of DECISION 2b).
    """
    counts = _pytest_counts(done.output)
    if counts is None:
        return Result.INDETERMINATE, "no parseable pytest summary line"
    failed = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    if failed:
        return Result.FAIL, f"{failed} failing test(s)"
    if done.exit_code != 0:
        return Result.INDETERMINATE, (
            f"the summary reports no failures but pytest exited {done.exit_code} "
            f"(0 is the only code that means 'the whole run completed'; 2 is an "
            f"interrupt, which prints a pass-shaped partial summary) — a run that "
            f"did not finish has not shown it passed"
        )
    return Result.PASS, f"{counts.get('passed', 0)} passed, {counts.get('skipped', 0)} skipped"


ADAPTERS: dict[str, Callable[[JudgeSpec, Completed], tuple[Result, str]]] = {
    "exit_zero": _adapt_exit_zero,
    "exit_count": _adapt_exit_count,
    "json_field": _adapt_json_field,
    "pytest_summary": _adapt_pytest_summary,
}


def _pytest_counts(text: str) -> dict[str, int] | None:
    matches = _PYTEST_SUMMARY.findall(text or "")
    if not matches:
        return None
    counts: dict[str, int] = {}
    for number, word in matches:
        counts[word] = counts.get(word, 0) + int(number)
    return counts


def _parse_json_report(stdout: str) -> dict[str, Any] | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Tolerate a leading banner: take the last balanced object.
        start = text.find("{")
        if start < 0:
            return None
        try:
            parsed = json.loads(text[start:])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


# ─────────────────────────────────────────────────────────────────────────────
# Work counting (§2.4) — parsed from the process, never supplied
# ─────────────────────────────────────────────────────────────────────────────


def work_count(spec: JudgeSpec, done: Completed) -> int | None:
    """How much the judge actually did. ``None`` = could not tell.

    Never accepts a caller-supplied number. Every source here is the
    subprocess's own output.
    """
    if spec.adapter == "pytest_summary":
        counts = _pytest_counts(done.output)
        if counts is None:
            return None
        # Executed = passed + failed + errors. Skipped is NOT executed.
        return (
            counts.get("passed", 0)
            + counts.get("failed", 0)
            + counts.get("error", 0)
            + counts.get("errors", 0)
        )

    if spec.work_json_field:
        report = _parse_json_report(done.stdout)
        if report is None or spec.work_json_field not in report:
            return None
        value = report[spec.work_json_field]
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, (list, dict, str)):
            return len(value)
        return None

    if spec.work_regex:
        match = re.search(spec.work_regex, done.output)
        if not match:
            return None
        try:
            return int(match.group(spec.work_regex_group))
        except (IndexError, ValueError):
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Requirements (§2.c) — deny by default
# ─────────────────────────────────────────────────────────────────────────────


def default_requirement_probe(requirement: str) -> bool:
    """Is a declared requirement satisfied? Unknown requirement → False.

    Deny-by-default, the same posture as §5's budget. An unrecognised
    requirement name resolves to absent, so a typo makes a judge INDETERMINATE
    rather than silently unguarded.
    """
    if requirement == "keap_token_ro":
        return bool(os.environ.get("KEAP_AGENT_TOKEN_RO", "").strip())
    if requirement == "cortex_token_ro":
        return bool(os.environ.get("CORTEX_AGENT_TOKEN_RO", "").strip())
    if requirement == "docker":
        return shutil.which("docker") is not None
    if requirement == "live_estate":
        # Honest and narrow: the estate is "live" only if the container runtime
        # answers. Anything softer would let `nos-smoke`'s zero-entry false
        # green back in through the requirement door.
        if shutil.which("docker") is None:
            return False
        try:
            proc = subprocess.run(  # noqa: S603
                ["docker", "ps", "--quiet"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0 and bool(proc.stdout.strip())
    return False


def _executable_present(
    spec: JudgeSpec, repo_root: Path, env: Mapping[str, str] | None = None
) -> tuple[str | None, str | None]:
    """Resolve argv[0] under the JUDGE env and say why it cannot run, if so.

    Returns ``(resolved_path, reason)`` — exactly one is None. Resolution is
    against the env the judge will actually be spawned with, NOT the daemon's:
    resolving against the daemon's PATH and spawning with the filtered one
    would answer "is it present" about a different world than the one that
    runs (A4's defect shape, one step earlier).
    """
    exe = spec.argv[0]
    search = (env or os.environ).get("PATH", os.defpath)
    resolved = exe if os.path.isabs(exe) else shutil.which(exe, path=search)
    if resolved is None or not os.path.isfile(resolved):
        return None, f"executable {exe!r} not found on PATH"
    # `python3 tools/x.py` — the script itself is the real requirement.
    for arg in spec.argv[1:]:
        if arg.endswith(".py"):
            if not (repo_root / arg).is_file() and not Path(arg).is_file():
                return None, f"script {arg!r} not found under {repo_root}"
            break
        if arg.startswith("-"):
            continue
        break
    return os.path.realpath(resolved), None


#: `<resolved> --version` is stable for a given binary within a process
#: lifetime, and ansible-lint's answer takes seconds — cache it. CEILING,
#: stated: a pyenv SHIM's version can depend on env/cwd, so the cache key is
#: the resolved path only; two judge envs resolving to the SAME shim would
#: share one probe. Today's filter changes WHICH path resolves, not what a
#: fixed path answers, so the key is honest for every measured case.
_VERSION_CACHE: dict[str, str | None] = {}


def probe_interpreter(resolved: str, env: Mapping[str, str]) -> str | None:
    """What `<resolved> --version` says, probed from a REAL subprocess.

    A4's defect: `identity()` recorded the LITERAL argv ("python3"), so the
    record could not distinguish the dev pyenv interpreter (2488 tests
    collected) from Bone's pytest-less venv ("No module named pytest") — the
    same argv, the same tree_sha, two different worlds, one identity. The
    probe is evidence read out of a subprocess, never a caller's claim
    (constraint B); a tool that does not speak `--version` records None,
    honestly, rather than a guess.
    """
    if resolved in _VERSION_CACHE:
        return _VERSION_CACHE[resolved]
    try:
        proc = subprocess.run(  # noqa: S603 — resolved from committed argv
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=dict(env),
        )
        lines = [
            ln.strip()
            for ln in f"{proc.stdout}\n{proc.stderr}".splitlines()
            if ln.strip()
        ]
        value = lines[0] if proc.returncode == 0 and lines else None
    except (OSError, subprocess.SubprocessError):
        value = None
    _VERSION_CACHE[resolved] = value
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Exclusive resources (M7) and the sandbox (§2.5)
# ─────────────────────────────────────────────────────────────────────────────


class _ResourceBusy(Exception):
    pass


class _FileLock:
    """O_EXCL lock guarding a shared mutated file.

    M7: ``genome-codegen`` WRITES ``files/anatomy/module_utils/nos_entity.py``
    and ``test_genome_contract.py`` MUTATES the same file. There is no lock
    upstream, so concurrent runs corrupt each other. Never blocks: a held lock
    is INDETERMINATE, because waiting an unbounded time inside an unattended
    03:00 cycle is its own failure mode.
    """

    def __init__(self, resource: str, lock_dir: Path) -> None:
        self.path = lock_dir / f"nos-loop-{resource}.lock"
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise _ResourceBusy(f"resource lock held: {self.path}") from None
            raise
        os.write(self._fd, f"{os.getpid()}\n".encode())
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
        self.path.unlink(missing_ok=True)


class SandboxError(Exception):
    pass


def git_worktree_sandbox(repo_root: Path) -> tuple[Path, str, Callable[[], None]]:
    """Create an ephemeral detached git worktree. Returns (path, tree_sha, cleanup).

    DECISION 2d / §2.5 — EVERY judge of a set runs here, attended and unattended
    alike. Two reasons, and the second is why this moved out of `_run_one`:

      * a killed run otherwise leaves a TRACKED source file corrupted
        (test_genome_contract.py appends HAND_EDITED and restores in a
        `finally`), and being killed is an unattended loop's normal failure mode;
      * MEASURED defect this closes: with only `mutates_worktree` judges
        sandboxed, gate set `repo` ran ansible-lint and genome-codegen against
        the LIVE, possibly dirty tree while pytest-anatomy ran against HEAD, and
        aggregated the two as if they described one thing. An uncommitted edit
        to `.ansible-lint` — no proposal, no fingerprint, no diff — silenced a
        judge in every set containing it. §2.5 says the engine enforces one
        tree; it did not, so now it does.

    The sha is READ BACK OUT of the created tree rather than assumed, because
    the identity of what was judged is evidence and evidence is measured.
    """
    tmp = Path(tempfile.mkdtemp(prefix="nos-loop-sandbox-"))
    target = tmp / "tree"
    proc = subprocess.run(  # noqa: S603
        ["git", "worktree", "add", "--detach", str(target), "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SandboxError(f"git worktree add failed: {proc.stderr.strip()[:400]}")

    def cleanup() -> None:
        subprocess.run(  # noqa: S603
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)

    head = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"],
        cwd=str(target),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    sha = head.stdout.strip()
    if head.returncode != 0 or not sha:
        cleanup()
        raise SandboxError(
            "the sandbox exists but will not name its own commit — a verdict "
            "that cannot say which tree it judged is a claim"
        )
    return target, sha, cleanup


def apply_proposal_diff(sandbox: Path, diff_text: str) -> str:
    """Apply a proposal's STORED diff inside the sandbox; return the judged
    tree's own name (`git write-tree`).

    A1, the review's headline finding: an attached verdict was a verdict on
    unmodified HEAD — `run_gate_set` never saw the proposal, so the ceremony
    judged nothing, permanently (the skills forbid committing, and the sandbox
    checks out HEAD). This is the missing step: `git apply --index` stages the
    diff into the sandbox's index AND worktree, and `git write-tree` reads the
    resulting tree id back OUT of git — a replayable identity (same diff on the
    same base always writes the same tree), measured rather than claimed, and
    necessarily different from the base commit whenever the diff changes bytes.

    Raises SandboxError on any failure. The caller must treat that as
    INDETERMINATE for the whole set — NEVER as licence to judge unpatched HEAD,
    which would attach a verdict to a change no judge ever saw.
    """
    proc = subprocess.run(  # noqa: S603 — the diff arrives via stdin, not argv
        ["git", "apply", "--index", "--whitespace=nowarn", "-"],
        cwd=str(sandbox),
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise SandboxError(
            f"diff does not apply at engine base: {proc.stderr.strip()[:400]}"
        )
    wt = subprocess.run(  # noqa: S603
        ["git", "write-tree"],
        cwd=str(sandbox),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    tree_id = wt.stdout.strip()
    if wt.returncode != 0 or not tree_id:
        raise SandboxError(
            "the diff applied but the tree will not name itself "
            f"(git write-tree: {wt.stderr.strip()[:200]}) — an unnameable tree "
            "cannot be replayed, so it cannot be judged"
        )
    return tree_id


# ─────────────────────────────────────────────────────────────────────────────
# Run records (constraint B) and the verdict
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class JudgeRun:
    """One judge's run record.

    Created with ``status="running"`` BEFORE the process starts and completed by
    the code that READS the exit. The judge never writes this. A process that is
    killed leaves ``status="crashed"``, and a crashed run is INDETERMINATE.
    """

    judge_name: str
    gate_set: str
    argv: tuple[str, ...]
    status: str = "running"  # running | exited | crashed | skipped
    result: Result | None = None
    reason: str = ""
    exit_code: int | None = None
    work: int | None = None
    min_work: int = 0
    stdout_sha: str | None = None
    stdout_head: str = ""
    sandbox_path: str | None = None
    #: What argv[0] RESOLVED to under the judge env, and what that binary said
    #: to `--version`. A4: the literal argv ("python3") named two different
    #: worlds — the dev pyenv (pytest present) and Bone's venv (pytest absent)
    #: — with one identity, so §11 replay could not detect that a rerun ran a
    #: different interpreter than the record. Both are measured, never claimed.
    resolved_argv0: str | None = None
    interpreter: str | None = None
    #: The tree this judge actually observed. For a baseline run it is the
    #: sandbox commit read out by `git_worktree_sandbox`; for an ATTACHED run it
    #: is the `git write-tree` id of base + the proposal's stored diff
    #: (`apply_proposal_diff`) — read out of git, never a caller's label. §11
    #: makes replay the guarantee, and a run that cannot name its tree cannot
    #: be replayed against it.
    tree_sha: str | None = None
    #: The ENGINE-chosen base the diff was applied to (A1): current HEAD, never
    #: the proposer's declared tree_sha. Equal to `tree_sha` on baseline runs.
    base_sha: str | None = None
    started_at: float | None = None
    finished_at: float | None = None

    def identity(self) -> dict[str, Any]:
        """The part of the record that a rerun on the same tree must reproduce.

        Excludes wall-clock times and the sandbox path — both vary run to run
        and neither is evidence. `tree_sha` is the opposite of both: it is
        constant for a given commit and it is the single most load-bearing piece
        of evidence a verdict carries. `resolved_argv0` + `interpreter` are in
        for the same reason: the same LITERAL argv on the same tree yielded
        "2488 tests collected" under the dev pyenv and "No module named pytest"
        under Bone's venv — a replay that cannot see which interpreter ran is
        comparing two different measurements under one name.
        """
        return {
            "judge": self.judge_name,
            "argv": list(self.argv),
            "resolved_argv0": self.resolved_argv0,
            "interpreter": self.interpreter,
            "status": self.status,
            "result": self.result.value if self.result else None,
            "exit_code": self.exit_code,
            "work": self.work,
            "min_work": self.min_work,
            "stdout_sha": self.stdout_sha,
            "tree_sha": self.tree_sha,
            "base_sha": self.base_sha,
        }


@dataclass
class GateSetVerdict:
    gate_set: str
    result: Result
    runs: list[JudgeRun] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        """True ONLY on PASS. INDETERMINATE is not a pass."""
        return self.result is Result.PASS

    @property
    def blocks_acceptance(self) -> bool:
        """FAIL and INDETERMINATE both block. Only PASS does not."""
        return self.result is not Result.PASS

    def identity(self) -> dict[str, Any]:
        return {
            "gate_set": self.gate_set,
            "result": self.result.value,
            "runs": [r.identity() for r in self.runs],
        }

    def digest(self) -> str:
        """sha256 over the reproducible identity. Same tree → same digest."""
        blob = json.dumps(self.identity(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity()
        payload["reason"] = self.reason
        payload["digest"] = self.digest()
        return payload


def aggregate(runs: Iterable[JudgeRun], gate_set: str) -> GateSetVerdict:
    """DECISION 2a — PASS iff EVERY judge is PASS.

    Any FAIL → FAIL. Any INDETERMINATE with no FAIL → INDETERMINATE. No
    majority, no weighting, no "mostly green".

    An EMPTY set is INDETERMINATE, never PASS. `all([])` is True in Python, and
    that one built-in truth is precisely the hidden-fee-08 shape — an empty
    stack reading as success — sitting in the aggregator of the engine written
    to detect it.
    """
    runs = list(runs)
    if not runs:
        return GateSetVerdict(
            gate_set=gate_set,
            result=Result.INDETERMINATE,
            runs=[],
            reason="gate set ran no judges — absence is not success",
        )
    fails = [r for r in runs if r.result is Result.FAIL]
    if fails:
        return GateSetVerdict(
            gate_set=gate_set,
            result=Result.FAIL,
            runs=runs,
            reason="; ".join(f"{r.judge_name}: {r.reason}" for r in fails),
        )
    unknown = [r for r in runs if r.result is not Result.PASS]
    if unknown:
        return GateSetVerdict(
            gate_set=gate_set,
            result=Result.INDETERMINATE,
            runs=runs,
            reason="; ".join(f"{r.judge_name}: {r.reason}" for r in unknown),
        )
    return GateSetVerdict(
        gate_set=gate_set,
        result=Result.PASS,
        runs=runs,
        reason=f"{len(runs)} judge(s) passed",
    )


# ─────────────────────────────────────────────────────────────────────────────
# The runner
# ─────────────────────────────────────────────────────────────────────────────

STDOUT_HEAD_CHARS = 2000


def run_gate_set(
    gate_set: str,
    *,
    registry: Registry | None = None,
    repo_root: str | os.PathLike[str] | None = None,
    spawn: Callable[[Sequence[str], str, int], Completed] | None = None,
    probe: Callable[[str], bool] | None = None,
    sandbox_factory: Callable[[Path], tuple[Path, str, Callable[[], None]]] | None = None,
    lock_dir: str | os.PathLike[str] | None = None,
    judge_env: Mapping[str, str] | None = None,
    proposal_diff: str | None = None,
) -> GateSetVerdict:
    """Run a named gate set and return a structured, three-valued verdict.

    THE ONLY INPUT THAT SELECTS WORK IS ``gate_set`` — a name. Nothing in this
    signature supplies, hints at or overrides a result (constraint A). ``spawn``
    replaces the process; the adapters still compute the verdict from what that
    process returned. ``sandbox_factory`` replaces THE TREE, not the judgment,
    and it must still hand back the sha of whatever it produced — there is no
    seam that yields a tree with no identity. ``judge_env`` replaces the BASE
    environment (a test hands in a PATH); it is ALWAYS passed through
    ``judge_spawn_env``, so no seam can smuggle the daemon's private venv back
    onto a judge's PATH.

    ``proposal_diff`` is the ARTIFACT UNDER JUDGMENT, not a hint at a result
    (A1). When set, the STORED diff — the routes read it off the proposal row,
    never a request body, so it is the same bytes the budget checked and the
    content fingerprint deduplicated — is applied inside the sandbox at an
    ENGINE-chosen base: the repo's current HEAD, never the proposer's declared
    tree_sha. `git apply --index` + `git write-tree` give the judged tree a
    replayable identity, recorded on every run as `tree_sha` with the base as
    `base_sha`. A diff that does not apply is INDETERMINATE for the whole set
    — never a fallback to unpatched HEAD, never a pass — because a verdict on
    HEAD attached to a proposal is a verdict on a change no judge ever saw,
    which is exactly what every attached verdict was before this parameter
    existed. ``None`` means a deliberate unattached baseline of HEAD itself.

    ONE SET, ONE TREE (§2.5). The sandbox is created HERE, once, and every judge
    of the set runs inside it. Per-judge sandboxing (the previous shape, keyed on
    ``mutates_worktree``) meant a set could aggregate judges that had observed
    two different trees; see `git_worktree_sandbox`. If the sandbox cannot be
    created, no judge runs and the set is INDETERMINATE — never a fallback to
    the live tree.

    Raises ConfigError for an unknown gate set — never a verdict, because a typo
    must not be reportable as either "the tree is bad" or "the tree is fine".
    """
    root = Path(repo_root) if repo_root else _default_repo_root()
    reg = registry or load_registry(root)
    spec_set = reg.gate_set(gate_set)
    jenv = judge_spawn_env(base=judge_env)
    if spawn is not None:
        do_spawn = spawn
    else:
        def do_spawn(argv: Sequence[str], cwd: str, timeout_s: int) -> Completed:
            return real_spawn(argv, cwd, timeout_s, env=jenv)
    do_probe = probe or default_requirement_probe
    locks = Path(lock_dir) if lock_dir else Path(tempfile.gettempdir())

    if not spec_set.judges:
        # `all([])` is True; an empty set gets no sandbox and no benefit of the
        # doubt. `aggregate` states the rule.
        return aggregate([], gate_set)

    try:
        cwd, base_sha, cleanup = (sandbox_factory or git_worktree_sandbox)(root)
    except Exception as exc:  # noqa: BLE001 — any sandbox failure is INDETERMINATE
        why = (
            f"sandbox could not be created ({exc}) — refusing to run against the "
            f"live tree"
        )
        return aggregate(
            [_skipped(reg.judges[n], gate_set, why) for n in spec_set.judges], gate_set
        )

    try:
        # A1 — an attached run judges base + diff, and NOTHING ELSE. The judged
        # tree's identity is read back out of git; a failure here ends the set
        # before any judge runs, because the only tree left to run them on is
        # the one the proposal is not.
        judged_tree = base_sha
        if proposal_diff is not None:
            if not proposal_diff.strip():
                why = (
                    "attached proposal has no stored diff — nothing to apply, and "
                    "judging unmodified HEAD instead would attach a verdict to a "
                    "change no judge ever saw"
                )
                return aggregate(
                    [_skipped(reg.judges[n], gate_set, why) for n in spec_set.judges],
                    gate_set,
                )
            try:
                judged_tree = apply_proposal_diff(Path(cwd), proposal_diff)
            except SandboxError as exc:
                why = (
                    f"{exc} (engine base {base_sha}) — the proposal was not "
                    f"judged; refusing to fall back to unpatched HEAD"
                )
                return aggregate(
                    [_skipped(reg.judges[n], gate_set, why) for n in spec_set.judges],
                    gate_set,
                )

        runs: list[JudgeRun] = []
        for judge_name in spec_set.judges:
            spec = reg.judges[judge_name]
            runs.append(
                _run_one(
                    spec,
                    gate_set=gate_set,
                    sandbox=Path(cwd),
                    tree_sha=judged_tree,
                    base_sha=base_sha,
                    spawn=do_spawn,
                    probe=do_probe,
                    lock_dir=locks,
                    env=jenv,
                )
            )
    finally:
        cleanup()
    return aggregate(runs, gate_set)


def _skipped(spec: JudgeSpec, gate_set: str, reason: str) -> JudgeRun:
    """A judge that never ran. INDETERMINATE — never PASS, never FAIL.

    Not FAIL, because a missing token says nothing about the proposal; treating
    it as FAIL would teach the loop to "fix" code in response to an unplugged
    organ (§2.4).
    """
    return JudgeRun(
        judge_name=spec.name,
        gate_set=gate_set,
        argv=spec.argv,
        status="skipped",
        result=Result.INDETERMINATE,
        reason=reason,
        min_work=spec.min_work,
    )


def _run_one(
    spec: JudgeSpec,
    *,
    gate_set: str,
    sandbox: Path,
    tree_sha: str,
    base_sha: str | None,
    spawn: Callable[[Sequence[str], str, int], Completed],
    probe: Callable[[str], bool],
    lock_dir: Path,
    env: Mapping[str, str],
) -> JudgeRun:
    # ── Pre-flight: never run degraded (DECISION 2c) ────────────────────────
    missing = [r for r in spec.requires if not probe(r)]
    if missing:
        return _skipped(
            spec, gate_set, f"requirement(s) absent: {', '.join(missing)} — not run"
        )

    # Resolved against the SANDBOX, not the live tree: the judge's script is
    # part of the tree under judgment, so "is it present" must be asked of the
    # same tree that will run it. And against the JUDGE env, not the daemon's:
    # the answer must describe the world the subprocess will actually run in.
    resolved, why = _executable_present(spec, sandbox, env)
    if why:
        return _skipped(spec, gate_set, f"{why} — not run")

    # Evidence about WHAT will run, measured before it runs (A4). The probe is
    # a real subprocess of the resolved binary, never a caller's claim.
    interpreter = probe_interpreter(resolved, env) if resolved else None

    # ── Exclusive resource (M7) ─────────────────────────────────────────────
    if spec.exclusive_resource:
        try:
            with _FileLock(spec.exclusive_resource, lock_dir):
                return _spawn_and_read(
                    spec, gate_set, sandbox, tree_sha, spawn,
                    base_sha=base_sha,
                    resolved_argv0=resolved, interpreter=interpreter,
                )
        except _ResourceBusy as exc:
            return _skipped(
                spec,
                gate_set,
                f"{exc} — {spec.exclusive_resource} is mutated by another "
                f"judge and there is no lock upstream",
            )
    return _spawn_and_read(
        spec, gate_set, sandbox, tree_sha, spawn,
        base_sha=base_sha,
        resolved_argv0=resolved, interpreter=interpreter,
    )


def _spawn_and_read(
    spec: JudgeSpec,
    gate_set: str,
    cwd: Path,
    tree_sha: str,
    spawn: Callable[[Sequence[str], str, int], Completed],
    *,
    base_sha: str | None = None,
    resolved_argv0: str | None = None,
    interpreter: str | None = None,
) -> JudgeRun:
    """CONSTRAINT B, in code.

    The record is opened as ``running`` BEFORE the process exists, and every
    field below is written by THIS function — the exit reader — from what the
    process produced. The judge contributes bytes on a pipe and nothing else.
    (`resolved_argv0`/`interpreter` were measured by `_run_one` a moment
    earlier — from `shutil.which` and a `--version` subprocess, not a caller.)
    """
    run = JudgeRun(
        judge_name=spec.name,
        gate_set=gate_set,
        argv=spec.argv,
        status="running",
        result=None,
        min_work=spec.min_work,
        sandbox_path=str(cwd),
        tree_sha=tree_sha,
        base_sha=base_sha,
        resolved_argv0=resolved_argv0,
        interpreter=interpreter,
        started_at=time.time(),
    )

    try:
        done = spawn(spec.argv, str(cwd), spec.timeout_s)
    except ExecutableMissing as exc:
        run.status = "crashed"
        run.result = Result.INDETERMINATE
        run.reason = f"executable vanished between check and spawn: {exc}"
        run.finished_at = time.time()
        return run
    except Exception as exc:  # noqa: BLE001 — a spawn that blew up produced no evidence
        run.status = "crashed"
        run.result = Result.INDETERMINATE
        run.reason = f"spawn failed: {type(exc).__name__}: {exc}"
        run.finished_at = time.time()
        return run

    run.finished_at = time.time()
    run.exit_code = done.exit_code
    run.stdout_sha = hashlib.sha256(done.stdout.encode("utf-8", "replace")).hexdigest()
    run.stdout_head = done.output[:STDOUT_HEAD_CHARS]

    # A process that never delivered an exit status produced no verdict.
    if done.timed_out or done.exit_code is None:
        run.status = "crashed"
        run.result = Result.INDETERMINATE
        run.reason = (
            f"judge timed out after {spec.timeout_s}s — killed, no exit status"
            if done.timed_out
            else "judge produced no exit status"
        )
        return run

    run.status = "exited"
    adapter = ADAPTERS[spec.adapter]
    result, reason = adapter(spec, done)
    run.work = work_count(spec, done)

    # ── DECISION 2b — the work ratchet gates the PASS claim ─────────────────
    # Ordering matters and is deliberate: a FAIL stands on its own. Downgrading
    # a real failure to INDETERMINATE because its work line was unparseable
    # would hide a red, and INDETERMINATE is for "we do not know", not "we know
    # it is broken". The ratchet exists solely to stop absence reading as
    # success, so it is applied ONLY to a PASS.
    if result is Result.PASS:
        if run.work is None:
            run.result = Result.INDETERMINATE
            run.reason = (
                f"exit says pass but {spec.work_field} could not be read — a judge "
                f"that cannot show its work has not shown it passed"
            )
            return run
        if run.work < spec.min_work:
            run.result = Result.INDETERMINATE
            run.reason = (
                f"exit says pass but {spec.work_field}={run.work} < min_work="
                f"{spec.min_work} — scope shrank; absence is not success"
            )
            return run

    run.result = result
    run.reason = reason
    return run
