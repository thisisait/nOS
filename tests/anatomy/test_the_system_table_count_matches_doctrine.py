"""The DataTable-engine contract must name the measured SYSTEM set.

`nos-sot:doctrine/cross-repo-contracts.md` froze "the 18" on 2026-09-05, when
state/keap-tables/ happened to hold 18 files. The glob is 33 now; bumping that
blindly to 33 would count fixture/user-shaped defs (print-*, kolben-*) as
SYSTEM. USER tables are KEAP-born and never in nOS git; the fixtures are a
third shape — tenant-demo furniture that happens to live in git.

This gate counts SYSTEM = every *.table.yml whose slug is NOT print-* or
kolben-*, and refuses a doctrine integer that does not match. It also pins
keap_repo_ref to the role default (today v2.0.0-rc.1), so a review's stale
tag cannot hide in the contract prose.

Offline: stdlib + the committed yaml. No live KEAP. The roadmap `when` 409
is a recorded exception in the same file; this gate only checks the exception
is named when the definition has already dropped the column.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES = REPO / "state" / "keap-tables"
DOCTRINE = REPO / "ssot" / "doctrine" / "cross-repo-contracts.md"
DEFAULTS = REPO / "roles" / "pazny.keap" / "defaults" / "main.yml"
ROADMAP = TABLES / "roadmap.table.yml"

#: Tenant-demo furniture. Party is the shared EN 16931 spine (accounting
#: rowRefs it) — SYSTEM, not a fixture prefix.
FIXTURE_PREFIXES = ("print-", "kolben-")


def _slugs() -> list[str]:
    files = sorted(TABLES.glob("*.table.yml"))
    assert files, f"no DataTable defs under {TABLES.relative_to(REPO)}"
    return [p.name[: -len(".table.yml")] for p in files]


def _system_slugs() -> list[str]:
    return [s for s in _slugs() if not s.startswith(FIXTURE_PREFIXES)]


def _doctrine() -> str:
    return DOCTRINE.read_text(encoding="utf-8")


def _keap_pin() -> str:
    m = re.search(r'^keap_repo_ref:\s*"([^"]+)"', DEFAULTS.read_text(encoding="utf-8"), re.M)
    assert m, f"{DEFAULTS.relative_to(REPO)} no longer declares keap_repo_ref"
    return m.group(1)


def test_doctrine_system_count_matches_the_tree():
    counted = len(_system_slugs())
    text = _doctrine()
    named = [int(n) for n in re.findall(r"SYSTEM tables \(the (\d+)\)", text)]
    named += [int(n) for n in re.findall(r"(\d+) of them are SYSTEM", text)]
    assert named, (
        f"{DOCTRINE.relative_to(REPO)} no longer names a SYSTEM count "
        "(expected 'SYSTEM tables (the N)' / 'N of them are SYSTEM')"
    )
    drift = sorted({n for n in named if n != counted})
    assert not drift, (
        f"doctrine SYSTEM count {drift} != measured SYSTEM set ({counted}): "
        + ", ".join(_system_slugs())
    )


def test_doctrine_total_defs_match_the_glob():
    counted = len(_slugs())
    text = _doctrine()
    m = re.search(r"(\d+)\s+DataTable DEFINITIONS live in nOS git", text)
    assert m, (
        f"{DOCTRINE.relative_to(REPO)} no longer says how many DEFINITIONS "
        "live in nOS git"
    )
    assert int(m.group(1)) == counted, (
        f"doctrine total {m.group(1)} != {counted} *.table.yml files"
    )
    fx = re.search(r"(\d+) are fixture/user-shaped", text)
    assert fx, "doctrine no longer names the fixture/user-shaped count"
    n_fx = counted - len(_system_slugs())
    assert int(fx.group(1)) == n_fx, (
        f"doctrine fixture count {fx.group(1)} != {n_fx} print-*/kolben-* defs"
    )


def test_doctrine_names_the_live_keap_pin():
    pin = _keap_pin()
    blob = re.sub(r"\s+", " ", _doctrine())
    assert f"`keap_repo_ref` (`{pin}`)" in blob, (
        f"{DOCTRINE.relative_to(REPO)} does not cite keap_repo_ref ({pin}) "
        "from roles/pazny.keap/defaults/main.yml. A stale review tag is how "
        "v1.47.0 outlived the tree."
    )


def test_roadmap_when_drop_is_a_recorded_exception():
    """Git dropped `when`; live still has it. Name that. Do not recreate."""
    src = ROADMAP.read_text(encoding="utf-8")
    if re.search(r"^  - key: when$", src, re.M) or re.search(r"^    - key: when$", src, re.M):
        return
    # Column keys in this tree are `  - key: <name>` under schema.columns.
    if re.search(r"key:\s*when\b", src):
        return
    text = _doctrine()
    assert "Recorded exception" in text and "roadmap.table.yml" in text, (
        "roadmap.table.yml dropped `when` but the contract does not record "
        "the live 409 as a known exception"
    )
    assert "409" in text and "`when`" in text, (
        "the recorded exception must name the 409 and the live `when` column"
    )
    assert "drop-and-recreate the live table" in text.lower() or (
        "Do not drop-and-recreate the live table" in text
    ), "the exception must forbid silently drop-and-recreating live roadmap"
