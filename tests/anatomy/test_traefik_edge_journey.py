"""One journey through the Traefik edge: the role's vars, its static and dynamic
templates, the routers it derives from the manifest and what each router lets through.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_traefik_upstream_matches_the_manifest, test_no_dup_traefik_router_labels,
  test_native_oidc_no_authentik_middleware, test_the_edge_reaches_the_host_on_both_platforms,
  test_traefik_api_not_insecure, test_bare_ip_lands_on_the_face,
  test_edge_auth_vocabulary_is_closed, test_no_route_inherits_its_gate,
  test_traefik_exposure_justified, test_rem047_authentik_header_injection.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from glob import glob

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

ROLE = REPO / "roles" / "pazny.traefik"
T = ROLE / "templates"
TRAEFIK_VARS = ROLE / "vars" / "main.yml"
STATIC = T / "traefik.yml.j2"
SERVICES = T / "dynamic" / "services.yml.j2"
TRAEFIK_MW = T / "dynamic" / "middlewares.yml.j2"
MANIFEST = REPO / "state" / "manifest.yml"
PLUGINS = REPO / "files" / "anatomy" / "plugins"


def _vars() -> dict:
    """roles/pazny.traefik/vars/main.yml with `{{ }}` expressions made scalars."""
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", TRAEFIK_VARS.read_text(encoding="utf-8"))
    return yaml.safe_load(raw) or {}


def _manifest_services() -> list[dict]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return manifest["services"] if isinstance(manifest, dict) else manifest


# ── test_traefik_upstream_matches_the_manifest ──────────────────────────────
# 2026-09-01: 5 of 9 hand `svc:` overrides in traefik_container_upstreams were
# byte-identical to the default. The manifest's container_name IS the compose
# service Traefik dials; a stale `svc:` is a 502 nothing joins. Only rows with a
# single container_name are checkable (woodpecker/authentik stay hand-written).

def _upstreams() -> dict:
    return _vars().get("traefik_container_upstreams") or {}


def _compose_service_name(row: dict) -> str | None:
    """`<stack>-<compose service>-<n>` → the compose service. None if unknowable."""
    cn = row.get("container_name")
    if not cn:
        return None
    m = re.fullmatch(rf"(?:{re.escape(row.get('stack', ''))}-)?(.+?)(?:-\d+)?", cn)
    return m.group(1) if m else None


def test_every_derivable_upstream_agrees_with_its_row() -> None:
    rows = {s["id"]: s for s in ni.services()}
    checked, wrong = 0, []
    for sid, up in _upstreams().items():
        row = rows.get(sid)
        assert row is not None, f"traefik_container_upstreams.{sid} is not a manifest id"
        derived = _compose_service_name(row)
        if derived is None:
            continue
        checked += 1
        effective = up.get("svc", sid.replace("_", "-"))
        if effective != derived:
            wrong.append(f"{sid}: dials {effective!r}, row says {derived!r} ({row['container_name']})")
    assert not wrong, (
        "the Traefik upstream alias disagrees with the manifest container_name — "
        "one of the two is stale and the render is a 502:\n  " + "\n  ".join(wrong))
    assert checked >= 7, f"only {checked} rows carry a container_name — coverage shrank"


# ── test_no_dup_traefik_router_labels ───────────────────────────────────────
# 2026-06-02 Jellyfin/Calibre/Kiwix 502s: a plugin compose-ext emitted @docker
# router labels on a host port beside the @file router at the same priority — a
# per-reload coin-flip. Plugin compose-exts may only opt out (traefik.enable=false).

FORBIDDEN = ("traefik.http.routers.", "traefik.http.services.")


def _compose_exts() -> list[pathlib.Path]:
    return sorted(PLUGINS.glob("*/templates/*.compose.yml.j2"))


def test_compose_exts_exist():
    assert _compose_exts(), "no plugin compose-extensions found — glob/path drift?"


def test_no_docker_provider_router_labels():
    offenders = []
    for f in _compose_exts():
        text = f.read_text()
        for needle in FORBIDDEN:
            if needle in text:
                offenders.append(f"{f.relative_to(REPO)} :: {needle}")
    assert not offenders, (
        "plugin compose-extensions must not emit docker-provider router/service labels "
        "(Tier-1 services are file-provider-routed; a second @docker router collides with "
        "@file and 502s on coin-flip). Offenders:\n  " + "\n  ".join(offenders)
    )


# ── test_native_oidc_no_authentik_middleware ────────────────────────────────
# 2026-05-07: Node-RED flipped to native_oidc but its compose-ext still labelled
# authentik@file; the @docker and @file routers collided and ~50% of requests
# 404'd. A native_oidc plugin's templates declare no authentik@file middleware.

def _native_oidc_plugins() -> list[str]:
    """Yield every plugin.yml whose authentik.mode is native_oidc."""
    out: list[str] = []
    for path in glob(f"{REPO}/files/anatomy/plugins/*/plugin.yml"):
        try:
            with open(path) as fh:
                doc = yaml.safe_load(fh) or {}
        except (yaml.YAMLError, OSError):
            continue
        mode = (doc.get("authentik") or {}).get("mode")
        if mode == "native_oidc":
            out.append(path)
    return out


# Match a non-commented line that declares `authentik@file` as part of a
# Traefik middleware label — both YAML-list and dict forms.
_LABEL_RE = re.compile(
    r"^[^#]*traefik\.http\.routers\.[^=:\s]+\.middlewares\s*[=:][^#]*authentik@file",
    re.MULTILINE,
)


def test_native_oidc_compose_extensions_dont_emit_authentik_middleware():
    offenders: list[str] = []
    for plugin_yml in _native_oidc_plugins():
        plugin_dir = os.path.dirname(plugin_yml)
        tpl_dir = os.path.join(plugin_dir, "templates")
        if not os.path.isdir(tpl_dir):
            continue
        for tpl in glob(os.path.join(tpl_dir, "*.j2")):
            try:
                with open(tpl) as fh:
                    body = fh.read()
            except OSError:
                continue
            if _LABEL_RE.search(body):
                rel = os.path.relpath(tpl, REPO)
                offenders.append(rel)

    assert not offenders, (
        "native_oidc plugins MUST NOT emit `authentik@file` Traefik middleware in\n"
        "compose-extension templates. The service handles OIDC inside the app;\n"
        "wrapping it in forward-auth creates duplicate routers + double login.\n\n"
        "Fix: remove the `traefik.http.routers.<name>.middlewares` label from the\n"
        "extension, OR delete the extension entirely if Traefik routing was its\n"
        "only purpose. The file-provider router (auto-derived from state/manifest.yml\n"
        "+ traefik_auth_modes) is the canonical Tier-1 route.\n\n"
        "Offenders:\n  - " + "\n  - ".join(offenders)
    )


# ── test_the_edge_reaches_the_host_on_both_platforms ────────────────────────
# CI 2026-08-31, first Linux run with a Traefik: every router answered 500 —
# traefik_host_gateway_ip defaulted to Docker Desktop's 192.168.65.254, absent on
# a Linux bridge (hidden_fees/39). Pins the per-platform resolution; reachability
# itself belongs to the CI wet-test.

PLATFORM = REPO / "tasks/_platform.yml"
#: The Docker Desktop (macOS) gateway. Correct there, meaningless on Linux.
MAC_GATEWAY = "192.168.65.254"


def _platform_tasks() -> list[dict]:
    return [t for t in yaml.safe_load(PLATFORM.read_text(encoding="utf-8")) or []
            if isinstance(t, dict)]


def test_the_gateway_is_resolved_per_platform() -> None:
    setters = [t for t in _platform_tasks()
               if "traefik_host_gateway_ip" in str(t.get("ansible.builtin.set_fact")
                                                   or t.get("set_fact") or "")]
    assert setters, (
        "tasks/_platform.yml no longer resolves traefik_host_gateway_ip. Without "
        f"it the value falls back to the literal {MAC_GATEWAY} in "
        "services.yml.j2 — Docker Desktop's gateway — and every host-daemon "
        "route on Linux answers 500.")

    body = yaml.dump(setters)
    assert "macos" in body, (
        "the resolver does not branch on platform, so it is a second hardcoded "
        "default rather than a fix")
    assert MAC_GATEWAY in body, (
        f"the macOS branch no longer carries {MAC_GATEWAY}. services.yml.j2 "
        "records that the IPv6 `nos-host` alias does NOT reach host loopback on "
        "macOS, so that literal is a measurement, not an arbitrary choice")


def test_the_template_still_defers_to_the_variable() -> None:
    """The resolver is pointless if the template stops reading the variable."""
    body = SERVICES.read_text(encoding="utf-8")
    assert "traefik_host_gateway_ip" in body, (
        "services.yml.j2 no longer reads traefik_host_gateway_ip — the platform "
        "resolution in tasks/_platform.yml now governs nothing")


# ── test_traefik_api_not_insecure ───────────────────────────────────────────
# REM-194 (live 2026-08-12): `api.insecure: true` served the whole API, edge
# anti-spoof tokens included, on container :8080 to every peer container. Pins:
# insecure false, /ping on its own :8080 entry point, and a dashboard route (if
# any) that is api@internal behind authentik@file.

def _static_directives() -> str:
    """traefik.yml.j2 with comment lines stripped — so prose that quotes the old
    `insecure: true` disposition can't satisfy or trip the directive scan."""
    lines = []
    for ln in STATIC.read_text().splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("#"):
            continue
        # Drop trailing inline comments too.
        lines.append(ln.split("#", 1)[0] if "#" in ln else ln)
    return "\n".join(lines)


