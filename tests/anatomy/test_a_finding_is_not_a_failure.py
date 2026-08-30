"""A pulse panel that judges an exit code must read `findings_exit_codes`.

MEASURED 2026-08-29, within a day of `docs/hidden_fees/32` — the same defect,
one organ over, and this time the estate had already written down the answer.

`pulse_jobs.findings_exit_codes` is a JSON array of the exit codes a job uses to
mean *I found something*: `discovery:contradiction-scan` and
`gitleaks:nightly-scan` declare `[1]`, `loop:propose` declares `[1,3]`. The
column has existed for months. The first draft of `27-pulse.json` classified any
non-zero exit as a failure and produced this table:

    discovery:contradiction-scan   24 runs   16 failed   66.7%   ← top of the list

Sixteen of those were contradictions found. The detector was working perfectly
and led the failure ranking on the surface an operator uses to decide what to
fix. Read with the column, the same thirty days say `0 failed, 16 found`, and
the real failures — `alert-relay:relay-firing` at 157, `wing:audit-chain-verify`
at 4 — stop being buried under a working job.

WHAT MAKES THIS WORTH ITS OWN GATE rather than a careful author. Fee 32's lesson
was "no gate reads questions", and that is still true — nothing here can tell
whether a panel's TITLE matches its SQL. But this is a narrower and checkable
claim: a query that branches on `exit_code` and never mentions
`findings_exit_codes` has decided that every non-zero exit is a fault, and it
decided it silently.

Retro-verified 2026-08-29 against a panel with the column stripped out.
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3

REPO = pathlib.Path(__file__).resolve().parents[2]
DASH = (REPO / "files/anatomy/plugins/grafana-base/provisioning/dashboards"
        / "27-pulse.json")
SCHEMA = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"


def _queries() -> list[tuple[str, str]]:
    dash = json.loads(DASH.read_text(encoding="utf-8"))
    return [(p.get("title", "?"), t["rawQueryText"])
            for p in dash.get("panels", []) for t in p.get("targets") or []
            if t.get("rawQueryText")]


def test_every_verdict_on_an_exit_code_consults_the_declaration() -> None:
    for title, q in _queries():
        # A query that only counts zeros (`exit_code = 0`) is stating a fact.
        # One that puts a name on non-zero is passing judgement.
        if not re.search(r"exit_code\s*(<>|!=)\s*0", q):
            continue
        assert "findings_exit_codes" in q, (
            f"panel {title!r} classifies a non-zero exit without reading "
            "pulse_jobs.findings_exit_codes, so a job that exits 1 to report a "
            "finding is reported as broken:\n  " + q)


def test_the_declaration_is_matched_as_a_whole_code() -> None:
    """`[1]` must not match exit code 11, and `[13]` must not match 3. The
    text form pads both sides with commas for exactly this reason; a LIKE
    without them is a false green on a neighbouring code."""
    conn = sqlite3.connect(":memory:")
    for stmt in re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?.*?\n\);",
                           SCHEMA.read_text(encoding="utf-8"), re.S):
        conn.executescript(stmt)
    # Both directions of the substring trap. `narrow` declares [1] and must not
    # claim exit 11 or 13; `wide` declares [13] and must not claim exit 1 or 3.
    for job, codes in (("narrow", "[1]"), ("wide", "[13]")):
        conn.execute("INSERT INTO pulse_jobs (id, plugin_name, job_name, command, "
                     "schedule, findings_exit_codes) VALUES (?,'p','n','c','* * * * *',?)",
                     (job, codes))
        for code in (1, 3, 11, 13):
            conn.execute("INSERT INTO pulse_runs (run_id, job_id, fired_at, "
                         "finished_at, exit_code) VALUES (?, ?, '2026-08-29', "
                         "'2026-08-29', ?)", (f"{job}-{code}", job, code))

    title, query = next((t, q) for t, q in _queries() if "findings_exit_codes" in q
                        and "GROUP BY r.job_id" in q)
    got = {row[0]: row[3] for row in conn.execute(query)}
    assert got == {"narrow": 1, "wide": 1}, (
        f"panel {title!r} counted {got}; each job declares exactly one code and "
        "ran it once, so each must report one finding. Anything else is a "
        "substring match: [1] claiming 11, or [13] claiming 1.")


def test_the_dashboard_says_so_where_a_reader_will_see_it() -> None:
    """The rule is not obvious from a table of numbers. It belongs in the
    panel's own description, which is where a doubted figure gets checked."""
    dash = json.loads(DASH.read_text(encoding="utf-8"))
    prose = " ".join(p.get("description", "") + p.get("options", {}).get("content", "")
                     for p in dash.get("panels", []))
    assert "findings_exit_codes" in prose, (
        "no panel explains that a non-zero exit can be a finding — the number "
        "is right and the reader has no way to know why it differs from `wc`")


