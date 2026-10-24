#!/usr/bin/env python3
"""What is TRUE right now, across the three places a fact about nOS can live.

    the running host   ·   this checkout (+ its branches)   ·   origin (+ its branches)

WHY THIS EXISTS, and it is measured rather than argued. On 2026-08-10 one session
made the same mistake three times in one day, each time hand-deriving "what is
true now" from a partial source:

  * KEAP: read the local checkout (v1.36.0) and reported it as the estate's
    version. The DEPLOYED KEAP was v1.39.0 — three releases ahead, for a week,
    and both were correct because the repo is not the running system.
  * config: read `install_gitlab: false` from default.config.yml and reported
    sixteen services as "switched off but running". All sixteen are `true` in
    config.yml, the documented override layer. The verdict was inverted twice
    over — the sixteen were false alarms, and the ONE genuinely-off running
    service was invisible.
  * git: read a LOCAL `master` ref that was 188 commits behind origin and
    reported a release as never having landed. It had, eight days earlier.

Three instances, one failure. The estate already solved this class once, for the
security queue, and CLAUDE.md says so in the tool's own voice: *"This line no
longer carries the numbers — ask instead: tools/rem-status.py"*. This is that
medicine applied to state.

THREE RULES THIS TOOL IS BUILT ON, each from something the survey found:

  1. ASK THE RUNNING SYSTEM, NOT THE DISK. A health endpoint beats a VERSION
     file beats a git ref. Disk says what was copied there; the port says what
     is serving. Where an organ cannot answer, this prints "not reported" — an
     absence, never a guess.

  2. A FLOATING PIN IS A FINDING, NOT A BLANK. `node_nvm_version: "lts/*"` and a
     `:latest` tag cannot disagree with anything, so they can never warn you.
     Rendering them as "match" would be the calm-by-absence defect this estate
     keeps finding in its own gates.

  3. AN INTENTIONAL DIFFERENCE CARRIES ITS REASON. ansible-core is 2.20.5 on
     this host and 2.21.0 in the frozen CI venv ON PURPOSE. Printed bare it
     reads as drift and someone "fixes" it. Every known split names where the
     reasoning is written down.

FETCH IS ON BY DEFAULT. A stale ref is the failure this tool exists to stop, and
an unfetched comparison is worse than no comparison because it looks like one.
`--no-fetch` exists for offline use and SAYS SO in the output.

Exit codes
----------
  0  every comparison made agreed, or was honestly reported as uncomparable
  1  at least one real disagreement
  2  a side could not be read — NOTHING was compared on that axis
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ── the three places ────────────────────────────────────────────────────────

REPOS = [
    ("nOS", REPO),
    ("KEAP", REPO.parent / "knowledge-explorer-and-preserver"),
]

#: An organ and every way it can be asked what it is. Ordered by trust:
#: the port first, then a stamp on disk, then a git ref. `version_keys` are
#: searched in the health payload (top level and under `data`).
ORGANS = [
    {"name": "keap", "url": "http://127.0.0.1:8091/agent/v1/health",
     "version_keys": ("version",), "src": Path.home() / "keap/src",
     "repo_version": ("KEAP", "package.json")},
    {"name": "cortex", "url": "http://127.0.0.1:8098/agent/v1/health",
     "version_keys": ("version", "build"), "src": None,
     "repo_version": ("nOS", "files/anatomy/cortex/package.json")},
    {"name": "face", "url": None,
     "version_keys": (), "src": Path.home() / "face/src",
     "repo_version": ("nOS", "files/anatomy/face/package.json")},
    {"name": "bone", "url": "http://127.0.0.1:8099/api/health",
     "version_keys": ("git_ref",), "src": None, "repo_version": None,
     "compare_ref": True},
    {"name": "wing", "url": "http://127.0.0.1:9000/api/v1/hub/health",
     "version_keys": ("git_ref",), "src": None, "repo_version": None,
     "compare_ref": True},
]

#: Host tool -> how to read its version, and what declares it.
TOOLCHAIN = [
    {"tool": "python", "cmd": ["python3", "-V"], "pin_file": ".python-version",
     "pin_re": r"^\s*([0-9.]+)\s*$"},
    {"tool": "ansible-core", "cmd": ["ansible", "--version"],
     "pin_file": "tools/ci-freeze.env", "pin_re": r'NOS_ANSIBLE_CORE="[^=]+==([0-9.]+)"'},
    {"tool": "node", "cmd": ["node", "-v"], "pin_file": "defaults",
     "pin_re": r'^node_nvm_version:\s*"([^"]+)"'},
    {"tool": "ollama", "cmd": ["ollama", "--version"], "pin_file": "defaults",
     "pin_re": r'^ollama_version:\s*"?([0-9.]+)"?'},
    {"tool": "docker", "cmd": ["docker", "--version"], "pin_file": None, "pin_re": None},
]

#: Differences that are DELIBERATE. Keyed by tool; the value says what the split
#: is and WHERE the reasoning lives, so nobody closes it as drift. A split that
#: stops matching reality is reported as drift like anything else — this table
#: excuses one specific pair of values, not the whole comparison.
KNOWN_SPLITS = {
    "ansible-core": {
        "host": "2.20.5", "pin": "2.21.0",
        "why": "the operator's daily driver stays 2.20.5; 2.21.0 is the frozen "
               "CI mirror (the GitHub runner's filter-load path needs a 2.21 "
               "symbol). Reasoning: tools/ci-freeze.env header + docs/git-and-release.md "
               "§Frozen integration toolchain.",
    },
}

#: A pin that cannot disagree with anything. Rule 2: these are reported, never
#: scored as agreement.
FLOATING = re.compile(r"^(latest|main|lts/\*|\*|stable|edge|nightly|dev)$", re.I)

OK, DISAGREE, UNREADABLE = "ok", "disagree", "unreadable"


@dataclass
class Line:
    axis: str
    subject: str
    detail: str
    state: str = OK


@dataclass
class Result:
    lines: list[Line] = field(default_factory=list)
    uncomparable: list[str] = field(default_factory=list)

    def add(self, axis: str, subject: str, detail: str, state: str = OK) -> None:
        self.lines.append(Line(axis, subject, detail, state))

    @property
    def disagreements(self) -> list[Line]:
        return [x for x in self.lines if x.state == DISAGREE]

    @property
    def unreadable(self) -> list[Line]:
        return [x for x in self.lines if x.state == UNREADABLE]


# ── readers ─────────────────────────────────────────────────────────────────


def git(repo: Path, *args: str, timeout: int = 60) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def http_json(url: str, timeout: int = 4) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read(20000).decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def first_key(payload: dict, keys: tuple[str, ...]) -> str | None:
    """Search the envelope and its `data` member — both shapes are in use."""
    for scope in (payload, payload.get("data") if isinstance(payload.get("data"), dict) else {}):
        for k in keys:
            v = (scope or {}).get(k)
            if isinstance(v, (str, int, float)):
                return str(v)
    return None


def host_version(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", out.stdout + out.stderr)
    return m.group(0) if m else None


def declared(pin_file: str | None, pin_re: str | None) -> str | None:
    if not pin_file or not pin_re:
        return None
    if pin_file == "defaults":                      # the whole default layer set
        text = default_config_text()
    else:
        path = REPO / pin_file
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
    m = re.search(pin_re, text, re.MULTILINE)
    return m.group(1) if m else None


# ── axis 1: the repos, against origin ───────────────────────────────────────


def axis_repos(res: Result, do_fetch: bool) -> None:
    for name, path in REPOS:
        if not (path / ".git").exists():
            res.add("repo", name, f"{path} is not a git checkout", UNREADABLE)
            continue

        if do_fetch and git(path, "fetch", "--all", "--tags", "--quiet", timeout=120) is None:
            # A failed fetch does NOT fall through to a stale comparison — that
            # is precisely the mistake this tool exists to prevent.
            res.add("repo", name, "fetch failed; refs may be stale — NOT compared", UNREADABLE)
            continue

        branch = git(path, "rev-parse", "--abbrev-ref", "HEAD") or "?"
        head = git(path, "rev-parse", "--short", "HEAD") or "?"
        dirty = bool(git(path, "status", "--porcelain"))
        counts = git(path, "rev-list", "--left-right", "--count", f"origin/{branch}...{branch}")
        if counts and len(counts.split()) == 2:
            behind, ahead = counts.split()
            drift = f"{ahead} ahead, {behind} behind origin/{branch}"
            state = DISAGREE if int(behind) else OK
        else:
            drift, state = f"no origin/{branch} to compare against", UNREADABLE
        res.add("repo", f"{name} @{branch}",
                f"{head}{' [dirty]' if dirty else ''} · {drift}", state)

        unmerged = [b.strip().lstrip("* ") for b in (git(path, "branch", "--no-merged", branch) or "").splitlines() if b.strip()]
        if unmerged:
            res.add("repo", f"{name} unmerged", ", ".join(unmerged))
    axis_estate(res, do_fetch)


def axis_estate(res: Result, do_fetch: bool) -> None:
    """The clone the converge runs from (row estate-dev-split), at the ref `nos update` recorded."""
    est = Path(os.environ.get("NOS_ESTATE_DIR") or Path.home() / ".nos" / "estate")
    if not (est / ".git").exists():
        res.add("repo", "estate", f"{est} absent — the converge runs from a dev tree (tools/estate-adopt.sh)", UNREADABLE)
        return
    if do_fetch and git(est, "fetch", "--tags", "--quiet", timeout=120) is None:
        res.add("repo", "estate", "fetch failed; refs may be stale — NOT compared", UNREADABLE)
        return
    ref = git(est, "config", "--get", "nos.estate-ref") or "dev"
    target = f"origin/{ref}" if git(est, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{ref}") else ref
    head = git(est, "rev-parse", "--short", "HEAD") or "?"
    dirty = bool(git(est, "status", "--porcelain"))
    counts = git(est, "rev-list", "--left-right", "--count", f"{target}...HEAD")
    if counts and len(counts.split()) == 2:
        behind, ahead = (int(n) for n in counts.split())
        drift = f"{ahead} ahead, {behind} behind {target}" + ("; `nos update` moves it" if behind else "")
        state = DISAGREE if ahead or dirty else OK
    else:
        drift, state = f"no {target} to compare against", UNREADABLE
    res.add("repo", f"estate @{ref}", f"{head}{' [dirty]' if dirty else ''} · {drift}", state)


# ── axis 2: the organs, asked rather than inferred ──────────────────────────


def axis_organs(res: Result) -> None:
    repo_by_name = dict(REPOS)
    for organ in ORGANS:
        deployed, how = None, None

        if organ["url"]:
            payload = http_json(organ["url"])
            if payload is None:
                res.add("organ", organ["name"], f"unreachable at {organ['url']}", UNREADABLE)
                continue
            deployed = first_key(payload, organ["version_keys"])
            how = "http"
            if deployed is None:
                # RULE 1's honest failure. The organ answers and omits the one
                # field that would say what it is. Not a crash, not a guess.
                res.add("organ", organ["name"],
                        "reachable, but reports no version — provenance unanswerable",
                        UNREADABLE)

        # A host organ with no repo semver answers `repo != running system`
        # by reporting the git ref it was DEPLOYED from; compare it to the
        # checkout this reader runs from. `unknown` means the organ answers but
        # the converge never stamped it — reachable, provenance still absent.
        if organ.get("compare_ref") and deployed is not None:
            if deployed == "unknown":
                res.add("organ", organ["name"],
                        "reachable, deploy ref unstamped (converge to stamp it)",
                        UNREADABLE)
                continue
            head = git(REPO, "describe", "--always", "--dirty", "--abbrev=12")
            if head is None:
                res.add("organ", organ["name"],
                        f"deployed {deployed} (via http) · no local checkout to compare")
            elif head == deployed:
                res.add("organ", organ["name"],
                        f"deployed {deployed} (via http) = checkout HEAD")
            else:
                res.add("organ", organ["name"],
                        f"deployed {deployed} (via http) ≠ checkout {head} — expected "
                        "only if this checkout is deliberately off the deployed ref",
                        DISAGREE)
            continue

        src = organ["src"]
        if deployed is None and src and (src / "VERSION").exists():
            deployed, how = (src / "VERSION").read_text(encoding="utf-8").strip(), "VERSION"
        if deployed is None and src and (src / ".git").exists():
            deployed, how = git(src, "describe", "--tags", "--always") or None, "git"
        if deployed is None:
            continue

        want = None
        if organ["repo_version"]:
            rname, rel = organ["repo_version"]
            rpath = repo_by_name.get(rname, Path("/nonexistent")) / rel
            if rpath.exists():
                try:
                    want = json.loads(rpath.read_text(encoding="utf-8")).get("version")
                except ValueError:
                    want = None

        if want is None:
            res.add("organ", organ["name"], f"deployed {deployed} (via {how}) · repo declares nothing to compare")
        elif str(want) in str(deployed):
            res.add("organ", organ["name"], f"deployed {deployed} (via {how}) = repo {want}")
        else:
            # NOT automatically wrong — the repo is not the running system, and
            # a checkout may legitimately sit behind or ahead. Flagged so a
            # human decides, never silently equated.
            res.add("organ", organ["name"],
                    f"deployed {deployed} (via {how}) ≠ repo {want} — expected only if "
                    "the checkout is deliberately off the deployed ref", DISAGREE)


def axis_blank(res: Result) -> None:
    """The newest confirmed blank (main.yml opens it, callback_plugins/blank_record.py closes it)."""
    path = Path.home() / ".nos" / "blank-runs.jsonl"
    try:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError) as exc:
        res.add("blank", "newest blank", f"UNKNOWN — no readable record ({type(exc).__name__}: {path})", UNREADABLE)
        return
    if not rows:
        res.add("blank", "newest blank", f"UNKNOWN — {path} is empty", UNREADABLE)
        return
    try:  # any row shape we cannot read is UNKNOWN, never a crash
        started = max(r.get("started") or "" for r in rows)
        last = [r for r in rows if r.get("started") == started][-1]
        age = datetime.now(timezone.utc) - datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        smoke = last.get("smoke_strict")
        red = smoke and (smoke["ok"] < smoke["total"] or smoke["failed"])
        strict = f"smoke --strict {smoke['ok']}/{smoke['total']}" if smoke else "no strict smoke"
        strict += f" at {smoke['at']}" if smoke and smoke.get("at") else ""
        strict += f" failed: {', '.join(map(str, smoke['failed']))}" if red else ""
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        res.add("blank", "newest blank", f"UNKNOWN — unreadable record ({type(exc).__name__}: {path})", UNREADABLE)
        return
    when = f"{started} ({age.days}d ago) at {last.get('nos_commit')}"
    if not last.get("finished"):
        res.add("blank", "newest blank", f"{when} never finished (still running, or the run died)", DISAGREE)
    elif last.get("failed"):
        res.add("blank", "newest blank", f"{when} FAILED · {strict}", DISAGREE)
    elif not smoke or red:  # no strict smoke, or a strict probe red: the release gate needs all green
        res.add("blank", "newest blank", f"{when} · {strict} (release gate unmet)", DISAGREE)
    else:
        res.add("blank", "newest blank", f"{when} · {strict} (release gate met)")


# ── axis 3: the toolchain ───────────────────────────────────────────────────


def axis_toolchain(res: Result) -> None:
    for spec in TOOLCHAIN:
        host = host_version(spec["cmd"])
        pin = declared(spec["pin_file"], spec["pin_re"])

        if pin is not None and FLOATING.match(pin):
            # RULE 2 — checked BEFORE the host probe (2026-08-19): floating is
            # a property of the DECLARATION, not of the host. Gating it on the
            # binary being installed meant a host without node got no floating
            # report at all — the pin that can never warn anyone additionally
            # went unreported exactly where nothing else could warn either.
            host_part = f"host {host}" if host else "host not installed / not readable"
            res.add("tool", spec["tool"],
                    f"{host_part} · pin is '{pin}' — FLOATING, so it can never warn you",
                    OK if host else UNREADABLE)
            res.uncomparable.append(f"{spec['tool']} (floating pin '{pin}')")
            continue
        if host is None:
            res.add("tool", spec["tool"], "not installed / not readable on this host", UNREADABLE)
            continue
        if pin is None:
            res.add("tool", spec["tool"], f"host {host} · nothing declares a pin")
            continue

        split = KNOWN_SPLITS.get(spec["tool"])
        if split and host.startswith(split["host"]) and pin.startswith(split["pin"]):
            # RULE 3.
            res.add("tool", spec["tool"],
                    f"host {host} vs pin {pin} — INTENTIONAL: {split['why']}")
            continue
        if host.startswith(pin) or pin.startswith(host):
            res.add("tool", spec["tool"], f"host {host} = pin {pin}")
        else:
            res.add("tool", spec["tool"], f"host {host} ≠ pin {pin}", DISAGREE)


# ── axis 4: a config flag, resolved the way the playbook resolves it ────────


# Layer resolution lives in nos_identity — the same reader discovery-scan and
# nos-smoke use, so three tools cannot disagree about one flag.
from nos_identity import UNKNOWN, default_config_text, install_flags, ran, resolve_flag, services  # noqa: E402


def axis_config(res: Result, flag: str) -> None:
    layers = resolve_flag(flag)
    if not layers:
        res.add("config", flag, "declared in no layer", UNREADABLE)
        return
    winner = layers[-1]
    trail = " -> ".join(f"{lyr}={val}" for lyr, val in layers)

    # THE PRECEDENCE RULE IS PRINTED WHETHER OR NOT A SECOND LAYER EXISTS.
    # It used to appear only when len(layers) > 1, which taught the rule to the
    # reader who could already see it working and withheld it from the one
    # looking at a single line, wondering whether something else could be in
    # play. It also made this axis environment-dependent — config.yml is
    # gitignored, so CI resolves one layer where the operator resolves two — and
    # a gate asserting the sentence went red on CI for a difference that is not
    # a defect. Measured 2026-08-11.
    note = "  (the LAST layer wins)"
    declared_in = {lyr for lyr, _ in layers}
    if "config.yml" not in declared_in:
        note += "; config.yml does not override it"
    res.add("config", flag, f"{trail}{note}  ==> {winner[1]}")
    axis_ran(res, flag, winner[1])


def axis_ran(res: Result, flag: str, declared: str) -> None:
    """What the last converge RESOLVED, beside what the layers declare. The layers
    cannot see a run's -e (`-e @profiles/core.yml`), so the two can differ, and a
    difference is a disagreement shown, not a value silently picked."""
    run = ran()
    if run.source == UNKNOWN:
        res.add("config", "ran", run.provenance(), UNREADABLE)
        return
    if run.source == "layers":
        res.add("config", "ran", f"{run.provenance()} — the layers above are all there is")
        return
    recorded = run.flag(flag)
    if not recorded:
        res.add("config", "ran", "state.yml records no value for this flag (declared only)")
        return
    at = (run.state.get("last_run") or {})
    where = f"last converge {at.get('run_id', '?')} at {at.get('at', '?')} (tags {at.get('tag', '?')})"
    for subject, value in recorded:
        if value is None:
            res.add("config", "ran", f"{where}: {subject} — state.yml holds no value yet")
            continue
        word = str(value).lower()
        if word == declared.lower():
            res.add("config", "ran", f"{where}: {subject}  ==> {word}")
        else:
            res.add("config", "ran", f"{where}: {subject}  ==> {word}  "
                    f"(declared {declared}: an -e / profile the files do not show)", DISAGREE)


# ── axis 5: what each host organ IS, and who it runs as (the medulla's measure) ─


#: argv0 basename prefix -> runtime; `native` becomes rust when the organ has a Cargo.toml.
#: A table of names, not a command: nothing here runs an interpreter (test_host_php_is_resolved
#: reads a `("php", …` argv literally, so the table is a dict).
RUNTIMES = {"python": "python", "frankenphp": "php", "php": "php",
            "node": "node", "bash": "shell", "sh": "shell"}


def _deployed_job(label: str, root: Path, home: Path) -> tuple[str, list[str], bool] | None:
    """(domain, argv, scheduled) of the job installed for `label` — one lookup on both
    platforms. `scheduled` = launchd calendar/interval or a systemd .timer beside the unit."""
    for domain, path in (("LaunchAgent", home / "Library/LaunchAgents" / f"{label}.plist"),
                         ("LaunchDaemon", root / "Library/LaunchDaemons" / f"{label}.plist")):
        if path.exists():
            try:
                doc = plistlib.loads(path.read_bytes())
            except Exception:  # noqa: BLE001 — unparsable is still installed; ps then cannot match it
                return domain, [], False
            scheduled = "StartCalendarInterval" in doc or "StartInterval" in doc
            return domain, list(doc.get("ProgramArguments") or [doc.get("Program", "")]), scheduled
    for domain, path in (("user unit", home / ".config/systemd/user" / f"{label}.service"),
                         ("system unit", root / "etc/systemd/system" / f"{label}.service")):
        if path.exists():
            scheduled = path.with_suffix(".timer").exists()
            for raw in path.read_text(encoding="utf-8").splitlines():
                if raw.strip().startswith("ExecStart="):
                    return domain, shlex.split(raw.split("=", 1)[1].lstrip("-@:+!")), scheduled
            return domain, [], scheduled
    return None


def axis_identity(res: Result, root: Path = Path("/"), home: Path = Path.home(),
                  ps_lines: list[str] | None = None) -> None:
    if ps_lines is None:
        try:
            ps_lines = subprocess.run(["ps", "-axo", "uid=,user=,command="], capture_output=True,
                                      text=True, timeout=10, check=True).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            ps_lines = []
    procs = [p for p in (x.split(None, 2) for x in ps_lines) if len(p) == 3]
    operator_uid = home.stat().st_uid if home.exists() else None
    langs = {"php": 0, "python": 0, "node": 0, "rust": 0}
    runs = {"operator": 0, "root": 0, "other": 0}
    # Symbiont daemons (ollama, alloy, dnsmasq…) are shown apart, for information: the medulla absorbs
    # self-owned organs only, so the transplant numbers below never count them (operator 2026-10-22).
    syms = {"installed": 0, "running": 0}
    rows = [(r, False) for r in services() if r.get("software_owner") == "self" and r.get("launchd_label")]
    rows += [(r, True) for r in services() if r.get("software_owner") == "symbiont" and r.get("launchd_label")]
    for row, apart in rows:
        rid = row["id"]
        job = _deployed_job(row["launchd_label"], root, home)
        if job is None:
            if not apart:
                res.add("identity", rid, f"{rid} · not installed here")
            continue
        if apart:
            syms["installed"] += 1
        domain, argv, scheduled = job
        argv0 = argv[0] if argv else ""
        interp = argv0
        try:  # an entry script (venv uvicorn) runs on its shebang's interpreter
            first = Path(argv0).read_bytes()[:128].split(b"\n")[0].decode() if argv0 else ""
            if first.startswith("#!"):
                words = first[2:].split()
                if words and words[0].endswith("/env"):  # env [-S] [flags] python3 [flags]
                    words = [w for w in words[1:] if not w.startswith("-")]
                interp = words[0] if words else argv0
        except (OSError, UnicodeDecodeError):
            pass
        runtime = next((rt for pre, rt in RUNTIMES.items() if Path(interp).name.startswith(pre)), "native")
        language = runtime
        if runtime == "native":
            src = REPO / "files/anatomy" / rid.replace("_", "-")
            language = "rust" if any(src.glob("**/Cargo.toml")) else "native"
        if not apart:
            langs[language] = langs.get(language, 0) + 1
        # An interpreter argv0 is matched by its arguments (the python shim re-execs under another
        # argv0, `-m pkg` included); anything else by its whole argv.
        # ponytail: argv substring match; upgrade to pid-from-launchd/systemd when two organs share a key.
        own = any(Path(argv0).name.startswith(pre) for pre in RUNTIMES)
        key = " ".join(argv[1:] if own and len(argv) > 1 else argv)
        hit = next((p for p in procs if key and key in p[2]), None)
        head = f"{rid} · {'symbiont · ' if apart else ''}{language}/{runtime}"
        if hit is None and scheduled and procs:
            res.add("identity", rid, f"{head} · scheduled, idle (no run in progress) · {domain}")
            continue
        if hit is None:
            why = "ps unreadable" if not procs else f"no process runs {key or '(no argv)'}"
            res.add("identity", rid, f"{head} · not reported ({why}) · {domain}", UNREADABLE)
            continue
        uid, user = int(hit[0]), hit[1]
        if apart:
            syms["running"] += 1
        else:
            runs["root" if uid == 0 else "operator" if uid == operator_uid else "other"] += 1
        res.add("identity", rid, f"{head} · runs as {user} uid {uid} · {domain}")
    res.add("identity", "summary",
            "host runtimes: " + ", ".join(f"{k} {v}" for k, v in langs.items())
            + " · run as " + ", ".join(f"{k} {v}" for k, v in runs.items()))
    res.add("identity", "symbionts",
            f"symbiont daemons: {syms['installed']} installed, {syms['running']} running (not counted above)")


# ── output ──────────────────────────────────────────────────────────────────


MARK = {OK: " ", DISAGREE: "!", UNREADABLE: "?"}


def render(res: Result, fetched: bool) -> None:
    axis = None
    for line in res.lines:
        if line.axis != axis:
            axis = line.axis
            print(f"\n  {axis.upper()}")
        print(f"  {MARK[line.state]} {line.subject:<22} {line.detail}")

    print()
    if not fetched:
        print("  NOT FETCHED — every origin comparison above is against a possibly stale ref.")
    if res.uncomparable:
        print(f"  uncomparable by construction: {', '.join(res.uncomparable)}")
    if res.unreadable:
        print(f"  {len(res.unreadable)} side(s) could not be read — those axes were NOT compared.")
    n = len(res.disagreements)
    print(f"  {n} disagreement(s). Absence of a comparison is not agreement.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip the fetch (offline); the output says so")
    ap.add_argument("--config", metavar="FLAG",
                    help="resolve one config flag across the layering")
    ap.add_argument("--install-flags", action="store_true",
                    help="every install_* resolved, as one JSON object (exit 0)")
    ap.add_argument("--identity", action="store_true",
                    help="only the organ-identity axis (language, runtime, run-as uid)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.install_flags:
        print(json.dumps(install_flags(), indent=2))
        return 0

    res = Result()
    if args.config:
        axis_config(res, args.config)
    elif args.identity:
        axis_identity(res)
    else:
        axis_repos(res, do_fetch=not args.no_fetch)
        axis_organs(res)
        axis_identity(res)
        axis_blank(res)
        axis_toolchain(res)

    if args.json:
        print(json.dumps({
            "fetched": not args.no_fetch,
            "lines": [vars(x) for x in res.lines],
            "uncomparable": res.uncomparable,
            "disagreements": len(res.disagreements),
        }, indent=2))
    else:
        render(res, fetched=not args.no_fetch)

    if res.unreadable and not res.disagreements:
        return 2
    return 1 if res.disagreements else 0


if __name__ == "__main__":
    sys.exit(main())