def test_api_is_not_insecure():
    txt = _static_directives()
    assert "insecure: false" in txt, (
        "traefik.yml.j2 no longer sets `insecure: false` — REM-194 re-opens the "
        "whole API (incl. the edge tokens in /api/http/middlewares) on :8080 to "
        "every peer container the moment insecure is true again."
    )
    assert "insecure: true" not in txt, (
        "traefik.yml.j2 has a live `insecure: true` directive — that is exactly "
        "the REM-194 regression: the API becomes anonymous on container :8080."
    )


def test_ping_has_its_own_entrypoint():
    """/ping must ride a dedicated entry point, not the (now-gone) API one."""
    txt = STATIC.read_text()
    assert "entryPoint: \"ping\"" in txt or "entryPoint: ping" in txt, (
        "ping is no longer pinned to the dedicated `ping` entry point — with "
        "api.insecure false and no ping entry point, the healthcheck/smoke probe "
        "on :8080/ping stops answering and the container never reports healthy."
    )
    # The dedicated entry point must be declared, bound to :8080.
    assert "ping:\n    address: \":8080\"" in txt, (
        "the dedicated `ping` entry point on :8080 vanished from entryPoints — "
        "the host publish 127.0.0.1:<dash>:8080 would then reach nothing."
    )


def test_dashboard_route_is_sso_gated():
    """If the dashboard route is present, it is api@internal behind authentik."""
    txt = SERVICES.read_text()
    if "traefik-dashboard:" not in txt:
        # Route dropped entirely (traefik_dashboard_route_enabled=false) — fine,
        # nothing anonymous exists. Nothing to gate.
        return
    # Isolate the router block.
    block = txt.split("traefik-dashboard:", 1)[1].split("\n\n", 1)[0]
    assert "api@internal" in block, (
        "the traefik-dashboard router no longer points at the built-in "
        "api@internal service — a host-gateway upstream here is REM-144's shape."
    )
    assert "authentik@file" in block, (
        "the traefik-dashboard router lost its authentik@file middleware — the "
        "dashboard/API would be anonymous at the edge again (REM-194/REM-144)."
    )