# ─────────────────────────────────────────────────────────────────────────────
# THE SAME RULE, ONE MORE ORGAN OVER — added 2026-08-30.
#
# The gates above cover the Grafana panels. The WEAKNESS READER had the identical
# defect and it was worse, because the loop consumes it: `_source_pulse_runs`
# selected `exit_code <> 0` and never read the declaration. Measured against the
# live ledger, of six jobs it called failed, TWO had succeeded —
# `discovery:contradiction-scan` (declares [1]) and `loop:propose` (declares
# [1,3]).
#
# `loop:propose` is the LOOP'S OWN ENTRY. Three such nights ratchet a weakness to
# HIGH (`_PULSE_STREAK_DEPTH`), so the loop mined itself as a high-severity
# weakness — one its own `files/anatomy/bone/**` deny rule forbids it from
# proposing against — for exiting 1 to say it had found work. Fable's review named
# this shape before it was measured (docs/idea/19-fable-review-2.md §3.1).
#
# Retro-verified 2026-08-30 by restoring the bare `exit_code <> 0` filter.

def test_the_weakness_reader_does_not_mine_a_finding_as_a_failure(tmp_path) -> None:
    import importlib.util
    import os
    import sqlite3
    import sys

    db = tmp_path / "wing.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, findings_exit_codes TEXT);
        CREATE TABLE pulse_runs (job_id TEXT, exit_code INT, fired_at TEXT, stderr_tail TEXT);
    """)
    conn.executemany("INSERT INTO pulse_jobs VALUES (?,?)", [
        ("finder", "[1,3]"),      # exits 1 to say "found something"
        ("breaker", None),        # no declaration: 1 is a failure
        ("malformed", "{oops"),   # a bad declaration must not silence a red job
    ])
    conn.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?)", [
        # Three findings nights in a row: the streak that used to ratchet to HIGH.
        ("finder", 1, "2026-08-28T01:00:00Z", ""),
        ("finder", 1, "2026-08-29T01:00:00Z", ""),
        ("finder", 1, "2026-08-30T01:00:00Z", ""),
        ("breaker", 1, "2026-08-30T01:00:00Z", "boom"),
        ("malformed", 1, "2026-08-30T01:00:00Z", "boom"),
    ])
    conn.commit()
    conn.close()

    spec = importlib.util.spec_from_file_location(
        "weaknesses_findings", REPO / "files/anatomy/bone/weaknesses.py")
    mod = importlib.util.module_from_spec(spec)
    old = os.environ.get("WING_DB_PATH")
    os.environ["WING_DB_PATH"] = str(db)
    # weaknesses.py imports its siblings by bare name (`import judges`), the way
    # Bone runs it. Put its own directory on the path rather than rewriting the
    # module to suit a test.
    sys.path.insert(0, str(REPO / "files/anatomy/bone"))
    # Registered before exec: `@dataclass` resolves its annotations through
    # sys.modules[cls.__module__], which is None for a module that ran without
    # being registered — and the failure names dataclasses, not this line.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        report = mod._source_pulse_runs(set())
    finally:
        sys.path.remove(str(REPO / "files/anatomy/bone"))
        sys.modules.pop(spec.name, None)
        if old is None:
            os.environ.pop("WING_DB_PATH", None)
        else:
            os.environ["WING_DB_PATH"] = old

    reported = {w.weakness_id: w for w in report.weaknesses}
    assert "pulse:finder" not in reported, (
        "a job that declares exit 1 as a finding is reported as failed — three "
        "such nights ratchet it to HIGH, which is how the loop came to mine its "
        "own entry as a weakness it may not fix")
    assert "pulse:breaker" in reported, (
        "a job with NO declaration must still be red on exit 1; the fix must "
        "not become a blanket amnesty")
    assert "pulse:malformed" in reported, (
        "a malformed findings_exit_codes silenced a red job — an unparseable "
        "declaration is not a declaration")
