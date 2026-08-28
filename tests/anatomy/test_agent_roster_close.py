"""The 2026-08-26 agent-roster close stays closed.

THE MEASUREMENT (fable review wf_72000040-d16, verified against wing.db
events before acting): five agent profiles had never emitted one event in
the DB epoch — scout, remediator, upgrade-advisor, curator, migration-author
— while each carried a directory profile, a second loose .yml with a
divergent prompt, a ~200-line launcher, an Authentik client, two secrets, a
pulse_jobs row and membership in ~31 gates. Two spellings of one truth is
the defect class that produced the cAdvisor scrape and the dialectOptions
bug; a roster asserted by gates that nothing ever runs is worse.

The operator's ruling, pinned here:

  RETIRED  — scout, remediator, upgrade-advisor: every spelling deleted
             (git history keeps them). upgrade-ARCHITECT is a different,
             live agent and must NOT be swept up by a confusion of names.
  PARKED   — curator, migration-author (joining inspektor): AgentKit dir
             contract only, honest metadata.runner_status, no loose .yml,
             no launcher — the profile itself says it is parked.

Resurrecting any retired spelling, or re-growing a parked agent's launcher
apparatus without flipping runner_status, reopens the dual-declaration
defect this close removed — that is the regression this file refuses.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
TOOLS = REPO / "tools"

RETIRED = ("scout", "remediator", "upgrade-advisor")
PARKED = ("inspektor", "curator", "migration-author")
PARKED_STATUSES = {"parked", "deferred"}  # inspektor predates the close


def test_the_premise_agents_exist_at_all():
    """Positive control — if the agents tree moved, absence below would be
    vacuous. The live roster's anchor profiles must be present."""
    assert (AGENTS / "conductor/agent.yml").is_file()
    assert (AGENTS / "surveyor" / "agent.yml").is_file()


def test_retired_agents_left_no_spelling_behind():
    for name in RETIRED:
        assert not (AGENTS / name).exists(), (
            f"files/anatomy/agents/{name}/ reappeared — {name} was retired "
            "2026-08-26; git history keeps the profile, the tree must not"
        )
        assert not (AGENTS / f"{name}.yml").exists(), (
            f"files/anatomy/agents/{name}.yml reappeared — the loose profile "
            f"was the second spelling of {name}, deleted with the retirement"
        )
        assert not (TOOLS / f"run-{name}.sh").exists(), (
            f"tools/run-{name}.sh reappeared — the launcher died with {name}"
        )


def test_retired_agents_left_the_authentik_registry():
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text())
    slugs = {c.get("slug") for c in (cfg.get("authentik_agent_clients") or [])}
    for name in RETIRED:
        assert f"nos-{name}" not in slugs, (
            f"authentik_agent_clients declares nos-{name} again — the client "
            "was removed 2026-08-26; the converge deletes it from the realm"
        )
    # The confusion guard: the ADVISOR went, the ARCHITECT stays.
    assert "nos-upgrade-architect" in slugs, (
        "nos-upgrade-architect vanished from authentik_agent_clients — the "
        "roster close retired the upgrade-ADVISOR only; the architect is live"
    )


def test_retired_secrets_left_every_store_spelling():
    registry = (REPO / "files/anatomy/secrets/registry.yml").read_text()
    template = (REPO / "templates/secrets.yml.j2").read_text()
    creds = (REPO / "default.credentials.yml").read_text()
    catalog = (
        REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
    ).read_text()
    gone = (
        "agent_scout", "agent_remediator", "agent_upgrade_advisor",
        "wing_scout", "wing_remediator", "wing_upgrade_advisor",
        "scout_wing_api_token", "remediator_wing_api_token",
        "upgrade_advisor_wing_api_token",
        # parked agents keep their reserved OIDC client secret but lose the
        # Wing bearer with the launcher apparatus:
        "wing_curator", "wing_migration_author",
        "curator_wing_api_token", "migration_author_wing_api_token",
    )
    for key in gone:
        for label, body in (
            ("files/anatomy/secrets/registry.yml", registry),
            ("templates/secrets.yml.j2", template),
            ("default.credentials.yml", creds),
            ("discover-pulse-catalog.py", catalog),
        ):
            assert f"{key}:" not in body and f"{key} }}" not in body, (
                f"{label} declares {key} again — removed in the 2026-08-26 "
                "roster close; a re-add re-derives an orphan the estate "
                "stopped consuming"
            )


def test_parked_agents_are_contract_only_and_say_so():
    for name in PARKED:
        d = AGENTS / name
        assert (d / "agent.yml").is_file(), (
            f"{name} is PARKED, not retired — the AgentKit dir profile must "
            "stay (the epic that un-parks it builds on the contract)"
        )
        assert not (AGENTS / f"{name}.yml").exists(), (
            f"files/anatomy/agents/{name}.yml reappeared — a parked agent has "
            "ONE spelling (the dir profile); un-parking re-declares deliberately"
        )
        assert not (TOOLS / f"run-{name}.sh").exists(), (
            f"tools/run-{name}.sh exists while {name} is parked — either "
            "un-park (flip runner_status, re-declare the apparatus) or drop it"
        )
        meta = (
            yaml.safe_load((d / "agent.yml").read_text()).get("metadata") or {}
        )
        assert meta.get("runner_status") in PARKED_STATUSES, (
            f"{name}/agent.yml metadata.runner_status is "
            f"{meta.get('runner_status')!r} — a parked agent must say so in "
            "its own file (inspektor pattern); if it is live again, its "
            "launcher and pulse apparatus must exist too"
        )
        # A plan_ref must RESOLVE, not just be non-empty (defect class
        # 9b2a9201): found live 2026-08-26 — migration-author's park pointed
        # at a plan doc that had already moved to docs/archive/.
        plan_ref = meta.get("plan_ref")
        if plan_ref:
            assert (REPO / plan_ref).is_file(), (
                f"{name}/agent.yml metadata.plan_ref points at {plan_ref}, "
                "which does not exist in this tree — a parked agent's "
                "un-parking epic must be a file a reader can open"
            )


def test_wing_post_provisions_no_retired_or_parked_bearer():
    src = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    for name in RETIRED + ("curator", "migration-author"):
        assert f"--name={name}\n" not in src.replace("\r", ""), (
            f"wing post.yml provisions a Wing bearer for {name} again — "
            "removed 2026-08-26 (the live api_tokens row is the operator's "
            "to deactivate; the playbook must stop re-asserting it)"
        )
    assert "--name=upgrade-architect" in src, (
        "the upgrade-architect bearer task vanished — the roster close must "
        "not touch the live architect"
    )
