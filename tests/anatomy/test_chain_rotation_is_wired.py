"""The rotation's correctness is its ORDER, so the order is what this pins.

`test_audit_chain_key_rotation.py` proves the ring works. This proves the
playbook performs it in the one sequence that is correct:

    seal the anchor  →  mint the new key  →  retire the old one

Sealing after minting is the failure that looks like success's opposite: the
first row signed with the new key lands mid-segment, the elected key cannot
verify it, and `verify-audit-chain.php` reports CHAIN-BROKEN at exactly the row
that proves nothing was tampered with. An operator would then be looking for an
intruder.

REHEARSED, not reasoned about — on a copy of the live 140,758-row chain,
2026-08-06:

    baseline (current key)          CHAIN-OK: 140758 rows
    seal anchor + rotate + 1 row
    ring (new + retired)            CHAIN-OK: 140759 rows
    new key alone                   CHAIN-BROKEN at id=1   ← the control

The last line is the one worth keeping: without the retired key the chain does
NOT quietly pass. A ring that accepted anything would be worse than losing the
history.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
WING_PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
WING_PLUGIN = REPO / "files/anatomy/plugins/wing-base/plugin.yml"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
WING_POST = REPO / "roles/pazny.wing/tasks/post.yml"
SECRETS_TPL = REPO / "templates/secrets.yml.j2"

RETIRED = "bone_secret_retired"


def _main_text() -> str:
    return MAIN.read_text(encoding="utf-8")


def test_the_anchor_is_sealed_before_the_key_is_minted():
    text = _main_text()
    seal = text.find("Seal the current head as a rotation anchor")
    retire = text.find("Retire the outgoing key onto the ring")
    mint = text.find("_bone_secret_rotating | default(false) or '_pw_' in (bone_secret")
    assert seal != -1, "the anchor-sealing task is gone — rotation now breaks the chain"
    assert retire != -1, "the retire-onto-the-ring task is gone"
    assert mint != -1, "the bone_secret mint no longer honours rotation"
    assert seal < retire < mint, (
        "the rotation steps are out of order. Sealing must precede minting, or "
        "the first row signed with the new key lands mid-segment and the chain "
        "reads as tampered at the row that proves it was not.\n"
        f"  seal@{seal} retire@{retire} mint@{mint}"
    )


def test_the_seal_and_the_retire_share_one_condition():
    """Half a rotation is worse than none: an anchor with no new key is a
    harmless no-op, but a new key with no anchor breaks the chain. Both tasks
    carry the same guard so they cannot diverge."""
    text = _main_text()
    block = text[text.find("Seal the current head as a rotation anchor"):
                 text.find("Rotation summary")]
    guards = re.findall(r"bone_secret_rotate \| default\(false\) \| bool", block)
    assert len(guards) == 2, (
        f"expected the same rotate guard on both the seal and the retire task, "
        f"found {len(guards)}"
    )


def test_the_ring_reaches_every_place_that_verifies():
    assert RETIRED in SECRETS_TPL.read_text(encoding="utf-8"), (
        "the retired ring is not persisted to ~/.nos/secrets.yml — it is the "
        "ONLY durable record of a retired key, and losing it makes every row "
        "signed before the last rotation unverifiable forever"
    )
    assert "WING_EVENTS_HMAC_SECRET_RETIRED" in WING_PLIST.read_text(encoding="utf-8"), (
        "the Wing daemon has no retired ring"
    )
    plugin = yaml.safe_load(WING_PLUGIN.read_text(encoding="utf-8"))
    jobs = {j["name"]: j for j in (plugin.get("pulse") or {}).get("jobs", [])}
    verify_env = jobs.get("audit-chain-verify", {}).get("env", {})
    assert "WING_EVENTS_HMAC_SECRET_RETIRED" in verify_env, (
        "the nightly audit-chain-verify job has no retired ring — it is the job "
        "that would go red the morning after a rotation"
    )


def test_the_ring_token_can_actually_render():
    """A bare `{{ token }}` the catalog does not know reaches Wing verbatim.

    It is a literal str.replace over a fixed map, and this token is
    legitimately EMPTY until the first rotation — so an omission here would
    look like "no rotation yet" rather than like a bug.
    """
    assert '"{{ bone_secret_retired }}"' in CATALOG.read_text(encoding="utf-8"), (
        "the catalog cannot render {{ bone_secret_retired }}"
    )
    assert "NOS_BONE_SECRET_RETIRED" in WING_POST.read_text(encoding="utf-8"), (
        "the substitution key exists but nothing feeds it a value"
    )


def test_sqlite3_is_not_assumed_to_live_under_homebrew():
    """Measured 2026-08-06: it does not. macOS ships /usr/bin/sqlite3 and brew
    installs no sqlite CLI by default, so `{{ homebrew_prefix }}/bin/sqlite3`
    would have failed the rotation at its very first step."""
    text = _main_text()
    block = text[text.find("Seal the current head as a rotation anchor"):
                 text.find("Retire the outgoing key onto the ring")]
    # Comment lines out FIRST. The first draft failed on its own explanation —
    # the comment naming the wrong path was read as the wrong path. Third time
    # today that a comment was mistaken for data; strip, then judge.
    block = "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#"))
    assert "homebrew_prefix" not in block, (
        "the anchor task resolves sqlite3 under homebrew_prefix, where it is "
        "not installed on macOS"
    )
    assert '- "sqlite3"' in block, "the anchor task no longer invokes sqlite3"