# ── test_bare_ip_lands_on_the_face ──────────────────────────────────────────
# spark1 2026-10-19: http(s)://<host ip> answered 404. Bare-IP routers redirect to
# face_domain on both entrypoints, and the web blanket https redirect sits below
# them by priority. Renders the templates and reads the YAML Traefik would read.

def _render_tpl(path: pathlib.Path, **ctx) -> dict:
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined, extensions=["jinja2.ext.do"])
    env.filters["to_json"] = json.dumps
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "1", "yes") if not isinstance(v, bool) else v
    env.globals["lookup"] = lambda _kind, _name, default=None: default
    base = {"nos_manifest": {"services": []}, "traefik_auth_modes": {}, "tenant_domain": "spark.internal",
            "face_domain": "os.spark.internal", "ansible_managed": "test"}
    return yaml.safe_load(env.from_string(path.read_text()).render(**{**base, **ctx})) or {}


def _routers(**ctx) -> dict:
    return ((_render_tpl(SERVICES, **ctx).get("http") or {}).get("routers")) or {}


def test_both_entrypoints_route_a_bare_ip_to_the_face():
    r = _routers(install_face=True)
    web, sec = r.get("bare-ip-to-face-web"), r.get("bare-ip-to-face-websecure")
    assert web and sec, f"rendered routers: {sorted(r)}"
    assert web["entryPoints"] == ["web"] and "tls" not in web, "an http router must not demand TLS"
    assert sec["entryPoints"] == ["websecure"] and "tls" in sec
    for x in (web, sec):
        assert x["middlewares"] == ["bare-ip-to-face@file"] and x["rule"].startswith("HostRegexp(`^[0-9]+")
    mw = _render_tpl(TRAEFIK_MW)["http"]["middlewares"]["bare-ip-to-face"]["redirectRegex"]
    assert mw["replacement"] == "https://os.spark.internal/"


