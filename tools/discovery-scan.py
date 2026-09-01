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
import os
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
KEAP = "http://127.0.0.1:8091"
BASE = f"{KEAP}/api/tables/{TABLE}"
HEADERS = {
    "X-Authentik-Username": "akadmin",
    "X-Authentik-Email": "admin@pazny.eu",
    "X-Authentik-Groups": "nos-providers,nos-admins",
    "Content-Type": "application/json",
}

# Rows this tool files are prefixed so a reader can tell an OBSERVATION from a
# plan. The prefix survives now that `source` is live (verified 2026-08-08: the
# column exists with `agent-observation` among its options, and the rows carry
# it) because a slug is what a person reads in a list; `source` is what a query
# filters on. Both, not either.
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
    #: Slugs this run reached a VERDICT on, whether or not it found a
    #: contradiction. A slug in here and not in `findings` is a finding that has
    #: stopped reproducing. A slug in neither was never judged — see `judge`.
    judged: set[str] = field(default_factory=set)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def judge(self, slug: str) -> None:
        """Record that this run compared the pair `slug` names, and decided.

        THIS IS WHAT MAKES CLOSING SAFE, and it is the whole reason the
        stale-row report is not simply "the finding is absent this run". A
        finding can be absent because it was fixed, or because the probe SKIPPED
        it — an unreadable container, a fix_version that is prose, a prerelease
        suffix that will not compare. Treating the second as the first would let
        this tool retire a live contradiction, which is the failure it exists to
        catch, committed by the catcher.

        So a row is reported stale only when its slug is in here: the probe ran
        the comparison to completion and found nothing to report.
        """
        self.compared += 1
        self.judged.add(slug)


# ---------------------------------------------------------------------------
# Reading the two sides
# ---------------------------------------------------------------------------

_VERSION_VAR = re.compile(r"^([a-z0-9_]+)_version:\s*[\"']?([^\"'#\s]+)", re.MULTILINE)
# FULLMATCH, not a prefix match. The prefix version read REM-129's
# fix_version — "6.8.6 / 6.9.5 / 7.0.2 (none dockerized as of 2026-07-20)" —
# as 6.8.6 and reported a contradiction against a row that names three fix
# versions and says none of them ships in a container. That is exactly the
# guess this tool's precision rule forbids: an ambiguous comparison SKIPS.
#
# THE PRERELEASE SUFFIX IS PART OF THE VERSION, and this regex used to swallow
# it: the `(?:-…)?` group matched it and nothing read it back, so only group(1)
# was compared. `1.0.0-beta.11` and `1.0.0-beta.12` both reduced to (1, 0, 0).
# Measured 2026-08-09 — the scan reported, in its own words,
#   "REM-187 still pending; iiab-rustfs-1 already runs 1.0.0-beta.11 >= 1.0.0-beta.12"
# and filed two roadmap rows from it. The tool whose whole job is catching false
# records was producing one.
#
# The dangerous direction is the silent one. A swallowed suffix makes a BEHIND
# container read as EQUAL, so probe A stops reporting a pin that never reached
# its container, and probe B stops reporting a `resolved` row whose fix never
# landed — for every prerelease-tagged component. rustfs, the backup target, is
# exactly such a component. A false alarm gets read; a suppressed one does not.
_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)(?:-([a-z0-9.]+))?$", re.IGNORECASE)


# A `fix_version` is written by a human or an LLM for a human, so it is a
# SENTENCE as often as it is a version. `numeric()` refuses all of it, on the
# correct ground that prose beginning with a number is prose. Measured
# 2026-08-22 against the live estate: that refusal cost 49 of the 173 unjudged
# pairs, and the refused set splits three ways.
#
#   PROSE, and the refusal is right:
#       "latest" · "n/a (config change)" · "SEC-02 gate (arch mitigation)"
#       "hardening only (no CVE; pin is clean)" · "digest pin + post-start …"
#
#   A FLOOR, which is a version plus a claim about everything after it:
#       "1.24.7+"  "10.10.7+"  "0.59.1+"  "2026.3.02+"
#       gitea runs 1.27.1 against a floor of 1.24.7 — SATISFIED, and the row
#       still says pending. That is precisely the class this probe exists for,
#       and it was invisible because of a trailing plus sign.
#
#   A VERSION WITH DELIMITED COMMENTARY:
#       "8.6.3 (re-pin off EOL 8.0 branch)" · "7.0.2 (dockerized 2026-08-02)"
#       "version-6.6.3 (security floor) -- recommend …"
#
# WHAT THIS DOES NOT DO, and it is the whole safety argument. It does not relax
# `numeric()`. A wrong extraction manufactures a FALSE CONTRADICTION, and this
# file's standing position is that a skip is honest and a false alarm is not
# ("skips are not agreements" is printed on every run). So the delimiter must be
# unambiguous — a `(` or a ` -- ` — and anything else is left to skip. "1.2.3 or
# later if you can" does not parse here, deliberately.
_FLOOR = re.compile(r"^v?(\d+(?:\.\d+)+)\s*\+$")
_COMMENTED = re.compile(r"^(?:version-)?v?(\d+(?:\.\d+)+(?:-[a-z0-9.]+)?)\s*(?:\(|--\s)")
_PREFIXED = re.compile(r"^version-(\d+(?:\.\d+)+(?:-[a-z0-9.]+)?)$", re.IGNORECASE)

