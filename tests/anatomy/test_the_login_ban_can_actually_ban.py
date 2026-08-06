"""Home Assistant enables a ban that cannot fire, and nOS has to switch it on.

UPSTREAM'S SHAPE. `components/http/__init__.py` sets `ip_ban_enabled` to True
by default. `login_attempts_threshold` defaults to
`NO_LOGIN_ATTEMPT_THRESHOLD = -1`, and `ban.py`'s `process_wrong_login` returns
on `request.app[KEY_LOGIN_THRESHOLD] < 1` **before** it increments the
failed-attempt counter and before any ban is issued. So the boolean reads
enabled, reports enabled, and bans nothing. The positive integer is the switch;
the boolean is decoration.

WHY IT MATTERED HERE (REM-168, measured on this host, not theorised):

  * the `home.<tld>` router is anonymous by design — `traefik_auth_modes` says
    `oidc`, and native OIDC ADDS a Sign-in-with-Authentik button to Home
    Assistant's own login page rather than putting a wall in front of it, so
    `POST /auth/login_flow` is reachable with no credentials;
  * every failed login costs a cost-12 bcrypt — 207.7 ms in-container —
    because HA deliberately hashes a dummy for an UNKNOWN username to keep
    timing constant. The anti-timing defence is the amplifier;
  * the container is capped at 1.0 CPU, so ~4.8 anonymous requests per second
    saturate it. One client, one thread.

The live `configuration.yaml` set neither key.

WHAT THIS GATE HOLDS, and it renders rather than greps: the block Ansible
writes must actually parse as YAML and must actually carry a positive
threshold. A grep for the key name would pass on a commented-out line, and a
`{% if %}` that emits `ip_ban_enabled: true` with no threshold would reproduce
upstream's defect inside our own config.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles/pazny.homeassistant/tasks/main.yml"
CONFIG = REPO / "default.config.yml"

#: Changing this ORPHANS the block already written on every live install:
#: blockinfile would append a second `http:` mapping, and Home Assistant
#: refuses a configuration.yaml with a duplicate top-level key.
MARKER = "# {mark} ANSIBLE MANAGED - trusted_proxies"


def _http_block() -> str:
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    for task in tasks:
        block = task.get("ansible.builtin.blockinfile") or task.get("blockinfile")
        if isinstance(block, dict) and "trusted_proxies" in str(block.get("marker", "")):
            return block["block"]
    raise AssertionError("no blockinfile writes the http: block — this gate is blind")


def _render(threshold: int, trim_blocks: bool = True) -> dict:
    env = jinja2.Environment(trim_blocks=trim_blocks, lstrip_blocks=False)
    text = env.from_string(_http_block()).render(
        homeassistant_login_attempts_threshold=threshold
    )
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict), f"the rendered block is not a mapping:\n{text}"
    return doc.get("http") or {}


def test_the_marker_is_unchanged():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    markers = [
        (t.get("ansible.builtin.blockinfile") or {}).get("marker")
        for t in tasks
        if isinstance(t.get("ansible.builtin.blockinfile"), dict)
    ]
    assert MARKER in markers, (
        f"the http: block's marker changed. Every live install already carries "
        f"a block under {MARKER!r}; a new marker appends a SECOND `http:` "
        f"mapping and Home Assistant refuses to load a duplicate top-level key. "
        f"The marker is a migration contract, not a label."
    )


@pytest.mark.parametrize("trim_blocks", [True, False])
def test_the_default_renders_a_threshold_that_actually_bans(trim_blocks):
    """Rendered under both Jinja whitespace settings, because the block is
    templated as a task argument and the environment is not ours to choose."""
    default = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))[
        "homeassistant_login_attempts_threshold"
    ]
    http = _render(int(default), trim_blocks=trim_blocks)
    assert int(http.get("login_attempts_threshold", -1)) > 0, (
        f"the rendered http: block carries "
        f"{http.get('login_attempts_threshold')!r}. Anything below 1 is "
        f"upstream's own inert default: ban.py returns before it counts."
    )
    assert http.get("ip_ban_enabled") is True
    # The proxy trust is what makes a ban land on the CLIENT rather than on
    # Traefik. Losing it would turn the ban into a self-inflicted outage.
    assert http.get("use_x_forwarded_for") is True and http.get("trusted_proxies")


def test_disabling_it_does_not_leave_the_upstream_lie_behind():
    """Setting the threshold to 0 must remove BOTH keys.

    Emitting `ip_ban_enabled: true` with no threshold would rebuild, in our own
    configuration, the exact defect this exists to fix: a ban that reports
    itself enabled and never fires.
    """
    http = _render(0)
    assert "login_attempts_threshold" not in http
    assert "ip_ban_enabled" not in http, (
        "with the ban switched off, the config still claims ip_ban_enabled — "
        "an enabled-looking defence that cannot fire is what REM-168 was"
    )
    assert http.get("trusted_proxies"), "the opt-out dropped the proxy trust too"
