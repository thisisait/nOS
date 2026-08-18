"""The face's group lists are a MIRROR. Mirrors need something to check them.

`files/anatomy/face/src/lib/security/tier.ts` says so in its own first line —
"the shell-side mirror of the Authentik group → tier map" — and then hard-codes
the group names:

    WRITE_GROUPS = ['nos-admins', 'nos-providers', 'nos-managers']
    ADMIN_GROUPS = ['nos-admins', 'nos-providers']

Those are tier 2 and tier 1 of `authentik_rbac_tiers` in `default.config.yml`,
and that variable is DOCUMENTED AS CONFIGURABLE — CLAUDE.md: "Group names are
configurable via `authentik_rbac_tiers`. Legacy installs provisioned before
2026-04-22 carry the old `devboxnos-*` prefix". So the rename this mirror
cannot survive is not hypothetical; it is a rename the estate has already done
once, and a tenant may do again.

WHY IT MATTERS EVEN THOUGH THE FACE DECIDES NOTHING. The file is careful to
say access "is decided server-side", and that is true — a stale mirror grants
no permission. What it does is hide the truth from the person holding the
screen: an operator whose groups were renamed sees write affordances that are
gone, or loses affordances they still have, and the UI disagrees with the
estate without either side being wrong about its own job.

MEASURED 2026-08-18: the same class had a live instance one layer in.
`roles/pazny.superset/templates/superset_config.py.j2` mapped Authentik groups
to FAB roles through an attribute lookup on a LIST, so tier renames never
reached Superset at all and `nos-providers` landed as Gamma. That one was a
comment describing a mapping that did not happen; this one is a copy that
nothing compares. Both are the same defect wearing different clothes, and the
Superset instance is why this file exists rather than a TODO.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TIER_TS = REPO / "files/anatomy/face/src/lib/security/tier.ts"
CONFIG = REPO / "default.config.yml"


def _ts_groups(name: str) -> set[str]:
    src = TIER_TS.read_text(encoding="utf-8")
    m = re.search(rf"export const {name}\s*=\s*\[(.*?)\]", src, re.S)
    assert m, f"{name} is gone from tier.ts — this gate's premise has changed"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _tier_groups(tier: int) -> set[str]:
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    rows = doc.get("authentik_rbac_tiers") or []
    row = next((r for r in rows if int(r.get("tier", -1)) == tier), None)
    assert row, f"authentik_rbac_tiers has no tier {tier}"
    return set(row.get("groups") or [])


def test_the_two_sides_are_both_readable():
    """Positive control — if either parse yields nothing, every comparison
    below passes by comparing emptiness to emptiness."""
    assert TIER_TS.is_file(), f"{TIER_TS} is gone"
    assert _ts_groups("ADMIN_GROUPS"), "parsed no groups out of ADMIN_GROUPS"
    assert _ts_groups("WRITE_GROUPS"), "parsed no groups out of WRITE_GROUPS"
    assert _tier_groups(1), "authentik_rbac_tiers tier 1 declares no groups"


def test_admin_groups_mirror_tier_1():
    ts, cfg = _ts_groups("ADMIN_GROUPS"), _tier_groups(1)
    assert ts == cfg, (
        f"tier.ts ADMIN_GROUPS {sorted(ts)} != authentik_rbac_tiers tier 1 "
        f"{sorted(cfg)}. The face would show admin affordances to the wrong "
        "set — or hide them from the right one — while the server keeps "
        "deciding correctly, so nothing errors and the UI is simply wrong."
    )


def test_write_groups_mirror_tier_2():
    """Tier 2 is the write boundary: its group list is every tier that may
    write, which is precisely what WRITE_GROUPS claims to be."""
    ts, cfg = _ts_groups("WRITE_GROUPS"), _tier_groups(2)
    assert ts == cfg, (
        f"tier.ts WRITE_GROUPS {sorted(ts)} != authentik_rbac_tiers tier 2 "
        f"{sorted(cfg)}. Renaming a tier group is a supported operation "
        "(CLAUDE.md), and this copy does not travel with it."
    )


def test_the_mirror_is_a_subset_relationship_the_config_actually_declares():
    """A structural check the two equalities cannot make: every admin group
    must also be a write group. If the config ever stopped nesting the tiers,
    both tests above could pass while the face's own `isWriteTier` logic —
    which assumes admins can write — became false."""
    admin, write = _tier_groups(1), _tier_groups(2)
    assert admin <= write, (
        f"tier 1 {sorted(admin)} is not contained in tier 2 {sorted(write)}; "
        "the face treats admin as a strict subset of write, so an operator "
        "in an admin-only group would be shown as read-only."
    )
