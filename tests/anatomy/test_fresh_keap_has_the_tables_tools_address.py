"""A fresh KEAP holds every table the default tools address.

After `nos --remove=data` (2026-10-09) `nos dtt seed --sync` died on a 404: the
roadmap table was created by hand once, years of tools hard-code its id, and no
converge task ever created it. current-state (the agents' claim board) and the
books spine the face's Books app reads were missing the same way.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "roles/pazny.keap/tasks"
REQUIRED = ["current-state", "party", "party-tax-identity", "account", "invoice", "invoice-line",
            "journal-entry", "posting", "pending-invoice-verify", "book-access"]


def _roadmap_id() -> str:
    m = re.search(r'NOS_ROADMAP_TABLE_ID", "([^"]+)"', (REPO / "tools/roadmap-seed.py").read_text())
    return m.group(1)


def _seeded_on_keap_alone() -> set[str]:
    out = set()
    for t in yaml.safe_load((TASKS / "post.yml").read_text()):
        inc, when = t.get("ansible.builtin.include_tasks"), t.get("when")
        when = [when] if isinstance(when, str) else (when or [])
        if inc and inc.startswith("seed-") and all("install_keap" in w for w in when):
            text = (TASKS / inc).read_text()
            text = text.replace("{{ keap_roadmap_table_id }}", _role_default("keap_roadmap_table_id"))
            out |= set(re.findall(r'slug: "([^"{]+)"', text))
    return out


def _role_default(name: str) -> str:
    return str((yaml.safe_load((REPO / "roles/pazny.keap/defaults/main.yml").read_text()) or {}).get(name, ""))


def test_every_addressed_table_is_created_by_a_converge():
    seeded = _seeded_on_keap_alone()
    missing = [s for s in [_roadmap_id()] + REQUIRED if s not in seeded]
    assert not missing, f"a fresh KEAP lacks tables the default tools address: {missing}"


def test_an_existing_roadmap_is_created_never_reshaped():
    """The estate's roadmap predates its definition (refs text, a `when` column);
    a reconcile against it is a 409 that fails the converge. Create only."""
    core = (TASKS / "seed-core-tables.yml").read_text()
    item = core[core.index("keap_roadmap_table_id"):core.index('slug: "current-state"')]
    assert "create_only: true" in item
    seeder = (TASKS / "seed-face-table.yml").read_text()
    assert "create_only" in seeder, "the shared seeder ignores create_only"
