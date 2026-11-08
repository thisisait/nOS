"""One journey through a Wing agent session: open, loop, fall back, grade, judge, stop, reap.

Merged 2026-11-08 (roadmap gate-diet-role-journeys). Absorbed, assert for assert:
  test_a_revision_sees_its_own_attempt.py
  test_a_fallback_says_that_it_answered.py
  test_the_grader_retry_says_what_was_wrong.py
  test_grader_sees_the_work.py
  test_the_latest_run_is_picked_before_it_is_judged.py
  test_bound_agent_can_file_its_report.py
  test_a_bound_session_binds_every_client.py
  test_an_unrunnable_judge_is_not_failed_work.py
  test_a_session_can_be_stopped.py
  test_a_dead_session_is_closed_by_a_successor.py

Most checks are source-level (Wing has no PHP unit harness); the php sections run the
real classes and skip, counted, without php or the wing vendor tree.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess

import pytest
import yaml

from test_a_child_session_names_its_parent import _HARNESS
from test_face_user_owns_its_sessions import AUTOLOAD, WING, _agents, needs_php, needs_vendor

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = WING / "app"
RUNNER = APP / "AgentKit/Runner.php"

# Honest only outside a declaring environment: CI declares php + the vendor
# path via NOS_TEST_PROVIDES, so there the contract aborts the session instead.
needs_php_and_vendor = pytest.mark.skipif(
    shutil.which("php") is None or not (WING / "vendor/autoload.php").is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)


# ── revision: the attempt travels with the critique ─────────────────────────
# 2026-08-27, surveyor on MiniMax: each needs_revision iteration restarted from
# prompt + feedback alone, re-explored from zero and hit the call cap three times
# (261,767 in / 7,414 out, max_iterations_reached).

#: The critique's heading in the revision message ("GRADER FEEDBACK" until 2026-08-29).
CRITIQUE_HEADING = "WHY IT IS NOT DONE"


def _revision_block() -> str:
    src = RUNNER.read_text(encoding="utf-8")
    i = src.index(CRITIQUE_HEADING)
    return src[src.rindex("$conversation[] =", 0, i): src.index(");", i) + 2]


def test_the_attempt_travels_with_the_critique():
    block = _revision_block()
    assert "$finalText" in block, (
        "the revision message does not carry the previous attempt — the agent "
        "is asked to revise something it cannot see"
    )


def test_an_empty_attempt_is_named_rather_than_omitted():
    """Silence is the case that broke: no text and no mention of it reads as
    'nothing happened' rather than 'you never wrote the deliverable'."""
    block = _revision_block()
    assert re.search(r"\$finalText\s*!==\s*''", block), (
        "no branch for an empty previous attempt; the agent is handed a blank "
        "and learns nothing from it"
    )


# ── fallback: the record says who answered ──────────────────────────────────
# 2026-08-13: model_uri was written at session OPEN from the primary, and both
# callWithRetry fallback paths answered silently — permanent misattribution in a
# hash-chained events table. Ruling 2 (fail-closed) requires the unmatched message logged.

def _runner_src() -> str:
    return RUNNER.read_text(encoding="utf-8")


def _method_until_next(src: str, signature: str) -> str:
    """The body of one method, from its signature to the next one."""
    start = src.index(signature)
    nxt = src.find("\n\tprivate function ", start + len(signature))
    alt = src.find("\n\tpublic function ", start + len(signature))
    end = min(x for x in (nxt, alt, len(src)) if x > 0)
    return src[start:end]


def test_both_fallback_paths_go_through_one_place():
    """Two call sites drifting apart is how one of them lost its event."""
    src = _runner_src()
    body = _method_until_next(src, "private function callWithRetry(")
    assert body.count("serveFallback(") == 2, (
        "callWithRetry no longer routes BOTH fallback paths (unrecognised "
        "error, exhausted retries) through serveFallback — found "
        f"{body.count('serveFallback(')}. A path that builds its own fallback "
        "client answers without recording that it did."
    )
    assert "fromUri($agent->modelFallbackUri)" not in body, (
        "callWithRetry builds a fallback client directly again, bypassing the "
        "one place that records the substitution."
    )


def test_the_fallback_records_who_actually_answered():
    src = _runner_src()
    body = _method_until_next(src, "private function serveFallback(")
    assert re.search(r"\$this->servedByUri\s*=\s*\$fallback->identifier\(\)", body), (
        "serveFallback no longer records the identifier of the client that "
        "answered. Without it the session keeps the primary's name, which is "
        "written at open before anything has answered at all."
    )


def test_the_unmatched_message_is_emitted_verbatim():
    """Ruling 2's condition: fail closed, but say what you could not classify."""
    src = _runner_src()
    body = _method_until_next(src, "private function serveFallback(")
    assert "agent_model_fallback" in body, (
        "the fallback no longer emits an event. Engagement becomes invisible "
        "again — the state ruling 2 accepted fail-closed classification to "
        "escape."
    )
    assert "unmatched_message" in body and "getMessage()" in body, (
        "the event no longer carries the unclassified error message. That "
        "string is the only evidence from which a real rule for a foreign "
        "backend's phrasing could ever be written."
    )


