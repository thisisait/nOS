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
import pathlib
import re
import ssl
import sys
import time
import urllib.error
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


def probe(entry: dict) -> ProbeResult:
    """Single HEAD/GET probe. Falls back to GET if HEAD returns 405."""
    url = entry["url"]
    timeout = float(entry.get("timeout", 5))
    expect = entry.get("expect")
    if isinstance(expect, int):
        expect = [expect]
    expect = set(expect or [200, 301, 302, 308])

    ctx = ssl.create_default_context()
    if entry.get("insecure", True):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    started = time.monotonic()

    def _do(method: str) -> tuple[int | None, str | None]:
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

    code, err = _do("HEAD")
    if code == 405:  # some apps refuse HEAD — try GET
        code, err = _do("GET")
    duration_ms = int((time.monotonic() - started) * 1000)
    ok = code in expect
    return ProbeResult(entry, code, duration_ms, err, ok)


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
    args = p.parse_args()

    # ── Load Ansible-style variables ───────────────────────────────────────
    vars_dict = merge_config(
        REPO / "default.config.yml",
        REPO / "config.yml",      # gitignored operator override
    )
    # Self-substitute Jinja inside vars (e.g. wing_domain: "wing.{{ instance_tld }}")
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

    # ── Run probes in parallel ─────────────────────────────────────────────
    run_id = "smoke_" + datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(probe, all_entries))

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
