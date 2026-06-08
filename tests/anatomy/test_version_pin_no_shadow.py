"""Gate: no NEW version-pin shadow between default.config.yml and role defaults.

The trap (memory ``version-pins-default-config-shadow``): a service version
lives in BOTH ``default.config.yml`` and ``roles/pazny.<svc>/defaults/main.yml``.
``default.config.yml`` is loaded via ``vars_files`` and OUTRANKS role defaults,
so bumping ONLY the role default produces a **dead pin** — the intended version
never runs, and a later ``main.yml`` re-render silently keeps the config value.
This bit a live n8n RCE pin and the 5 services reconciled 2026-06-08
(prometheus/loki/outline/metabase/infisical).

This gate asserts that every ``*_version`` var defined in BOTH places either
AGREES, or is in ``INTENTIONAL_SHADOW`` — the documented set where the two use
different tag CONVENTIONS on purpose (config pins exact / a SHA; the role
default is a looser ``latest`` / ``stable`` / variant-suffix fallback, and
config-wins is the desired behaviour). A NEW unlisted divergence FAILS, so a
future dead-pin bump can't slip in. The allowlist is also checked for rot: if a
listed pair is reconciled, it must be removed from the list.
"""

from __future__ import absolute_import, division, print_function

import os
import re
import glob

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_VER_RE = re.compile(r'^([a-z0-9_]+_version):\s*["\']?([^"\'#\s]+)')


# var -> (config_value, role_value, reason). config-wins is intentional here:
# config carries the operative exact/SHA pin; the role default is a looser
# fallback tag. These are convention differences, NOT dead newer pins.
INTENTIONAL_SHADOW = {
    "calibreweb_version":     ("config pins the bare version; role keeps the LSIO -lsNNN build tag"),
    "maps_tileserver_version": ("config pins 'latest' floating; role default is an exact fallback"),
    "nextcloud_version":      ("config pins the 'stable' channel; role default is a major-number fallback"),
    "paperclip_version":      ("config pins an exact image SHA; role default is 'latest'"),
    "puter_version":          ("config pins an exact tag; role default is 'latest'"),
    "qgis_version":           ("config pins 'latest'; role default is the 'LTR' channel"),
    "uptime_kuma_version":    ("config pins an exact patch; role default is the major-track tag"),
    "woodpecker_version":     ("config pins the major track 'v3'; role default is an exact patch"),
    "wordpress_version":      ("config pins the bare version; role keeps the -phpX-apache variant"),
}


def _scan_versions(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            m = _VER_RE.match(line)
            if m:
                out.setdefault(m.group(1), m.group(2))
    return out


def _config_versions():
    return _scan_versions(os.path.join(ROOT, "default.config.yml"))


def _role_versions():
    out = {}
    for f in glob.glob(os.path.join(ROOT, "roles", "pazny.*", "defaults", "main.yml")):
        for var, val in _scan_versions(f).items():
            out.setdefault(var, (val, f))
    return out


def test_no_unlisted_version_pin_shadow():
    cfg = _config_versions()
    roles = _role_versions()
    shadowed = sorted(set(cfg) & set(roles))
    mismatches = {v: (cfg[v], roles[v][0]) for v in shadowed if cfg[v] != roles[v][0]}

    unlisted = sorted(set(mismatches) - set(INTENTIONAL_SHADOW))
    assert not unlisted, (
        "New version-pin shadow(s) — default.config.yml wins, so the role "
        "default is a DEAD pin. Reconcile (sync the pair) or add to "
        "INTENTIONAL_SHADOW with a reason:\n  " + "\n  ".join(
            "%s: config=%r role=%r" % (v, mismatches[v][0], mismatches[v][1])
            for v in unlisted))


def test_intentional_shadow_list_has_no_rot():
    cfg = _config_versions()
    roles = _role_versions()
    stale = []
    for v in INTENTIONAL_SHADOW:
        if v not in cfg or v not in roles:
            stale.append("%s: no longer defined in both files" % v)
        elif cfg[v] == roles[v][0]:
            stale.append("%s: now AGREES (config=role=%r) — remove from list" % (v, cfg[v]))
    assert not stale, "INTENTIONAL_SHADOW is stale:\n  " + "\n  ".join(stale)
