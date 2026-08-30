#!/usr/bin/env python3
"""What macOS will and will not let this estate do — in one place.

WHY THIS EXISTS. The operator's report, 2026-08-30: *"Občas vidím na obrazovce
nativní macOS prompt, že python, nebo node vyžaduje přístup k terminálu, nebo
disku. Měli bychom mít jedno místo, kde ověříme všechna práva, aby se nestalo,
že celá práce stojí, protože na displeji čeká malé okénko."*

A permission dialog is the one failure this estate cannot reason about. Every
other stall leaves a trace in a log a reader can find; a TCC prompt leaves a
window on a screen nobody is looking at, and everything behind it simply waits.
Worse, the silent form leaves no window at all — the call returns EPERM and the
caller reports an empty result, which is this estate's oldest defect wearing
Apple's clothes.

TWO HALVES, BECAUSE NEITHER IS SUFFICIENT.

`--probes` PERFORMS a tiny real operation per capability and reports what
happened. That is the only honest way to answer "can this be done", because
**neither TCC database is readable** — opening `TCC.db` requires the very Full
Disk Access grant we are trying to check, which is a closed loop and is why no
tool here enumerates grants.

`--grants` reads the system log's own TCC subsystem, correlating each request's
`AUTHREQ_CTX` (which service), `AUTHREQ_SUBJECT` (which binary) and
`AUTHREQ_RESULT` (`authValue`: 0 denied, 2 allowed, 3/4 limited). That reaches
what a probe cannot: what a LAUNCHD AGENT was refused at 04:00 while nobody was
awake.

THE DISTINCTION THAT MAKES THIS TOOL HONEST, and it is the one a reader will
get wrong: **a TCC grant belongs to a BINARY, not to a user or a session.** A
probe that succeeds here proves that *this* interpreter, launched from *this*
terminal, may do it. It proves nothing about `~/Library/LaunchAgents/
eu.thisisait.nos.backup.plist`, which runs a different binary with its own
posture. Every probe row therefore names the binary it spoke for, and the
launchd agents are listed separately as UNPROVEN unless the log has an answer
for them.

MEASURED ON FIRST RUN, 2026-08-30, over two days of log:

    com.docker.docker   SystemPolicyAllFiles   DENIED x15
    ghostty (terminal)  SystemPolicyAllFiles   DENIED x30
    restic, python, node                       DENIED
    the same four       SystemPolicyRemovable  ALLOWED

which is the estate's real posture: Full Disk Access is refused nearly
everywhere, Removable Volumes is granted, and `/Volumes/SSD1TB` — where the
data lives — is a removable volume. Things work for a reason nobody had
written down, and `roles/pazny.backup/files/backup.sh` had written down the
wrong one ("Docker Desktop holds the grant").

WHAT IT WILL NOT DO. It never grants, never opens System Settings, never
prompts. Triggering a dialog to see what happens is precisely the failure it
exists to prevent, so every probe is chosen to be answerable without one where
that is possible, and marked when it is not.

Usage:
  tools/permission-status.py              # both halves
  tools/permission-status.py --probes     # only what this process can do now
  tools/permission-status.py --grants     # only what the log says was asked
  tools/permission-status.py --json
  tools/permission-status.py --days 7     # widen the log window (default 2)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
HOME = pathlib.Path.home()

OK, DENIED, UNKNOWN = "OK", "DENIED", "UNKNOWN"

#: authValue as tccd reports it. 1 is "the request was made and no stored
#: answer applied", which is NOT a grant — it renders as UNKNOWN, never green.
AUTH = {0: DENIED, 1: UNKNOWN, 2: OK, 3: "LIMITED", 4: "LIMITED"}

#: Subjects that are Apple's own and never ours. Filtered so the estate's
#: binaries are not buried under a hundred system daemons.
NOISE = re.compile(r"^/System/|^/usr/libexec/|^/usr/sbin/|^com\.apple")

#: The services this estate's own operation depends on. Everything else the log
#: carries (a terminal being refused Photos, a launcher asking for Reminders) is
#: real but none of our business; `--all` shows it rather than hiding it.
OURS = {"SystemPolicyAllFiles", "SystemPolicyRemovableVolumes", "SystemPolicyRemovable",
        "SystemPolicyAppData", "SystemPolicyAppBundles", "DeveloperTool",
        "AppleEvents", "Accessibility", "ScreenCapture", "PostEvent", "ListenEvent"}


def _short(binary: str) -> str:
    """`~`-relative and elided in the MIDDLE, never the front.

    A first draft cut the leading 46 characters and printed
    `s/pazny/.pyenv/versions/3.13.13/bin/python3.13`, which reads as a path
    that does not exist. The interesting halves of a binary path are both
    ends."""
    b = binary.replace(str(HOME), "~")
    return b if len(b) <= 44 else b[:20] + "…" + b[-23:]


def _run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ── half one: what can this process actually do, right now ──────────────────

def _probe_read(path: pathlib.Path) -> tuple[str, str]:
    """Read a directory. EPERM is the silent form of a TCC refusal."""
    try:
        next(iter(os.scandir(path)), None)
        return OK, f"listed {path}"
    except PermissionError as exc:
        return DENIED, f"{path}: {exc.strerror}"
    except FileNotFoundError:
        return UNKNOWN, f"{path} does not exist — nothing to conclude"
    except OSError as exc:
        return UNKNOWN, f"{path}: {exc.strerror}"


def probes() -> list[dict]:
    """One row per capability the estate depends on.

    Each names the BINARY it speaks for, because that is what the grant is
    attached to. `sys.executable` here is whatever interpreter is running this
    file — usually not the one a launchd agent uses.
    """
    me = sys.executable
    rows: list[dict] = []

    def add(cap: str, state: str, detail: str, subject: str, matters: str):
        rows.append({"capability": cap, "state": state, "detail": detail,
                     "subject": subject, "matters": matters})

    # The volume the estate's data actually lives on. Removable Volumes.
    ext = pathlib.Path("/Volumes/SSD1TB/nOS/data")
    state, detail = _probe_read(ext)
    add("Removable Volumes (/Volumes/SSD1TB)", state, detail, me,
        "every service data dir, the KEAP database and the backup sources")

    # Full Disk Access, tested without a prompt: TCC's own store is the
    # canonical FDA-only path, and reading it is refused rather than asked.
    state, detail = _probe_read(HOME / "Library/Application Support/com.apple.TCC")
    add("Full Disk Access", state, detail, me,
        "reading other apps' data; NOT needed for /Volumes, which is Removable")

    # Where launchd agents keep their logs and where the estate writes state.
    for label, path, why in (
            ("~/.nos state dir", HOME / ".nos", "secrets.yml and state.yml"),
            ("~/Library/LaunchAgents", HOME / "Library/LaunchAgents",
             "the eleven agent plists; your OWN Library needs no grant")):
        state, detail = _probe_read(path)
        add(label, state, detail, me, why)

    # Docker's own view of the removable volume — the path the keap backup
    # takes, and the one backup.sh justified with the wrong grant.
    if _run(["docker", "info"], timeout=15).returncode == 0:
        got = _run(["docker", "run", "--rm", "-v", "/Volumes/SSD1TB:/m:ro",
                    "alpine:3", "sh", "-c", "ls /m >/dev/null && echo ok"], timeout=90)
        state = OK if "ok" in got.stdout else DENIED
        add("Docker can bind-mount /Volumes", state,
            (got.stdout or got.stderr).strip()[-120:] or "no output",
            "com.docker.docker",
            "the in-container keap-db backup reads /data through this mount")
    else:
        add("Docker can bind-mount /Volumes", UNKNOWN, "docker not responding",
            "com.docker.docker", "cannot be established while Docker is down")

    # The keap-db HOST fallback. backup.sh takes the container route because
    # this one is refused; the survey found its comment blames the wrong grant,
    # so the estate should be able to see the refusal rather than read about it.
    keap = pathlib.Path("/Volumes/SSD1TB/nOS/data/platform/services/keap/data/keap.db")
    if keap.exists() and (sq := _run(["sqlite3", str(keap), "select 1;"], timeout=30)):
        state = OK if sq.returncode == 0 else DENIED
        add("sqlite3 may read keap.db on the volume", state,
            (sq.stderr or sq.stdout).strip()[:120] or "returned a row",
            "sqlite3", "backup.sh's host fallback when the container is down")

    # Apple Events. Asking WOULD prompt, so it is opt-in — see the docstring.
    if os.environ.get("NOS_PERM_PROBE_AUTOMATION") == "1":
        got = _run(["osascript", "-e",
                    'tell application "System Events" to get name of first process'],
                   timeout=30)
        state = OK if got.returncode == 0 else DENIED
        add("Automation / Apple Events", state,
            (got.stderr or got.stdout).strip()[:120], "osascript",
            "autostart.yml's login-item check and the stale-mount Docker restart")
    else:
        add("Automation / Apple Events", UNKNOWN,
            "not probed — the probe IS a dialog, and an unattended run must not "
            "raise one. NOS_PERM_PROBE_AUTOMATION=1 to ask, with a human present.",
            "osascript",
            "3 consumers, ALL `failed_when: false`: autostart.yml login-item "
            "check + add, and docker-external-mount-preflight's `quit app Docker` "
            "self-heal, which reports the WRONG cause when Automation is refused")

    return rows


# ── half two: what the system log says was asked, and answered ──────────────

def grants(days: int = 2, everything: bool = False) -> list[dict]:
    """Correlate the TCC subsystem's own request/verdict pairs.

    Reaches what a probe cannot: a refusal handed to a launchd agent at 04:00.
    An empty result is reported as such — `log show` keeps a bounded window,
    so "nothing found" means "not in the last N days", never "never happened".
    """
    got = _run(["log", "show", "--last", f"{days}d", "--style", "compact",
                "--predicate",
                'subsystem == "com.apple.TCC" AND ('
                'eventMessage CONTAINS "AUTHREQ_CTX" OR '
                'eventMessage CONTAINS "AUTHREQ_SUBJECT" OR '
                'eventMessage CONTAINS "AUTHREQ_RESULT")'], timeout=600)
    if got.returncode != 0:
        return [{"error": f"log show failed: {got.stderr.strip()[-200:]}"}]

    ctx: dict[str, str] = {}
    subj: dict[str, str] = {}
    res: dict[str, int] = {}
    for line in got.stdout.splitlines():
        m = re.search(r"msgID=([\d.]+)", line)
        if not m:
            continue
        key = m.group(1)
        if "AUTHREQ_CTX" in line and (s := re.search(r"service=(\w+)", line)):
            ctx[key] = s.group(1).replace("kTCCService", "")
        elif "AUTHREQ_SUBJECT" in line and (s := re.search(r"subject=([^,]*)", line)):
            subj[key] = s.group(1).strip()
        elif "AUTHREQ_RESULT" in line and (s := re.search(r"authValue=(\d+)", line)):
            res[key] = int(s.group(1))

    seen: dict[tuple[str, str, str], int] = {}
    for key, who in subj.items():
        if not who or NOISE.search(who):
            continue
        svc = ctx.get(key, "?")
        if not everything and svc not in OURS:
            continue
        row = (who, svc, AUTH.get(res.get(key), UNKNOWN))
        seen[row] = seen.get(row, 0) + 1
    return [{"binary": w, "service": s, "state": v, "requests": n}
            for (w, s, v), n in sorted(seen.items(),
                                       key=lambda kv: (kv[0][2] != DENIED, -kv[1]))]


# ── the launchd agents, which no probe here can speak for ───────────────────

#: Binaries whose grant is pinned to a path that CHANGES on an ordinary
#: upgrade. TCC keys on the binary, so a new path is a new subject with no
#: history — the grant does not carry forward and the failure is silent.
VERSIONED = re.compile(r"/\.nvm/versions/node/v[\d.]+/|/\.pyenv/versions/[\d.]+/|"
                       r"/Cellar/[^/]+/[\d][^/]*/")


def agents() -> list[dict]:
    """The estate's own launchd agents and the binary each one runs.

    Listed, never probed. A grant belongs to a binary: nothing this process
    does establishes what `eu.thisisait.nos.backup.offsite` may do at 03:00.
    Cross-read against `--grants`, which is the only source that can answer.
    """
    out = []
    for plist in sorted((HOME / "Library/LaunchAgents").glob("eu.thisisait.nos.*.plist")):
        got = _run(["plutil", "-extract", "ProgramArguments.0", "raw", "-o", "-",
                    str(plist)], timeout=10)
        binary = got.stdout.strip() if got.returncode == 0 else "?"
        out.append({"agent": plist.stem, "binary": binary,
                    "version_pinned": bool(VERSIONED.search(binary))})
    return out


def render(data: dict) -> int:
    if p := data.get("probes"):
        print("PROBES — what the interpreter running this file may do NOW\n")
        for r in p:
            print(f"  {r['state']:<8}{r['capability']}")
            print(f"          {r['detail']}")
            print(f"          matters for: {r['matters']}")
        print()
    if g := data.get("grants"):
        if g and "error" in g[0]:
            print(f"GRANTS — UNKNOWN: {g[0]['error']}\n")
        else:
            print(f"GRANTS — what the TCC log recorded over {data['days']} day(s)\n")
            for r in g:
                print(f"  {r['state']:<8}{r['service'][:26]:<28}{_short(r['binary']):<46}x{r['requests']}")
            if not g:
                print("  (nothing in the window — NOT proof that nothing was asked)")
            print()
    if a := data.get("agents"):
        print("LAUNCHD AGENTS — each needs its OWN grant; no probe above speaks for them\n")
        for r in a:
            mark = "  <- version-pinned path" if r.get("version_pinned") else ""
            print(f"  {r['agent'].replace('eu.thisisait.nos.', ''):<22}"
                  f"{_short(r['binary'])}{mark}")
        if any(r.get("version_pinned") for r in a):
            print()
            print("  A version-pinned path is a NEW SUBJECT to TCC after an upgrade:")
            print("  `nvm install` or a brew bump moves the binary, the grant does not")
            print("  follow it, and the job goes quiet rather than loud. cortex's")
            print("  nightly fs-sync reads /Volumes through exactly such a path.")
        print()
    print("  A grant belongs to a BINARY, not to you. A probe that passes in your")
    print("  terminal says nothing about the same code under launchd.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probes", action="store_true")
    ap.add_argument("--grants", action="store_true")
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--all", action="store_true",
                    help="every TCC service in the log, not only the ones the estate uses")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    both = not (args.probes or args.grants)

    data: dict = {"days": args.days}
    if both or args.probes:
        data["probes"] = probes()
    if both or args.grants:
        data["grants"] = grants(args.days, args.all)
    if both:
        data["agents"] = agents()

    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    return render(data)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