# A row can ask for something a VERSION COMPARISON cannot answer. REM-188 is
# the worked example: "SAME SEMVER, DIFFERENT IMAGE — base-layer drift a
# version pin cannot express", fix_version "11.8.8 (re-pull)". `_COMMENTED`
# read the 11.8.8 head and this probe reported "still pending; already runs
# 11.8.8 >= 11.8.8 (re-pull)" — a category error: satisfying the version is
# the row's PREMISE, not its remedy. Judging such a row means reading the
# registry's current digest for the tag, which is a network act this offline
# reader does not perform; the honest verdict is a named refusal.
_DIGEST_SHAPED = re.compile(
    r"\b(re-pull|digests?|base[- ]layer|same[- ]semver)\b", re.IGNORECASE)


def read_fix(raw: str) -> tuple["Version", bool] | None:
    """`fix_version` -> (version, is_floor), or None when it is not a version.

    `is_floor` matters: "1.24.7+" is satisfied by anything at or above it, while
    a bare "1.24.7" is a specific target and running 1.27.1 against it is a
    different statement. Collapsing the two would report every over-shooting
    estate as a contradiction.
    """
    text = raw.strip()
    exact = numeric(text)
    if exact is not None:
        return exact, False
    m = _FLOOR.match(text)
    if m:
        v = numeric(m.group(1))
        return (v, True) if v else None
    for pattern in (_COMMENTED, _PREFIXED):
        m = pattern.match(text)
        if m:
            v = numeric(m.group(1))
            if v is not None:
                return v, False
    return None


def read_tag(raw: str) -> "Version | None":
    """An image tag, allowing only the `version-` prefix `numeric()` rejects.

    Firefly tags `version-6.2.21`. A digest tag (`sha-b9a80dc`) still returns
    None and still skips — there is no version in it to read.
    """
    text = raw.strip()
    exact = numeric(text)
    if exact is not None:
        return exact
    m = _PREFIXED.match(text)
    return numeric(m.group(1)) if m else None


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


def at_ref(ref: str, relpath: str) -> str | None:
    """The file's content as `ref` holds it, or None if git can't answer.

    None means a new file, a detached state, a missing ref, no git at all —
    every one a reason to skip rather than to claim drift.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{ref}:{relpath}"],
        capture_output=True, text=True, timeout=30,
    )
    return out.stdout if out.returncode == 0 else None


def at_head(relpath: str) -> str | None:
    """The file's content as the CURRENT BRANCH holds it, or None."""
    return at_ref("HEAD", relpath)


# The scan artefacts live in TWO places by design, and disk legitimately matches
# either at different moments. The nightly scanner writes remediation-queue.json /
# scan-state.json and commits them to the `scan-data` branch; resolutions are then
# reviewed onto `dev`/HEAD. So at any instant disk may equal scan-data (fresh
# scan), OR HEAD (a checkout carrying reviewed resolutions scan-data has not caught
# up to). Probe C's real question is NOT "does disk match ONE chosen ref" — that
# manufactures a contradiction out of the intended lag in whichever direction the
# chosen ref happens to trail (measured 2026-08-12: disk 190 == scan-data 190,
# HEAD 188 → HEAD trailed; after a resolution commit scan-data trails instead).
# The genuine failure — the "one `git checkout` from gone" case — is disk matching
# NEITHER ref: scan output recorded nowhere in git. So we gather every baseline and
# fire only when disk equals none of them.
SCAN_DATA_REF = "scan-data"
SCAN_ARTEFACT_REFS = (SCAN_DATA_REF, "HEAD")


def scan_artefact_baselines(relpath: str) -> "list[tuple[str, str]]":
    """[(ref_name, content), …] for every ref that holds `relpath`.

    Empty when no ref answers (new file, detached, no git) — the caller then
    skips rather than claiming drift.
    """
    out = []
    for ref in SCAN_ARTEFACT_REFS:
        content = at_ref(ref, relpath)
        if content is not None:
            out.append((ref, content))
    return out


@dataclass(frozen=True)
class Version:
    """A release core plus an optional prerelease, ordered by semver rules.

    `pre is None` means a release. A release outranks any prerelease sharing
    its core (1.0.0 > 1.0.0-beta.12), and prereleases order by dot-separated
    identifier: numeric ones numerically, and numeric below alphanumeric.
    """

    core: tuple[int, ...]
    pre: tuple[tuple[int, int, str], ...] | None


def numeric(v: str) -> Version | None:
    """Only a WHOLE dotted-numeric version compares. Anything else skips.

    A leading-numeric match is not good enough: prose that begins with a
    version number is prose, and treating it as a version manufactures
    contradictions out of punctuation. A prerelease suffix is READ, not
    discarded — see the note on _VERSION.
    """
    m = _VERSION.fullmatch(v.strip())
    if not m:
        return None
    core = tuple(int(x) for x in m.group(1).split("."))
    suffix = m.group(2)
    if suffix is None:
        return Version(core, None)
    ids: list[tuple[int, int, str]] = []
    for part in suffix.lower().split("."):
        # (rank, number, text): rank 0 = numeric identifier, which semver puts
        # below any alphanumeric one. The unused slot stays neutral so the
        # tuples compare field-by-field without ever mixing int against str.
        ids.append((0, int(part), "") if part.isdigit() else (1, 0, part))
    return Version(core, tuple(ids))


