#!/usr/bin/env python3
"""Stack health probe — one-shot snapshot for the in-stream bring-up heartbeat.

Given one or more compose project names, prints a human-readable per-stack
readiness line plus a machine-readable final marker the Ansible tick-loop keys
on. Used by tasks/stacks/health-tick.yml to turn the silent `docker compose up
--wait` into a per-tick progress report in the main ansible.log stream.

Readiness rule per container (parsed from `docker ps` Status, no jq needed):
  ready    = Status starts with "Up" AND not "(unhealthy)" AND not
             "(health: starting)"   (a container with no healthcheck is ready
             once it is simply "Up")
  pending  = "(health: starting)", "Restarting", "Created", "Paused"
  failed   = "Exited", "Dead", "(unhealthy)"

Output (stdout), one line per stack then a marker line:
  iiab: 17/18 ready (waiting: jellyfin[starting])
  devops: 2/5 ready (waiting: gitlab[starting], woodpecker-server[starting]) FAILED: none
  ALL_READY            # every container across every stack is ready
  -- or --
  PENDING              # at least one container still starting / not yet up
  -- or --
  FAILED               # at least one container Exited/Dead/unhealthy (and none pending)

Exit code is always 0 — the marker line carries the state (the tick loop reads
stdout, never the rc, so a transient docker hiccup never aborts the wait).

Usage: stack-health-probe.py <stack> [<stack> ...]
"""
from __future__ import annotations

import os
import subprocess
import sys

# Match the binary the playbook uses (default.config.yml docker_bin). The
# Ansible command task exports NOS_DOCKER_BIN; fall back to PATH lookup.
DOCKER = os.environ.get("NOS_DOCKER_BIN") or "docker"


def _docker_ps(project: str) -> list[tuple[str, str]]:
    """Return [(name, status), ...] for one compose project. Empty on error."""
    try:
        out = subprocess.run(
            [DOCKER, "ps", "-a",
             "--filter", f"label=com.docker.compose.project={project}",
             "--format", "{{.Names}}|{{.Status}}"],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return []
    rows = []
    for line in (out.stdout or "").splitlines():
        if "|" in line:
            name, _, status = line.partition("|")
            rows.append((name.strip(), status.strip()))
    return rows


#: Docker's own words when a healthcheck's binary is missing from the image.
#: The check never ran, so its verdict is not about the service.
#: Doctrine: docs/doctrine/foreign-properties.md §2 (upstream property, no fix
#: on our side) and §2.2 (this annotation is the performing code).
CANNOT_RUN = ("executable file not found", "no such file or directory",
              "exec format error", "oci runtime exec failed")


def _check_could_not_run(name: str) -> bool:
    """Did the healthcheck FAIL, or was it unable to execute at all?

    These are different faults and they send an operator to different places.
    On 2026-08-06 a redis_exporter bump moved upstream's default image to
    scratch — no wget, no shell, nothing but the binary — so
    `CMD wget --spider` could not start. Docker marked the container unhealthy;
    this probe reported `FAILED: redis-exporter-1`; the converge failed after
    1200 s. The exporter was serving metrics on :9121 the entire time.

    Reported as an annotation, not a new class: the container IS unhealthy and
    the bring-up SHOULD still fail — a container whose health cannot be
    established is not a container known to be well. What changes is that the
    line now says which of the two things broke.

    Only called for containers already classified failed, so the extra inspect
    costs nothing on a healthy converge.
    """
    try:
        out = subprocess.run(
            [DOCKER, "inspect", name,
             "--format", "{{range .State.Health.Log}}{{.ExitCode}}:{{.Output}}{{end}}"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    return blob_says_check_could_not_run(out.stdout or "")


def blob_says_check_could_not_run(blob: str) -> bool:
    """The pure half, so a gate can exercise it without a Docker daemon.

    Fixture that produced these markers, verbatim from the live container on
    2026-08-06:
      -1 OCI runtime exec failed: exec failed: unable to start container
      process: exec: "wget": executable file not found in $PATH
    """
    low = blob.lower()
    return any(marker in low for marker in CANNOT_RUN)


def _classify(status: str) -> str:
    """ready | pending | failed, from a `docker ps` Status string."""
    s = status.lower()
    if s.startswith("up"):
        if "(unhealthy)" in s:
            return "failed"
        if "health: starting" in s:
            return "pending"
        return "ready"          # Up + healthy, or Up with no healthcheck
    if s.startswith(("restarting", "created", "paused")):
        return "pending"
    # Exited, Dead, or anything else
    return "failed"


def main(argv: list[str]) -> int:
    stacks = argv or []
    any_pending = False   # at least one container still starting
    any_failed = False    # at least one container Exited/Dead/unhealthy
    for stack in stacks:
        rows = _docker_ps(stack)
        if not rows:
            # No containers for this project. The caller only health-waits AFTER
            # `docker compose up -d` (which blocks until containers are created),
            # so an empty result here means the stack legitimately has none
            # (e.g. every service in it is toggled off) — nothing to wait for.
            print(f"{stack}: 0/0 ready (no containers — stack empty)")
            continue
        ready_n = 0
        waiting, failed = [], []
        for name, status in rows:
            short = name.split("-", 1)[-1] if "-" in name else name
            cls = _classify(status)
            if cls == "ready":
                ready_n += 1
            elif cls == "pending":
                tag = "starting" if "health: starting" in status.lower() \
                    else status.split()[0].lower()
                waiting.append(f"{short}[{tag}]")
                any_pending = True
            else:
                if "(unhealthy)" in status.lower() and _check_could_not_run(name):
                    failed.append(f"{short}[check cannot run — the image ships "
                                  f"no such binary; the service may be fine]")
                else:
                    failed.append(short)
                any_failed = True
        line = f"{stack}: {ready_n}/{len(rows)} ready"
        if waiting:
            line += f" (waiting: {', '.join(waiting)})"
        if failed:
            line += f" FAILED: {', '.join(failed)}"
        print(line)
    # Marker the tick loop keys on. PENDING wins over FAILED (still moving, give
    # it time to converge); FAILED only when nothing is pending but something is
    # broken; ALL_READY when every container across every stack is ready.
    if any_pending:
        print("PENDING")
    elif any_failed:
        print("FAILED")
    else:
        print("ALL_READY")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
