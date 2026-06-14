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


# a role-default version line is "annotated" when it (or the line directly
# above it) names the canonical layer. The source-of-truth comment makes the
# shadow visible at the edit site, so an operator bumping the role default sees
# the warning that default.config.yml outranks it.
def _annotated_version_vars(path):
    annotated = set()
    with open(path) as fh:
        lines = fh.read().splitlines()
    for i, line in enumerate(lines):
        m = _VER_RE.match(line)
        if not m:
            continue
        tail = line.split("#", 1)[1].lower() if "#" in line else ""
        prev = lines[i - 1].lower() if i > 0 else ""
        if "default.config" in tail or "config.yml" in tail or "default.config" in prev:
            annotated.add(m.group(1))
    return annotated


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


def test_dual_pinned_role_defaults_point_to_config():
    """Every role default shadowed by default.config.yml must carry a
    source-of-truth comment at the edit site, so a bump there can't be a silent
    dead pin. Adds the contract the n8n RCE incident exposed: the comment is not
    decorative — it's the visible warning that default.config.yml outranks."""
    cfg = _config_versions()
    missing = []
    for f in sorted(glob.glob(os.path.join(ROOT, "roles", "pazny.*", "defaults", "main.yml"))):
        role_vars = _scan_versions(f)
        annotated = _annotated_version_vars(f)
        for var in role_vars:
            if var in cfg and var not in annotated:
                missing.append("%s in %s" % (var, os.path.relpath(f, ROOT)))
    assert not missing, (
        "Dual-pinned role-default version line lacks a 'default.config.yml' "
        "source-of-truth comment (config OUTRANKS the role default — bumping "
        "only here is a dead pin). Annotate each:\n  " + "\n  ".join(missing))


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


# --- CVE-citation drift across the three mariadb_version surfaces ------------
# Sibling of the version-pin shadow: the VALUE (11.8.6) can agree across all
# three files while the CVE comment that JUSTIFIES the pin drifts. That drift
# bites an AUDITOR, not the runtime — three files claim different CVEs are
# patched by the same image tag. default.config.yml is the source-of-truth
# layer (it OUTRANKS the role default), so its comment must be the complete
# citation; README.md + defaults/main.yml must not claim MORE than it does.

_CVE_RE = re.compile(r"CVE-\d{4}-\d+")

# (relative path, line-substring that anchors the mariadb_version pin line)
_MARIADB_PIN_SITES = [
    ("default.config.yml", 'mariadb_version: "11.8.6"'),
    ("roles/pazny.mariadb/defaults/main.yml", 'mariadb_version: "11.8.6"'),
    ("roles/pazny.mariadb/README.md", "`mariadb_version`"),
]


def _cves_on_anchored_line(path, anchor):
    with open(os.path.join(ROOT, path)) as fh:
        for line in fh:
            if anchor in line:
                return frozenset(_CVE_RE.findall(line))
    raise AssertionError("anchor %r not found in %s" % (anchor, path))


def test_mariadb_cve_citation_consistent_across_surfaces():
    """The CVE list pinned to the mariadb 11.8.6 image must match across
    default.config.yml, the role default, and the role README — otherwise an
    operator reading any one surface gets a contradictory security claim.

    Closes finding ``version-pin-shadow-mariadb``: README + defaults cited
    'CVE-2026-32710 + CVE-2026-3494' but default.config.yml omitted the second.
    """
    cites = {path: _cves_on_anchored_line(path, anchor)
             for path, anchor in _MARIADB_PIN_SITES}

    distinct = set(cites.values())
    assert len(distinct) == 1, (
        "mariadb_version CVE citations disagree across surfaces "
        "(default.config.yml is source-of-truth; align the others to it):\n  "
        + "\n  ".join("%s: %s" % (p, sorted(c)) for p, c in cites.items()))

    # guard against the citation being silently emptied on all three at once.
    assert "CVE-2026-3494" in next(iter(distinct)), (
        "CVE-2026-3494 (11.8.x audit-logging bypass, fixed in 11.8.6) dropped "
        "from the mariadb_version citation — re-add it or justify removal.")
