"""The infra stack is enabled by one list and rendered by another. They must agree.

WHAT HAPPENED. `tasks/stacks/core-up.yml` decides two things from two separately
written expressions:

  * `_core_infra_enabled` — whether to bring the infra stack up (and health-wait
    on it),
  * the `when:` on the task that renders `stacks/infra/docker-compose.yml`.

Both were correct the day they were written. Neither had any way to stay correct
with the other. `install_bone` entered the first in 3eace4a9, when track-a ran
Bone as a compose service, and stayed after anatomy A3a returned Bone to host
launchd — so an estate with `install_bone: true` and the rest of infra off
skipped the render and then ran `docker compose up -f` against a file nobody had
written. rc=1, no MariaDB, no PostgreSQL, no Authentik, no Traefik — and the
health probe called it `0/0 ready (no containers — stack empty)`.

That is `docs/hidden_fees/08` reproduced by CONFIGURATION, on any platform,
with no Linux render bug involved. It was found on 2026-08-27 by an agent
reading the two expressions side by side, four weeks after the fee documented
the same shape arriving from the other direction.

WHY IT BECAME URGENT rather than merely untidy: the bring-up assert added the
same morning (`[Core] Infra bring-up failed — stop the run`) reads that rc. A
disagreement that used to cost a silent lie now stops the run.

WHAT IS PINNED. The two service sets are equal. Nothing here says which services
belong in infra — that is the operator's design and it moves. It says only that
one file may not hold two answers to it.

WHAT IT CANNOT SEE. Whether either list is RIGHT: a service missing from both
is invisible here, and so is a service whose compose fragment renders into the
stack by another path. This gate catches divergence, not error.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CORE_UP = REPO / "tasks/stacks/core-up.yml"

#: Every toggle spelling that can appear in either expression. `redis_docker`
#: is the one that is not an `install_*`, which is why this is a pattern and
#: not a prefix test.
TOGGLE = re.compile(r"\b(install_[a-z0-9_]+|redis_docker)\b")


def _tasks() -> list[dict]:
    return [t for t in yaml.safe_load(CORE_UP.read_text(encoding="utf-8")) or []
            if isinstance(t, dict)]


def _module(task: dict, name: str):
    """A task's module args under either spelling.

    This tree mixes `set_fact:` and `ansible.builtin.set_fact:` — ansible-lint's
    `fqcn` rule is in the skip list, so both are legal and both occur. Keying on
    one spelling is how a gate goes quietly vacuous: the first cut of this file
    looked only for the bare name, found nothing, and its own error message
    ("if the gate moved, follow it") is what stopped it being read as a pass.
    """
    return task.get(name) or task.get(f"ansible.builtin.{name}")


def _enabled_expression() -> str:
    """The `_core_infra_enabled` fact, as authored."""
    for task in _tasks():
        fact = _module(task, "set_fact")
        if isinstance(fact, dict) and "_core_infra_enabled" in fact:
            return str(fact["_core_infra_enabled"])
    raise AssertionError(
        "no set_fact defines _core_infra_enabled in tasks/stacks/core-up.yml — "
        "if the gate moved, this gate must follow it, not be deleted")


def _render_condition() -> str:
    """The `when:` guarding the infra compose render."""
    for task in _tasks():
        tmpl = _module(task, "template")
        if isinstance(tmpl, dict) and "infra/docker-compose.yml.j2" in str(tmpl.get("src", "")):
            when = task.get("when")
            assert when is not None, (
                "the infra compose render is now UNCONDITIONAL. That is a "
                "legitimate design, but then _core_infra_enabled is the only "
                "gate left and this comparison is meaningless — delete this "
                "gate deliberately rather than letting it pass vacuously")
            return " ".join(when) if isinstance(when, list) else str(when)
    raise AssertionError("no template task renders stacks/infra/docker-compose.yml.j2")


def test_the_two_expressions_name_the_same_services():
    """The whole gate. Two spellings of one truth, forced to agree."""
    enabled = set(TOGGLE.findall(_enabled_expression()))
    renders = set(TOGGLE.findall(_render_condition()))

    only_enabled = sorted(enabled - renders)
    only_renders = sorted(renders - enabled)

    assert not only_enabled, (
        f"{only_enabled} turn(s) the infra stack ON but do NOT cause its compose "
        "file to be rendered. An estate with only those toggles set runs "
        "`docker compose up -f` against a file that was never written: rc=1, an "
        "empty stack, and — before the bring-up assert — a probe calling it "
        "'0/0 ready'. Either add them to the render's `when:`, or (if the "
        "service renders no container at all, as Bone has since anatomy A3a) "
        "remove them from _core_infra_enabled.")

    assert not only_renders, (
        f"{only_renders} cause the infra compose file to be RENDERED but do not "
        "turn the stack on, so the render is dead work and the service never "
        "starts. Add them to _core_infra_enabled or drop them from the `when:`.")


def test_bone_is_not_among_them():
    """The specific regression, named.

    A set-equality gate would go green if someone added `install_bone` to BOTH
    expressions — symmetric, and still wrong, because Bone renders no container
    (`roles/pazny.bone/templates/` holds only bone.plist.j2). Equality is the
    invariant; this is the one member the artifact can rule on by itself.
    """
    bone_templates = REPO / "roles/pazny.bone/templates"
    compose = sorted(p.name for p in bone_templates.glob("*compose*"))
    if compose:
        pytest.skip(f"Bone renders compose again ({compose}) — it may legitimately "
                    "be an infra member; this assertion no longer applies")

    for name, expr in (("_core_infra_enabled", _enabled_expression()),
                       ("the infra render when:", _render_condition())):
        assert "install_bone" not in expr, (
            f"install_bone is back in {name}, but Bone renders no container — "
            f"{bone_templates.relative_to(REPO)} holds only a launchd plist. It "
            "cannot make the infra stack non-empty, so listing it can only "
            "produce a stack that is enabled and empty. It sat in "
            "_core_infra_enabled from 3eace4a9 (when Bone WAS a compose "
            "service) until 2026-08-27.")
