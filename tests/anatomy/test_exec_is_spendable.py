"""An agent holding `exec` must hold a token the executor will accept.

MEASURED 2026-09-01, by the adversarial reviewer of the build that shipped the
tool. `ExecTool` was written, registered, schema-declared and gated — and every
call it could ever make would have returned 403, for every agent, on day one.

The reason is a seam no single file can see. `CortexExecutorPresenter::startup`
refuses any token missing ANY of the three cortex axes (verbs, namespaces,
tenants), deliberately: "a token that is powerful elsewhere is not a way in."
The tool presents `NOS_AGENT_WING_TOKEN`, which `tools/run-agent.sh` resolves
per agent from `~/.nos/secrets.yml`, which the playbook mints in
roles/pazny.wing/tasks/post.yml. Exactly one token in that file carried cortex
axes, and it belonged to no agent — `cortex-executor` is a service principal.

So three declarations had to agree and nothing compared them:

    agent.yml `tools:`        who may call it
    post.yml  `--cortex-*`    whose token the route will accept
    the tool's requiredScopes what the registry admits

This gate compares the first two, statically, in both directions. It cannot
prove the live row (that is `test_the_mint_matches_the_manifest.py`'s job and
needs a converged host) — what it CAN prove is that nobody was handed a tool
with no door, and that nobody minted a cortex grant for an agent that cannot
spend it. Both directions matter: the first is a capability that silently does
nothing, the second is a standing grant nobody is using.

NOT A STYLE CHECK. A gate asserting the tool "should" have a token would be
prose. This asserts the two sets are EQUAL, so either half moving alone fails.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
POST = REPO / "roles/pazny.wing/tasks/post.yml"
CREDENTIALS = REPO / "default.credentials.yml"

TOOL_ID = "exec"
AXES = ("--cortex-verbs=", "--cortex-namespaces=", "--cortex-tenants=")


def _agents_holding(tool_id: str) -> set[str]:
    holders = set()
    for manifest in sorted(AGENTS.glob("*/agent.yml")):
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        ids = {t.get("id") for t in (doc.get("tools") or []) if isinstance(t, dict)}
        if tool_id in ids:
            holders.add(doc.get("name") or manifest.parent.name)
    return holders


def _minted_with_all_three_axes() -> dict[str, set[str]]:
    """`--name=X` blocks that set all three cortex columns.

    Partial grants are collected too, because `CortexCapability::fromToken`
    treats a half-written grant as NO grant — a mint carrying verbs and no
    namespaces reads, at a glance, like a working door.
    """
    src = POST.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"--name=([a-z][a-z0-9-]*)(.*?)(?=\n\s*- name:|\Z)", src, re.S):
        present = {a for a in AXES if a in m.group(2)}
        if present:
            out[m.group(1)] = present
    return out


def test_the_sweep_sees_both_sides() -> None:
    """Positive control — an empty read on either side makes the rest vacuous."""
    assert _agents_holding("mcp-wing-read"), "no agent declares any tool; the parse is broken"
    assert _minted_with_all_three_axes(), (
        f"no --cortex-* mint found in {POST.name}; the flag has been renamed and "
        "this gate is measuring nothing"
    )


def test_every_cortex_mint_is_complete() -> None:
    """A partial grant is not a weaker door, it is no door — and it reads like one."""
    partial = {n: sorted(a) for n, a in _minted_with_all_three_axes().items() if len(a) != 3}
    assert not partial, (
        f"these tokens set some cortex axes and not all three: {partial}. "
        "CortexCapability::fromToken returns null unless verbs, namespaces AND "
        "tenants are all granted, so the route refuses them exactly as it would "
        "a token with nothing — while the task looks like it opened something."
    )


def test_the_agents_holding_exec_are_the_agents_minted_a_cortex_token() -> None:
    holders = _agents_holding(TOOL_ID)
    # `cortex-executor` is a service principal with no agent.yml — the token the
    # HTTP surface was tested with, never carried by a running agent. It is
    # excluded by name, and the exclusion is written here rather than inferred,
    # so a future agent called `cortex-executor` cannot slip through it.
    minted = set(_minted_with_all_three_axes()) - {"cortex-executor"}
    assert holders == minted, (
        f"agents holding `{TOOL_ID}`: {sorted(holders)}; agents minted a complete "
        f"cortex token: {sorted(minted)}. A holder with no token "
        f"({sorted(holders - minted)}) gets 403 on every call and reads the "
        f"refusal as an estate fact. A mint with no holder ({sorted(minted - holders)}) "
        "is a standing grant nobody spends."
    )


def test_each_minted_token_has_a_secret_to_be() -> None:
    """The mint interpolates a variable; the variable has to exist.

    `--token={{ jeff_wing_api_token }}` renders empty if nothing declares it,
    and provision-token.php would then write an empty-string bearer that
    authenticates nothing — an absence arriving as a value.
    """
    # Split into ansible tasks: `--token=` sits ABOVE `--name=` in the argv, so
    # a window anchored on the name misses it.
    tasks = re.split(r"\n(?=- name:)", POST.read_text(encoding="utf-8"))
    declared = CREDENTIALS.read_text(encoding="utf-8")
    for name in _minted_with_all_three_axes():
        block = next((t for t in tasks if f"--name={name}\n" in t), None)
        assert block is not None, f"no single task block mints {name}"
        token = re.search(r"--token=\{\{\s*([a-z0-9_]+)\s*\}\}", block)
        assert token is not None, f"the {name} mint does not interpolate a token variable"
        assert re.search(rf"^{token.group(1)}:", declared, re.M), (
            f"{token.group(1)} is minted for {name} but declared nowhere in "
            f"{CREDENTIALS.name} — it renders empty, and an empty bearer is not "
            "a refused one, it is an unauthenticated one."
        )