# The only prerelease words this tool claims to know the order of. Everything
# else — dev, nightly, snapshot, canary, a date, a git sha — is a moving build
# whose position relative to the release is the vendor's convention, not ours.
_CHANNELS = {"alpha": 0, "beta": 1, "rc": 2}


def _channel(pre: tuple[tuple[int, int, str], ...]) -> str | None:
    """The leading identifier when it is a word; None when it is a number."""
    kind, _, text = pre[0]
    return text if kind == 1 else None


def compare(a: Version, b: Version) -> int | None:
    """-1 / 0 / +1, or None when the two are not comparable.

    Cores are zero-padded, so 2.44 == 2.44.0. Where the cores differ they
    decide outright — a prerelease of 1.0.0 is below 1.1.0 either way.

    Same core, and the suffixes have to be honest about their limits:
      * neither has one          -> equal
      * only one has one         -> NOT COMPARABLE. Whether `6.0.0-dev` is a
                                    build BEFORE 6.0.0 or a dev build cut AFTER
                                    it is the vendor's convention. Semver says
                                    below; Docker tagging very often means
                                    above. Refuse rather than guess — this is
                                    the same rule that makes prose skip.
      * same channel word        -> the rest decides (beta.11 < beta.12)
      * both channels known      -> alpha < beta < rc
      * anything else            -> NOT COMPARABLE
    """
    width = max(len(a.core), len(b.core))
    ca = a.core + (0,) * (width - len(a.core))
    cb = b.core + (0,) * (width - len(b.core))
    if ca != cb:
        return -1 if ca < cb else 1
    if a.pre is None and b.pre is None:
        return 0
    if a.pre is None or b.pre is None:
        return None
    cha, chb = _channel(a.pre), _channel(b.pre)
    if cha == chb:
        if a.pre == b.pre:
            return 0
        return -1 if a.pre < b.pre else 1
    if cha in _CHANNELS and chb in _CHANNELS:
        return -1 if _CHANNELS[cha] < _CHANNELS[chb] else 1
    return None


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
        verdict = compare(have, want)
        if verdict is None:
            res.skip("prerelease suffix not comparable to the other side")
            continue
        res.judge(f"{OBS_PREFIX}pin-{var.replace('_', '-')}")
        if verdict == 0:
            continue
        direction = "BEHIND" if verdict < 0 else "AHEAD OF"
        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}pin-{var.replace('_', '-')}",
            title=f"{name} runs {tag}, pinned {declared}",
            # `verdict`, not `have < want`: Version carries a prerelease suffix
            # and deliberately has no ordering operators, because two suffixes
            # are not always comparable — that is what compare() returning None
            # means, and it is handled above. This line was left behind by the
            # refactor that introduced compare(), and it crashed the whole scan
            # (TypeError) rather than any one probe, so nothing ran at all.
            track="security" if verdict < 0 else "platform",
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
        if _DIGEST_SHAPED.search(str(fix)):
            res.skip("row wants a digest comparison, not a version — not judged")
            continue
        # `security_floor` is the machine-comparable half of a prose
        # `fix_version`. REM-159 is why it exists: one field carried a security
        # floor AND a regression floor ("19.2.2-ce.0 (or 18.11.9-ce.0 for the
        # non-security regression fixes only)"), and the closing pass picked the
        # branch the row's own text disclaims. When the writer has said which
        # version is load-bearing, read that and nothing else.
        floor_field = item.get("security_floor")
        if floor_field is not None:
            parsed = read_fix(str(floor_field))
            if parsed is None:
                res.skip("security_floor present but not strictly readable")
                continue
        else:
            parsed = read_fix(str(fix))
        fix = floor_field if floor_field is not None else fix
        have = read_tag(tag or "")
        if tag is None or parsed is None or have is None:
            res.skip("queue or image version not strictly numeric")
            continue
        want, is_floor = parsed
        verdict = compare(have, want)
        if verdict is None:
            res.skip("prerelease suffix not comparable to the other side")
            continue
        res.judge(f"{OBS_PREFIX}queue-{item['id'].lower()}")

        # A FLOOR NEEDS NO SPECIAL CASE, and the first cut of this got it wrong
        # by adding one. `fix_version: "1.24.7+"` means "at or above", and both
        # branches below already test INEQUALITY rather than equality — a
        # resolved row is a finding only when the estate is BELOW (`< 0`), a
        # pending row only when it is at or above (`>= 0`). Over-shooting a
        # floor was never reported. The guard written here first also suppressed
        # `resolved` + below-floor, which is a real contradiction: the fix never
        # reached the estate. `is_floor` is therefore read, recorded and
        # deliberately not branched on.
        _ = is_floor

        if status == "resolved" and verdict < 0:
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
        elif status == "pending" and verdict >= 0:
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

    Disk is compared against every baseline ref (scan-data, HEAD); it is safe as
    long as it matches ONE — the artefact is then recorded in git and no
    `git checkout` erases it. Only when disk matches NONE is it genuinely
    uncommitted. Byte equality is the whole comparison, so there is nothing to
    guess.
    """
    for rel in HOST_WRITTEN:
        path = REPO / rel
        if not path.is_file():
            res.skip("host-written artefact absent from this checkout")
            continue
        baselines = scan_artefact_baselines(rel)
        if not baselines:
            res.skip("artefact not tracked at scan-data or HEAD")
            continue
        live = path.read_text(encoding="utf-8")
        res.judge(f"{OBS_PREFIX}uncommitted-{Path(rel).stem}")
        if any(live == content for _, content in baselines):
            continue  # recorded in git somewhere — not one checkout from gone

        # Matches no ref. A row-count delta against each, when parseable — the
        # divergence stands on its own, so a parse failure must not suppress it.
        def _n(text: str) -> "int | str":
            try:
                d = json.loads(text)
                return len(d if isinstance(d, list) else d.get("items", []))
            except Exception:
                return "?"
        refs_seen = ", ".join(f"{name} {_n(content)}" for name, content in baselines)
        detail = f" ({_n(live)} rows on disk; {refs_seen})"

        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}uncommitted-{Path(rel).stem}",
            title=f"{Path(rel).name} on disk matches no committed ref{detail}",
            track="security",
            refs=f"{rel} · git show {SCAN_DATA_REF}:{rel}",
            body=(
                f"A nightly job writes {rel}; it is committed to the {SCAN_DATA_REF} "
                f"branch and resolutions are reviewed onto HEAD. This working "
                f"tree's copy{detail} matches NEITHER — so this scan output exists "
                f"only here, is invisible on every branch, never reaches CI, and "
                f"is one `git checkout` from gone. Commit it to {SCAN_DATA_REF} "
                f"(fresh scan) or review the resolutions onto HEAD."
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
    doc = CLAUDE_MD.read_text(encoding="utf-8")
    m = _TALLY.search(doc)
    if m is None:
        # THE DOCUMENT STOPPED CACHING THE NUMBER (2026-08-07). It now names
        # `tools/rem-status.py` instead, which is the structural cure for the
        # defect this probe was written to catch: a moving value cannot go
        # stale in a document that does not hold it.
        #
        # So the check does not disappear, it INVERTS. A skip here forever
        # would be a probe quietly measuring nothing; instead the delegation
        # itself is now the thing asserted, and re-adding a hand-written tally
        # — or dropping the pointer — puts the estate back where it was.
        if "rem-status.py" in doc:
            res.judge(f"{OBS_PREFIX}claude-md-backlog-tally")
            return
        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}claude-md-backlog-tally",
            title="CLAUDE.md neither quotes the backlog nor points at the query",
            track="platform",
            refs="CLAUDE.md 'Security remediation backlog' · tools/rem-status.py",
            body=(
                "The tally sentence is gone and `tools/rem-status.py` is not named.\n\n"
                "The paragraph carried the counts inline for four months and was wrong "
                "three times; the cure was to stop caching a moving value and delegate "
                "to a query. Losing the pointer as well leaves a reader with neither a "
                "number nor a way to get one, which is worse than the stale number was."
            ),
        ))
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
    res.judge(f"{OBS_PREFIX}claude-md-backlog-tally")

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

def _agent_token() -> str:
    """The RW agent token, from the pulse job's env (see the plugin manifest).

    Absent, this tool files through the human door instead — which still records
    the finding, and says so. A scan that refused to report because a token was
    missing would lose the observation to protect a row id.
    """
    return os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip()


def file_rows(findings: list[Finding]) -> int:
    """POST rows the table does not already hold. HTTP only — no file writes.

    THROUGH THE AGENT DOOR, AND THE DOOR IS THE POINT (fixed 2026-08-08).

    A KEAP row has two names: the id it is addressed by, and what its `slug`
    cell says. The human API mints a UUID id; the agent API uses the slug. And
    the agent API's upsert — the ONLY way to update a row, since the human API
    has no update at all — keys on the ID. So every row this tool filed through
    the human door was unreachable by any later write: an "upsert" against it
    matched nothing and inserted a duplicate.

    Measured that day: all 68 roadmap rows carried UUID ids and not one had ever
    been updated since it was filed. Seven of them were this tool's.

    So the rows go through the agent door, where the id is the slug and a later
    correction can actually land. If no token is available the human door is
    used and the caller is told, because losing the finding would be worse than
    filing one that needs `tools/keap-reid-rows.py` afterwards.
    """
    req = urllib.request.Request(BASE + "/rows?limit=500", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        existing = {r["values"].get("slug")
                    for r in json.loads(resp.read())["data"]["rows"]}
    token = _agent_token()
    filed = 0
    for f in findings:
        if f.slug in existing:
            continue
        # No date. An observation has no target (nobody has scheduled it) and no
        # landing (nothing happened). The column this used to fill was `when: 0`
        # — epoch, rendered as a date, meaning nothing.
        values = {
            "slug": f.slug, "title": f.title, "parent": "",
            "status": "queued", "track": f.track, "release": "",
            "refs": f.refs, "body": f.body, "source": "agent-observation",
        }
        if token:
            r = urllib.request.Request(
                f"{KEAP}/agent/v1/tables/{TABLE}/rows",
                data=json.dumps(values).encode(), method="POST",
                headers={"authorization": f"Bearer {token}",
                         "content-type": "application/json"})
        else:
            r = urllib.request.Request(BASE + "/rows",
                                       data=json.dumps({"values": values}).encode(),
                                       headers=HEADERS, method="POST")
        with urllib.request.urlopen(r, timeout=30):
            filed += 1
    if filed and not token:
        print("  note: filed through the human API (no KEAP_AGENT_TOKEN_RW), so "
              "these rows are keyed by UUID and cannot be updated until "
              "`tools/keap-reid-rows.py --apply` runs.", file=sys.stderr)
    return filed


# ---------------------------------------------------------------------------
# Probe E — what the operator SWITCHED OFF vs what is still running
# ---------------------------------------------------------------------------

def resolved_install_flags(default_path: Path | None = None,
                           override_path: Path | None = None) -> dict[str, str]:
    """`install_*` flags resolved across the documented config layering.

    default.config.yml is the committed default; config.yml (gitignored,
    operator-owned) overrides it — the same order main.yml's vars_files
    declares. The override wins where both declare a flag, and a flag declared
    only in config.yml is seen too: that is exactly the shape of an operator
    switching OFF something the default ships ON.

    WHY THIS FUNCTION EXISTS AS A FUNCTION. Probe E's first run (2026-08-10)
    read the committed default alone, and on any host carrying a config.yml
    that inverts the verdict twice over: services config.yml ENABLES read as
    "switched off but running" (expected drift reported as contradiction —
    sixteen of them here), while the one service the operator genuinely
    switched off (install_mailpit: false, container up) was invisible. The
    wrong sixteen then propagated into docs/hidden_fees/01 and three queue
    amendments before anyone re-derived it. Gate:
    tests/anatomy/test_discovery_probe_reads_resolved_config.py.
    """
    default_path = CONFIG if default_path is None else default_path
    override_path = (REPO / "config.yml") if override_path is None else override_path
    flags: dict[str, str] = {}
    for path in (default_path, override_path):
        if not path.exists():
            continue
        for m in re.finditer(r"^install_([a-z0-9_]+):\s*(\S+)",
                             path.read_text(encoding="utf-8"), re.MULTILINE):
            flags[m.group(1)] = m.group(2).strip().strip('"\'')
    return flags


def probe_disabled_vs_running(images: dict[str, str], res: ScanResult) -> None:
    """`install_<svc>: false` (RESOLVED across the config layering) while the
    container is up.

    docs/hidden_fees/01 records the mechanism and calls it open: the role render
    path is create-only, so a disabled service's compose override stays on disk
    and keeps being merged into `docker compose up`. Measured honestly for the
    first time 2026-08-10, after the layering fix in resolved_install_flags():
    ONE service on this host — mailpit, switched off in the operator's
    config.yml, both fragments still on disk, iiab-mailpit-1 up. (The same
    day's first draft read only default.config.yml and reported sixteen; every
    one of those is enabled in config.yml and running legitimately.)

    WHY IT BELONGS IN THE SECURITY SCANNER AND NOT ONLY IN THE FEE LEDGER. Nine
    rows in the remediation queue argue mitigation from exactly this flag —
    "MITIGATED: install_gitlab=false" — and three of them are HIGH. A row that
    downgrades its own severity on the strength of a flag whose RESOLVED value
    is true is measuring the wrong layer; a row whose resolved value is false
    while the container runs is an open exposure that has been talked out of
    being counted. This probe now distinguishes the two.
    """
    # DERIVED, not restated: main.yml's "Auto-enable …" tasks flip some flags to
    # true at run time from other flags, so `false` in default.config.yml is the
    # correct DEFAULT for them and a running container is no contradiction at
    # all. Reading the list from main.yml means a fourth auto-enabled dependency
    # needs no edit here. The first run of this probe reported install_postgresql
    # as a finding, which is exactly the noise this tool's own docstring says
    # gets a detector muted.
    auto = set(re.findall(r"^\s*(install_[a-z0-9_]+|redis_docker):\s*true\s*$",
                          (REPO / "main.yml").read_text(encoding="utf-8"), re.MULTILINE))
    live: list[tuple[str, str, str]] = []
    for var, declared in sorted(resolved_install_flags().items()):
        if declared not in ("false", "no"):
            continue
        if f"install_{var}" in auto:
            res.skip("flag is auto-enabled from another flag at run time")
            continue
        # A Tier-2 manifest app is brought up by apps_runner from apps/<name>.yml,
        # not by this toggle, so the toggle is not the thing that would have
        # switched it off. Comparing them is the ambiguity this tool skips on.
        if (REPO / "apps" / f"{var}.yml").exists():
            res.skip("manifest app — apps/<name>.yml owns bring-up, not the toggle")
            continue
        res.compared += 1   # per-var; the CLASS verdict is judged after the loop
        hit = container_for(var, images)
        if hit is not None:
            live.append((var, hit[0], hit[1]))

    # Judged AFTER the loop, because the finding is one row for the CLASS.
    # Reaching here means every toggle was resolved and every container looked
    # up, so an empty `live` is a real "no longer reproduces".
    res.judge(f"{OBS_PREFIX}disabled-services-still-running")
    if not live:
        return

    # ONE finding for the CLASS, not one per instance. The fee is a single
    # mechanism with N victims, and filing N rows would bury the roadmap under
    # one defect wearing sixteen names — the opposite of what a triage surface
    # is for. The instances travel in the body, where they can be re-counted.
    listing = "\n".join(f"  install_{v}: false -> {n} ({i})" for v, n, i in sorted(live))
    res.findings.append(Finding(
        slug=f"{OBS_PREFIX}disabled-services-still-running",
        title=f"{len(live)} service(s) declared false are running",
        track="security",
        refs="default.config.yml + config.yml (resolved) · docker ps · docs/hidden_fees/01",
        body=(
            f"{len(live)} service(s) carry install_<svc>: false RESOLVED "
            "across default.config.yml + config.yml (the operator's override "
            "layer wins) and have a container up right now:\n\n"
            f"{listing}\n\n"
            "MECHANISM, already recorded and still open: docs/hidden_fees/01. The "
            "role render path is create-only — each role writes "
            "stacks/<stack>/overrides/<svc>.yml and NOTHING removes a fragment, "
            "so the orchestrator keeps merging the override written on the "
            "converge that had the service ON. The retired case was closed "
            "2026-07-20 (nos_retired_services + prune-retired.yml); the DISABLED "
            "case was left, because it is the one that does not fail loudly.\n\n"
            "WHY THIS IS A SECURITY ROW AND NOT ONLY A TIDINESS ONE. Rows in the "
            "remediation queue argue mitigation from this exact flag — "
            "'MITIGATED: install_gitlab=false' — and some of them are HIGH. A row "
            "that lowers its own severity because a service is 'disabled' is an "
            "open exposure that has been talked out of being counted. Before "
            "trusting any queue row's disposition for these components, re-read "
            "it against this list."
        ),
    ))


# ---------------------------------------------------------------------------
# Probe F — a route that declares "the service gates itself", and does not
# ---------------------------------------------------------------------------

def probe_declared_gate_actually_exists(res: ScanResult) -> None:
    """`traefik_auth_modes: oidc` asserts the service's OWN login offers Authentik.

    That assertion buys something real: no forward-auth middleware is attached,
    because stacking one on a native_oidc service is the documented double-login
    anti-pattern. The estate has a gate for the stacking half
    (test_forward_auth_does_not_stack.py) and CLAUDE.md names, in that gate's own
    words, what it cannot cover: "a native_oidc claim whose upstream OIDC does
    not exist (FreeScout)".

    That blind spot became a HIGH on 2026-08-11 (REM-192). FreeScout was marked
    `oidc`, so its edge carried no middleware, while the freescout-oauth module
    404s at both upstreams — /login served a bare local email+password form to
    the internet. Four files said gated; the login page said otherwise.

    So this asks the login page. A service claiming `oidc` whose page offers a
    PASSWORD FIELD and NO Authentik/OAuth affordance is claiming a gate it does
    not have.

    DELIBERATELY CONSERVATIVE. Unreachable is a SKIP, never a finding — half the
    estate is off on any given host. A page with no password field is a skip too:
    plenty of services answer 200 with a redirect shell or an SPA, and guessing
    from an empty page is the noise that gets a detector muted.
    """
    manifest = REPO / "state/manifest.yml"
    tvars = REPO / "roles/pazny.traefik/vars/main.yml"
    if not manifest.exists() or not tvars.exists():
        res.skip("manifest or traefik vars absent")
        return
    try:
        import yaml  # noqa: PLC0415 — optional dep; absence must skip, not crash
    except ImportError:
        res.skip("pyyaml absent — the declared-gate probe did not run")
        return

    modes = (yaml.safe_load(tvars.read_text(encoding="utf-8")) or {}).get("traefik_auth_modes") or {}
    rows = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    rows = rows.get("services", rows)
    rows = rows if isinstance(rows, list) else list(rows.values())
    cfg = CONFIG.read_text(encoding="utf-8")

    #: A page that offers a local password AND nothing Authentik-shaped.
    pw = re.compile(r"""(type=["']password|name=["']password)""", re.I)
    sso = re.compile(r"(authentik|oauth|openid|oidc|single.sign|sign in with)", re.I)

    for row in rows:
        sid = row.get("id")
        if not sid or modes.get(sid) != "oidc":
            continue
        port_var = row.get("port_var")
        m = re.search(rf"^{re.escape(str(port_var))}:\s*(\d+)", cfg, re.MULTILINE) if port_var else None
        if not m:
            res.skip("no loopback port for the declared-oidc service")
            continue
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{m.group(1)}/login",
                headers={"User-Agent": "nos-discovery-scan"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                body = resp.read(60000).decode("utf-8", "replace")
        except Exception:
            # Unreachable, redirecting off-host, or no /login. Not a finding.
            res.skip("declared-oidc service did not serve a readable /login")
            continue

        res.judge(f"{OBS_PREFIX}gate-claimed-not-offered-{sid.replace('_', '-')}")
        if not pw.search(body):
            res.skip("declared-oidc /login has no password field to judge")
            continue
        if sso.search(body):
            continue  # a local form beside an Authentik button is normal
        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}gate-claimed-not-offered-{sid.replace('_', '-')}",
            title=f"{sid} is marked oidc but its login page offers no Authentik",
            track="security",
            refs=f"roles/pazny.traefik/vars/main.yml traefik_auth_modes.{sid} · "
                 f"127.0.0.1:{m.group(1)}/login · docs/idea (SSO trichotomy)",
            body=(
                f"traefik_auth_modes.{sid} is `oidc`, which asserts the service's "
                "OWN login page gates the user — and on that assertion the edge "
                "router is rendered WITHOUT authentik@file. The page served on "
                f"the loopback port carries a password field and no Authentik, "
                "OAuth, OIDC or 'sign in with' affordance anywhere in the first "
                "60 KB.\n\n"
                "If that is right, the route is open onto a local credential "
                "form. The fix is usually the CLASSIFICATION rather than a hunt "
                "for the missing module: set traefik_auth_modes to `proxy` (this "
                "map's word for forward-auth) and flip the plugin's "
                "authentik.mode/provider_type to forward_auth, dropping "
                "redirect_uris and scopes. That is what closed REM-192 for "
                "freescout on 2026-08-11.\n\n"
                "If it is WRONG — the page is a shell and the real login is "
                "elsewhere — say so here rather than muting the probe, because "
                "the next reader will ask the same question."
            ),
        ))


