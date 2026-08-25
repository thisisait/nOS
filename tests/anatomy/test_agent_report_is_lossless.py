"""The agent's drafts must survive the trip from wing.db to the operator.

WHAT HAPPENED (2026-08-25, upgrade-architect run 8c52551a). The agent's 12
drafted recipes lived in a conductor_report event, correctly escaped: one
json.loads() of result_json yields `from_regex: "^8\\."` — valid YAML, the
exact form the recipe files use. The launcher's saved report did not contain
them (tail -60 of stdout, zero ```yaml blocks), so the operator extracted by
hand, a shell round-trip ate one backslash level, `"^8\."` is an invalid
double-quoted escape, and six of ten files failed to parse. The commit that
repaired them (99465662) blamed "the report event's JSON" — measured here,
the event was lossless; the READ-OUT was the lossy hop.

WHAT IS PINNED. tools/agent-report.py is the owned read-out: one JSON decode,
stdout via sys.stdout.write, byte-exact backslashes, YAML in the report parses
verbatim. The gate also demonstrates the failure mode it replaces (printf %b
eats the level) so the distinguishing power is visible, and pins that the
upgrade-architect launcher actually CALLS the tool — a lossless tool nobody
invokes repairs nothing.

WHAT IT CANNOT SEE. Whether the agent's own POST into the event was lossless
for some future agent (only the stored artifact is testable offline), and
whether the operator pipes the tool's output through something lossy anyway.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/agent-report.py"
LAUNCHER = REPO / "tools/run-upgrade-architect.sh"

# The draft shape that broke on 2026-08-25: double backslash inside a
# double-quoted YAML scalar, plus diacritics (the 2026-07-27 HMAC lesson says
# non-ASCII is where transports cheat).
DRAFT_YAML = '  - id: "redis-8-current"\n    from_regex: "^8\\\\."\n    to: "8.10.1"\n'
REPORT = (
    "## Upgrade architect report\n\nPříliš žluťoučký kůň.\n\n"
    "```yaml\n" + DRAFT_YAML + "```\n\nNOS_AGENT_EXIT: 1\n"
)


def _fixture_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "wing.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, type TEXT, "
        "source TEXT, result_json TEXT)"
    )
    payload = json.dumps({"report": REPORT, "recipes_drafted": 1, "agent_exit": 1})
    con.execute(
        "INSERT INTO events (ts, type, source, result_json) VALUES (?,?,?,?)",
        ("2026-08-25T17:37:04Z", "conductor_report", "upgrade-architect", payload),
    )
    # An older report from the same agent — --since and ORDER BY must skip it.
    con.execute(
        "INSERT INTO events (ts, type, source, result_json) VALUES (?,?,?,?)",
        ("2026-08-01T00:00:00Z", "conductor_report", "upgrade-architect",
         json.dumps({"report": "stale report"})),
    )
    con.commit()
    con.close()
    return db


def _run(db: pathlib.Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), "--agent", "upgrade-architect", "--db", str(db), *extra],
        capture_output=True, text=True, timeout=60,
    )


def test_the_report_arrives_byte_exact(tmp_path):
    out = _run(_fixture_db(tmp_path))
    assert out.returncode == 0, out.stderr
    assert 'from_regex: "^8\\\\."' in out.stdout, (
        "the double backslash did not survive — this is the exact loss that "
        f"broke six of ten drafts on 2026-08-25:\n{out.stdout}")
    assert "Příliš žluťoučký kůň." in out.stdout, "diacritics were re-escaped"
    assert "stale report" not in out.stdout, "newest-first ordering broke"


def test_the_yaml_block_parses_to_the_regex_the_recipes_use(tmp_path):
    out = _run(_fixture_db(tmp_path))
    block = out.stdout.split("```yaml\n", 1)[1].split("```", 1)[0]
    parsed = yaml.safe_load(block)
    assert parsed[0]["from_regex"] == "^8\\.", (
        "the recipe regex decoded to something other than ^8\\. — applied "
        f"verbatim this draft would not match the pin: {parsed!r}")


def test_the_shell_round_trip_it_replaces_is_lossy(tmp_path):
    """The broken direction, kept runnable: pipe the same report through the
    kind of shell interpolation the hand extraction used, and watch the
    backslash level vanish. If this ever PASSES through printf %b unmangled,
    the fixture no longer exercises the failure mode and must be reshaped."""
    mangled = subprocess.run(
        ["bash", "-c", 'printf %b "$1"', "_", REPORT],
        capture_output=True, text=True, timeout=60,
    ).stdout
    assert 'from_regex: "^8\\."' in mangled and 'from_regex: "^8\\\\."' not in mangled, (
        "printf %b no longer eats a backslash level — the gate's broken-"
        "direction demonstration is dead, reshape it")
    try:
        yaml.safe_load(mangled.split("```yaml\n", 1)[1].split("```", 1)[0])
        parsed_ok = True
    except yaml.YAMLError:
        parsed_ok = False
    assert not parsed_ok, (
        "the mangled form parsed as YAML — then the 2026-08-25 failure would "
        "have been invisible and this gate proves nothing")


def test_since_filters_and_absence_is_an_error(tmp_path):
    db = _fixture_db(tmp_path)
    out = _run(db, "--since", "2026-09-01T00:00:00Z")
    assert out.returncode == 1, (
        "no event in the window must exit 1 — a silent empty stdout is how a "
        "launcher would embed nothing and still claim the drafts are inside")
    assert out.stdout == ""


def test_the_launcher_reads_through_this_tool():
    """Structural: run-upgrade-architect.sh must obtain the drafts via
    tools/agent-report.py (scoped to THIS run via --since) instead of trusting
    a tail of stdout. Code reference, not prose — the string asserted is the
    invocation itself."""
    src = LAUNCHER.read_text(encoding="utf-8")
    assert "tools/agent-report.py" in src or "agent-report.py" in src, (
        "the launcher no longer extracts the report from the event store; "
        "its saved file is back to tail-of-stdout and the drafts are lost")
    assert "--agent" in src and "--since" in src, (
        "the launcher's agent-report.py call must scope by agent and by this "
        "run's start time, or a stale report can masquerade as this run's")
