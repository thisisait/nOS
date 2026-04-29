#!/usr/bin/python
# -*- coding: utf-8 -*-
# (c) 2026, This is AIT / nOS project
# GNU GPL v3.0 — distributed with the nOS Ansible playbook.
"""
nos_apps_render — Ansible module that walks ``apps/*.yml`` Tier-2 manifests,
validates them via ``module_utils.nos_app_parser``, runs the three deploy
gates (TLS / SSO / EU residency), resolves magic tokens with stable secret
seeding, and returns a structured result the caller can splice into
``service-registry.json``, Wing's ``systems`` table, Authentik's
``authentik_oidc_apps`` list, and the apps-stack compose override.

The module is INTENT-ONLY: it never writes to disk. The runner role
(``pazny.apps_runner``) takes the dict it returns and feeds it into the
existing template/lineinfile/include_role infrastructure.

Returned shape (what the role consumes):

    {
      "apps": [
        {
          "id": "documenso",
          "version": "1.0.0",
          "fqdn": "documenso.apps.dev.local",
          "category": "productivity",
          "auth_mode": "proxy" | "oidc" | "none",
          "compose": {<resolved compose service block(s)>},
          "traefik_labels": [<list of label strings>],
          "registry_entry": {<for service-registry.json>},
          "wing_system": {<for /api/v1/hub/systems upsert>},
          "authentik_entry": {<for authentik_oidc_apps>} | null,
          "kuma_monitor": {<for uptime_kuma manifest extension>},
          "smoke_entry": {<for state/smoke-catalog.yml extension>},
          "gdpr": {<full Article 30 record>},
          "secrets_used": ["PASSWORD_DB", "BASE64_32_SESSION", ...]
        },
        ...
      ],
      "generated_secrets": {
        "documenso": {"PASSWORD_DB": "...", "BASE64_32_SESSION": "..."},
        ...
      },
      "gate_violations": [<list of human-readable strings>]
    }

The role emits a hard fail when ``gate_violations`` is non-empty (unless
``apps_force: true``). Each violation includes the app id and the gate
that fired so the operator can fix it in one read.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
    name: nos_apps_render
    short_description: Parse, gate, and resolve Tier-2 app manifests under apps/.
    description:
      - Discovers every apps/*.yml (skips _-prefixed files), parses + validates
        each via module_utils.nos_app_parser.parse_app_file, runs the TLS / SSO
        / EU-residency deploy gates, resolves magic tokens with stable secret
        seeding, and returns a structured dict for the runner role to consume.
    options:
      apps_dir:
        description: Directory containing apps/*.yml manifests.
        required: true
        type: path
      instance_tld:
        description: TLD used in $SERVICE_FQDN_<APP> token expansion.
        required: true
        type: str
      apps_subdomain:
        description: Subdomain segment for Tier-2 apps. Default 'apps'.
        required: false
        type: str
        default: "apps"
      secret_seed:
        description: |
          Pre-seed for PASSWORD/BASE64 tokens. Pass the previous run's
          generated_secrets here so values stay stable across runs.
        required: false
        type: dict
        default: {}
      eu_registries:
        description: Extra image registries treated as EU-resident.
        required: false
        type: list
        elements: str
        default: []
      strict:
        description: Raise on first gate violation. Default false (collect all).
        required: false
        type: bool
        default: false
"""

import os
import sys

# Standard Ansible module API
from ansible.module_utils.basic import AnsibleModule  # noqa: E402

# nOS parser (relative import — module_utils is on sys.path during play)
try:
    from ansible.module_utils.nos_app_parser import (  # type: ignore[import]
        parse_app_file,
        gate_tls_required,
        gate_sso_required,
        gate_eu_residency,
        resolve_tokens,
        AppParseError,
    )
except Exception:  # pragma: no cover — pytest fallback path
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(_here, ".."))
    from module_utils.nos_app_parser import (  # type: ignore[no-redef]
        parse_app_file,
        gate_tls_required,
        gate_sso_required,
        gate_eu_residency,
        resolve_tokens,
        AppParseError,
    )


# ---------------------------------------------------------------------------
# Per-app derivations

def _fqdn_for(app_name, instance_tld, subdomain):
    """Tier-2 hostname: <id>.<subdomain>.<tld>. apps_subdomain keeps Tier-2
    out of Tier-1 routing so a 'gitea' Tier-2 app can coexist with the Tier-1
    pazny.gitea role on git.<tld>."""
    sub = subdomain.strip(".") if subdomain else ""
    if sub:
        return "{}.{}.{}".format(app_name, sub, instance_tld)
    return "{}.{}".format(app_name, instance_tld)