def test_no_face_no_redirect_and_the_switch_turns_it_off():
    assert not any(k.startswith("bare-ip") for k in _routers(install_face=False))
    assert not any(k.startswith("bare-ip") for k in _routers(install_face=True, traefik_bare_ip_redirect=False))


def test_the_blanket_https_redirect_yields_to_it():
    static = _render_tpl(STATIC)
    blanket = static["entryPoints"]["web"]["http"]["redirections"]["entryPoint"]["priority"]
    assert blanket < _routers(install_face=True)["bare-ip-to-face-web"]["priority"]


# ── test_edge_auth_vocabulary_is_closed ─────────────────────────────────────
# services.yml.j2 gates on `_auth == 'proxy'`; every other value, a typo
# included, renders ungated. 2026-08-11 REM-192's fix nearly shipped as
# `forward_auth` (the doctrine word). The legal vocabulary is derived from the
# template; whether an `oidc` login really offers Authentik is discovery-scan's.

@pytest.fixture(scope="module")
def modes() -> dict[str, str]:
    return _vars().get("traefik_auth_modes") or {}


def _template_vocabulary() -> set[str]:
    """The values the TEMPLATE actually branches on — derived, not restated:
    whatever it compares `_auth` against, plus its `.get(id, DEFAULT)` fallback."""
    text = SERVICES.read_text(encoding="utf-8")
    compared = set(re.findall(r"_auth\s*==\s*'([a-z_]+)'", text))
    fallback = set(re.findall(r"traefik_auth_modes\.get\([^,]+,\s*'([a-z_]+)'\)", text))
    return compared | fallback


def test_the_template_still_decides_with_a_comparison() -> None:
    """Guard the guard: if the branch changed shape, the derivation is blind."""
    vocab = _template_vocabulary()
    assert "proxy" in vocab, (
        "the template no longer compares _auth against 'proxy'. Re-read "
        f"{SERVICES.relative_to(REPO)} — this gate derives the legal vocabulary "
        "from that comparison and has just gone blind."
    )


def test_every_declared_mode_is_one_the_template_understands(modes) -> None:
    vocab = _template_vocabulary()
    # `oidc` and `none` never reach a comparison — they are the {% else %} — so
    # they are legal by intent rather than by syntax.
    intentional_else = {"oidc", "none"}
    legal = vocab | intentional_else

    strays = {sid: mode for sid, mode in modes.items() if mode not in legal}
    assert not strays, (
        "traefik_auth_modes carries value(s) the template does not understand: "
        f"{strays}. The template gates on `_auth == 'proxy'` and sends every "
        f"other value down the ungated branch, so these routes are OPEN while "
        f"the declaration says otherwise. Legal: {sorted(legal)}.\n"
        "This is exactly how REM-192's fix was nearly shipped ungated: the "
        "doctrine word is `forward_auth`, this map's word is `proxy`."
    )


