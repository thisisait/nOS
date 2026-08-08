"""One character, one definition. Two runtimes may render it; neither owns it.

WHAT WAS FOUND, 2026-08-08, auditing OpenClaw/Hermes overlap.

"Inspektor Klepitko" existed twice:

    ~/.openclaw/workspace/SOUL.md   280 lines, copied from a STATIC file
    ~/.hermes/SOUL.md                93 lines, rendered from a role template

They differed in content, and both had drifted from the estate — in different
directions, which is what two copies of one law always produce:

  * the static one taught nginx as the HTTPS proxy and `*.dev.local` hostnames.
    `install_nginx` has been `false` since Traefik became primary (C1), and this
    tenant runs its own TLD. A static file cannot know either, which is exactly
    why it drifted furthest.
  * the templated one still pointed at `~/projects/mac-dev-playbook` and told
    the agent to run `nginx -t` before deploying.

An agent persona is not decoration: it is what the model believes about the
machine it is acting on. Two divergent beliefs, both wrong, is worse than one.

WHAT THIS PINS. A single rendered source, `templates/personas/klepitko.md.j2`,
with per-runtime branches. Every estate fact comes from a variable, so the
persona cannot drift from the estate without the estate changing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PERSONA = REPO / "templates/personas/klepitko.md.j2"
ROLES = {
    "pazny.hermes": "hermes",
    "pazny.openclaw": "openclaw",
}


def persona_tasks() -> dict[str, dict]:
    """The SOUL.md-deploying task in each role, by role name."""
    out: dict[str, dict] = {}
    for role in ROLES:
        doc = yaml.safe_load((REPO / "roles" / role / "tasks/main.yml").read_text())
        for task in doc or []:
            mod = task.get("ansible.builtin.template") or task.get("ansible.builtin.copy") or {}
            if str(mod.get("dest", "")).endswith("SOUL.md"):
                out[role] = task
                break
    return out


def test_both_runtimes_render_the_same_source():
    tasks = persona_tasks()
    missing = sorted(set(ROLES) - set(tasks))
    assert not missing, f"no SOUL.md deploy task found in: {missing}"

    srcs = set()
    for role, task in tasks.items():
        assert "ansible.builtin.template" in task, (
            f"{role} deploys its persona with `copy:`, not `template:`. A static "
            "persona cannot know tenant_domain, install_nginx or playbook_dir — "
            "which is how the OpenClaw copy came to teach nginx and *.dev.local "
            "years after the estate stopped using either."
        )
        srcs.add(task["ansible.builtin.template"]["src"])
    assert len(srcs) == 1, (
        f"the two runtimes render different persona sources: {sorted(srcs)}. "
        "One character, one definition — otherwise they drift apart, which is "
        "measured fact and not a worry."
    )
    assert srcs == {"personas/klepitko.md.j2"}, f"unexpected persona source: {srcs}"


def test_each_render_declares_its_runtime():
    """The shared template branches on it; an unset value renders neither block."""
    for role, expected in ROLES.items():
        task = persona_tasks()[role]
        got = (task.get("vars") or {}).get("persona_runtime")
        assert got == expected, (
            f"{role} renders the shared persona with persona_runtime={got!r}, "
            f"expected {expected!r}. Unset, the template emits no runtime block "
            "at all and the agent is told nothing about what it is."
        )


def test_the_template_carries_no_estate_fact_as_a_literal():
    """Anything hard-coded here is a fact that can go stale silently."""
    src = PERSONA.read_text(encoding="utf-8")
    body = re.sub(r"\{#.*?#\}", "", src, flags=re.S)  # the header explains the defect
    for literal, why in [
        ("dev.local", "hostnames come from tenant_domain"),
        ("mac-dev-playbook", "the repo path comes from playbook_dir"),
        ("nginx -t", "host nginx is opt-in and off by default"),
    ]:
        assert literal not in body, (
            f"the persona hard-codes {literal!r} — {why}. That is precisely how "
            "the two previous copies drifted."
        )
    for var in ("tenant_domain", "playbook_dir", "persona_runtime"):
        assert var in body, f"the persona no longer reads {{{{ {var} }}}}"


def test_the_superseded_sources_are_gone():
    """A leftover copy gets edited by someone who cannot see the other."""
    for stale in ("roles/pazny.hermes/templates/SOUL.md.j2", "files/openclaw/SOUL.md"):
        assert not (REPO / stale).exists(), (
            f"{stale} still exists beside the unified persona. Two files, one "
            "character — the state this gate was written to end."
        )
