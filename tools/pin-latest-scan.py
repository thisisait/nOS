#!/usr/bin/env python3
"""What is each image pin missing, measured against its registry.

WHY A TOOL AND NOT A SWEEP. A pin wave is the estate's most common maintenance
job and its most common source of quiet wrongness: the version in the queue is
stale by the time it is read (n8n's "fix version" was five releases behind on
2026-08-06), the newest tag is sometimes IN the vulnerable range (WordPress
7.0.0/7.0.1 were, while 7.0.2 was the fix), and "latest" is not a version. So
this reports and classifies; it never edits a pin.

WHAT IT REFUSES TO GUESS. Three classes are reported and never proposed:

  * `major` — a jump across the leading number. For a stateful service that is
    a one-way schema migration, and `git checkout` of the old pin does not undo
    it: the schema is already migrated and the old binary refuses to start.
  * `unpinnable` — the pin is `latest`, a digest, or a `sha-` build id. There
    is no version to compare, which is itself the finding.
  * `local` — images this repository builds (nos/*). Their version is ours.

Everything else is `minor` or `patch` within the same major, which is the part
a sweep may take.

USAGE
    tools/pin-latest-scan.py                 # table, all pins
    tools/pin-latest-scan.py --json          # machine-readable
    tools/pin-latest-scan.py --class minor   # one class

Exit 0 always: this is a report, not a gate. A gate that fails because upstream
released something would go red on a calendar rather than on a defect.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TIMEOUT = 25

#: Images this repository builds. Their tags are not upstream's business.
LOCAL_PREFIXES = ("nos/",)

VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$")


#: A leading number this large is a DATE STAMP or a build counter, not a major
#: version. Jellyfin publishes `2026080308` beside `10.11.10`; without this the
#: scan proposed "upgrade 10.11.10 to 2026080308", a nightly build wearing a
#: version's shape.
#:
#: The threshold has to clear CALENDAR VERSIONING, which is a real scheme this
#: estate uses: authentik `2026.5.2` and Home Assistant `2026.6.0` are proper
#: versions whose major IS the year. A first cut at 1000 rejected both and
#: reported them "unpinnable" — trading one false reading for another. A
#: ten-digit build id and a four-digit year are six orders of magnitude apart,
#: so the line sits between them with room to spare.
NOT_A_MAJOR = 1_000_000


def parse(tag: str):
    """(major, minor, patch, suffix) or None if the tag is not a version."""
    m = VERSION_RE.match(tag.strip())
    if not m:
        return None
    major, minor, patch, suffix = m.groups()
    if int(major) >= NOT_A_MAJOR:
        return None
    # A suffix that is a pre-release marker disqualifies the tag as a target.
    return (int(major), int(minor or 0), int(patch or 0), suffix or "")


def stable(tag: str) -> bool:
    p = parse(tag)
    if p is None:
        return False
    suffix = p[3].lower()
    if not suffix:
        return True
    # Accept build-flavour suffixes we deliberately pin (php8.3-apache,
    # -alpine, -ce.0); reject pre-releases.
    bad = ("rc", "beta", "alpha", "nightly", "dev", "pre", "canary", "insiders", "hotfix")
    return not any(b in suffix for b in bad)


# ── registries ───────────────────────────────────────────────────────────────


def _get(url: str, headers: dict | None = None) -> dict | None:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def dockerhub_tags(image: str, until: str | None = None) -> list[str]:
    """Newest-first tags, stopping as soon as `until` is seen.

    Pagination is the expensive part and Docker Hub throttles anonymous
    callers. A flat 12-page sweep over 43 images spent the budget and started
    returning EMPTY lists — which the honesty rule reported as "unknown" for
    three images that had answered fine a minute earlier. Correct, useless, and
    entirely self-inflicted.

    Stopping at the pinned tag is what the caller actually needs: everything
    newer than the pin is already in hand, and nothing older can be a target.
    Most pins land on page one.
    """
    repo = image if "/" in image else f"library/{image}"
    tags, url = [], f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&ordering=last_updated"
    for _ in range(12):
        data = _get(url)
        if not data:
            break
        tags += [t["name"] for t in data.get("results", [])]
        if until and until in tags:
            break
        url = data.get("next")
        if not url:
            break
    return tags


def ghcr_tags(image: str) -> list[str]:
    """Anonymous OCI token flow. ghcr serves the tag list to a pull token."""
    path = image.split("/", 1)[1]
    token = _get(f"https://ghcr.io/token?scope=repository:{path}:pull&service=ghcr.io")
    if not token or "token" not in token:
        return []
    data = _get(f"https://ghcr.io/v2/{path}/tags/list?n=1000",
                {"Authorization": f"Bearer {token['token']}"})
    return (data or {}).get("tags", []) or []


def registry_tags(image: str, until: str | None = None) -> list[str]:
    if image.startswith("ghcr.io/"):
        return ghcr_tags(image)
    if image.startswith(("gcr.io/", "lscr.io/", "quay.io/")):
        # Not queried anonymously here; reported as unknown rather than guessed.
        return []
    return dockerhub_tags(image, until=until)


# ── classification ───────────────────────────────────────────────────────────


def classify(pinned: str, newest: str | None) -> str:
    if newest is None:
        return "unknown"
    a, b = parse(pinned), parse(newest)
    if a is None or b is None:
        return "unknown"
    if b[:3] <= a[:3]:
        return "current"
    if b[0] != a[0]:
        return "major"
    if b[1] != a[1]:
        return "minor"
    return "patch"


def best_tag(pinned: str, tags: list[str]) -> str | None:
    """The newest stable tag sharing the pin's SHAPE.

    Shape matters: `wordpress:7.0.2` and `wordpress:7.0.2-php8.3-apache` are
    different pins, and offering one for the other silently changes the runtime.
    """
    p = parse(pinned)
    if p is None:
        return None
    suffix, prefix_v = p[3], pinned.startswith("v")
    candidates = []
    for t in tags:
        q = parse(t)
        if q is None or not stable(t):
            continue
        if (q[3] or "") != (suffix or ""):
            continue
        if t.startswith("v") != prefix_v:
            continue
        candidates.append((q[:3], t))
    if not candidates:
        return None
    return max(candidates)[1]


def live_images() -> dict[str, str]:
    """image -> tag, from `docker ps`. What is RUNNING, which is not the same
    thing as what is pinned."""
    out = subprocess.run(["docker", "ps", "--format", "{{.Image}}"],
                         capture_output=True, text=True)
    live = {}
    for line in out.stdout.splitlines():
        if ":" in line:
            name, _, tag = line.rpartition(":")
            live[name] = tag
    return live


def collect_pins() -> list[dict]:
    cfg = (REPO / "default.config.yml").read_text(encoding="utf-8")
    pins = dict(re.findall(r'^([a-z0-9_]*_version):\s*"([^"]+)"', cfg, re.M))
    images: dict[str, str] = {}
    for pattern in ("roles/*/templates/*.j2", "files/anatomy/plugins/*/templates/*.j2"):
        for tpl in REPO.glob(pattern):
            for m in re.finditer(r"image:\s*([\w./\-]+):\{\{\s*([a-z0-9_]+)", tpl.read_text(encoding="utf-8")):
                images.setdefault(m.group(2), m.group(1))
    return [{"var": v, "pinned": val, "image": images.get(v)}
            for v, val in sorted(pins.items()) if images.get(v)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--class", dest="klass", help="only this class")
    args = ap.parse_args()

    live = live_images()
    rows = []
    for row in collect_pins():
        image, pinned = row["image"], row["pinned"]
        if image.startswith(LOCAL_PREFIXES):
            row.update(klass="local", newest=None)
        elif parse(pinned) is None or pinned in ("latest",) or "@sha256:" in pinned or pinned.startswith("sha-"):
            row.update(klass="unpinnable", newest=None)
        else:
            tags = registry_tags(image, until=pinned)
            # THE HONESTY RULE, added after the first run. If the tag we are
            # PINNED TO is not in the list we fetched, then the list is not the
            # registry — it is a window onto it, and everything computed from it
            # is a guess. On run one this printed "current" for open-webui
            # (0.10.2 vs a 0.1.121 it found instead) and for tempo (2.10.3 vs
            # 2.9.4): both were truncation, both read as reassurance.
            if pinned not in tags:
                # FALLBACK, not a guess: ask the registry for tags whose name
                # contains the pin's major, instead of walking the newest-first
                # stream. grafana/tempo re-pushes enough per-arch tags that
                # 2.10.3 sat beyond 1200 entries while `docker ps` showed it
                # running — the window was the problem, not the pin.
                p = parse(pinned)
                if p is not None and not image.startswith("ghcr.io/"):
                    repo = image if "/" in image else f"library/{image}"
                    data = _get(f"https://hub.docker.com/v2/repositories/{repo}"
                                f"/tags?page_size=100&name={p[0]}.")
                    tags += [t["name"] for t in (data or {}).get("results", [])]
            if pinned not in tags:
                row.update(newest=None, klass="unknown",
                           why=f"the pinned tag is absent from {len(tags)} fetched tags")
            else:
                newest = best_tag(pinned, tags)
                row.update(newest=newest, klass=classify(pinned, newest))
        row["live"] = live.get(image)
        row["drifted"] = bool(row["live"] and row["live"] != pinned)
        rows.append(row)

    if args.klass:
        rows = [r for r in rows if r["klass"] == args.klass]

    if args.json:
        json.dump(rows, sys.stdout, indent=1)
        print()
        return 0

    order = ["major", "minor", "patch", "current", "unknown", "unpinnable", "local"]
    for klass in order:
        group = [r for r in rows if r["klass"] == klass]
        if not group:
            continue
        print(f"\n── {klass} ({len(group)})")
        for r in group:
            target = r["newest"] or "-"
            drift = "  ⚠ live=" + r["live"] if r["drifted"] else ""
            why = f"  ({r['why']})" if r.get("why") else ""
            print(f"  {r['image']:<42} {r['pinned']:<26} -> {target:<20}{drift}{why}")
    print(f"\n{len(rows)} pins. Classes are advisory; nothing here edits a pin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