def test_the_doctrine_word_is_never_used_here(modes) -> None:
    """`forward_auth` is correct in plugin.yml's `authentik.mode`, WRONG here,
    and wrong in the direction that opens a route."""
    offenders = [sid for sid, mode in modes.items() if mode in ("forward_auth", "forwardauth")]
    assert not offenders, (
        f"{offenders} use `forward_auth` in traefik_auth_modes. That is the "
        "plugin/doctrine spelling; this map's equivalent is `proxy`. The "
        "template does not recognise it and the route renders WITHOUT "
        "authentik@file — ungated, while four other files say it is gated."
    )


def test_the_gated_value_actually_attaches_authentik(modes) -> None:
    """`proxy` must still be the value that pulls in the middleware."""
    text = SERVICES.read_text(encoding="utf-8")
    branch = text[text.index("{% if _auth == 'proxy' %}"):]
    head = branch[: branch.index("{% else %}")]
    assert "authentik@file" in head, (
        "the `proxy` branch no longer attaches authentik@file. Every service "
        f"marked proxy ({sum(1 for m in modes.values() if m == 'proxy')} of them) "
        "would be silently ungated."
    )
    tail = branch[branch.index("{% else %}"):]
    assert "authentik@file" not in tail[: tail.index("{% endif %}")], (
        "the non-proxy branch now attaches authentik@file too, which would "
        "stack forward-auth on native_oidc services — the documented "
        "double-login anti-pattern (see test_forward_auth_does_not_stack.py)."
    )


# ── test_no_route_inherits_its_gate ─────────────────────────────────────────
# 2026-08-31: snappymail, smtp_stalwart and backrest (own auth disabled) were
# routed with no traefik_auth_modes entry — gated only by `.get(id, 'proxy')`, a
# default nobody chose. This asks that a human chose; whether the mode is right
# is the access-facet reconciliation's job.

def _routed_ids() -> list[str]:
    v = _vars()
    skipped = set(v.get("traefik_skip_ids") or [])
    services = (yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {})["services"]
    return [s["id"] for s in services
            if s.get("domain_var") and s["id"] not in skipped]


def test_every_routed_service_names_its_mode() -> None:
    modes = _vars().get("traefik_auth_modes") or {}
    inheriting = [i for i in _routed_ids() if i not in modes]
    assert not inheriting, (
        "these routed services have no entry in traefik_auth_modes, so the "
        "renderer's `.get(id, 'proxy')` decides for them. That is the safe "
        "direction and it is still not a decision — and for backrest, whose own "
        "auth is disabled, the inherited middleware is the only gate there is:\n  "
        + "\n  ".join(inheriting))


def test_every_listed_mode_is_a_manifest_id() -> None:
    """The other direction: a key no renderer can reach decides nothing.

    `traefik_auth_modes.get(s.id, ...)` is keyed by manifest id, so `openwebui`
    (removed 2026-09-01, alias of `open_webui`) was never read — a spelling
    kept beside the real one, reading as a decision.
    """
    ids = {s["id"] for s in (yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {})["services"]}
    orphans = [k for k in (_vars().get("traefik_auth_modes") or {}) if k not in ids]
    assert not orphans, (
        "these traefik_auth_modes keys are not manifest ids, so the renderer "
        f"never looks them up: {orphans}")


def test_the_gate_has_a_population() -> None:
    """Guard against the vacuous pass: a manifest or vars parse that silently
    yields nothing would make the assertion above trivially true."""
    routed, modes = _routed_ids(), (_vars().get("traefik_auth_modes") or {})
    assert len(routed) >= 40, f"only {len(routed)} routed services parsed — check the reader"
    assert len(modes) >= 40, f"only {len(modes)} auth modes parsed — check the reader"


