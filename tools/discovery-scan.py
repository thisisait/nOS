#!/usr/bin/env python3
"""Discovery: find two representations of one fact that disagree.

WHY THIS SHAPE, and it is measured rather than chosen. On 2026-08-04 this
estate found eight real defects in a day. Every one of them was the same thing:

  role default uptime_kuma_version "1"   vs  default.config.yml "2.2.1"
  REM-073 "resolved, Verified"           vs  a container serving its installer
  backup "success"                       vs  an archive with zero members
  Docker `healthy`                       vs  /api/entry-page: setup-database
  /opt/homebrew/bin/claude -> v24.19.0   vs  the live session on v24.18.0
  "'1' never jumps to v2.x"              vs  the pin that jumped
  webhook contentType: json              vs  a body only read when "custom"

Two places holding one fact, and nothing comparing them. Not one was found by a
gate — each was found by someone noticing an inconsistency and chasing it.

So discovery is a CONTRADICTION FINDER, and its niche is specifically the pairs
where one side is the LIVE ESTATE. pytest cannot go there; that is exactly
where the worst of the eight lived, undetected for weeks.

THE PRECISION RULE, which matters more than coverage. Both sides must be
machine-readable and the disagreement exact. No LLM in the detection path. A
noisy detector gets muted, and a muted detector is worse than none — this
estate already ran a nightly drift watcher that produced no verdict at all for
months and nobody noticed. When a comparison is ambiguous this tool SKIPS and
says how many it skipped, rather than guessing.

WHAT IT MAY AND MAY NOT DO. It FILES rows into the roadmap. It cannot promote
them: implementation requires a committed workflow spec naming the row, and
this tool speaks HTTP to a table and performs no filesystem writes at all. That
asymmetry is the triage gate — see docs/doctrine/workflows.md §6 and
tests/anatomy/test_triage_gate_is_a_commit.py.

Usage:  discovery-scan.py [--file] [--json]
        (default is report-only; --file writes roadmap rows)

Exit codes
----------
  0  scanned; no contradiction found
  1  at least one contradiction found
  2  could not read one of the two sides — NOTHING WAS COMPARED
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "default.config.yml"
QUEUE = REPO / "docs/llm/security/remediation-queue.json"
CLAUDE_MD = REPO / "CLAUDE.md"

# Repo files that a NIGHTLY JOB writes and no job commits. Every one of these is
# a fact the estate produced about itself, living in a working tree that git
# considers dirty — one `git checkout` from gone, and invisible to anyone
# reading the branch.
HOST_WRITTEN = [
    "docs/llm/security/remediation-queue.json",
    "docs/llm/security/scan-state.json",
]

TABLE = "2d498264-bc9a-4324-9935-489e5e4d92f3"
BASE = f"http://127.0.0.1:8091/api/tables/{TABLE}"
HEADERS = {
    "X-Authentik-Username": "akadmin",
    "X-Authentik-Email": "admin@pazny.eu",
    "X-Authentik-Groups": "nos-providers,nos-admins",
    "Content-Type": "application/json",
}

# Rows this tool files are prefixed so a reader can tell an OBSERVATION from a
# plan. The live table has no `source` column yet — the git-owned definition
# adds one, and until that migration lands the slug carries it.
OBS_PREFIX = "obs-"


@dataclass
class Finding:
    slug: str
    title: str
    body: str
    refs: str = ""
    track: str = "platform"


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    compared: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


# ---------------------------------------------------------------------------
# Reading the two sides
# ---------------------------------------------------------------------------

_VERSION_VAR = re.compile(r"^([a-z0-9_]+)_version:\s*[\"']?([^\"'#\s]+)", re.MULTILINE)
# FULLMATCH, not a prefix match. The prefix version read REM-129's
# fix_version — "6.8.6 / 6.9.5 / 7.0.2 (none dockerized as of 2026-07-20)" —
# as 6.8.6 and reported a contradiction against a row that names three fix
# versions and says none of them ships in a container. That is exactly the
# guess this tool's precision rule forbids: an ambiguous comparison SKIPS.
_NUMERIC = re.compile(r"v?(\d+(?:\.\d+)*)(?:-[a-z0-9.]+)?$", re.IGNORECASE)


def declared_versions() -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _VERSION_VAR.finditer(
        CONFIG.read_text(encoding="utf-8"))}


def running_images() -> dict[str, str]:
    """container name -> image ref, from the live daemon."""
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"docker ps failed: {out.stderr.strip()[:200]}")
    images = {}
    for line in out.stdout.splitlines():
        if "\t" in line:
            name, image = line.split("\t", 1)
            images[name.strip()] = image.strip()
    return images


def _flat(s: str) -> str:
    """Separator-insensitive key: `open-webui`, `open_webui`, `openwebui` → one."""
    return s.replace("-", "").replace("_", "").lower()


def container_for(service: str, images: dict[str, str]) -> tuple[str, str] | None:
    """`<stack>-<service>-1` is the naming convention; match on the middle.

    Matching is SEPARATOR-INSENSITIVE, and that is not cosmetic. The security
    queue writes `openwebui` and `calibreweb`; Docker names the containers
    `iiab-open-webui-1` and `iiab-calibre-web-1`. An exact match skipped all
    nine of those rows — including REM-138, which asks for Open WebUI 0.10.2
    while the estate has been RUNNING 0.10.2. A stale `pending` row is exactly
    what probe B exists to find, and the finder was blind to it because of a
    hyphen.

    The residual risk is a false match between two services whose names differ
    only by separators. There is no such pair in this estate today, and if one
    ever appears the comparison it produces is version-vs-version, which will
    disagree loudly rather than silently.
    """
    want = _flat(service)
    for name, image in images.items():
        parts = name.split("-")
        # strip the leading stack and the trailing replica index
        middle = "-".join(parts[1:-1]) if len(parts) > 2 else name
        if _flat(middle) == want:
            return name, image
    return None


def image_tag(image: str) -> str | None:
    """`repo/name:tag` -> tag. Digest-pinned or untagged refs return None."""
    if "@" in image:
        return None
    _, _, tag = image.rpartition(":")
    return tag if tag and "/" not in tag else None


def queue_items() -> list[dict]:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("items", data.get("remediations", []))


def at_head(relpath: str) -> str | None:
    """The file's content as the CURRENT BRANCH holds it, or None.

    None means "git could not answer" — a new file, a detached state, no git at
    all. Every one of those is a reason to skip rather than to claim drift.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO), "show", f"HEAD:{relpath}"],
        capture_output=True, text=True, timeout=30,
    )
    return out.stdout if out.returncode == 0 else None


