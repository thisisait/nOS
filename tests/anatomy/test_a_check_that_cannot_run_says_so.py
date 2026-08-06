"""A healthcheck that cannot execute is a broken CHECK, not a broken service.

WHAT HAPPENED, 2026-08-06. A pin sweep moved `redis_exporter` v1.58.0 →
v1.88.0. Upstream had changed its default image to scratch in between — no
wget, no shell, nothing but the binary — so the compose healthcheck
`["CMD", "wget", "--spider", "-q", "http://localhost:9121/metrics"]` could not
start at all. Docker's health log recorded, five times:

    -1 OCI runtime exec failed: exec failed: unable to start container
    process: exec: "wget": executable file not found in $PATH

Docker therefore marked the container unhealthy. `stack-health-probe.py`
reported `observability: 9/10 ready FAILED: redis-exporter-1`, the STRICT
health-wait failed the converge after 1200 s, and the exporter was serving
metrics on :9121 throughout. The message named the service; the fault was in
the check. Every minute of diagnosis went to the wrong layer.

THE DISTINCTION THIS FILE HOLDS. "The check said no" and "the check never ran"
are different faults with different fixes — one is a service to repair, the
other is a probe to rewrite — and only the second is invisible in a `docker ps`
Status string, which is all the probe used to read.

WHAT IS DELIBERATELY UNCHANGED: the container is still counted FAILED and the
bring-up still fails. A container whose health cannot be established is not a
container known to be well, and downgrading it to "ready" would be this repo's
oldest defect — absence reading as calm — dressed up as a fix. Only the
DIAGNOSIS changes.

The estate already knew this hazard in prose: CLAUDE.md's operator gotcha about
Rust-slim images says a `wget --spider` check against an image without wget
"logs `wget: not found` and marks the container unhealthy". It was written for
Tier-2 manifests, it applies to every image, and nothing compared it to
anything until now.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "files/anatomy/scripts/stack-health-probe.py"


def _probe():
    spec = importlib.util.spec_from_file_location("nos_stack_health_probe", PROBE)
    assert spec and spec.loader, f"cannot load {PROBE}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nos_stack_health_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


#: Verbatim from `docker inspect` on the live container, 2026-08-06.
REAL_CANNOT_RUN = (
    '-1:OCI runtime exec failed: exec failed: unable to start container '
    'process: exec: "wget": executable file not found in $PATH'
)

#: A healthcheck that RAN and returned a verdict. Must not be confused with
#: the above — this one is about the service.
REAL_SERVICE_DOWN = (
    "1:wget: can't connect to remote host (127.0.0.1): Connection refused"
)


def test_it_recognises_a_check_that_never_started():
    assert _probe().blob_says_check_could_not_run(REAL_CANNOT_RUN), (
        "the probe does not recognise docker's own words for a healthcheck "
        "binary that is missing from the image — the exact string that cost a "
        "1200s converge on 2026-08-06"
    )


def test_it_does_not_swallow_a_real_failure():
    """The counterweight. A predicate that answered True for everything would
    satisfy the test above and hide every genuine outage behind 'the service
    may be fine'."""
    assert not _probe().blob_says_check_could_not_run(REAL_SERVICE_DOWN), (
        "a connection-refused healthcheck reads as 'the check could not run', "
        "so a dead service would be reported as a probe problem"
    )
    assert not _probe().blob_says_check_could_not_run(""), "empty log reads as cannot-run"


def test_a_container_whose_health_is_unknown_still_fails_the_bring_up():
    """The annotation must not become an exemption.

    `_classify` decides ready/pending/failed and knows nothing about WHY a
    check failed — which is what keeps the distinction diagnostic rather than
    permissive. If someone ever routes cannot-run to 'ready', a scratch image
    with a broken probe would sail through a STRICT health gate.
    """
    mod = _probe()
    assert mod._classify("Up 30 minutes (unhealthy)") == "failed"
    assert mod._classify("Up 30 minutes (healthy)") == "ready"
    assert mod._classify("Up 30 minutes") == "ready", (
        "a container with NO healthcheck must stay ready — that is a declared "
        "choice, not the same thing as a check that could not execute"
    )
    source = PROBE.read_text(encoding="utf-8")
    classify_body = source[source.find("def _classify"):source.find("def main(")]
    assert "could_not_run" not in classify_body, (
        "the cannot-run signal leaked into the classifier. It is a diagnosis, "
        "not a pass: a container whose health cannot be established is not a "
        "container known to be well."
    )


def test_the_diagnosis_reaches_the_operator_line():
    """It is only worth anything if it is printed where the converge fails."""
    source = PROBE.read_text(encoding="utf-8")
    main_body = source[source.find("def main("):]
    assert "_check_could_not_run" in main_body, (
        "main() never asks whether the check could run, so the snapshot the "
        "operator reads still names the service for a probe's fault"
    )
    assert "check cannot run" in main_body, "the failure line does not say so in words"
