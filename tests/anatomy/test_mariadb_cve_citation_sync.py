"""Gate: MariaDB version pin + its CVE citations stay in sync across all 3 sites.

CVE-2026-3494-orphaned-citation (v0.7 overnight audit): the finding flagged
CVE-2026-3494 as appearing "only in role README + defaults, never cited
upstream." Per the authoritative remediation queue REM-067
(``docs/llm/security/remediation-queue.json``, confidence=high, sourced to
MariaDB's official CVE docs), CVE-2026-3494 IS real — an audit-logging bypass
(CVSS 5.3) on the **11.8.x branch**, fixed in **11.8.6**, which is exactly the
release nOS pins. The companion CVE-2026-32710 (JSON_SCHEMA_VALID heap overflow,
CVSS 8.6; REM-031) is the other CVE the pin closes.

All three definition sites — ``default.config.yml`` (loaded via ``vars_files``,
OUTRANKS the role default per the version-pins-default-config-shadow trap),
``roles/pazny.mariadb/defaults/main.yml``, and the role README table — already
cite BOTH CVEs against the ``11.8.6`` pin. This gate pins that consistency so an
edit to one site (the exact drift the audit hit) can never orphan a citation or
silently change the pinned release out from under the cited fix.
"""

from __future__ import absolute_import, division, print_function

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CONFIG = os.path.join(ROOT, "default.config.yml")
ROLE_DEFAULT = os.path.join(ROOT, "roles", "pazny.mariadb", "defaults", "main.yml")
README = os.path.join(ROOT, "roles", "pazny.mariadb", "README.md")

# The release that carries all cited fixes. REM-031 (CVE-2026-32710) +
# REM-067 (CVE-2026-3494, 11.8.x-branch audit-log bypass) land in 11.8.6;
# REM-102 bumps to 11.8.8 to also carry CVE-2026-49261 (wsrep_notify_cmd RCE,
# not reachable single-node but patched anyway).
PINNED_VERSION = "11.8.8"

# Every CVE the pinned release is cited as closing. Adding a CVE here forces it
# into all three sites; orphaning it in any site fails the gate.
CITED_CVES = ("CVE-2026-49261", "CVE-2026-32710", "CVE-2026-3494")

_PIN_RE = re.compile(r'^mariadb_version:\s*["\']?([\d.]+)["\']?', re.M)


def _read(path):
    with open(path) as fh:
        return fh.read()


def _read_pin(path):
    m = _PIN_RE.search(_read(path))
    assert m, "mariadb_version not found in %s" % path
    return m.group(1)


def test_pin_is_the_cited_release():
    for path in (CONFIG, ROLE_DEFAULT):
        tag = _read_pin(path)
        assert tag == PINNED_VERSION, (
            "%s pins mariadb_version=%r but the CVE citations claim %r is fixed. "
            "Bumping the pin without re-verifying the CVE coverage is the exact "
            "audit-confusion drift CVE-2026-3494-orphaned-citation flagged."
            % (path, tag, PINNED_VERSION))


def test_config_and_role_default_pins_in_sync():
    cfg, role = _read_pin(CONFIG), _read_pin(ROLE_DEFAULT)
    assert cfg == role, (
        "MariaDB pin shadow: default.config.yml=%r vs role default=%r. "
        "config wins via vars_files, so a lone role bump is a DEAD pin — sync both."
        % (cfg, role))


def test_readme_table_cites_pinned_version():
    body = _read(README)
    assert ("`%s`" % PINNED_VERSION) in body or PINNED_VERSION in body, (
        "README variables table no longer cites mariadb_version %r" % PINNED_VERSION)


def test_every_cited_cve_present_in_all_three_sites():
    """No orphaned citation: each CVE must appear in config + role default + README."""
    for cve in CITED_CVES:
        for label, path in (
            ("default.config.yml", CONFIG),
            ("role default", ROLE_DEFAULT),
            ("role README", README),
        ):
            assert cve in _read(path), (
                "%s is missing from %s (%s). All MariaDB CVE citations must stay "
                "in sync across all three sites — an orphaned citation triggers "
                "audit confusion during compliance reviews "
                "(CVE-2026-3494-orphaned-citation)." % (cve, label, path))