def numeric(v: str) -> tuple[int, ...] | None:
    """Only a WHOLE dotted-numeric version compares. Anything else skips.

    A leading-numeric match is not good enough: prose that begins with a
    version number is prose, and treating it as a version manufactures
    contradictions out of punctuation.
    """
    m = _NUMERIC.fullmatch(v.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


# ---------------------------------------------------------------------------
# Probe A — what the estate is PINNED to vs what it is RUNNING
# ---------------------------------------------------------------------------

def probe_pin_vs_running(images: dict[str, str], res: ScanResult) -> None:
    """The version-pin shadow, live.

    A pin that never reached a container is the defect recorded in the
    operator's memory `version-pins-default-config-shadow`: a converge left n8n
    on an unpatched 2.14.1 while the role default said 2.20.7, and a HEALTHY
    container ran the vulnerable image for weeks. Comparing the two is the
    whole check.
    """
    for var, declared in declared_versions().items():
        hit = container_for(var, images)
        if hit is None:
            res.skip("no running container for the pin")
            continue
        name, image = hit
        tag = image_tag(image)
        if tag is None:
            res.skip("image is digest-pinned or untagged")
            continue
        want, have = numeric(declared), numeric(tag)
        if want is None or have is None:
            # `latest`, `main`, `6.0.0-dev` — comparing these is guessing.
            res.skip("version not strictly numeric")
            continue
        res.compared += 1
        if want == have:
            continue
        direction = "BEHIND" if have < want else "AHEAD OF"
        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}pin-{var.replace('_', '-')}",
            title=f"{name} runs {tag}, pinned {declared}",
            track="security" if have < want else "platform",
            refs=f"default.config.yml {var} · docker ps {name}",
            body=(
                f"The running container is {direction} its pin. "
                f"default.config.yml declares {var}: {declared}; the live image "
                f"is {image}. A pin that never reached a container is not "
                f"applied — and a healthy container can run an old, vulnerable "
                f"image indefinitely, which is how this class went unnoticed "
                f"for weeks in the n8n case. Recreate with "
                f"`ansible-playbook main.yml --tags {var.replace('_version', '')}` "
                f"and re-check, or correct the pin if the image is intentional."
            ),
        ))