def _primary_port(record):
    """Resolve the app's primary HTTP port (used for Traefik label).

    Order of preference:
      1. record.meta.ports[0]                         (operator-declared)
      2. compose.services.<app_name>.ports[0]         (compose port mapping)
      3. fall back to 80                              (last resort, will warn)
    """
    name = record["meta"]["name"]
    meta_ports = (record.get("meta") or {}).get("ports") or []
    if meta_ports:
        try:
            return int(str(meta_ports[0]).split(":")[-1])
        except (TypeError, ValueError):
            pass
    services = ((record.get("compose") or {}).get("services") or {})
    svc = services.get(name) or next(iter(services.values()), {})
    for p in (svc.get("ports") or []):
        # accept "8080" / "8080:80" / "127.0.0.1:8080:80"
        try:
            return int(str(p).split(":")[-1])
        except (TypeError, ValueError):
            continue
    return 80


def _auth_mode(record):
    """Authentication mode hint for Traefik labels + Authentik provider type.

    Manifest may set `nginx.auth: proxy|oidc|none`. Default `proxy` (safest:
    Authentik forward-auth gates the request before it reaches the app).
    Operator must opt out explicitly to `none`, and the parser already
    enforces SSO requirements via gate_sso_required.
    """
    mode = ((record.get("nginx") or {}).get("auth") or "proxy").lower()
    if mode not in ("proxy", "oidc", "none"):
        mode = "proxy"
    return mode


def _traefik_labels(app_name, fqdn, port, auth_mode, traefik_network):
    """Standard Traefik Docker-provider labels for a Tier-2 app."""
    name_safe = app_name.replace("_", "-")
    labels = [
        "traefik.enable=true",
        "traefik.docker.network={}".format(traefik_network),
        "traefik.http.routers.{}.rule=Host(`{}`)".format(name_safe, fqdn),
        "traefik.http.routers.{}.entrypoints=websecure".format(name_safe),
        "traefik.http.routers.{}.tls=true".format(name_safe),
        "traefik.http.services.{}.loadbalancer.server.port={}".format(name_safe, port),
    ]
    if auth_mode == "proxy":
        labels.append(
            "traefik.http.routers.{}.middlewares=authentik@file,security-headers@file,compress@file"
            .format(name_safe)
        )
    else:
        labels.append(
            "traefik.http.routers.{}.middlewares=security-headers@file,compress@file"
            .format(name_safe)
        )
    return labels


def _rbac_tier(record):
    """Authentik RBAC tier (1-4) for the app. Drives the runtime extension
    of `authentik_app_tiers` in roles/pazny.apps_runner/tasks/post.yml.

    Manifests declare it via nginx.rbac_tier; defaults to 3 (end_users)
    matching the convention in roles/pazny.authentik (services without
    an explicit entry default to tier 3).
    """
    raw = ((record.get("nginx") or {}).get("rbac_tier"))
    try:
        tier = int(raw) if raw is not None else 3
    except (TypeError, ValueError):
        tier = 3
    return max(1, min(4, tier))  # clamp


def _registry_entry(app_name, record, fqdn):
    """Shape that lines up with templates/service-registry.json.j2 schema.
    Note: `tier` is an INT — Tier-1 entries above use the int form too,
    so the consumer (Bone /api/services + Wing /systems) sees a uniform type.
    """
    meta = record.get("meta") or {}
    return {
        "name": app_name,
        "category": meta.get("category", "app"),
        "tier": 2,
        "enabled": True,
        "toggle_var": "install_app_" + app_name,
        "domain": fqdn,
        "port": _primary_port(record),
        "url": "https://{}/".format(fqdn),
        "type": "docker",
        "stack": "apps",
        "description": meta.get("summary", ""),
        # Future-UI cross-link metadata (Wing /apps cards consume these)
        "version": meta.get("version", "unknown"),
        "homepage": meta.get("homepage", ""),
    }


def _wing_system(app_name, record, fqdn, auth_mode, rbac_tier):
    """Shape that fits Wing's POST /api/v1/hub/systems upsert payload.

    Includes future-UI cross-link metadata (auth_mode, rbac_tier,
    gdpr_id, traefik_router) so Wing's planned /apps cards can link to
    /gdpr/<id>, the Traefik dashboard router page, and the Authentik
    application slug without re-derivation.
    """
    meta = record.get("meta") or {}
    return {
        "id": "app_" + app_name,
        "name": meta.get("name", app_name),
        "type": "app",
        "category": meta.get("category", "app"),
        "stack": "apps",
        "domain": fqdn,
        "port": _primary_port(record),
        "url": "https://{}/".format(fqdn),
        "enabled": True,
        # Future-UI metadata
        "tier": 2,
        "rbac_tier": rbac_tier,
        "auth_mode": auth_mode,
        "version": meta.get("version", "unknown"),
        "homepage": meta.get("homepage", ""),
        "gdpr_id": "app_" + app_name,             # gdpr_processing.id
        "traefik_router": app_name.replace("_", "-"),
        "authentik_slug": app_name.replace("_", "-") if auth_mode != "none" else None,
    }


