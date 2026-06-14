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
    """When the destroy guard is about to refuse (engine=tofu, destroys>0), the
    task must surface a diagnostic that names the exact destroyed resource
    address(es) — not just a count — plus the paste-able supervised recovery
    one-liner, BEFORE the fail. Operators flipping install_*=false otherwise
    have to hand-parse the plan JSON to learn which service drops out."""
    body = TASK.read_text()
    # the diagnostic maps the deleting changes to their addresses
    assert "map(attribute='address')" in body, \
        "destroy diagnostic does not list the destroyed resource address(es)"
    # paste-able supervised recovery command
    assert "tofu apply -parallelism=1 tfplan" in body, \
        "destroy diagnostic does not offer the supervised-apply one-liner"
    # the diagnostic must run BEFORE the REFUSE-apply fail (ordering matters:
    # a debug after the fail never prints)
    diag = body.index("list resources the plan would destroy")
    refuse = body.index("REFUSE apply — plan would destroy resources")
    assert diag < refuse, "destroy diagnostic must precede the REFUSE fail"
    # and it is gated on the same condition as the fail it precedes
    assert body.count("_tofu_destroys | int > 0") >= 2, \
        "destroy diagnostic not gated on engine=tofu AND destroys>0"


def test_filter_is_discoverable_by_ansible():
    """ansible.cfg must point at filter_plugins/ so the play resolves the
    custom filter (it auto-discovers ./filter_plugins, but the explicit pin
    documents intent and survives a cwd change)."""
    cfg = (REPO / "ansible.cfg").read_text()
    assert "filter_plugins = ./filter_plugins" in cfg
    # and the FilterModule actually exports the name the task calls
    mod = _load()
    assert "nos_tofu_immutable_field_updates" in mod.FilterModule().filters()
