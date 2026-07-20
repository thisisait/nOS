"""HEALTHCHECK coverage ratchet (A1) — every compose service is gated by the STRICT wait.

nOS's STRICT bring-up wait (tasks/stacks/wait-stacks-healthy.yml +
files/anatomy/scripts/stack-health-probe.py) treats a container with NO health
status as "running == ready". A service whose image bakes no HEALTHCHECK and
whose compose template declares none is therefore health-blind: it can boot
broken and still pass the stack-up green gate (this once hid a dead dnsmasq for
a whole session — "green != working").

This offline gate pins the fix: every Docker-compose SERVICE across all role
compose templates must EITHER declare a `healthcheck:` block OR be listed in
HEALTH_BLIND below with a reason. A new service added without a healthcheck
fails this gate until it is fixed or deliberately allowlisted.

HEALTH_BLIND has two classes, both with real runtime justification:
  - BAKED   — the image already ships a HEALTHCHECK (verified via
              `docker inspect --format '{{.Config.Healthcheck.Test}}'`), so the
              container DOES have a runtime health state; a compose block would
              be redundant.
  - BLIND   — no safe probe exists (distroless image with no shell/curl/wget, a
              dual-mode entrypoint that legitimately idles, or an opt-in/parked
              heavy stack). A probe that always fails is WORSE than none — it
              would make the STRICT wait fail the whole stack — so these stay
              health-blind on purpose.

No docker / no network — pure template parse (repo-root via parents[2]).
"""
import glob
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Services we added a compose `healthcheck:` block to in A1. Kept explicit so a
# regression that drops one of these blocks fails loudly (not just silently
# re-classified as "new + unallowlisted").
FIXED = {
    "calibre-web": "curl /  (LSIO image ships curl; 302->/login is <400)",
    "homeassistant": "curl / (HA image ships curl+wget; onboarding/frontend 200)",
    "mcpo": "bash TCP :8000 (OpenAPI routes are --api-key gated; TCP is auth-independent)",
    "miniflux": "/usr/bin/miniflux -healthcheck auto (built-in; image has no curl)",
    "nextcloud": "curl /status.php (NC image ships curl)",
    "wordpress": "curl / (WP image ships curl; wp-cli not present in this image)",
    "infisical": "curl /api/status (image ships curl)",
    "qgis-server": "bash TCP :80 (kartoza image has bash, no curl/wget; WMS needs query params)",
    "freescout": "curl / (nfrastack image ships curl)",
    "superset": "curl /health (image ships curl)",
    "hedgedoc": "bash TCP :3000 (image has bash+node, no curl/wget)",
    "smtp_stalwart": "bash TCP :8080 (webadmin root can 401/redirect; TCP is protocol-agnostic)",
}

# Deliberately health-blind, with reason. Class prefix documents why.
HEALTH_BLIND = {
    # ── BAKED: image already ships a HEALTHCHECK (runtime health present) ──────
    "authentik-server": "BAKED: image bakes HEALTHCHECK `ak healthcheck` (worker overrides it in-compose)",
    "vaultwarden": "BAKED: image bakes HEALTHCHECK `/healthcheck.sh`",
    "uptime-kuma": "BAKED: image bakes HEALTHCHECK `extra/healthcheck`",
    "keap": "BAKED: image bakes HEALTHCHECK `wget /api/health` (built from source; see compose header)",
    "face": "BAKED: image bakes HEALTHCHECK on /health (SvelteKit adapter-node; built from source; see compose header)",
    "tileserver": "BAKED: image bakes HEALTHCHECK `node .../healthcheck.js`",
    "watchtower": "BAKED: image bakes HEALTHCHECK `/watchtower --health-check`",
    # ── BLIND: no safe probe (a guaranteed-failing probe would break the wait) ─
    "portainer": "BLIND: distroless image (no shell/curl/wget) and no health CLI",
    "mcp-grafana": "BLIND: optional SSE MCP sidecar, no published port / no documented health endpoint",
    "woodpecker-server": "BLIND: distroless Go image (no shell/curl/wget)",
    "woodpecker-agent": "BLIND: distroless Go image, headless (no HTTP surface)",
    "kiwix": "BLIND: dual-mode entrypoint idles (sleep infinity) when no ZIM present, so any probe would false-fail a no-content deploy and break the STRICT wait",
    "freepbx": "BLIND: vendor-abandoned image (REM-014/046/113), opt-in supervised voip stack",
    "erpnext-configurator": "BLIND: one-shot (restart:\"no\", exits 0) — a healthcheck on an exiting service is meaningless",
    "erpnext-backend": "BLIND: erpnext parked + excluded from all-on (heavy Frappe); worker has no HTTP surface",
    "erpnext-frontend": "BLIND: erpnext parked + excluded from all-on (heavy Frappe)",
    "erpnext-queue-short": "BLIND: erpnext parked + excluded from all-on; headless queue worker",
    "erpnext-queue-long": "BLIND: erpnext parked + excluded from all-on; headless queue worker",
    "erpnext-scheduler": "BLIND: erpnext parked + excluded from all-on; headless scheduler",
}

