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
    for path in (CONFIG,):
        tag = _read_pin(path)
        assert tag == PINNED_VERSION, (
            "%s pins mariadb_version=%r but the CVE citations claim %r is fixed. "
            "Bumping the pin without re-verifying the CVE coverage is the exact "
            "audit-confusion drift CVE-2026-3494-orphaned-citation flagged."
            % (path, tag, PINNED_VERSION))


# test_config_and_role_default_pins_in_sync retired 2026-08-05: the role default
# no longer declares mariadb_version, so there is nothing left to be out of sync
# with. `test_a_pin_is_declared_once` forbids the pair returning.


def test_readme_table_cites_pinned_version():
    body = _read(README)
    assert ("`%s`" % PINNED_VERSION) in body or PINNED_VERSION in body, (
        "README variables table no longer cites mariadb_version %r" % PINNED_VERSION)


def test_every_cited_cve_present_in_both_surfaces():
    """No orphaned citation: each CVE must appear in config + README.

    It was three surfaces until the role default stopped declaring the pin. The
    third was never a separate claim — it was the same sentence copied beside a
    value that could not win — so dropping it removes an obligation, not a check.
    """
    for cve in CITED_CVES:
        for label, path in (
            ("default.config.yml", CONFIG),
            ("role README", README),
        ):
            assert cve in _read(path), (
                "%s is missing from %s (%s). All MariaDB CVE citations must stay "
                "in sync across both surfaces — an orphaned citation triggers "
                "audit confusion during compliance reviews "
                "(CVE-2026-3494-orphaned-citation)." % (cve, label, path))
