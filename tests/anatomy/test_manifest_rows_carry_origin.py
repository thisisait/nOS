"""Anatomy gate — every manifest row says whose software it is.

WHY (repo-body-plan I-12, 2026-10-07; ssot/doctrine/body-plan.md §4.1). `software_owner` in
config.d/20-host-software.yml classes the HOST packages (self / symbiont /
habitat), but the 73 organs of state/manifest.yml carried no origin at all, so
"nOS's own part" and "vendor software nOS runs" were told apart by reading
role code. The row now carries the same key with the same two values that can
be an organ: `self` (one of nOS's own parts — its code is in this repo or a
contract-declared sibling) or `symbiont` (declared vendor software beside nOS).
Habitat is the machine owner's and is never a row.

What it reads, all artifacts:
  (a) the schema requires the field and closes the enum;
  (b) every row carries one of the two values;
  (c) a `self` row's source is under files/anatomy/<id>/ or a contract dir
      files/anatomy/contracts/<id>/, or SELF_SOURCE_ELSEWHERE names where
      (shrink-only);
  (d) the row's owner and the host-package lists never disagree: a row's
      brew_formula or symbiont cask found in a classed list carries that
      list's class.
"""
from __future__ import annotations

import functools
import json
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = REPO / "state" / "manifest.yml"
SCHEMA = REPO / "state" / "schema" / "manifest.schema.json"
ROW_OWNERS = {"self", "symbiont"}

#: self rows whose code is not under files/anatomy/<id>/ — where it is instead.
#: 2026-10-07. Only ever delete lines (move the code or write the contract).
SELF_SOURCE_ELSEWHERE = {
    "backup": "roles/pazny.backup/files/backup.sh",
    "iiab_terminal": "files/iiab-terminal/iiab_terminal.py",
    "nos_forum": "roles/pazny.nos_forum",   # own repo ghcr.io/pazny/nos-forum-web; joint pending
}


@functools.lru_cache(maxsize=None)
def _rows() -> tuple[dict, ...]:
    return tuple(yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"])


@functools.lru_cache(maxsize=None)
def _defaults() -> dict:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415
    return nos_identity.default_config()


def _names(entries) -> set[str]:
    return {str(e.get("name") if isinstance(e, dict) else e) for e in entries or []}


def self_source_problems(rows) -> list[str]:
    bad = []
    for r in rows:
        if r.get("software_owner") != "self":
            continue
        rid = r["id"]
        dashed = rid.replace("_", "-")
        homes = (REPO / "files" / "anatomy" / dashed, REPO / "files" / "anatomy" / "contracts" / dashed)
        if any(h.is_dir() for h in homes):
            continue
        where = SELF_SOURCE_ELSEWHERE.get(rid)
        if not where:
            bad.append(f"{rid}: self, but no files/anatomy/{dashed}/, no contracts/{dashed}/ and "
                       f"not in SELF_SOURCE_ELSEWHERE")
        elif not (REPO / where).exists():
            bad.append(f"{rid}: SELF_SOURCE_ELSEWHERE names {where}, which does not exist")
    return bad


def host_list_disagreements(rows, defaults: dict) -> list[str]:
    """A row's brew_formula found in a classed formula list, or a cask whose
    `flag` is the row's install_flag, must carry that list's class. Joined on
    the declared package, never the row id: the `infisical` and `ntfy` formulae
    are CLIs beside the server rows of the same name."""
    owner = defaults["software_owner"]
    formulae = {name: (lst, cls) for lst, cls in owner.items() if lst.startswith("homebrew_")
                for name in _names(defaults.get(lst))}
    casks = {c["flag"]: (lst, cls) for lst, cls in owner.items() if lst.endswith("_casks")
             for c in defaults.get(lst) or [] if isinstance(c, dict) and c.get("flag")}
    bad = []
    for r in rows:
        for key, table in (("brew_formula", formulae), ("install_flag", casks)):
            hit = table.get(str(r.get(key) or ""))
            if hit and hit[1] != r.get("software_owner"):
                bad.append(f"{r['id']}: row says {r.get('software_owner')!r}, {hit[0]} says {hit[1]!r} ({key} {r.get(key)})")
    return bad


# ── the gates ─────────────────────────────────────────────────────────────


def test_the_schema_requires_the_origin_and_closes_it():
    svc = json.loads(SCHEMA.read_text(encoding="utf-8"))["definitions"]["service"]
    assert "software_owner" in svc["required"], "software_owner is optional in the schema"
    assert set(svc["properties"]["software_owner"]["enum"]) == ROW_OWNERS, "habitat is never a row"


def test_every_row_says_whose_it_is():
    bad = [f"{r['id']}: software_owner {r.get('software_owner')!r}" for r in _rows()
           if r.get("software_owner") not in ROW_OWNERS]
    assert not bad, "rows without an origin (self | symbiont; body-plan.md §4.1):\n  " + "\n  ".join(bad)


def test_a_self_row_has_its_source_in_the_repo():
    bad = self_source_problems(_rows())
    assert not bad, "\n  ".join(["a self organ's code is nOS's own:", *bad])
    unused = sorted(k for k in SELF_SOURCE_ELSEWHERE if k not in {r["id"] for r in _rows()
                    if r.get("software_owner") == "self"})
    assert not unused, f"SELF_SOURCE_ELSEWHERE names rows that are not self rows: {unused}"


def test_row_owner_and_host_lists_agree():
    bad = host_list_disagreements(_rows(), _defaults())
    assert not bad, "\n  ".join(["one package, two owners:", *bad])


def test_the_readers_can_go_red():
    planted = [{"id": "zzz_planted", "software_owner": "self"},
               {"id": "openhuman", "software_owner": "self", "install_flag": "install_openhuman"},
               {"id": "x", "software_owner": "symbiont", "brew_formula": "git"}]
    assert ("zzz_planted: self, but no files/anatomy/zzz-planted/, no contracts/zzz-planted/ and "
            "not in SELF_SOURCE_ELSEWHERE") in self_source_problems(planted)
    hits = host_list_disagreements(planted, _defaults())
    assert any(h.startswith("openhuman: row says 'self', homebrew_symbiont_casks says 'symbiont'") for h in hits), hits
    assert any(h.startswith("x: row says 'symbiont', homebrew_installed_packages says 'self'") for h in hits), hits