# ---------------------------------------------------------------------------
# Probe G — `healthy` vs actually reachable from the host
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTPError, i.e. into "it answered"."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None

    opener = urllib.request.build_opener()


_NoRedirect.opener = urllib.request.build_opener(_NoRedirect)


def probe_healthy_but_unreachable(images: dict[str, str], res: ScanResult) -> None:
    """Docker says healthy; the published port answers nothing.

    MEASURED 2026-08-11 on paperclip, which had been `Up 47 hours (healthy)`
    while every host request was closed on connect. The app bound 127.0.0.1
    INSIDE the container (a wizard-written config.json in the persisted volume
    declared `server.bind: loopback`, outranking the compose env), Docker's port
    forward targeted eth0 where nothing listened, and the healthcheck curled
    `localhost` — the one address that worked. Every signal was green and the
    service was unreachable.

    WHY THIS IS A PROBE AND NOT A GATE. 34 compose templates in this estate
    healthcheck via localhost, and for almost all of them that is FINE: a
    service that binds 0.0.0.0 is correctly proven alive by a loopback request.
    Banning the pattern would fail 34 files to catch one, and a gate that cries
    that loudly gets deleted. Whether the bind is actually wrong is a live fact,
    so it is measured live.

    SCOPE, deliberately narrow. Only services the manifest routes over HTTP
    (they carry a `domain_var`), only those Docker currently calls `healthy`,
    and only their loopback-published port. A finding means the two disagree:
    the container claims health and the host cannot get a single HTTP status
    line out of it. Any status — 200, 401, 500 — counts as reachable, because
    the question is transport, not content.
    """
    manifest = REPO / "state/manifest.yml"
    if not manifest.exists():
        res.skip("manifest absent — reachability not checked")
        return
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        res.skip("pyyaml absent — reachability not checked")
        return

    rows = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    rows = rows.get("services", rows)
    rows = rows if isinstance(rows, list) else list(rows.values())
    cfg = CONFIG.read_text(encoding="utf-8")

    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "health=healthy", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30)
        healthy = {n.strip() for n in out.stdout.splitlines() if n.strip()}
    except (subprocess.SubprocessError, OSError):
        res.skip("could not list healthy containers")
        return

    for row in rows:
        sid, port_var = row.get("id"), row.get("port_var")
        if not sid or not port_var or not row.get("domain_var"):
            continue
        hit = container_for(sid, images)
        if hit is None or hit[0] not in healthy:
            continue  # not running, or not claiming health — nothing to contradict
        m = re.search(rf"^{re.escape(str(port_var))}:\s*(\d+)", cfg, re.MULTILINE)
        if not m:
            res.skip("healthy service has no loopback port declared")
            continue

        port = m.group(1)
        res.judge(f"{OBS_PREFIX}healthy-unreachable-{sid.replace('_', '-')}")
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/",
                                         headers={"User-Agent": "nos-discovery-scan"})
            # REDIRECTS ARE NOT FOLLOWED, and that is the whole correctness of
            # this probe. The first draft used a plain urlopen: wordpress and
            # gitlab both answer 301 to `https://<domain>/`, urllib chased it
            # off-box, the chase failed, and the probe reported two healthy,
            # perfectly reachable services as answering nothing. The question
            # here is TRANSPORT — did anything speak HTTP back — so a 301 is a
            # yes, and following it asks a different question badly.
            _NoRedirect.opener.open(req, timeout=6).read(1)
            continue                      # answered
        except urllib.error.HTTPError:
            continue                      # 3xx/4xx/5xx is still an answer
        except Exception as exc:          # noqa: BLE001 — transport failure is the finding
            detail = f"{type(exc).__name__}: {exc}"

        res.findings.append(Finding(
            slug=f"{OBS_PREFIX}healthy-unreachable-{sid.replace('_', '-')}",
            title=f"{hit[0]} is healthy and answers nothing on 127.0.0.1:{port}",
            track="security",
            refs=f"docker ps (health=healthy) · 127.0.0.1:{port} · docs/hidden_fees/02",
            body=(
                f"Docker reports {hit[0]} healthy, and a plain HTTP request to its "
                f"published port 127.0.0.1:{port} produced no status line at all "
                f"({detail}).\n\n"
                "The two cannot both be right. The usual cause is a healthcheck "
                "that probes `localhost` INSIDE the container while the service "
                "binds only the loopback there — the check then measures the one "
                "address nobody reaches through. paperclip sat in exactly this "
                "state for at least 47 hours on 2026-08-11 and the fix was two "
                "parts: bind the container's real interface, and make the "
                "healthcheck request the address Docker's port forward targets "
                "(`hostname -i | awk '{print $1}'` — it prints several when the "
                "container is on several networks).\n\n"
                "Check the bind first: `docker exec <c> cat /proc/net/tcp` and "
                "read the listening address. A config file in a persisted volume "
                "can outrank the compose environment, which is what made this "
                "survive a converge."
            ),
        ))