def test_the_session_attribution_is_corrected_at_the_end():
    src = _runner_src()
    assert re.search(
        r"servedByUri\s*!==\s*null\s*\?\s*\['model_uri'\s*=>\s*\$this->servedByUri\]",
        src,
    ), (
        "endSession no longer patches `model_uri` with the client that served. "
        "The value written at session open is the primary's, chosen before any "
        "call was made, and the events it feeds are hash-chained — so leaving "
        "it is a permanent misattribution, not a stale field."
    )


def test_the_ordinary_session_is_left_alone():
    """A primary-served run must not be patched, or `null` becomes a claim."""
    src = _runner_src()
    assert "private ?string $servedByUri = null;" in src, (
        "the served-by marker is no longer nullable-by-default; a run the "
        "primary served must stay distinguishable from one where a fallback "
        "served unnoticed."
    )
    run_body = _method_until_next(src, "public function run(")
    assert "$this->servedByUri = null;" in run_body, (
        "run() no longer resets the marker. A second sequential session in the "
        "same process would inherit the first one's fallback attribution."
    )


# ── grader retry: name the actual fault, never re-open content ──────────────
# 2026-08-27: a well-formed reply with one word outside the enum was told "not
# strict JSON" three times → outcome_failed on a report that existed. Q9 (08-29):
# parser, ONE format-only re-ask, UNPARSEABLE; a bad enum is never re-asked.

GRADER = APP / "AgentKit/Outcome/Grader.php"


def _grader_src() -> str:
    return GRADER.read_text(encoding="utf-8")


def test_shape_faults_go_through_the_three_stage_contract():
    src = _grader_src()
    assert "OutputRepair::parse" in src, (
        "the grader parses model JSON on its own again — the deterministic "
        "shape repair and the single bounded re-ask are bypassed"
    )
    assert "$this->llm->send" in src


def test_there_is_exactly_one_reask_and_it_reformats_only():
    """Two calls in the whole method: the grade, and at most one reformat.

    A loop here is what let a format correction quietly become a re-grade.
    """
    src = _grader_src()
    assert src.count("$this->llm->send") == 2, (
        "the grader makes more than one possible retry call — the format "
        "re-ask is bounded to ONE by the Q9 contract"
    )
    reask = src[src.index("OutputRepair::parse"):src.index("$repaired =")]
    assert "You do not evaluate" in reask, (
        "the re-ask does not forbid evaluation, so the reformat is free to "
        "reconsider the verdict while it is in there"
    )
    assert "SAME" in reask, "the re-ask does not quote the original content back"


def test_a_bad_enum_value_is_not_treated_as_a_shape_fault():
    src = _grader_src()
    branch = src[src.index("in_array($result, [self::RESULT_SATISFIED"):]
    branch = branch[: branch.index("return [") + 400]
    assert "OutputRepair" not in branch and "llm->send" not in branch, (
        "a value outside the enum triggers another model call. It is a "
        "CONTENT fault: the answer is well-formed and wrong, and re-asking "
        "invites a different verdict rather than the same one reformatted."
    )


def test_a_bad_enum_does_not_discard_the_critique():
    """The 2026-08-27 defect itself: one word outside the enum threw away a
    whole correct critique."""
    src = _grader_src()
    branch = src[src.index("in_array($result, [self::RESULT_SATISFIED"):]
    branch = branch[: branch.index("];", branch.index("return ["))]
    assert "$decoded['feedback']" in branch, (
        "the bad-enum branch returns no feedback from the grader's own reply — "
        "the critique it got right is dropped for the word it got wrong"
    )


def test_the_permitted_values_are_named_where_the_grader_can_see_them():
    src = _grader_src()
    system = src[src.index("SYSTEM_TEMPLATE = "):src.index("public function __construct")]
    for value in ("satisfied", "needs_revision", "failed"):
        assert value in system, (
            f"the system prompt never names '{value}', so a grader that guessed "
            "a synonym has nothing to correct itself against"
        )


# ── grader sees the work ────────────────────────────────────────────────────
# 2026-08-04 audit: runToolUseLoop took $conversation BY VALUE and never returned
# it, so the grader got the bare prompt; and `new Grader($llm)` let the proposer
# grade itself. Closed 08-29: satisfaction is the gate set; self-grading refused.

AGENT = APP / "AgentKit/Agent.php"
SCHEMA = REPO / "state/schema/agent.schema.yaml"


