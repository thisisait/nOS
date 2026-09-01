"""A CI config value must never become persistent estate credential state.

MEASURED 2026-09-01, on the live estate. `tests/config.yml` carried

    # -- Dummy passwords for CI (unused because install_* flags are off) ----
    mariadb_root_password: "ci-test-password"

and the comment was false. `templates/secrets.yml.j2` persists
`mariadb_root_password` UNCONDITIONALLY — the install flags gate whether the
service runs, not whether the credential is written to `~/.nos/secrets.yml`.
So one converge run as

    ansible-playbook main.yml --tags preflight -e @tests/config.yml

froze the literal string `ci-test-password` into the estate's credential store
at 08:29:35. Every later run faithfully reused the persisted value, because the
store is the source of truth once a key is in it. The real root password —
`{global_password_prefix}_pw_mariadb`, still the one baked into the data volume
at init — was simply gone from the estate's own record of it.

WHY IT WENT UNNOTICED FOR SIX HOURS AND WOULD HAVE GONE UNNOTICED FOR WEEKS.
Nothing authenticates as MariaDB root except (a) the converge's verify task and
(b) the nightly `mariadb-dump --all-databases` in backup.sh. The container had
been up three weeks, so (a) never ran; (b) runs at 03:00 and its
`rc=$?` reads the LAST command of a pipe (`aws s3 cp`), not `mariadb-dump`, so
an access-denied dump still uploads and still reports success. A credential
that is only tested at restart is not tested.

THE GATE. Any key that `templates/secrets.yml.j2` persists is estate state, and
no test/CI config may declare a value for it. This is a static cross-check of
two artifacts, not of anyone's comment about them — the comment above is
precisely what was wrong.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
STORE_TEMPLATE = REPO / "templates/secrets.yml.j2"
CI_CONFIG = REPO / "tests/config.yml"

_TOP_LEVEL_KEY = re.compile(r"^([a-z0-9_]+):", re.M)


def _keys(path):
    return set(_TOP_LEVEL_KEY.findall(path.read_text()))


def test_ci_config_declares_no_persisted_secret():
    persisted = _keys(STORE_TEMPLATE)
    assert persisted, "secrets.yml.j2 parsed to zero keys — the regex broke"

    poisoned = sorted(persisted & _keys(CI_CONFIG))
    assert not poisoned, (
        f"{CI_CONFIG.relative_to(REPO)} declares {poisoned}, which "
        f"{STORE_TEMPLATE.relative_to(REPO)} persists into ~/.nos/secrets.yml. "
        "A converge that loads this file with -e @ writes the CI value into the "
        "live credential store PERMANENTLY — the install_* flags do not gate "
        "the persist step. This is how mariadb_root_password became "
        "'ci-test-password' on 2026-09-01. Remove the key: default.config.yml "
        "already resolves it from nos_derived_secrets."
    )
