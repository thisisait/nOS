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
  -- or --
  UNKNOWN              # a zero-container stack whose expected count could not
                        # be determined (see below) — never ALL_READY

ZERO CONTAINERS — absence needs a denominator (doctrine:
docs/hidden_fees/08-empty-stack-reads-as-success.md). `docker ps` returning
nothing for a stack is ambiguous on its own: it means either "every service in
this stack is toggled off" (fine) or "the bring-up never produced anything"
(not fine), and a plain container count cannot tell the two apart. This probe
resolves the ambiguity from an artifact it CAN read without a live Docker
daemon or the Ansible-side `up` result: the rendered compose inputs
themselves — `{{ stacks_dir }}/<stack>/docker-compose.yml` plus every
role-rendered `{{ stacks_dir }}/<stack>/overrides/*.yml` — the same files
`docker compose up` itself consumes (env var `NOS_STACKS_DIR` points at
`stacks_dir`; set by tasks/stacks/health-tick.yml).

  - rendered inputs declare 0 services  -> legitimately empty, PASS silently
    ("stack empty by configuration").
  - rendered inputs declare N>0 services but 0 containers exist -> FAIL
    ("bring-up failed"), regardless of any `up` rc — the artifact alone
    disambiguates this case.
  - the base compose file is flat-out MISSING -> UNKNOWN, not FAIL. A probe
    reading only rendered artifacts cannot tell "this stack's render was
    never even attempted because it's disabled" from "the render step ran
    and failed to produce output" (the measured CI case: no compose file, rc=1
    from `up`). Consulting the `up` rc — a different, complementary layer —
    is what turns this UNKNOWN into a precise verdict; this probe alone
    cannot and must not guess.
  - `NOS_STACKS_DIR` unset, or PyYAML unavailable, or the artifact unreadable
    -> UNKNOWN for the same reason: guessing either verdict here would repeat
    the defect this file exists to close.

UNKNOWN is deliberately NOT folded into ALL_READY or silently dropped: the
tick loop only ever short-circuits on the literal string "ALL_READY", so an
UNKNOWN stack keeps the health-wait polling for its full budget and then
surfaces loudly via wait-stacks-healthy.yml's timeout failure, with "UNKNOWN"
visible in the last snapshot — never read as success.

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


def _expected_service_count(stack: str) -> tuple[int | None, str, list[str]]:
    """How many services the stack's RENDERED inputs declare — the absent
    denominator (docs/hidden_fees/08-empty-stack-reads-as-success.md).

    Reads exactly the files `docker compose up` itself would read for this
    project: `{{ stacks_dir }}/<stack>/docker-compose.yml` plus every
    `{{ stacks_dir }}/<stack>/overrides/*.yml` role fragment. Says nothing
    about whether `up` ran or what its rc was — this is the artifact side of
    the probe, a COMPLEMENT to consulting the bring-up result, not a
    replacement for it.

    Returns (expected, reason, names):
      expected is None  -> UNKNOWN. `reason` says why (env unset, no PyYAML,
                            base file missing, or a file could not be parsed).
                            Guessing a verdict here would repeat the defect
                            this function exists to close — see module
                            docstring "ZERO CONTAINERS".
      expected is an int -> the count of distinct service names found across
                            every file that COULD be read. 0 is a legitimate,
                            common answer (nothing in this stack is enabled);
                            `reason` is '' in that case. `names` is the sorted
                            list backing a >0 verdict's FAILED message.
    """
    base_dir = os.environ.get("NOS_STACKS_DIR")
    if not base_dir:
        return None, "NOS_STACKS_DIR not set — probe run outside the playbook", []

    try:
        import yaml  # local import: only this path needs it
    except ImportError:
        return None, "PyYAML not importable — cannot read rendered compose", []

    compose_path = os.path.join(base_dir, stack, "docker-compose.yml")
    if not os.path.isfile(compose_path):
        return None, (
            f"{compose_path} does not exist — cannot tell a stack that was "
            "never enabled from one whose render failed"
        ), []

    override_dir = os.path.join(base_dir, stack, "overrides")
    files = [compose_path]
    if os.path.isdir(override_dir):
        files += [
            os.path.join(override_dir, fname)
            for fname in sorted(os.listdir(override_dir))
            if fname.endswith((".yml", ".yaml"))
        ]

    names: set[str] = set()
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
        except Exception as exc:  # unreadable or unparsable — indeterminate
            return None, f"{path}: could not parse ({exc})", []
        if isinstance(doc, dict):
            services = doc.get("services")
            if isinstance(services, dict):
                names.update(services.keys())
    return len(names), "", sorted(names)


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
    any_failed = False    # at least one container Exited/Dead/unhealthy, or a
                           # zero-container stack whose rendered inputs prove
                           # something was expected
    any_unknown = False   # a zero-container stack whose expected count could
                           # not be determined from the rendered artifacts
    for stack in stacks:
        rows = _docker_ps(stack)
        if not rows:
            # Zero containers is EITHER "everything toggled off" (fine) OR
            # "bring-up produced nothing" (not fine) — indistinguishable from
            # container state alone, so the rendered compose inputs supply
            # the denominator (module docstring "ZERO CONTAINERS").
            expected, reason, names = _expected_service_count(stack)
            if expected is None:
                print(f"{stack}: 0/? ready (expected service count UNKNOWN — {reason})")
                any_unknown = True
            elif expected == 0:
                print(f"{stack}: 0/0 ready (stack empty by configuration)")
            else:
                print(
                    f"{stack}: 0/{expected} ready FAILED: bring-up produced no "
                    f"containers, but the rendered compose declares {expected} "
                    f"service(s): {', '.join(names)}"
                )
                any_failed = True
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
    # Marker the tick loop keys on: PENDING > FAILED > UNKNOWN > ALL_READY
    # (still-moving beats a definite break beats an indeterminate one).
    # UNKNOWN is never folded into ALL_READY — the tick loop short-circuits
    # only on the literal "ALL_READY", so an unclassifiable stack polls to
    # the full budget and surfaces via wait-stacks-healthy.yml's timeout.
    if any_pending:
        print("PENDING")
    elif any_failed:
        print("FAILED")
    elif any_unknown:
        print("UNKNOWN")
    else:
        print("ALL_READY")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
