"""from_regex should match the installed version string as documented in
each recipe's notes."""

from __future__ import absolute_import, division, print_function

import os
import re

import pytest

from .conftest import UPGRADES_DIR


def _load_yaml(path):
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def _recipe(service, recipe_id):
    doc = _load_yaml(os.path.join(UPGRADES_DIR, "%s.yml" % service))
    for rec in doc["recipes"]:
        if rec["id"] == recipe_id:
            return rec
    raise KeyError("recipe not found: %s/%s" % (service, recipe_id))


# Expected match matrix.  Each tuple: (service, recipe_id, should_match, version).
CASES = [
    # Grafana 10 -> 11
    ("grafana", "grafana-10-to-11", True,  "10.0.0"),
    ("grafana", "grafana-10-to-11", True,  "10.4.2"),
    ("grafana", "grafana-10-to-11", False, "11.0.0"),
    ("grafana", "grafana-10-to-11", False, "9.5.0"),
    # Grafana 11 -> 12
    ("grafana", "grafana-11-to-12", True,  "11.0.0"),
    ("grafana", "grafana-11-to-12", True,  "11.5.0"),
    ("grafana", "grafana-11-to-12", False, "10.4.2"),
    ("grafana", "grafana-11-to-12", False, "12.0.0"),
    # Postgres 15 -> 16
    ("postgresql", "postgresql-15-to-16", True,  "15"),
    ("postgresql", "postgresql-15-to-16", True,  "15.4"),
    ("postgresql", "postgresql-15-to-16", False, "16"),
    ("postgresql", "postgresql-15-to-16", False, "14.8"),
    # Postgres 16 -> 17
    ("postgresql", "postgresql-16-to-17", True,  "16"),
    ("postgresql", "postgresql-16-to-17", True,  "16.2"),
    ("postgresql", "postgresql-16-to-17", False, "15.4"),
    ("postgresql", "postgresql-16-to-17", False, "17.0"),
    # MariaDB 10 -> 11
    ("mariadb", "mariadb-10-to-11", True,  "10.6.18"),
    ("mariadb", "mariadb-10-to-11", True,  "10.11.0"),
    ("mariadb", "mariadb-10-to-11", False, "11.4.0"),
    ("mariadb", "mariadb-10-to-11", False, "9.5.0"),
    # Authentik 2024 -> 2025
    ("authentik", "authentik-2024-to-2025", True,  "2024.12.3"),
    ("authentik", "authentik-2024-to-2025", False, "2025.2.1"),
    # Authentik 2025 -> 2026
    ("authentik", "authentik-2025-to-2026", True,  "2025.10.0"),
    ("authentik", "authentik-2025-to-2026", False, "2024.10.0"),
    # Redis 7 -> 8
    ("redis", "redis-7-to-8", True,  "7.2.4"),
    ("redis", "redis-7-to-8", True,  "7.4.0"),
    ("redis", "redis-7-to-8", False, "8.0.0"),
    ("redis", "redis-7-to-8", False, "6.2.14"),
    # Infisical 0.60 -> 0.70
    ("infisical", "infisical-0.60-to-0.70", True,  "0.60.0"),
    ("infisical", "infisical-0.60-to-0.70", True,  "0.60.42"),
    ("infisical", "infisical-0.60-to-0.70", False, "0.70.0"),
    ("infisical", "infisical-0.60-to-0.70", False, "0.6.0"),
    # Infisical 0.70 -> 0.80
    ("infisical", "infisical-0.70-to-0.80", True,  "0.70.5"),
    ("infisical", "infisical-0.70-to-0.80", False, "0.80.0"),
    # ── Forward-coverage tracks (2026-05-30): each pins the advisor to the
    #    verified-installed major so the recipe stops reporting as "stale". ──
    ("grafana",   "grafana-12-current",     True,  "12.4.2"),
    ("grafana",   "grafana-12-current",     True,  "12.0.0"),
    ("grafana",   "grafana-12-current",     False, "11.5.0"),
    ("grafana",   "grafana-12-current",     False, "13.0.0"),
    ("mariadb",   "mariadb-11-current",     True,  "11.8.6"),
    ("mariadb",   "mariadb-11-current",     True,  "11.0.0"),
    ("mariadb",   "mariadb-11-current",     False, "10.11.0"),
    ("mariadb",   "mariadb-11-current",     False, "12.0.0"),
    # re-pinned to the 0.160.x line 2026-06-10 (installed v0.160.4 had NO
    # matching recipe — upgrade-architect gap; the 0.159 pin went stale)
    ("infisical", "infisical-current",      True,  "0.160.4"),
    ("infisical", "infisical-current",      True,  "0.160.0"),
    ("infisical", "infisical-current",      False, "0.159.16"),
    ("infisical", "infisical-current",      False, "0.161.0"),
    ("authentik", "authentik-2026-current", True,  "2026.5.2"),
    ("authentik", "authentik-2026-current", True,  "2026.1.0"),
    ("authentik", "authentik-2026-current", False, "2025.10.0"),
    ("authentik", "authentik-2026-current", False, "2027.1.0"),
    ("redis",     "redis-8-current",        True,  "8.0"),
    ("redis",     "redis-8-current",        True,  "8.0.0"),
    ("redis",     "redis-8-current",        False, "7.4.0"),
    ("redis",     "redis-8-current",        False, "9.0.0"),
    # gitlab 18-to-current regex FIX: ^18\.([0-9]|[1-9][0-9])\. now matches
    # two-digit minors (18.10+), which the old ^18\.(0|[1-9])\. could not.
    ("gitlab",    "gitlab-18-to-current",   True,  "18.10.3-ce.0"),
    ("gitlab",    "gitlab-18-to-current",   True,  "18.0.5-ce.0"),
    ("gitlab",    "gitlab-18-to-current",   True,  "18.99.9-ce.0"),
    ("gitlab",    "gitlab-18-to-current",   False, "17.11.7-ce.0"),
    ("gitlab",    "gitlab-18-to-current",   False, "19.0.0-ce.0"),
]


@pytest.mark.parametrize("service,recipe_id,should_match,version", CASES)
def test_from_regex(service, recipe_id, should_match, version):
    rec = _recipe(service, recipe_id)
    pattern = re.compile(rec["from_regex"])
    actual = pattern.match(version) is not None
    if should_match:
        assert actual, (
            "expected %r to match %r in recipe %s (regex %r)"
            % (version, should_match, recipe_id, rec["from_regex"])
        )
    else:
        assert not actual, (
            "did NOT expect %r to match recipe %s (regex %r)"
            % (version, recipe_id, rec["from_regex"])
        )


def test_alphabetic_ordering_yields_progressive_upgrades():
    """If a system at 10.x loads all grafana recipes, alphabetic sort of ids
    yields 10->11 before 11->12 — exactly what the engine needs."""
    import yaml  # noqa: local import to allow skip-on-missing elsewhere
    doc = yaml.safe_load(open(os.path.join(UPGRADES_DIR, "grafana.yml")))
    ids = sorted([r["id"] for r in doc["recipes"]])
    # grafana-12-current (the at-target forward-coverage track) sorts AFTER
    # both transition tracks, so a 10.x system still gets 10->11 first.
    assert ids == ["grafana-10-to-11", "grafana-11-to-12", "grafana-12-current"]
