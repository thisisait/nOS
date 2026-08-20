#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nos_secret_map — resolve the secret scheme and derive the credential map.

Secrets P1 (docs/secrets-p1-hkdf.md). Three modes, and the split between the
first two is load-bearing:

mode=resolve    Scheme resolution ONLY. Returns {scheme, mint} and NO secret
                material, so the main.yml task that runs it carries no no_log
                and every SchemeError arrives with its remediation text
                intact. (The first cut resolved+derived in one no_log task;
                the adversarial review showed Ansible then censors exactly
                the failure messages the module was written to emit.)
mode=map        Derivation, under task-level `no_log: true`. Returns the full
                {key: value} map + the master (minted here when resolve said
                mint). Its own failure modes are registry-shape errors, which
                the resolve pass has already validated — so a censored
                failure here is a bug, not the designed UX.
mode=user_leaf  One per-user credential (§P1b); first consumer is the
                Bluesky PDS bridge. v1 keeps the historical
                `<prefix>_pw_<v1_suffix>` byte-identical.

no_log discipline, learned the hard way (adversarial review, reproduced):
`prefix` MUST NOT be a `no_log` parameter. AnsibleModule.exit_json() runs
remove_values() over the whole result with every no_log param value as a
substring filter — and every scheme-v1 value CONTAINS the prefix by
construction, so a no_log prefix rewrites the entire v1 map to
`********_pw_<key>`: the exact opposite of the byte-identity this change
promises. Confidentiality is the TASK's job (`no_log: true` on the map task);
the parameter must stay scrubber-invisible. `master` stays no_log: no returned
value ever contains it (HKDF is one-way; pinned by the derive unit tests), so
the scrubber has nothing to corrupt, and it keeps the hex out of argv/log
echoes of module args.

