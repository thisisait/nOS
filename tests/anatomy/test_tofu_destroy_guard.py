"""ADR-0001 — OpenTofu Authentik destroy/UPDATE guard gate.

The destroy guard in tasks/tofu-authentik.yml refuses any apply whose plan
deletes/replaces a resource. That `selectattr('change.actions','contains',
'delete')` catches DELETE and replace (delete+create) but NOT a pure in-place
UPDATE. An UPDATE to an Authentik *lookup key* — OAuth2Provider.client_id,
ProxyProvider.external_host, Application.slug — is silently catastrophic: the id
is baked into consumer env / OIDC discovery, so flipping it in place breaks SSO
with no resource destroyed (e.g. a registry slug edit changing client_id
nos-grafana -> nos-grafana-new).

Two layers, both offline:
  1. LOGIC — drive nos_tofu_immutable_field_updates with synthetic plan JSON and
     assert it flags dangerous UPDATEs while ignoring safe ones (non-denylisted
     field, CREATE, replace).
  2. WIRING — the task must compute the fact, refuse apply on a non-empty
     result, and gate the apply on it being empty (so dropping the guard from
     the task fails here too).
"""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
FILTER = REPO / "filter_plugins/nos_tofu_guard.py"
TASK = REPO / "tasks/tofu-authentik.yml"


