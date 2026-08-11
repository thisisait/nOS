"""Anatomy gate: the e2e spec's contract number must equal the one the organ ships.

MEASURED 2026-08-11. `CORTEX_CONTRACT_VERSION` went to 2 when the agent noun and
`delegate` landed; the e2e spec kept asserting

    expect(health.contracts.cortex).toBe(1);

so the Cortex CI job went red — `Expected: 1, Received: 2` — and stayed red for
two days across four pushes. Nothing was broken. The organ was right, the spec
was stale, and the only signal was a job nobody could distinguish from a real
regression by looking at the badge.

WHY THE SYNC GATE DID NOT CATCH IT. `test_vendored_cortex_matches_keap.py`
compares the vendored copy against KEAP's byte for byte, and both said 1. Two
copies agreeing with each other and neither agreeing with the code — the same
shape as the four documents that agreed FreeScout was gated while Traefik sent
it through the open branch.

WHY THE SPEC SHOULD KEEP A LITERAL. The obvious "fix" is to have the spec import
`CORTEX_CONTRACT_VERSION` and assert against it, which would make the assertion
unfalsifiable: a test that reads the value it is checking passes whatever the
value becomes, and the contract number stops being pinned by anything. So the
literal stays, and THIS file is what makes it move.

WHAT THIS CANNOT DO: tell you whether a bump was warranted. It only refuses the
state where the code says one number and the test that guards it says another.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
OPCODES = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"
SPEC = REPO / "files/anatomy/cortex/e2e/validate.spec.ts"


def _declared() -> int:
    m = re.search(
        r"export const CORTEX_CONTRACT_VERSION\s*=\s*(\d+)",
        OPCODES.read_text(encoding="utf-8"),
    )
    assert m, (
        f"CORTEX_CONTRACT_VERSION is no longer declared in "
        f"{OPCODES.relative_to(REPO)}. This gate reads it from there; without it "
        "the gate is blind and the spec is unpinned again."
    )
    return int(m.group(1))


#: EVERY place the spec writes the contract number down, not just the first.
#: The first cut of this gate matched only `health.contracts.cortex` and shipped
#: green while `data.contract` — the SAME number, published by the opcode
#: registry twelve lines further down — was still 1. CI found the second one on
#: the next push. A gate that covers one of two identical literals is not half a
#: gate; it is a gate that reports the file as checked.
ASSERTIONS = (
    r"expect\(\s*health\.contracts\.cortex\s*\)\.toBe\(\s*(\d+)\s*\)",
    r"expect\(\s*data\.contract\s*\)\.toBe\(\s*(\d+)\s*\)",
)


def _asserted_all() -> list[int]:
    text = SPEC.read_text(encoding="utf-8")
    found: list[int] = []
    for pattern in ASSERTIONS:
        m = re.search(pattern, text)
        assert m, (
            f"{SPEC.relative_to(REPO)} no longer asserts a literal contract "
            f"number for /{pattern}/. If it now compares against the imported "
            "constant, the assertion cannot fail and the contract version is "
            "pinned by nothing — see this file's docstring for why the literal "
            "is deliberate."
        )
        found.append(int(m.group(1)))
    return found


def test_the_spec_asserts_the_version_the_organ_ships() -> None:
    declared, asserted = _declared(), _asserted_all()[0]
    assert asserted == declared, (
        f"the cortex organ ships contract v{declared} and the e2e spec asserts "
        f"v{asserted}. CI fails with 'Expected: {asserted}, Received: {declared}' "
        "and it is not a regression — it is a bump nobody carried into the spec. "
        "Update both copies of validate.spec.ts (the vendored one and KEAP's; "
        "test_vendored_cortex_matches_keap.py compares them byte for byte)."
    )


def test_the_version_is_a_plausible_contract_number() -> None:
    """Guard against a regex that starts matching something else entirely."""
    v = _declared()
    assert 1 <= v <= 99, (
        f"CORTEX_CONTRACT_VERSION read as {v}. That is not a contract version, "
        "so this gate is matching the wrong thing and its verdicts are noise."
    )


@pytest.mark.parametrize("path", ["files/anatomy/cortex/e2e/validate.spec.ts"])
def test_the_spec_the_gate_reads_is_the_spec_ci_runs(path: str) -> None:
    """Cheap guard on the file identity, so the gate cannot drift onto a copy.

    If the CI job's spec moves and this one stays, the gate would keep passing
    against a file nobody executes — which is the same "reachable from nowhere"
    failure the estate keeps rediscovering, wearing a test's clothes.
    """
    assert (REPO / path).is_file(), f"{path} is gone; re-point this gate"
    ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "cortex" in ci.lower(), (
        "the CI workflow no longer mentions cortex, so the job this gate exists "
        "to keep green may not run at all any more."
    )


def test_every_place_the_spec_writes_the_number_agrees() -> None:
    """Both literals, together — the defect that got past the first version.

    `health.contracts.cortex` and the opcode registry's `data.contract` are the
    same version published on two surfaces. Bumping one is how the CI job stayed
    red after a fix that looked complete.
    """
    declared = _declared()
    found = _asserted_all()
    assert all(v == declared for v in found), (
        f"the organ ships contract v{declared} and the spec asserts {found} "
        "across its two surfaces. They are the same number: `contracts.cortex` "
        "on /health and `contract` on the opcode registry. Bump both, in the "
        "vendored copy AND in KEAP's."
    )