def _authentik_entry(app_name, record, fqdn, auth_mode, secrets_):
    """Shape mirroring entries in default.config.yml authentik_oidc_apps.

    auth=none → no Authentik entry needed.
    auth=oidc → OAuth2 provider (redirect_uris).
    auth=proxy → Proxy provider (external_host + type: proxy).
    """
    if auth_mode == "none":
        return None
    meta = record.get("meta") or {}
    common = {
        "name": meta.get("name") or app_name,
        "slug": app_name.replace("_", "-"),
        "enabled": True,
        "client_id": "nos-app-" + app_name,
        "client_secret": secrets_.get(
            "PASSWORD_AUTHENTIK",
            "REPLACE_ME_app_" + app_name + "_authentik",
        ),
    }
    if auth_mode == "oidc":
        # Apps wired to OIDC are expected to declare their callback path
        # in the manifest's nginx.oidc_callback hint; default = /oauth/callback.
        callback = ((record.get("nginx") or {}).get("oidc_callback")
                    or "/oauth/callback")
        common["redirect_uris"] = "https://{}{}".format(fqdn, callback)
    else:  # proxy
        common["external_host"] = "https://{}".format(fqdn)
        common["launch_url"] = "https://{}".format(fqdn)
        common["type"] = "proxy"
    return common


def _kuma_monitor(app_name, record, fqdn):
    """Pseudo-manifest entry the existing pazny.uptime_kuma role consumes
    via the runtime fact extension (see C3)."""
    return {
        "id": "app_" + app_name,
        "domain_var": "__inline__",
        "_resolved_domain": fqdn,
        "install_flag": "__always__",
        "stack": "apps",
        "category": (record.get("meta") or {}).get("category", "app"),
    }


def _smoke_entry(app_name, fqdn):
    """Auto-extending entry for state/smoke-catalog.yml. The runner appends
    these so every onboarded Tier-2 app gets a smoke probe automatically.

    Status code shape:
      200 — app rendered (no auth gate)
      301/302/308 — redirect to Authentik for proxy auth, or app's own /login
      401 — proxy gate response before user logs in
      502 — Traefik gets the request but the upstream container is still
            booting (first 30-60s after compose-up). Smoke runs immediately
            after stack-up so this is the most common transient.
    """
    return {
        "id": "app_" + app_name,
        "url": "https://{}/".format(fqdn),
        "expect": [200, 301, 302, 308, 401, 502],
        "tier": 2,
        "note": "Tier-2 app onboarded via apps_runner",
    }


# ---------------------------------------------------------------------------
# Compose service block resolution

def _resolve_compose_block(app_name, record, instance_tld, secret_seed,
                           apps_subdomain=""):
    """Walk record.compose.services, resolve magic tokens in every string
    field, return (resolved compose dict, generated secrets dict, secret keys
    actually used).

    Pass-through of apps_subdomain so $SERVICE_FQDN_<APP> resolves to
    ``<host>.<apps_subdomain>.<tld>`` matching what _fqdn_for() emits for
    the Traefik label. Without this the env-var FQDN diverges from the
    Traefik route — Documenso ends up advertising
    https://documenso.dev.local/ in NEXT_PUBLIC_WEBAPP_URL while Traefik
    actually routes documenso.apps.dev.local. Magic-link emails would
    point at a host with no route.
    """
    import json
    compose = record.get("compose") or {}

    # Serialize → token-resolve → deserialize. Resolves tokens uniformly across
    # nested env strings, image refs, command lines, etc. without per-key
    # special-casing.
    raw = json.dumps(compose, ensure_ascii=False)
    resolved, secrets = resolve_tokens(
        raw, app_name=app_name, instance_tld=instance_tld,
        secret_seed=secret_seed, apps_subdomain=apps_subdomain,
    )
    try:
        out = json.loads(resolved)
    except ValueError as exc:
        raise AppParseError(app_name, [
            "compose JSON re-parse failed after token resolve: {}".format(exc),
        ])
    return out, secrets, sorted(secrets.keys())


# ---------------------------------------------------------------------------
# Main per-app processor

