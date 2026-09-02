#!/usr/bin/env python3
"""nos-smoke.py — post-run web-UI smoke test for nOS.

Auto-derives one GET / per state/manifest.yml service that has a
domain_var, then layers state/smoke-catalog.yml on top (additions +
overrides). Runs each probe in parallel via a thread pool, prints a
table of pass/fail/warn results, exits with the count of failures
(0 = clean).

Usage:
  ./tools/nos-smoke.py                       # all enabled endpoints
  ./tools/nos-smoke.py --tier 1              # only Tier-1 (manifest-derived)
  ./tools/nos-smoke.py --tier 2              # only Tier-2 apps
  ./tools/nos-smoke.py --failed-only         # print only non-OK rows
  ./tools/nos-smoke.py --json                # JSONL on stdout (one event per line)
  ./tools/nos-smoke.py --jsonl ~/.nos/events/smoke.jsonl
  ./tools/nos-smoke.py --include auth,wing   # filter by id substring

The script reads the SAME variables Ansible reads (default.config.yml +
config.yml) so URLs match what the operator's environment expects. No
ansible runtime needed — pure Python + PyYAML.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import http.cookiejar
import pathlib
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required: pip3 install pyyaml\n")
    sys.exit(2)


REPO = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO / "tools"))
from nos_identity import resolve_flag  # noqa: E402

# Lazy ANSI colors — disabled when stdout isn't a TTY.
_TTY = sys.stdout.isatty()
COLOR = {
    "green":  "\033[32m" if _TTY else "",
    "red":    "\033[31m" if _TTY else "",
    "yellow": "\033[33m" if _TTY else "",
    "dim":    "\033[2m"  if _TTY else "",
    "reset":  "\033[0m"  if _TTY else "",
}


# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\|\s*default\(([^)]+)\)\s*)?\}\}")


def load_yaml(path: pathlib.Path) -> dict:
    """Lenient YAML loader — returns {} on missing file or parse error."""
    if not path.is_file():
        return {}
    try:
        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        sys.stderr.write("WARN: %s parse failed (%s) — skipping\n" % (path, exc))
        return {}


def merge_config(*paths: pathlib.Path) -> dict:
    """Layer YAML files in order — later wins. Mimics Ansible's vars_files."""
    out: dict = {}
    for p in paths:
        out.update(load_yaml(p))
    return out


def apply_runtime_estate(
    vars_dict: dict,
    config_path: pathlib.Path,
    state_path: pathlib.Path | None = None,
    manifest: dict | None = None,
) -> None:
    """Enablement comes from ~/.nos/state.yml — the run's resolved answer.

    config.yml cannot see a run's extra-vars, so `-e @profiles/<p>.yml` leaves it
    describing an estate that was not deployed. state.yml is written per run by
    pazny.state_manager and records what actually converged; probing anything
    else asks about services whose routes the same run removed.

    tld still falls back only when config.yml is absent; CLI --tenant-domain wins.

    The loop engine judges an EPHEMERAL worktree, which never contains the
    gitignored config.yml — so this script rendered `dev.local` while the
    estate served `pazny.eu` and every probe 404'd; with the tld fixed it
    still probed mailpit/superset, which the operator's config.yml disables
    (measured 2026-08-29, judge run 81dd74b6 and the worktree re-run after).
    The runtime sidecar is the estate's own resolved answer for both:
    `instance.tld` and `services.<id>.enabled`. CLI --tenant-domain and an
    operator checkout's config.yml still win.
    """
    state_path = state_path or pathlib.Path(os.path.expanduser("~/.nos/state.yml"))
    state = load_yaml(state_path)
    tld = str(((state.get("instance") or {}).get("tld") or "")).strip()
    if tld and not config_path.exists():
        vars_dict["tenant_domain"] = tld
    services = state.get("services") or {}
    if not services:
        return
    # id → install flag, from the committed manifest (present in any worktree).
    flags = {
        s.get("id"): s.get("install_flag")
        for s in (manifest or {}).get("services", [])
        if s.get("install_flag")
    }
    for sid, body in services.items():
        enabled = (body or {}).get("enabled")
        if enabled is None:
            continue
        # Unconditional: state.yml is the run's resolved answer, so a flag it
        # names but no vars_file declares must still be settable.
        vars_dict[flags.get(sid) or f"install_{sid}"] = bool(enabled)


def resolve_jinja_lite(text: str, vars_dict: dict, depth: int = 0) -> str:
    """Resolve `{{ var }}` and `{{ var | default('x') }}` against vars_dict.

    Intentionally narrow — full Jinja2 would mean shipping Jinja2 + render
    pipeline. The smoke catalog only uses simple ``{{ name }}`` and
    ``{{ name | default('foo') }}`` patterns. Other ``|`` filters fail loud.
    """
    if depth > 10:
        return text  # arbitrary recursion ceiling

    def repl(match: re.Match) -> str:
        name = match.group(1)
        default = match.group(2)
        val = vars_dict.get(name)
        if val is None and default is not None:
            # default("x") / default('x')
            d = default.strip().strip("\"'")
            return d
        if val is None:
            return ""  # leave empty rather than literal {{ name }}
        return str(val)

    out = _VAR_RE.sub(repl, text)
    return resolve_jinja_lite(out, vars_dict, depth + 1) if "{{" in out else out


