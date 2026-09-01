# nOS — compose-prune destroy guard.
#
# MEASURED 2026-09-01. A converge run as
#   ansible-playbook main.yml --tags preflight -e @tests/config.yml
# deleted 36 compose fragments and force-removed 33 running containers, and
# reported `changed=3` (Ansible counts TASKS, not loop items). Two independent
# defects, both closed here:
#
#  1. BLAST RADIUS. `prune-disabled.yml` chose containers by UNANCHORED
#     substring of the disabled-service alternation against `docker ps`.
#     `install_observability: false` is a STACK flag with no compose fragment,
#     so it removed nothing — and still matched every `observability-*`
#     container by substring, destroying grafana, prometheus, loki, tempo,
#     influxdb and four exporters. Fragments removed by that token: zero.
#     Containers destroyed by it: nine. The fix is to derive containers from
#     the compose `services:` keys of the fragments ACTUALLY removed, which is
#     exact — `infra/overrides/authentik.yml` declares `authentik-server` +
#     `authentik-worker`, so the containers are `infra-authentik-server-1` and
#     `infra-authentik-worker-1` and nothing else can match.
#
#  2. NO ATTRIBUTION. Extra-vars outrank config.yml, so a foreign config file
#     reclassified 36 enabled services as disabled and the prune obeyed with no
#     dry run and no confirmation. The OpenTofu path already refuses exactly
#     this (nos_tofu_destroy_split): a destroy whose install flag resolves off
#     APPLIES, one that is un-authored REFUSES and says which. The compose path
#     had no equivalent. It does now.
#
# "Authored" means the ON-DISK config layers — default.config.yml overlaid by
# config.yml — say the service is off. That is the operator's own standing
# declaration, and it stays a one-flag, no-ceremony operation. A disablement
# that exists only for the duration of one command is not a declaration.

from __future__ import annotations

import os
import re

#: A value we cannot attribute without rendering Jinja (e.g.
#: `install_acme: "{{ not tenant_domain_is_local }}"`). Neither authored-off nor
#: un-authored: it contributes no fragments, so ignoring it destroys nothing and
#: blocks nothing.
_JINJA = re.compile(r"\{\{|\{%")

#: Distinguishes "declared false" from "not declared" — both are falsey to
#: `.get()`, and only one of them is a declaration.
_MISSING = object()


def _literal_state(value):
    """-> True / False / None(indeterminate) for an on-disk install_* value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if _JINJA.search(value):
            return None
        v = value.strip().lower()
        if v in ("true", "yes", "on", "1"):
            return True
        if v in ("false", "no", "off", "0"):
            return False
    return None


def _sep_insensitive(name):
    """`uptime_kuma` matches `uptime-kuma.yml` and `uptime_kuma.yml` alike —
    fragments are named by whatever separator the role chose."""
    return re.compile(
        r"^" + re.escape(name).replace("_", "[-_]?") + r"(-base)?$"
    )


def nos_prune_plan(disabled, on_disk_flags, overrides, containers):
    """Split a compose prune into what may be applied and what must be refused.

    disabled      -- [svc] whose install_<svc> resolves FALSE at run time
    on_disk_flags -- {"install_<svc>": value} merged from default.config.yml
                     then config.yml, UNRENDERED
    overrides     -- {path: [compose service names the fragment declares]}
    containers    -- [running container names]

    Returns {"unauthored": [...], "indeterminate": [...],
             "fragments": [...], "containers": [...]}.

    `unauthored` non-empty means REFUSE: the caller must not act on `fragments`
    or `containers`, which are returned empty in that case so a caller that
    forgets to check the refusal still destroys nothing.
    """
    disabled = sorted(set(disabled or []))
    on_disk_flags = on_disk_flags or {}
    overrides = overrides or {}
    containers = list(containers or [])

    authored, unauthored, indeterminate = [], [], []
    for svc in disabled:
        value = on_disk_flags.get("install_" + svc, _MISSING)
        if value is _MISSING:
            # Off at run time, not declared on disk at all: the extra-vars case
            # again, and the one with the least evidence behind it.
            unauthored.append(svc)
            continue
        state = _literal_state(value)
        if state is None:
            indeterminate.append(svc)
        elif state is False:
            authored.append(svc)
        else:
            # Enabled on disk but off at run time: the disablement came from
            # somewhere with no durable record — extra-vars, -e @file, an
            # include_vars. Not a declaration.
            unauthored.append(svc)

    if unauthored:
        return {
            "unauthored": unauthored,
            "indeterminate": indeterminate,
            "fragments": [],
            "containers": [],
        }

    patterns = [_sep_insensitive(s) for s in authored]
    fragments, compose_services = [], []
    for path, services in sorted(overrides.items()):
        parts = path.split(os.sep)
        if len(parts) < 3 or parts[-2] != "overrides":
            continue
        stem = re.sub(r"\.ya?ml$", "", parts[-1])
        if not any(p.match(stem) for p in patterns):
            continue
        fragments.append(path)
        for svc in services or []:
            compose_services.append((parts[-3], svc))

    # EXACT names only. `<project>-<service>-<n>` is compose's own scheme; the
    # bare `<service>` covers a fragment that pins `container_name:`. Neither
    # can over-match, which is the whole point — the substring form is what
    # destroyed nine unrelated containers.
    wanted = set()
    for stack, svc in compose_services:
        wanted.add(re.compile(r"^" + re.escape(stack) + r"-" + re.escape(svc) + r"-\d+$"))
        wanted.add(re.compile(r"^" + re.escape(svc) + r"$"))

    doomed = sorted({c for c in containers if any(p.match(c) for p in wanted)})

    return {
        "unauthored": [],
        "indeterminate": indeterminate,
        "fragments": fragments,
        "containers": doomed,
    }


class FilterModule(object):
    def filters(self):
        return {"nos_prune_plan": nos_prune_plan}