# ---------------------------------------------------------------------------
# Probe B — what the security queue CLAIMS vs what is running
# ---------------------------------------------------------------------------

def probe_queue_vs_running(images: dict[str, str], res: ScanResult) -> None:
    """A `resolved` row whose fix never reached the estate.

    REM-073 is the worked example and the reason this probe exists: it recorded
    "container healthy on 2.2.1, http 200. Verified" while the container served
    its own installer. That particular lie is not detectable here — healthy and
    200 were both true — but the version half is, and the inverse case (six
    items sat `pending` while already live at their fix) is caught in the same
    comparison.
    """
    for item in queue_items():
        status = item.get("status")
        component, fix = item.get("component"), item.get("fix_version")
        if status not in ("resolved", "pending") or not component or not fix:
            res.skip("queue row lacks component or fix_version")
            continue
        hit = container_for(component, images)
        if hit is None:
            res.skip("no running container for the queue component")
            continue
        name, image = hit
        tag = image_tag(image)
        want, have = numeric(str(fix)), numeric(tag or "")
        if tag is None or want is None or have is None:
            res.skip("queue or image version not strictly numeric")
            continue
        res.compared += 1

        if status == "resolved" and have < want:
            res.findings.append(Finding(
                slug=f"{OBS_PREFIX}queue-{item['id'].lower()}",
                title=f"{item['id']} says resolved; {name} runs {tag} < {fix}",
                track="security",
                refs=f"remediation-queue.json {item['id']} · docker ps {name}",
                body=(
                    f"The queue records {item['id']} ({component}) as RESOLVED at "
                    f"{fix}, and the running image is {image}. One of the two is "
                    f"wrong. A resolved row that never reached the estate is the "
                    f"most expensive kind of false record: it stops anyone "
                    f"looking. Either the converge did not recreate the "
                    f"container, or the row was closed on intent rather than on "
                    f"a reading."
                ),
            ))
        elif status == "pending" and have >= want:
            res.findings.append(Finding(
                slug=f"{OBS_PREFIX}queue-{item['id'].lower()}",
                title=f"{item['id']} still pending; {name} already runs {tag} >= {fix}",
                track="security",
                refs=f"remediation-queue.json {item['id']} · docker ps {name}",
                body=(
                    f"The queue lists {item['id']} ({component}) as PENDING with "
                    f"fix {fix}, but the live image {image} already satisfies it. "
                    f"Six rows were found in exactly this state on 2026-08-02 — "
                    f"the queue does not learn from a converge, so a 'pending' row "
                    f"may simply be stale. Stale pendings are not harmless: they "
                    f"inflate the backlog and hide the rows that are real."
                ),
            ))


# ---------------------------------------------------------------------------
# Probe C — what a nightly job WROTE vs what the branch HOLDS
# ---------------------------------------------------------------------------

