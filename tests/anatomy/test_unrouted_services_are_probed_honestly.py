"""A monitor must not ask a question we have already answered by removing the route.

MEASURED ON THE LIVE ESTATE, 2026-08-05, minutes after a green converge:

    Traefik   https://traefik.pazny.eu/ping   404      127.0.0.1:8082/ping  200
    Bone      https://api.pazny.eu            404
    Cortex    https://cortex.pazny.eu         404

All three are healthy. All three are in `traefik_skip_ids`, so
`services.yml.j2` renders no router for them and the edge 404 is the intended
outcome — REM-144's remediation was precisely "take the dashboard off the
edge". The Kuma monitor builder derived its URL from `domain_var` alone and
never consulted that list, so every service we deliberately unroute earns a
permanently red monitor.

That is worse than having no monitor. A red light that is always red is one an
operator learns to skip, and the habit does not distinguish between this light
and the next one.

THE FIX IS NOT A SPECIAL CASE. `state/manifest.yml` already carries the right
probe for each of them — `health_check.url_template`, a loopback endpoint with
an expected status. Two representations of one fact ("how do you check this
service"), and nothing compared them. The builder now prefers the authored one
for unrouted ids and keeps the edge probe for everything else, because an edge
probe tests more: DNS, router, middleware and backend in one question.

WHAT THIS GATE CHECKS is the declaration side, which is where the silence would
be. If an unrouted service lacks a `url_template` or a `port_var`, the builder
has nothing honest to construct and skips it — correctly, but quietly, and the
service ends up with no monitor at all. So the manifest must carry both for
every id we take off the edge.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "state/manifest.yml"
TRAEFIK_VARS = REPO / "roles/pazny.traefik/vars/main.yml"
MONITORS = REPO / "roles/pazny.uptime_kuma/tasks/monitors.yml"


def _skip_ids() -> list[str]:
    return yaml.safe_load(TRAEFIK_VARS.read_text(encoding="utf-8")).get(
        "traefik_skip_ids", []
    )


def _services() -> dict[str, dict]:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return {s["id"]: s for s in doc.get("services", []) if isinstance(s, dict)}


def test_the_inputs_are_readable():
    """Positive control — an empty skip list makes every check below vacuous."""
    assert _skip_ids(), "traefik_skip_ids is empty or unreadable; this gate is blind"
    assert _services(), "state/manifest.yml has no services"


@pytest.mark.parametrize("sid", _skip_ids())
def test_an_unrouted_service_declares_a_loopback_probe(sid):
    svc = _services().get(sid)
    if svc is None:
        pytest.skip(f"{sid} is not in state/manifest.yml — nothing derives a monitor for it")
    if "domain_var" not in svc:
        pytest.skip(f"{sid} has no domain_var, so no edge monitor was ever derived")

    hc = svc.get("health_check") or {}
    assert hc.get("url_template"), (
        f"{sid} is in traefik_skip_ids and has a domain_var, so an edge monitor "
        f"would be derived for a route that returns 404 by design — but it "
        f"declares no health_check.url_template, so there is nothing honest to "
        f"probe instead. The monitor will be skipped and the service silently "
        f"loses its monitoring."
    )
    assert svc.get("port_var"), (
        f"{sid} declares a health_check but no port_var, so the loopback URL "
        f"cannot be built without rendering another role's default — the "
        f"eager-resolution trap. Add port_var."
    )
    assert "localhost" in hc["url_template"] or "127.0.0.1" in hc["url_template"], (
        f"{sid} is unrouted, so its authored probe must be a loopback one; "
        f"{hc['url_template']!r} points somewhere the edge cannot reach either."
    )


def test_the_monitor_builder_consults_the_unrouted_list():
    """Secondary, and knowingly weak: presence, not effect.

    The effect lives in Ansible and is exercised by a converge, not by pytest —
    `--tags uptime_kuma` then `SELECT url FROM monitor` is the real check. This
    only catches the builder losing the input entirely.
    """
    src = MONITORS.read_text(encoding="utf-8")
    assert "traefik_skip_ids" in src, (
        "monitors.yml no longer reads traefik_skip_ids, so it is back to "
        "deriving every URL from domain_var and will re-mint red monitors for "
        "every service taken off the edge."
    )
    assert "_kuma_unrouted" in src, "the unrouted list is read but never used"
