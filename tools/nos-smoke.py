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

def derive_from_manifest(manifest: dict, vars_dict: dict, defaults: dict) -> list[dict]:
    """Auto-derive one GET / probe per manifest service with domain_var."""
    out = []
    for s in manifest.get("services", []):
        if "domain_var" not in s:
            continue
        flag = s.get("install_flag")
        if flag and not vars_dict.get(flag, False):
            continue  # service not enabled → skip
        domain = vars_dict.get(s["domain_var"])
        if not domain:
            continue
        url = f"https://{domain}/"
        out.append({
            "id": s["id"],
            "url": url,
            "expect": defaults.get("expect", [200, 301, 302, 308]),
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

    # ── Anon path: simple HEAD/GET ─────────────────────────────────────────
    def _do_simple(method: str) -> tuple[int | None, str | None]:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "nos-smoke/1.0")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.status, None
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except urllib.error.URLError as exc:
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
        got = str(r.status) if r.status is not None else "DEAD"
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
    args = p.parse_args()

    # ── Load Ansible-style variables ───────────────────────────────────────
    vars_dict = merge_config(
        REPO / "default.config.yml",
        REPO / "config.yml",      # gitignored operator override
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

    manifest_entries = derive_from_manifest(manifest, vars_dict, defaults)
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
        bad = len(results) - ok
        print()
        summary = "%d / %d OK  ·  %d failed" % (ok, len(results), bad)
        if bad == 0:
            print(COLOR["green"] + "✅ " + summary + COLOR["reset"])
        else:
            print(COLOR["red"] + "❌ " + summary + COLOR["reset"])

    # ── JSONL persistence ──────────────────────────────────────────────────
    if not args.no_jsonl:
        path = args.jsonl or pathlib.Path.home() / ".nos" / "events" / "smoke.jsonl"
        try:
            emit_jsonl(path, run_id, results)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("WARN: JSONL append to %s failed: %s\n" % (path, exc))

    failed = sum(1 for r in results if not r.ok)
    return min(failed, 127)  # exit code capped at 127


if __name__ == "__main__":
    sys.exit(main())