def test_the_default_is_still_the_gated_one() -> None:
    """If the template's fallback ever became `none`, every unlisted id would go
    from gated to open and this file's premise would invert. Read from the
    template, not restated."""
    tpl = SERVICES
    if not tpl.is_file():
        tpl = next(REPO.glob("roles/pazny.traefik/templates/**/services.yml.j2"), None)
        assert tpl is not None, "services.yml.j2 not found — the premise is unreadable"
    body = tpl.read_text(encoding="utf-8")
    found = re.search(r"traefik_auth_modes.*?\|\s*default\(\s*'([a-z]+)'\s*\)", body, re.S) \
        or re.search(r"traefik_auth_modes\.get\(\s*[^,]+,\s*'([a-z]+)'\s*\)", body)
    assert found, "cannot find the fallback in services.yml.j2 — read it by hand"
    assert found.group(1) == "proxy", (
        f"the renderer's fallback is now {found.group(1)!r}; an unlisted id would "
        "no longer be gated, which inverts everything this file assumes")


# ── test_traefik_exposure_justified ─────────────────────────────────────────
# REM-144 (live 2026-07-30): the dashboard was auto-routed, `none`-moded and
# "justified" by a false comment, so the whole API, edge tokens included, was
# anonymous over :443. A comment is not a justification: an ungated route says
# why in traefik_auth_none_justification, a field this can read.

DEFAULT_MODE = "proxy"
UNGATED = "none"


def _load():
    return _manifest_services(), _vars()


def _emitted_router_ids(services, skip_ids) -> list[str]:
    """Ids services.yml.j2 will actually emit a router for (domain_var AND port_var)."""
    return [
        s["id"]
        for s in services
        if s.get("domain_var") and s.get("port_var") and s["id"] not in skip_ids
    ]


def test_sources_parse():
    services, tvars = _load()
    assert services, "state/manifest.yml has no services — path/shape drift?"
    assert "traefik_auth_modes" in tvars, "traefik_auth_modes vanished from vars/main.yml"
    assert "traefik_skip_ids" in tvars, "traefik_skip_ids vanished from vars/main.yml"


def test_default_auth_mode_is_gated():
    """The fall-through must stay `proxy`. A service nobody classified is gated."""
    tpl = SERVICES.read_text()
    assert f"traefik_auth_modes.get(s.id, '{DEFAULT_MODE}')" in tpl, (
        "services.yml.j2 no longer defaults unclassified services to "
        f"'{DEFAULT_MODE}' — an unlisted service would render ungated"
    )


def test_every_ungated_route_carries_a_justification():
    services, tvars = _load()
    skip_ids = set(tvars.get("traefik_skip_ids") or [])
    modes = tvars.get("traefik_auth_modes") or {}
    reasons = tvars.get("traefik_auth_none_justification") or {}

    offenders = []
    for sid in _emitted_router_ids(services, skip_ids):
        if modes.get(sid, DEFAULT_MODE) != UNGATED:
            continue
        reason = (reasons.get(sid) or "").strip()
        if len(reason) < 40:
            offenders.append(
                f"{sid}: routed (domain_var + port_var, not in traefik_skip_ids) "
                f"with auth_mode 'none' but no usable justification in "
                f"traefik_auth_none_justification"
            )

    assert not offenders, (
        "Anonymously reachable at the edge with nothing but a comment behind it "
        "(this is REM-144's exact shape):\n  " + "\n  ".join(offenders)
    )


def test_justifications_describe_live_routes_only():
    """Stale reasons rot into false comfort — the same failure one layer up."""
    services, tvars = _load()
    skip_ids = set(tvars.get("traefik_skip_ids") or [])
    modes = tvars.get("traefik_auth_modes") or {}
    reasons = tvars.get("traefik_auth_none_justification") or {}

    live_ungated = {
        sid
        for sid in _emitted_router_ids(services, skip_ids)
        if modes.get(sid, DEFAULT_MODE) == UNGATED
    }
    stale = sorted(set(reasons) - live_ungated)
    assert not stale, (
        "traefik_auth_none_justification explains services that are no longer "
        f"routed-and-ungated: {stale}. Drop them, or the map starts vouching for "
        "decisions nobody is making any more."
    )


