# nOS — `flags | nos_installed(rows)`: the manifest rows this host runs.
# Ansible's face of tools/nos_identity.installed, so a template and the readers
# share one derivation. Gate: tests/anatomy/test_service_registry_is_the_installed_set.py.

import sys
from pathlib import Path


def nos_installed(flags, rows=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from nos_identity import installed  # noqa: PLC0415

    return installed(dict(flags), list(rows) if rows is not None else None)


class FilterModule:
    def filters(self):
        return {"nos_installed": nos_installed}