@pytest.fixture(scope="module")
def runner_src() -> str:
    assert RUNNER.is_file(), f"{RUNNER} is missing"
    return RUNNER.read_text(encoding="utf-8")


def _body(src: str, marker: str) -> str:
    """Source from a marker to the end — good enough to scope an assertion."""
    idx = src.index(marker)
    return src[idx:]


def test_the_tool_use_loop_returns_the_conversation(runner_src):
    """Without this the work is unreachable by anything downstream."""
    body = _body(runner_src, "private function runToolUseLoop")
    ret = body[body.index("return ["):body.index("return [") + 600]
    assert "'conversation'" in ret, (
        "runToolUseLoop no longer returns the conversation it built. Its "
        "`$conversation` parameter is BY VALUE, so if the array is not "
        "returned the agent's assistant and tool messages are discarded when "
        "the method exits — and the grader downstream sees only the prompt."
    )


def test_the_grader_transcript_is_built_from_the_loop_output(runner_src):
    """The defect itself, as the thing that must stay false."""
    m = re.search(r"\$transcript\s*=\s*\$this->summariseConversation\(([^;]+)\);",
                  runner_src)
    assert m, "the grader transcript is no longer built by summariseConversation"
    arg = m.group(1)
    assert "loopOut" in arg or "loop[" in arg, (
        f"the grader transcript is built from {arg.strip()!r}. That is the "
        f"OUTER conversation, which never receives the tool-use loop's inner "
        f"messages — on iteration 0 it is just the initial prompt. Build it "
        f"from what runToolUseLoop returned."
    )


def test_the_grader_client_is_never_the_agents_own(runner_src):
    """Judge and proposer must not share an identity — at all, since 2026-08-29.
    Behaviour is pinned by test_satisfaction_is_written_by_a_gate_run.py; this
    stays a source assertion that Runner has no second construction path."""
    assert "new Grader(" not in runner_src, (
        "Runner constructs a Grader directly again — that is the path the "
        "`$llm` fallback lived on. Use Grader::forUri, which returns null on "
        "the absent path instead of handing over the proposer's own client."
    )
    assert "Grader::forUri" in runner_src, "Runner no longer resolves a grader at all"


def test_a_separate_grader_model_can_actually_be_declared(runner_src):
    """The split is useless if nothing can request it."""
    assert "modelGraderUri" in AGENT.read_text(encoding="utf-8"), (
        "Agent has no modelGraderUri field, so no agent can ask for a separate "
        "grader and the split in Runner can never take effect"
    )
    assert "modelGraderUri" in runner_src, (
        "Runner never reads the agent's grader model"
    )
    schema = SCHEMA.read_text(encoding="utf-8")
    assert re.search(r"^\s+grader:\s*$", schema, re.MULTILINE), (
        "state/schema/agent.schema.yaml does not allow model.grader — the "
        "schema sets additionalProperties: false, so an agent.yml declaring it "
        "would be REJECTED at load time and the field is unreachable"
    )


# ── latestVerdicts: pick the latest run, then ask if it failed ──────────────
# 2026-09-02: `exit_code != 0` sat in the WHERE, before the latest-run selection,
# so a tie on fired_at reported a job failing whose latest run succeeded. The SQL
# is lifted from PulseRepository.php and run against synthetic ties in sqlite.

PULSE_REPO = APP / "Model/PulseRepository.php"
needs_window_functions = pytest.mark.skipif(
    sqlite3.sqlite_version_info < (3, 25),
    reason=f"no window functions in sqlite {sqlite3.sqlite_version}",
)


def _sql() -> str:
    src = PULSE_REPO.read_text(encoding="utf-8")
    body = re.search(r"public function latestVerdicts\(\).*?\n\t\}", src, re.S)
    assert body, "latestVerdicts is gone from PulseRepository"
    q = re.search(r"query\(\s*'(.*?)',", body.group(0), re.S)
    assert q, "latestVerdicts no longer issues a literal query"
    return q.group(1)


def _rows(sql: str, runs: list[tuple], removed: dict[str, str | None] | None = None) -> set[str]:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE pulse_runs "
                 "(run_id TEXT, job_id TEXT, fired_at TEXT, exit_code INT)")
    conn.execute("CREATE TABLE pulse_jobs (id TEXT, removed_at TEXT)")
    conn.executemany("INSERT INTO pulse_runs VALUES (?,?,?,?)", runs)
    jobs = {r[1]: None for r in runs} | (removed or {})
    conn.executemany("INSERT INTO pulse_jobs VALUES (?,?)",
                     [(j, at) for j, at in jobs.items() if at != "deleted"])
    try:
        return {r[0] for r in conn.execute(sql)}
    finally:
        conn.close()


