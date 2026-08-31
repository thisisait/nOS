"""A proposal names the run that authored it, or the loop's entry has no cost.

WHAT CHANGED, AND WHY IT NEEDED A GATE (2026-08-29). `tools/loop-propose.py`
used to spawn `claude --print --permission-mode bypassPermissions`: the
operator's own session, unattended. Every event it wrote was attributed to the
operator, no `agent_sessions` row existed, no tokens were tallied, no ceiling
applied, and the proposal that came out named nothing. The loop's ENTRY was the
one step of the loop with no record of itself — while every other step wrote a
row. It now opens an AgentKit session through `tools/run-agent.sh`
(`bin/run-agent.php`, the anthropic adapter, one `agentkit` slot of the Q12
lock) and threads that session's uuid through to the proposal POST.

THE CLAIM UNDER TEST is a JOIN, so it is asserted as one:

    loop_proposals.session_uuid  ->  agent_sessions.uuid

An orphan on that join is the defect returning in disguise — a proposal exists,
and what it cost is unknowable. `agent_sessions.model_uri` is NOT NULL in the
real schema (this gate creates the table from
files/anatomy/wing/db/schema-extensions.sql, not from a hand-copy), so a row
that names no model cannot be the far side of the join either.

HOW IT RUNS THE REAL THING. `invoke()` — the real entry point, real argv
construction, real read-back — against a temp wing.db, with the RUNNER
substituted (`NOS_LOOP_AGENT_RUNNER`) for a stub standing exactly where
run-agent.php stands: it is handed `--session-uuid`, and it writes the session
row and the proposal the way the runtime would. Nothing else is faked. What the
stub CANNOT prove is that a real session resolves a real backend, so that half
is asserted separately by running the actual `App\\AgentKit\\LLMClient\\
BindingResolver` over the committed registry and requiring the session's
model_uri to be what it returns (skipped, loudly, without php).

ponytail: the stub stands in for run-agent.php because a real one spends money
at a third party. If the loop ever gets a recorded-cassette runtime, replace it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"
SCHEMA = WING / "db/schema-extensions.sql"
PROPOSER = REPO / "tools/loop-propose.py"

if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

WEAKNESS = {"id": "hidden-fee:08", "severity": "high",
            "title": "a weakness the temp ledger will accept"}
WEAKNESS_INDEX = {"hidden-fee:08": "sha-08"}
ALLOWED = "roles/pazny.gitea/defaults/main.yml"

#: What the stub session declares it ran on when the resolver is unavailable.
FALLBACK_URI = "anthropic-claude-sonnet-4-5"


def _load_proposer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_loop_propose_entry", PROPOSER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _agent_sessions_ddl() -> str:
    """The REAL CREATE TABLE, lifted from the schema the daemon applies. A
    hand-written copy here would drift into accepting a NULL model_uri, and
    then the join would be satisfiable by a row that names no model."""
    sql = SCHEMA.read_text(encoding="utf-8")
    m = re.search(r"CREATE TABLE IF NOT EXISTS agent_sessions\b.*?\n\);", sql, re.S)
    assert m, f"agent_sessions DDL not found in {SCHEMA} — the gate lost its subject"
    return m.group(0)


# ── the stub that stands where bin/run-agent.php stands ──────────────────────
# It does the two things the runtime does and nothing else: open the session it
# was told to open, and let the agent POST a proposal naming it.
_STUB = r'''#!/usr/bin/env python3
import json, os, sqlite3, sys
argv = sys.argv[1:]
json.dump(argv, open(os.environ["NOS_STUB_ARGV_OUT"], "w"))
opt = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in argv if a.startswith("--") and "=" in a}
if os.environ.get("NOS_STUB_SILENT") == "1":
    sys.exit(0)                      # a run that produced nothing
uuid = opt["--session-uuid"]
db = os.environ["WING_DB_PATH"]
conn = sqlite3.connect(db)
conn.execute(
    "INSERT INTO agent_sessions (uuid, agent_name, agent_version, status, trigger,"
    " actor_id, trace_id, model_uri, started_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
    (uuid, opt["--agent"], 1, "idle", opt.get("--trigger", "operator"),
     "agent:" + opt["--agent"], "0" * 32, os.environ["NOS_STUB_MODEL_URI"]))
conn.commit()
conn.close()

sys.path.insert(0, os.environ["NOS_BONE_DIR"])
import ledger
led = ledger.open_ledger("proposer", weakness_index=json.loads(os.environ["NOS_STUB_WEAKNESS_INDEX"]))
path = os.environ["NOS_STUB_PATH"]
led.record_proposal(
    weakness_id=os.environ["NOS_STUB_WEAKNESS"],
    target_paths=[path], intent_class="config-fix", gate_set="repo",
    tree_sha="a" * 40, proposer_id="agent:proposer",
    diff_text="diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n-a\n+b\n" % (path, path, path, path),
    session_uuid=(None if os.environ.get("NOS_STUB_ORPHAN") == "1" else uuid))
led.close()
print(json.dumps({"session_uuid": uuid}))
'''


@pytest.fixture()
def estate(tmp_path, monkeypatch, resolved_model_uri):
    """A temp wing.db carrying BOTH sides of the join, and a stubbed runner."""
    db = tmp_path / "wing.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_agent_sessions_ddl())
    conn.commit()
    conn.close()

    stub = tmp_path / "run-agent-stub.py"
    stub.write_text(_STUB)
    stub.chmod(0o755)
    argv_out = tmp_path / "argv.json"

    for k, v in {
        "WING_DB_PATH": str(db),
        "WING_EVENTS_HMAC_SECRET": "names-a-session-test-secret",
        "NOS_LOOP_AGENT_RUNNER": str(stub),
        "NOS_LOOP_PROPOSER_AGENT": "proposer",
        "NOS_BONE_DIR": str(BONE),
        "NOS_STUB_ARGV_OUT": str(argv_out),
        "NOS_STUB_MODEL_URI": resolved_model_uri or FALLBACK_URI,
        "NOS_STUB_WEAKNESS": WEAKNESS["id"],
        "NOS_STUB_WEAKNESS_INDEX": json.dumps(WEAKNESS_INDEX),
        "NOS_STUB_PATH": ALLOWED,
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("NOS_STUB_SILENT", "NOS_STUB_ORPHAN"):
        monkeypatch.delenv(k, raising=False)

    mod = _load_proposer()
    return mod, db, argv_out


def run(estate) -> int:
    mod, _, _ = estate
    return mod.invoke(dict(WEAKNESS), lambda line: None)


def rows(db, sql, *args):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# ── the join ─────────────────────────────────────────────────────────────────

def test_every_proposal_names_a_session_that_exists(estate):
    mod, db, _ = estate
    assert run(estate) == 0, "the real invoke() did not accept its own run"

    props = rows(db, "SELECT * FROM loop_proposals")
    assert props, (
        "ANTI-VACUITY: no proposal was recorded, so the join below holds over "
        "an empty table and proves nothing"
    )
    orphans = rows(db,
                   "SELECT p.uuid FROM loop_proposals p "
                   "LEFT JOIN agent_sessions s ON s.uuid = p.session_uuid "
                   "WHERE s.uuid IS NULL")
    assert orphans == [], (
        f"{len(orphans)} proposal(s) name no session: {orphans} — the cost of "
        "the run that authored them is unknowable, which is the defect the "
        "AgentKit cutover closed"
    )
    joined = rows(db,
                  "SELECT s.agent_name, s.model_uri, s.trigger "
                  "FROM loop_proposals p JOIN agent_sessions s "
                  "ON s.uuid = p.session_uuid")
    assert joined and joined[0]["agent_name"] == "proposer"
    assert joined[0]["model_uri"], "a session that names no model is not a run"


def test_the_uuid_on_the_row_is_the_uuid_that_was_spawned(estate):
    """The two halves must be the SAME uuid. A stub minting its own would
    satisfy the join while the proposer's `--session-uuid` went nowhere."""
    _, db, argv_out = estate
    run(estate)
    argv = json.loads(argv_out.read_text())
    passed = [a.split("=", 1)[1] for a in argv if a.startswith("--session-uuid=")]
    assert len(passed) == 1, f"the spawn must carry exactly one session uuid: {argv}"
    assert rows(db, "SELECT session_uuid FROM loop_proposals")[0]["session_uuid"] \
        == passed[0]


