"""`wing.write` is one spelling for two different axes. Do not compare them.

MEASURED 2026-08-29, after the converge that shipped the ops plane, and the
first version of this gate got it WRONG — which is the finding worth keeping.

`conductor` held `wing.read,wing.write` in `api_tokens` while its manifest holds
no write tool. That looked like a widening, so this file first asserted that the
manifest and the mint must agree. It then failed on `surveyor`, which declares
`wing.write` and is minted `wing.read` — and surveyor is CORRECT. The two are
different things wearing the same string:

  * `agent.yml: audit.capability_scopes` — TOOL ADMISSION. `ToolRegistry` refuses
    to load `mcp-wing-write` without `wing.write` here. Surveyor needs it to
    issue any POST at all.
  * `api_tokens.scopes` — HTTP ROUTE CLASS. `TokenRepository::permits()` reads it
    per request. Surveyor does NOT need it, because `EventsPresenter` declares
    `publicActions = ['default']` and its POST is HMAC-gated, taking no bearer.

So a gate that equates them refuses a correct configuration. What is left after
that correction is smaller and true:

  * the live row must match what the provisioning task mints — a converge
    re-mints, so a mismatch is an un-converged change or a hand edit;
  * and the token axis is declared in exactly ONE place, the ansible task. There
    is no per-agent manifest field for it, which is why conductor's grant was
    invisible: nothing was contradicted, because nothing else said anything.

That second point is a gap this gate can only report, not close.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
POST = REPO / "roles/pazny.wing/tasks/post.yml"
WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"

WING_SCOPES = {"wing.read", "wing.write"}


def minted() -> dict[str, set[str]]:
    """`--name=X` … `--scopes=a,b` pairs, read out of the provisioning task."""
    src = POST.read_text(encoding="utf-8")
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"--name=([a-z][a-z0-9-]*)(.*?)(?=\n\s*- name:|\Z)", src, re.S):
        scopes = re.search(r"--scopes=([a-z0-9_.,]+)", m.group(2))
        if scopes:
            out[m.group(1)] = {s for s in scopes.group(1).split(",")} & WING_SCOPES
        elif "capability_scopes" in m.group(2):
            # Ruling 3 (2026-09-03): agent mints DERIVE scopes from their
            # manifest — resolve the same file the template names.
            import yaml
            ay = AGENTS / m.group(1) / "agent.yml"
            if ay.is_file():
                caps = (yaml.safe_load(ay.read_text()).get("audit") or {}
                        ).get("capability_scopes") or []
                out[m.group(1)] = {c for c in caps} & WING_SCOPES
    return out


def test_the_sweep_sees_the_mints() -> None:
    """Positive control — an empty read makes everything below vacuous."""
    m = minted()
    assert len(m) >= 4, f"only {len(m)} minted tokens found in {POST.name}"
    assert any(m.values()), "no minted token carries a wing scope; the flag has been renamed"


def test_the_token_axis_is_declared_exactly_once() -> None:
    """The gap, stated rather than closed.

    If a per-agent field for the HTTP route class ever appears, this gate should
    start comparing it — and this test is where a reader will find out that the
    comparison was deliberately absent, not forgotten.
    """
    fields = set()
    for d in sorted(AGENTS.iterdir()):
        f = d / "agent.yml"
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        fields |= set(doc.keys())
    assert "api_token_scopes" not in fields and "token_scopes" not in fields, (
        "an agent manifest now declares its HTTP route class. Good — but this "
        "gate still compares only the task to the live row. Extend it to three."
    )


@pytest.mark.skipif(not WING_DB.is_file(),
                    reason="no wing.db on this host — the live half is UNKNOWN, not green")
def test_the_live_row_matches_what_the_task_mints() -> None:
    conn = sqlite3.connect(f"file:{WING_DB}?mode=ro&immutable=1", uri=True)
    try:
        rows = dict(conn.execute("SELECT name, COALESCE(scopes,\'\') FROM api_tokens").fetchall())
    finally:
        conn.close()
    m = minted()
    drift = {
        name: {"live": live or "(none)", "task": ",".join(sorted(m[name])) or "(none)"}
        for name, live in rows.items()
        if name in m and ({s for s in live.split(",") if s} & WING_SCOPES) != m[name]
    }
    assert not drift, (
        f"the live api_tokens row disagrees with what post.yml mints: {drift}. "
        f"A converge re-mints, so this is an un-converged change or a hand edit."
    )
