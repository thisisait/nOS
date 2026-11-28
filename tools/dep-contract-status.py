#!/usr/bin/env python3
"""dep-contract-status — does the running Gitea still answer the way nOS stands on it (a trial, one app).

Row plat-dep-contracts, ruled 2026-11-23 (a). A dependency contract is one-sided: Gitea will never run our gate,
so nOS states what it reads and this reader checks the upstream still provides it. The statement is the
`relies_on:` block of files/anatomy/plugins/gitea-base/plugin.yml: per endpoint a GET path, the fields nOS
reads, and a saved answer (the shape, FAKE_ values) under state/fixtures/dep-contracts/gitea/.

It asks the running Gitea on loopback, GET only, the token in an Authorization header (never a URL, never
printed), and prints one line per endpoint:
  holds    every field nOS reads is there, of the saved answer's type
  CHANGED  a field nOS reads is missing or of another type (named)
  UNKNOWN  no answer, not 2xx, not JSON, an empty list (the shape was not seen), or no token for it
Values are never printed: only endpoint names, paths as declared and field names.

    tools/dep-contract-status.py              # the estate's Gitea (127.0.0.1:<gitea_port>)
    tools/dep-contract-status.py --base URL   # another Gitea, e.g. a scratch one
    tools/dep-contract-status.py --json

Exit 0 always: a reader.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

PLUGIN = REPO / "files/anatomy/plugins/gitea-base/plugin.yml"
MISSING, EMPTY = object(), object()


def _forge() -> dict | None:
    """Token, owner and repo as tools/loop-pr.py resolves them (one resolution, not a second copy); None
    when the forge is not provisioned."""
    spec = importlib.util.spec_from_file_location("loop_pr", REPO / "tools" / "loop-pr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod._forge("gitea")
    except mod.Refused:
        return None


def at(doc, path: str):
    """The value at `a.b` (or `[].a.b`: the first element of a list answer); MISSING or EMPTY."""
    if path.startswith("[]."):
        if not isinstance(doc, list):
            return MISSING
        if not doc:
            return EMPTY
        doc, path = doc[0], path[3:]
    for part in path.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return MISSING
        doc = doc[part]
    return doc


def judge(live, saved, reads: list[str]) -> tuple[str, str]:
    """(holds | CHANGED | UNKNOWN, why) for one answer against its saved shape."""
    changed, unseen = [], []
    for path in reads:
        v, s = at(live, path), at(saved, path)
        if v is EMPTY:
            unseen.append(path)
        elif v is MISSING:
            changed.append(f"missing {path}")
        elif v is not None and type(v).__name__ != type(s).__name__:
            changed.append(f"{path} is {type(v).__name__}, saved {type(s).__name__}")
    if changed:
        return "CHANGED", "; ".join(changed)
    if unseen:
        return "UNKNOWN", f"empty list, {', '.join(unseen)} not seen"
    return "holds", ""


def ask(url: str, token: str | None) -> tuple[object, str]:
    """(the parsed answer, "") or (None, why it is UNKNOWN). GET only."""
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json",
                                                             **({"Authorization": f"token {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — loopback or the operator's --base
            body = resp.read()
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"no answer ({type(exc).__name__})"
    try:
        return json.loads(body), ""
    except ValueError:
        return None, "not JSON"


def report(base: str | None) -> dict:
    try:
        block = (yaml.safe_load(PLUGIN.read_text(encoding="utf-8")) or {}).get("relies_on") or {}
    except (OSError, yaml.YAMLError) as exc:
        return {"app": "gitea", "error": f"{PLUGIN.name} unreadable ({type(exc).__name__})", "endpoints": []}
    own = not base  # the estate's token goes only to the estate's own loopback Gitea (review 11-28)
    if own:
        port = ni.resolved(["gitea_port"]).get("gitea_port") or 3003
        base = f"http://127.0.0.1:{port}"
    forge = _forge() if own else None
    out = []
    for e in block.get("endpoints") or []:
        row = {"name": e["name"], "get": e["get"]}
        needs_token = e.get("auth") == "token"
        if needs_token and not forge:
            why = "no Gitea token (gitea_api_token): not asked" if own else "--base gets no estate token: not asked"
            out.append({**row, "state": "UNKNOWN", "why": why})
            continue
        path = e["get"]
        if "{owner}" in path or "{repo}" in path:
            if not forge:
                out.append({**row, "state": "UNKNOWN", "why": "owner/repo unresolved: not asked"})
                continue
            path = path.replace("{owner}", urllib.parse.quote(forge["owner"], safe="")) \
                       .replace("{repo}", urllib.parse.quote(forge["repo"], safe=""))
        try:
            saved = json.loads((REPO / e["answer"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out.append({**row, "state": "UNKNOWN", "why": f"saved answer unreadable ({type(exc).__name__})"})
            continue
        live, why = ask(base.rstrip("/") + path, forge["token"] if (needs_token and forge) else None)
        if live is None:
            out.append({**row, "state": "UNKNOWN", "why": why})
            continue
        state, why = judge(live, saved, list(e.get("reads") or []))
        row.update(state=state, why=why)
        if e["name"] == "version" and isinstance(live, dict) and isinstance(live.get("version"), str):
            row["running"] = live["version"]
        out.append(row)
    return {"app": "gitea", "verified": block.get("verified"), "endpoints": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base", help="Gitea base URL (default: http://127.0.0.1:<gitea_port>)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = report(a.base)
    if a.json:
        print(json.dumps(r, indent=1))
        return 0
    if r.get("error"):
        print(f"dep-contract-status — gitea UNKNOWN: {r['error']}")
        return 0
    running = next((e.get("running") for e in r["endpoints"] if e.get("running")), None)
    print(f"dep-contract-status — gitea: {len(r['endpoints'])} endpoint(s) nOS reads, answers saved for "
          f"{r.get('verified') or '?'}; running {running or 'UNKNOWN'}")
    for e in r["endpoints"]:
        print(f"  {e['state']:8} {e['name']:12} GET {e['get']}" + (f": {e['why']}" if e.get("why") else ""))
    if not r["endpoints"]:
        print("  UNKNOWN  no relies_on endpoints declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