def probe_artefact_vs_repo(res: ScanResult) -> None:
    """A finding that exists only in a working tree has not been recorded.

    The nightly security scan writes its results INTO the repository —
    remediation-queue.json and scan-state.json — and nothing commits them. So
    the estate's own knowledge of its exposure accumulates as an uncommitted
    diff in whichever checkout the scan happened to run from. It is invisible
    to anyone reading the branch, it does not reach CI, and a single
    `git checkout` erases weeks of scanning.

    This is not hypothetical. On 2026-08-05 the main checkout carried 165 rows
    while `origin/dev` carried 152: thirteen findings, including two HIGH, that
    only one directory on one machine knew about. A worktree opened from that
    same repo read the 152-row copy and compared the WRONG SIDE — this scanner
    included.

    The pair is the file on disk against the file at HEAD. Byte equality is the
    whole comparison, so there is nothing to guess.
    """
    for rel in HOST_WRITTEN:
        path = REPO / rel
        if not path.is_file():
            res.skip("host-written artefact absent from this checkout")
            continue
        committed = at_head(rel)
        if committed is None:
            res.skip("artefact not tracked at HEAD")
            continue
        live = path.read_text(encoding="utf-8")
        res.compared += 1
        if live == committed:
            continue

        # A row-count delta when both sides parse; the divergence stands on its
        # own either way, so a parse failure must not suppress the finding.
        detail = ""
        try:
            def _n(text: str) -> int:
                d = json.loads(text)
                return len(d if isinstance(d, list) else d.get("items", []))
            detail = f" ({_n(live)} rows on disk, {_n(committed)} at HEAD)"
        except Exception:
            pass

        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}uncommitted-{Path(rel).stem}",
            title=f"{Path(rel).name} on disk differs from the branch{detail}",
            track="security",
            refs=f"{rel} · git show HEAD:{rel}",
            body=(
                f"A nightly job writes {rel} and no job commits it, so its "
                f"content{detail} exists only in this working tree. That has "
                f"three consequences, and the third is the one that bites: it "
                f"is invisible on the branch; it never reaches CI; and any "
                f"OTHER checkout — a worktree, a fresh clone, this scanner — "
                f"reads the stale committed copy and compares against it "
                f"without knowing. Commit the artefact, or make the writing job "
                f"commit it. Until then the estate's record of its own exposure "
                f"is one `git checkout` from gone."
            ),
        ))


# ---------------------------------------------------------------------------
# Probe D — what the DOCUMENTATION claims vs what the file says
# ---------------------------------------------------------------------------

# The tally line names five statuses and a total, in a fixed order:
#   **15 pending / 128 resolved / 5 vendor-blocked / 3 wontfix / 1 obsolete** of 152
_TALLY = re.compile(
    r"\*\*(\d+) pending / (\d+) resolved / (\d+) vendor-blocked / "
    r"(\d+) wontfix / (\d+) obsolete\*\* of (\d+)"
)