The module READS state it does not trust the play to relay (the persisted
store file, the stacks dir) and never writes anything — persistence stays with
the existing secrets.yml.j2 render, so this module cannot record its own
success (the read-back rule).
"""

from __future__ import annotations

import os

from ansible.module_utils.basic import AnsibleModule

# Under Ansible, module_utils is packed into the AnsiballZ payload; when the
# module runs STANDALONE (the module-boundary gate executes it exactly the way
# Ansible does, subprocess + ANSIBLE_MODULE_ARGS), the sibling directory is the
# source. Same dual-import shape as nos_state.py.
try:
    from ansible.module_utils import nos_secret_derive as derive  # type: ignore
except ImportError:
    import os
    import sys

    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "module_utils")
    )
    import nos_secret_derive as derive  # type: ignore


def main():
    module = AnsibleModule(
        argument_spec=dict(
            mode=dict(type="str", default="map",
                      choices=["resolve", "map", "user_leaf"]),
            registry_path=dict(type="path", required=False),
            store_path=dict(type="path", required=False),
            stacks_dir=dict(type="path", required=False),
            # NOT no_log — see the module docstring. The map task's own
            # `no_log: true` is what keeps values out of logs.
            prefix=dict(type="str", default=""),
            tester_prefix=dict(type="str", default=""),
            requested_scheme=dict(type="str", default=""),
            blanking=dict(type="bool", default=False),
            # map (post-resolve) + user_leaf: the already-resolved scheme.
            scheme=dict(type="str", default=""),
            mint=dict(type="bool", default=False),
            master=dict(type="str", default="", no_log=True),
            username=dict(type="str", default=""),
            service=dict(type="str", default=""),
            purpose=dict(type="str", default=""),
            v1_suffix=dict(type="str", default=""),
        ),
        supports_check_mode=True,
    )
    p = module.params

    try:
        if p["mode"] == "resolve":
            result = _resolve(p)
        elif p["mode"] == "user_leaf":
            result = _user_leaf(p)
        else:
            result = _map(module, p)
    except (derive.SchemeError, ValueError) as exc:
        module.fail_json(msg=str(exc))
        return
    # Derivation is a pure read of declared state — never `changed`.
    module.exit_json(changed=False, **result)


def _read_store(store_path):
    """The recorded scheme + master, from the FILE — the module examines the
    store itself rather than trusting relay vars, because include_vars order
    has bitten this repo before (the credentials.yml shadowing fix, 2026-08-15).
    """
    if not store_path or not os.path.isfile(store_path):
        return False, "", ""
    import yaml

    try:
        with open(store_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise derive.SchemeError(
            "~/.nos/secrets.yml is not parseable YAML (%s) — refusing to "
            "guess the secret scheme from a corrupt store. Restore the file "
            "from backup, or run a confirmed blank." % exc
        )
    if not isinstance(data, dict):
        data = {}
    return True, str(data.get("nos_secret_scheme", "") or ""), str(
        data.get("nos_secret_master", "") or ""
    )


def _resolve(p):
    """Scheme decision + full validation, secret-free return."""
    if not p["registry_path"]:
        raise ValueError("mode=resolve requires registry_path")
    # Validate the registry HERE so a shape error fails in the loud task,
    # not inside the censored map task.
    derive.load_registry(p["registry_path"])

    store_exists, recorded, stored_master = _read_store(p["store_path"])
    stacks = p["stacks_dir"] or ""
    estate_converged = bool(stacks) and os.path.isdir(stacks) and bool(os.listdir(stacks))

    scheme, mint = derive.resolve_scheme(
        recorded=recorded,
        requested=p["requested_scheme"],
        blanking=p["blanking"],
        store_exists=store_exists,
        estate_converged=estate_converged,
    )
    if scheme == derive.SCHEME_V2 and not mint:
        # Loud here, censored nowhere: a v2 record with a corrupt master.
        derive.master_bytes(stored_master)
    return {"scheme": scheme, "mint": bool(mint)}


def _map(module, p):
    if not p["registry_path"]:
        raise ValueError("mode=map requires registry_path")
    if p["scheme"] not in derive.SCHEMES:
        raise ValueError(
            "mode=map requires the scheme from a prior mode=resolve call "
            "(got %r)" % p["scheme"]
        )
    if not p["prefix"]:
        raise ValueError(
            "mode=map requires the password prefix (scheme v1 derives from it)"
        )
    registry = derive.load_registry(p["registry_path"])
    scheme = p["scheme"]

    master_hex = ""
    if scheme == derive.SCHEME_V2:
        if p["mint"]:
            master_hex = derive.mint_master()
        else:
            _, _, master_hex = _read_store(p["store_path"])
        derive.master_bytes(master_hex)  # loud on a corrupt store

    secret_map = derive.build_map(
        scheme, registry, p["prefix"], p["tester_prefix"], master_hex
    )
    return {
        "scheme": scheme,
        "minted": bool(p["mint"] and scheme == derive.SCHEME_V2),
        "master": master_hex,
        "map": secret_map,
    }


def _user_leaf(p):
    for req in ("scheme", "username", "service", "purpose"):
        if not p[req]:
            raise ValueError("mode=user_leaf requires %s" % req)
    if p["scheme"] == derive.SCHEME_V1:
        if not p["prefix"]:
            raise ValueError(
                "mode=user_leaf under scheme v1 requires the password prefix "
                "— an empty prefix would silently derive `_pw_...` alone"
            )
        suffix = p["v1_suffix"] or ("%s_%s" % (p["service"], p["username"]))
        return {"value": derive.v1_leaf(p["prefix"], suffix)}
    if p["scheme"] == derive.SCHEME_V2:
        master = derive.master_bytes(p["master"])
        uid = derive.slugify_uid(p["username"])
        if not uid:
            raise ValueError(
                "username %r slugifies to nothing — refusing an unsalted user leaf"
                % p["username"]
            )
        return {"value": derive.user_leaf(master, uid, p["service"], p["purpose"])}
    raise ValueError("unknown scheme %r" % p["scheme"])


if __name__ == "__main__":
    main()