def evaluate_when(expr: str | None, vars_dict: dict) -> bool:
    """Evaluate a `when:` expression. Truth-y if any of:
    - empty / None / 'true'
    - matches "<name> | default(true)" → reads vars_dict[name] (default true)
    - matches "<name>" → reads vars_dict[name] truthiness
    Anything more complex falls back to True (won't accidentally drop the
    entry — runner over-reports rather than under-reports).
    """
    if not expr:
        return True
    s = expr.strip()
    if s.lower() in ("true", "yes", "1"):
        return True
    if s.lower() in ("false", "no", "0"):
        return False
    # Match: <name> | default(<true|false>)
    m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*\|\s*default\(\s*(true|false|True|False)\s*\)\s*$", s)
    if m:
        name, dflt = m.group(1), m.group(2).lower() == "true"
        v = vars_dict.get(name)
        if v is None:
            return dflt
        return bool(v)
    # Plain bareword
    m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)$", s)
    if m:
        return bool(vars_dict.get(m.group(1), False))
    # Anything else — be permissive, default to True
    return True


# ---------------------------------------------------------------------------
# Catalog assembly
# ---------------------------------------------------------------------------

def unrouted_ids(repo: pathlib.Path) -> set:
    """Service ids for which Traefik renders no router, so the edge 404s.

    Measured 2026-08-05: `traefik` smoked ❌ on a converge that was otherwise
    green, and it was correct to. REM-144's remediation is "take the dashboard
    off the edge", so `services.yml.j2` derives no router and
    `https://traefik.<tld>/` is a 404 BY DESIGN. The probe was asking a question
    we had already answered by changing the routing, and the same is true of
    bone and cortex.

    A check that is permanently red is one an operator learns to skip past —
    and the habit does not distinguish it from the next red thing.
    """
    data = load_yaml(repo / "roles/pazny.traefik/vars/main.yml")
    return set(data.get("traefik_skip_ids") or [])


def _loopback_probe(s: dict, vars_dict: dict) -> "tuple[str, list] | None":
    """The manifest's own answer to 'how do you health-check this service'.

    `health_check.url_template` is authored per service; only its PATH is taken.
    MEASURED 2026-09-01: `cortex_port` lives in a role default, this tool read
    two layers, so the cortex probe returned None and derive_from_manifest
    dropped it — silently, for as long as the row existed. Role defaults are a
    real layer (nos_identity.resolve_flag); an unresolvable port now SAYS so.
    """
    hc = s.get("health_check") or {}
    tpl = hc.get("url_template") or ""
    port_var = s.get("port_var")
    if not tpl or not port_var:
        return None
    port = vars_dict.get(port_var) or next(
        (v for _, v in reversed(resolve_flag(port_var))), None)
    if not port:
        print(f"DROPPED {s.get('id')}: {port_var} resolves in no config layer "
              f"(roles/*/defaults, default.config.yml, config.yml)", file=sys.stderr)
        return None
    path = tpl.split("}}")[-1] if "}}" in tpl else "/"
    expect = hc.get("expect_status", 200)
    return f"http://127.0.0.1:{port}{path}", [expect]


def flag_enabled(flag: str, vars_dict: dict, sid: str) -> bool:
    """Enabled? Absent from vars_dict is not the same answer as false.

    vars_dict holds two layers; role defaults are the third, and the manifest
    gate accepts a flag declared only there. Such a flag read as false and its
    probe vanished. Unresolvable in ALL three now SAYS so, like a dropped port.
    """
    if flag in vars_dict:
        return bool(vars_dict[flag])
    layers = resolve_flag(flag)
    if not layers:
        print(f"DROPPED {sid}: {flag} resolves in no config layer "
              f"(roles/*/defaults, default.config.yml, config.yml)", file=sys.stderr)
        return False
    return layers[-1][1] not in ("false", "no")


def derive_from_manifest(manifest: dict, vars_dict: dict, defaults: dict,
                         skip_ids: set | None = None) -> list[dict]:
    """Auto-derive one GET / probe per manifest service with domain_var."""
    out = []
    skip_ids = skip_ids or set()
    for s in manifest.get("services", []):
        if "domain_var" not in s:
            continue
        flag = s.get("install_flag")
        if flag and not flag_enabled(flag, vars_dict, s["id"]):
            continue
        domain = vars_dict.get(s["domain_var"])
        if not domain:
            continue
        url = f"https://{domain}/"
        expect_override = None
        if s["id"] in skip_ids:
            probe = _loopback_probe(s, vars_dict)
            if probe is None:
                # Unrouted AND no authored probe: there is nothing honest to
                # ask. Dropping it is deliberate — see unrouted_ids().
                continue
            url, expect_override = probe
        out.append({
            "id": s["id"],
            "url": url,
            # A loopback health endpoint answers with its declared status or it
            # has not answered; the edge list keeps 301/302/308 because a
            # redirect there proves the router is alive, which is the point.
            "expect": expect_override or defaults.get("expect", [200, 301, 302, 308]),
            "timeout": defaults.get("timeout", 5),
            "tier": 1,
            "note": f"manifest auto: {s.get('category','-')}/{s.get('stack','-')}",
            "_source": "manifest",
        })
    return out


