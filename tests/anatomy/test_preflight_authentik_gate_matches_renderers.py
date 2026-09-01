"""Anatomy gate — the Authentik preflight's set IS the renderers' set.

WHAT IT PINS. `main.yml`'s `[Preflight] Find enabled services that need an
Authentik to gate them` computes the services that would answer 500 when
`install_authentik: false` leaves `authentik@file` undefined. Two other places
decide that for real:

  * `roles/pazny.traefik/templates/dynamic/services.yml.j2` — Tier-1 routers.
  * `files/anatomy/library/nos_apps_render.py:209` — Tier-2 Docker labels.

A preflight that computes the answer a *second* way is a guess. This renders
BOTH artifacts with the same Ansible that main.yml uses, collects every router
that actually receives `authentik@file`, and asserts equality with the fact.

WHY IT EXISTS — the first cut of that predicate was wrong on 15 of 17 services.
It read `traefik_auth_modes` and `traefik_skip_ids`, which are pazny.traefik
ROLE vars, from `pre_tasks`, where the role has not run and they do not exist.
`| default({})` swallowed the absence, `.get(id, 'proxy')` then reported EVERY
enabled service as gated: 14 false positives (authentik, portainer, grafana,
gitea, nextcloud, n8n, open-webui, outline, superset, vaultwarden, rustfs,
bone, cortex, traefik) and one false negative — `traefik-dashboard`, emitted
unconditionally at services.yml.j2:120-127 and therefore invisible to any
predicate written from the manifest loop. Reading the source could not have
caught that; only executing it did.

WHAT IT CANNOT COVER. The estate's own `config.yml` is deliberately NOT loaded
(it is gitignored and per-host). This runs against `default.config.yml`, so it
proves the two computations agree on the committed default — the drift it is
built to catch is structural, not per-host. A `@docker`-provider label that
attaches `authentik@file` from a role compose template (one exists,
pazny.smtp_stalwart) is likewise out of scope: it is not a Tier-1 router and
the preflight never claimed it.

CI-safe: `hosts: localhost, connection: local`, only `set_fact` and a pure
render module. It cannot reach the estate. Skips where ansible-playbook is
absent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
FACT_TASK = "[Preflight] Find enabled services that need an Authentik to gate them"

# The probe must sit at the repo root: the predicate under test builds its paths
# from `playbook_dir`, and anywhere else would silently exercise a different one.
PROBE = """---
- hosts: localhost
  connection: local
  gather_facts: false
  vars_files: [default.config.yml]
  tasks:
    - ansible.builtin.set_fact: {ANSIBLE_FACT}
    - ansible.builtin.include_vars:
        file: "{{{{ playbook_dir }}}}/roles/pazny.traefik/vars/main.yml"
    - ansible.builtin.set_fact:
        nos_manifest: "{{{{ lookup('file', playbook_dir ~ '/state/manifest.yml') | from_yaml }}}}"
    - ansible.builtin.set_fact:
        _t1: "{{{{ lookup('template', playbook_dir ~ '/roles/pazny.traefik/templates/dynamic/services.yml.j2') }}}}"
    - nos_apps_render:
        apps_dir: "{{{{ playbook_dir }}}}/apps"
        tenant_domain: "{{{{ tenant_domain }}}}"
      register: _t2
    - ansible.builtin.copy:
        dest: "{out}"
        content: >-
          {{{{ {{'preflight': _nos_gated_without_authentik,
                'tier1': _t1,
                'tier2': _t2.apps | map(attribute='id') | zip(_t2.apps | map(attribute='traefik_labels')) | list}}
             | to_json }}}}
