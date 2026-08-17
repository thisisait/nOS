"""Two copies of a blueprint, one of which renders. They must be identical.

The authentik-base plugin's own header states the arrangement and the
condition it rests on (`files/anatomy/plugins/authentik-base/plugin.yml`):

    roles/pazny.authentik/tasks/blueprints.yml KEEPS RENDERING for now
    (Phase 2 C1+C5 deletes the role-side after Q2 lands per-plugin
    `authentik:` blocks across 35 services). Both render to the same
    target dir; templates are BYTE-IDENTICAL -> idempotent.

MEASURED 2026-08-17: they were not. `30-agent-clients.yaml.j2` carried, in
the ROLE copy only:

    grant_types:
      - "client_credentials"

with a comment explaining that Authentik 2026.5.x made `grant_types` an
explicit ArrayField defaulting to EMPTY, and that an unset list mints no
tokens. The PLUGIN copy lacked all five lines, the plugin loader renders
last, and so the deployed blueprint contained the fix nowhere: `grep -c
grant_types` over the rendered file returned 0.

WHAT IT COST. Every agent provider created after the divergence came up
without the client_credentials grant. Existing agents kept working — their
providers were created while a correct render was live — so the estate
looked healthy from every angle: the blueprint applied, the providers
existed, scout and conductor authenticated. The tenth agent could not get a
token, and the error Authentik returns for a missing grant is
`invalid_grant`, which reads as a wrong secret. Both secrets matched
byte-for-byte on both sides; the hours went into the wrong half.

THE SHAPE, which is worth more than the instance: a fix applied to the copy
that no longer renders. The doctrine did not merely fail to prevent it — the
doctrine ASSERTED the property that would have prevented it, and nothing
checked. That is the estate's own recurring lesson (a success marker written
by the thing being measured) wearing a comment instead of a status field.

RETIRE THIS FILE when Phase 2 C1+C5 deletes the role-side copies. A single
source cannot disagree with itself, and this gate should not outlive the
duplication it guards.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE_DIR = REPO / "roles/pazny.authentik/templates/blueprints"
PLUGIN_DIR = REPO / "files/anatomy/plugins/authentik-base/blueprints"


def _pairs() -> dict[str, tuple[pathlib.Path, pathlib.Path]]:
    """Blueprints that exist in BOTH trees. A file present in only one place
    is the migrated (or not-yet-migrated) state and is not this gate's
    business — five of the seven are plugin-only today."""
    out = {}
    for role_file in sorted(ROLE_DIR.glob("*.yaml.j2")):
        twin = PLUGIN_DIR / role_file.name
        if twin.is_file():
            out[role_file.name] = (role_file, twin)
    return out


def test_both_blueprint_trees_are_present():
    """Positive control — if either directory has moved, every check below
    passes by finding nothing."""
    assert ROLE_DIR.is_dir(), f"{ROLE_DIR} is gone; this gate cannot compare anything"
    assert PLUGIN_DIR.is_dir(), f"{PLUGIN_DIR} is gone — the live render path moved"
    assert list(PLUGIN_DIR.glob("*.yaml.j2")), "the plugin tree holds no blueprints at all"


def test_a_duplicated_blueprint_is_byte_identical():
    """The plugin header claims this. Nothing enforced it until it broke."""
    pairs = _pairs()
    if not pairs:
        # Not a failure: C1+C5 may have landed. Say so rather than pass mutely.
        assert not list(ROLE_DIR.glob("*.yaml.j2")), (
            "role-side blueprints exist but none has a plugin twin — the pairing "
            "this gate reasons about has changed shape; re-read it, do not delete it."
        )
        return

    diverged = []
    for name, (role_file, plugin_file) in pairs.items():
        if role_file.read_bytes() != plugin_file.read_bytes():
            r, p = role_file.read_text().splitlines(), plugin_file.read_text().splitlines()
            only_role = [ln.strip() for ln in r if ln not in p][:3]
            only_plugin = [ln.strip() for ln in p if ln not in r][:3]
            diverged.append(f"{name}: role-only={only_role} plugin-only={only_plugin}")

    assert not diverged, (
        "duplicated blueprint(s) disagree:\n  " + "\n  ".join(diverged) +
        "\n\nThe PLUGIN copy is the one that renders (the loader's pre_compose "
        "hook runs after the role task writes the same path), so a fix living "
        "only in the role copy is applied to nothing. Port it, or delete the "
        "role-side copy if C1+C5 has landed."
    )


def test_the_agent_grant_survives_in_the_copy_that_renders():
    """The specific line the divergence swallowed, pinned in the live path.

    Named rather than left to the byte-comparison above: if both copies were
    ever 'fixed' by deleting the block from the role side, they would agree
    and mint no tokens, and this estate would be back to an `invalid_grant`
    that reads like a wrong password.
    """
    live = PLUGIN_DIR / "30-agent-clients.yaml.j2"
    if not live.is_file():
        return  # the agent-clients blueprint moved; the pair gate covers the rest
    src = live.read_text(encoding="utf-8")
    assert "grant_types:" in src and '"client_credentials"' in src, (
        "the rendered agent-clients blueprint no longer grants client_credentials. "
        "Authentik 2026.5.x defaults grant_types to EMPTY, an empty list mints no "
        "tokens, and every agent provider created from this render will fail to "
        "authenticate with `invalid_grant` — an error that names the wrong cause."
    )