def merge_catalog(manifest_entries: list[dict], extra_entries: list[dict],
                  defaults: dict, vars_dict: dict) -> list[dict]:
    """Catalog = manifest auto-derived + smoke-catalog.yml. Extra entries
    REPLACE manifest entries when ids collide (operator override path).
    """
    by_id: dict[str, dict] = {e["id"]: e for e in manifest_entries}
    for e in extra_entries or []:
        e = dict(e)
        e.setdefault("expect", defaults.get("expect", [200, 301, 302, 308]))
        e.setdefault("timeout", defaults.get("timeout", 5))
        e.setdefault("tier", defaults.get("tier", 3))
        e["_source"] = "catalog"
        if "when" in e and not evaluate_when(e["when"], vars_dict):
            continue
        # resolve Jinja in url
        e["url"] = resolve_jinja_lite(e["url"], vars_dict)
        by_id[e["id"]] = e
    return sorted(by_id.values(), key=lambda x: (x["tier"], x["id"]))


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

class ProbeResult:
    __slots__ = ("entry", "status", "duration_ms", "error", "ok")

    def __init__(self, entry, status, duration_ms, error, ok):
        self.entry = entry
        self.status = status
        self.duration_ms = duration_ms
        self.error = error
        self.ok = ok


def _make_ssl_context(insecure: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _try_authentik_login(opener, authentik_domain: str, tester_user: str,
                         tester_password: str, ctx: ssl.SSLContext,
                         timeout: float) -> tuple[bool, str | None]:
    """Submit tester credentials via Authentik flow executor API.

    Authentik exposes ``/api/v3/flows/executor/<slug>/?query=`` for headless
    auth — POST a JSON body with the username (identification stage) then a
    second POST with the password (password stage). On success the cookie
    jar attached to ``opener`` carries the session, and any subsequent GET
    against a forward_auth-protected service should return 200.

    Returns (success, error_message).
    """
    # Default flow slug for Authentik 2024.2+: 'default-authentication-flow'.
    # Could be overridden via env later.
    flow_slug = "default-authentication-flow"
    base = "https://%s/api/v3/flows/executor/%s/" % (authentik_domain, flow_slug)
    headers_common = {
        "User-Agent": "nos-smoke/1.0 (auth-flow)",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    def _post(url: str, body: dict) -> tuple[int | None, dict | None, str | None]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        for k, v in headers_common.items():
            req.add_header(k, v)
        try:
            with opener.open(req, timeout=timeout, context=ctx) as resp:
                txt = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(txt) if txt else None, None
        except urllib.error.HTTPError as exc:
            txt = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(txt), None
            except Exception:
                return exc.code, None, txt[:200]
        except Exception as exc:  # noqa: BLE001
            return None, None, type(exc).__name__ + ": " + str(exc)

    # Stage 1: prime the flow (GET so the executor sets initial cookies).
    try:
        req = urllib.request.Request(base, method="GET")
        req.add_header("User-Agent", "nos-smoke/1.0 (auth-flow)")
        opener.open(req, timeout=timeout, context=ctx).read()
    except Exception:  # noqa: BLE001
        pass  # not fatal — POST may still work

    # Stage 2: identification (username).
    code, body, err = _post(base, {"uid_field": tester_user})
    if err:
        return False, "auth identification: %s" % err
    if code and code >= 400:
        return False, "auth identification HTTP %s" % code

    # Stage 3: password.
    code, body, err = _post(base, {"password": tester_password})
    if err:
        return False, "auth password: %s" % err
    if code and code >= 400:
        return False, "auth password HTTP %s" % code

    # Authentik returns the next stage in the body. A successful login lands
    # on type=redirect (back to source app) or type=ak-stage-access-denied etc.
    if isinstance(body, dict):
        comp = body.get("component", "")
        if "access-denied" in comp or "deny" in comp:
            return False, "auth flow ended: %s" % comp
    return True, None


# ── loopback fallback ────────────────────────────────────────────────────────
# A probe must fail when the SERVICE is broken, not when the host lacks a DNS
# entry the platform is not supposed to have. See the call site for the full
# reasoning; keep these three helpers together.

def _is_name_resolution_error(exc) -> bool:
    reason = getattr(exc, "reason", exc)
    text = str(reason)
    return (
        getattr(reason, "errno", None) in (-2, -3, -5)
        or "Name or service not known" in text
        or "nodename nor servname" in text
        or "Temporary failure in name resolution" in text
    )


# The tenant's own namespace. Set once from the resolved tenant_domain; the
# loopback retry below is allowed inside it and nowhere else.
_TENANT_SUFFIX = ""


def set_tenant_suffix(domain: str) -> None:
    global _TENANT_SUFFIX
    _TENANT_SUFFIX = (domain or "").strip().lstrip(".").lower()


def _loopback_ok(url: str) -> bool:
    """Names we expect the LOCAL EDGE to serve — never an arbitrary public host.

    The original rule was `.local`/`.test`/`.lan`, on the reasoning that a probe
    for a public name must not be answered by our own loopback and called
    healthy. That reasoning is right and the rule was too narrow: an operator
    running a PUBLIC tenant domain (pazny.eu here) serves the entire estate from
    the local Traefik under that domain, so the retry was disabled for every
    service on the host.

    The consequence, measured 2026-08-05: a transient DNS failure became a hard
    `DEAD` with no second look. `paperclip` smoked DEAD at 10ms on the converge
    while its container was healthy for 11 days and Uptime Kuma had 40
    consecutive successes — and `portainer` did the identical thing minutes
    later, `URLError: nodename nor servname provided` at 23ms. That is a
    resolver blip being reported as a dead service, which is the fastest way to
    teach an operator that the smoke table is noise.

    So the guard is now the TENANT'S OWN namespace, which is precise: these are
    the names this host is supposed to serve. Anything outside it still gets no
    loopback retry.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host.endswith(".local") or host.endswith(".test") or host.endswith(".lan"):
        return True
    return bool(_TENANT_SUFFIX) and (
        host == _TENANT_SUFFIX or host.endswith("." + _TENANT_SUFFIX))


def _probe_via_loopback(url, ctx, timeout, method):
    """Same request, sent to 127.0.0.1 with the original Host header."""
    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    direct = urllib.parse.urlunsplit(
        (parts.scheme, "127.0.0.1:%d" % port, parts.path or "/", parts.query, ""))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(direct, method=method)
    req.add_header("Host", parts.hostname or "")
    req.add_header("User-Agent", "nos-smoke/1.0 (loopback)")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__ + ": " + str(exc)


def _secret(name: str) -> str | None:
    """A value from ~/.nos/secrets.yml, or None. Never from the catalog itself."""
    path = pathlib.Path.home() / ".nos/secrets.yml"
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:                                            # noqa: BLE001
        return None
    value = data.get(name)
    return str(value) if value else None


def _dotted(data, path: str):
    """`data.stages[0].result.rows` → the value, or None if any hop is missing."""
    cur = data
    for part in path.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            if not part.isdigit() or int(part) >= len(cur):
                return None
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _probe_api(entry: dict, ctx, timeout: float) -> tuple[int | None, str | None, str | None]:
    """POST + bearer + a truthiness assertion on the parsed answer.

    Returns (status, transport_error, assertion_failure). A failed assertion
    reports the status it really got AND why that status was not enough, because
    "200 but the pipe was dead" is the case this probe was added for.
    """
    url = entry["url"]
    body = json.dumps(entry.get("body") or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "nos-smoke/1.0")

    for header, secret in (entry.get("bearer_secret") and
                           [("Authorization", entry["bearer_secret"])] or []):
        value = _secret(secret)
        if not value:
            return None, f"secret '{secret}' not in ~/.nos/secrets.yml", None
        req.add_header(header, f"Bearer {value}")
    for header, secret in (entry.get("header_secrets") or {}).items():
        value = _secret(secret)
        if not value:
            return None, f"secret '{secret}' not in ~/.nos/secrets.yml", None
        req.add_header(header, value)

    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=timeout) as resp:
            status, payload = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, None, None
    except (urllib.error.URLError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}", None

    require = entry.get("require_json")
    if not require:
        return status, None, None
    try:
        parsed = json.loads(payload.decode("utf-8", "replace"))
    except ValueError:
        return status, None, "response was not JSON, so require_json could not be checked"
    value = _dotted(parsed, require)
    if value is None or value is False or value == [] or value == 0:
        return status, None, (
            f"{status} but `{require}` is {value!r} — the surface answered and "
            "did nothing, which is the case this probe exists to catch"
        )
    return status, None, None


def probe(entry: dict, *, strict: bool = False, tester_user: str | None = None,
          tester_password: str | None = None,
          authentik_domain: str | None = None) -> ProbeResult:
    """Single HEAD/GET probe. Falls back to GET if HEAD returns 405.

    In strict mode (``strict=True``) the default expected status set tightens
    to [200, 204] and 30x answers fail unless the entry declares
    ``auth: tester`` and the tester auth flow successfully follows the
    redirect chain to a final 200.
    """
    url = entry["url"]
    timeout = float(entry.get("timeout", 5))
    auth_mode = entry.get("auth", "anon")

    # Pick expect set based on strict mode + entry override.
    explicit = entry.get("expect")
    explicit_strict = entry.get("expect_strict")
    if strict:
        expect = explicit_strict if explicit_strict is not None else (
            explicit if explicit is not None else [200, 204]
        )
    else:
        expect = explicit if explicit is not None else [200, 301, 302, 308]
    if isinstance(expect, int):
        expect = [expect]
    expect = set(expect or [200])

    ctx = _make_ssl_context(entry.get("insecure", True))
    started = time.monotonic()

    # ── An API probe: POST a body, carry a bearer, read the answer ──────────
    #
    # WHY THIS EXISTS. Until 2026-08-11 every catalog entry was a GET whose only
    # verdict was a status code, so a surface that answers 200 while doing
    # nothing smoked green. The cortex executor is exactly that shape: it is
    # POST-only, bearer-gated, and its interesting failure is `200 with every
    # stage absent` — a chain that parsed, dispatched and read nothing. An
    # adversarial review found it had NO smoke entry at all, so the release gate
    # would have tagged around the week's flagship feature without calling it.
    #
    # `require_json` is a dotted path into the response that must be TRUTHY and,
    # for a list, non-empty. Deliberately not an expression language: a probe
    # that can compute is a probe whose verdict needs its own review.
    #
    # `bearer_secret` names a key in ~/.nos/secrets.yml rather than carrying a
    # value, so the catalog stays committable.
    if entry.get("method", "GET").upper() == "POST":
        status, err, detail = _probe_api(entry, ctx, timeout)
        elapsed = (time.monotonic() - started) * 1000
        # `ok` is the AND of both questions: did it answer with an accepted
        # status, and did the answer contain what the entry requires. A probe
        # that stopped at the status is the probe this entry exists to replace.
        return ProbeResult(entry=entry, status=status, duration_ms=elapsed,
                           error=err or detail,
                           ok=(err is None and detail is None and status in expect))

    # ── Anon path: simple HEAD/GET ─────────────────────────────────────────
    # Redirect-loop detection: urllib.request.urlopen follows redirects up to
    # 10 hops by default. For our smoke, an honest service should land on a
    # 200/30x within 1-2 hops; chains of 3+ identical Location headers signal
    # the classic CF Flexible-SSL trap (CF→origin via HTTP, origin redirects
    # to HTTPS, CF re-serves that 308, browser loops). Catch it explicitly so
    # the smoke output points the operator at the actual root cause instead
    # of a generic timeout. See docs/operator-domain-switch.md "Troubleshooting".
    # An autologin / forward_auth service bounces the anon probe to the
    # Authentik IdP (/ -> /login -> auth.<tld>/application/o/authorize -> the
    # MFA flow). That chain legitimately exceeds the hop cap, so once
    # sso_autologin is on every SSO-redirecting service smokes DEAD. Treat
    # "redirected to Authentik" as ALIVE — the service is up and correctly
    # delegating to SSO. Detect via the auth domain (when known) or the
    # unmistakable Authentik path markers.
    _auth_markers = ("/application/o/authorize", "/outpost.goauthentik.io", "/if/flow/")

    def _is_auth_redirect(loc: str) -> bool:
        if authentik_domain and authentik_domain in loc:
            return True
        return any(m in loc for m in _auth_markers)

    class _RedirectedToAuth(Exception):
        """Sentinel: the probe was bounced to the SSO IdP (service is alive)."""

    def _do_simple(method: str) -> tuple[int | None, str | None]:
        # Build a custom redirect handler that records every Location header
        # seen and bails when we hit the same URL twice in a row (loop) or
        # exceed our cap of 5 hops (longer than any legitimate auth flow).
        seen_locations: list[str] = []
        max_redirs = 5

        class _LoopAwareRedirect(urllib.request.HTTPRedirectHandler):
            def http_error_302(self, req, fp, code, msg, headers):
                loc = headers.get("location") or headers.get("Location") or ""
                if loc:
                    if _is_auth_redirect(loc):
                        raise _RedirectedToAuth(loc)
                    if seen_locations and seen_locations[-1] == loc:
                        raise urllib.error.URLError(
                            "redirect loop detected: %d hops to %s "
                            "(see docs/operator-domain-switch.md — likely "
                            "CF Flexible SSL; switch to Full (strict))"
                            % (len(seen_locations) + 1, loc)
                        )
                    seen_locations.append(loc)
                    if len(seen_locations) > max_redirs:
                        raise urllib.error.URLError(
                            "exceeded %d redirects (last: %s)"
                            % (max_redirs, loc)
                        )
                return super().http_error_302(req, fp, code, msg, headers)
            http_error_301 = http_error_302
            http_error_303 = http_error_302
            http_error_307 = http_error_302
            http_error_308 = http_error_302

        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            _LoopAwareRedirect(),
        )
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "nos-smoke/1.0")
        try:
            with opener.open(req, timeout=timeout) as resp:
                return resp.status, None
        except _RedirectedToAuth:
            # Alive: bounced to the SSO IdP. 302 is in the non-strict expect
            # set; strict mode still wants `auth: tester` to follow to 200.
            return 302, None
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except urllib.error.URLError as exc:
            # No resolver for the tenant domain (Linux has no /etc/resolver —
            # that mechanism is macOS-only, tasks/dnsmasq.yml), so a DNS-based
            # probe measures a layer the platform never provides and reports a
            # healthy estate as dead. Retry against the loopback edge with the
            # Host header the router keys on: that tests the thing we actually
            # care about (does the reverse proxy route this service?) instead
            # of name resolution. Labelled distinctly so a run that never
            # exercised DNS cannot be mistaken for one that did.
            if _is_name_resolution_error(exc) and _loopback_ok(url):
                status, direct_err = _probe_via_loopback(url, ctx, timeout, method)
                if status is not None:
                    return status, None
                return None, "URLError: %s (loopback retry: %s)" % (
                    exc.reason, direct_err)
            return None, "URLError: %s" % exc.reason
        except Exception as exc:  # noqa: BLE001
            return None, type(exc).__name__ + ": " + str(exc)

    if auth_mode in ("anon", "none", None) or not (tester_user and tester_password):
        # No tester credentials available, or entry doesn't ask for auth.
        # In strict mode without auth, 30x is a failure — caller has chance
        # to label this entry `auth: tester` and supply credentials.
        code, err = _do_simple("HEAD")
        if code == 405:
            code, err = _do_simple("GET")
        if strict and auth_mode == "tester" and not (tester_user and tester_password):
            err = err or "auth: tester requested but no --tester-user/--tester-password"
        duration_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(entry, code, duration_ms, err, code in expect)

    # ── Auth path: cookie-jar Session + Authentik flow executor ────────────
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx),
    )
    opener.addheaders = [("User-Agent", "nos-smoke/1.0 (tester)")]

    # 1. First request — may return 200 (already-public health endpoint) or
    #    302 to Authentik. We follow up to 5 redirects manually so we can
    #    detect when we land on the auth flow page.
    final_code: int | None = None
    err: str | None = None
    cur = url
    for _ in range(5):
        try:
            req = urllib.request.Request(cur, method="GET")
            with opener.open(req, timeout=timeout, context=ctx) as resp:
                final_code = resp.status
                final_url = resp.geturl()
                break
        except urllib.error.HTTPError as exc:
            final_code = exc.code
            final_url = cur
            break
        except Exception as exc:  # noqa: BLE001
            err = type(exc).__name__ + ": " + str(exc)
            final_code = None
            final_url = cur
            break

    # 2. If we ended up on Authentik (anywhere under auth.<tld>), perform
    #    the headless flow then re-fetch the original URL with the cookie.
    auth_used = False
    if final_code in (200, 401) and authentik_domain and authentik_domain in (final_url or ""):
        ok_auth, auth_err = _try_authentik_login(
            opener, authentik_domain, tester_user, tester_password, ctx, timeout
        )
        auth_used = True
        if not ok_auth:
            err = auth_err
        else:
            # Re-fetch original URL with the auth session cookie.
            try:
                req = urllib.request.Request(url, method="GET")
                with opener.open(req, timeout=timeout, context=ctx) as resp:
                    final_code = resp.status
            except urllib.error.HTTPError as exc:
                final_code = exc.code
            except Exception as exc:  # noqa: BLE001
                err = type(exc).__name__ + ": " + str(exc)
                final_code = None

    duration_ms = int((time.monotonic() - started) * 1000)
    ok = final_code in expect
    if auth_used and not err:
        # Annotate the entry's note for the table render — the operator can
        # see at a glance which probes actually went through the auth flow.
        entry = dict(entry)
        entry["_auth_used"] = True
    return ProbeResult(entry, final_code, duration_ms, err, ok)


# ---------------------------------------------------------------------------
# Render output
# ---------------------------------------------------------------------------

def render_table(results: list[ProbeResult], failed_only: bool = False) -> str:
    """Pretty-print a results table."""
    rows = []
    rows.append(("ID", "URL", "EXPECT", "GOT", "MS", "RESULT"))
    width = [len(c) for c in rows[0]]
    body = []
    for r in results:
        if failed_only and r.ok:
            continue
        e = r.entry
        expect_str = ",".join(str(x) for x in (e["expect"] if isinstance(e["expect"], list) else [e["expect"]]))
        got = str(r.status) if r.status is not None else "UNREACH"
        flag = "✅" if r.ok else "❌"
        row = (
            e["id"],
            e["url"][:60],
            expect_str,
            got,
            str(r.duration_ms),
            "%s %s" % (flag, "OK" if r.ok else (r.error or "FAIL")),
        )
        body.append(row)
        for i, cell in enumerate(row):
            width[i] = max(width[i], len(cell))
    out = []
    fmt = "  ".join("{:<%d}" % w for w in width)
    out.append(fmt.format(*rows[0]))
    out.append(fmt.format(*("-" * w for w in width)))
    for row in body:
        line = fmt.format(*row)
        if "❌" in row[5]:
            line = COLOR["red"] + line + COLOR["reset"]
        elif "✅" in row[5]:
            line = COLOR["green"] + line + COLOR["reset"]
        out.append(line)
    return "\n".join(out)


def emit_jsonl(path: pathlib.Path, run_id: str, results: list[ProbeResult]) -> None:
    """Append one JSON object per result to the JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", encoding="utf-8") as fh:
        for r in results:
            obj = {
                "ts": ts,
                "run_id": run_id,
                "type": "smoke_result",
                "id": r.entry["id"],
                "url": r.entry["url"],
                "expect": r.entry["expect"],
                "status": r.status,
                "duration_ms": r.duration_ms,
                "ok": r.ok,
                "error": r.error,
                "tier": r.entry.get("tier", 3),
            }
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tier", type=int, choices=[1, 2, 3], help="filter by tier")
    p.add_argument("--include", help="comma-separated id substrings")
    p.add_argument("--failed-only", action="store_true",
                   help="show only non-OK rows in stdout table")
    p.add_argument("--json", action="store_true",
                   help="JSONL on stdout (one event per line, no table)")
    p.add_argument("--jsonl", type=pathlib.Path, default=None,
                   help="append JSONL events to this path (default: ~/.nos/events/smoke.jsonl when --jsonl is unset, OR --no-jsonl to disable)")
    p.add_argument("--no-jsonl", action="store_true",
                   help="disable JSONL output")
    p.add_argument("--workers", type=int, default=20,
                   help="parallel probe workers (default 20)")
    # ── Track F: ad-hoc Ansible -e overrides that this subprocess otherwise
    # doesn't see (the YAML files are the only var source). Operators running
    # `ansible-playbook -K -e blank=true -e host_alias=lab` need smoke to
    # pick up host_alias=lab so the URLs probe the right hosts.
    p.add_argument("--host-alias", dest="host_alias", default=None,
                   help="override host_alias from YAML (mirrors -e host_alias=...)")
    p.add_argument("--tenant-domain", dest="tenant_domain", default=None,
                   help="override tenant_domain from YAML (mirrors -e tenant_domain=...)")
    p.add_argument("--apps-subdomain", dest="apps_subdomain", default=None,
                   help="override apps_subdomain from YAML")
    # ── Track G: strict mode + tester credentials ──────────────────────────
    # Strict mode tightens default expect to [200, 204] and treats any 30x
    # without a successful tester auth-flow as failure (per AIT philosophy:
    # 30x alone is not proof a service works for an authorized user).
    p.add_argument("--strict", action="store_true",
                   help="strict mode — expect [200,204] only; 30x must auth-flow to 200")
    p.add_argument("--tester-user", dest="tester_user", default=None,
                   help="override tester username (mirrors nos_tester_username)")
    p.add_argument("--tester-password", dest="tester_password", default=None,
                   help="override tester password (mirrors nos_tester_password)")
    p.add_argument("--authentik-domain", dest="authentik_domain", default=None,
                   help="override authentik_domain — needed only when auth flow runs")
    p.add_argument("--fail-ratio", dest="fail_ratio", type=float, default=None,
                   help="systemic-failure gate: exit 1 iff (failed/total) >= this "
                        "ratio, else 0 — used as a release gate that fails a run "
                        "when the platform is broadly unreachable (e.g. local DNS "
                        "down = ~all DEAD) while tolerating a few flaky probes. "
                        "When unset, exit code is the raw failed count (min 127).")
    args = p.parse_args()

    # ── Load Ansible-style variables ───────────────────────────────────────
    vars_dict = merge_config(
        REPO / "default.config.yml",
        REPO / "config.yml",      # gitignored operator override
    )
    apply_runtime_estate(
        vars_dict, REPO / "config.yml",
        manifest=load_yaml(REPO / "state" / "manifest.yml"),
    )

    # ── Track F: apply CLI overrides BEFORE helper computation ───────────────
    # These mirror Ansible -e flags. Without them, the subprocess can't see
    # the operator's per-blank overrides (host_alias=lab etc.) and probes
    # the wrong hosts. nos_smoke_strict=true then fails the playbook for
    # what is fundamentally a smoke-config drift.
    if args.host_alias is not None:
        vars_dict["host_alias"] = args.host_alias
    if args.tenant_domain is not None:
        vars_dict["tenant_domain"] = args.tenant_domain
    if args.apps_subdomain is not None:
        vars_dict["apps_subdomain"] = args.apps_subdomain

    # ── Track F: pre-compute domain composition helpers ──────────────────────
    # default.config.yml defines `_host_alias_seg`, `_host_alias_normalized`,
    # and `_acme_zone` via Jinja expressions with conditionals + length filters
    # (e.g. `{{ '.' + x if (x | length > 0) else '' }}`) that the lightweight
    # resolver below cannot parse. If we leave them as raw Jinja strings, the
    # downstream `<svc>_domain` lookup expands them via lite-resolver to the
    # raw text — producing literal '{{...}}' in URLs that curl rejects with
    # 'InvalidURL: control characters'. Pre-computing them here as concrete
    # values keeps the resolver narrow while honouring host_alias.
    _host_alias_raw = vars_dict.get("host_alias", "") or ""
    if not isinstance(_host_alias_raw, str):
        _host_alias_raw = ""
    _host_alias_norm = _host_alias_raw.strip(".")
    vars_dict["_host_alias_normalized"] = _host_alias_norm
    vars_dict["_host_alias_seg"] = f".{_host_alias_norm}" if _host_alias_norm else ""

    _tenant_domain_raw = vars_dict.get("tenant_domain", "dev.local") or "dev.local"
    # Names under the tenant domain are served by THIS host's edge, so a DNS
    # blip on one of them earns a loopback retry rather than a DEAD verdict.
    set_tenant_suffix(_tenant_domain_raw)
    _acme_zone = (
        f"{_host_alias_norm}.{_tenant_domain_raw}" if _host_alias_norm
        else _tenant_domain_raw
    )
    vars_dict["_acme_zone"] = _acme_zone

    _apps_subdomain_raw = vars_dict.get("apps_subdomain", "apps") or "apps"
    if not isinstance(_apps_subdomain_raw, str):
        _apps_subdomain_raw = "apps"
    vars_dict["_apps_subdomain_normalized"] = _apps_subdomain_raw.strip(".")

    # Self-substitute Jinja inside vars (e.g. wing_domain: "wing.{{ tenant_domain }}")
    for k, v in list(vars_dict.items()):
        if isinstance(v, str) and "{{" in v:
            vars_dict[k] = resolve_jinja_lite(v, vars_dict)

    # ── Load manifest + smoke catalog (static + runtime) ───────────────────
    # state/smoke-catalog.yml         — checked-in, edited by humans
    # state/smoke-catalog.runtime.yml — auto-written by pazny.apps_runner
    #                                   tasks/post.yml; one entry per Tier-2
    #                                   apps/<name>.yml manifest. Same shape
    #                                   as the static catalog so this loader
    #                                   stays simple. Missing file = no-op.
    manifest = load_yaml(REPO / "state" / "manifest.yml")
    catalog = load_yaml(REPO / "state" / "smoke-catalog.yml")

    defaults = catalog.get("smoke_defaults") or {}
    extras = list(catalog.get("smoke_endpoints") or [])

    runtime_path = REPO / "state" / "smoke-catalog.runtime.yml"
    if runtime_path.is_file():
        runtime_catalog = load_yaml(runtime_path)
        runtime_extras = runtime_catalog.get("smoke_endpoints") or []
        # Append after the static entries so static IDs win on duplicate keys
        # (matching the same precedence rule merge_catalog applies to manifest
        # vs. catalog entries — last-writer-wins becomes first-wins via the
        # merge_catalog dedup logic).
        extras = extras + list(runtime_extras)

    manifest_entries = derive_from_manifest(
        manifest, vars_dict, defaults, skip_ids=unrouted_ids(REPO))
    all_entries = merge_catalog(manifest_entries, extras, defaults, vars_dict)

    # ── Filters ────────────────────────────────────────────────────────────
    if args.tier:
        all_entries = [e for e in all_entries if e.get("tier") == args.tier]
    if args.include:
        needles = [s.strip() for s in args.include.split(",") if s.strip()]
        all_entries = [e for e in all_entries if any(n in e["id"] for n in needles)]

    if not all_entries:
        sys.stderr.write("smoke catalog yielded zero entries (check filters / install_* flags)\n")
        return 0

    # ── Tester credentials & strict mode resolution ────────────────────────
    # Prefer CLI overrides; fall back to YAML; allow either to be missing
    # (auth-flow entries simply won't auth-flow if credentials are absent —
    # they'll fall back to anon and the strict-mode check will catch the 30x).
    tester_user = args.tester_user or vars_dict.get("nos_tester_username") or "nos-tester"
    tester_password = args.tester_password or vars_dict.get("nos_tester_password")
    authentik_domain = (
        args.authentik_domain
        or vars_dict.get("authentik_domain")
        or "auth%s.%s" % (vars_dict.get("_host_alias_seg", ""), vars_dict.get("tenant_domain", "dev.local"))
    )

    def _probe_one(e):
        return probe(
            e,
            strict=args.strict,
            tester_user=tester_user,
            tester_password=tester_password,
            authentik_domain=authentik_domain,
        )

    # ── Run probes in parallel ─────────────────────────────────────────────
    run_id = "smoke_" + datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_probe_one, all_entries))

    # ── Output ─────────────────────────────────────────────────────────────
    if args.json:
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for r in results:
            print(json.dumps({
                "ts": ts, "run_id": run_id, "type": "smoke_result",
                "id": r.entry["id"], "url": r.entry["url"],
                "expect": r.entry["expect"], "status": r.status,
                "duration_ms": r.duration_ms, "ok": r.ok, "error": r.error,
                "tier": r.entry.get("tier", 3),
            }, ensure_ascii=False))
    else:
        print(render_table(results, failed_only=args.failed_only))
        ok = sum(1 for r in results if r.ok)
        # A probe that got no answer at all is UNREACHABLE, not a service that
        # answered wrongly. From the host those look identical and are not:
        # Docker's forwarder fails while every service is healthy (fee 43).
        unreach = sum(1 for r in results if not r.ok and r.status is None)
        bad = len(results) - ok - unreach
        print()
        summary = "%d / %d OK  ·  %d failed  ·  %d unreachable" % (
            ok, len(results), bad, unreach)
        if bad == 0 and unreach == 0:
            print(COLOR["green"] + "✅ " + summary + COLOR["reset"])
        else:
            print(COLOR["red"] + "❌ " + summary + COLOR["reset"])
        if unreach and not bad:
            print(COLOR["red"] + "   NOTHING ANSWERED on %d probe(s) — no service "
                  "reported a status, so this is a TRANSPORT verdict, not %d "
                  "broken services." % (unreach, unreach) + COLOR["reset"])
            print("   Ask a container before believing the host (fee 43):")
            print("     docker exec devops-gitea-1 curl -sk -o /dev/null -w '%{http_code}\\n' \\")
            print("       -H 'Host: <domain>' https://infra-traefik-1/")

    # ── JSONL persistence ──────────────────────────────────────────────────
    if not args.no_jsonl:
        path = args.jsonl or pathlib.Path.home() / ".nos" / "events" / "smoke.jsonl"
        try:
            emit_jsonl(path, run_id, results)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("WARN: JSONL append to %s failed: %s\n" % (path, exc))

    failed = sum(1 for r in results if not r.ok)
    # Systemic-failure gate: when --fail-ratio is set, exit non-zero ONLY when a
    # large PROPORTION of probes fail (the "green != working" class — e.g. local
    # DNS down makes ~every service DEAD) while a couple of flaky probes stay
    # tolerated. Otherwise the exit code is the raw failed count.
    if args.fail_ratio is not None:
        total = len(results)
        ratio = (failed / total) if total else 0.0
        # failed>0 guard so a clean run is always 0 even at ratio 0.0 (which
        # otherwise means "fail on ANY probe failure" = strict mode).
        return 1 if (failed > 0 and ratio >= args.fail_ratio) else 0
    # 0 or 1 — NOT the failure count (2026-08-06).
    #
    # The count used to BE the exit code, capped at 127, and that was the
    # estate's third exit-code convention: Pulse's runner already reserves 126
    # for an allowlist refusal, 127 for command-not-found and -9 for a timeout
    # kill, so a smoke run with 127+ dead probes was indistinguishable from a
    # binary that never started. Two different facts, one integer.
    #
    # Nothing needed the number here. `tasks/post-smoke.yml` compares `rc != 0`
    # and the only reader of the magnitude was state/judge-sets.yml's
    # `exit_count` adapter, which is now `exit_zero` — it reads the count from
    # stdout via work_regex ("N / M OK"), where it was all along and where it
    # is not competing with a signal about the process itself.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
