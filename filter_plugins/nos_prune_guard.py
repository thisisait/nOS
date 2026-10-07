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
import sys
from pathlib import Path

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
    fragments are named by whatever separator the role chose.

    FALLBACK ONLY since 2026-09-01: it is a guess, and three services are
    unreachable by any separator rule (`install_calibreweb` -> calibre-web.yml,
    `install_openwebui` -> open-webui.yml, `install_offline_maps` ->
    tileserver.yml). Used only where the manifest has no row to ask.
    """
    return re.compile(
        r"^" + re.escape(name).replace("_", "[-_]?") + r"(-base)?$"
    )


def _manifest_stems():
    """install_<svc> -> [fragment stem], from state/manifest.yml. The join.

    A flag carried by SEVERAL rows is a stack flag, not a service identity
    (`install_observability` -> grafana+prometheus+loki+tempo+alloy), and
    pruning on it is the 2026-09-01 blast radius. Excluded: it answers `[]`,
    which is what the guess answered too.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from nos_identity import fragment_stem, services  # noqa: PLC0415

    by_flag = {}
    for row in services():
        by_flag.setdefault(row.get("install_flag"), []).append(fragment_stem(row))
    return {f: [s for s in v if s] for f, v in by_flag.items() if f and len(v) == 1}


try:
    _STEMS = _manifest_stems()
except Exception:  # noqa: BLE001 — never fail a converge over the join
    _STEMS = {}


def nos_prune_plan(disabled, on_disk_flags, overrides, containers):
    """Split a compose prune into what may be applied and what must be refused.

    disabled      -- [svc] whose install_<svc> resolves FALSE at run time
    on_disk_flags -- {"install_<svc>": value} merged from default.config.yml
                     then config.yml, UNRENDERED
    overrides     -- {path: [compose service names the fragment declares]}
    containers    -- [running container names]

    Returns {"unauthored": [...], "unauthored_destructive": [...],
             "indeterminate": [...], "fragments": [...], "containers": [...],
             "stop": [...]}.

    `stop` is every off-at-run-time service's running containers, authored or
    not. Stopping is reversible and survives a reboot via
    `restart: unless-stopped`, so it is returned even on a refusal — the
    refusal guards DELETION.

    `unauthored_destructive` non-empty means REFUSE: the caller must not act on
    `fragments` or `containers`, which are returned empty in that case so a
    caller that forgets to check the refusal still destroys nothing.

    REFUSAL KEYS ON BLAST RADIUS, NOT ON ATTRIBUTION. The first cut refused on
    `unauthored` alone and thereby broke `profiles/gov-local.yml`, a committed
    profile invoked exactly as documented (`-e @profiles/gov-local.yml`): it
    sets `install_tailscale: false` over a config.yml that says true, so the
    disablement is correctly un-authored — and tailscale has no compose
    fragment, so obeying it would have destroyed nothing. Refusing a converge
    to protect zero containers is the guard failing at its own job. An
    un-authored service that owns no fragment is reported and skipped; one
    that owns a fragment still stops the run, which is the 2026-09-01 case.
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

    def _patterns(name):
        """The manifest row is authoritative — including when it answers "no
        fragment". Only a name with no row at all falls back to the guess."""
        flag = "install_" + name
        if flag in _STEMS:
            return [re.compile(r"^" + re.escape(s) + r"(-base)?$") for s in _STEMS[flag]]
        return [_sep_insensitive(name)]

    def _select(names):
        patterns = [p for s in names for p in _patterns(s)]
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

        # EXACT names only. `<project>-<service>-<n>` is compose's own scheme;
        # the bare `<service>` catches a pinned `container_name:`, which the
        # caller supplies alongside the service keys because the two are only
        # equal by coincidence (pazny.smtp_stalwart is the one live case).
        # Neither form can over-match, which is the whole point — the substring
        # form is what destroyed nine unrelated containers.
        wanted = set()
        for stack, svc in compose_services:
            wanted.add(re.compile(
                r"^" + re.escape(stack) + r"-" + re.escape(svc) + r"-\d+$"))
            wanted.add(re.compile(r"^" + re.escape(svc) + r"$"))
        return fragments, sorted(
            {c for c in containers if any(p.match(c) for p in wanted)})

    # STOPPING IS NOT DELETING, so the two sets are computed apart.
    # `stop` covers every service that is off at run time, authored or not:
    # `docker stop` is reversible, and `restart: unless-stopped` keeps it
    # stopped across a reboot, so it needs neither a toggle nor a refusal.
    _, stoppable = _select(disabled)

    # An un-authored disablement only matters if obeying it would DESTROY
    # something. Attribute first, then measure the radius.
    destructive = [s for s in unauthored if _select([s])[0]]
    if destructive:
        return {
            "unauthored": unauthored,
            "unauthored_destructive": destructive,
            "indeterminate": indeterminate,
            "fragments": [],
            "containers": [],
            "stop": stoppable,
        }

    fragments, doomed = _select(authored)
    return {
        "unauthored": unauthored,
        "unauthored_destructive": [],
        "indeterminate": indeterminate,
        "fragments": fragments,
        "containers": doomed,
        "stop": stoppable,
    }


