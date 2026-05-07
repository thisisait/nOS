"""E2E journey test fixtures (Anatomy A13, 2026-05-07).

Pytest plumbing for non-interactive end-to-end "journey" tests. Each
journey is a sequence of named steps; each step writes one Wing event
via HMAC POST so the Grafana E2E Journeys dashboard renders pass/fail
heatmaps, step-duration histograms, and a per-run audit timeline.

Usage in a test:

    def test_some_journey(journey):
        with journey("operator_login") as j:
            with j.step("authentik_flow_executor") as s:
                # do work; raise on failure to mark step as failed
                resp = requests.post(...)
                resp.raise_for_status()
                s.note = f"login took {resp.elapsed.total_seconds():.2f}s"
            with j.step("fetch_dashboard") as s:
                ...

The `journey` fixture is session-scoped on actor_action_id but each
test call gets its own JourneyRecorder, so journeys don't accidentally
share UUIDs. start/end events bookend the test; one event per step.

Wing API contract: /api/v1/events accepts HMAC-signed POSTs with
``X-Wing-Timestamp: <unix_ts>`` + ``X-Wing-Signature: hex(HMAC-SHA256(
secret, "<ts>.<raw_body>"))`` headers. The shared secret comes from
the WING_EVENTS_HMAC_SECRET env (= bone_secret) — same value Bone
signs callback events with.
"""

from __future__ import annotations

import atexit
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

# A13.6 ephemeral SSO tester identity (Vrstva A.5).
# Imports are guarded so the existing journeys (smoke / plugin_contract /
# halt_resume / approval_flow) keep working even if Authentik is offline —
# the tester_identity fixture is the only thing that requires it.
try:
    from .lib.tester_identity import (
        TesterIdentity,
        provision_tester,
        teardown_tester,
        sweep_orphans,
    )
    _IDENTITY_LIB_AVAILABLE = True
except ImportError as _import_exc:  # pragma: no cover — dev/CI env without requests/yaml
    _IDENTITY_LIB_AVAILABLE = False
    _IDENTITY_IMPORT_ERROR = _import_exc


# ── Configuration ────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wing_url() -> str:
    return os.environ.get("WING_API_URL", "http://127.0.0.1:9000").rstrip("/")


def _hmac_secret() -> str:
    return os.environ.get(
        "WING_EVENTS_HMAC_SECRET",
        os.environ.get("BONE_SECRET", ""),
    )