"""


def _fact_expression() -> str:
    """The set_fact body, lifted verbatim out of main.yml.

    Lifted rather than copied so this gate cannot pass against a predicate that
    has since been edited.
    """
    for play in yaml.safe_load(MAIN.read_text()):
        for task in play.get("pre_tasks", []) + play.get("tasks", []):
            if task.get("name") == FACT_TASK:
                return task["ansible.builtin.set_fact"]["_nos_gated_without_authentik"]
    raise AssertionError(f"main.yml no longer defines a task named {FACT_TASK!r}")


def _render(expression: str) -> dict:
    probe = REPO / f".preflight-gate-{uuid.uuid4().hex[:8]}.yml"
    out = Path(os.environ.get("TMPDIR", "/tmp")) / f"{probe.stem}.json"
    fact = json.dumps({"_nos_gated_without_authentik": expression})
    probe.write_text(PROBE.format(ANSIBLE_FACT=fact, out=out))
    try:
        # inventory:4 pins ansible_python_interpreter=/opt/homebrew/bin/python3
        # — correct on the operator's Mac, absent on the Linux pytest runner,
        # where every module fails "interpreter not found". Extra-vars outrank
        # an inventory host var, so this is what makes the probe portable.
        run = subprocess.run(
            ["ansible-playbook", probe.name,
             "-e", f"ansible_python_interpreter={sys.executable}"],
            cwd=REPO, capture_output=True, text=True, timeout=300,
            env={**os.environ, "ANSIBLE_PYTHON_INTERPRETER": sys.executable},
        )
        assert run.returncode == 0, f"probe failed:\n{run.stdout}\n{run.stderr}"
        return json.loads(out.read_text())
    finally:
        probe.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


def _rendered_gated(payload: dict) -> set[str]:
    routers = (yaml.safe_load(payload["tier1"])["http"]["routers"]) or {}
    gated = {
        name for name, r in routers.items()
        if "authentik@file" in ((r or {}).get("middlewares") or [])
    }
    gated |= {
        f"app:{app_id}" for app_id, labels in payload["tier2"]
        if any("authentik@file" in label for label in labels)
    }
    return gated


@pytest.fixture(scope="module")
def payload() -> dict:
    if shutil.which("ansible-playbook") is None:
        pytest.skip("ansible-playbook unavailable in this lane")
    return _render(_fact_expression())


def test_preflight_set_equals_what_the_renderers_gate(payload):
    preflight = set(payload["preflight"])
    rendered = _rendered_gated(payload)
    assert preflight == rendered, (
        "the Authentik preflight disagrees with the artifacts Traefik is handed.\n"
        f"  refuses but is NOT gated: {sorted(preflight - rendered)}\n"
        f"  is gated but NOT refused: {sorted(rendered - preflight)}"
    )


def test_the_comparison_is_capable_of_failing():
    """The manifest-loop predicate this replaced must still be observed WRONG.

    Without this, a preflight that silently degraded to `[]` would satisfy the
    equality above the moment the renderers also produced nothing.
    """
    if shutil.which("ansible-playbook") is None:
        pytest.skip("ansible-playbook unavailable in this lane")
    superseded = (
        "{%- set ns = namespace(need=[]) -%}"
        "{%- set _man = lookup('file', playbook_dir ~ '/state/manifest.yml') | from_yaml -%}"
        "{%- for s in _man.services | default([]) -%}"
        "{%- if s.domain_var is defined and (s.port_var is defined or s.id == 'wing')"
        "       and s.id not in (traefik_skip_ids | default([]))"
        "       and (lookup('vars', s.install_flag, default=false) | bool)"
        "       and (traefik_auth_modes | default({})).get(s.id, 'proxy') == 'proxy' -%}"
        "{%- set ns.need = ns.need + [s.id] -%}"
        "{%- endif -%}{%- endfor -%}{{ ns.need }}"
    )
    payload = _render(superseded)
    assert set(payload["preflight"]) != _rendered_gated(payload), (
        "the superseded manifest-loop predicate now AGREES with the renderers — "
        "either the role vars became play-scoped or this gate stopped rendering."
    )


def test_the_dashboard_exemption_is_the_only_one(payload):
    """What is refused may differ from what is gated by exactly one named id.

    services.yml.j2:120-127 emits `traefik-dashboard` with `authentik@file`
    unconditionally, so refusing on it would refuse every legitimate
    Authentik-free estate. Any OTHER subtraction is a hole.
    """
    play = yaml.safe_load(MAIN.read_text())[0]
    tasks = play.get("pre_tasks", []) + play.get("tasks", [])
    refusable = next(
        t["ansible.builtin.set_fact"]["_nos_gated_without_authentik_refusable"]
        for t in tasks
        if "_nos_gated_without_authentik_refusable" in t.get("ansible.builtin.set_fact", {})
    )
    assert "difference(['traefik-dashboard'])" in refusable.replace('"', "'"), (
        "the refusal no longer subtracts exactly traefik-dashboard — a wider "
        "exemption silently stops refusing services that WILL 500"
    )
    assert "traefik-dashboard" in _rendered_gated(payload), (
        "traefik-dashboard is no longer gated, so the exemption is now dead "
        "code hiding whatever takes its place"
    )
