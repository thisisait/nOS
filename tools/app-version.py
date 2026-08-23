#!/usr/bin/env python3
"""What each container actually RUNS, against what the pin says it bundles.

WHY THIS EXISTS. `default.config.yml:2371` read:

    freescout_version: "2.1.5-php8.3"   # ... app 1.8.231 — REM-142 (7 GHSA fixes)

The container runs **1.8.230**. It always did. FreeScout 1.8.231 was released
2026-07-25 and the image was published 2026-07-18, so the claim was
arithmetically impossible from the day it was written — and nobody opened the
container to check. REM-142 was CLOSED on that premise and REM-193 was FILED on
it, so two advisories the queue believed patched were live for six weeks
(REM-218, cycle 38).

The mechanism is general and boring: **an image tag and an application version
are two different numbers.** For most services they happen to agree, which is
exactly what makes the exception invisible. `tools/discovery-scan.py` compares
the queue against `docker ps`, and `docker ps` reports the TAG.

WHAT IT DOES. Runs each service's own version probe inside its live container
and prints three things side by side: the image tag, the version the
application reports, and the version the pin's comment CLAIMS it bundles. The
claim is parsed out of the existing `# … app X.Y.Z …` convention — deliberately
not a new field. That convention was already there; it was simply never read by
anything, and a claim nothing reads is a wish.

VERDICTS.
  MATCH      the app agrees with the claim (or with the tag when no claim)
  MISMATCH   the pin's comment says one version and the container runs another
  UNKNOWN    the container is not running, or the probe could not answer

`tag_tracks_app: false` marks a service whose tag family deliberately differs
from its application version — nfrastack's freescout 2.x images bundle FreeScout
1.8.x. That is not an error; treating it as one is.

WHAT IT IS NOT. It reads. It does not pull, bump, restart or stamp anything.
An unreadable probe is UNKNOWN, never a pass — "no data" and "no problem" are
the two readings this estate has most often confused.

Usage:
    tools/app-version.py           # one line per service
    tools/app-version.py --json    # for a caller

Exit 0 always, including on a MISMATCH. Reporting is the job.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "default.config.yml"
TIMEOUT = 20

#: service -> how to ask the RUNNING application what version it is.
#:
#: Every probe reads a file or runs the binary's own `--version`; none of them
#: consults the image tag, which is the whole point. `pin` names the variable in
#: default.config.yml whose inline comment carries the claim.
#:
#: Adding a service is three lines and worth doing whenever a pin's comment
#: starts asserting a bundled version — that assertion is now checkable.
SERVICES: dict[str, dict] = {
    "freescout": {
        "container": "b2b-freescout-1",
        "pin": "freescout_version",
        # nfrastack's own versioning; the app is FreeScout's. They are unrelated
        # sequences and the queue spent six weeks treating them as one.
        "tag_tracks_app": False,
        "argv": ["grep", "-m1", "-o", r"'version' => '[^']*'", "/www/html/config/app.php"],
        "extract": r"'version' => '([^']+)'",
    },
    "gitea": {
        "container": "devops-gitea-1",
        "pin": "gitea_version",
        "tag_tracks_app": True,
        "argv": ["/usr/local/bin/gitea", "--version"],
        "extract": r"gitea version (\S+)",
    },
    "bookstack": {
        "container": "b2b-bookstack-1",
        "pin": "bookstack_version",
        "tag_tracks_app": True,
        "argv": ["cat", "/app/www/version"],
        "extract": r"v?([0-9][^\s]*)",
    },
    "keap": {
        "container": "iiab-keap-1",
        "pin": "keap_repo_ref",
        # The tag is `<version>-<build sha>`, so it CARRIES the version but is
        # not equal to it — `docs/hidden_fees/12` is about that suffix meaning
        # "whatever the last build produced".
        "tag_tracks_app": True,
        "argv": ["sh", "-c", "grep -m1 '\"version\"' /app/package.json"],
        "extract": r'"version"\s*:\s*"([^"]+)"',
    },
}

#: The convention already in the file: `freescout_version: "2.1.5-php8.3"  # … app 1.8.231 …`
CLAIM = re.compile(r"\bapp\s+v?([0-9]+(?:\.[0-9]+)+)")


def _docker() -> str | None:
    return shutil.which("docker")


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:      # pragma: no cover
        return 1, str(exc)
    return p.returncode, (p.stdout or p.stderr)


def pin_lines() -> dict[str, tuple[str, str]]:
    """var -> (pinned value, the rest of the line after `#`)."""
    out: dict[str, tuple[str, str]] = {}
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        m = re.match(r'^([a-z_][a-z0-9_]*):\s*"?([^"#]*?)"?\s*(?:#(.*))?$', line)
        if m and m.group(2).strip():
            out[m.group(1)] = (m.group(2).strip(), (m.group(3) or "").strip())
    return out


def inspect_tag(container: str) -> str | None:
    docker = _docker()
    if not docker:
        return None
    rc, text = _run([docker, "inspect", container, "--format", "{{.Config.Image}}"])
    if rc != 0:
        return None
    image = text.strip()
    if "@" in image:
        return None
    _, _, tag = image.rpartition(":")
    return tag or None


def probe(name: str, spec: dict, pins: dict) -> dict:
    row = {"service": name, "container": spec["container"], "verdict": "UNKNOWN"}

    pinned, comment = pins.get(spec["pin"], ("", ""))
    row["pin_var"] = spec["pin"]
    row["pinned"] = pinned or None
    claim = CLAIM.search(comment)
    row["claimed_app"] = claim.group(1) if claim else None

    row["image_tag"] = inspect_tag(spec["container"])
    row["tag_tracks_app"] = spec["tag_tracks_app"]

    docker = _docker()
    if not docker:
        row["error"] = "docker not on PATH"
        return row
    rc, text = _run([docker, "exec", spec["container"], *spec["argv"]])
    if rc != 0:
        row["error"] = text.strip()[:160] or f"probe exit {rc}"
        return row
    found = re.search(spec["extract"], text)
    if not found:
        row["error"] = f"probe answered but nothing matched {spec['extract']!r}"
        return row

    actual = found.group(1)
    row["app_version"] = actual

    # A claim beats the tag: it is what a human asserted and what the queue
    # reasoned from. Only when nobody claimed anything does the tag stand in.
    if row["claimed_app"]:
        row["verdict"] = "MATCH" if actual == row["claimed_app"] else "MISMATCH"
        row["compared_against"] = "pin comment"
    elif spec["tag_tracks_app"] and row["image_tag"]:
        tag = row["image_tag"].lstrip("v").split("-")[0]
        row["verdict"] = "MATCH" if tag.startswith(actual) or actual.startswith(tag) else "MISMATCH"
        row["compared_against"] = "image tag"
    else:
        # Declared not to track, and nothing claimed: there is nothing to
        # compare against. Reporting the number is still the useful act.
        row["verdict"] = "UNCLAIMED"
        row["compared_against"] = None
    return row


def collect() -> dict:
    pins = pin_lines()
    return {"services": [probe(n, s, pins) for n, s in SERVICES.items()]}


def render(report: dict) -> list[str]:
    lines = ["what each container runs — the tag is not the version", ""]
    for r in report["services"]:
        lines.append(f"  {r['service']:<12} {r['verdict']}")
        if r.get("error"):
            lines.append(f"    could not read: {r['error']}")
            lines.append("")
            continue
        lines.append(f"    image tag    {r.get('image_tag')}"
                     + ("" if r["tag_tracks_app"] else "   (does NOT track the app version)"))
        lines.append(f"    app reports  {r.get('app_version')}")
        if r.get("claimed_app"):
            lines.append(f"    pin claims   {r['claimed_app']}"
                         f"   ({r['pin_var']}'s comment)")
        if r["verdict"] == "MISMATCH":
            lines.append("    ^ the queue and the roadmap reason from the CLAIM; "
                         "every row resting on it is wrong")
        lines.append("")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()
    report = collect()
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print("\n".join(render(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
