#!/usr/bin/env python3
"""origin-lock-report — cycles and dead packages in one checkout's lockfiles, from the lockfiles alone.

Row git-origin-watcher, slice 1 (choices 1(a) every cycle is reported, 2(a) a plain tool until its loop
manifest lands). No model, no network, no subprocess, no write: it reads the paths it is given.

    tools/origin-lock-report.py --composer-lock composer.lock --package-lock package-lock.json
    tools/origin-lock-report.py --package-lock package-lock.json --json
    tools/origin-lock-report.py ... --strict     # exit 3 on a cycle or a flag, 2 on an unreadable file

- composer.lock: nodes are `packages` + `packages-dev`; an edge is a `require` key naming another locked
  package; `abandoned` set = flagged.
- package-lock.json (lockfileVersion 2 or 3): nodes are the `packages` map; an entry's `dependencies`
  resolve as npm does (the nearest `node_modules/<name>` up the entry's path); `deprecated` = flagged.
- A cycle is a strongly connected set of two or more packages (or one that requires itself), by name.
- A missing, malformed, oversized or unsupported file, or a symlink that leaves its directory, is
  UNKNOWN (`unreadable`), never clean. Names and messages are lockfile data: printed clipped, as text.

Exit 0 always; with --strict 2 if any file is unreadable, else 3 on any cycle or flag (the findings code
the loops use, tools/loops/repo-check.py), else 0.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

MAX_BYTES = 64 * 1024 * 1024  # a lockfile above this is refused, not half-read
FINDINGS, UNREADABLE = 3, 2


class Unreadable(Exception):
    pass


def clip(s: object, n: int = 120) -> str:
    """Lockfile text as one printable line: control characters dropped, at most n chars."""
    t = "".join(c for c in str(s) if c.isprintable())
    return t if len(t) <= n else t[: n - 1] + "…"


def load(path: str) -> dict:
    p = pathlib.Path(path)
    if p.is_symlink() and not p.resolve().is_relative_to(p.parent.resolve()):
        raise Unreadable("a symlink out of its directory")
    try:
        if not p.is_file():
            raise Unreadable("not found")
        if p.stat().st_size > MAX_BYTES:
            raise Unreadable(f"over {MAX_BYTES // 1024 // 1024} MB")
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Unreadable(type(exc).__name__) from None
    except ValueError:
        raise Unreadable("not JSON") from None
    if not isinstance(doc, dict):
        raise Unreadable("not a JSON object")
    return doc


def cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """Strongly connected components of two or more nodes, or a node with an edge to itself (iterative Tarjan)."""
    index, low, on, stack, out, n = {}, {}, set(), [], [], 0
    for root in edges:
        if root in index:
            continue
        work = [(root, iter(sorted(edges[root])))]
        index[root] = low[root] = n
        n += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = n
                    n += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(edges.get(w, ())))))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in edges.get(v, ()):
                    out.append(sorted(comp))
    return sorted(out)


def composer(doc: dict) -> tuple[int, list[list[str]], list[dict]]:
    pkgs = [p for k in ("packages", "packages-dev") for p in (doc.get(k) or []) if isinstance(p, dict)]
    if "packages" not in doc:
        raise Unreadable("no `packages` list: not a composer.lock")
    names = {str(p.get("name")) for p in pkgs if p.get("name")}
    edges, flagged = {}, []
    for p in pkgs:
        name = str(p.get("name") or "")
        if not name:
            continue
        req = p.get("require") if isinstance(p.get("require"), dict) else {}
        edges[name] = {r for r in req if r in names}
        if p.get("abandoned"):
            alt = p["abandoned"]
            flagged.append({"name": name, "version": str(p.get("version") or ""),
                            "why": "abandoned" + (f", use {alt}" if isinstance(alt, str) and alt else "")})
    return len(pkgs), cycles(edges), flagged


def _resolve(packages: dict, at: str, dep: str) -> str | None:
    """npm's lookup: `<at>/node_modules/<dep>`, then the same from each enclosing package, then the root."""
    base = at
    while True:
        cand = f"{base}/node_modules/{dep}" if base else f"node_modules/{dep}"
        if cand in packages:
            return cand
        if not base:
            return None
        cut = base.rfind("/node_modules/")
        base = base[:cut] if cut >= 0 else ""


