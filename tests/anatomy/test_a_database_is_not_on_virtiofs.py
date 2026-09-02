"""Anatomy CI gate — an embedded database engine does not live on a bind mount.

Twice now, on the same layer:

  mariadb   VirtIOFS crashed InnoDB mid-FK-ALTER (OS error 71 on the .ibd file).
            Moved to a named volume; the bug disappeared.
  onlyoffice/euro-office  MEASURED 2026-09-02, after Docker 29.7.2: VirtioFS
            presents a host directory as owned by the ASKING uid, so the
            embedded postgres saw root and refused — "Data directory
            /var/lib/postgresql/16/main must not be owned by root". 31 restarts,
            never started, and it had been healthy the day before.

A named volume routes I/O through Docker's own filesystem, where ownership and
locking are real. This gate pins the two that moved, so a later edit cannot
quietly put a database engine back on a bind mount.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

#: role -> (container path of the engine's data dir, expected named volume)
ENGINES = {
    "pazny.mariadb": ("/var/lib/mysql", "mariadb_data"),
    "pazny.onlyoffice": ("/var/lib/postgresql", "onlyoffice_db"),
}


def _compose(role: str) -> str:
    return (REPO / "roles" / role / "templates" / "compose.yml.j2").read_text(
        encoding="utf-8")


@pytest.mark.parametrize("role,spec", ENGINES.items(), ids=list(ENGINES))
def test_the_engine_data_dir_is_a_named_volume(role, spec):
    dest, volume = spec
    src = _compose(role)
    mounts = [ln.strip() for ln in src.splitlines()
              if ln.strip().startswith("- ") and ln.rstrip().endswith(dest)
              and not ln.lstrip().startswith("#")]
    assert mounts, f"{role}: no volume line mounts {dest}"
    for m in mounts:
        assert m == f"- {volume}:{dest}", (
            f"{role}: {dest} is mounted as {m!r}. A host path here puts the "
            f"database engine back on VirtioFS, which has broken this estate "
            f"twice — InnoDB corruption (mariadb) and a postgres ownership "
            f"refusal (onlyoffice). Use the named volume {volume!r}")


@pytest.mark.parametrize("role,spec", ENGINES.items(), ids=list(ENGINES))
def test_the_named_volume_is_declared_with_an_explicit_name(role, spec):
    _, volume = spec
    src = _compose(role)
    assert re.search(rf"^volumes:\s*$", src, re.M), (
        f"{role}: no top-level volumes: block, so the named volume is undeclared")
    assert re.search(rf"^\s+{re.escape(volume)}:\s*$", src, re.M), (
        f"{role}: {volume} is not declared under volumes:")
    assert re.search(rf"name:\s*{re.escape(volume)}\b", src), (
        f"{role}: {volume} has no explicit `name:`. Without it Compose prefixes "
        f"the project and the volume does not survive a `compose down` in "
        f"another project context")
