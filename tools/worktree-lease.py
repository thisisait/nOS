#!/usr/bin/env python3
"""A lease over a worktree's SHAPE, so a long agent run cannot be cut from under.

WHY THIS IS NOT THE PULSE MUTEX. `files/anatomy/scripts/pulse-run-agent.sh`
serialises claude-CLI agents with an atomic mkdir lock — one at a time, because
concurrent runs crashed all participants. That is the right answer there and the
wrong one here: a workflow legitimately runs a dozen subagents in ONE worktree,
and serialising them would defeat the workflow.

So this is a lease, not a mutex, and it guards a narrower thing.

THE RULE
--------
    While a lease is held, PATHS ARE IMMUTABLE.
    Content may change. Shape may not.

Adding a path is always allowed. Moving or deleting one is not.

That asymmetry is the whole insight, and it comes from the incident that
produced this file (2026-08-02): a workflow was mid-run when the main session
moved `plugins/nos-loop` to `.claude/plugins/nos-loop`. Nothing was corrupted —
but every in-flight agent still held the old path, so the next reader would have
reported "the plugin does not exist", a false finding manufactured by the very
session that would then have to triage it.

Nothing can hold a stale reference to a path that did not exist yet, which is
why creation is safe and relocation is not.

ADVISORY, AND HONEST ABOUT IT
-----------------------------
This cannot stop a process that does not ask. It makes the answer *available* at
the moment of the decision, which is all a lease can do. The enforcement half is
a gate asserting that the known mutators consult it.

The lease lives in ~/.nos/, NOT in the worktree — runtime state, not repo state,
matching the estate's side-car convention. A lease file inside the tree it
guards would be a path the lease forbids moving.

USAGE
    worktree-lease.py acquire --kind workflow --label nos-loop-engine [--ttl 3600]
    worktree-lease.py check                  # exit 0 = safe to move/delete paths
    worktree-lease.py status
    worktree-lease.py release
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: Backstop for a pid that died and had its number recycled by the OS. Liveness
#: is the primary signal; this catches the case liveness gets wrong.
DEFAULT_TTL_SECONDS = 3 * 3600


def _worktree_root(start: Path | None = None) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start or Path.cwd()),
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except Exception:
        return (start or Path.cwd()).resolve()


def _lease_dir(root: Path) -> Path:
    # Keyed by absolute path so sibling worktrees of one repo lease separately —
    # they are different trees and a lease on one says nothing about the other.
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return Path(os.path.expanduser("~/.nos/worktree-leases")) / f"{key}.lease"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except Exception:
        return False


def _read(lease: Path) -> dict | None:
    try:
        return json.loads((lease / "holder.json").read_text())
    except Exception:
        return None


def _expired(holder: dict) -> str | None:
    """Return why the lease is dead, or None if it is live.

    Liveness is OBSERVED (is the pid there?), never self-reported. A holder that
    wrote 'status: done' and then died would still be believed by a status field;
    it is not believed by kill(0).
    """
    pid = int(holder.get("pid", 0) or 0)
    if pid and not _alive(pid):
        return f"holder pid {pid} is gone"
    age = time.time() - float(holder.get("acquired_at", 0) or 0)
    ttl = float(holder.get("ttl_seconds", DEFAULT_TTL_SECONDS) or DEFAULT_TTL_SECONDS)
    if age > ttl:
        return f"lease is {int(age)}s old, past its {int(ttl)}s ttl"
    return None


def cmd_acquire(args) -> int:
    root = _worktree_root()
    lease = _lease_dir(root)
    lease.parent.mkdir(parents=True, exist_ok=True)

    # Atomic: mkdir either creates or fails. No flock on macOS, same trick the
    # pulse agent mutex uses.
    try:
        lease.mkdir()
    except FileExistsError:
        holder = _read(lease)
        if holder:
            why = _expired(holder)
            if why is None:
                print(
                    f"REFUSED: {root} is leased by {holder.get('kind')}/{holder.get('label')} "
                    f"(pid {holder.get('pid')}, since {holder.get('acquired_iso')})",
                    file=sys.stderr,
                )
                return 2
            print(f"reclaiming stale lease: {why}", file=sys.stderr)
        else:
            print("reclaiming lease with unreadable holder", file=sys.stderr)
        cmd_release(args, force=True)
        try:
            lease.mkdir()
        except FileExistsError:
            print("REFUSED: lost the reclaim race", file=sys.stderr)
            return 2

    (lease / "holder.json").write_text(json.dumps({
        # getppid, NOT getpid: this CLI exits the instant it returns, so a lease
        # stamped with its OWN pid reads as "holder gone" immediately and every
        # lease was stealable on the next call (2026-09-05). The parent — the
        # shell/agent that ran the CLI — is the real holder; a caller with a
        # different long-lived owner passes --pid.
        "pid": args.pid if args.pid else os.getppid(),
        "kind": args.kind,
        "label": args.label,
        "worktree": str(root),
        "acquired_at": time.time(),
        "acquired_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_seconds": args.ttl,
    }, indent=1))
    print(f"leased {root} for {args.kind}/{args.label}")
    return 0


def cmd_release(args, force: bool = False) -> int:
    lease = _lease_dir(_worktree_root())
    # rmdir + unlink, never rmtree: a misset path must not widen the blast
    # radius. Same reasoning as pulse-run-agent.sh's _release_agent_lock.
    try:
        (lease / "holder.json").unlink()
    except FileNotFoundError:
        pass
    try:
        lease.rmdir()
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"could not release cleanly: {e}", file=sys.stderr)
        return 1
    if not force:
        print("released")
    return 0


def cmd_check(args) -> int:
    """exit 0 = the shape may be changed. Non-zero = a lease says otherwise."""
    root = _worktree_root()
    holder = _read(_lease_dir(root))
    if holder is None:
        print("no lease — moving and deleting paths is safe")
        return 0
    why = _expired(holder)
    if why:
        print(f"lease present but dead ({why}) — safe, and worth releasing")
        return 0
    print(
        "HELD: paths are immutable while this lease is live.\n"
        f"  holder : {holder.get('kind')}/{holder.get('label')} (pid {holder.get('pid')})\n"
        f"  since  : {holder.get('acquired_iso')}\n"
        f"  tree   : {holder.get('worktree')}\n"
        "\n"
        "  ADDING a path is fine — nothing can hold a stale reference to something\n"
        "  that did not exist. MOVING or DELETING one is what breaks an in-flight\n"
        "  reader, and manufactures a finding the mover then has to triage.",
        file=sys.stderr,
    )
    return 3


def cmd_status(args) -> int:
    root = _worktree_root()
    holder = _read(_lease_dir(root))
    print(json.dumps({
        "worktree": str(root),
        "leased": holder is not None and _expired(holder) is None,
        "holder": holder,
        "dead_because": _expired(holder) if holder else None,
    }, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("acquire")
    a.add_argument("--kind", required=True, choices=["workflow", "session", "agent", "job"])
    a.add_argument("--label", required=True)
    a.add_argument("--ttl", type=float, default=DEFAULT_TTL_SECONDS)
    a.add_argument("--pid", type=int, default=0, help="pid to watch instead of this process")
    a.set_defaults(fn=cmd_acquire)

    for name, fn in (("release", cmd_release), ("check", cmd_check), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