def _post_event(payload: dict) -> int:
    """POST a single event to Wing's HMAC ingest. Returns HTTP status.

    Failures don't kill the test — telemetry is observability, not the
    contract under test. We return the status so the runner can warn
    when the pipe is broken (a journey that runs but doesn't telemeter
    is still a real test, just invisible in Grafana).
    """
    secret = _hmac_secret()
    if not secret:
        return 0  # no telemetry without a secret; silent no-op
    body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()

    req = urllib.request.Request(
        _wing_url() + "/api/v1/events",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Wing-Timestamp": ts,
            "X-Wing-Signature": sig,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0


# ── Recorder dataclasses ─────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    status: str = "running"      # "ok" | "failed"
    duration_ms: int = 0
    note: str | None = None
    error: str | None = None


@dataclass
class JourneyRecorder:
    name: str
    actor_action_id: str
    run_id: str
    started_at: float = field(default_factory=time.time)
    steps: list[StepResult] = field(default_factory=list)

    @contextmanager
    def step(self, step_name: str):
        """Time a step + emit one e2e_journey_step event on exit."""
        result = StepResult(name=step_name)
        t0 = time.time()
        try:
            yield result
            result.status = "ok"
        except Exception as e:
            result.status = "failed"
            result.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            result.duration_ms = int((time.time() - t0) * 1000)
            self.steps.append(result)
            _post_event({
                "ts": _now_iso(),
                "type": "e2e_journey_step",
                "run_id": self.run_id,
                "source": "e2e",
                "actor_id": "e2e-runner",
                "actor_action_id": self.actor_action_id,
                "acted_at": _now_iso(),
                "task": f"{self.name}/{step_name}",
                "result": {
                    "journey": self.name,
                    "step": step_name,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "note": result.note,
                    "error": result.error,
                },
            })


# ── Fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def journey():
    """Yield a factory: ``with journey('name') as j:`` opens a recorded run.

    Emits e2e_journey_start on enter and e2e_journey_end on exit
    (with aggregated step counts + total duration).
    """
    @contextmanager
    def _factory(name: str):
        action_id = str(uuid.uuid4())
        run_id = f"e2e-{name}-{int(time.time())}"
        recorder = JourneyRecorder(
            name=name, actor_action_id=action_id, run_id=run_id,
        )
        _post_event({
            "ts": _now_iso(),
            "type": "e2e_journey_start",
            "run_id": run_id,
            "source": "e2e",
            "actor_id": "e2e-runner",
            "actor_action_id": action_id,
            "acted_at": _now_iso(),
            "task": name,
        })
        passed_overall = True
        try:
            yield recorder
        except Exception:
            passed_overall = False
            raise
        finally:
            duration_ms = int((time.time() - recorder.started_at) * 1000)
            passed = sum(1 for s in recorder.steps if s.status == "ok")
            failed = sum(1 for s in recorder.steps if s.status == "failed")
            _post_event({
                "ts": _now_iso(),
                "type": "e2e_journey_end",
                "run_id": run_id,
                "source": "e2e",
                "actor_id": "e2e-runner",
                "actor_action_id": action_id,
                "acted_at": _now_iso(),
                "task": name,
                "result": {
                    "journey": name,
                    "status": "ok" if (passed_overall and failed == 0) else "failed",
                    "steps": len(recorder.steps),
                    "passed": passed,
                    "failed": failed,
                    "duration_ms_total": duration_ms,
                },
            })
    return _factory


# ── A13.6 Ephemeral tester identity ─────────────────────────────────
#
# Every test that needs SSO-authenticated traffic asks for ``tester_identity``;
# pytest hands back a freshly-provisioned per-tier user, valid for the test's
# lifetime. Teardown deletes the user + revokes the Wing token. atexit handler
# is the safety net for crashed runs (sweeps anything still alive at the end
# of the pytest process).
#
# Usage:
#
#   @pytest.mark.parametrize("tester_identity", ["provider"], indirect=True)
#   def test_admin_route(tester_identity):
#       ...
#
#   @pytest.mark.parametrize("tester_identity",
#                            ["provider", "manager", "user", "guest"],
#                            indirect=True)
#   def test_rbac_matrix(tester_identity, expected_status):
#       ...

# Track every ID we created during this pytest process so the atexit safety
# net only deletes things WE made — never touches the static blueprint user.
_PROVISIONED: list["TesterIdentity"] = []


@pytest.fixture
def tester_identity(request):
    """Provision a per-test ephemeral SSO identity in the requested RBAC tier.

    Parametrize indirectly with the tier name (``provider``/``manager``/
    ``user``/``guest``). Default tier is ``user`` if no param supplied.
    """
    if not _IDENTITY_LIB_AVAILABLE:
        pytest.skip(f"tester identity lib unavailable: {_IDENTITY_IMPORT_ERROR}")

    tier = getattr(request, "param", "user")
    try:
        identity = provision_tester(tier)
    except Exception as exc:  # noqa: BLE001 — pytest-skip on infra failure, not test failure
        pytest.skip(f"cannot provision tester identity (tier={tier}): {exc}")
        return  # unreachable, pytest.skip raises

    _PROVISIONED.append(identity)
    try:
        yield identity
    finally:
        try:
            teardown_tester(identity)
        finally:
            try:
                _PROVISIONED.remove(identity)
            except ValueError:
                pass


def _atexit_sweep_provisioned():
    """Best-effort cleanup of identities we EXPLICITLY tracked in this
    process. Catches: hard kills (SIGKILL), pytest-internal crashes,
    fixture-teardown exceptions that swallowed the cleanup.

    SCOPED to ``_PROVISIONED`` only — we used to also call ``sweep_orphans()``
    here as a belt-and-suspenders catch-all, but the A13.6 incident (2026-05-07)
    showed that a bug in ``list_users_by_prefix``'s server-side filter can
    bypass the prefix scoping and DELETE arbitrary users. Lesson: NEVER auto-
    sweep on atexit. Only delete things we minted in *this* process — those
    are unambiguously ours. Crashes that strand identities are recovered by
    operator-invoked ``files/anatomy/scripts/sweep-orphan-testers.py``, which
    requires explicit human action and runs the multi-layer prefix safety check.

    Logs but never raises — atexit is past the point of useful failure.
    """
    if not _IDENTITY_LIB_AVAILABLE:
        return
    log = logging.getLogger("nos.e2e.atexit")
    if _PROVISIONED:
        log.warning("atexit: %d ephemeral testers still alive — sweeping "
                    "ONLY tracked identities (no orphan sweep)",
                    len(_PROVISIONED))
        for identity in list(_PROVISIONED):
            try:
                teardown_tester(identity)
            except Exception as exc:  # noqa: BLE001
                log.warning("atexit teardown failed for %s: %s",
                            identity.username, exc)


atexit.register(_atexit_sweep_provisioned)
