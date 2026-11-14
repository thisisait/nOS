"""One journey through Wing's API surface: edge (Caddy), auth, presenters, clients, debug.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys); every assert kept verbatim:
  test_the_wing_api_log_holds_no_secret, test_wing_refuses_multipart,
  test_wing_upload_progress_off, test_only_a_gated_presenter_answers_without_a_token,
  test_presenter_static_shadowing, test_systemrepo_mass_assignment,
  test_client_body_suppression, test_wing_speaks_bones_dialect,
  test_preloader_does_not_block_fallback_login, test_wing_tracy_secret_redaction.

CEILING. The two live Caddy checks need a frankenphp binary (PATH or ~/.local/bin);
CI without one runs the rendered-shape half only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
APP = WING / "app"
CADDY = REPO / "roles" / "pazny.wing" / "templates" / "wing.Caddyfile.j2"
ENV = REPO / "roles/pazny.wing/templates/wing.env.j2"
PLIST = REPO / "roles/pazny.wing/templates/wing.plist.j2"
_spec = importlib.util.spec_from_file_location("_metrics", REPO / "tests/anatomy/test_medulla_serves_metrics.py")
_metrics = importlib.util.module_from_spec(_spec)  # its _wait: ready = PHP started, not only the port
_spec.loader.exec_module(_metrics)


# ── shared Caddy harness (api log + multipart) ──────────────────────────────


def _render(tmp: Path) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(CADDY.read_text(encoding="utf-8")).render(
        wing_log_dir=str(tmp), wing_app_dir=str(tmp),
        nos_docker_host_ip="127.0.0.1", wing_edge_token="t", medulla_routes=[], medulla_http_port=8095)


def _frankenphp():
    return shutil.which("frankenphp") or next(
        (p for p in [Path.home() / ".local/bin/frankenphp"] if p.exists()), None)


def _serve(tmp_path: Path, index_php: str):
    """Start the rendered Wing Caddyfile on a free port; return (proc, port) once it listens."""
    (tmp_path / "www").mkdir()
    (tmp_path / "www/index.php").write_text(index_php)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = _render(tmp_path).replace(":9000 {", f":{port} {{", 1)
    (tmp_path / "Caddyfile").write_text(conf.replace("admin off", "admin off\n    persist_config off", 1))
    proc = subprocess.Popen([str(_frankenphp()), "run", "--config", str(tmp_path / "Caddyfile")],
                            cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "XDG_DATA_HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path)})
    _metrics._wait(proc, port, "frankenphp served the rendered Caddyfile", php_log=tmp_path / "access.log")
    return proc, port


# ── test_the_wing_api_log_holds_no_secret ───────────────────────────────────
# 2026-10-28, row wing-to-medulla-waves wave 0: every /api/v1 call is logged for a
# release. Caddy logs every header by default (bearer, cookie, ?token=); the file
# must hold method, path, status, duration and nothing replayable.

SECRET = "FAKE_s3cr3t-must-not-land"


def test_the_api_log_is_bounded_and_drops_headers_and_query():
    site = _render(Path("/x")).split(":9000 {", 1)[1]
    log = re.search(r"^\s*log\s+\S+\s*\{(.*?)^\s{4}\}", site, re.M | re.S)
    assert log, "Wing's site block has no named access log"
    body = log.group(1)
    assert "/x/api-access.log" in body and "roll_size" in body and "roll_keep" in body, \
        "the api log is not its own bounded file under wing_log_dir"
    assert re.search(r"^\s*request>headers\s+delete\s*$", body, re.M), \
        "request headers (Authorization, Cookie) are not deleted from the log"
    assert re.search(r"^\s*request>uri\s+regexp\s+\\\?", body, re.M), "the query string is logged"
    assert re.search(r"^\s*log_skip\s+@\S+", site, re.M), "the log is not limited to /api/v1"


@pytest.mark.skipif(not _frankenphp(), reason="no frankenphp binary")
def test_a_logged_api_call_carries_no_credential(tmp_path):
    proc, port = _serve(tmp_path, '<?php echo "php";')

    def get(path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={
            "Authorization": f"Bearer {SECRET}", "Cookie": f"PHPSESSID={SECRET}"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except urllib.error.HTTPError:
            pass

    log = tmp_path / "api-access.log"
    try:
        get(f"/api/v1/probe?token={SECRET}")
        get("/dashboard")
        for _ in range(50):
            if log.exists() and log.stat().st_size:
                break
            time.sleep(0.1)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    text = log.read_text() if log.exists() else ""
    assert SECRET not in text, "a credential reached the api access log"
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["request"]["uri"] for r in rows] == ["/api/v1/probe"], f"logged: {rows}"
    assert {"status", "duration"} <= rows[0].keys() and rows[0]["request"]["method"] == "GET"


# ── test_wing_refuses_multipart ─────────────────────────────────────────────
# 2026-10-21: PHP's multipart (rfc1867) parser had a reported heap UAF and runs
# pre-auth on every POST to 127.0.0.1:9000 / the docker bridge. Wing reads no
# uploads, so Caddy answers any multipart Content-Type with 415 before PHP.


def test_the_site_refuses_multipart():
    site = _render(Path("/x")).split(":9000 {", 1)[1]
    m = re.search(r"^\s*@(\S+)\s+header_regexp\s+Content-Type\s+\(\?i\)multipart\s*$", site, re.M)
    assert m, "no case-insensitive multipart matcher in Wing's site block"
    assert re.search(rf"^\s*respond\s+@{m.group(1)}\b.*\b4\d\d\b", site, re.M), \
        "the multipart matcher does not answer 4xx"


@pytest.mark.skipif(not _frankenphp(), reason="no frankenphp binary")
def test_a_multipart_post_never_reaches_php(tmp_path):
    proc, port = _serve(tmp_path, '<?php touch(__DIR__."/../hit"); echo "php";')

    def post(ctype, body=b"--x\r\nContent-Disposition: form-data; name=a\r\n\r\n1\r\n--x--\r\n"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=body, headers={"Content-Type": ctype})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code

    try:
        for ctype in ("multipart/form-data; boundary=x", "MULTIPART/Form-Data; boundary=x"):
            assert post(ctype) == 415, ctype
            assert not (tmp_path / "hit").exists(), f"PHP ran for {ctype}"
        assert post("application/json", b"{}") == 200, "a JSON POST no longer reaches PHP"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ── test_wing_upload_progress_off ───────────────────────────────────────────
# 2026-10-21 (spark1): session.upload_progress UAF (CVE-2026-109618/-109619) found
# Wing on stock enabled=1 with no php.ini. Wing never reports upload progress, so
# the frankenphp global block sets it 0. Reads the template, not the live process.


def _frankenphp_block() -> str:
    text = CADDY.read_text(encoding="utf-8")
    m = re.search(r"^\s*frankenphp\s*\{(.*?)^\s*\}", text, re.S | re.M)
    assert m, f"no global frankenphp {{ }} block in {CADDY.name}"
    return m.group(1)


def test_upload_progress_is_off_in_the_frankenphp_block():
    lines = [ln.split("#", 1)[0].split() for ln in _frankenphp_block().splitlines()]
    assert ["php_ini", "session.upload_progress.enabled", "0"] in lines, \
        "Wing's PHP keeps the stock session.upload_progress.enabled = On"


# ── test_only_a_gated_presenter_answers_without_a_token ─────────────────────
# AgentQuestionRepository::answerAsOperator() skips the reply token; safe only behind
# a Tier-1 browser gate (cited before it existed, 2026-08-08). Ruled exceptions: the
# medulla wing.answer relay (Q3 2026-11-01) and the face Inbox Tier-1 branch
# (2026-11-08, run by test_wing_inbox_journey.py). The token path refuses anonymity.

REPOSITORY = APP / "Model/AgentQuestionRepository.php"
API_PRESENTER = APP / "Presenters/Api/InboxPresenter.php"
BASE_API = APP / "Presenters/Api/BaseApiPresenter.php"


def code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def call_sites() -> dict[Path, str]:
    """path -> comment-stripped source, for every file that CALLS
    answerAsOperator (declaration site excluded)."""
    out: dict[Path, str] = {}
    for php in APP.rglob("*.php"):
        if php == REPOSITORY:
            continue
        code = code_only(php.read_text(encoding="utf-8"))
        if re.search(r"->answerAsOperator\s*\(", code):
            out[php] = code
    return out


def _the_ruled_relay(path: Path, code: str) -> bool:
    """Api\\InboxPresenter, the call on the wing.answer branch (and the face-bff Tier-1 branch), the
    first scope confined to $answerActions POSTs and the second to an operator action."""
    if path != API_PRESENTER:
        return False
    call = re.search(r"\$relay(\s*\|\|\s*\$face)?\s*\?\s*\$this->questions->answerAsOperator\(", code)
    branch = re.search(r"\$relay\s*=\s*TokenRepository::grants\([^;]*'wing\.answer'\)\s*;", code) and \
        call and len(re.findall(r"->answerAsOperator\s*\(", code)) == 1
    if call and call.group(1):
        face = re.search(r"\$face\s*=\s*\$this->endUser\s*!==\s*null\s*&&\s*\$this->endUser->operator\s*&&"
                         r"[^;]*===\s*EndUser::TOKEN_NAME\s*;", code)
        operator = re.search(r"protected\s+array\s+\$operatorActions\s*=\s*\[[^\]]*'answer'[^\]]*\]", code)
        branch = branch and face and operator
    base = code_only(BASE_API.read_text(encoding="utf-8"))
    confined = re.search(r"grants\([^;]*'wing\.answer'\)\s*&&\s*!\(\$this->getMethod\(\)\s*===\s*'POST'\s*&&\s*"
                         r"in_array\(strtolower\(\$this->getAction\(\)\),\s*\$this->answerActions,\s*true\)\)\)\s*\{\s*"
                         r"\$this->sendError\([^;]*S403_Forbidden", base)
    return bool(branch and confined)


def test_every_token_less_answer_sits_behind_a_tier_gate():
    sites = call_sites()
    assert sites, (
        "nothing calls answerAsOperator() any more — either the browser "
        "answer path is gone (a regression: /inbox can no longer decide) or "
        "the method was renamed; re-point this gate rather than letting it "
        "pass vacuously."
    )
    offenders = []
    for path, code in sites.items():
        rel = str(path.relative_to(REPO))
        if "/Presenters/Api/" in rel.replace("\\", "/"):
            if _the_ruled_relay(path, code):
                continue
            offenders.append(f"{rel}: API presenters authenticate services, not people")
            continue
        if not re.search(r"\$minAccessTier\s*=\s*1\s*;", code):
            offenders.append(f"{rel}: no `$minAccessTier = 1` declaration")
    assert not offenders, (
        "answerAsOperator() — the path that skips the reply-token check — is "
        "called from an ungated place:\n  " + "\n  ".join(offenders)
        + "\n\nIt is safe ONLY behind an RBAC gate that names a person. "
        "Gate the caller or make it present the token."
    )


def _action_answer_body() -> str:
    code = code_only(API_PRESENTER.read_text(encoding="utf-8"))
    m = re.search(
        r"public function actionAnswer\([^)]*\)\s*:\s*void\s*\{(.*?)\n\t\}",
        code, re.DOTALL,
    )
    assert m, "Api\\InboxPresenter::actionAnswer body not parseable"
    return m.group(1)


def test_the_token_path_refuses_an_anonymous_identity():
    body = _action_answer_body()
    assert re.search(r"\$answeredBy\s*===\s*''", body), (
        "actionAnswer no longer refuses an empty answered_by — an anonymous "
        "approval is an audit dead end; a channel that cannot name the "
        "operator must be refused, not recorded."
    )
    # The old fallback was `$b['answered_by'] ?? $this->getActorId() ?? 'unknown'`;
    # refusing a literal 'unknown' is fine, defaulting to one is not.
    assert "getActorId" not in body and "?? 'unknown'" not in body, (
        "actionAnswer falls back to the bearer token's name (or 'unknown') "
        "when answered_by is missing. A service token is not a person; "
        "\"who approved this\" must name someone or the call must fail."
    )


def test_a_non_person_identity_is_refused_by_shape():
    """`agent:*` and `channel:*` are the two non-person spellings the estate
    already uses for actor_id — an adapter passing its OWN identity as the
    answerer must be caught even when it is not empty."""
    body = _action_answer_body()
    for prefix in ("agent:", "channel:"):
        assert f"'{prefix}'" in body, (
            f"actionAnswer no longer refuses answered_by values shaped "
            f"`{prefix}*`. That spelling names an actor that is not a person "
            f"— recording it as the decider is the audit dead end the plan's "
            f"own trap list named."
        )


# ── test_presenter_static_shadowing ─────────────────────────────────────────
# 2026-05-17 live run: ApprovalsPresenter's `private static function canonicalize()`
# shadowed Nette's non-static parent → class-load fatal that crashed every DI-loading
# bin/ script mid-playbook. Forbids static shadows of Nette parent-method names.

PRESENTERS_DIR = APP / "Presenters"

# Non-static on Nette\Application\UI\Presenter; removing one requires checking upstream.
RESERVED_PARENT_METHODS = {
    "canonicalize", "redirect", "redirectPermanent", "redirectUrl", "terminate",
    "forward", "sendPayload", "sendResponse", "sendTemplate", "sendJson", "startup",
    "beforeRender", "afterRender", "shutdown", "getName", "getAction", "getView",
    "getHttpRequest", "getHttpResponse", "getRequest", "getSession", "getUser",
    "getContext", "getParameter", "isAjax", "link", "lazyLink", "createTemplate",
    "saveGlobalState", "loadState", "saveState",
}


def test_no_static_override_of_nette_parent_method():
    """For every PHP file under app/Presenters/, no `static function
    <NAME>` may appear where <NAME> is a Nette parent method — PHP
    would refuse to load the class."""
    pattern = re.compile(
        r"\b(public|private|protected)\s+static\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    )
    offenders: list[tuple[str, str, int]] = []
    for php in PRESENTERS_DIR.rglob("*.php"):
        text = php.read_text()
        for line_no, line in enumerate(text.splitlines(), 1):
            m = pattern.search(line)
            if not m:
                continue
            name = m.group(2)
            if name in RESERVED_PARENT_METHODS:
                offenders.append(
                    (str(php.relative_to(REPO)), name, line_no),
                )
    assert not offenders, (
        "static function declared with a Nette parent-method name — "
        f"PHP will refuse to load the class. Rename the helper: {offenders}"
    )


# ── test_systemrepo_mass_assignment ─────────────────────────────────────────
# SEC-7 (2026-05-23): HubPresenter left POST /systems public and upsert() passed the
# whole JSON body to insert() — forged registry rows, SSRF-guard bypass, writes to
# health columns. Fix: WRITABLE_FIELDS allowlist + auth bypass for GET only.

SYSTEM_REPO = APP / "Model/SystemRepository.php"
HUB_API = APP / "Presenters/Api/HubPresenter.php"


def test_systemrepo_has_writable_fields_whitelist():
    """WRITABLE_FIELDS enumerates only install-shape columns; health/audit/scan_* excluded."""
    src = SYSTEM_REPO.read_text()
    assert "WRITABLE_FIELDS" in src, "SystemRepository must declare WRITABLE_FIELDS constant"
    m = re.search(r"WRITABLE_FIELDS\s*=\s*\[(.*?)\];", src, re.DOTALL)
    assert m, "WRITABLE_FIELDS array literal not found"
    body = m.group(1)
    for col in ("id", "name", "type", "category", "stack", "domain", "url", "port", "enabled"):
        assert f"'{col}'" in body, f"WRITABLE_FIELDS missing expected column '{col}'"
    for col in ("health_status", "health_http_code", "created_at", "scan_priority"):
        assert f"'{col}'" not in body, (
            f"WRITABLE_FIELDS MUST NOT include '{col}' — owned by setHealth() "
            f"or the DB, not by operator/agent input"
        )


def test_systemrepo_upsert_filters_via_array_intersect():
    """The whitelist must be APPLIED via array_intersect_key, and insert/update use the filtered data."""
    src = SYSTEM_REPO.read_text()
    m = re.search(r"public function upsert\(.*?\)\s*:\s*void\s*\{(.*?)\n\t\}", src, re.DOTALL)
    assert m, "upsert() method not found"
    body = m.group(1)
    assert "array_intersect_key" in body, \
        "upsert() must filter input via array_intersect_key against WRITABLE_FIELDS"
    assert "WRITABLE_FIELDS" in body, \
        "upsert() must reference the WRITABLE_FIELDS whitelist"
    assert "->insert($filtered)" in body, "upsert() must insert FILTERED data, not raw $data"
    assert "->update($filtered)" in body, "upsert() must update FILTERED data, not raw $data"


def test_hubpresenter_drops_systems_from_public_actions():
    """`systems` must NOT be in $publicActions; GET is recovered via startup()."""
    src = HUB_API.read_text()
    m = re.search(r"\$publicActions\s*=\s*\[(.*?)\]", src)
    assert m, "publicActions array not found"
    allowed = m.group(1)
    assert "'systems'" not in allowed, \
        "HubPresenter must NOT include 'systems' in publicActions (POST = unauthenticated write surface)"
    assert "'health'" in allowed


def test_hubpresenter_startup_bypasses_auth_only_for_get():
    """GET /systems is public; everything else falls through to BaseApiPresenter."""
    src = HUB_API.read_text()
    assert "public function startup(): void" in src
    m = re.search(r"public function startup\(\): void\s*\{(.*?)\n\t\}", src, re.DOTALL)
    assert m
    body = m.group(1)
    assert "'GET'" in body
    assert "parent::startup()" in body, \
        "non-GET requests must fall through to BaseApiPresenter::startup (requireTokenAuth)"


# ── test_client_body_suppression ────────────────────────────────────────────
# SEC-10 (2026-05-23): `throw new RuntimeException("HTTP $code: " . substr($raw,...))`
# put upstream bodies (Authentik fixed_data, Infisical metadata, Stalwart emails) into
# /events and launchd.err.log. Clients throw the status code only.

WING_MODEL = APP / "Model"


def _http_client_files():
    return sorted(
        list(WING_MODEL.glob("*Client.php"))
        + list(WING_MODEL.glob("*Provisioner.php"))
    )


def test_http_clients_suppress_response_body_in_exceptions():
    """No `substr(... $raw ...)` within 300 chars after a `throw new`."""
    violations = []
    for path in _http_client_files():
        src = path.read_text()
        for m in re.finditer(r"substr\(.*?\$raw.*?\)", src):
            pre = src[: m.start()]
            last_throw = pre.rfind("throw new")
            if last_throw > 0 and (m.start() - last_throw) < 300:
                rel = path.relative_to(REPO)
                violations.append(f"{rel}: substr at offset {m.start()} inside throw")
    assert not violations, (
        "HTTP client classes must not embed upstream response bodies "
        "in exception messages — peer-tenant data leak via /events log. "
        "Found:\n  " + "\n  ".join(violations)
    )


def test_authentik_client_explicitly_suppresses_body():
    """Pin the SEC-10 fix in AuthentikClient by name."""
    src = (WING_MODEL / "AuthentikClient.php").read_text()
    assert "body suppressed" in src, \
        "AuthentikClient should suppress upstream response bodies"
    for m in re.finditer(
        r'throw new RuntimeException\(\s*"Authentik\s+\{?\$method\}?\s+\{?\$path\}?:\s*HTTP\s+\{?\$code\}?:[^"]*"',
        src,
    ):
        msg = m.group(0)
        assert "$raw" not in msg, \
            f"AuthentikClient HTTP-code throw still interpolates $raw: {msg}"


# ── test_wing_speaks_bones_dialect ──────────────────────────────────────────
# Measured 2026-08-29: every Bone proxy route answered 401 for four months — BoneClient
# sent X-API-Key, retired by Bone decision O4 (2026-04-26). Fix wired the uncalled
# AgentIdentity Bearer and wrote its env into both carriers.

CLIENT = APP / "Model/BoneClient.php"
BONE_AUTH = REPO / "files/anatomy/bone/auth.py"
IDENTITY_KEYS = ("WING_AGENT_CLIENT_ID", "WING_AGENT_CLIENT_SECRET", "WING_AGENT_SCOPES")


def test_bone_still_demands_a_bearer() -> None:
    """The premise. If Bone ever accepts a key again this file is the wrong shape."""
    src = BONE_AUTH.read_text(encoding="utf-8")
    assert 'authorization.lower().startswith("bearer ")' in src, (
        "require_scope no longer refuses non-Bearer credentials — re-derive what "
        "Wing should send before trusting the assertions below"
    )


def test_the_client_sends_a_bearer_and_no_key() -> None:
    src = CLIENT.read_text(encoding="utf-8")
    assert "'Authorization: Bearer ' . $token," in src, (
        "BoneClient does not send a Bearer, so every route behind "
        "require_scope() answers 401 — the four-month defect"
    )
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith(("*", "/*", "//")))
    assert "X-API-Key" not in code, (
        "BoneClient sends X-API-Key again. Bone retired that channel (decision "
        "O4) and reads no key at all; a request carrying one authenticates as "
        "nobody."
    )


def test_the_token_comes_from_the_identity_that_had_no_caller() -> None:
    src = CLIENT.read_text(encoding="utf-8")
    assert "AgentIdentity::fromEnv()" in src, (
        "the Bearer is not minted through AgentIdentity — if it comes from "
        "somewhere else, say where, because a second minting path is a second "
        "place the scopes can drift from authentik_agent_clients"
    )


def test_an_unmintable_identity_is_not_reported_as_a_401() -> None:
    """A 401 sends the reader to the token; a 503 naming the identity sends them to Authentik."""
    src = CLIENT.read_text(encoding="utf-8")
    assert "'error' => 'Bone identity unavailable'" in src


def test_both_env_carriers_write_what_the_identity_reads() -> None:
    """The .env FrankenPHP loads and the launchd plist: a key in one is not a key in the other."""
    for carrier in (ENV, PLIST):
        text = carrier.read_text(encoding="utf-8")
        missing = [k for k in IDENTITY_KEYS if k not in text]
        assert not missing, (
            f"{carrier.relative_to(REPO)} does not write {missing}. "
            "AgentIdentity::fromEnv() falls back to an EMPTY secret, so the "
            "mint throws and the state surface is down for a reason no reader "
            "of the 401 would guess."
        )


# ── test_preloader_does_not_block_fallback_login ────────────────────────────
# sso-autologin-plan.md §"Custom preloader": the splash masks ~100-200 ms on repeat
# logins and must never trap a user — ?skip_splash=1 always bypasses, a prompt=none
# failure routes to the normal flow, redirect hosts are per-service only.

PRESENTER = APP / "Presenters" / "HubPresenter.php"
SPLASH = APP / "Templates" / "Hub" / "splash.latte"
WARMER = WING / "www" / "assets" / "hub-session-warmer.js"


def test_splash_offers_manual_escape_to_dashboard():
    """The splash always carries a manual skip link so a stuck user reaches the normal flow without JS."""
    splash = SPLASH.read_text()
    assert "/hub?skip_splash=1" in splash, \
        "splash has no manual skip-to-dashboard link (would trap the user)"


def test_warmer_failure_routes_to_normal_flow_not_dead_end():
    """On prompt=none failure the warmer navigates to the fallback URL, which skips the splash."""
    js = WARMER.read_text()
    assert "goToNormalFlow" in js, "no normal-flow fallback function"
    assert "window.location.replace(fallbackUrl)" in js, \
        "goToNormalFlow does not navigate to the fallback URL"
    assert "skip_splash=1" in js, "fallback URL does not skip the splash"


def test_preloader_never_disables_local_form():
    """The preloader is a pure client-side redirect helper: no login-form toggle lives in it."""
    for p in (PRESENTER, SPLASH, WARMER):
        src = p.read_text()
        for forbidden in ("DISABLE_LOGIN_FORM", "SSO_ONLY", "ENABLE_PASSWORD_SIGNIN_FORM"):
            assert forbidden not in src, (
                f"{p.name} mutates a service login-form toggle ({forbidden}) — "
                "the preloader must stay a pure client-side redirect helper "
                "and never disable a local fallback form")


def test_redirect_host_whitelist_is_per_service_only():
    """ALLOWED_REDIRECT_HOSTS is only `<svc>.<tld>` + `auth.<tld>`; off-list falls back to /hub."""
    js = WARMER.read_text()
    assert "ALLOWED_REDIRECT_HOSTS" in js, "no redirect-host whitelist"
    assert "hostAllowed" in js, "warmer does not check the host whitelist"
    assert "'auth.' + tenantDomain" in js, \
        "whitelist missing auth.<tld>"
    assert "+ tenantDomain" in js, \
        "whitelist not derived from the tenant domain"
    assert "return '/hub'" in js, \
        "warmer does not fall back to same-origin /hub for off-whitelist hosts"


def test_bypass_preserves_service_deeplink():
    """The skip/dormant bypass forwards a ?service= deep-link to /hub."""
    presenter = PRESENTER.read_text()
    assert "'service'" in presenter or '"service"' in presenter, \
        "renderSplash bypass drops the ?service= deep-link"


# ── test_wing_tracy_secret_redaction ────────────────────────────────────────
# SEC-2 (2026-05-23): Tracy exception dumps (0644) held every Wing env secret. Fix:
# extend $keysToHide + log dir 0700; debug cookie-gated (2026-05-27). plat-gate-shape
# (2026-09-15): substring hunt stayed green with the fix commented out — strip comments.

BOOTING = APP / "Bootstrap/Booting.php"

_PHP_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_PHP_LINE = re.compile(r"//[^\n]*")
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)

REQUIRED_SUBSTRINGS = (
    "token",
    "secret",
    "hmac",
    "jwt",
    "bearer",
    "key",  # APP_KEY, NOS_DEPLOY_HMAC_SECRET
    "credentials",
)


def _php_code(src: str) -> str:
    return _PHP_LINE.sub("", _PHP_BLOCK.sub("", src))


def _xml_code(src: str) -> str:
    return _XML_COMMENT.sub("", src)


def _booting_code() -> str:
    return _php_code(BOOTING.read_text())


def _secret_key_substrings(code: str) -> list[str]:
    m = re.search(r"SECRET_KEY_SUBSTRINGS\s*=\s*\[(.*?)]\s*;", code, re.S)
    assert m, "SECRET_KEY_SUBSTRINGS array not found in live PHP"
    return re.findall(r"'([^']+)'", m.group(1))


def test_booting_php_extends_tracy_keys_to_hide():
    """Booting.php array_merges the nOS secret substrings into Debugger::$keysToHide."""
    code = _booting_code()
    assert re.search(r"use\s+Tracy\\Debugger\s*;", code)
    assert re.search(
        r"Debugger::\$keysToHide\s*=\s*array_merge\s*\(\s*Debugger::\$keysToHide",
        code,
    ), "must array_merge into Debugger::$keysToHide, not overwrite it"
    items = _secret_key_substrings(code)
    missing = [s for s in REQUIRED_SUBSTRINGS if s not in items]
    assert not missing, (
        f"SECRET_KEY_SUBSTRINGS is missing {missing} — parsed {items}"
    )


def test_booting_extends_after_enable_tracy():
    """enableTracy() registers the debugger BEFORE $keysToHide is assigned."""
    code = _booting_code()
    enable_idx = code.find("enableTracy(")
    extend = re.search(r"Debugger::\$keysToHide\s*=\s*array_merge", code)
    assert enable_idx > 0 and extend, "enableTracy() or $keysToHide merge missing"
    assert extend.start() > enable_idx, (
        "$keysToHide assignment must come AFTER enableTracy() call"
    )


def test_wing_role_creates_log_dir_at_0700():
    """The log dir mode decides who can READ the dumps: a dedicated 0700 task, out of the 0755 loop."""
    src = (REPO / "roles/pazny.wing/tasks/main.yml").read_text()
    idx = src.find("Ensure log directory exists at 0700")
    assert idx > 0, \
        "pazny.wing must have a dedicated task setting wing_log_dir to 0700"
    loop_start = src.find("Ensure runtime directories exist")
    loop_end = src.find("\n- name:", loop_start + 10)
    loop_body = src[loop_start:loop_end]
    assert "{{ wing_log_dir }}" not in loop_body, \
        "wing_log_dir must be removed from the 0755 loop (use the dedicated 0700 task)"


def test_tracy_debug_off_by_default_cookie_gated():
    """2026-05-27: setDebugMode('127.0.0.1') kept the bar on for all proxied traffic.
    Debug is OFF by default and gated behind a long secret cookie."""
    code = _booting_code()
    assert "setDebugMode('127.0.0.1')" not in code, "IP gating is a no-op behind the loopback proxy"
    assert re.search(r"getenv\(\s*'WING_TRACY_SECRET'\s*\)", code), (
        "debug must read WING_TRACY_SECRET from the environment"
    )
    assert re.search(r"\$_COOKIE\s*\[\s*'tracy-debug'\s*\]", code), (
        "debug must require a matching tracy-debug cookie"
    )
    assert re.search(r"hash_equals\s*\(", code), "cookie compare must be constant-time"
    plist = _xml_code(PLIST.read_text())
    assert "<key>WING_TRACY_SECRET</key>" in plist, (
        "plist must declare WING_TRACY_SECRET as a live env key, not a comment"
    )
    assert "wing_tracy_secret | default('')" in plist


def test_error_presenter_renders_clean_production_page():
    """errorPresenter: Error needs a minimal IPresenter (not BasePresenter) that emits no Tracy meta."""
    ep = APP / "Presenters/ErrorPresenter.php"
    assert ep.is_file(), "ErrorPresenter.php missing (errorPresenter: Error in common.neon)"
    src = _php_code(ep.read_text())
    assert "implements Nette\\Application\\IPresenter" in src, "must implement IPresenter directly"
    assert "extends BasePresenter" not in src, "must NOT extend BasePresenter (edge guard would re-fire)"
    assert 'name="generator"' not in src and 'content="Tracy"' not in src, \
        "clean error page must not emit a generator/Tracy meta"
