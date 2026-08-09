"""Anatomy gate: the vendored cortex must declare the same contract as KEAP's.

`files/anatomy/cortex/server/` is a VENDORED PORT of KEAP's cortex half
(`f6c15a9a`, "vendor the KEAP cortex port"). Two copies of a contract with
nothing comparing them is a fork with a delay on it.

MEASURED 2026-08-10, which is why this exists: adding the `agent:` namespace and
the `delegate` opcode to KEAP left the nOS copy on contract v1 — two registries,
two namespace enums, two opcode lists, and every test still green on both sides,
because each suite only ever asked its own copy. The organ would have refused a
sentence KEAP had just accepted, and the first evidence would have been a
production `unknown_opcode` against a verb the validator published.

WHAT IS COMPARED, AND WHY NOT THE BYTES. Only the DECLARATIONS: the contract
version, the namespace enum, the policy table, the published scope, and the
opcode list with its arity, params, mutating flag and `since`. Prose may
legitimately differ — the two repos cite different doc paths, and a gate that
demanded byte-identity would be failed by a corrected comment, which teaches
people to skip it. What may never differ is what the two programs DO.

WHAT THIS CANNOT COVER. That the two implementations behave the same given the
same declarations — only that they are asked to. The behavioural half is each
side's own vitest suite, and this gate deliberately does not restate it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
VENDORED = REPO / "files/anatomy/cortex/server/cortex-opcodes.ts"
# The upstream working copy, when it is checked out beside nOS. Absent on CI and
# on a fresh clone, so the comparison SKIPS rather than fails — a gate that goes
# red because a sibling directory is missing gets disabled, and then it is gone
# for the case it was written for.
UPSTREAM = REPO.parent / "knowledge-explorer-and-preserver/server/cortex-opcodes.ts"


def _declarations(source: str) -> dict[str, object]:
    """Pull the contract out of the module text.

    Regex rather than a TS parse on purpose: this file must not acquire a
    node/tsc dependency to answer a question about two string literals, and the
    shapes below are frozen `as const` literals whose formatting is fixed by the
    repo's prettier config.
    """
    out: dict[str, object] = {}

    version = re.search(r"CORTEX_CONTRACT_VERSION\s*=\s*(\d+)", source)
    out["contract_version"] = int(version.group(1)) if version else None

    namespaces = re.search(r"CORTEX_NAMESPACES\s*=\s*\[(.*?)\]\s*as const", source, re.S)
    out["namespaces"] = (
        tuple(re.findall(r"'([a-z]+)'", namespaces.group(1))) if namespaces else None
    )

    policy = re.search(r"NAMESPACE_POLICY[^=]*=\s*\{(.*?)\n\};", source, re.S)
    out["policy"] = (
        tuple(sorted(re.findall(r"^\s*([a-z]+):\s*'(\w+)'", policy.group(1), re.M)))
        if policy
        else None
    )

    scope = re.search(r"CORTEX_SCOPE\s*=\s*\{(.*?)\}\s*as const", source, re.S)
    out["scope"] = (
        tuple(re.findall(r"(\w+):\s*(\[[^\]]*\]|'[^']*'|true|false)", scope.group(1)))
        if scope
        else None
    )

    # Shared param bundles (`MUTATION_PARAMS`, `GATE_PARAMS`) must be resolved
    # before an opcode's params can be read: most mutating verbs write
    # `params: MUTATION_PARAMS`, and an extractor that only understood inline
    # literals would report them as declaring NO gate flags. The gate's own
    # first run said exactly that about `link` — a false accusation from a blind
    # extractor, which is the failure mode this file warns about two paragraphs
    # up, arriving immediately.
    bundles: dict[str, tuple] = {}
    for bundle in re.finditer(r"const (\w+_PARAMS)\s*=\s*\{(.*?)\}\s*as const", source, re.S):
        bundles[bundle.group(1)] = tuple(
            sorted(re.findall(r"(\w+):\s*\{\s*type:\s*'([\w-]+)'", bundle.group(2)))
        )

    def params_of(body: str) -> tuple:
        block = re.search(r"params:\s*(\{.*?\}|\w+),\s*\n", body, re.S)
        if not block:
            return ()
        text = block.group(1)
        found: list[tuple[str, str]] = []
        # A bare reference (`params: GATE_PARAMS`) or a spread inside a literal
        # (`params: { ...GATE_PARAMS, via: … }`) both pull the bundle in.
        for name in re.findall(r"\.{3}(\w+_PARAMS)|^(\w+_PARAMS)$", text, re.M):
            key = name[0] or name[1]
            found.extend(bundles.get(key, ()))
        found.extend(re.findall(r"(\w+):\s*\{\s*type:\s*'([\w-]+)'", text))
        return tuple(sorted(set(found)))

    # One tuple per opcode: everything a caller can observe about what it accepts.
    opcodes: list[tuple] = []
    for block in re.finditer(
        r"\{\s*(?://[^\n]*\n\s*|/\*.*?\*/\s*)*name:\s*'([a-z-]+)',.*?since:\s*(\d+),\s*\}",
        source,
        re.S,
    ):
        body = block.group(0)
        operands = re.search(
            r"operands:\s*\{\s*min:\s*(\d+),\s*max:\s*(\d+),\s*namespaces:\s*\[([^\]]*)\]",
            body,
        )
        mutating = re.search(r"mutating:\s*(true|false)", body)
        opcodes.append((
            block.group(1),
            int(operands.group(1)) if operands else None,
            int(operands.group(2)) if operands else None,
            tuple(re.findall(r"'([a-z]+)'", operands.group(3))) if operands else None,
            mutating.group(1) if mutating else None,
            int(block.group(2)),
            # param NAMES and TYPES; the `default:` values are documentary (D8:
            # never injected), so they are not part of what the two must agree on.
            params_of(body),
        ))
    out["opcodes"] = tuple(opcodes)
    return out


@pytest.fixture(scope="module")
def vendored() -> dict[str, object]:
    return _declarations(VENDORED.read_text(encoding="utf-8"))


def test_the_extractor_actually_found_something(vendored) -> None:
    """Guard the guard: a regex that matches nothing agrees with everything."""
    assert vendored["contract_version"] and vendored["contract_version"] >= 1
    assert vendored["namespaces"] and len(vendored["namespaces"]) >= 7
    assert vendored["policy"] and len(vendored["policy"]) == len(vendored["namespaces"]), (
        "every namespace must carry a policy; the extractor found "
        f"{len(vendored['policy'] or ())} for {len(vendored['namespaces'] or ())} namespaces"
    )
    assert vendored["opcodes"] and len(vendored["opcodes"]) >= 14, (
        f"only {len(vendored['opcodes'] or ())} opcodes parsed out — the registry "
        "literal's shape changed and this gate has gone blind rather than green"
    )


def test_every_namespace_the_opcodes_use_is_declared(vendored) -> None:
    """Local soundness, checkable without upstream — so CI gets it too."""
    declared = set(vendored["namespaces"] or ())
    for name, _min, _max, namespaces, *_ in vendored["opcodes"]:  # type: ignore[misc]
        unknown = set(namespaces or ()) - declared
        assert not unknown, f"opcode `{name}` accepts undeclared namespace(s): {sorted(unknown)}"


def test_a_mutating_opcode_declares_its_gate_flags(vendored) -> None:
    """Wing refuses mutating stages at the door; the flags are how it reports why."""
    for name, *_rest in vendored["opcodes"]:  # type: ignore[misc]
        *_, mutating, _since, params = _rest
        if mutating != "true":
            continue
        types = dict(params)
        assert types.get("dry_run") == "bool" and types.get("commit") == "bool", (
            f"mutating opcode `{name}` does not declare both gate flags as bool"
        )


@pytest.mark.skipif(not UPSTREAM.exists(), reason="KEAP is not checked out beside nOS")
def test_the_two_registries_declare_the_same_contract(vendored) -> None:
    upstream = _declarations(UPSTREAM.read_text(encoding="utf-8"))

    drifted = [k for k in vendored if vendored[k] != upstream[k]]
    if not drifted:
        return

    lines: list[str] = []
    for key in drifted:
        if key != "opcodes":
            lines.append(f"  {key}:\n    nOS:  {vendored[key]}\n    KEAP: {upstream[key]}")
            continue
        # Name the opcodes that differ rather than printing two long tuples.
        ours = {o[0]: o for o in vendored["opcodes"]}  # type: ignore[index]
        theirs = {o[0]: o for o in upstream["opcodes"]}  # type: ignore[index]
        for name in sorted(set(ours) | set(theirs)):
            if ours.get(name) != theirs.get(name):
                lines.append(f"  opcode `{name}`:\n    nOS:  {ours.get(name)}\n    KEAP: {theirs.get(name)}")

    raise AssertionError(
        "the vendored cortex registry and KEAP's have drifted. The organ would "
        "accept or refuse sentences the validator does not, and each side's own "
        "suite stays green throughout because neither asks the other.\n"
        "Re-vendor from KEAP (the source of truth for this contract), then re-run "
        "both suites:\n" + "\n".join(lines)
    )