def test_a_proposal_without_its_session_is_not_reported_as_success(estate, monkeypatch):
    """The success marker is written by the READER. A run that produced a
    proposal naming no session must not exit 0 — that is precisely the state
    the old path was permanently in."""
    monkeypatch.setenv("NOS_STUB_ORPHAN", "1")
    assert run(estate) == 1
    assert rows(estate[1], "SELECT session_uuid FROM loop_proposals")[0]["session_uuid"] is None


def test_a_run_that_proposed_nothing_is_not_success(estate, monkeypatch):
    monkeypatch.setenv("NOS_STUB_SILENT", "1")
    assert run(estate) == 1
    # Through the module's OWN reader: a wing.db with no ledger table yet must
    # read as "no proposals", not raise — absence is a fact, not an error.
    assert estate[0]._proposals_citing(WEAKNESS["id"]) == []


# ── the spawn is an AgentKit run, not a CLI bypass ───────────────────────────

def test_the_spawn_is_an_agentkit_session_not_a_permission_bypass(estate):
    _, _, argv_out = estate
    run(estate)
    argv = json.loads(argv_out.read_text())
    flat = " ".join(argv)
    assert "bypassPermissions" not in flat and "--print" not in flat, (
        f"the proposer is spawning the operator's own claude session again: {flat[:200]}"
    )
    assert any(a.startswith("--agent=") for a in argv), (
        "an AgentKit run names the agent whose profile, principals and "
        "Article-30 record govern it"
    )