_LAUNCHD_VAR = re.compile(r'^(\w+)_launchd_label:\s*"([\w.\-]+)"')


def launchd_declarations(repo=None):
    """Every launchd label the repo declares, once: a `<x>_launchd_label` var
    in role defaults or default.config.yml — the var name, never the value's
    shape (an `eu.thisisait.nos.*` .app bundle id is not a job, 2026-10-05).
    Flag: the role (`pazny.backrest` -> install_backrest), else `install_<x>` if
    declared. Domain: `<x>_launchd_domain`, default gui. Shared with
    tools/anatomy-graph-gen.py harvest_daemons, so roster and plan agree."""
    repo = Path(repo) if repo else Path(__file__).resolve().parents[1]
    cfg = repo / "default.config.yml"
    flags = set(re.findall(r"^(install_\w+):", cfg.read_text(encoding="utf-8"), re.M))
    sources = [(p, "install_" + p.parent.parent.name.split(".", 1)[1])
               for p in sorted(repo.glob("roles/*/defaults/main.yml"))
               if p.parent.parent.name.startswith("pazny.")] + [(cfg, None)]
    rows = {}
    for path, role_flag in sources:
        text = path.read_text(encoding="utf-8")
        domains = dict(re.findall(r'^(\w+)_launchd_domain:\s*"(\w+)"', text, re.M))
        for line in text.splitlines():
            m = _LAUNCHD_VAR.match(line.strip())
            if not m or "legacy" in m.group(1):
                continue
            x, label = m.groups()
            flag = role_flag or (f"install_{x}" if f"install_{x}" in flags else None)
            rows.setdefault(label, {"label": label, "install_flag": flag,
                                    "domain": domains.get(x, "gui")})
    return list(rows.values())


def graph_launchd_labels(nodes):
    """The launchd roster the graph carries: a row's own jobs sit on its
    service: node as `launchd_labels` (I-12, one organ one node); a daemon: node
    is a job no row owns (the heartbeat). Shared with tools/undeclared-status.py."""
    labels = set()
    for nid, n in (nodes or {}).items():
        if not isinstance(n, dict) or ":" not in nid:
            continue
        if n.get("kind") == "daemon":
            labels.add(nid.split(":", 1)[1])
        labels.update(n.get("launchd_labels") or [])
    return labels


def nos_host_daemon_plan(graph, domain=None):
    """Join anatomy-graph daemon nodes to install_* via their declaration.

    The graph is the roster — a label not in it is dropped, even if a role
    still declares it. No hand list of daemons. Heartbeat/resume live in
    templates/ with no install_*, so they are not in this plan. `domain`
    narrows to gui (the sudo-free stack layer) or system (needs become).
    """
    nodes = (graph or {}).get("nodes") or {}
    graph_labels = graph_launchd_labels(nodes)
    return [r for r in launchd_declarations()
            if r["install_flag"] and r["label"] in graph_labels
            and domain in (None, r["domain"])]


# ── Orphan compose extensions (2026-10-03) ─────────────────────────────────
# A plugin fragment (core-up pre_compose) can land before its role's base
# fragment (stack-up), and compose then refuses the WHOLE project: `service
# "nos-forum" has neither an image nor a build context` took 22 healthy iiab
# services down. A fragment naming a service no file defines is excluded.
_DEFINES = ("image", "build", "extends")


def _services(doc):
    svc = (doc or {}).get("services") if isinstance(doc, dict) else None
    return svc if isinstance(svc, dict) else {}


def orphan_fragments(docs):
    """docs: {path: parsed compose} incl. the base file -> orphan paths, sorted."""
    defined = {name for d in docs.values() for name, body in _services(d).items()
               if isinstance(body, dict) and any(k in body for k in _DEFINES)}
    return sorted(p for p, d in docs.items() if set(_services(d)) - defined)


def stack_orphans(stack_dir):
    """Read <stack>/docker-compose.yml + overrides/*.yml from disk."""
    import yaml  # noqa: PLC0415 — Ansible ships it; the reader host has it
    root = Path(stack_dir)
    files = [root / "docker-compose.yml", *sorted((root / "overrides").glob("*.yml"))]
    docs = {}
    for f in files:
        if f.is_file():
            try:
                docs[str(f)] = yaml.safe_load(f.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue  # compose names an unparsable file itself
    return [p for p in orphan_fragments(docs) if "/overrides/" in p]


def nos_split_orphans(found, stacks_dir):
    """{stack: [find file dicts]} -> {'keep': same shape, 'orphans': [paths]}."""
    orphans = [p for stack in found for p in stack_orphans(Path(stacks_dir) / stack)]
    keep = {k: [f for f in v if f.get("path") not in orphans] for k, v in found.items()}
    return {"keep": keep, "orphans": orphans}


class FilterModule(object):
    def filters(self):
        return {
            "nos_prune_plan": nos_prune_plan,
            "nos_host_daemon_plan": nos_host_daemon_plan,
            "nos_split_orphans": nos_split_orphans,
        }
