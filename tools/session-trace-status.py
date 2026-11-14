#!/usr/bin/env python3
"""Did a persistence surface of the operator's session change since the operator accepted it?

The operator+assistant session is the estate's largest attack surface (ssot/doctrine/session-threat-model.md):
whatever plants itself in a shell rc, a git hook, a Claude settings hook or the crontab survives the session
that planted it. This reader hashes each surface and compares with the last set the operator accepted in
~/.nos/session-trace.json. A new, changed or removed entry is RED with its path and the two hashes, never
its content: the reader prints, logs and stores hashes and paths only.

Surfaces: ~/.zshrc ~/.zprofile ~/.bashrc ~/.bash_profile ~/.profile; the checkout's executable .git/hooks/*
(not *.sample); the `hooks` and `permissions` sections of ~/.claude/settings.json, ~/.claude/settings.local.json
and the checkout's .claude/settings*.json (a section hash: an unrelated key change does not trip it); the
user's crontab. LaunchAgents are undeclared-status.py's: its verdict is quoted here, not recomputed.

    tools/session-trace-status.py            # the verdict
    tools/session-trace-status.py --json
    tools/session-trace-status.py --accept   # the current set becomes the baseline (the one write, 0600)

Exit 0 always (a reader). A surface it cannot read is UNKNOWN for that surface only. It never executes a hook,
sources an rc file, or reads secrets.yml, credentials.yml or a token file. Row session-trace-reader.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOME = Path.home()
BASELINE = HOME / ".nos" / "session-trace.json"
RC_FILES = (".zshenv", ".zshrc", ".zprofile", ".zlogin", ".bashrc", ".bash_profile", ".profile")  # .zshenv: every zsh, hooks and cron too
SECTIONS = ("hooks", "permissions")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file(kind: str, path: Path) -> dict:
    try:
        return {"kind": kind, "path": str(path), "sha256": _sha(path.read_bytes())}
    except FileNotFoundError:
        return {"kind": kind, "path": str(path), "sha256": None}
    except OSError as exc:
        return {"kind": kind, "path": str(path), "sha256": None, "unknown": type(exc).__name__}


def _settings(path: Path) -> list[dict]:
    """One entry per section of a Claude settings file: the hash of that section alone, sorted keys."""
    out = []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [{"kind": f"claude:{s}", "path": str(path), "sha256": None} for s in SECTIONS]
    except (OSError, ValueError) as exc:
        return [{"kind": f"claude:{s}", "path": str(path), "sha256": None, "unknown": type(exc).__name__} for s in SECTIONS]
    for s in SECTIONS:
        sec = doc.get(s) if isinstance(doc, dict) else None
        out.append({"kind": f"claude:{s}", "path": str(path),
                    "sha256": None if sec is None else _sha(json.dumps(sec, sort_keys=True).encode())})
    return out


def _crontab() -> dict:
    entry = {"kind": "crontab", "path": "crontab -l"}
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return {**entry, "sha256": None, "unknown": type(exc).__name__}
    if r.returncode == 0:
        return {**entry, "sha256": _sha(r.stdout)}
    if b"no crontab" in r.stderr.lower():
        return {**entry, "sha256": None}
    return {**entry, "sha256": None, "unknown": f"crontab -l exit {r.returncode}"}


def _launchd() -> dict:
    """undeclared-status.py's launchd verdict, quoted (labels only); UNKNOWN when it does not answer."""
    try:
        r = subprocess.run([sys.executable, str(REPO / "tools" / "undeclared-status.py"), "--json"],
                           capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout).get("launchd")
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as exc:
        return {"state": "UNKNOWN", "why": type(exc).__name__}
    if not isinstance(items, list):
        return {"state": "UNKNOWN", "why": "no launchd verdict in undeclared-status.py --json"}
    return {"state": "ok", "undeclared": sorted(str(d.get("label")) for d in items if isinstance(d, dict))}