def test_the_default_runner_exists(monkeypatch):
    """Unconfigured, the proposer must resolve to a runner that is really
    there. It holds no mutex of its own — `tools/run-agent.sh` takes one
    `agentkit` slot of the Q12 lock, and that acquisition is pinned by
    tests/anatomy/test_cli_lock_excludes_agentkit_slots.py, which runs the
    lock script rather than reading it."""
    monkeypatch.delenv("NOS_LOOP_AGENT_RUNNER", raising=False)
    runner = _load_proposer().RUNNER
    assert runner.is_file(), (
        f"the default runner {runner} does not exist — the proposer would "
        "refuse every run"
    )


# ── the model_uri really came from the resolver ──────────────────────────────

_PHP_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1];

use App\AgentKit\Agent;
use App\AgentKit\LLMClient\BindingResolver;
use App\AgentKit\LLMClient\Factory;
use App\AgentKit\Vault\CredentialResolver;

[$_, $autoload, $registryPath, $primaryUri] = $argv;

$agent = new Agent(
    name: 'proposer', version: 1, description: 'the loop proposer',
    modelPrimaryUri: $primaryUri, modelFallbackUri: null, modelGraderUri: null,
    systemPrompt: null, tools: [], rubric: null, maxIterations: 1,
    capabilityScopes: [], piiClassification: 'none', requiredCredentials: [],
    subscriptions: [], metadata: [], sourceDir: '/nonexistent',
    backendName: null,
    gdpr: ['processors' => [['name' => 'Anthropic, PBC']]],
);