SERVICE_HDR = re.compile(r'^  ([A-Za-z0-9_.-]+):\s*$')
HC_LINE = re.compile(r'^    healthcheck:\s*$')
TOPLEVEL = re.compile(r'^[A-Za-z_]')


def _services(text):
    """Map service-name -> has_healthcheck for one compose template.

    Only 2-space keys UNDER the top-level `services:` block count as services;
    a subsequent column-0 key (e.g. `volumes:` / `networks:`) closes the section
    so a named volume is never mistaken for a service.
    """
    in_services = False
    cur = None
    out = {}
    for ln in text.splitlines():
        if re.match(r'^services:\s*$', ln):
            in_services = True
            continue
        if TOPLEVEL.match(ln) and not ln.startswith('services:'):
            in_services = False
            cur = None
            continue
        if not in_services:
            continue
        m = SERVICE_HDR.match(ln)
        if m:
            cur = m.group(1)
            out.setdefault(cur, False)
            continue
        if cur and HC_LINE.match(ln):
            out[cur] = True
    return out


def _all_services():
    """Every (role, service, has_hc) across all role compose templates."""
    for f in sorted(glob.glob(str(ROOT / "roles/pazny.*/templates/compose.yml.j2"))):
        role = pathlib.Path(f).parent.parent.name
        for svc, has_hc in _services(pathlib.Path(f).read_text()).items():
            yield role, svc, has_hc


def test_no_service_is_silently_health_blind():
    """Every compose service has a healthcheck OR is a documented allowlist entry."""
    offenders = []
    for role, svc, has_hc in _all_services():
        if has_hc:
            continue
        if svc in HEALTH_BLIND:
            continue
        offenders.append(f"{role}:{svc}")
    assert not offenders, (
        "Health-blind compose services (no healthcheck: block, not allowlisted) — "
        "add a HEALTHCHECK to the role's templates/compose.yml.j2, or add the service "
        "to HEALTH_BLIND in this file with a reason:\n  " + "\n  ".join(offenders)
    )


def test_fixed_services_keep_their_healthcheck():
    """The A1-added healthcheck blocks must not silently regress."""
    have_hc = {svc for _r, svc, hc in _all_services() if hc}
    missing = sorted(s for s in FIXED if s not in have_hc)
    assert not missing, (
        "A1 healthcheck block regressed (removed from compose template):\n  "
        + "\n  ".join(f"{s}  [{FIXED[s]}]" for s in missing)
    )


def test_allowlist_entries_are_actually_health_blind():
    """A service can't be both fixed-with-HC and allowlisted (stale allowlist guard)."""
    have_hc = {svc for _r, svc, hc in _all_services() if hc}
    stale = sorted(s for s in HEALTH_BLIND if s in have_hc)
    assert not stale, (
        "HEALTH_BLIND lists services that now DO declare a healthcheck: — "
        "drop them from the allowlist:\n  " + "\n  ".join(stale)
    )


def test_fixed_and_allowlist_disjoint():
    overlap = sorted(set(FIXED) & set(HEALTH_BLIND))
    assert not overlap, f"Services in both FIXED and HEALTH_BLIND: {overlap}"


def test_miniflux_healthcheck_is_db_aware():
    """miniflux's probe must hit a DB-dependent route, not /healthcheck.

    2026-07-20: Postgres was reinitialised at 05:25 while this container had
    been up since 22:08 the previous day, so miniflux alone missed the
    re-migration that every restarted service got — its schema was gone. The
    canonical upstream probe (`miniflux -healthcheck auto` → /healthcheck)
    answers from the HTTP layer and never touches Postgres, so the container
    reported `healthy` for 19 hours while every real request 500'd, and the
    STRICT health-wait passed it. "Green != working" — the probe must be able
    to see an empty schema.
    """
    tpl = (ROOT / "roles/pazny.miniflux/templates/compose.yml.j2").read_text()
    probe = next((ln for ln in tpl.splitlines() if ln.strip().startswith("test:")), "")
    assert probe, "miniflux must declare a healthcheck"
    assert "-healthcheck" not in probe, (
        "miniflux is back on the DB-blind upstream probe (`miniflux -healthcheck "
        "auto` → /healthcheck answers without touching Postgres)"
    )
    assert "8080/" in probe, "miniflux probe must request a DB-rendering route (/)"
