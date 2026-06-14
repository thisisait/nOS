"""Anatomy CI gate — blank-reset auto-deps must mirror main.yml's auto-deps.

tasks/blank-reset.yml line ~244 carries a `[BLANK] Resolve auto-dependencies
for cleanup` set_fact that DUPLICATES main.yml's auto-enable logic (the three
`Auto-enable {MariaDB,PostgreSQL,Redis Docker} for services that require it`
set_facts around main.yml:1125-1164). The duplication is load-bearing AND
documented in the blank-reset comment: at blank-reset time main.yml's
auto-deps have NOT run yet, so blank-reset must resolve them itself —
otherwise the DB data dir for a service that auto-enables a database (e.g.
firefly → MariaDB+Redis, authentik → PostgreSQL+Redis) is left intact, and
the NEXT install carries stale schema/version → DB-version pollution and
startup failures.

The duplication had silently drifted: blank-reset omitted bookstack+firefly
(MariaDB), authentik+infisical+paperclip+miniflux+hedgedoc (PostgreSQL), and
authentik+infisical+bookstack+firefly+onlyoffice (Redis) that main.yml lists.

This gate parses BOTH files, extracts the set of `install_*` drivers feeding
each database's auto-enable, and asserts the two copies are byte-for-driver
identical per DB type. When someone adds a new DB-dependent service to
main.yml's auto-enable but forgets blank-reset.yml (or vice versa), this fails
with an exact per-DB diff and a re-sync hint — BEFORE a blank run orphans data.

Mapping note:
  main.yml uses three separate `when:`-gated set_facts (one per DB), keyed by
  the fact each SETS (install_mariadb / install_postgresql / redis_docker).
  blank-reset.yml uses ONE set_fact with three `<fact>: >- {{ ... or ... }}`
  keys. Both reduce to: per target fact, the set of install_* drivers that
  flip it on. We compare those driver sets.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = REPO_ROOT / "main.yml"
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"

# The three database facts whose auto-enable logic is duplicated. Keyed by the
# fact main.yml/blank-reset.yml SET; the value is the human label for diffs.
DB_FACTS = {
    "install_mariadb": "MariaDB",
    "install_postgresql": "PostgreSQL",
    "redis_docker": "Redis Docker",
}

# install_* tokens that are the fact being SET, not a driver — exclude the
# target fact itself (blank-reset seeds each fold with `<fact> | default(false)`).
_SELF = set(DB_FACTS)


def _drivers(expr: str, target_fact: str) -> set[str]:
    """All install_* drivers referenced in `expr`, minus the target fact itself."""
    found = set(re.findall(r"install_[a-z0-9_]+", expr))
    # redis_docker's self-seed isn't an install_* token, but mariadb/postgresql
    # seed themselves via `install_mariadb | default(false)` etc. — drop those.
    found -= _SELF
    found.discard(target_fact)
    return found


def _main_autodeps() -> dict[str, set[str]]:
    """Parse main.yml's three `Auto-enable <DB>` set_facts → {fact: {drivers}}."""
    src = MAIN_PATH.read_text()
    out: dict[str, set[str]] = {}
    for fact in DB_FACTS:
        # Match the set_fact that assigns `<fact>: true` and capture its when: body.
        m = re.search(
            r"ansible\.builtin\.set_fact:\s*\n\s*"
            + re.escape(fact)
            + r":\s*true\s*\n\s*when:\s*>\n(?P<body>(?:\s+.*\n)+?)\s*tags:",
            src,
        )
        assert m, f"could not locate main.yml Auto-enable set_fact for {fact}"
        out[fact] = _drivers(m.group("body"), fact)
    return out


def _blank_reset_autodeps() -> dict[str, set[str]]:
    """Parse blank-reset's single resolve set_fact → {fact: {drivers}}."""
    src = BLANK_RESET_PATH.read_text()
    block = re.search(
        r"\[BLANK\] Resolve auto-dependencies for cleanup\"\n"
        r"\s*ansible\.builtin\.set_fact:\n(?P<body>(?:\s+.*\n)+?)\n",
        src,
    )
    assert block, "could not locate blank-reset.yml auto-dependency resolve set_fact"
    body = block.group("body")
    out: dict[str, set[str]] = {}
    for fact in DB_FACTS:
        # Each fact is a `<fact>: >- {{ ... }}` fold; capture up to the next
        # top-level fact key (or end of block).
        m = re.search(
            re.escape(fact) + r":\s*>-\n(?P<expr>(?:\s+.*\n)+?)(?=\s{4}\S|\Z)",
            body,
        )
        assert m, f"could not locate blank-reset.yml fold for {fact}"
        out[fact] = _drivers(m.group("expr"), fact)
    return out


def test_main_autodeps_parse_nonempty():
    """Sanity: each main.yml DB auto-enable parses to a non-empty driver set."""
    deps = _main_autodeps()
    for fact, drivers in deps.items():
        assert drivers, f"main.yml auto-enable for {fact} parsed to empty driver set"


def test_blank_reset_autodeps_parse_nonempty():
    """Sanity: each blank-reset DB fold parses to a non-empty driver set."""
    deps = _blank_reset_autodeps()
    for fact, drivers in deps.items():
        assert drivers, f"blank-reset.yml fold for {fact} parsed to empty driver set"


def test_blank_reset_autodeps_mirror_main():
    """Core gate: per DB, blank-reset's driver set == main.yml's driver set.

    A divergence means blank=true may skip wiping a DB data dir whose owning
    service auto-enables that DB → stale schema/version on the next install.
    """
    main_deps = _main_autodeps()
    blank_deps = _blank_reset_autodeps()

    diffs: list[str] = []
    for fact, label in DB_FACTS.items():
        in_main = main_deps[fact]
        in_blank = blank_deps[fact]
        missing = sorted(in_main - in_blank)   # in main.yml, not in blank-reset
        extra = sorted(in_blank - in_main)     # in blank-reset, not in main.yml
        if missing or extra:
            lines = [f"  {label} ({fact}):"]
            if missing:
                lines.append(
                    "    missing from blank-reset.yml (would orphan DB data): "
                    + ", ".join(missing)
                )
            if extra:
                lines.append(
                    "    extra in blank-reset.yml (not an auto-dep in main.yml): "
                    + ", ".join(extra)
                )
            diffs.append("\n".join(lines))

    if diffs:
        pytest.fail(
            "blank-reset.yml auto-dependency resolution has DRIFTED from "
            "main.yml's auto-enable logic. Re-sync the duplicated set_fact in "
            "tasks/blank-reset.yml so each database's driver list matches "
            "main.yml exactly:\n\n" + "\n\n".join(diffs)
        )