$credentials = (new ReflectionClass(CredentialResolver::class))->newInstanceWithoutConstructor();
$decision = (new BindingResolver($credentials, $registryPath))->resolve($agent);
$llm = (new Factory($credentials))->fromUri($agent->modelPrimaryUri, $decision->binding);
echo json_encode(['model_uri' => $llm->identifier(), 'backend' => $llm->backendName()]);
"""


@pytest.fixture(scope="module")
def resolution(tmp_path_factory) -> dict | None:
    """What `BindingResolver` + the client factory actually serve a proposer
    session on this checkout: the model_uri the runtime writes into
    `agent_sessions.model_uri`, and the backend that carries it. None when
    php/vendor is absent."""
    php = shutil.which("php")
    if php is None or not AUTOLOAD.is_file():
        return None
    tmp = tmp_path_factory.mktemp("proposer-binding")
    harness = tmp / "harness.php"
    harness.write_text(_PHP_HARNESS)
    out = subprocess.run(
        [php, str(harness), str(AUTOLOAD),
         str(REPO / "state/llm-backends.yml"), FALLBACK_URI],
        capture_output=True, text=True, timeout=120,
        # A fake key: buildAnthropic refuses to construct a client without one,
        # and nothing here ever sends. HOME is a tmp dir so the operator's own
        # ~/.nos/secrets.yml is not read.
        env={"HOME": str(tmp), "PATH": f"{Path(php).parent}:/usr/bin:/bin",
             "ANTHROPIC_API_KEY": "harness-key-never-sent"},
    )
    if out.returncode != 0:
        pytest.fail(f"the binding harness died: {out.stderr[-600:]}")
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def resolved_model_uri(resolution) -> str | None:
    return None if resolution is None else resolution["model_uri"]


def test_a_proposer_session_resolves_onto_the_anthropic_adapter(resolution):
    """Ruling from state/llm-backends.yml:26-28: the SDK adapter is the only
    one that keeps TOOLS through a binding, and a proposer with no tools cannot
    read the budget it must stay inside. So the resolver must not hand this
    ceremony to the tool-less CLI path — or to a refusal."""
    if resolution is None:
        pytest.skip(
            "php or files/anatomy/wing/vendor/autoload.php missing — the "
            "resolver half is unproven HERE; the join above still ran. "
            "Run `composer install` in files/anatomy/wing to cover it."
        )
    assert resolution["backend"] == "anthropic", (
        f"a proposer session resolves onto {resolution['backend']!r} — if that "
        "adapter cannot carry tool schemas the run has no way to read its "
        "budget, and every proposal it files is outside a boundary it never saw"
    )


def test_the_session_model_uri_is_what_the_resolver_returns(estate, resolved_model_uri):
    if resolved_model_uri is None:
        pytest.skip("php or wing vendor missing — see the sibling skip above")
    run(estate)
    session = rows(estate[1], "SELECT model_uri FROM agent_sessions")[0]
    assert session["model_uri"] == resolved_model_uri, (
        f"the session ran on {session['model_uri']!r} but BindingResolver "
        f"serves a proposer {resolved_model_uri!r} — a session whose model is "
        "not the resolved one is outside the register that permits it"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AND THE AUTHOR, added 2026-08-31 — the same defect one field over.
#
# `nos-loop propose` defaults `--proposer-id` to `operator:$USER`, which is
# right for a human at a terminal and false for every agent run, because
# McpLoopTool never sent the flag. Measured that morning:
#
#     uuid …aa4bb912   rem:REM-156   proposer_id: operator:pazny   01:33:35
#
# Filed by the unattended nightly `loop:propose` job. The operator was asleep.
#
# It reads as cosmetic and is not. The loop's safety argument is that any
# proposal can be traced to what authored it and what that cost; a model's work
# wearing the operator's name defeats that at the first question anyone asks of
# it, and it is precisely the direction of mis-attribution that matters — an
# agent's diff looks reviewed-by-a-human.
#
# Stamped from the tool context exactly like the session uuid, and for the same
# stated reason: a value the MODEL supplies names whoever the model chose.

def _stamped_args(sub: str = "propose") -> list[str]:
    """The argv McpLoopTool builds, read out of its source.

    A behavioural test would need the PHP tool container; this reads the two
    stamps as a pair, because the failure that matters is one of them being
    added and the other forgotten — which is exactly what happened."""
    src = (REPO / "files/anatomy/wing/app/AgentKit/Tools/McpLoopTool.php").read_text(
        encoding="utf-8")
    return src.split("$argv = array_merge")[0]


def test_an_agent_authored_proposal_is_not_stamped_as_the_operator() -> None:
    body = _stamped_args()
    assert "'--proposer-id'" in body, (
        "McpLoopTool does not stamp --proposer-id, so nos-loop's default "
        "`operator:$USER` applies and every agent-authored proposal is "
        "recorded as the human at the terminal")
    assert "$context->actorId" in body, (
        "--proposer-id is being supplied from something other than the tool "
        "context; a value the model can choose names whoever it chose")


def test_both_stamps_are_conditional_on_the_model_not_having_sent_one() -> None:
    """Neither stamp may overwrite an explicit argument — a duplicate flag is
    an argparse error, and the run would die on the tool call instead of
    proposing."""
    body = _stamped_args()
    for flag in ("--session-uuid", "--proposer-id"):
        assert f"!in_array('{flag}', $args, true)" in body, (
            f"{flag} is appended unconditionally; if the model also passes it "
            "the CLI sees the flag twice")
