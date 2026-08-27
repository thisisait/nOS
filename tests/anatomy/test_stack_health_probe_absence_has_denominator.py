"""Absence needs a denominator (docs/hidden_fees/08-empty-stack-reads-as-success.md).

`stack-health-probe.py` used to treat EVERY zero-container stack as ready:

    print(f"{stack}: 0/0 ready (no containers - stack empty)")

That line is correct only when nothing was ever supposed to be there. It is
wrong when the bring-up failed before creating anything — and the probe had
no way to tell the two apart, because "0" has no denominator: it counts what
IS running, never what SHOULD be. Measured on the Linux CI runner
2026-07-22: `infra` had no rendered `docker-compose.yml` (the render step
never produced one), `docker compose up` returned rc=1, and the probe still
printed "0/0 ready (no containers - stack empty)" — the STRICT health gate
passed an estate with no MariaDB, no PostgreSQL, no Authentik, no Traefik.

THIS FILE pins the fix: the probe now derives the missing denominator from
an artifact it can read without a live Docker daemon or the Ansible `up`
result — the rendered compose inputs themselves (`docker-compose.yml` +
every role override in `overrides/`), the same files `docker compose up`
itself consumes.

  - 0 declared services  -> legitimately empty, PASS silently (unchanged
    behaviour for the many stacks that are empty by configuration).
  - N>0 declared services, 0 containers -> FAIL. The artifact alone proves
    something was expected; no rc needed.
  - the base compose file is simply missing -> UNKNOWN, not a guess in
    either direction. A probe that can only read rendered artifacts cannot
    tell "never enabled, template gated off" from "render step failed" —
    that disambiguation belongs to a different, complementary layer
    (consulting the `up` rc). UNKNOWN must never collapse into "ALL_READY".

Every assertion below drives the REAL script's REAL functions against
crafted files on disk — never a regex over the module's source text. A gate
that matched prose would pass on a docstring rewrite and miss a broken
`main()`; these call `_expected_service_count` and `main` directly.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "files/anatomy/scripts/stack-health-probe.py"


def _probe():
    spec = importlib.util.spec_from_file_location("nos_stack_health_probe_denom", PROBE)
    assert spec and spec.loader, f"cannot load {PROBE}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nos_stack_health_probe_denom"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def no_docker(monkeypatch):
    """Every scenario here is the ZERO-CONTAINER branch — `docker ps` must
    return nothing, exactly as it does on a sandbox with no docker binary at
    all (the module's own `except Exception: return []` already guarantees
    this; pointing NOS_DOCKER_BIN at a binary that cannot exist makes the
    guarantee explicit and independent of the host running the test)."""
    monkeypatch.setenv("NOS_DOCKER_BIN", "definitely-not-a-real-docker-binary-nos-test")


def _write_compose(path: Path, services: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["services:"]
    if services:
        for name in services:
            lines.append(f"  {name}:")
            lines.append("    image: example/x:latest")
    else:
        lines[-1] = "services: {}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── the denominator function, in isolation ──────────────────────────────────

def test_expected_service_count_unions_base_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    _write_compose(tmp_path / "mystack" / "docker-compose.yml", {"base-svc": {}})
    _write_compose(tmp_path / "mystack" / "overrides" / "a.yml", {"svc-a": {}})
    _write_compose(tmp_path / "mystack" / "overrides" / "b.yml", {"svc-b": {}})

    mod = _probe()
    expected, reason, names = mod._expected_service_count("mystack")

    assert expected == 3, "must union services across base + every override file"
    assert reason == ""
    assert names == ["base-svc", "svc-a", "svc-b"]


def test_expected_service_count_zero_is_legitimate(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    _write_compose(tmp_path / "mystack" / "docker-compose.yml", {})

    mod = _probe()
    expected, reason, names = mod._expected_service_count("mystack")

    assert (expected, reason, names) == (0, "", []), (
        "an empty services: {} with no overrides is the common, legitimate "
        "case — every install_* toggle for this stack is off"
    )


def test_expected_service_count_missing_base_file_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    # tmp_path/mystack does not even exist — nothing was ever rendered here.

    mod = _probe()
    expected, reason, names = mod._expected_service_count("mystack")

    assert expected is None, (
        "a missing base compose file is exactly the measured CI case "
        "(infra: rc=1 'no such file or directory') — the probe must not "
        "guess PASS *or* FAIL from an artifact that isn't there"
    )
    assert "does not exist" in reason
    assert names == []


def test_expected_service_count_no_stacks_dir_is_unknown(monkeypatch):
    monkeypatch.delenv("NOS_STACKS_DIR", raising=False)

    mod = _probe()
    expected, reason, names = mod._expected_service_count("anystack")

    assert expected is None, (
        "run by hand outside the playbook (no NOS_STACKS_DIR) the probe has "
        "no artifact to consult at all — must say so, not assume either verdict"
    )
    assert "NOS_STACKS_DIR" in reason


# ── main(): the printed line + the marker the tick loop keys on ────────────

def test_legitimately_empty_stack_still_passes_silently(tmp_path, monkeypatch, capsys, no_docker):
    """Requirement C: existing behaviour survives. A stack with nothing
    enabled must still read as ready, with no ceremony."""
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    _write_compose(tmp_path / "iiab" / "docker-compose.yml", {})

    rc = _probe().main(["iiab"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "stack empty by configuration" in out
    assert "UNKNOWN" not in out
    assert "FAILED" not in out
    assert out.strip().splitlines()[-1] == "ALL_READY"


def test_declared_services_zero_containers_fails_with_reason(tmp_path, monkeypatch, capsys, no_docker):
    """The exact shape the fee asks for: a FAIL that names WHICH case it is,
    not the old undifferentiated '0/0 ready (stack empty)'."""
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    _write_compose(tmp_path / "infra" / "docker-compose.yml", {})
    _write_compose(tmp_path / "infra" / "overrides" / "mariadb.yml", {"mariadb": {}})
    _write_compose(tmp_path / "infra" / "overrides" / "traefik.yml", {"traefik": {}})

    rc = _probe().main(["infra"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "0/2 ready FAILED" in out
    assert "bring-up produced no containers" in out, "message must say WHICH case it is"
    assert "declares 2 service(s)" in out
    assert "mariadb" in out and "traefik" in out
    assert out.strip().splitlines()[-1] == "FAILED"


def test_missing_render_artifact_is_unknown_never_all_ready(tmp_path, monkeypatch, capsys, no_docker):
    """The measured CI shape, from the artifact side: no compose file at
    all. Must be loud (UNKNOWN), never silently pass as ALL_READY — that
    silent pass is the entire defect this file exists to close."""
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    # tmp_path/infra is never created.

    rc = _probe().main(["infra"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "UNKNOWN" in out
    assert "does not exist" in out
    marker = out.strip().splitlines()[-1]
    assert marker == "UNKNOWN", (
        f"marker was {marker!r} — an indeterminate zero-container stack must "
        "never resolve to ALL_READY (that is the exact silent-pass defect) "
        "nor be silently dropped"
    )


def test_one_unknown_stack_taints_the_whole_marker(tmp_path, monkeypatch, capsys, no_docker):
    """Multi-stack invocation (the real wave-2 call shape: _wait_stacks is a
    list). One indeterminate stack must not be washed out by a second,
    genuinely-empty stack reporting ALL_READY-worthy state."""
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path))
    _write_compose(tmp_path / "iiab" / "docker-compose.yml", {})  # legit empty
    # tmp_path/devops never rendered -> UNKNOWN

    rc = _probe().main(["iiab", "devops"])
    out = capsys.readouterr().out

    assert rc == 0
    assert out.strip().splitlines()[-1] == "UNKNOWN"


def test_probe_invoked_by_hand_without_env_is_unknown(tmp_path, monkeypatch, capsys, no_docker):
    """Requirement A: run outside a playbook (no NOS_STACKS_DIR wiring), the
    probe cannot resolve the denominator at all — must say UNKNOWN, not the
    old blind PASS."""
    monkeypatch.delenv("NOS_STACKS_DIR", raising=False)

    rc = _probe().main(["infra"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "UNKNOWN" in out
    assert out.strip().splitlines()[-1] == "UNKNOWN"