def open_obs_rows() -> dict[str, str]:
    """Every `obs-` row this tool has filed that is still open, slug -> status.

    Returns {} when the table cannot be read, and the caller says so rather than
    reporting "nothing is stale" — the same rule the rest of the tool follows.
    """
    req = urllib.request.Request(BASE + "/rows?limit=500", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read())["data"]["rows"]
    return {v["slug"]: v.get("status", "")
            for r in rows if (v := r["values"]).get("slug", "").startswith(OBS_PREFIX)
            and v.get("status") not in ("shipped", "dropped")}


def stale_rows(res: ScanResult, open_rows: dict[str, str]) -> dict[str, str]:
    """Filed rows whose finding this run compared and did NOT reproduce.

    `s in res.judged` is the load-bearing half. Without it this would report
    every filed row the scan happened not to re-emit — including the ones it
    SKIPPED because a version was prose or a container was unreadable — and the
    tool would recommend retiring live contradictions.

    REM-188 is the worked example: `fix_version: "11.8.8 (re-pull)"` is prose, so
    the probe skips it, so its slug is never judged, so it is never reported
    stale — even though the running tag equals the fix and a naive comparison
    would call it agreement.
    """
    found = {f.slug for f in res.findings}
    return {s: st for s, st in open_rows.items()
            if s in res.judged and s not in found}


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
    probe_disabled_vs_running(images, res)
    probe_declared_gate_actually_exists(res)
    probe_healthy_but_unreachable(images, res)

    # WHAT STOPPED REPRODUCING. This tool was write-once — `file_rows` skips a
    # slug that already exists — so it could open a finding and never close one.
    # Measured 2026-09-01: four of its `obs-queue-rem-*` rows described a queue
    # that had since been reconciled, and one described a CLAUDE.md that had
    # already stopped quoting the numbers it complained about. The contradiction
    # finder was itself holding records that had stopped being true, which is
    # the defect it exists to find, in its own output.
    #
    # It still does not close them. Closing stays a deliberate act with the
    # evidence written into the row (CLAUDE.md, "Security remediation backlog").
    # What changes is that the estate can now be ASKED which rows are candidates
    # instead of someone re-deriving it by hand, four containers at a time.
    stale: dict[str, str] = {}
    obs_error: str | None = None
    try:
        stale = stale_rows(res, open_obs_rows())
    except Exception as exc:  # noqa: BLE001 — an unreadable table is UNKNOWN
        obs_error = str(exc)

    if args.json:
        print(json.dumps({
            "compared": res.compared,
            "skipped": res.skipped,
            "findings": [f.__dict__ for f in res.findings],
            "judged": sorted(res.judged),
            "no_longer_reproducing": sorted(stale),
            "obs_rows_error": obs_error,
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

        if obs_error:
            print(f"\n  UNKNOWN — could not read the filed rows: {obs_error}")
            print("  Nothing is claimed about which findings have stopped "
                  "reproducing.")
        elif stale:
            print(f"\n{len(stale)} filed row(s) NO LONGER REPRODUCE — this run "
                  f"compared each pair and found them in agreement:")
            for slug, status in sorted(stale.items()):
                print(f"  [{status}] {slug}")
            print("  Not closed here. Close deliberately, with the reading "
                  "written into the row.")

    if args.file and res.findings:
        print(f"filed {file_rows(res.findings)} new roadmap row(s)")

    return 1 if res.findings else 0


if __name__ == "__main__":
    sys.exit(main())