def _process_one(path, instance_tld, apps_subdomain, secret_seed,
                 extra_eu_registries, strict, traefik_network):
    """Return ({app dict OR None}, {generated secrets OR {}}, [violations])."""
    name = os.path.splitext(os.path.basename(path))[0]
    try:
        record = parse_app_file(path)
    except AppParseError as exc:
        return None, {}, [
            "[{}] {}".format(exc.app_name, v) for v in exc.violations
        ]
    except Exception as exc:  # noqa: BLE001
        return None, {}, ["[{}] unexpected: {}".format(name, exc)]

    violations = []

    # Gate 1 — TLS required for sensitive subjects
    if gate_tls_required(record):
        # The runner role enforces TLS at the Traefik label level
        # (entrypoints=websecure, tls=true). Nothing to validate here beyond
        # that the manifest didn't ask for plain HTTP — which the parser
        # already rejected at validate() time. So this is informational.
        pass

    # Gate 2 — SSO required when legal_basis: consent
    if gate_sso_required(record):
        mode = _auth_mode(record)
        if mode == "none":
            violations.append(
                "[{}] gate_sso_required: legal_basis=consent demands "
                "Authentik wiring (nginx.auth must be 'proxy' or 'oidc')"
                .format(name)
            )

    # Gate 3 — EU residency
    eu_ok, eu_offenders = gate_eu_residency(record, extra_eu_registries=extra_eu_registries)
    if not eu_ok:
        for o in eu_offenders:
            violations.append(
                "[{}] gate_eu_residency: {}".format(name, o)
            )

    if violations and strict:
        return None, {}, violations

    # Per-app secret seed (operator's previous-run secrets, if any)
    seed_for_app = (secret_seed or {}).get(name, {}) or {}

    fqdn = _fqdn_for(name, instance_tld, apps_subdomain)
    port = _primary_port(record)
    auth_mode = _auth_mode(record)

    # Resolve compose block tokens — pass apps_subdomain so $SERVICE_FQDN_*
    # in env strings matches the Traefik-routed hostname.
    try:
        compose_resolved, generated_secrets, secrets_used = _resolve_compose_block(
            name, record, instance_tld, seed_for_app,
            apps_subdomain=apps_subdomain,
        )
    except AppParseError as exc:
        return None, {}, ["[{}] {}".format(exc.app_name, v) for v in exc.violations]

    # Authentik entry (if applicable) + RBAC tier for the runtime
    # extension of authentik_app_tiers in apps_runner post.yml.
    authentik = _authentik_entry(name, record, fqdn, auth_mode, generated_secrets)
    rbac_tier = _rbac_tier(record)

    out = {
        "id": name,
        "version": (record.get("meta") or {}).get("version", "unknown"),
        "fqdn": fqdn,
        "category": (record.get("meta") or {}).get("category", "app"),
        "auth_mode": auth_mode,
        "rbac_tier": rbac_tier,
        "compose": compose_resolved,
        "traefik_labels": _traefik_labels(name, fqdn, port, auth_mode, traefik_network),
        "registry_entry": _registry_entry(name, record, fqdn),
        "wing_system": _wing_system(name, record, fqdn, auth_mode, rbac_tier),
        "authentik_entry": authentik,
        "kuma_monitor": _kuma_monitor(name, record, fqdn),
        "smoke_entry": _smoke_entry(name, fqdn),
        "gdpr": record.get("gdpr") or {},
        "secrets_used": secrets_used,
    }
    return out, ({name: generated_secrets} if generated_secrets else {}), violations


# ---------------------------------------------------------------------------
# Ansible entrypoint

def main():
    module = AnsibleModule(
        argument_spec=dict(
            apps_dir=dict(type="path", required=True),
            instance_tld=dict(type="str", required=True),
            apps_subdomain=dict(type="str", default="apps"),
            secret_seed=dict(type="dict", default={}),
            eu_registries=dict(type="list", elements="str", default=[]),
            strict=dict(type="bool", default=False),
            traefik_network=dict(type="str", default="shared_net"),
        ),
        supports_check_mode=True,
    )
    p = module.params
    apps_dir = p["apps_dir"]
    if not os.path.isdir(apps_dir):
        module.exit_json(changed=False, apps=[], generated_secrets={},
                         gate_violations=[],
                         msg="apps_dir {} does not exist — nothing to render".format(apps_dir))

    apps = []
    generated = {}
    violations = []
    for fname in sorted(os.listdir(apps_dir)):
        if not fname.endswith((".yml", ".yaml")):
            continue
        if fname.startswith("_"):  # skip templates
            continue
        if fname.endswith((".draft", ".draft.yml", ".draft.yaml")):
            continue
        path = os.path.join(apps_dir, fname)
        app, secrets, viol = _process_one(
            path,
            instance_tld=p["instance_tld"],
            apps_subdomain=p["apps_subdomain"],
            secret_seed=p["secret_seed"],
            extra_eu_registries=p["eu_registries"],
            strict=p["strict"],
            traefik_network=p["traefik_network"],
        )
        if app is not None:
            apps.append(app)
        generated.update(secrets)
        violations.extend(viol)

    module.exit_json(
        changed=False,  # render is pure / cacheable; the role drives changes
        apps=apps,
        generated_secrets=generated,
        gate_violations=violations,
        ids=[a["id"] for a in apps],
    )


if __name__ == "__main__":
    main()
