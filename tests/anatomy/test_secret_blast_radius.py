"""How many credentials does one leaked string yield?

`{prefix}_pw_{service}` is not a derivation, it is CONCATENATION: the rendered
credential contains the master in clear, so any single leaked value reveals the
master by inspection, and the master yields every sibling by construction. That
is why REM-144 was not "an edge token leaked" but "the estate leaked".

This gate turns blast radius from a claim into a measured number.

State after P2 (2026-08-02):

    101 credential names DECLARED as prefix-derived, of which 17 are rescued at
    runtime by main.yml's lazy-regenerate group -> 86 are TRULY derived.

CROWN JEWELS are the keys whose compromise costs more than one service, because
what they protect CONTAINS other credentials:

    backup_encryption_passphrase  -> the nightly archive
    restic_password               -> the off-site repo

`backup_nos_state: true` puts the plaintext `~/.nos/secrets.yml` (29 keys, 27
credential-shaped, holding the RANDOMLY generated secrets) inside that archive.
While its key was derived, the chain ran

    prefix -> archive key -> the archive -> every random secret

and REM-144 leaked the prefix. P2 broke it: both keys are now minted random and
persisted, with the outgoing derived key preserved in a read-only key ring so
archives written before the rotation still open. CROWN_JEWEL_CEILING is 0.

TWO MISTAKES THIS FILE MADE, KEPT AS INSTRUCTIONS:

1. MEASURE THE RUNTIME VALUE, NOT THE DECLARATION. The first version counted
   declaration sites and reported `infisical_encryption_key` as derived -- "the
   vault is inside its own blast radius". Wrong: it is in the lazy-regenerate
   group and the live value is 32 hex with no `_pw_`. Reading the shape instead
   of the effect is the defect v0.10-beta is named after.

2. ...BUT NOT FOR THE CROWN JEWELS. Applying lesson 1 to them made the crown
   jewel test VACUOUS -- restoring the derived default left it green, because
   the key was also in the rescue list. For a key protecting other credentials,
   "something else randomises it" is a coupling between two files, not safety.
   That test asserts on the DECLARATION on purpose; both forms were verified by
   putting the derivation back and watching it go red.

Plan: docs/plans/secret-blast-radius.md

The ceilings below are RATCHETS, not targets. They record today's reality so the
number cannot silently grow, and each phase of the plan lowers them. The end
state is CROWN_JEWEL_CEILING = 0 and MAX_BLAST_RADIUS = 1.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The literal that every derived credential is built from.
MASTER = "global_password_prefix"

#: `name: "{{ global_password_prefix }}..."` — a credential minted by concatenation.
DERIVED = re.compile(
    r"^\s*([a-z0-9_]+):\s*[\"']?\{\{\s*" + MASTER + r"\b", re.MULTILINE
)

#: Keys whose compromise does not cost one service, but every service — because
#: what they protect CONTAINS other credentials.
CROWN_JEWELS = {
    "backup_encryption_passphrase": "the nightly archive (which contains ~/.nos/secrets.yml)",
    "restic_password": "the off-site restic repo",
    # infisical_encryption_key WOULD belong here on its declaration, but the
    # lazy-regenerate group randomises it at runtime — so it is not derived in
    # practice. Kept as a comment so nobody "re-discovers" it from the template.
}

# ── Ratchets. Lower these as the plan lands; never raise them. ───────────────
BLAST_RADIUS_CEILING = 86    # runtime, after lazy-regenerate. P1 drives this to 1
DECLARED_CEILING = 101       # declaration sites; falls as defaults stop being templates
CROWN_JEWEL_CEILING = 0      # P2 landed 2026-08-02 — must never come back


def _sources() -> list[Path]:
    out = [REPO / "default.credentials.yml", REPO / "default.config.yml"]
    out += sorted((REPO / "roles").glob("*/defaults/main.yml"))
    return [p for p in out if p.is_file()]


def _lazy_regenerated() -> set[str]:
    """Names main.yml replaces with `openssl rand` on first run, then persists.

    These are declared as `{{ prefix }}_pw_x` in the defaults but never hold
    that value on a converged host, so counting them as derived overstates the
    blast radius. Parsed from the live task rather than mirrored, because a
    mirrored list is the thing that drifts.
    """
    main = (REPO / "main.yml").read_text()
    blk = re.search(r"Lazy-regenerate placeholder.*?\n      tags:", main, re.S)
    assert blk, (
        "the lazy-regenerate set_fact task was renamed or removed — this gate "
        "would silently start counting rescued credentials as derived"
    )
    names = set(re.findall(r"^\s{8}([a-z0-9_]+):\s*\"\{%", blk.group(0), re.M))
    assert len(names) >= 15, f"parsed only {len(names)} lazy-regenerated names — parser broke"
    return names


def _scan() -> tuple[set[str], int, list[str]]:
    names: set[str] = set()
    sites = 0
    where: list[str] = []
    for path in _sources():
        hits = DERIVED.findall(path.read_text(encoding="utf-8", errors="replace"))
        if hits:
            where.append(f"{path.relative_to(REPO)}: {len(hits)}")
        names |= set(hits)
        sites += len(hits)
    return names, sites, where


def test_blast_radius_does_not_grow():
    """One leaked string must not buy MORE than it already does."""
    declared, sites, where = _scan()
    names = declared - _lazy_regenerated()
    assert len(declared) <= DECLARED_CEILING, (
        f"declared-derived credentials GREW to {len(declared)} "
        f"(ceiling {DECLARED_CEILING})"
    )
    assert len(names) <= BLAST_RADIUS_CEILING, (
        f"RUNTIME blast radius GREW to {len(names)} (ceiling {BLAST_RADIUS_CEILING}). "
        f"A new credential was minted by concatenating {MASTER}. Derive it "
        f"instead — see docs/plans/secret-blast-radius.md P1.\n  "
        + "\n  ".join(where)
    )



def test_crown_jewels_do_not_grow():
    """A key that protects OTHER credentials must not be derived from the master.

    These are the difference between "a service password leaked" and "every
    secret leaked", because what they encrypt contains the rest.
    """
    # DECLARED, not runtime — deliberately stricter than the blast-radius test.
    #
    # A first version of this subtracted the lazy-regenerate rescue here too,
    # and was VACUOUS: putting the derived default straight back into
    # roles/pazny.backup/defaults/main.yml left it green, because the key was
    # also in the rescue list. For a key that protects OTHER credentials,
    # "something else happens to randomise it" is not safety — it is a coupling
    # between two files, and deleting one line in the rescue list would re-arm
    # the derivation silently. The default itself must be safe.
    declared, _, _ = _scan()
    live = sorted(declared & set(CROWN_JEWELS))
    assert len(live) <= CROWN_JEWEL_CEILING, (
        "a key protecting OTHER credentials is now derived from the master:\n  "
        + "\n  ".join(f"{k} → {CROWN_JEWELS[k]}" for k in live)
    )
    # Name them in the report even while the ceiling tolerates them, so the
    # debt is visible on every green run rather than only when it worsens.
    if live:
        print(
            "\nOUTSTANDING crown-jewel derivations (P2 removes these):\n  "
            + "\n  ".join(f"{k} → {CROWN_JEWELS[k]}" for k in live)
        )


def test_the_backup_contains_the_secrets_file_it_is_keyed_against():
    """The specific chain that makes this urgent, pinned as a fact.

    prefix → backup key → the archive → ~/.nos/secrets.yml → every RANDOM secret.

    While all three links hold, the estate's at-rest backup encryption is worth
    exactly as much as the prefix. This test does not fail on that (P2 is the
    fix); it fails if someone believes they have fixed it by touching only ONE
    link, which would leave the chain intact and the docs wrong.
    """
    backup_defaults = (REPO / "roles/pazny.backup/defaults/main.yml").read_text()
    config = (REPO / "default.config.yml").read_text()

    key_derived = bool(
        re.search(r"backup_encryption_passphrase:\s*[\"']?\{\{\s*" + MASTER, backup_defaults)
    )
    state_in_backup = bool(re.search(r"^backup_nos_state:\s*true", backup_defaults, re.M))

    if not key_derived:
        # P2 landed. Then the archive may safely keep carrying the state file.
        return
    assert state_in_backup, (
        "backup_nos_state changed while backup_encryption_passphrase is STILL "
        "derived from the master — if this was meant to break the chain, it "
        "broke the wrong link: the key is the problem, not the payload. "
        "See docs/plans/secret-blast-radius.md P2."
    )
    assert "_pw_restic" in config or "restic_password" in config, (
        "restic_password vanished from default.config.yml — if the off-site key "
        "moved, update CROWN_JEWELS here so the ratchet still counts it"
    )
