"""Anatomy gate — a service with its own Authentik button is not gated twice.

Plan: docs/idea/13-relations.md §R5, row "Forward-auth ≠ native-OIDC
      double-protection" ("ours, derivable").

WHAT IS BEING REFUSED. A `native_oidc` service redirects to Authentik from its
OWN login page. Putting `authentik@file` in front of it as well makes the
operator authenticate twice for the same session and buys nothing: the second
factor is the same Authentik, the same cookie domain, the same groups. It also
breaks machine callers — the estate has already paid for that once, and the
receipt is in `roles/pazny.traefik/vars/main.yml:63-72`, where gating Woodpecker
would have 302'd the playbook's own post-wiring API calls.

WHY THIS IS A GATE AND NOT A PARAGRAPH. `traefik_auth_modes` FALLS THROUGH TO
`proxy` — `templates/dynamic/services.yml.j2:54` reads
`traefik_auth_modes.get(s.id, 'proxy')`, and line 82 attaches `authentik@file`
for that mode. So the double-login is what you get by *forgetting* an entry, not
by writing a wrong one, and forgetting is the failure mode a rule in CLAUDE.md
cannot catch. The same default sits on the Tier-2 side under a different key
(`nginx.auth`, `files/anatomy/library/nos_apps_render.py:192`).

FOUR PLACES CAN ATTACH THE MIDDLEWARE, AND THIS READS ALL FOUR:

  1. `traefik_auth_modes[id]` — mode `proxy`, or ABSENT (services.yml.j2:54/82)
  2. `traefik_extra_routers[].auth` — same default (services.yml.j2:107)
  3. a `traefik.http.routers.*.middlewares=…authentik@file…` compose label,
     the @docker provider — one live today (`roles/pazny.smtp_stalwart`)
  4. a Tier-2 manifest's `nginx.auth` (nos_apps_render.py:192/209)

MEASURED 2026-08-07, and the finding is that there is nothing to fix: 45 routed
services, 19 of them declaring `native_oidc`, and all 19 carry edge mode `oidc`.
Corroborated against the running estate rather than only the source —
`~/stacks/infra/traefik/conf.d/services.yml` renders 42 routers of which 19
carry `authentik@file`, and the two sets are disjoint. This file therefore ships
GREEN on purpose; it was shown RED by deleting one line
(`grafana: oidc`), which is exactly the edit the `proxy` default punishes. The
quoted failure is in the R5 report.

FOUR THINGS IT CANNOT COVER, none of them silent:

  * **The `access` facet does not exist yet.** §R4 puts `form`/`layer`/`build`
    — and `access` — in the genome entity schema; until then "how is this
    reached" lives in the two storage sites read here, exactly as
    `test_access_facet_reconciled.py` says. When entities migrate this becomes
    a regenerate-and-diff.
  * **A runtime opt-in can flip a service's real mode without moving either
    declaration.** `paperclip_native_oidc_enabled` (default false,
    `default.config.yml:2350`) renders a `BETTER_AUTH_OIDC_*` block behind a
    `forward_auth` declaration. Inert today —
    `roles/pazny.paperclip/tasks/post.yml:170` records "Upstream Paperclip does
    not yet wire BetterAuth genericOAuth from env. Access control remains
    enforced by the Nginx Authentik outpost" — so it is not a stack. If
    upstream ever consumes it, this gate reads the unflipped declaration and
    stays green on a real double login.
  * **The FreeScout case CLOSED (fee 49).** It declared `native_oidc` while
    both module sources were HTTP 404 — ungated, not double-gated. Flipped to
    `mode: forward_auth` under REM-192 (2026-08-11); the dead OIDC env and the
    module clone were removed 2026-09-03. This gate now covers it like any
    other forward_auth service.
  * **Auth that is not Authentik's.** Woodpecker's gate is Gitea OAuth at app
    level; the sibling file's `PROVIDER_NOT_EDGE_ATTACHED` carries that
    reasoning. Nothing here can see an in-service login that Authentik does not
    issue.

CI-safe: pure source scan. No Docker, no network, no live host.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"
PLUGINS = REPO / "files" / "anatomy" / "plugins"
APPS = REPO / "apps"

#: services.yml.j2:54 and nos_apps_render.py:192 both default to this. An id
#: with no entry is GATED — reading absence as "none" is how a reviewer would
#: conclude this gate has nothing to check.
DEFAULT_MODE = "proxy"

#: `provider_type` is the Authentik object name, `mode` the nOS doctrine label,
#: and `state/schema/plugin.schema.json` calls them aliases: `oauth2 ≡
#: native_oidc`, `proxy ≡ forward_auth`. Measured 2026-08-07: every block that
#: has a `provider_type` also has a `mode`, so the alias mapping is DEFENSIVE
#: rather than load-bearing today — but the schema permits `provider_type`
#: alone, and five plugins already spell it `oauth2` (bookstack, freescout,
#: hedgedoc, miniflux, wordpress). Dropping one `mode:` line would otherwise
#: take that service out of the population silently.
CANON = {
    "oauth2": "native_oidc",
    "native_oidc": "native_oidc",
    "proxy": "forward_auth",
    "forward_auth": "forward_auth",
    "header_oidc": "header_oidc",
}

#: header_oidc is NOT a stack: the outpost must stay in path precisely so it can
#: stamp Remote-User / X-Authentik-* for the service to auto-create the account
#: (firefly, keap). Only native_oidc contradicts a forward-auth gate.
STACK_CONTRADICTS = "native_oidc"

_LABEL_AUTHENTIK = re.compile(
    r"traefik\.http\.routers\.[^\s=]*\.middlewares=[^\"'\n]*authentik@file")


def _vars() -> dict:
    return yaml.safe_load(TRAEFIK_VARS.read_text(encoding="utf-8"))


def _norm(service_id: str) -> str:
    """manifest/vars use snake_case ids; plugin slugs use kebab. Same service."""
    return service_id.replace("_", "-")


def routed_ids() -> list[str]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    services = manifest["services"] if isinstance(manifest, dict) else manifest
    skip = set(_vars().get("traefik_skip_ids") or [])
    return [
        s["id"] for s in services
        if s.get("domain_var") and s.get("port_var") and s["id"] not in skip
    ]


def declared_modes() -> dict[str, tuple[str, str]]:
    """normalised slug → (canonical mode, where it was declared)."""
    out: dict[str, tuple[str, str]] = {}
    for p in sorted(PLUGINS.rglob("plugin.yml")):
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        a = m.get("authentik") or {}
        raw = a.get("mode") or a.get("provider_type")
        if not raw:
            continue
        slug = a.get("slug") or m["name"].replace("-base", "")
        out[_norm(slug)] = (CANON.get(raw, raw), str(p.relative_to(REPO)))
    for p in sorted(APPS.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        a = m.get("authentik") or {}
        raw = a.get("mode") or a.get("provider_type")
        if not raw:
            continue
        slug = a.get("slug") or p.stem
        out[_norm(slug)] = (CANON.get(raw, raw), str(p.relative_to(REPO)))
    return out


def _owner_slug(path: pathlib.Path) -> str:
    """Which service owns this template — `pazny.<x>` or `<x>-base`, at any depth.

    Positional (`parts[-3]`) breaks on the nested template dirs the estate
    already has (`roles/pazny.traefik/templates/dynamic/…`), and a slug that
    resolves to `templates` matches no declaration — which would drop a real
    attachment silently. That is the failure this gate exists to refuse, so it
    must not commit it itself.
    """
    for part in reversed(path.parts):
        if part.startswith("pazny."):
            return part.split(".", 1)[1]
        if part.endswith("-base"):
            return part[: -len("-base")]
    return path.stem


def attachments() -> dict[str, list[str]]:
    """normalised slug → every place `authentik@file` gets attached to it."""
    out: dict[str, list[str]] = {}

    def add(slug: str, where: str) -> None:
        out.setdefault(_norm(slug), []).append(where)

    v = _vars()
    modes = v.get("traefik_auth_modes") or {}
    for sid in routed_ids():
        if modes.get(sid, DEFAULT_MODE) == "proxy":
            where = ("traefik_auth_modes[%s]=proxy" % sid if sid in modes
                     else "traefik_auth_modes has NO entry for %r → services.yml.j2:54 "
                          "default 'proxy'" % sid)
            add(sid, where)
    for r in v.get("traefik_extra_routers") or []:
        if (r.get("auth") or DEFAULT_MODE) == "proxy":
            add(str(r.get("id", "?")), "traefik_extra_routers[%s].auth" % r.get("id"))
    for p in sorted(REPO.glob("roles/*/templates/**/*.j2")) + \
            sorted(PLUGINS.glob("*/templates/*.j2")):
        if not p.is_file():
            continue
        try:
            raw = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in _LABEL_AUTHENTIK.finditer(raw):
            line_start = raw.rfind("\n", 0, m.start()) + 1
            # A commented-out label attaches nothing. Counting one would invent
            # a gate the edge does not have — and inventing gates is the
            # direction that makes a real double login look already-handled.
            if raw[line_start:m.start()].lstrip().startswith("#"):
                continue
            lineno = raw.count("\n", 0, m.start()) + 1
            add(_owner_slug(p), "@docker label %s:%d" % (p.relative_to(REPO), lineno))
    for p in sorted(APPS.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        auth = ((m.get("nginx") or {}).get("auth") or DEFAULT_MODE).lower()
        if auth == "proxy":
            where = ("%s nginx.auth=proxy" % p.name if (m.get("nginx") or {}).get("auth")
                     else "%s has NO nginx.auth → nos_apps_render.py:192 default 'proxy'"
                          % p.name)
            add(p.stem, where)
    return out


# ── INV-1: the contradiction ──────────────────────────────────────────────


def test_no_native_oidc_service_is_also_forward_auth_gated():
    modes = declared_modes()
    attach = attachments()
    stacked = []
    for slug, (mode, source) in sorted(modes.items()):
        if mode != STACK_CONTRADICTS:
            continue
        for where in attach.get(slug, []):
            stacked.append(
                f"{slug}: declared {mode} in {source}, but authentik@file "
                f"attaches via {where}")
    assert not stacked, (
        "these services redirect to Authentik from their own login page AND "
        "get an authentik@file forward-auth gate in front of it — the operator "
        "authenticates twice for one session, and any machine caller gets a "
        "302 instead of its API response. Either drop the gate or drop the "
        "native_oidc claim.\n\n" + "\n".join(stacked)
    )


# ── INV-2: the population, so a green cannot come from an empty set ───────


def test_the_gate_has_a_population_to_judge():
    """A cross-check over an empty set certifies nothing and reads as calm.

    Floors are the 2026-08-07 census minus headroom: 45 routed services, 19
    declaring native_oidc. If a glob, a rename or a skip-list edit empties
    either side, this reports scope loss rather than passing INV-1 for free.
    """
    routed = routed_ids()
    modes = declared_modes()
    native = sorted(s for s in routed if (modes.get(_norm(s), ("",))[0]) == "native_oidc")
    assert len(routed) >= 40, f"only {len(routed)} routed services — manifest/skip drift?"
    assert len(native) >= 15, (
        f"only {len(native)} routed services declare native_oidc ({native}) — "
        "19 on 2026-08-07. Below this the 'nothing is stacked' verdict is a "
        "statement about an empty set, not about the estate"
    )


def test_the_attachment_model_actually_finds_attachments():
    """INV-1 passes trivially if nothing is read as gated.

    The estate gates 19 routers with `authentik@file` (measured live in
    `~/stacks/infra/traefik/conf.d/services.yml`, 42 routers). A model that
    finds far fewer has stopped reading one of the four attachment paths, and
    the one it would drop first is the DEFAULT — the silent one.
    """
    attach = attachments()
    assert len(attach) >= 18, (
        f"only {len(attach)} services read as authentik@file-gated: "
        f"{sorted(attach)}. The live edge gates 19; a smaller number means an "
        "attachment path is no longer being read"
    )
    labelled = [w for ws in attach.values() for w in ws if w.startswith("@docker")]
    assert labelled, (
        "no @docker `traefik.http.routers.*.middlewares=…authentik@file` label "
        "was found. roles/pazny.smtp_stalwart/templates/compose.yml.j2 carries "
        "one; if it moved, this gate stopped covering the label path entirely"
    )