@needs_window_functions
def test_a_tie_resolves_to_the_later_run():
    """Two runs at the same fired_at: the later one succeeded, so the job is green."""
    rows = [("r1", "nightly", "2026-09-02T03:00:00+02:00", 1),
            ("r2", "nightly", "2026-09-02T03:00:00+02:00", 0)]
    assert _rows(_sql(), rows) == set(), (
        "a job whose latest run succeeded is reported as failing. The exit_code "
        "test runs before the latest-run selection, so the tie-break ranges "
        "over the failures it already filtered down to")


@needs_window_functions
def test_a_genuinely_failing_job_is_still_reported():
    """The population guard — a query returning nothing would pass the test
    above for the wrong reason."""
    rows = [("r1", "nightly", "2026-09-01T03:00:00+02:00", 0),
            ("r2", "nightly", "2026-09-02T03:00:00+02:00", 2)]
    assert _rows(_sql(), rows) == {"nightly"}, (
        "the query reports no failure for a job whose latest run exited 2")


@needs_window_functions
def test_an_unfinished_latest_run_is_not_a_failure():
    """exit_code NULL means still running. Counting it red would light the tile
    for every job mid-flight."""
    rows = [("r1", "nightly", "2026-09-01T03:00:00+02:00", 1),
            ("r2", "nightly", "2026-09-02T03:00:00+02:00", None)]
    assert _rows(_sql(), rows) == set(), (
        "a job whose latest run has not finished is reported as failing")


@needs_window_functions
def test_a_retired_job_is_history_not_state():
    """ares-verify was retired 2026-10-02 and stayed red after it left pulse_jobs.
    A job that no longer exists, or is marked removed, cannot be failing now."""
    rows = [("r1", "gone", "2026-10-02T23:00:00+02:00", 127),
            ("r2", "marked", "2026-10-02T23:00:00+02:00", 127),
            ("r3", "live", "2026-10-02T23:00:00+02:00", 1)]
    assert _rows(_sql(), rows, {"gone": "deleted", "marked": "2026-10-02"}) == {"live"}


# ── a bound agent can file its report ───────────────────────────────────────
# The bound loop ran on MiniMax, yet every ceremony failed: the Wing MCP tool sent
# a bearer only, so POST /api/v1/events answered 401 (checkHmac). Runs the real
# tool against a Guzzle mock and verifies the HMAC over the bytes actually sent.

HMAC_PROBE_404 = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\McpWingReadTool;
use App\AgentKit\Tools\ToolContext;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Psr7\Response;

$stack = HandlerStack::create(new MockHandler([new Response(404, [], '<html>not found</html>')]));
$tool = new McpWingReadTool(new Client(['handler' => $stack]), 'probe-token');
$ctx = new ToolContext('s-1', 'th-1', 't-1', 'sp-1', 'probe', 'tu-1');
$r = $tool->execute(['method' => 'GET', 'path' => '/api/v1/systems'], $ctx);
echo json_encode(['content' => $r->content]);
"""

HMAC_PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\McpWingWriteTool;
use App\AgentKit\Tools\ToolContext;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use GuzzleHttp\Psr7\Response;

putenv('WING_EVENTS_HMAC_SECRET=probe-secret');

$sent = [];
$stack = HandlerStack::create(new MockHandler([new Response(201, [], '{"ok":true}')]));
$stack->push(Middleware::history($sent));
$tool = new McpWingWriteTool(new Client(['handler' => $stack]), 'probe-token');

$ctx = new ToolContext('s-1', 'th-1', 't-1', 'sp-1', 'probe', 'tu-1');
$tool->execute([
    'method' => 'POST',
    'path' => '/api/v1/events',
    'body' => ['ts' => '2026-08-28T00:00:00Z', 'type' => 'agent_message', 'run_id' => 'r-1'],
], $ctx);

$req = $sent[0]['request'];
echo json_encode([
    'raw' => (string) $req->getBody(),
    'ts' => $req->getHeaderLine('X-Wing-Timestamp'),
    'sig' => $req->getHeaderLine('X-Wing-Signature'),
]);
"""


def _run_wing_probe(src: str, name: str) -> dict:
    probe = WING / name
    probe.write_text("<?php\n" + src, encoding="utf-8")
    try:
        out = subprocess.run(["php", probe.name], cwd=WING,
                             capture_output=True, text=True, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_php_and_vendor
def test_post_is_hmac_signed_over_the_bytes_sent() -> None:
    probe = WING / "hmac-probe.php"
    probe.write_text("<?php\n" + HMAC_PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", probe.name], cwd=WING, capture_output=True, text=True, timeout=60
        )
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)

    assert got["ts"].isdigit(), "no HMAC timestamp on the request"
    expected = hmac.new(
        b"probe-secret", f"{got['ts']}.{got['raw']}".encode(), hashlib.sha256
    ).hexdigest()
    assert got["sig"] == expected, "signature does not verify over the raw body sent"


