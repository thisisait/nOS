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


class FilterModule(object):
    def filters(self):
        return {
            "nos_tofu_immutable_field_updates": nos_tofu_immutable_field_updates,
        }
