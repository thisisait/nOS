"""A log file the estate writes must have something that bounds it.

WHAT THIS COST. Measured 2026-08-31: Traefik's `access.log` had reached
5.2 GB / 4 157 848 lines over 38 days on the SSD. It was the estate's most
complete request record — every routed request to ~50 services — and no reader
could reach it: Alloy did not tail it, no Pulse job touched it, no dashboard
queried it. The compose `logging: max-size 20m` looked like the answer and was
not; the docker log driver bounds a container's STDOUT, and this was a file
inside a bind mount the driver never sees.

Two separate silences, and each hid the other. The log grew because nothing
rotated it, and nobody noticed it growing because nothing read it — wired
observability that was never observed.

THE RULE. Config that names a `filePath` for a log is taking on rotation and
shipping as its own problem, and neither Traefik nor the express/FastAPI/Nette
organs have a rotator. Writing to stdout instead hands both to machinery
already standing: the json-file driver rotates, and Alloy's `discovery.docker`
already tails every container in the estate.

SCOPE, honestly. This checks the containerised services' rendered config, where
stdout is always available and always tailed. The HOST organs write real files
by necessity (launchd has no log driver) and are covered by the `organ_logs`
Alloy block instead — so they are read, and their sizes are the next thing to
bound. Measured the same day: no host organ log exceeded 50 MB.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: EVERY template rendered into a container's config, not a hand-kept list of
#: one (2026-09-01). A named list is a claim that only these files can carry the
#: defect, and that claim rots the moment someone adds a service — the same
#: argument tools/stale-config-status.py makes against an exclusion list. The
#: sweep costs nothing: measured repo-wide, `filePath:` appears in exactly zero
#: templates today, so widening it introduces no noise and closes the rot.
TEMPLATE_ROOTS = ("roles", "files/anatomy/plugins", "templates")

#: The one file the defect was measured in. If the sweep stops finding it, the
#: glob is wrong and every assertion below would pass vacuously.
CANARY = "roles/pazny.traefik/templates/traefik.yml.j2"

_FILEPATH = re.compile(r"^\s*filePath\s*:", re.M)


def _templates() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for root in TEMPLATE_ROOTS:
        found += sorted((ROOT / root).rglob("*.j2"))
    return found


def test_the_sweep_reaches_the_file_the_defect_was_measured_in() -> None:
    assert (ROOT / CANARY) in _templates(), (
        f"{CANARY} is not in the sweep — the glob moved and this gate would "
        "pass by finding nothing to check")


def test_no_container_log_config_names_a_file_path() -> None:
    offenders = []
    for path in _templates():
        body = path.read_text(encoding="utf-8", errors="replace")
        for match in _FILEPATH.finditer(body):
            rel = path.relative_to(ROOT)
            offenders.append(f"{rel}:{body[: match.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "a containerised service is told to write its log to a file: "
        + ", ".join(offenders)
        + ". Nothing in the estate rotates it and nothing tails it — the last one "
        "reached 5.2 GB unread. Drop the filePath and let it go to stdout, where "
        "the json-file driver rotates it and Alloy already ships it to Loki."
    )
