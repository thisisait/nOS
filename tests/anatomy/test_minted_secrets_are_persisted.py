"""A secret that is minted but not persisted is minted AGAIN next run.

Found live on 2026-08-03. P2 moved `backup_encryption_passphrase` and
`restic_password` off the password prefix and into `main.yml`'s
lazy-regenerate group — which mints them with `openssl rand`. It did not add
them to `templates/secrets.yml.j2`, which is what writes them to
`~/.nos/secrets.yml`.

So every converge minted a fresh key and discarded it. The archive written on
Monday could not be opened on Tuesday. **That is strictly worse than the derived
key P2 replaced**: a weak key is recoverable, a forgotten one is not.

It surfaced because restic failed loudly — `Fatal: wrong password or no key
found` — on a repo `config.yml` enables and `default.config.yml` does not (the
version-pin shadow class: one file overriding another, and only the default was
checked). Had restic been off, the defect would have waited for a restore.

THE RULE
--------
    If main.yml MINTS it, secrets.yml.j2 must PERSIST it.

The lazy-regenerate group's own comment already says why, for a different
secret: "if these regenerated every run … nothing holding an old one could
reach the API, and 'the loop stopped answering' is not a boundary, it is an
outage."
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
TEMPLATE = REPO / "templates" / "secrets.yml.j2"

#: Minted values that are deliberately NOT persisted, each with the reason it
#: is safe to regenerate. Empty today — every current mint must persist. An
#: entry here is a claim that losing the old value costs nothing, and that claim
#: has to be written down where the next reader sees it.
EPHEMERAL: dict[str, str] = {}


def _minted() -> set[str]:
    """Names the lazy-regenerate set_fact replaces with fresh randomness.

    Parsed from the live task, not mirrored — a mirrored list is the thing that
    drifts, and this gate exists because two files disagreed.
    """
    block = re.search(
        r"Lazy-regenerate placeholder.*?\n      tags:", MAIN.read_text(), re.S
    )
    assert block, (
        "the lazy-regenerate set_fact was renamed or removed — this gate would "
        "silently stop checking anything"
    )
    body = block.group(0)
    names = set()
    for name in re.findall(r'^\s{8}([a-z0-9_]+):\s*"\{%', body, re.M):
        # Only the ones that actually mint. A branch that merely re-states the
        # existing value is not a mint and does not need persisting.
        stanza = re.search(rf'^\s{{8}}{re.escape(name)}:\s*"(.+)$', body, re.M)
        if stanza and ("openssl rand" in stanza.group(1) or "lookup('pipe'" in stanza.group(1)):
            names.add(name)
    assert len(names) >= 15, f"parsed only {len(names)} minted names — parser broke"
    return names


def _persisted() -> set[str]:
    return set(re.findall(r"^([a-z0-9_]+):\s", TEMPLATE.read_text(), re.M))


def test_every_minted_secret_is_persisted():
    missing = sorted(_minted() - _persisted() - set(EPHEMERAL))
    assert not missing, (
        "minted every run and never written to ~/.nos/secrets.yml — each of "
        "these gets a NEW value on the next converge, and whatever the old one "
        "encrypted or authenticated is unreachable:\n  "
        + "\n  ".join(missing)
        + f"\n\nAdd them to {TEMPLATE.relative_to(REPO)}, or declare them in "
        "EPHEMERAL with the reason losing the old value is free."
    )


def test_the_backup_key_ring_persists_with_its_key():
    """The ring is worth nothing if it does not outlive the process.

    `backup_encryption_keys_previous` holds every superseded key so archives
    written before a rotation still open. A ring that lives only in a fact is a
    ring that forgets at the end of the play — the exact failure it exists to
    prevent, one level down.
    """
    persisted = _persisted()
    for name in ("backup_encryption_passphrase", "backup_encryption_keys_previous"):
        assert name in persisted, (
            f"{name} is not persisted — see docs/archive/secret-blast-radius.md P2"
        )


def test_ephemeral_exemptions_carry_a_reason():
    for name, reason in EPHEMERAL.items():
        assert len(reason.strip()) >= 30, (
            f"{name} is exempted from persistence with no real justification. "
            "An exemption is a claim that losing the old value is free; say why."
        )