def _load():
    spec = importlib.util.spec_from_file_location("nos_tofu_guard", FILTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rc(rtype, actions, before, after, address=None):
    return {
        "address": address or rtype,
        "type": rtype,
        "change": {"actions": actions, "before": before, "after": after},
    }


# ── Layer 1: detection logic ─────────────────────────────────────────────────

def test_flags_client_id_update():
    """The motivating case: a pure UPDATE flipping OAuth2Provider.client_id."""
    fn = _load().nos_tofu_immutable_field_updates
    plan = [_rc("authentik_provider_oauth2", ["update"],
                {"client_id": "nos-grafana"}, {"client_id": "nos-grafana-new"})]
    out = fn(plan)
    assert len(out) == 1
    assert out[0]["field"] == "client_id"
    assert out[0]["before"] == "nos-grafana"
    assert out[0]["after"] == "nos-grafana-new"


def test_flags_external_host_and_slug():
    fn = _load().nos_tofu_immutable_field_updates
    plan = [
        _rc("authentik_provider_proxy", ["update"],
            {"external_host": "https://a.dev.local"},
            {"external_host": "https://b.dev.local"}),
        _rc("authentik_application", ["update"],
            {"slug": "grafana"}, {"slug": "grafana-2"}),
    ]
    fields = {f["field"] for f in fn(plan)}
    assert fields == {"external_host", "slug"}


def test_ignores_non_denylisted_field_update():
    """An UPDATE to a field that is NOT a lookup key (e.g. name) is safe."""
    fn = _load().nos_tofu_immutable_field_updates
    plan = [_rc("authentik_provider_oauth2", ["update"],
                {"client_id": "nos-grafana", "name": "Grafana"},
                {"client_id": "nos-grafana", "name": "Grafana SSO"})]
    assert fn(plan) == []


def test_ignores_create_writing_field_first_time():
    """A CREATE writing client_id for the first time (before None) is not a
    mutation of a live reference."""
    fn = _load().nos_tofu_immutable_field_updates
    plan = [_rc("authentik_provider_oauth2", ["create"],
                None, {"client_id": "nos-new"})]
    assert fn(plan) == []
    # and a null before with an 'update' action is still treated as create-ish
    plan2 = [_rc("authentik_provider_oauth2", ["update"],
                 {"client_id": None}, {"client_id": "nos-new"})]
    assert fn(plan2) == []


def test_ignores_replace_handled_by_destroy_guard():
    """A replace is actions ['delete','create'] — the destroy guard catches it;
    the UPDATE guard must NOT (avoid double-counting / wrong message)."""
    fn = _load().nos_tofu_immutable_field_updates
    plan = [_rc("authentik_provider_oauth2", ["delete", "create"],
                {"client_id": "a"}, {"client_id": "b"})]
    assert fn(plan) == []


def test_empty_and_malformed_inputs_are_safe():
    fn = _load().nos_tofu_immutable_field_updates
    assert fn([]) == []
    assert fn(None) == []
    assert fn(["junk", {}, {"type": "authentik_provider_oauth2"}]) == []
    # before/after not dicts (known-after-apply whole object)
    assert fn([_rc("authentik_provider_oauth2", ["update"], None, None)]) == []


def test_summary_is_human_readable():
    fn = _load().nos_tofu_immutable_field_updates
    out = fn([_rc("authentik_application", ["update"],
                  {"slug": "x"}, {"slug": "y"})])
    assert out[0]["summary"] == "authentik_application.slug: x -> y"


def test_denylist_covers_every_module_lookup_key():
    """The denylist must name the three lookup keys the module creates. If the
    module gains a new immutable field, this nudges the author to add it."""
    mod = _load()
    dl = mod.IMMUTABLE_FIELDS
    assert dl["authentik_provider_oauth2"] == ["client_id"]
    assert dl["authentik_provider_proxy"] == ["external_host"]
    assert dl["authentik_application"] == ["slug"]


# ── Layer 2: task wiring ─────────────────────────────────────────────────────

def test_task_computes_and_enforces_the_update_guard():
    """The task must: compute _tofu_bad_updates from the plan via the filter,
    REFUSE apply when it is non-empty, and gate the apply task on it being
    empty. Dropping any of these regresses the guard and fails here."""
    body = TASK.read_text()
    assert "nos_tofu_immutable_field_updates" in body, \
        "task no longer computes the dangerous-update set via the filter"
    assert "_tofu_bad_updates" in body
    # a fail task gated on a non-empty result
    assert "_tofu_bad_updates | length > 0" in body, \
        "no REFUSE-apply guard on a non-empty dangerous-update set"
    # the apply task must additionally require zero dangerous updates
    assert "_tofu_bad_updates | length == 0" in body, \
        "apply is not gated on the dangerous-update set being empty"


def test_destroy_guard_diagnoses_which_resources_before_refusing():
    """The diagnostic must name the exact destroyed address(es) — not just a
    count — BEFORE the fail. Operators otherwise hand-parse the plan JSON to
    learn which service dropped out.

    RENAMED 2026-08-23: the fail is now "a destroy nobody declared", because
    the guard distinguishes a destroy the operator authorised (install_* off)
    from one nobody explained. See the tests below."""
    body = TASK.read_text()
    assert "map(attribute='address')" in body, \
        "destroy diagnostic does not list the destroyed resource address(es)"
    assert "tofu apply -parallelism=1 tfplan" in body, \
        "the supervised-apply one-liner is gone; it is the last resort and the "\
        "operator needs it spelled out when the guard genuinely refuses"
    diag = body.index("list resources the plan would destroy")
    refuse = body.index("REFUSE apply — a destroy nobody declared")
    assert diag < refuse, "destroy diagnostic must precede the REFUSE fail"


# ── The two causes the old guard could not tell apart (2026-08-23) ──────────
#
# The refusal message NAMED both causes and could act on neither:
#   (a) the tenant is only partially authored in HCL — a real defect;
#   (b) a service flipped enabled->false — a decision made in config.yml.
#
# (b) is derivable. A converge died on it: install_superset had been false for
# two days, with the reasoning written into config.yml, and the plan wanted to
# delete superset's Authentik application and OAuth2 provider — SSO objects
# that exist only to front a container this same playbook had already removed.
# Refusing there asks for one decision twice.

def test_a_destroy_explained_by_a_disabled_service_is_not_refused():
    mod = _load()
    registry = [{"slug": "superset", "enabled": "False"},
                {"slug": "grafana", "enabled": "True"}]
    changes = [_rc("authentik_application", ["delete"], {}, {},
                   address='module.service["superset"].authentik_application.this')]
    out = mod.nos_tofu_destroy_split(changes, registry)
    assert len(out["declared_off"]) == 1
    assert out["unexplained"] == [], (
        "a destroy whose service the operator turned off is authorised by that "
        "flag — the same flag already stopped the container")


def test_the_filter_fails_closed_on_everything_it_cannot_attribute():
    """Three ways to be unexplained, and all three must refuse. This is the
    load-bearing half: the relaxation above is only safe because nothing it
    cannot account for slips through with it."""
    mod = _load()
    registry = [{"slug": "grafana", "enabled": "True"}]
    cases = {
        "enabled service": 'module.service["grafana"].authentik_application.this',
        "not in registry": 'module.service["ghost"].authentik_application.this',
        "not a service module": "authentik_outpost.embedded",
    }
    for label, address in cases.items():
        out = mod.nos_tofu_destroy_split(
            [_rc("authentik_application", ["delete"], {}, {}, address=address)], registry)
        assert out["declared_off"] == [], f"{label} must not be authorised"
        assert len(out["unexplained"]) == 1, f"{label} must refuse"
        assert out["unexplained"][0]["why"], f"{label} refuses without saying why"


def test_a_replace_counts_as_a_destroy():
    """A replace is delete+create. superset's provider planned exactly that."""
    mod = _load()
    out = mod.nos_tofu_destroy_split(
        [_rc("authentik_provider_oauth2", ["delete", "create"], {}, {},
             address='module.service["superset"].authentik_provider_oauth2.this[0]')],
        [{"slug": "superset", "enabled": "false"}])
    assert len(out["declared_off"]) == 1


def test_refuse_and_apply_gate_on_the_same_predicate():
    """If the fail and the apply disagree, the run either applies what was
    refused or refuses what would have applied. Both must read `unexplained`,
    and neither may still read the raw destroy count."""
    body = TASK.read_text()
    assert "_tofu_destroy_split.unexplained | length > 0" in body, \
        "the refusal no longer fires on unexplained destroys"
    assert "_tofu_destroy_split.unexplained | length == 0" in body, \
        "the apply is not gated on the same predicate as the refusal"
    apply_when = body[body.index("tofu apply (engine=tofu"):]
    assert "_tofu_destroys | int == 0" not in apply_when.split("- name:")[0], (
        "the apply still gates on the raw destroy count, so an authorised "
        "removal would be planned, reported, and then silently skipped")


def test_filter_is_discoverable_by_ansible():
    """ansible.cfg must point at filter_plugins/ so the play resolves the
    custom filter (it auto-discovers ./filter_plugins, but the explicit pin
    documents intent and survives a cwd change)."""
    cfg = (REPO / "ansible.cfg").read_text()
    assert "filter_plugins = ./filter_plugins" in cfg
    # and the FilterModule actually exports the name the task calls
    mod = _load()
    assert "nos_tofu_immutable_field_updates" in mod.FilterModule().filters()


def test_an_unloadable_registry_names_itself_instead_of_refusing_everything():
    """The first LIVE run of the split got an EMPTY registry — the var is
    task-scoped and the call site had `| default([])` — so all four "unknown
    slug" branches fired and every destroy read *"not in the registry —
    un-authored"*. That is a fact about the guard's wiring being reported as a
    fact about the plan, and it refuses hardest of all the verdicts.

    Absence of the input must name ITSELF."""
    mod = _load()
    changes = [_rc("authentik_application", ["delete"], {}, {},
                   address='module.service["superset"].authentik_application.this')]
    for empty in ([], None, "not-a-list"):
        out = mod.nos_tofu_destroy_split(changes, empty)
        assert out["declared_off"] == []
        assert len(out["unexplained"]) == 1, f"registry={empty!r} lost the destroy"
        why = out["unexplained"][0]["why"]
        assert "registry did not load" in why and "WIRING" in why, (
            f"registry={empty!r} blames the plan for the guard's own wiring: {why}")


def test_a_populated_registry_does_not_take_the_unloadable_branch():
    """Proven in the other direction, because a branch that swallowed every
    input would pass the test above and break the whole guard."""
    mod = _load()
    out = mod.nos_tofu_destroy_split(
        [_rc("authentik_application", ["delete"], {}, {},
             address='module.service["superset"].authentik_application.this')],
        [{"slug": "superset", "enabled": "False"}])
    assert len(out["declared_off"]) == 1 and out["unexplained"] == []
