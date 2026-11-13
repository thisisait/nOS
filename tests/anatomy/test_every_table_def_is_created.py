"""Every DataTable definition has a creator (live path, ssot/doctrine/gates.md §7).

2026-11-13: morning-verdict, efferent-queue and loop-ticks had definitions, gate lines and writers,
and no converge task created the tables, so the 07:10 Pulse job failed "unknown table". The UNSEEDED
allow-list said "rows are written at runtime" and was read as "the table exists": rows and tables
are two different facts. A definition is now either named by a task the converge runs, or listed
here with who creates its table instead. A new definition without either is red.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Tables a converge task does not create, with their creator. Known 2026-11-13 and to be verified
# one by one (row keap-tables-each-has-a-creator); the list may only shrink.
CREATED_ELSEWHERE = {
    "apps": "the app generator (manifest apps), not the playbook seeder",
    "systems": "the service registry",
    "repo": "the repos importer (tools/digest-import-repos.py)",
    "application": "unverified 2026-11-13: digest/importer output — row keap-tables-each-has-a-creator",
    "package": "unverified 2026-11-13: digest/importer output — row keap-tables-each-has-a-creator",
    "device": "unverified 2026-11-13: the device organ — row keap-tables-each-has-a-creator",
    "device-extraction": "unverified 2026-11-13: the device organ — row keap-tables-each-has-a-creator",
    "invoice-review": "unverified 2026-11-13: the books importer — row keap-tables-each-has-a-creator",
    "party-address": "unverified 2026-11-13: the party importer — row keap-tables-each-has-a-creator",
    "party-contact": "unverified 2026-11-13: the party importer — row keap-tables-each-has-a-creator",
    "loop-config": "unverified 2026-11-13: the loops organ — row keap-tables-each-has-a-creator",
    "print-job": "a tenant-demo fixture definition, not an estate table",
    "print-job-step": "a tenant-demo fixture definition, not an estate table",
    "print-machine": "a tenant-demo fixture definition, not an estate table",
    "print-material": "a tenant-demo fixture definition, not an estate table",
    "print-order": "a tenant-demo fixture definition, not an estate table",
    "kolben-engineer": "a tenant-demo fixture definition, not an estate table",
    "kolben-project": "a tenant-demo fixture definition, not an estate table",
    "kolben-ticket": "a tenant-demo fixture definition, not an estate table",
    "kolben-time-entry": "a tenant-demo fixture definition, not an estate table",
}


def _converge_text() -> str:
    files = [*REPO.glob("roles/*/tasks/*.yml"), *REPO.glob("tasks/**/*.yml"), *REPO.glob("roles/*/templates/*.j2"),
             *REPO.glob("files/anatomy/plugins/*/plugin.yml")]
    # Comment lines out: a "# see x.table.yml" note is not a creator (review 13d).
    return "\n".join(line for p in files for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                     if not line.lstrip().startswith(("#", "{#")))


def _defs() -> list[str]:
    return sorted(p.name[: -len(".table.yml")] for p in (REPO / "state/keap-tables").glob("*.table.yml"))


def test_every_table_def_is_created_or_names_its_creator():
    text = _converge_text()
    missing = [d for d in _defs() if f"keap-tables/{d}.table.yml" not in text and d not in CREATED_ELSEWHERE]
    assert not missing, (
        f"{missing}: a table definition nothing creates. Add it to roles/pazny.keap/tasks/seed-core-tables.yml "
        "(rows: [] if its rows come at runtime), or name its creator in CREATED_ELSEWHERE.")


def test_the_elsewhere_list_holds_no_created_table():
    """The list may only shrink: an entry the converge now creates must leave it."""
    text = _converge_text()
    stale = [d for d in CREATED_ELSEWHERE if f"keap-tables/{d}.table.yml" in text]
    gone = [d for d in CREATED_ELSEWHERE if d not in _defs()]
    assert not stale and not gone, f"created by a task now: {stale}; no definition any more: {gone}"
