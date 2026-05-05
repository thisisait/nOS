#!/usr/bin/env python3
"""D3 — Authentik aggregator dry-run + parity report.

Compares two sources of OIDC client truth:
  1. Central `authentik_oidc_apps` list (default.config.yml, pre-Q2 shape).
  2. Per-plugin `authentik:` blocks aggregated by load_plugins.run_aggregators
     into authentik-base.inputs.clients (post-Q2 shape).

Goal: prove the per-plugin source is complete enough to replace the central
list, surface mapping gaps before C1 (delete authentik_oidc_apps) goes live.

Outputs:
  - per-slug coverage matrix (central / plugin / both)
  - field-level diff (client_id, client_secret, slug, mode/type)
  - rendered blueprint snippet from inputs.clients (manual sanity check)

Usage:
  python3 tools/aggregator-dry-run.py [--verbose]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "files/anatomy"))

from module_utils import load_plugins  # noqa: E402


def load_central_apps() -> list[dict]:
    """Parse the `authentik_oidc_apps` list out of default.config.yml without
    Jinja resolution (we only need slugs + shape, not rendered values)."""
    raw = (REPO / "default.config.yml").read_text(encoding="utf-8")
    # Strip {{ ... }} so PyYAML doesn't choke on template braces.
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", raw)
    data = yaml.safe_load(raw)
    return data.get("authentik_oidc_apps") or []


def normalize_central(apps: list[dict]) -> dict[str, dict]:
    """Index central list by slug, normalize shape for diff."""
    out: dict[str, dict] = {}
    for a in apps:
        slug = a.get("slug")
        if not slug:
            continue
        out[slug] = {
            "name": a.get("name"),
            "client_id": a.get("client_id"),
            "client_secret": a.get("client_secret"),
            "type": a.get("type", "oauth2"),  # central default
            "redirect_uris": a.get("redirect_uris"),
            "launch_url": a.get("launch_url"),
            "external_host": a.get("external_host"),
            "post_setup": a.get("post_setup"),
        }
    return out


def normalize_plugin(c: dict) -> dict:
    """Plugin authentik block → comparable shape."""
    mode = c.get("mode") or c.get("provider_type") or "native_oidc"
    type_ = "proxy" if mode in ("forward_auth", "proxy_auth") else "oauth2"
    redir = c.get("redirect_uris")
    if isinstance(redir, list):
        redir_list = list(redir)
    elif redir:
        redir_list = [redir]
    else:
        redir_list = []
    return {
        "client_id": c.get("client_id"),
        "client_secret": c.get("client_secret"),
        "type": type_,
        "redirect_uris": redir_list,
        "launch_url": c.get("launch_url"),
        "tier": c.get("tier"),
        "scopes": c.get("scopes"),
    }


_TEMPLATE_RE = re.compile(r"TEMPLATE")


def _semantic_eq(a: str | None, b: str | None) -> bool:
    """Compare two values where one may have been flattened by load_central_apps
    (Jinja {{ … }} → 'TEMPLATE'). Treat 'TEMPLATE' as a wildcard segment."""
    if a == b:
        return True
    if a is None or b is None:
        return False
    # Convert central 'TEMPLATE_pw_oidc_X' / 'https://TEMPLATE/path' into a
    # regex; the plugin side has the original Jinja which we treat as the
    # source of truth. Any TEMPLATE in `a` matches any non-empty span in `b`.
    pat = "^" + re.escape(a).replace("TEMPLATE", ".+") + "$"
    return bool(re.match(pat, b))


def diff_fields(central: dict, plugin: dict) -> list[str]:
    """Return human-readable field mismatches (semantic, ignoring Jinja
    template-flattening false positives)."""
    out = []
    for f in ("client_id", "client_secret", "type"):
        a, b = central.get(f), plugin.get(f)
        if a is not None and b is not None and not _semantic_eq(a, b):
            out.append(f"  {f}: central={a!r}  plugin={b!r}")
    # redirect_uris: central is space-separated string; plugin is list.
    cr_raw, pr_list = central.get("redirect_uris"), plugin.get("redirect_uris") or []
    if cr_raw and pr_list:
        cr_list = cr_raw.split() if isinstance(cr_raw, str) else list(cr_raw)
        # Each URI in central must have a semantic match in plugin's list.
        missing = [u for u in cr_list
                   if not any(_semantic_eq(u, p) for p in pr_list)]
        if missing:
            out.append("  redirect_uris missing in plugin:\n    "
                       + "\n    ".join(repr(m) for m in missing))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    plugins = load_plugins.discover(REPO / "files/anatomy/plugins")
    load_plugins.run_aggregators(plugins)

    by_name = {p.name: p for p in plugins}
    if "authentik-base" not in by_name:
        print("FAIL: authentik-base plugin not discovered", file=sys.stderr)
        return 2
    ab = by_name["authentik-base"]
    plugin_clients = ab.inputs.get("clients", [])

    central_idx = normalize_central(load_central_apps())
    plugin_idx: dict[str, dict] = {}
    for c in plugin_clients:
        slug = c.get("slug")
        if slug:
            plugin_idx[slug] = normalize_plugin(c)

    central_slugs = set(central_idx)
    plugin_slugs = set(plugin_idx)
    both = central_slugs & plugin_slugs
    only_central = central_slugs - plugin_slugs
    only_plugin = plugin_slugs - central_slugs

    print("# Aggregator dry-run parity report\n")
    print(f"central authentik_oidc_apps: {len(central_idx)} entries")
    print(f"plugin inputs.clients      : {len(plugin_idx)} entries")
    print(f"both sources               : {len(both)}")
    print(f"only central (NOT covered) : {len(only_central)}")
    print(f"only plugin (post-Q2 net)  : {len(only_plugin)}\n")

    if only_central:
        print("## Slugs in central list with NO corresponding plugin")
        print("(C1 cannot delete the central list until these are migrated)\n")
        for s in sorted(only_central):
            entry = central_idx[s]
            print(f"  - {s}  (type={entry['type']}, client_id={entry['client_id']})")
        print()

    if only_plugin:
        print("## Slugs in plugins with NO central entry (new coverage)\n")
        for s in sorted(only_plugin):
            print(f"  - {s}")
        print()

    print("## Field diffs for slugs in both sources\n")
    diff_count = 0
    for s in sorted(both):
        diffs = diff_fields(central_idx[s], plugin_idx[s])
        if diffs:
            diff_count += 1
            print(f"### {s}")
            for d in diffs:
                print(d)
            print()
    if diff_count == 0:
        print("(none — every shared slug agrees on client_id/secret/type)\n")

    print(f"\nSUMMARY: {len(both)} aligned, {len(only_central)} central-only, "
          f"{len(only_plugin)} plugin-only, {diff_count} field-diffs")

    if args.verbose:
        print("\n## inputs.clients raw dump\n")
        for c in plugin_clients:
            print(f"  - slug={c.get('slug')!r}  mode={c.get('mode') or c.get('provider_type')!r}  client_id={c.get('client_id')!r}")

    # Exit 0 if migration-ready (only_central empty), 1 otherwise.
    return 0 if not only_central else 1


if __name__ == "__main__":
    sys.exit(main())