def probe_doc_claim_vs_queue(res: ScanResult) -> None:
    """CLAUDE.md quotes the backlog. The file is the backlog.

    CLAUDE.md carries the counts inline and warns, in its own words, that "this
    line has been wrong twice by inheritance" — a number copied forward from an
    earlier session that nobody re-derived. That warning is the strongest
    possible argument for the check: a document that knows it drifts, and asks
    to be re-derived, is asking for exactly this comparison.

    Both sides are machine-readable and the disagreement is arithmetic, so this
    stays inside the precision rule. If the sentence is ever rephrased the
    pattern stops matching and the probe SKIPS — silently agreeing would be the
    worse failure, so the skip is counted and printed like every other.
    """
    if not CLAUDE_MD.is_file():
        res.skip("CLAUDE.md absent")
        return
    m = _TALLY.search(CLAUDE_MD.read_text(encoding="utf-8"))
    if m is None:
        res.skip("CLAUDE.md tally sentence did not match its pattern")
        return

    claimed = {
        "pending": int(m.group(1)), "resolved": int(m.group(2)),
        "vendor-blocked": int(m.group(3)), "wontfix": int(m.group(4)),
        "obsolete": int(m.group(5)),
    }
    claimed_total = int(m.group(6))

    items = queue_items()
    actual = {k: 0 for k in claimed}
    for it in items:
        s = it.get("status")
        if s in actual:
            actual[s] += 1
    res.compared += 1

    deltas = [f"{k}: doc {claimed[k]} vs file {actual[k]}"
              for k in claimed if claimed[k] != actual[k]]
    if claimed_total != len(items):
        deltas.append(f"total: doc {claimed_total} vs file {len(items)}")
    if not deltas:
        return

    res.findings.append(Finding(
        slug=f"{OBS_PREFIX}claude-md-backlog-tally",
        title=f"CLAUDE.md's backlog tally disagrees with the queue ({len(deltas)} field(s))",
        track="platform",
        refs="CLAUDE.md 'Security remediation backlog' · "
             "docs/llm/security/remediation-queue.json",
        body=(
            "CLAUDE.md quotes the remediation backlog inline and the numbers no "
            "longer match the file it names as authoritative:\n\n"
            + "\n".join(f"  - {d}" for d in deltas)
            + "\n\nThe document already warns that this line 'has been wrong "
            "twice by inheritance'. A quoted count is a copy, and a copy with "
            "no comparator drifts — which is the same defect the rest of this "
            "scanner looks for, in prose. Re-derive from the file, or stop "
            "quoting the numbers and point at it."
        ),
    ))


# ---------------------------------------------------------------------------

def file_rows(findings: list[Finding]) -> int:
    """POST rows the table does not already hold. HTTP only — no file writes."""
    req = urllib.request.Request(BASE + "/rows?limit=500", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        existing = {r["values"].get("slug")
                    for r in json.loads(resp.read())["data"]["rows"]}
    filed = 0
    for f in findings:
        if f.slug in existing:
            continue
        body = json.dumps({"values": {
            "slug": f.slug, "title": f.title, "parent": "", "when": 0,
            "status": "queued", "track": f.track, "release": "",
            "refs": f.refs, "body": f.body,
        }}).encode()
        r = urllib.request.Request(BASE + "/rows", data=body,
                                   headers=HEADERS, method="POST")
        with urllib.request.urlopen(r, timeout=30):
            filed += 1
    return filed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", action="store_true",
                    help="write findings as roadmap rows (default: report only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    res = ScanResult()
    try:
        images = running_images()
    except Exception as exc:
        # Exit 2, loudly. One side of every comparison is the live estate; if
        # it cannot be read, nothing was compared and reporting "no
        # contradictions" would be the defect this tool exists to find.
        print(f"[-] cannot read the running estate: {exc}", file=sys.stderr)
        print("[-] NOTHING WAS COMPARED. This is not a clean result.",
              file=sys.stderr)
        return 2

    probe_pin_vs_running(images, res)
    probe_queue_vs_running(images, res)
    probe_artefact_vs_repo(res)
    probe_doc_claim_vs_queue(res)

    if args.json:
        print(json.dumps({
            "compared": res.compared,
            "skipped": res.skipped,
            "findings": [f.__dict__ for f in res.findings],
        }, indent=2))
    else:
        print(f"compared {res.compared} pair(s) against {len(images)} running containers")
        for reason, n in sorted(res.skipped.items(), key=lambda kv: -kv[1]):
            print(f"  skipped {n:4d}  {reason}")
        for f in res.findings:
            print(f"\n  ! {f.title}\n    {f.refs}")
        print(f"\n{len(res.findings)} contradiction(s). "
              f"Skips are not agreements — {sum(res.skipped.values())} pair(s) "
              f"could not be compared exactly and were not judged.")

    if args.file and res.findings:
        print(f"filed {file_rows(res.findings)} new roadmap row(s)")

    return 1 if res.findings else 0


if __name__ == "__main__":
    sys.exit(main())
