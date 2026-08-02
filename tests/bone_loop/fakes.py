"""Synthetic weakness sources, shaped like the real ones.

Kept out of conftest.py so the test modules can import them by name: a bare
`import conftest` resolves to tests/conftest.py, which is a different file.

The shapes here are copied from the live files, INCLUDING their defects — a
`summary` that can disagree with `items[]`, a CRITICAL item that is already
resolved, a status column that is free text. A fixture that only models the
happy shape cannot exercise a reader whose whole job is the unhappy one.
"""

from __future__ import annotations

PROPOSE_TOKEN = "p" * 64
JUDGE_TOKEN = "j" * 64


def make_queue(
    *,
    pending=(),
    resolved=0,
    generated_at="2026-08-01T04:14:42+02:00",
    summary_by_status=None,
):
    """A remediation queue. `resolved` items are CRITICAL on purpose: in the
    live file 37 items are CRITICAL and zero of them are pending."""
    items = []
    for i, (sev, component) in enumerate(pending, start=1):
        items.append({
            "id": f"REM-{i:03d}",
            "finding_ref": f"CVE-{i}",
            "component": component,
            "severity": sev,
            "current_version": "1.0.0",
            "fix_version": "1.0.1",
            "remediation_type": "version_bump",
            "remediation_detail": (
                f"Bump {component} to 1.0.1. Long trailing prose that should be clipped."
            ),
            "status": "pending",
            "source": "static_analysis",
            "confidence": "high",
            "found_at": "2026-07-01T12:00:00Z",
            "scan_cycle": 20,
        })
    for i in range(resolved):
        items.append({
            "id": f"REM-9{i:02d}",
            "component": "old",
            "severity": "CRITICAL",
            "remediation_type": "version_bump",
            "remediation_detail": "done",
            "status": "resolved",
        })
    doc = {"generated_at": generated_at, "generator": "test", "items": items}
    if summary_by_status is not None:
        doc["summary"] = {"by_status": summary_by_status}
    return doc


def make_scan_state(*, last_full_scan="2026-08-02T02:14:02Z", components=None):
    return {
        "initialized_at": "2026-04-08T12:00:00Z",
        "last_full_scan": last_full_scan,
        "scan_cycle": 21,
        "components": components if components is not None else {
            # `status: scanned` is stamped by the agent claiming to have
            # scanned — present here so a reader that trusted it would be
            # visibly trusting it.
            "traefik": {"last_checked": "2026-07-30T04:00:50+02:00", "status": "scanned"},
        },
    }


#: Free-text status column, closed/partly/open + a "being paid now" bill —
#: every variant measured in the live index.
FEES_README = """# Hidden fees

## Index

| # | Fee | Bill comes due when | Status |
|---|---|---|---|
| [01](01-alpha.md) | A dead override lingers | a service is toggled off | open |
| [02](02-beta.md) | Healthchecks that skip the DB | a DB is reinitialised | partly closed |
| [03](03-gamma.md) | A slug cannot be a node id | ~~someone adds one~~ | **closed 2026-07-26** |
| [09](09-delta.md) | The vector index is 8x too large | being paid now — 449 MB | open |
"""

FEE_FILE = """# {slug}

## The fee

{body}

## When the bill comes due

Later.
"""

FEE_FILES = (
    ("01-alpha.md", "An override for a disabled service keeps merging."),
    ("02-beta.md", "The healthcheck answers without touching its database."),
    ("03-gamma.md", "A leading digit breaks the node id."),
    ("09-delta.md", "The index is eight times larger than it needs to be."),
)