@needs_php_and_vendor
def test_a_404_answers_with_the_routes_that_exist() -> None:
    """The surveyor invented /api/v1/systems and /api/v1/health from this tool's
    prose, got two 404s and gave up (2026-08-28, session 505e0f11). A 404 now
    answers with the live route table, read from the router the request missed."""
    content = _run_wing_probe(HMAC_PROBE_404, "hmac-probe-404.php")["content"]
    assert "not routed" in content, "a 404 no longer tells the model what exists"
    for route in ("/api/v1/events", "/api/v1/pulse_jobs", "/api/v1/hub/health"):
        assert route in content, f"the route hint omits {route}"
    assert "unreadable" not in content, "the tool could not find the router"
    assert "/api/v1/systems\n" not in content


# ── a bound session binds every client ──────────────────────────────────────
# 2026-08-15: grader and fallback were built UNBOUND inside a bound session, safe
# only by what agent files declare (no model.grader; unbindable fallbacks). These
# tripwires pin those premises; since 10-01 a bound session refuses a bindable fallback.

AGENTS = REPO / "files/anatomy/agents"


def _agent_models() -> dict[str, dict]:
    out = {}
    for entry in sorted(AGENTS.iterdir()):
        manifest = entry / "agent.yml"
        if entry.is_dir() and manifest.is_file():
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            out[doc.get("name", entry.name)] = doc.get("model") or {}
    return out


def test_the_sweep_sees_the_agents():
    """Positive control — an empty sweep would make both checks below vacuous."""
    models = _agent_models()
    assert len(models) >= 7, (
        f"only {len(models)} agent definition(s) found (seven exist since the "
        "2026-08-26 roster close); the premises of this "
        "gate are what those files declare, so a short sweep proves nothing."
    )


def test_no_agent_declares_a_grader_while_the_grader_is_built_unbound():
    """`model.grader` is legitimate — this is a tripwire, not a ban: the first
    agent to declare one must decide whether a bound judge may change backend."""
    offenders = {n: m["grader"] for n, m in _agent_models().items() if m.get("grader")}
    assert not offenders, (
        f"agent(s) declare model.grader: {offenders}. Runner builds the grader "
        "client without the session's binding (Runner.php:605), so on a bound "
        "run the judge would be served by the DEFAULT backend while the work "
        "was served by the bound one — one session, two parties, no error. "
        "Bind it, or refuse it, before declaring one."
    )


def test_every_fallback_is_a_provider_that_refuses_binding_anyway():
    """An UNBOUND fallback (no fallback_backend) is safe only while it names a
    provider a binding could not have reached. Since 2026-10-01 every fallback
    is bound, so this holds vacuously — and bites the first unbound one."""
    bindable = ("anthropic-", "claude-", "openai-", "openclaw-")
    offenders = {
        n: m["fallback"]
        for n, m in _agent_models().items()
        if m.get("fallback") and not m.get("fallback_backend")
        and str(m["fallback"]).startswith(bindable)
    }
    assert not offenders, (
        f"agent(s) declare a bindable fallback: {offenders}. `serveFallback` "
        "builds it with no binding, so a bound agent would fall back to the "
        "default backend — answering from a party its own Article-30 record "
        "does not name, and recorded under this session's attribution."
    )


def test_the_call_sites_this_gate_describes_still_look_like_this():
    """If Runner starts passing bindings to all three, this gate's premise is
    gone and it should be RETIRED, not left passing for the wrong reason."""
    src = RUNNER.read_text(encoding="utf-8")
    calls = re.findall(r"fromUri\(([^)]*)\)", src)
    assert len(calls) >= 3, (
        f"expected at least 3 fromUri call sites in Runner, found {len(calls)}; "
        "the shape this gate reasons about has changed."
    )
    bound = [c for c in calls if "binding" in c.lower()]
    assert len(bound) == 2, (
        f"{len(bound)} of {len(calls)} fromUri call sites now pass a binding "
        "(primary + the declared fallback_backend since 2026-10-01; the grader "
        "is still unbound). If the grader is bound now, retire its tripwire; "
        "if FEWER are bound, the fallback can answer unbound again."
    )


def test_a_bound_session_refuses_a_bindable_fallback():
    """Residency a failure can silently revoke is a claim, not a property: a bound
    session REFUSES a bindable fallback rather than degrade to the default backend."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "$this->activeBinding = $decision->binding;" in src, (
        "the session no longer records which binding serves it, so the "
        "fallback cannot be held to it."
    )
    body = src[src.index("private function fallbackClient("):]
    body = body[: body.index("\n\tprivate function ", 1)]
    assert "$this->activeBinding !== null" in body, (
        "fallbackClient no longer checks whether the session is bound; a bound "
        "agent can silently fall back to the default backend again."
    )
    assert "isBindableUri" in body, (
        "the refusal no longer distinguishes a bindable fallback from an "
        "unbindable one — refusing an openclaw fallback would turn every "
        "transient blip into an outage."
    )


# ── an unrunnable judge is not failed work ──────────────────────────────────
# Absence is UNKNOWN, never a verdict: the first bound ceremony (ea044f04,
# 2026-08-29) ended outcome_needs_revision on an environment defect. GateOracle::outcome
# runs here through the real class; Runner must consume it, not recompute.

ORACLE_PROBE = """<?php
require %(autoload)r;
use App\\AgentKit\\Outcome\\GateOracle;

