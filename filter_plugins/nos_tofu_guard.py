# nOS — OpenTofu Authentik destroy/update guard helper.
#
# The destroy guard in tasks/tofu-authentik.yml refuses any plan that DELETEs
# or REPLACEs a resource. That catches delete + delete-then-create (replace),
# but NOT a pure in-place UPDATE. An UPDATE to an Authentik *lookup key* —
# OAuth2Provider.client_id, ProxyProvider.external_host, Application.slug — is
# silently catastrophic: the id is baked into consumer env / OIDC discovery, so
# flipping it in place breaks SSO with no resource ever destroyed (e.g. a
# registry slug edit that changes `client_id: nos-grafana -> nos-grafana-new`).
#
# This filter parses `tofu show -json tfplan`'s resource_changes list and
# returns the list of dangerous in-place field changes. Empty list = safe.
# Pure Python (Jinja2 has no nested list comprehension) keeps the detection
# testable and out of fragile inline templating.

from __future__ import annotations

# Per-resource-type immutable-by-contract fields. Mirrors modules/
# nos-authentik-app/main.tf — keep in sync if the module gains a new lookup key.
IMMUTABLE_FIELDS = {
    "authentik_provider_oauth2": ["client_id"],
    "authentik_provider_proxy": ["external_host"],
    "authentik_application": ["slug"],
}


def nos_tofu_immutable_field_updates(resource_changes, denylist=None):
    """Return [{address,type,field,before,after,summary}, ...] for every pure
    UPDATE that mutates an immutable lookup field.

    A change counts only when:
      - its actions list is exactly ['update'] (a replace is ['delete',
        'create'] and is handled by the destroy guard, not here);
      - the before value is concrete (not None / known-after-apply) AND
        differs from after — a None before is a CREATE writing the field for
        the first time, not a mutation of a live reference.
    """
    fields_for = denylist if denylist is not None else IMMUTABLE_FIELDS
    if not isinstance(resource_changes, list):
        return []

    findings = []
    for rc in resource_changes:
        if not isinstance(rc, dict):
            continue
        rtype = rc.get("type")
        watched = fields_for.get(rtype)
        if not watched:
            continue
        change = rc.get("change") or {}
        if list(change.get("actions") or []) != ["update"]:
            continue
        before = change.get("before") or {}
        after = change.get("after") or {}
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        for field in watched:
            b = before.get(field)
            a = after.get(field)
            if b is None:
                continue  # CREATE writing the field, not a mutation
            if b != a:
                findings.append({
                    "address": rc.get("address", rtype),
                    "type": rtype,
                    "field": field,
                    "before": b,
                    "after": a,
                    "summary": "{}.{}: {} -> {}".format(rtype, field, b, a),
                })
    return findings


# ── Which destroys did the operator already authorise? ──────────────────────
#
# WHY THIS EXISTS (2026-08-23). The destroy guard refuses ANY delete/replace,
# and its own failure message names two causes it cannot tell apart:
#
#   (a) the tenant is only partially authored in HCL — a real defect;
#   (b) a service flipped enabled->false and dropped out of the registry
#       filter — a decision the operator already made, in config.yml.
#
# (b) is fully derivable and was being handed to a human every time. On
# 2026-08-23 a converge died on exactly this: `install_superset: false` had
# been set two days earlier, with the reasoning written into config.yml, and
# the plan wanted to delete superset's Authentik application and OAuth2
# provider. The estate had already stopped and removed the container on the
# same authority (prune_disabled_overrides). Refusing to remove the SSO
# objects that exist only to front it asks for the same consent twice.
#
# That is the rule CLAUDE.md already states for the compose prune: an opt-in
# flag that authorises removing a service's fragment also authorises stopping
# the container that fragment described — same decision, not a further one.
#
# WHAT IS STILL REFUSED, and this is the load-bearing half: a destroy whose
# service is NOT in the registry at all, or whose `enabled` resolves TRUE, is
# unexplained and still fails the run. Fail-closed on anything unrecognised —
# an address this parser cannot read is unexplained, never authorised.

import re

#: `module.service["superset"].authentik_application.this` -> superset
_SERVICE_KEY = re.compile(r'module\.service\["([^"]+)"\]')

#: Ansible renders the registry through lookup('template'), so `enabled`
#: arrives already resolved — but as a STRING ("False"), not a bool.
_FALSE = {"false", "no", "off", "0", "none", ""}


def _is_off(value):
    if isinstance(value, bool):
        return not value
    return str(value).strip().lower() in _FALSE


def nos_tofu_destroy_split(resource_changes, registry):
    """Split planned destroys into ones a disabled service explains, and the rest.

    Returns {"declared_off": [...], "unexplained": [...]}, each a list of
    {address, service, why}.
    """
    enabled_by_slug = {}
    if isinstance(registry, list):
        for svc in registry:
            if isinstance(svc, dict) and svc.get("slug") is not None:
                enabled_by_slug[str(svc["slug"])] = svc.get("enabled")

    declared_off, unexplained = [], []
    if not isinstance(resource_changes, list):
        return {"declared_off": [], "unexplained": []}

    for rc in resource_changes:
        if not isinstance(rc, dict):
            continue
        actions = (rc.get("change") or {}).get("actions") or []
        if "delete" not in actions:
            continue
        address = rc.get("address", "?")
        match = _SERVICE_KEY.search(address)
        if not match:
            unexplained.append({
                "address": address, "service": None,
                "why": "address does not name a service module — cannot be attributed",
            })
            continue
        slug = match.group(1)
        if slug not in enabled_by_slug:
            unexplained.append({
                "address": address, "service": slug,
                "why": "no `{}` in the registry — un-authored, not disabled".format(slug),
            })
        elif _is_off(enabled_by_slug[slug]):
            declared_off.append({
                "address": address, "service": slug,
                "why": "install flag for `{}` resolves off".format(slug),
            })
        else:
            unexplained.append({
                "address": address, "service": slug,
                "why": "`{}` is ENABLED — a destroy here is not explained by any flag".format(slug),
            })
    return {"declared_off": declared_off, "unexplained": unexplained}


class FilterModule(object):
    def filters(self):
        return {
            "nos_tofu_immutable_field_updates": nos_tofu_immutable_field_updates,
            "nos_tofu_destroy_split": nos_tofu_destroy_split,
        }
