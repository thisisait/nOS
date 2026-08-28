"""Anatomy gate — every live-runner agent routes its notifications.

Finding `notification-routing-for-agents` (low / gap, confirmed 2026-06-14):
agent profiles declare a `notification:` block (on_critical/on_high/…→channels)
and `pulse-run-agent.sh` POSTs a Bone notification on a non-zero exit with
`origin_agent=NOS_AGENT_NAME`. Bone's clients/wing.py::_lookup_channels resolves
the channel list from the aggregator-rendered `notification-routing.json`, keyed
by the agent name — and *silently falls back to ["wing-inbox"] only* when the
key (or a severity field) is missing. So a live agent whose profile drops the
notification block — or whose pulse job's NOS_AGENT_NAME drifts off the profile
`name` — would page the operator ONLY into the Wing inbox: a critical/high alert
would never reach ntfy/mail, with no error at deploy time.

Per-agent spot checks already existed (test_conductor_pulse_jobs.py, and the
remediator's routing check in the since-retired test_remediator_agent.py —
gone with its agent in the 2026-08-26 roster close)
but NO parametrized gate covered *every* agent, and none proved the
route actually resolves through Bone's real lookup. This gate closes both:

  1. every file-format agent profile with a live `pulse:` runner declares a
     `notification:` block with all five severity keys (on_critical/on_high/
     on_medium/on_low/on_info);
  2. channel values come from the canonical vocabulary (wing-inbox/ntfy/mail)
     and critical is a superset of high (a critical can never page FEWER
     channels than a high — the operator always hears a critical);
  3. each pulse job's NOS_AGENT_NAME matches the profile `name`, so the
     origin_agent Bone receives is the routing key;
  4. driving Bone's *real* `_lookup_channels` over a routing JSON built exactly
     like the wing-base template, every agent's critical + high events resolve
     to a NON-empty channel set (i.e. they do not silently degrade to the
     wing-inbox-only fallback).

Contract-only agents (inspektor / librarian — `metadata.runner_status:
deferred`, directory `agent.yml` with no pulse job) are excluded by design:
they never fire `pulse-run-agent.sh`, so there is no notification to route.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO / "files/anatomy/agents"
BONE_WING = REPO / "files/anatomy/bone/clients/wing.py"

SEVERITY_KEYS = ("on_critical", "on_high", "on_medium", "on_low", "on_info")
# Canonical channel vocabulary — must mirror bone/clients/wing.py::_VALID_CHANNELS.
VALID_CHANNELS = {"wing-inbox", "ntfy", "mail"}


def _live_runner_profiles() -> list[tuple[str, dict]]:
    """File-format agent profiles (`agents/<name>.yml`) that declare at least
    one `pulse:` job — i.e. an agent with a LIVE pulse-run-agent.sh runner that
    can actually POST a notification. Returns [(name, parsed-doc), …]."""
    out: list[tuple[str, dict]] = []
    for f in sorted(AGENTS_DIR.glob("*/agent.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        if ((doc.get("pulse") or {}).get("jobs")):
            out.append((f.name, doc))
    return out


def _profile_ids() -> list[str]:
    return [name for name, _ in _live_runner_profiles()]


def _load_bone_wing():
    """Import bone/clients/wing.py standalone (stdlib-only deps) so the gate
    can call the REAL _lookup_channels / _load_routing against a temp sidecar."""
    spec = importlib.util.spec_from_file_location("_bone_wing_client", BONE_WING)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _render_routing_entries(profiles: list[tuple[str, dict]]) -> dict:
    """Build the routing JSON exactly as wing-base's
    templates/notification-routing.json.j2 renders it: keyed by agent name,
    each value carrying the five severity arrays. Mirrors the aggregator
    (load_plugins.run_aggregators) keying agent blocks by profile `name`."""
    entries: dict[str, dict] = {}
    for _fname, doc in profiles:
        key = doc.get("name") or "unknown"
        notif = doc.get("notification") or {}
        entries[key] = {
            sev: list(notif.get(sev) or []) for sev in SEVERITY_KEYS
        }
        entries[key]["templates"] = {}
    return {"entries": entries}


# ── Static profile contract ───────────────────────────────────────────────


def test_at_least_one_live_runner_agent():
    """Sanity floor — if this empties, the glob/path drifted and every other
    parametrized case would vacuously pass."""
    profiles = _live_runner_profiles()
    assert profiles, (
        "no live-runner agent profiles found under "
        f"{AGENTS_DIR} — glob 'agents/*.yml' with a pulse: block drifted?"
    )


@pytest.mark.parametrize("name", _profile_ids())
def test_live_agent_declares_full_notification_block(name):
    doc = dict(_live_runner_profiles())[name]
    notif = doc.get("notification")
    assert isinstance(notif, dict), (
        f"{name}: live-runner agent (has a pulse job) must declare a "
        "notification: block — else its critical/high alerts silently route "
        "to wing-inbox only (Bone fallback)."
    )
    for sev in SEVERITY_KEYS:
        assert sev in notif, f"{name}: notification block missing '{sev}' key"
        assert isinstance(notif[sev], list), (
            f"{name}: notification.{sev} must be a list of channels"
        )
        for ch in notif[sev]:
            assert ch in VALID_CHANNELS, (
                f"{name}: notification.{sev} has unknown channel {ch!r} "
                f"(valid: {sorted(VALID_CHANNELS)})"
            )


@pytest.mark.parametrize("name", _profile_ids())
def test_critical_supersets_high(name):
    """A critical must never page FEWER channels than a high — the operator
    must always be reachable on the loudest severity. Pins the severity-floor
    monotonicity that makes 'approval-needed' / critical alerts un-droppable."""
    doc = dict(_live_runner_profiles())[name]
    notif = doc.get("notification") or {}
    crit = set(notif.get("on_critical") or [])
    high = set(notif.get("on_high") or [])
    assert high <= crit, (
        f"{name}: on_high channels {sorted(high)} not a subset of on_critical "
        f"{sorted(crit)} — a critical would page fewer places than a high."
    )
    assert crit, f"{name}: on_critical must route to at least one channel"


@pytest.mark.parametrize("name", _profile_ids())
def test_pulse_job_agent_name_matches_profile(name):
    """The runner POSTs origin_agent=NOS_AGENT_NAME; Bone keys routing by that.
    Each pulse job that sets NOS_AGENT_NAME must set it to the profile `name`
    (else origin_agent misses the routing key → wing-inbox-only fallback).
    Jobs that omit NOS_AGENT_NAME are deterministic non-LLM scripts (drift /
    scan) that do not run pulse-run-agent.sh, so they carry no agent route."""
    doc = dict(_live_runner_profiles())[name]
    profile_name = doc.get("name")
    for job in (doc.get("pulse") or {}).get("jobs") or []:
        env = job.get("env") or {}
        an = env.get("NOS_AGENT_NAME")
        if an is None:
            continue
        assert an == profile_name, (
            f"{name}: pulse job {job.get('name')!r} sets NOS_AGENT_NAME="
            f"{an!r} ≠ profile name {profile_name!r}; origin_agent would miss "
            "the notification-routing key."
        )


# ── Live-resolution contract (drives Bone's real lookup) ──────────────────


@pytest.mark.parametrize("name", _profile_ids())
def test_routing_resolves_through_bone_lookup(name, tmp_path, monkeypatch):
    """End-to-end: render the routing sidecar exactly as wing-base does, then
    call Bone's REAL _lookup_channels(origin_agent=<name>, severity). Critical
    and high MUST resolve to a non-empty channel set — proving the agent does
    not silently fall through to the ["wing-inbox"] default at notify time."""
    wing = _load_bone_wing()
    routing = _render_routing_entries(_live_runner_profiles())
    sidecar = tmp_path / "notification-routing.json"
    sidecar.write_text(json.dumps(routing))
    monkeypatch.setattr(wing, "_routing_path", lambda: sidecar)

    for sev in ("critical", "high"):
        resolved = wing._lookup_channels(None, name_to_agent(name), sev)
        assert resolved, (
            f"{name}: Bone _lookup_channels(origin_agent, {sev!r}) returned "
            f"{resolved!r} — agent would silently degrade to wing-inbox-only."
        )
        for ch in resolved:
            assert ch in VALID_CHANNELS, (
                f"{name}: resolved channel {ch!r} not in {sorted(VALID_CHANNELS)}"
            )


def name_to_agent(profile_filename: str) -> str:
    """Map a profile filename ('conductor.yml') to its routing key (the
    profile `name`, == NOS_AGENT_NAME == origin_agent)."""
    doc = dict(_live_runner_profiles())[profile_filename]
    return doc.get("name")
