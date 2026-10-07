"""A state/ file that encodes an obligation is classified, never loose data.

WHY (repo-body-plan I-11, 2026-10-07). Some law lives as data in state/ (the
judge sets, the GDPR maps, the offboard order, the digest constitution). The
re-cut by realm left them in place because their readers name them there; this
gate keeps the next one from arriving unclassified. An obligation is read from
the file's own KEYS (a lawful basis, a retention, an erasure order, a consent
capture, a portability flag, an invariant, a gate set), never from its name.
"""
from __future__ import annotations

import pathlib
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
INDEX = yaml.safe_load((REPO / "ssot/INDEX.yml").read_text(encoding="utf-8"))
COMPANIONS = INDEX["realms"]["doctrine"]["companions"]
REALMS = [s["path"].rstrip("/") + "/" for s in INDEX["realms"].values()
          if not s["path"].startswith("$")]
OBLIGATION_KEYS = {
    "legal_basis", "retention", "retention_days",     # Art. 30 record
    "erasure", "keap_delete_order",                   # erase, and in what order
    "capture_wired", "portability_eligible",          # Art. 7 consent, Art. 20 export
    "invariants", "gate_sets",                        # rules a judge enforces
}
# Test data binds no one; a schema names a key, it does not hold a record.
NOT_LAW = ("state/fixtures/", "state/schema/")


def _keys(node, acc: set[str]) -> set[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(str(k))
            _keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            _keys(v, acc)
    return acc


def obligations(rel: str, text: str) -> set[str]:
    acc: set[str] = set()
    for doc in yaml.safe_load_all(text):
        _keys(doc, acc)
    return acc & OBLIGATION_KEYS


def _classified(rel: str) -> bool:
    return any(rel == c or (c.endswith("/") and rel.startswith(c)) for c in COMPANIONS) \
        or rel.startswith(tuple(REALMS)) or rel.startswith(NOT_LAW)


def _state_yml() -> list[str]:
    out = subprocess.run(["git", "ls-files", "state"], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.split()
    return [p for p in out if p.endswith((".yml", ".yaml")) and not (REPO / p).is_symlink()]


def test_the_companions_exist_and_carry_obligations():
    """Positive control: each listed file exists, and the key test sees the
    companions it was written from (all but the erasure map, whose rows are
    method/command per service: listed by ruling, not found by keys)."""
    for c in COMPANIONS:
        assert (REPO / c).exists(), c
    seen = [c for c in COMPANIONS if not c.endswith("/")
            and obligations(c, (REPO / c).read_text(encoding="utf-8"))]
    assert len(seen) >= 5, seen


def test_the_key_test_finds_an_unlisted_obligation():
    assert obligations("state/x.yml", "gdpr:\n  legal_basis: consent\n") == {"legal_basis"}
    assert not _classified("state/new-retention-map.yml")


def test_every_state_obligation_is_classified():
    loose = {}
    for rel in _state_yml():
        hits = obligations(rel, (REPO / rel).read_text(encoding="utf-8"))
        if hits and not _classified(rel):
            loose[rel] = sorted(hits)
    assert not loose, (
        "state/ files encode an obligation but no realm owns them; list each in "
        f"ssot/INDEX.yml realms.doctrine.companions (or move it into a realm): {loose}")
