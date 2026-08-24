"""A scrape target must not outlive the container it scrapes.

WHAT HAPPENED. cAdvisor's container is gated on `ansible_os_family != 'Darwin'`
(`roles/pazny.grafana/templates/compose.yml.j2`) — its cgroup and layerdb paths
are real only on Linux, and REM-197 removed it from the Mac on 2026-08-22.
Alloy's scrape of it was gated on a SECOND, independent declaration,
`alloy_scrape_cadvisor: true`, which nothing changed.

So on this Mac, Alloy went on scraping `localhost:8080` at a container that no
longer exists. `NosWarningServiceDegraded` has been firing since, and **every
converge re-rendered the same dead target** — a red that could never clear by
being fixed, only by being noticed.

Found on 2026-08-24 by reading the inbox, two hours before an unattended night
that it would otherwise have burned through.

THE SHAPE, which is the reason this is a gate and not a one-line fix: one truth
in two spellings. Both declarations were correct when written; they had no way
to stay correct together. The flag is now DERIVED from the container's own
condition, and this gate refuses a future edit that re-splits them.

WHAT IT CANNOT SEE. Whether the container's own gate is right, whether Alloy
renders at all, or whether the scrape works when both agree. Those are a
converge and `tools/red-status.py`. This checks only that the two cannot
disagree.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "roles/pazny.grafana/templates/compose.yml.j2"
ALLOY = REPO / "files/observability/alloy/config.alloy.j2"
CONFIG = REPO / "default.config.yml"

#: The fact both conditions must turn on. Spelled either way — `ansible_os_family`
#: in a role template, `ansible_facts['os_family']` at play scope — because the
#: two idioms coexist in this tree and normalising them is not this gate's job.
FACT = re.compile(r"ansible_(?:os_family|facts\[.os_family.\])")


def _container_gate() -> str:
    """The `{% if %}` immediately above the cadvisor service block."""
    src = COMPOSE.read_text(encoding="utf-8")
    at = src.index("\n  cadvisor:")
    head = src[:at].splitlines()
    for line in reversed(head):
        if line.lstrip().startswith("{% if"):
            return line.strip()
    raise AssertionError("no {% if %} guards the cadvisor service block")


def test_the_container_is_still_platform_gated():
    """If this ever becomes unconditional the derivation below is wrong, and
    the flag would suppress a scrape of a container that does exist."""
    gate = _container_gate()
    assert FACT.search(gate), (
        f"the cadvisor container's gate no longer keys on the OS family: {gate!r}. "
        "Whatever replaced it is now the thing alloy_scrape_cadvisor must follow")
    assert "Darwin" in gate, gate


def test_the_scrape_flag_is_derived_from_that_same_fact():
    """Not 'is also true'. DERIVED — a second literal is how these two spent
    two days disagreeing while both looked right."""
    cfg = CONFIG.read_text(encoding="utf-8")
    m = re.search(r"^alloy_scrape_cadvisor:\s*(.+)$", cfg, re.M)
    assert m, "alloy_scrape_cadvisor is gone from default.config.yml"
    value = m.group(1).strip()
    assert FACT.search(value), (
        f"alloy_scrape_cadvisor is a bare literal ({value}) again. It must be "
        "derived from the same fact that decides whether the container exists — "
        "on 2026-08-22 the container went away on Darwin and this flag did not, "
        "and Alloy scraped a dead localhost:8080 until somebody read the inbox")
    assert "Darwin" in value, value


def test_the_scrape_block_still_consults_the_flag():
    """A derivation nothing reads is decoration."""
    alloy = ALLOY.read_text(encoding="utf-8")
    at = alloy.index('prometheus.scrape "cadvisor"')
    head = alloy[:at].splitlines()
    guard = next((ln for ln in reversed(head) if ln.lstrip().startswith("{% if")), "")
    assert "alloy_scrape_cadvisor" in guard, (
        f"the cadvisor scrape block is not gated on the flag: {guard!r}")


def test_the_two_agree_on_a_darwin_host():
    """The case that actually broke. Render the flag against Darwin facts and
    assert it is falsey — the platform where the container does not exist."""
    import jinja2

    cfg = CONFIG.read_text(encoding="utf-8")
    value = re.search(r"^alloy_scrape_cadvisor:\s*(.+)$", cfg, re.M).group(1).strip()
    value = value.strip('"').strip("'")
    env = jinja2.Environment()
    for family, expected in (("Darwin", False), ("Debian", True)):
        rendered = env.from_string(value).render(
            ansible_facts={"os_family": family}, ansible_os_family=family)
        got = rendered.strip().lower() in ("true", "yes", "1")
        assert got is expected, (
            f"on {family} the flag renders {rendered!r} (={got}); the container "
            f"{'does not exist' if family == 'Darwin' else 'exists'} there, so "
            f"the scrape must be {expected}")