def _npm_name(path: str, entry: dict) -> str:
    if entry.get("name"):
        return str(entry["name"])
    return path.rsplit("node_modules/", 1)[-1] if path else "(root)"


def npm(doc: dict) -> tuple[int, list[list[str]], list[dict]]:
    if doc.get("lockfileVersion") not in (2, 3) or not isinstance(doc.get("packages"), dict):
        raise Unreadable(f"lockfileVersion {clip(doc.get('lockfileVersion'), 8)}: only 2 and 3 carry the `packages` map")
    packages = {k: v for k, v in doc["packages"].items() if isinstance(v, dict)}
    by_path: dict[str, set[str]] = {}
    for path, entry in packages.items():
        deps = entry.get("dependencies") if isinstance(entry.get("dependencies"), dict) else {}
        by_path[path] = {t for d in deps if (t := _resolve(packages, path, d)) is not None}
    name = {p: _npm_name(p, e) for p, e in packages.items()}
    # A cycle by path, reported by name: two copies of one name at two paths stay two nodes.
    found = [sorted({name[p] for p in comp}) for comp in cycles(by_path)]
    flagged = [{"name": name[p], "version": str(e.get("version") or ""), "why": "deprecated: " + clip(e["deprecated"], 160)}
               for p, e in sorted(packages.items()) if e.get("deprecated")]
    return len(doc["packages"]), found, flagged


def report(composer_lock: str | None, package_lock: str | None) -> dict:
    files, unreadable = [], []
    for path, kind in ((composer_lock, "composer"), (package_lock, "npm")):
        if not path:
            continue
        try:
            n, found, flagged = (composer if kind == "composer" else npm)(load(path))
        except Unreadable as why:
            unreadable.append(path)
            files.append({"file": path, "kind": kind, "unreadable": str(why)})
            continue
        # Lockfile data leaves as clipped text, JSON too: 214 is npm's longest name, so a real one is never cut.
        files.append({"file": path, "kind": kind, "packages": n, "cycles": [[clip(x, 214) for x in c] for c in found],
                      "flagged": [{"name": clip(x["name"], 214), "version": clip(x["version"], 64), "why": clip(x["why"], 200)}
                                  for x in flagged]})
    return {"files": files, "unreadable": unreadable}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--composer-lock", help="a composer.lock")
    ap.add_argument("--package-lock", help="a package-lock.json (lockfileVersion 2 or 3)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 3 on a cycle or flag, 2 on an unreadable file")
    a = ap.parse_args(argv)
    if not (a.composer_lock or a.package_lock):
        ap.error("give --composer-lock and/or --package-lock")
    r = report(a.composer_lock, a.package_lock)
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
    else:
        for f in r["files"]:
            if "unreadable" in f:
                print(f"UNKNOWN {clip(f['file'], 1024)} ({f['kind']}): {f['unreadable']}")
                continue
            print(f"origin-lock-report — {clip(f['file'], 1024)} ({f['kind']}): {f['packages']} packages, "
                  f"{len(f['cycles'])} cycle(s), {len(f['flagged'])} flagged")
            for c in f["cycles"]:
                print("  cycle   " + " -> ".join(clip(x, 80) for x in c))
            for x in f["flagged"]:
                print(f"  flagged {clip(x['name'], 80)} {clip(x['version'], 40)}: {clip(x['why'], 200)}")
    if not a.strict:
        return 0
    if r["unreadable"]:
        return UNREADABLE
    return FINDINGS if any(f.get("cycles") or f.get("flagged") for f in r["files"]) else 0


if __name__ == "__main__":
    sys.exit(main())