def test_traefik_dashboard_is_not_routed():
    """The REM-144 regression test, named so a bisect points straight at it."""
    services, tvars = _load()
    skip_ids = set(tvars.get("traefik_skip_ids") or [])
    assert "traefik" in skip_ids, (
        "`traefik` left traefik_skip_ids. state/manifest.yml still gives it "
        "domain_var + port_var, so services.yml.j2 will auto-derive an edge router "
        "whose upstream is the Docker host-gateway — which proxies around the "
        "127.0.0.1 dashboard bind and re-opens the whole API anonymously over 443. "
        "If this is deliberate, the dashboard needs a real gate first (and note "
        "that /api/http/middlewares serves the edge tokens verbatim)."
    )


# ── test_rem047_authentik_header_injection ──────────────────────────────────
# REM-047 / PENTEST-001: a forward-auth backend trusts X-authentik-* blindly, so
# both edges must OVERWRITE client-sent values — nginx by auth_request_set +
# proxy_set_header, Traefik by the authResponseHeaders allow-list. Dropping a
# header from either list re-opens forgery for that field.

NGINX_CONF = REPO / "templates/nginx/authentik-proxy-auth.conf"

# The identity/authorization headers a backend must NEVER accept from the client.
SENSITIVE_HEADERS = [
    "x-authentik-username",
    "x-authentik-uid",
    "x-authentik-email",
    "x-authentik-name",
    "x-authentik-groups",
    "x-authentik-entitlements",
    "x-authentik-jwt",
    "x-authentik-meta-outpost",
    "x-authentik-meta-provider",
    "x-authentik-meta-app",
]


def test_nginx_captures_and_forwards_all_sensitive_headers():
    """nginx must auth_request_set FROM upstream AND proxy_set_header each header —
    both, so the outpost value overwrites the client's."""
    text = NGINX_CONF.read_text().lower()
    captured = set(re.findall(r"auth_request_set\s+\$\w+\s+\$upstream_http_(x_authentik_\w+)", text))
    forwarded = set(re.findall(r"proxy_set_header\s+(x-authentik-[\w-]+)\s+\$", text))

    for hdr in SENSITIVE_HEADERS:
        var_form = hdr.replace("-", "_")
        assert var_form in captured, (
            f"nginx must auth_request_set {hdr} from upstream (REM-047): "
            f"uncaptured headers pass client forgeries straight to the backend"
        )
        assert hdr in forwarded, (
            f"nginx must proxy_set_header {hdr} from the captured value (REM-047): "
            f"capture without forward leaves the client value in place"
        )


def test_traefik_allowlists_all_sensitive_auth_response_headers():
    """Traefik overwrites a request header only when it appears in the auth
    response allow-list; an absent header keeps the client-sent value."""
    text = TRAEFIK_MW.read_text()
    block = re.search(r"authResponseHeaders:\n((?:\s*-\s*\S+\n)+)", text)
    assert block, "traefik authentik middleware must declare authResponseHeaders"
    listed = {h.lower() for h in re.findall(r"-\s*(X-authentik-[\w-]+)", block.group(1))}

    # jwt+entitlements are unused by any nOS backend so the Traefik list
    # legitimately omits them; identity + provenance headers MUST be present.
    required = [
        "x-authentik-username",
        "x-authentik-uid",
        "x-authentik-email",
        "x-authentik-name",
        "x-authentik-groups",
        "x-authentik-meta-app",
        "x-authentik-meta-outpost",
        "x-authentik-meta-provider",
    ]
    for hdr in required:
        assert hdr in listed, (
            f"traefik authResponseHeaders must list {hdr} (REM-047): "
            f"absent headers keep the client-sent value → identity forgery"
        )


def test_nginx_forward_auth_is_fail_closed():
    """PENTEST-002 companion: outpost 403/5xx must NOT route to @authentik_bypass,
    or the request reaches the backend with no X-authentik-* overwrite."""
    text = NGINX_CONF.read_text()
    assert "error_page 404 = @authentik_bypass" in text, (
        "only 404 may bypass; 401/403/5xx must fail closed"
    )
    assert not re.search(r"error_page[^\n]*\b(401|403|500|502|503)\b[^\n]*@authentik_bypass", text), (
        "auth/error codes must not route to @authentik_bypass (PENTEST-002)"
    )
