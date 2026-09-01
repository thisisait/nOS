"""Compose-prune destroy guard — retro-verified against the 2026-09-01 incident.

WHAT HAPPENED. A converge run as

    ansible-playbook main.yml --tags preflight -e @tests/config.yml

deleted 36 compose fragments and force-removed 33 running containers on the
live estate, and reported `changed=3` — Ansible counts TASKS, not loop items,
so 71 destructive item results collapsed into a number an operator reads as
"nothing much happened". `--tags preflight` confined nothing because every task
in the compose-up flow carries `always` (CLAUDE.md, A17), and extra-vars outrank
config.yml, so a CI config file silently reclassified 36 ENABLED services as
disabled.

TWO DEFECTS, one gate each below.

  1. NO ATTRIBUTION. The OpenTofu path already refuses this exact shape
     (`nos_tofu_destroy_split`): a destroy whose install flag resolves off
     applies; one that is un-authored refuses and says which. The compose path
     had no equivalent — any source of a `false` was obeyed, permanently.

  2. BLAST RADIUS. Containers were chosen by UNANCHORED substring of the
     disabled-service alternation against `docker ps`. `install_observability:
     false` is a STACK flag with no compose fragment: it pruned nothing and
     still matched all nine `observability-*` containers by substring. Nine
     containers destroyed by a token that removed zero fragments.

RETRO-VERIFICATION. `test_the_incident_inputs_are_refused` and
`test_a_stack_flag_that_prunes_nothing_destroys_nothing` both drive the real
recorded inputs from that run. `test_old_substring_selection_was_the_bug`
reconstructs the PRE-FIX selection and asserts it destroyed the nine — so this
file fails against the broken state rather than merely describing it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
FILTER = REPO / "filter_plugins/nos_prune_guard.py"
TASK = REPO / "tasks/stacks/prune-disabled.yml"


def _load():
    spec = importlib.util.spec_from_file_location("nos_prune_guard", FILTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── The recorded incident, from ~/.nos/ansible.log p=67684 2026-09-01 08:24 ──

#: The nine containers the substring match destroyed via `install_observability`.
OBSERVABILITY_CONTAINERS = [
    "observability-grafana-1",
    "observability-prometheus-1",
    "observability-loki-1",
    "observability-tempo-1",
    "observability-influxdb-1",
    "observability-postgres-exporter-1",
    "observability-mysqld-exporter-1",
    "observability-redis-exporter-1",
    "observability-blackbox-exporter-1",
]

#: Real fragment -> compose service keys, as the estate renders them.
OVERRIDES = {
    "/stacks/infra/overrides/authentik.yml": ["authentik-server", "authentik-worker"],
    "/stacks/infra/overrides/portainer.yml": ["portainer"],
    "/stacks/infra/overrides/traefik.yml": ["traefik"],
    "/stacks/observability/overrides/grafana.yml": [
        "grafana",
        "postgres-exporter",
        "mysqld-exporter",
        "redis-exporter",
        "blackbox-exporter",
    ],
    "/stacks/iiab/overrides/mailpit.yml": ["mailpit"],
    "/stacks/iiab/overrides/uptime-kuma.yml": ["uptime-kuma"],
}

CONTAINERS = OBSERVABILITY_CONTAINERS + [
    "infra-authentik-server-1",
    "infra-authentik-worker-1",
    "infra-portainer-1",
    "infra-traefik-1",
    "iiab-mailpit-1",
    "iiab-uptime-kuma-1",
]


# ── 1. Attribution: the incident must be refused ────────────────────────────


def test_the_incident_inputs_are_refused():
    """`-e @tests/config.yml` disables services the estate's config enables."""
    plan = _load().nos_prune_plan(
        disabled=["authentik", "portainer", "traefik", "infisical"],
        # The estate's OWN config.yml has these ON. Only the extra-vars file
        # said otherwise, and only for the duration of one command.
        on_disk_flags={
            "install_authentik": True,
            "install_portainer": True,
            "install_traefik": True,
            "install_infisical": True,
        },
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["unauthored"] == ["authentik", "infisical", "portainer", "traefik"]
    # A caller that forgets to check the refusal must still destroy nothing.
    assert plan["fragments"] == []
    assert plan["containers"] == []


def test_an_authored_disablement_still_prunes():
    """The guard must not make a legitimate `install_x: false` impossible.

    The operator's standing declaration in config.yml is real and stays a
    one-flag operation — mailpit is the genuine case measured 2026-08-10.
    """
    plan = _load().nos_prune_plan(
        disabled=["mailpit"],
        on_disk_flags={"install_mailpit": False},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["unauthored"] == []
    assert plan["fragments"] == ["/stacks/iiab/overrides/mailpit.yml"]
    assert plan["containers"] == ["iiab-mailpit-1"]


def test_one_unauthored_service_refuses_the_whole_prune():
    """A mixed batch is not partially applied — the run stops and names it."""
    plan = _load().nos_prune_plan(
        disabled=["mailpit", "authentik"],
        on_disk_flags={"install_mailpit": False, "install_authentik": True},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["unauthored"] == ["authentik"]
    assert plan["fragments"] == [] and plan["containers"] == []


def test_a_jinja_valued_flag_neither_prunes_nor_blocks():
    """`install_acme: "{{ not tenant_domain_is_local }}"` cannot be attributed
    from the config text. Refusing on it would block every converge; pruning on
    it would destroy on a guess. It is excluded from both."""
    plan = _load().nos_prune_plan(
        disabled=["acme", "mailpit"],
        on_disk_flags={
            "install_acme": "{{ not tenant_domain_is_local }}",
            "install_mailpit": False,
        },
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["indeterminate"] == ["acme"]
    assert plan["unauthored"] == []
    assert plan["fragments"] == ["/stacks/iiab/overrides/mailpit.yml"]


def test_a_flag_absent_from_disk_is_unauthored():
    """Absent is not a declaration either — it is the extra-vars case again."""
    plan = _load().nos_prune_plan(
        disabled=["something_nobody_declared"],
        on_disk_flags={},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["unauthored"] == ["something_nobody_declared"]


# ── 2. Blast radius: a token that prunes nothing destroys nothing ───────────


def test_a_stack_flag_that_prunes_nothing_destroys_nothing():
    """`install_observability` is a STACK flag: no `observability.yml` fragment
    exists, so the prune touches nothing — and therefore must remove no
    container. This is the exact input that cost nine containers."""
    plan = _load().nos_prune_plan(
        disabled=["observability"],
        # Authored, so we are past the refusal and testing selection alone.
        on_disk_flags={"install_observability": False},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["unauthored"] == []
    assert plan["fragments"] == []
    assert plan["containers"] == [], (
        "a disabled-service token matching no fragment removed containers — "
        "this is the 2026-09-01 observability blast radius"
    )


def test_old_substring_selection_was_the_bug():
    """Retro-verification: the PRE-FIX selection destroyed the nine.

    Without this the gate above would pass on code that never had the defect,
    and would not prove the fix fixed anything.
    """
    disabled = ["observability"]
    alternation = "(" + "|".join(d.replace("_", "[-_]?") for d in disabled) + ")"
    old_victims = [c for c in CONTAINERS if re.search(alternation, c)]
    assert sorted(old_victims) == sorted(OBSERVABILITY_CONTAINERS)

    new = _load().nos_prune_plan(
        disabled=disabled,
        on_disk_flags={"install_observability": False},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert new["containers"] == []


def test_selection_is_exact_not_substring():
    """`kuma` must not reach `uptime-kuma`; a fragment's own services must."""
    mod = _load()
    plan = mod.nos_prune_plan(
        disabled=["uptime_kuma"],
        on_disk_flags={"install_uptime_kuma": False},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    # Separator-insensitive fragment match still works (uptime_kuma ->
    # uptime-kuma.yml) ...
    assert plan["fragments"] == ["/stacks/iiab/overrides/uptime-kuma.yml"]
    # ... and container selection is anchored, so nothing else is caught.
    assert plan["containers"] == ["iiab-uptime-kuma-1"]


def test_grafana_fragment_owns_its_exporters():
    """Selection follows the fragment's `services:` keys, so pruning grafana
    correctly takes the four exporters it declares — and only those."""
    plan = _load().nos_prune_plan(
        disabled=["grafana"],
        on_disk_flags={"install_grafana": False},
        overrides=OVERRIDES,
        containers=CONTAINERS,
    )
    assert plan["containers"] == sorted(OBSERVABILITY_CONTAINERS[:1] + OBSERVABILITY_CONTAINERS[5:])
    assert "observability-prometheus-1" not in plan["containers"]


# ── 3. Wiring: the task must actually use the guard ─────────────────────────


def test_the_task_refuses_and_uses_the_plan():
    body = TASK.read_text()
    assert "nos_prune_plan" in body, "task no longer computes the attributed plan"
    assert "ansible.builtin.fail" in body, "the refusal was removed"
    assert "_prune_plan.unauthored" in body, "the refusal no longer reads the plan"
    # The destructive tasks must consume the plan, not re-derive a selection.
    for consumed in ("_prune_plan.fragments", "_prune_plan.containers"):
        assert consumed in body, f"a destructive task stopped using {consumed}"


def test_the_substring_selection_does_not_come_back():
    """The literal shape that caused the incident: selecting containers by
    `select('search', ...)` over the disabled-service alternation."""
    body = TASK.read_text()
    assert "_running_after_prune" not in body, (
        "the unanchored substring survivor-selection is back"
    )
    assert "_disabled_fragments" not in body, (
        "the pre-guard fragment list is back; fragments must come from the "
        "attributed plan so they cannot be acted on when the prune is refused"
    )
