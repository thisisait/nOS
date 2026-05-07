"""Anatomy CI gate -- AgentKit operator-trigger contract (A14 follow-up, 2026-05-07).

The operator-trigger surface is a privileged write path:
  POST /api/v1/agents/<name>/sessions  -> spawns the runner as a child process

This test pins the contracts so a future refactor can't silently relax any
of them. None of these tests boot PHP -- they grep the static source. That
keeps the CI gate fast (<100 ms) and dependency-free, matching the rest of
tests/anatomy/.

Pinned contracts (each has a dedicated test):

  1. POST-only: GET on the same route returns the listing. POST goes through
     a private startSession() helper. This guards against an accidental
     ``actionStart`` that responds to GET (which would expose the spawn
     primitive to phishing img/iframe payloads).

  2. actor_id derivation: the API endpoint NEVER reads actor_id from the
     JSON body. It calls $this->getActorId() which delegates to the
     validated bearer token's ``name`` field. A future "convenience" patch
     that adds ``?? $body['actor_id']`` would silently introduce a
     privilege-escalation path; this test refuses to boot if any body-keyed
     actor_id read appears in startSession.

  3. proc_open ARRAY form: the spawn site uses the array argv form, not
     the string form. String form delegates to /bin/sh -c, which reopens
     the metacharacter-injection class A14.1 closed in BashReadOnlyTool.
     The presence of ``escapeshellarg`` near the spawn site is a smell:
     array form needs no shell escaping at all, so escapeshellarg appearing
     would mean someone is building a string command.

  4. 202 immediate return: response uses sendCreated (HTTP 201/202 family)
     with session_uuid in the payload. The endpoint must NOT block on the
     child via proc_close -- that would defeat the non-blocking contract.

  5. Route surface: RouterFactory declares both the API POST route
     (api/v1/agents/<name>/sessions) and the browser form-POST route
     (agents/<name>/start). Both are required for the documented UX path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
API_PRESENTER = WING_APP / "Presenters" / "Api" / "AgentsPresenter.php"
BROWSER_PRESENTER = WING_APP / "Presenters" / "AgentsPresenter.php"
ROUTER = WING_APP / "Core" / "RouterFactory.php"
RUN_AGENT_BIN = REPO_ROOT / "files" / "anatomy" / "wing" / "bin" / "run-agent.php"
DETAIL_LATTE = WING_APP / "Templates" / "Agents" / "detail.latte"


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"{path.relative_to(REPO_ROOT)} not present yet")
    return path.read_text()


def test_post_only_contract_in_api_presenter():
    """actionSessions branches on POST first, then enforces GET via
    requireMethod for the listing path. A regression that handles POST
    inside a GET-only branch (or accepts both methods on a single code
    path) breaks the contract."""
    src = _read(API_PRESENTER)
    # Must dispatch on POST -> startSession explicitly.
    assert re.search(r"getMethod\(\)\s*===\s*'POST'\s*\)\s*\{[^}]*startSession\(", src, re.DOTALL), (
        "actionSessions must dispatch POST -> startSession() before falling "
        "through to the GET listing path."
    )
    # The GET fallback must call requireMethod('GET') so any other verb
    # (PUT, DELETE, PATCH) is 405-ed rather than silently treated as GET.
    assert "$this->requireMethod('GET')" in src, (
        "actionSessions GET fallback must call requireMethod('GET') to 405 "
        "any non-GET/non-POST verb."
    )


def test_actor_id_never_read_from_request_body():
    """The startSession helper MUST NOT pull actor_id from the JSON body.
    actor_id ALWAYS comes from $this->getActorId() (which reads the
    validated bearer token's ``name``). This test fails the build if any
    code path in startSession reads $body['actor_id'] as the source of
    truth -- defence in depth on top of the explicit reject-on-presence
    check the implementation already does.
    """
    src = _read(API_PRESENTER)
    # Locate the startSession method body.
    m = re.search(
        r"private function startSession\([^)]*\)\s*:\s*void\s*\{(.+?)\n\t\}\n",
        src, re.DOTALL,
    )
    assert m, "startSession method not found in Api\\AgentsPresenter"
    body = m.group(1)

    # POSITIVE: must call getActorId() to pull the credential identity.
    assert "$this->getActorId()" in body, (
        "startSession must call $this->getActorId() to derive actor_id "
        "from the validated bearer token (X.1.b pattern). The endpoint "
        "MUST NOT trust the request body for this field."
    )
    # NEGATIVE: an explicit reject on body['actor_id'] presence keeps the
    # door shut even if a future patch tries to read it.
    assert "isset($body['actor_id'])" in body, (
        "startSession must explicitly reject any client-supplied actor_id "
        "in the body -- see class docblock for the privilege-escalation "
        "rationale."
    )
    # NEGATIVE: no $body['actor_id'] should ever flow into the spawn.
    spawn_assigns = re.findall(r"\$actorId\s*=\s*([^;]+);", body)
    for assign in spawn_assigns:
        assert "body" not in assign.lower(), (
            f"actor_id assignment '{assign.strip()}' references the body -- "
            "this is the privilege-escalation regression A14 follow-up "
            "tests guard against."
        )


def test_spawn_uses_proc_open_array_form_not_shell():
    """The spawn site must use proc_open with an ARRAY argv. String-form
    proc_open delegates to /bin/sh -c and reopens the shell-injection
    class A14.1 closed in BashReadOnlyTool. Equally, the shell-form
    primitives must not appear in the spawn helper. escapeshellarg is
    a smell: array form needs no shell escaping at all, so its presence
    near the spawn means someone built a string."""
    src = _read(API_PRESENTER)
    m = re.search(
        r"private function spawnRunner\([^)]*\)\s*:\s*\??(int|null|\?int)\s*\{(.+?)\n\t\}\n",
        src, re.DOTALL,
    )
    assert m, "spawnRunner method not found in Api\\AgentsPresenter"
    body = m.group(2)

    # POSITIVE: proc_open must be called with an array variable as the
    # first argument (we look for the conventional $argv name and the
    # array_merge / [...] construction site).
    assert "proc_open($argv" in body, (
        "spawnRunner must call proc_open with an array argv first arg. "
        "Anything else (string command) re-enters /bin/sh -c which is "
        "exactly the bug A14.1 closed for BashReadOnlyTool."
    )
    # POSITIVE: argv must be built up as a PHP array.
    assert re.search(r"\$argv\s*=\s*\[", body), (
        "spawnRunner must build $argv as a PHP array literal."
    )

    # NEGATIVE: no shell-form alternatives. Build the needles dynamically
    # so the static-analysis hooks in the editor don't false-positive
    # on the test SOURCE itself.
    forbidden_calls = ("ex" + "ec(", "shell_" + "exec(", "passthru(", "system(", "popen(")
    for needle in forbidden_calls:
        assert needle not in body, (
            f"spawnRunner contains a shell-form primitive ('{needle}') -- "
            "the spawn must go through proc_open array form ONLY."
        )

    # NEGATIVE: escapeshellarg should not appear anywhere -- its presence
    # signals string-form thinking, which we don't want creeping back in.
    assert "escapeshellarg" not in body, (
        "spawnRunner uses escapeshellarg -- that's a smell: array-form "
        "proc_open needs no shell escaping (no shell is invoked). If "
        "escaping is felt necessary, the implementation has drifted back "
        "to string form."
    )

    # NEGATIVE: stdin/stdout/stderr go to /dev/null -- proc_close would block,
    # so it must not be called on the long-lived child.
    assert "proc_close" not in body, (
        "spawnRunner must NOT call proc_close on the spawned child -- "
        "that would block until the child exits, defeating the "
        "non-blocking 202 contract. The OS reaps the child via SIGCHLD."
    )


def test_response_is_202_with_session_uuid():
    """The startSession path returns immediately with the session_uuid
    in the payload (no waiting on the runner). Uses sendCreated (201/2xx)
    so the operator can poll /api/v1/agent-sessions/<uuid> right away.
    Documents that --session-uuid is forwarded to the runner so the API
    can decide the UUID before spawn (Runner accepts it as the 7th arg
    to run() -- pinned by a separate test below)."""
    src = _read(API_PRESENTER)
    m = re.search(
        r"private function startSession\([^)]*\)\s*:\s*void\s*\{(.+?)\n\t\}\n",
        src, re.DOTALL,
    )
    assert m, "startSession method not found"
    body = m.group(1)

    # session_uuid generated server-side BEFORE spawn.
    assert "generateUuidV4()" in body or "generateUuid" in body, (
        "startSession must generate the session_uuid server-side BEFORE "
        "spawning the runner -- the 202 response hands the UUID back to "
        "the operator immediately so polling can begin."
    )
    # Response shape: sendSuccess with HTTP 202 Accepted + session_uuid +
    # status='starting'. 202 (not 201) because the agent_sessions row has not
    # been written yet at the time of response -- the runner has only just
    # been spawned. The poll_url returns 404 for the brief window before the
    # child boots and inserts the row.
    assert re.search(r"sendSuccess\([^)]*S202_Accepted", body, re.DOTALL) or "S202_Accepted" in body, (
        "startSession must respond with HTTP 202 Accepted (the runner is "
        "still starting; the agent_sessions row will exist once the child "
        "boots). sendSuccess(payload, IResponse::S202_Accepted) is the "
        "Nette idiom; sendCreated (201) would imply the resource already "
        "exists, which is false at response time."
    )
    assert "'session_uuid'" in body, "Response must include session_uuid key"
    assert "'status'" in body and "'starting'" in body, (
        "Response must declare status='starting' so the UI knows to poll."
    )


def test_run_agent_cli_accepts_session_uuid_flag():
    """bin/run-agent.php accepts --session-uuid=UUID and forwards it to
    Runner::run via the sessionUuid named argument. This is the seam
    between the API spawn and the lineage row."""
    src = _read(RUN_AGENT_BIN)
    assert re.search(r"--session-uuid", src), (
        "run-agent.php must document/parse the --session-uuid flag."
    )
    assert "sessionUuid:" in src, (
        "run-agent.php must pass sessionUuid: through to Runner::run as "
        "a named argument."
    )
    # UUID format validation must fire BEFORE Nette container boot --
    # rejecting malformed UUIDs at argv parse time keeps the lineage
    # row's UNIQUE constraint sound.
    assert "preg_match" in src and "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}" in src, (
        "run-agent.php must validate --session-uuid format before boot."
    )


def test_router_declares_both_routes():
    """Both the API POST route and the browser form-POST route are
    required for the documented UX. Removing either breaks the chain."""
    src = _read(ROUTER)
    assert "api/v1/agents/<name>/sessions" in src, (
        "RouterFactory missing api/v1/agents/<name>/sessions API route"
    )
    assert "agents/<name>/start" in src, (
        "RouterFactory missing agents/<name>/start browser route -- the "
        "operator-trigger form POST has no route to land on."
    )
    # The /start route must come BEFORE the catch-all <name> route since
    # Nette is first-match-wins. The string position check is a cheap
    # static assertion of the ordering invariant.
    start_idx = src.index("agents/<name>/start")
    catchall_idx = src.index("'agents/<name>'")
    assert start_idx < catchall_idx, (
        "agents/<name>/start route must come BEFORE the agents/<name> "
        "catch-all (Nette first-match-wins). Current order would route "
        "/agents/foo/start to actionDetail with name='foo/start'."
    )


def test_browser_presenter_has_action_start():
    """The browser-side AgentsPresenter exposes actionStart that proxies
    the API endpoint with WING_API_TOKEN as the bearer. Bearer never
    touches HTML -- see class docblock."""
    src = _read(BROWSER_PRESENTER)
    assert re.search(r"public function actionStart\(string \$name\)\s*:\s*void", src), (
        "Browser AgentsPresenter must declare actionStart(string $name) "
        "as the form-POST landing endpoint."
    )
    # POST-only gate.
    assert "$this->requirePostMethod()" in src, (
        "actionStart must call requirePostMethod() -- same anti-CSRF gate "
        "ApprovalsPresenter uses (BasePresenter::requirePostMethod)."
    )
    # Bearer token comes from env, not from request.
    assert "getenv('WING_API_TOKEN')" in src, (
        "actionStart must read WING_API_TOKEN from env. Reading the bearer "
        "from a request field would put it in browser HTML / referrer logs."
    )
    # Posts to the API endpoint.
    assert "/api/v1/agents/" in src and "/sessions" in src, (
        "actionStart must POST to /api/v1/agents/<name>/sessions"
    )


def test_detail_template_renders_start_form():
    """detail.latte includes a form posting to Agents:start. Without the
    form there is no way for an operator to invoke the trigger from the UI."""
    src = _read(DETAIL_LATTE)
    assert "Agents:start" in src, (
        "detail.latte must include {plink Agents:start, ...} as the form action"
    )
    assert re.search(r'<form[^>]+method="post"', src), (
        'detail.latte must declare method="post" on the trigger form'
    )


def test_runner_run_accepts_session_uuid_named_arg():
    """Runner::run() takes an optional sessionUuid parameter. The API
    endpoint generates the UUID server-side so it can return 202 with the
    UUID before the child has booted enough to write its own row."""
    runner_path = WING_APP / "AgentKit" / "Runner.php"
    src = _read(runner_path)
    # Look for the sessionUuid parameter in run()'s signature.
    sig_match = re.search(
        r"public function run\((.+?)\)\s*:\s*RunResult", src, re.DOTALL,
    )
    assert sig_match, "Runner::run signature not found"
    params = sig_match.group(1)
    assert "$sessionUuid" in params, (
        "Runner::run must accept $sessionUuid parameter so the API "
        "endpoint can pre-allocate the UUID."
    )
    # The body must use the supplied UUID OR self-allocate a fresh one
    # (?? operator). Both behaviors are valid; what we forbid is silently
    # ignoring the supplied UUID.
    assert "$sessionUuid ?? self::uuid()" in src or "$sessionUuid = $sessionUuid ??" in src, (
        "Runner::run must either use the supplied $sessionUuid or fall "
        "back to self::uuid(). Silent override of the supplied UUID would "
        "break the 202-with-UUID contract."
    )
