"""Gate: PostgreSQL is pinned to the 16.14 patch line, in sync across both pins.

REM-088 (``docs/llm/security/scan-state.json``): the ``16.13-alpine`` pin was
one patch behind the 2026-05-14 PostgreSQL release ``16.14`` (CVE cluster incl.
CVE-2026-6479, SSL/GSS DoS — authentication-relevant since ``ssl=on`` is enabled).
This gate pins the floor at ``16.14`` so a regression to an older patch can't slip
back in, AND asserts the two definition sites stay in sync — ``default.config.yml``
is loaded via ``vars_files`` and OUTRANKS ``roles/pazny.postgresql/defaults/main.yml``,
so a lone role-default bump would be a DEAD pin (the
``version-pins-default-config-shadow`` trap). Both must carry the operative tag.
"""

from __future__ import absolute_import, division, print_function

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

CONFIG = os.path.join(ROOT, "default.config.yml")
ROLE_DEFAULT = os.path.join(ROOT, "roles", "pazny.postgresql", "defaults", "main.yml")

# Operative floor — the patch line REM-088 demands. Bump (never lower) on a
# future remediation; the >= check keeps the gate forward-compatible.
MIN_MINOR = 14
MAJOR = 16

_PIN_RE = re.compile(r'^postgresql_version:\s*["\']?(\d+)\.(\d+)-alpine["\']?', re.M)


def _read_pin(path):
    with open(path) as fh:
        m = _PIN_RE.search(fh.read())
    assert m, "postgresql_version (NN.NN-alpine) not found in %s" % path
    return int(m.group(1)), int(m.group(2)), "%s.%s-alpine" % (m.group(1), m.group(2))


def test_config_pin_at_or_above_floor():
    major, minor, tag = _read_pin(CONFIG)
    assert major == MAJOR, "PostgreSQL major changed (%s) — major bumps need a pg_upgrade recipe, not a pin edit" % tag
    assert minor >= MIN_MINOR, (
        "default.config.yml postgresql_version=%s is behind the REM-088 floor 16.%d "
        "(stale patch line, SSL/GSS DoS CVE-2026-6479)" % (tag, MIN_MINOR))


# test_role_default_pin_at_or_above_floor and test_both_pins_in_sync lived here
# until 2026-08-05. Both read roles/pazny.postgresql/defaults/main.yml, which no
# longer declares the pin: `default.config.yml` outranks it, so the role default
# was a line that could be edited without effect. Keeping a floor check on an
# unreachable value would have been a gate certifying a version nothing runs,
# and the sync check has nothing left to compare — one declaration cannot
# disagree with itself. `test_a_pin_is_declared_once` now forbids the pair.