function oracle(array $script): GateOracle {
    $i = 0;
    return new GateOracle('/nonexistent', function (array $argv) use ($script, &$i) {
        [$exit, $result] = $script[$i++];
        return ['exit' => $exit, 'stdout' => json_encode(['state' => 'done', 'verdict' => [
            'uuid' => 'v-' . $i, 'result' => $result, 'gate_set' => 'live',
            'tree_sha' => str_repeat('a', 40), 'evidence' => '{}',
        ]]), 'stderr' => ''];
    });
}

// Environment cannot judge: every verdict INDETERMINATE (score 0).
$env = oracle([[1, 'indeterminate'], [1, 'indeterminate']]);
$env->judge(0, 'live');
$env->judge(1, 'live');

// Real red: the work genuinely failed its gates.
$red = oracle([[1, 'fail'], [1, 'fail']]);
$red->judge(0, 'live');
$red->judge(1, 'live');

// Nothing judged at all (loop threw before the first verdict).
$blank = oracle([]);

echo json_encode([
    'env_peak'      => ['stopped' => $env->outcome(true), 'budget' => $env->outcome(false)],
    'red_peak'      => $red->outcome(true),
    'red_budget'    => $red->outcome(false),
    'blank'         => $blank->outcome(false),
]);
"""


@pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_indeterminate_environment_is_not_needs_revision(tmp_path):
    probe = tmp_path / "probe.php"
    probe.write_text(ORACLE_PROBE % {"autoload": str(AUTOLOAD)})
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    got = json.loads(r.stdout)
    assert got["env_peak"] == {"stopped": "indeterminate", "budget": "indeterminate"}, (
        "an environment that could not judge was reported as failed work"
    )
    assert got["blank"] == "indeterminate"
    assert got["red_peak"] == "needs_revision"
    assert got["red_budget"] == "max_iterations_reached"


@pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_the_runner_consumes_the_oracles_outcome():
    runner = (WING / "app" / "AgentKit" / "Runner.php").read_text()
    assert "$oracle->outcome(" in runner, (
        "Runner recomputes its own outcome word instead of asking the oracle "
        "— the indeterminate/needs_revision distinction is lost at the seam"
    )


# ── a session can be stopped ────────────────────────────────────────────────
# Roadmap iris-subagent-stop: Iris could start and read a run but not end it.
# POST /api/v1/agent-sessions/<uuid>/cancel marks the row; the Runner reads it before
# every model call. Real Api presenter over SQLite + the real tool-use loop over stubs.

THAL = "thalamus:e1e1e1e1-0000-4000-8000-000000000001"     # the Iris session that started T1
OTHER = "thalamus:e2e2e2e2-0000-4000-8000-000000000002"    # another Iris session
T1 = "d1d1d1d1-0000-4000-8000-000000000001"   # alice's run, started by Iris (THAL)
T2 = "d2d2d2d2-0000-4000-8000-000000000002"   # alice's run, started by Iris (THAL)
B2 = "b2b2b2b2-0000-4000-8000-000000000002"   # bob's run, started by Iris (THAL)
A1 = "a1a1a1a1-0000-4000-8000-000000000001"   # alice's run, started from the face, not by Iris
ABSENT = "ffffffff-0000-4000-8000-00000000000f"

_TOKENS = "foreach (['bff-secret' => 'face-bff', 'ops-secret' => 'ansible-provisioned'] as $t => $n) {"
_SEED = [
    [T1, "helper", "user:alice", THAL],
    [T2, "helper", "user:alice", THAL],
    [B2, "helper", "user:bob", THAL],
    [A1, "helper", "user:alice", None],
]


def _harness() -> str:
    assert _HARNESS.count(_TOKENS) == 1, "the borrowed harness moved"
    return _HARNESS.replace(_TOKENS, "$pdo->query('INSERT INTO api_tokens', ['token' => hash('sha256', 'thal'), "
                                     "'name' => 'thalamus', 'scopes' => 'wing.write']);\n" + _TOKENS)


def _run_cancel_cases(tmp_path: pathlib.Path, cases: list[dict]) -> list[dict]:
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", "-r", _harness(), str(AUTOLOAD),
                        str(_agents(tmp_path)), json.dumps(cases), "/usr/bin/true", json.dumps(_SEED)],
                       capture_output=True, text=True, timeout=60, check=False, cwd=WING)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def _thal(uid="alice", groups="nos-users") -> dict:
    return {"token": "thal", "uid": uid, "groups": groups}


def _cancel(uuid: str, parent: str | None = THAL, **who) -> dict:
    return {"presenter": "AgentSessions", "method": "POST", "params": {"action": "cancel", "uuid": uuid},
            "body": {} if parent is None else {"parent": parent}, **who}


def _get(uuid: str) -> dict:
    return {"presenter": "AgentSessions", "method": "GET", "params": {"action": "default", "uuid": uuid},
            "token": "bff-secret", "uid": "alice", "groups": "nos-users"}


@needs_php
@needs_vendor
def test_the_thalamus_stops_a_run_it_started_and_the_row_says_who(tmp_path):
    stopped, read, again = _run_cancel_cases(tmp_path, [_cancel(T1, **_thal()), _get(T1), _cancel(T1, **_thal())])
    assert stopped["code"] == 202, stopped
    row = read["body"]["session"]
    assert (row["status"], row["stop_reason"]) == ("cancelled", "cancelled by user:alice"), row
    assert again["code"] == 409, "a session that is not running is not stopped twice"


@needs_php
@needs_vendor
def test_what_the_thalamus_did_not_start_answers_like_absent(tmp_path):
    """Another person's run, a run of the person's not started by Iris, a run another Iris
    session started, and no run at all answer the same 404: absent and not-yours alike."""
    theirs, faced, other_iris, absent, unnamed = _run_cancel_cases(tmp_path, [
        _cancel(B2, **_thal()),
        _cancel(A1, **_thal()),
        _cancel(T2, OTHER, **_thal()),
        _cancel(ABSENT, **_thal()),
        _cancel(T2, None, **_thal()),
    ])
    for got in (theirs, faced, other_iris, unnamed):
        assert (got["code"], got["body"]) == (absent["code"], absent["body"]), got
    assert absent["code"] == 404


@needs_php
@needs_vendor
def test_an_agent_token_stops_nothing(tmp_path):
    """No person behind the bearer: stopping someone's run is an operator decision."""
    ops, = _run_cancel_cases(tmp_path, [_cancel(T2, token="ops-secret")])
    assert ops["code"] == 403, ops


