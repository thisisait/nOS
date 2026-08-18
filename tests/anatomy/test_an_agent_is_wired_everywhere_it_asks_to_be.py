"""An agent that asks for a Wing token must be given one, everywhere.

`docs/hidden_fees/16` filed the shape: a claude-CLI agent exists only as the
intersection of five declarations, none of which references the others, and
nothing validates the set. Miss one and every gate stays green — the failure
arrives at 02:00, deep inside `pulse-run-agent.sh`, as ONE symptom naming ONE
layer (`WING_API_TOKEN is not set`, a 401 on the first call) with no indication
that the cause is "the set is incomplete".

The entry offered two closes: one derived source, or one gate over the
intersection. This is the gate — the affordable half — and it exists because
the expensive half is not scheduled.

WHAT IT FOUND ON THE DAY IT WAS WRITTEN. `curator` declares
`WING_API_TOKEN: "{{ curator_wing_api_token }}"` in its pulse env, the secret is
templated and present in `default.credentials.yml`, and
`roles/pazny.wing/tasks/post.yml` mentions curator **zero times**. Its token row
was never provisioned, so the ceremony would 401 on its first Wing call. Four of
the five declarations were in place, which is exactly the condition this entry
describes as invisible.

THE DISCRIMINATOR IS THE AGENT'S OWN ENV, NOT A LIST KEPT HERE. Not every agent
needs a Wing token: `migration-author`, `upgrade-advisor` and
`upgrade-architect` run operator-driven and ask for none, so demanding one of
them would be noise — and a gate that cries about correct configurations is a
gate people route around. So the trigger is the agent DECLARING
`<name>_wing_api_token` in its own profile. An agent that does not ask is not
checked; an agent that asks is checked everywhere.

That also means this gate cannot be satisfied by editing the gate. Adding an
agent to some allow-list here would do nothing — the only way to make it pass is
to wire the agent, or to stop asking for the token.

WHAT IT DOES NOT COVER, stated because the entry's point is that partial
coverage reads as full: it checks the token half of the set (declaration →
secret template → credentials → provisioning). The Authentik client and the
pulse-catalog substitution are separate members, checked below at a coarser
grain; and no static check can prove the provisioned token is the one the
runner will actually read at 02:00.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILES = REPO / "files/anatomy/agents"
SECRETS_TPL = REPO / "templates/secrets.yml.j2"
CREDENTIALS = REPO / "default.credentials.yml"
WING_POST = REPO / "roles/pazny.wing/tasks/post.yml"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
CONFIG = REPO / "default.config.yml"


def _profiles() -> dict[str, str]:
    """`{agent name: flat pulse profile text}`.

    The flat `agents/<name>.yml` is the Pulse-facing declaration — the file
    `pulse-run-agent.sh` reads as `NOS_AGENT_PROFILE`. An agent without one is
    contract-only (`inspektor`) and has nothing to wire.
    """
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(PROFILES.glob("*.yml"))
    }


def _asks_for_a_wing_token(name: str, text: str) -> bool:
    return f"{name}_wing_api_token" in text


def test_the_sweep_sees_the_profiles():
    """Positive control — an empty sweep makes everything below vacuous."""
    profiles = _profiles()
    assert len(profiles) >= 8, (
        f"only {len(profiles)} flat agent profile(s) found under {PROFILES}; "
        "this gate reasons over them, so a short sweep proves nothing."
    )
    assert any(_asks_for_a_wing_token(n, t) for n, t in profiles.items()), (
        "no agent asks for a Wing token at all, so every check below is "
        "vacuous. If the token contract changed, rewrite this gate."
    )


def test_the_sites_this_gate_reads_exist():
    for path in (SECRETS_TPL, CREDENTIALS, WING_POST, CATALOG, CONFIG):
        assert path.is_file(), f"{path.relative_to(REPO)} is gone — a moved "
        "declaration site would make this gate pass by not looking"


def test_every_agent_that_asks_for_a_token_is_wired_for_one():
    secrets = SECRETS_TPL.read_text(encoding="utf-8")
    creds = CREDENTIALS.read_text(encoding="utf-8")
    post = WING_POST.read_text(encoding="utf-8")

    missing: dict[str, list[str]] = {}
    for name, text in _profiles().items():
        if not _asks_for_a_wing_token(name, text):
            continue
        var = f"{name}_wing_api_token"
        gaps = []
        if var not in secrets:
            gaps.append(f"templates/secrets.yml.j2 has no {var} (the runner "
                        "reads ~/.nos/secrets.yml, so the value never lands)")
        if var not in creds:
            gaps.append(f"default.credentials.yml does not define {var}")
        if not re.search(rf"--name={re.escape(name)}\b", post):
            gaps.append("roles/pazny.wing/tasks/post.yml provisions no token "
                        f"row for --name={name}, so Wing rejects it at request time")
        if gaps:
            missing[name] = gaps

    assert not missing, (
        "agent(s) ask for a Wing API token that is not wired end to end:\n"
        + "\n".join(f"  {n}:\n" + "\n".join(f"    - {g}" for g in gs)
                    for n, gs in sorted(missing.items()))
        + "\n\nThis is docs/hidden_fees/16: the agent exists only as the "
          "intersection of several declarations, and the missing one shows up "
          "at 02:00 as a 401 that names the symptom, not the cause."
    )


def test_every_profiled_agent_has_an_authentik_client():
    """The member of the set that fails EARLIEST and most confusingly — without
    a client the runner cannot mint a token at all, and Authentik answers
    `invalid_grant`, which reads as a bad secret rather than a missing client.
    """
    config = CONFIG.read_text(encoding="utf-8")
    start = config.index("authentik_agent_clients:")
    declared = set(re.findall(r'slug:\s*"nos-([a-z0-9-]+)"', config[start:start + 12000]))
    orphans = sorted(set(_profiles()) - declared)
    assert not orphans, (
        f"agent profile(s) with no entry in authentik_agent_clients: {orphans}. "
        "The runner will fail to mint a token and Authentik will say "
        "'invalid_grant', which reads as a wrong secret."
    )


def test_every_profiled_agent_is_known_to_the_pulse_catalog():
    """The catalog substitutes literally — no Jinja engine — so an agent it has
    never heard of gets its tokens passed through verbatim into the stored job
    (memory `pulse-catalog-literal-substitution`, paid twice already)."""
    catalog = CATALOG.read_text(encoding="utf-8")
    profiles = _profiles()
    unknown = sorted(
        name for name, text in profiles.items()
        if _asks_for_a_wing_token(name, text) and name not in catalog
    )
    assert not unknown, (
        f"agent(s) asking for a Wing token that discover-pulse-catalog.py never "
        f"names: {unknown}. Substitution is literal, so the token reaches the "
        "stored pulse job as the unrendered string."
    )
