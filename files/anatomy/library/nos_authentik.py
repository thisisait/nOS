#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026, pazny (nOS)
# Spec: docs/framework-plan.md section 4.3

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: nos_authentik
short_description: Idempotent helper for Authentik identity operations used by nOS migrations.
version_added: "1.0.0"
description:
  - Thin wrapper over the Authentik REST API v3 (tested against 2026.1.x).
  - All actions are idempotent: re-running on an already-migrated system returns
    C(changed=false).
  - Used directly from playbooks, and indirectly by C(nos_migrate) via the
    C(authentik.*) action dispatch table.
options:
  action:
    description: Which operation to perform.
    required: true
    type: str
    choices:
      - list_groups
      - get_group
      - rename_group
      - rename_group_prefix
      - create_group
      - delete_group
      - list_oidc_clients
      - rename_oidc_client
      - rename_oidc_client_prefix
      - migrate_members
      - wait_api_reachable
  # --- connection ---
  authentik_api_url:
    description: Explicit base URL for the Authentik API (overrides port/domain).
    type: str
  authentik_port:
    description: Loopback port when the API lives on 127.0.0.1.
    type: int
  authentik_domain:
    description: Public domain when going through the nginx reverse proxy.
    type: str
  authentik_api_token:
    description: Bearer token override. Falls back to ~/.nos/secrets.yml -> env var.
    type: str
    no_log: true
  secrets_path:
    description: Path to the secrets file holding C(authentik_bootstrap_token).
    type: str
    default: "~/.nos/secrets.yml"
  verify_tls:
    description: Set to false to skip TLS verification (useful with dev.local).
    type: bool
    default: true
  timeout:
    description: Per-request timeout in seconds.
    type: int
    default: 15
  retries:
    description: Number of HTTP attempts before failing.
    type: int
    default: 3
  # --- action-specific ---
  name:
    description: Group or application/provider name, depending on action.
    type: str
  from_name:
    description: Source name for a rename action.
    type: str
  to_name:
    description: Destination name for a rename action.
    type: str
  from_prefix:
    description: Source prefix for C(rename_group_prefix) / C(rename_oidc_client_prefix).
    type: str
  to_prefix:
    description: Destination prefix for the prefix-rename actions.
    type: str
  from_group:
    description: Source group name for C(migrate_members).
    type: str
  to_group:
    description: Destination group name for C(migrate_members).
    type: str
  attributes:
    description: Free-form attributes dict for C(create_group).
    type: dict
  timeout_sec:
    description: Total reachability budget for C(wait_api_reachable).
    type: int
    default: 30
  poll_interval:
    description: Poll interval (seconds) for C(wait_api_reachable).
    type: float
    default: 1.0
  preserve_members:
    description: No-op flag kept for compatibility; Authentik preserves members on name change (PK unchanged).
    type: bool
    default: true
  preserve_policies:
    description: Asserts policy bindings remain attached after rename — verified, not acted upon.
    type: bool
    default: true
author:
  - pazny (@pazny)
"""

EXAMPLES = r"""
- name: Verify Authentik is reachable before a migration
  nos_authentik:
    action: wait_api_reachable
    authentik_port: 9003
    timeout_sec: 30

- name: Rename every group matching the legacy prefix
  nos_authentik:
    action: rename_group_prefix
    from_prefix: "devboxnos-"
    to_prefix: "nos-"
    authentik_port: 9003

- name: Rename one OIDC client (Application + Provider pair)
  nos_authentik:
    action: rename_oidc_client
    from_name: "devboxnos-grafana"
    to_name: "nos-grafana"
    authentik_domain: "auth.dev.local"
"""

RETURN = r"""
changed:
  description: Whether the action modified Authentik state.
  returned: always
  type: bool
renamed:
  description: Number of entities renamed (prefix actions only).
  returned: when action is rename_*_prefix
  type: int
groups:
  description: Groups touched (for list/rename_prefix).
  returned: sometimes
  type: list
  elements: dict
reachable:
  description: Whether the API responded within the timeout (C(wait_api_reachable) only).
  returned: when action == wait_api_reachable
  type: bool