@needs_php
@needs_vendor
def test_the_face_bff_stops_only_ones_own(tmp_path):
    """Operator 2026-11-08 (wing-inc2): the face-bff bearer reaches cancel, but Wing narrows it to
    the person's own run; another's answers 404 like an absent one and stays running."""
    other, read, own = _run_cancel_cases(tmp_path, [
        _cancel(A1, None, token="bff-secret", uid="bob", groups="nos-users"),
        _get(A1),
        _cancel(A1, None, token="bff-secret", uid="alice", groups="nos-users"),
    ])
    assert other["code"] == 404, other
    assert read["body"]["session"]["status"] == "running", read
    assert own["code"] == 202, own


_LOOP = r"""<?php
namespace App\Model { final class EventRepository { public function insert(array $p): int { return 1; } }
  final class AgentSessionRepository { public array $rows = [];
    public function findByUuid(string $u): ?array { return $this->rows[$u] ?? null; } } }
namespace {
use App\AgentKit\LLMClient\{LLMClientInterface, LLMResponse};
spl_autoload_register(function ($c) { $f = WING . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
    if (str_starts_with($c, 'App\\') && is_file($f)) require $f; });
$store = new App\Model\AgentSessionRepository();
$store->rows['s'] = ['status' => 'running', 'stop_reason' => null];
final class Stub implements LLMClientInterface {
    public int $calls = 0;
    public function __construct(private App\Model\AgentSessionRepository $store, private int $stopAt) {}
    public function identifier(): string { return 'stub'; }
    public function send(string $s, array $m, array $t = [], int $x = 4096): LLMResponse {
        if (++$this->calls === $this->stopAt) {
            $this->store->rows['s'] = ['status' => 'cancelled', 'stop_reason' => 'cancelled by user:alice'];
        }
        return new LLMResponse('tool_use', [['type' => 'tool_use', 'id' => 't' . $this->calls, 'name' => 'look', 'input' => []]], 1, 1);
    }
}
$agent = new App\AgentKit\Agent(name: 'x', version: 1, description: '', modelPrimaryUri: 'stub',
    modelFallbackUri: null, modelGraderUri: null, systemPrompt: 'SYS', tools: [], rubric: null,
    maxIterations: 1, capabilityScopes: [], piiClassification: 'none', requiredCredentials: [],
    subscriptions: [], metadata: [], sourceDir: '');
$llm = new Stub($store, 2);
$r = (new ReflectionClass(App\AgentKit\Runner::class))->newInstanceWithoutConstructor();
(function () use ($store) {
    $this->audit = new App\AgentKit\Telemetry\AuditEmitter(new App\Model\EventRepository());
    $this->sessions = $store;
    $this->sessionUuid = 's';
    $this->sessionDeadline = microtime(true) + 600;
    $this->fallbackContext = ['session_uuid' => 's', 'primary' => 'stub'];
})->call($r);
$out = ['calls' => null, 'threw' => null];
try {
    (function () use ($agent, $llm) { $spans = [];
        $this->runToolUseLoop($agent, $llm, [], [App\AgentKit\LLMClient\Message::userText('go')], 's', 'th', str_repeat('0', 32), str_repeat('0', 16), 'x', $spans);
    })->call($r);
} catch (Throwable $e) { $out['threw'] = get_class($e); $out['why'] = $e->getMessage(); }
$out['calls'] = $llm->calls;
$closing = fn () => method_exists($this, 'closing') ? $this->closing('s', 'idle', 'end_turn') : null;
$out['closing'] = $closing->call($r);
$store->rows['s'] = ['status' => 'running', 'stop_reason' => null];
$out['open'] = $closing->call($r);
echo json_encode($out);
}
"""


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed on this runner")
def test_the_loop_ends_at_the_next_call_after_the_stop(tmp_path):
    """The row turns cancelled during call 2: call 3 is never made, and the session
    closes with the stop's own status and reason instead of the loop's."""
    script = tmp_path / "loop.php"
    script.write_text(_LOOP.replace("WING", repr(str(WING))), encoding="utf-8")
    r = subprocess.run(["php", "-d", "display_errors=stderr", str(script)], capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads(r.stdout)
    assert got["calls"] == 2, f"the loop went on after the stop: {got}"
    assert got["threw"] == "App\\AgentKit\\SessionCancelled", got
    assert got["closing"] == ["cancelled", "cancelled by user:alice"], got
    assert got["open"] == ["idle", "end_turn"], "a session nobody stopped closes as the loop says"


# ── a dead session is closed by a successor ─────────────────────────────────
# terminateStale() (06-10) ran only on the /agents page; once red-status (a reader
# that may not write) showed orphans, a surveyor sat `running` 110 hours. Both
# session-opening paths now reap BEFORE inserting; the page-view reap still reports.

REPOSITORY = APP / "Model/AgentSessionRepository.php"
PRESENTER = APP / "Presenters/AgentsPresenter.php"


def repo_src() -> str:
    return REPOSITORY.read_text(encoding="utf-8")


def _method_braced(src: str, signature: str) -> str:
    """Body of a PHP method, by brace matching from its signature."""
    start = src.index(signature)
    brace = src.index("{", start)
    depth, i = 0, brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces after {signature!r}")


def test_the_reaper_still_exists():
    assert "public function terminateStale(" in repo_src(), (
        "terminateStale() is gone; five orphans were hand-cleaned the day it "
        "was written, and one sat for 110 hours the day it gained callers")


def test_both_session_creating_paths_reap_before_inserting():
    src = repo_src()
    for signature in ("public function startSession(", "public function syncFromAgentEvent("):
        body = _method_braced(src, signature)
        assert "terminateStale(" in body, (
            f"{signature}…) creates a `running` row without reconciling the "
            "abandoned ones. The 110-hour orphan arrived on the claude-CLI "
            "path (syncFromAgentEvent); covering only the other runtime would "
            "have missed exactly the case this exists for")
        reap = body.index("terminateStale(")
        insert = body.index("->insert(")
        assert reap < insert, (
            f"{signature}…) reaps AFTER inserting, so the session it just "
            "opened is a candidate for its own reaper the moment the cap is "
            "misconfigured — a run must never close itself")


def test_the_cap_belongs_to_the_reaper_not_to_a_caller():
    src = repo_src()
    assert "SESSION_CAP_MINUTES_DEFAULT" in src and "function staleCapMinutes(" in src, (
        "the cap must live with terminateStale(). It used to be a private "
        "constant on AgentsPresenter, which meant one of several callers "
        "defined the policy for all of them")
    presenter = PRESENTER.read_text(encoding="utf-8")
    assert not re.search(r"private const SESSION_CAP_MINUTES_DEFAULT", presenter), (
        "AgentsPresenter re-declares the cap; two defaults will drift and the "
        "countdown shown to the operator will stop matching the reap")


def test_the_page_view_reaper_survives_and_still_reports():
    presenter = PRESENTER.read_text(encoding="utf-8")
    body = _method_braced(presenter, "public function renderDefault(")
    assert "terminateStale(" in body, (
        "the lazy page-view reap was removed. Keep it: it is a free extra "
        "chance, and it is the ONLY path that tells the operator a reap "
        "happened rather than doing it silently")
    assert "flashMessage" in body, (
        "a reap that says nothing is indistinguishable from no reap at all")
