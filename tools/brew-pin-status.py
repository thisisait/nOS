#!/usr/bin/env python3
"""How old is the version brew wants to give us, and is it old enough to adopt?

WHY THIS EXISTS. `roles/pazny.openclaw/tasks/main.yml` installs ollama with
`state: latest` and then REFUSES the converge when the linked keg is not the
version `default.config.yml` records. That guard has fired three times, and
every time the answer was the same: bump the record, re-run. The record follows
brew, after a failed run, unattended, at whatever hour the converge happened to
reach that task.

The measurement that names the problem (2026-08-27):

    ollama 0.33.0        landed in homebrew-core   2026-08-26T03:01:09Z
    the converge adopted it                        2026-08-27  ~14:5x

**A formula one day old, taken without anyone deciding to take it.** The
previous bump, 0.32.15, was five days old. Nobody chose either number.

THE BORROWED IDEA. Omarchy's stable channel tracks an Arch mirror deliberately
running a MONTH behind, "so we can catch any new incompatibilities that require
config changes before they cause problems for people". mise ships the same
primitive as `MISE_MINIMUM_RELEASE_AGE`. Homebrew has no lagged mirror, so the
lag has to be a decision we make rather than a channel we subscribe to — and a
decision needs a reading to be made from. This is that reading.

WHAT IT DOES NOT DO. It does not upgrade, downgrade, edit a pin, or write
anything. It reports, and it exits 0 whatever it finds: a reader that exits
non-zero is a gate wearing a reader's name.

    tools/brew-pin-status.py                # every pinned formula
    tools/brew-pin-status.py --lag 14       # ask a different window
    tools/brew-pin-status.py --json

THE CARVE-OUT IS PART OF THE DESIGN, not an oversight. `tasks/nginx.yml:34`
holds `state: latest` ON PURPOSE — REM-134 needs host nginx >= 1.31.3 for
CVE-2026-42533, so lagging it would re-open a closed finding. A security floor
outranks a lag window every time (`docs/doctrine/security-floor.md`). Formulae
in EXEMPT are listed with their reason and reported as exempt, never silently
skipped: an exemption nobody can see is indistinguishable from a gap.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
CONFIG = REPO / "default.config.yml"

#: formula -> (the var in default.config.yml that RECORDS what brew linked,
#:             why this formula is watched at all)
#: Keyed on the formula name because that is what brew and the API both answer
#: to. Add a row when a role starts recording a brew version.
PINNED = {
    "ollama": ("ollama_version",
               "roles/pazny.openclaw refuses the converge when the linked keg "
               "is not this value; MLX backend needs >= 0.19"),
}

#: formula -> why it is deliberately NOT lagged.
EXEMPT = {
    "nginx": "tasks/nginx.yml:34 keeps state: latest for REM-134 "
             "(CVE-2026-42533, host nginx must stay >= 1.31.3) — a security "
             "floor outranks a lag window",
}

DEFAULT_LAG_DAYS = 30
TIMEOUT = 20

FORMULA_API = "https://formulae.brew.sh/api/formula/{name}.json"
#: homebrew-core files live under Formula/<first-letter>/<name>.rb
HISTORY_API = ("https://api.github.com/repos/Homebrew/homebrew-core/commits"
               "?path=Formula/{letter}/{name}.rb&per_page=40")


def _get(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": "nos-brew-pin-status",
        "Accept": "application/vnd.github+json",
    })
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def recorded_pin(var: str) -> str | None:
    """What default.config.yml RECORDS. Deliberately not the resolved value.

    `tools/estate-status.py --config` resolves through config.yml and is the
    right tool for "what does the estate use". This file asks a narrower
    question — what has been written down as adopted — and config.yml is
    gitignored, so resolving here would make the answer unshareable.
    """
    m = re.search(rf"^{re.escape(var)}:\s*[\"']?([^\"'#\s]+)",
                  CONFIG.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def linked_keg(formula: str) -> str | None:
    """The keg `formula` will actually exec — the same reading the role takes.

    `brew list --versions` prints every keg brew kept, and matching a pin
    against that line is how a pin stayed silent while the binary was a
    different version (measured 2026-08-10, see the role's own comment).
    """
    try:
        which = subprocess.run(["command", "-v", formula], capture_output=True,
                               text=True, timeout=10, shell=False)
    except (OSError, subprocess.SubprocessError):
        which = None
    path = (which.stdout.strip() if which and which.returncode == 0 else "")
    if not path:
        from shutil import which as _which
        path = _which(formula) or ""
    if not path:
        return None
    real = os.path.realpath(path)
    m = re.search(r"/Cellar/[^/]+/([^/]+)/", real)
    return m.group(1) if m else None


def landed_at(formula: str, version: str) -> tuple[dt.datetime | None, str]:
    """When homebrew-core first carried `version` of `formula`.

    The formula API's `generated_date` is when the JSON was built, not when the
    version landed — reading it as an age would report every formula as brand
    new for ever. The commit that bumps a formula is titled `<name> <version>`,
    so the history is the artifact that can answer.
    """
    letter = formula[0].lower()
    try:
        commits = _get(HISTORY_API.format(letter=letter, name=formula))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return None, f"homebrew-core history unreachable ({exc})"
    if isinstance(commits, dict):
        return None, f"GitHub API said: {commits.get('message', '?')}"

    # Oldest matching commit wins: a bottle rebuild for the same version lands
    # later and would make the version look younger than it is.
    best = None
    for c in commits:
        subject = (c.get("commit", {}).get("message") or "").splitlines()[0]
        if re.match(rf"^{re.escape(formula)}\s+{re.escape(version)}\b", subject):
            when = c.get("commit", {}).get("committer", {}).get("date")
            if when:
                stamp = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
                best = stamp if best is None or stamp < best else best
    if best is None:
        return None, (f"no commit titled '{formula} {version}' in the last 40 "
                      "touches — the version may predate the window")
    return best, ""


def _cmp(a: str, b: str) -> int | None:
    """Numeric compare, refusing anything that is not a version.

    Same refusal discipline as UpgradeRepository::compareVersions — a build id
    or `latest` must not be guessed at in either direction.
    """
    def parts(v):
        t = re.match(r"^\d+(?:\.\d+)*", v.lstrip("vV"))
        return [int(x) for x in t.group(0).split(".")] if t else None
    pa, pb = parts(a), parts(b)
    if pa is None or pb is None:
        return None
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return (pa > pb) - (pa < pb)


def survey(lag_days: int) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for formula, (var, why) in sorted(PINNED.items()):
        row = {"formula": formula, "var": var, "why": why,
               "pin": recorded_pin(var), "keg": linked_keg(formula)}
        try:
            api = _get(FORMULA_API.format(name=formula))
            row["stable"] = (api.get("versions") or {}).get("stable")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            row["stable"], row["note"] = None, f"formula API unreachable ({exc})"

        if not row["pin"] or not row["stable"]:
            row["verdict"] = "UNKNOWN"
            row.setdefault("note", "pin or upstream version could not be read")
            out.append(row)
            continue

        c = _cmp(row["pin"], row["stable"])
        if c is None:
            row["verdict"] = "UNKNOWN"
            row["note"] = f"{row['pin']!r} vs {row['stable']!r} is not a version comparison"
        elif c >= 0:
            row["verdict"] = "AT-PIN"
            row["note"] = ("the record is at or past upstream"
                           if c == 0 else "the record is AHEAD of upstream stable")
        else:
            when, note = landed_at(formula, row["stable"])
            if when is None:
                row["verdict"] = "UNKNOWN"
                row["note"] = note
            else:
                age = (now - when).days
                row["landed"] = when.isoformat()
                row["age_days"] = age
                row["verdict"] = "ELIGIBLE" if age >= lag_days else "TOO-FRESH"
                row["note"] = (f"{row['stable']} has been out {age}d "
                               f"({'>=' if age >= lag_days else '<'} {lag_days}d window)")
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lag", type=int, default=DEFAULT_LAG_DAYS,
                    help=f"days a version must be out before it may be adopted "
                         f"(default {DEFAULT_LAG_DAYS})")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = survey(args.lag)
    if args.json:
        print(json.dumps({"lag_days": args.lag, "pinned": rows,
                          "exempt": EXEMPT}, indent=2))
        return 0

    print(f"brew pins, against a {args.lag}-day lag window\n")
    for r in rows:
        head = (f"  {r['verdict']:<10} {r['formula']:<12} "
                f"pin {r.get('pin') or '?':<10} upstream {r.get('stable') or '?'}")
        print(head)
        if r.get("keg") and r.get("keg") != r.get("pin"):
            print(f"               linked keg is {r['keg']} — the RECORD and the "
                  "BINARY already disagree; that is the converge's refusal, not this window")
        if r.get("note"):
            print(f"               {r['note']}")
    if not rows:
        print("  (no formula is pinned — PINNED is empty)")

    print(f"\n  exempt by design ({len(EXEMPT)}):")
    for formula, reason in sorted(EXEMPT.items()):
        print(f"    {formula}: {reason}")

    unknown = [r for r in rows if r["verdict"] == "UNKNOWN"]
    if unknown:
        print(f"\n  {len(unknown)} UNKNOWN — an unread pin is not a pin at its "
              "target. Absence of a comparison is not agreement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
