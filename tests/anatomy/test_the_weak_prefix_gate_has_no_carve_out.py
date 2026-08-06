"""The weak-prefix assert must be reachable on every tenant.

WHAT THE PREFIX IS. `global_password_prefix` is not one secret. 88 credentials
derive from it at runtime — DB roots, admin passwords, the prefix-derived OIDC
and agent client secrets, and the backup encryption key, which keys an archive
containing `~/.nos/secrets.yml`. The repository ships it as the literal
`changeme` (default.config.yml), the operator override lives in the gitignored
`credentials.yml`, and so A FRESH CLONE'S EFFECTIVE PREFIX IS `changeme`.

WHAT WENT WRONG. The guard that refuses a weak prefix carried
`when: not (tenant_domain_is_local | default(true) | bool)` — lenient for local
development, on the reasoning that a local install is not exposed. REM-144
disproved that reasoning on this very estate: an unauthenticated Traefik API
served the prefix from a *local* install, and `tenant_domain_is_local` defaults
to TRUE, so the lenient branch was the default branch.

The carve-out was dropped 2026-08-02 (`4e958788`). Nothing pinned it, and the
comment directly above the task still described the removed behaviour four days
later. This file is what makes the removal durable, because a carve-out is the
kind of thing that comes back as a one-line convenience during a demo.

WHAT IS DELIBERATELY *NOT* ASSERTED: that the shipped default stops being
`changeme`. An obvious sentinel that fails the run closed is better than a
generated default that silently works — the operator is told, once, in a
message naming the blast radius. The exposure is closed by the refusal, not by
the value.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
CONFIG = REPO / "default.config.yml"

def _find_task(node):
    """The assert that refuses a weak prefix, found by WHAT IT ASSERTS.

    Deliberately not by name. The task was called "[Security] Refuse a weak
    password prefix **on a public tenant**" while it carried the carve-out, and
    was renamed when the carve-out went. A name-keyed gate run against that old
    file reports "the task is gone" — it goes red, but for the wrong reason,
    and it would go equally red on a harmless rename while saying nothing about
    the condition that actually matters.

    The play is nested (tasks / block / rescue), so this recurses rather than
    scanning one list and reporting 'absent' from the wrong depth.
    """
    if isinstance(node, dict):
        assertion = node.get("ansible.builtin.assert") or node.get("assert")
        if isinstance(assertion, dict):
            that = assertion.get("that") or []
            joined = " ".join(str(t) for t in (that if isinstance(that, list) else [that]))
            if "global_password_prefix" in joined:
                return node
        for value in node.values():
            found = _find_task(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_task(item)
            if found is not None:
                return found
    return None


def _guard() -> dict:
    doc = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
    task = _find_task(doc)
    assert task is not None, (
        "main.yml contains no assert over global_password_prefix. The estate "
        "derives 88 credentials from that value, including the backup key — "
        "nothing refuses a weak one."
    )
    return task


def _when_terms(task: dict) -> list[str]:
    when = task.get("when")
    if when is None:
        return []
    return [str(w) for w in (when if isinstance(when, list) else [when])]


def test_the_guard_is_not_gated_on_tenant_locality():
    terms = " ".join(_when_terms(_guard()))
    assert "tenant_domain_is_local" not in terms, (
        "the weak-prefix assert is gated on tenant locality again. "
        "tenant_domain_is_local defaults to TRUE, so this is not an edge case — "
        "it is the default path, and REM-144 showed a local install serving the "
        "prefix to an unauthenticated caller."
    )


def test_the_only_way_past_is_an_explicit_bypass():
    """A bypass an operator types is a decision. A condition that resolves
    true on its own is a default nobody chose."""
    terms = _when_terms(_guard())
    assert terms, "the guard has no `when:` at all — check it still runs"
    assert len(terms) == 1, (
        f"the weak-prefix assert has {len(terms)} conditions: {terms}. Every "
        f"extra one is another way for it not to run."
    )
    assert "allow_weak_prefix" in terms[0], (
        f"the guard's only condition is {terms[0]!r}, which is not the explicit "
        f"operator bypass"
    )


def test_the_guard_survives_a_tag_filtered_run():
    """`--tags <anything>` must not skip it. A security assert that only fires
    on a full converge is absent from every partial one."""
    tags = _guard().get("tags") or []
    assert "always" in tags, (
        f"the weak-prefix assert carries tags {tags} — without 'always' a run "
        f"like `--tags stacks` provisions the estate without ever checking the "
        f"prefix those services derive their passwords from"
    )


def test_it_refuses_both_the_shipped_sentinel_and_a_short_prefix():
    """Two distinct failures: the committed default, and anything guessable."""
    that = _guard()["ansible.builtin.assert"]["that"]
    joined = " ".join(str(t) for t in that)
    assert "changeme" in joined, "the guard no longer names the shipped default"
    assert "length" in joined and ">= 12" in joined, (
        "the guard no longer imposes a minimum length, so 'abc' passes"
    )


def test_the_shipped_default_is_still_the_sentinel_the_guard_names():
    """If the default were changed without updating the assert, the guard would
    pass on a value the repository still publishes to the world."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    shipped = config.get("global_password_prefix")
    that = " ".join(str(t) for t in _guard()["ansible.builtin.assert"]["that"])
    assert shipped in that, (
        f"default.config.yml ships global_password_prefix={shipped!r} and the "
        f"assert does not name it. A committed prefix that the guard does not "
        f"refuse is a shipped credential."
    )