def surfaces() -> list[dict]:
    out = [_file("rc", HOME / n) for n in RC_FILES]
    # The hooks git RUNS: --git-path honours core.hooksPath (this checkout: tools/git-hooks) and worktrees;
    # the hooksPath value itself is a surface, so re-pointing it is a change (review 11-14).
    hooks = REPO / ".git" / "hooks"
    try:
        def vcs(*a):
            return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, timeout=10)
        hooks = (REPO / vcs("rev-parse", "--git-path", "hooks").stdout.strip()).resolve()
        hp = vcs("config", "--get", "core.hooksPath").stdout.strip()
        out.append({"kind": "git-hooks-path", "path": "core.hooksPath", "sha256": _sha(hp.encode()) if hp else None})
    except (OSError, subprocess.SubprocessError):
        out.append({"kind": "git-hooks-path", "path": "core.hooksPath", "sha256": None, "unknown": "unreadable"})
    if hooks.is_dir():
        for h in sorted(hooks.iterdir()):
            if h.is_file() and not h.name.endswith(".sample") and os.access(h, os.X_OK):
                out.append(_file("git-hook", h))
    for p in (HOME / ".claude" / "settings.json", HOME / ".claude" / "settings.local.json",
              *sorted((REPO / ".claude").glob("settings*.json"))):
        out += _settings(p)
    out.append(_crontab())
    return out


def _key(s: dict) -> str:
    return f"{s['kind']}|{s['path']}"


def collect() -> dict:
    cur = surfaces()
    try:
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        base = None
    except (OSError, ValueError):
        base = {"unreadable": True}
    held = (base or {}).get("surfaces") or {}
    for s in cur:
        old = held.get(_key(s))
        if s.get("unknown"):
            s["state"] = "UNKNOWN"
        elif s["sha256"] is None:
            s["state"] = "removed" if old else "absent"
        elif base is None or old is None:
            s["state"] = "new"
        else:
            s["state"] = "unchanged" if old == s["sha256"] else "changed"
        if old and s["state"] in ("changed", "removed"):
            s["was"] = old
    gone = sorted(set(held) - {_key(s) for s in cur})
    for k in gone:  # e.g. a git hook deleted since the baseline
        kind, _, path = k.partition("|")
        cur.append({"kind": kind, "path": path, "sha256": None, "state": "removed", "was": held[k]})
    return {"surfaces": cur, "baseline_at": (base or {}).get("accepted_at"),
            "baseline": "absent" if base is None else ("unreadable" if base.get("unreadable") else "ok"),
            "launchd": _launchd()}


def accept(report: dict) -> None:
    held = {_key(s): s["sha256"] for s in report["surfaces"] if s.get("sha256")}
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BASELINE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"accepted_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "surfaces": held}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(BASELINE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--accept", action="store_true", help="make the current set the baseline (writes ~/.nos/session-trace.json)")
    args = ap.parse_args()
    report = collect()
    if args.accept:
        accept(report)
        print(f"accepted {sum(1 for s in report['surfaces'] if s.get('sha256'))} surface(s) into {BASELINE}")
        return 0
    if args.json:
        json.dump(report, sys.stdout, indent=1)
        print()
        return 0
    if report["baseline"] == "absent":
        print(f"no baseline — run tools/session-trace-status.py --accept once you have looked ({BASELINE})")
    elif report["baseline"] == "unreadable":
        print(f"RED baseline {BASELINE} unreadable: every surface is compared against nothing")
    else:
        print(f"baseline accepted {report['baseline_at']}")
    for s in report["surfaces"]:
        st = s["state"]
        red = st in ("changed", "removed") or (st == "new" and report["baseline"] == "ok")
        hashes = f"  {str(s.get('was'))[:12]} -> {str(s.get('sha256'))[:12]}" if "was" in s else ""
        why = f"  ({s['unknown']})" if st == "UNKNOWN" else ""
        print(f"  {'RED ' if red else '    '}{st:9s} {s['kind']:18s} {s['path']}{hashes}{why}")
    ld = report["launchd"]
    print("launchd (undeclared-status.py): " + (f"UNKNOWN ({ld['why']})" if ld["state"] != "ok"
          else (f"{len(ld['undeclared'])} undeclared: " + ", ".join(ld["undeclared"][:6]) if ld["undeclared"] else "nothing undeclared")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