"""


import os
import sys
import traceback

from ansible.module_utils.basic import AnsibleModule

# Resolve the module_utils import.  When run by Ansible the playbook-root
# ``module_utils`` directory is on sys.path automatically.  When the module
# file is executed directly (e.g. unit tests), fall back to the project root.
try:
    from ansible.module_utils.nos_authentik_client import (  # type: ignore[import]
        AuthentikApiError,
        NosAuthentikClient,
        resolve_endpoint,
        resolve_token,
    )
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from module_utils.nos_authentik_client import (  # type: ignore[no-redef]
        AuthentikApiError,
        NosAuthentikClient,
        resolve_endpoint,
        resolve_token,
    )


# ---------------------------------------------------------------------------
# Idempotent high-level operations.  These are also the entry points called
# by the ``authentik_proxy`` action handlers inside ``nos_migrate``.
# ---------------------------------------------------------------------------


def op_list_groups(client, search=None):
    groups = client.list_groups(search=search)
    return {"changed": False, "groups": groups}


def op_get_group(client, name):
    g = client.get_group_by_name(name)
    return {"changed": False, "group": g, "exists": g is not None}


def op_rename_group(client, from_name, to_name, preserve_policies=True):
    """Rename one group. Idempotent: returns unchanged if already renamed."""
    existing_dst = client.get_group_by_name(to_name)
    if existing_dst is not None:
        # Destination already owns the name; confirm source no longer exists.
        still_src = client.get_group_by_name(from_name)
        if still_src is None:
            return {"changed": False, "renamed": 0, "group": existing_dst}
        # Both exist — ambiguous.  Bail loudly so the operator can resolve.
        raise AuthentikApiError(
            "Cannot rename %r -> %r: both groups already exist. "
            "Manual intervention required." % (from_name, to_name)
        )

    src = client.get_group_by_name(from_name)
    if src is None:
        # Nothing to do.
        return {"changed": False, "renamed": 0, "group": None}

    pk = src.get("pk")
    bindings_before = []
    if preserve_policies:
        bindings_before = client.list_policy_bindings_for_group(pk)

    updated = client.rename_group(pk, to_name)

    # Post-rename verification: PK (= UUID) must be unchanged, so members are
    # preserved implicitly.  Policy bindings reference PK, not name — verify.
    if updated.get("pk") != pk:
        raise AuthentikApiError(
            "Authentik changed group PK during rename (%s -> %s). "
            "Member/policy preservation cannot be guaranteed." % (pk, updated.get("pk"))
        )

    if preserve_policies:
        bindings_after = client.list_policy_bindings_for_group(pk)
        before_ids = sorted(b.get("pk") for b in bindings_before if b.get("pk"))
        after_ids = sorted(b.get("pk") for b in bindings_after if b.get("pk"))
        if before_ids != after_ids:
            raise AuthentikApiError(
                "Policy bindings changed during rename of %r. "
                "Before: %s After: %s" % (from_name, before_ids, after_ids)
            )

    return {"changed": True, "renamed": 1, "group": updated}


def op_rename_group_prefix(client, from_prefix, to_prefix):
    """Rename every group whose name starts with C(from_prefix).

    Behaviour:
    * If no groups match ``from_prefix``: ``changed=False, renamed=0``.
    * If a group with the target name already exists, that one is skipped
      silently (idempotent replay).
    * Otherwise each candidate is renamed via ``op_rename_group``.
    """
    if not from_prefix or not to_prefix:
        raise AuthentikApiError("rename_group_prefix requires both from_prefix and to_prefix")
    if from_prefix == to_prefix:
        return {"changed": False, "renamed": 0, "groups": []}

    all_groups = client.list_groups()
    candidates = [g for g in all_groups if g.get("name", "").startswith(from_prefix)]
    renamed = []
    for g in candidates:
        old_name = g["name"]
        new_name = to_prefix + old_name[len(from_prefix):]
        if new_name == old_name:
            continue
        # Idempotent replay: if the destination name already exists, skip.
        existing = client.get_group_by_name(new_name)
        if existing is not None:
            continue
        result = op_rename_group(client, old_name, new_name, preserve_policies=True)
        if result.get("changed"):
            renamed.append({"from": old_name, "to": new_name, "pk": g.get("pk")})

    return {
        "changed": bool(renamed),
        "renamed": len(renamed),
        "groups": renamed,
    }


def op_create_group(client, name, attributes=None):
    existing = client.get_group_by_name(name)
    if existing is not None:
        return {"changed": False, "group": existing}
    new = client.create_group(name=name, attributes=attributes)
    return {"changed": True, "group": new}


def op_delete_group(client, name):
    existing = client.get_group_by_name(name)
    if existing is None:
        return {"changed": False}
    client.delete_group(existing["pk"])
    return {"changed": True, "deleted": name}


# ---------------------------------------------------------------------------
# OIDC client == Application + OAuth2 Provider pair.  Authentik stores them
# separately but the user-facing "client" is the named pair bound together
# via ``application.provider = provider.pk``.
# ---------------------------------------------------------------------------


def _find_oidc_pair(client, name):
    """Return (application, provider) for a named OIDC client, each may be None."""
    app = client.get_application_by_name(name)
    if app is None:
        # Fallback: some setups name the slug after the provider.
        app = client.get_application_by_slug(name)
    provider = client.get_oauth2_provider_by_name(name)
    # If application has a provider ref, prefer that provider (canonical link).
    if app and not provider and app.get("provider"):
        try:
            provider = client.get("/providers/oauth2/%s/" % (app["provider"],))
        except AuthentikApiError:
            provider = None
    return app, provider


def op_list_oidc_clients(client):
    providers = client.list_oauth2_providers()
    apps = client.list_applications()
    # Join by provider pk for a human-friendly view.
    by_pk = {a.get("provider"): a for a in apps if a.get("provider")}
    joined = []
    for p in providers:
        joined.append({
            "name": p.get("name"),
            "provider_pk": p.get("pk"),
            "client_id": p.get("client_id"),
            "application": by_pk.get(p.get("pk")),
        })
    return {"changed": False, "clients": joined}


def op_rename_oidc_client(client, from_name, to_name):
    """Rename the Application **and** Provider that form one OIDC client.

    Preserves the application<->provider binding (the ``provider`` FK on the
    application is never touched — only the display names).
    """
    # Idempotent replay: if the destination names already exist, bail no-op.
    dst_app = client.get_application_by_name(to_name)
    dst_prov = client.get_oauth2_provider_by_name(to_name)
    if dst_app is not None and dst_prov is not None:
        src_app = client.get_application_by_name(from_name)
        src_prov = client.get_oauth2_provider_by_name(from_name)
        if src_app is None and src_prov is None:
            return {"changed": False, "renamed": 0}
        raise AuthentikApiError(
            "Ambiguous rename %r -> %r: both source and destination partially exist."
            % (from_name, to_name)
        )

    src_app, src_prov = _find_oidc_pair(client, from_name)
    if src_app is None and src_prov is None:
        return {"changed": False, "renamed": 0}

    changed = False
    binding_provider_pk_before = src_app.get("provider") if src_app else None

    if src_prov is not None and src_prov.get("name") == from_name:
        client.rename_oauth2_provider(src_prov["pk"], to_name)
        changed = True

    if src_app is not None and src_app.get("name") == from_name:
        # PATCH only the name; do NOT touch ``provider`` FK.
        client.update_application(src_app["slug"], {"name": to_name})
        changed = True

    # Verify binding preserved (provider FK on application is unchanged).
    if src_app is not None:
        app_after = client.get_application_by_name(to_name) or client.get_application_by_slug(src_app["slug"])
        if app_after is not None and binding_provider_pk_before is not None:
            if app_after.get("provider") != binding_provider_pk_before:
                raise AuthentikApiError(
                    "Application<->Provider binding lost during rename of %r "
                    "(was provider=%s, now %s)."
                    % (from_name, binding_provider_pk_before, app_after.get("provider"))
                )

    return {"changed": changed, "renamed": 1 if changed else 0}


def op_rename_oidc_client_prefix(client, from_prefix, to_prefix):
    if not from_prefix or not to_prefix:
        raise AuthentikApiError(
            "rename_oidc_client_prefix requires both from_prefix and to_prefix"
        )
    if from_prefix == to_prefix:
        return {"changed": False, "renamed": 0, "clients": []}

    providers = client.list_oauth2_providers()
    apps = client.list_applications()

    # Collect every unique client-name with the legacy prefix — whether it
    # originates from the Application side or the Provider side (both should
    # match in healthy setups, but we accept either).
    candidate_names = set()
    for p in providers:
        n = p.get("name", "")
        if n.startswith(from_prefix):
            candidate_names.add(n)
    for a in apps:
        n = a.get("name", "")
        if n.startswith(from_prefix):
            candidate_names.add(n)

    renamed = []
    for old_name in sorted(candidate_names):
        new_name = to_prefix + old_name[len(from_prefix):]
        result = op_rename_oidc_client(client, old_name, new_name)
        if result.get("changed"):
            renamed.append({"from": old_name, "to": new_name})

    return {
        "changed": bool(renamed),
        "renamed": len(renamed),
        "clients": renamed,
    }


def op_migrate_members(client, from_group, to_group):
    """Move members from C(from_group) to C(to_group).

    In most Authentik migrations this is a no-op because PK-preserving
    renames already carry members.  We implement it for completeness —
    useful when collapsing two groups into one.
    """
    src = client.get_group_by_name(from_group)
    dst = client.get_group_by_name(to_group)
    if src is None:
        return {"changed": False, "migrated": 0, "reason": "source_missing"}
    if dst is None:
        raise AuthentikApiError(
            "migrate_members: destination group %r does not exist" % (to_group,)
        )
    src_users = src.get("users") or []
    dst_users = set(dst.get("users") or [])

    added = [u for u in src_users if u not in dst_users]
    if not added:
        return {"changed": False, "migrated": 0}
    new_members = sorted(dst_users.union(added))
    client.patch("/core/groups/%s/" % (dst["pk"],), json_body={"users": new_members})
    return {"changed": True, "migrated": len(added)}


def op_wait_api_reachable(client, timeout_sec=30, poll_interval=1.0):
    ok = client.wait_reachable(timeout_sec=timeout_sec, poll_interval=poll_interval)
    return {"changed": False, "reachable": bool(ok)}


# ---------------------------------------------------------------------------
# Action dispatch — used both by AnsibleModule main() and by callers (action
# handlers in ``module_utils/nos_migrate_actions/authentik_proxy.py``).
# ---------------------------------------------------------------------------


def build_client(*, api_url=None, port=None, domain=None, token=None,
                 secrets_path=None, timeout=15, retries=3, verify_tls=True):
    base = resolve_endpoint(explicit=api_url, authentik_port=port, authentik_domain=domain)
    resolved_token = resolve_token(explicit=token, secrets_path=secrets_path)
    return NosAuthentikClient(
        base_url=base,
        token=resolved_token,
        timeout=timeout,
        retries=retries,
        verify_tls=verify_tls,
    )


def dispatch(action, client, params):
    """Invoke the right op.  ``params`` is a plain dict of caller args."""
    if action == "list_groups":
        return op_list_groups(client, search=params.get("search"))
    if action == "get_group":
        return op_get_group(client, name=params["name"])
    if action == "rename_group":
        return op_rename_group(
            client,
            from_name=params["from_name"],
            to_name=params["to_name"],
            preserve_policies=params.get("preserve_policies", True),
        )
    if action == "rename_group_prefix":
        return op_rename_group_prefix(
            client,
            from_prefix=params["from_prefix"],
            to_prefix=params["to_prefix"],
        )
    if action == "create_group":
        return op_create_group(
            client, name=params["name"], attributes=params.get("attributes"),
        )
    if action == "delete_group":
        return op_delete_group(client, name=params["name"])
    if action == "list_oidc_clients":
        return op_list_oidc_clients(client)
    if action == "rename_oidc_client":
        return op_rename_oidc_client(
            client, from_name=params["from_name"], to_name=params["to_name"],
        )
    if action == "rename_oidc_client_prefix":
        return op_rename_oidc_client_prefix(
            client,
            from_prefix=params["from_prefix"],
            to_prefix=params["to_prefix"],
        )
    if action == "migrate_members":
        return op_migrate_members(
            client, from_group=params["from_group"], to_group=params["to_group"],
        )
    if action == "wait_api_reachable":
        return op_wait_api_reachable(
            client,
            timeout_sec=params.get("timeout_sec", 30),
            poll_interval=params.get("poll_interval", 1.0),
        )
    raise AuthentikApiError("Unknown action: %r" % (action,))


def main():
    module = AnsibleModule(
        argument_spec=dict(
            action=dict(type="str", required=True, choices=[
                "list_groups", "get_group", "rename_group",
                "rename_group_prefix", "create_group", "delete_group",
                "list_oidc_clients", "rename_oidc_client",
                "rename_oidc_client_prefix", "migrate_members",
                "wait_api_reachable",
            ]),
            authentik_api_url=dict(type="str"),
            authentik_port=dict(type="int"),
            authentik_domain=dict(type="str"),
            authentik_api_token=dict(type="str", no_log=True),
            secrets_path=dict(type="str", default="~/.nos/secrets.yml"),
            verify_tls=dict(type="bool", default=True),
            timeout=dict(type="int", default=15),
            retries=dict(type="int", default=3),
            name=dict(type="str"),
            search=dict(type="str"),
            from_name=dict(type="str"),
            to_name=dict(type="str"),
            from_prefix=dict(type="str"),
            to_prefix=dict(type="str"),
            from_group=dict(type="str"),
            to_group=dict(type="str"),
            attributes=dict(type="dict"),
            timeout_sec=dict(type="int", default=30),
            poll_interval=dict(type="float", default=1.0),
            preserve_members=dict(type="bool", default=True),
            preserve_policies=dict(type="bool", default=True),
        ),
        supports_check_mode=False,
    )

    params = module.params
    try:
        client = build_client(
            api_url=params.get("authentik_api_url"),
            port=params.get("authentik_port"),
            domain=params.get("authentik_domain"),
            token=params.get("authentik_api_token"),
            secrets_path=os.path.expanduser(params.get("secrets_path") or "~/.nos/secrets.yml"),
            timeout=params.get("timeout") or 15,
            retries=params.get("retries") or 3,
            verify_tls=params.get("verify_tls"),
        )
        result = dispatch(params["action"], client, params)
    except AuthentikApiError as exc:
        module.fail_json(msg=str(exc), status_code=getattr(exc, "status_code", None),
                         url=getattr(exc, "url", None))
    except Exception as exc:  # pragma: no cover — defensive
        module.fail_json(msg=str(exc), traceback=traceback.format_exc())
    else:
        module.exit_json(**result)


if __name__ == "__main__":
    main()
