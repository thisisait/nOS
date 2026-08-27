"""The agent runners' pre-flight MINTS A TOKEN; liveness is not a verdict.

MEASURED 2026-08-25: `tools/run-upgrade-architect.sh` (and every sibling)
pre-flighted Authentik with `GET /-/health/live/` and printed
`✓ Authentik … liveness → 200` — then handed the job to pulse-run-agent.sh,
whose very first act is a client_credentials grant that can 400 on
`invalid_grant`. The pre-flight asked whether the SERVER answers; the run
dies on whether THIS CLIENT's credential is the one the provider holds.
A check that cannot fail the way it matters is the estate's signature
defect, and this one wore a checkmark.

The fix is `pulse.secrets.token_preflight` — living beside the `secret:`
resolver it depends on, one implementation for every caller (the daemon's
package, the shell runners via the zero-logic `pulse_token_preflight` shim
in tools/lib/pulse-env.sh): it performs the actual grant for the actual
client and fails closed on anything but 200.

This file tests the ARTIFACT against a local stub token endpoint — the
refusal (400), the success (200), the unresolvable-reference and
missing-credential shapes, and that resolution happens INSIDE the pre-flight
(same code path as the daemon). Then it pins that every agent runner
actually calls it.
"""

from __future__ import annotations

import http.server
import json
import pathlib
import subprocess
import sys
import threading

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
LIB = REPO / "tools/lib/pulse-env.sh"
PKG = REPO / "files/anatomy/pulse"


class _StubToken(http.server.BaseHTTPRequestHandler):
    code = 200
    seen: list[tuple[str, str]] = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _StubToken.seen.append((self.path, body.decode()))
        self.send_response(_StubToken.code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "invalid_grant"}'
                         if _StubToken.code >= 400 else b'{"access_token": "x"}')

    def log_message(self, *_):  # quiet
        pass


@pytest.fixture()
def stub_server():
    _StubToken.seen = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _StubToken)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _run_cli(tmp_path: pathlib.Path, env_json: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pulse.secrets", "--token-preflight"],
        input=json.dumps(env_json), capture_output=True, text=True, timeout=30,
        env={"HOME": str(tmp_path), "PYTHONPATH": str(PKG), "PATH": "/usr/bin:/bin"},
    )


def _env(url: str, secret: str = "FAKE-unit-secret-value") -> dict:
    return {
        "NOS_AUTHENTIK_URL": url,
        "NOS_AGENT_CLIENT_ID": "nos-unit-agent",
        "NOS_AGENT_CLIENT_SECRET": secret,
    }


def test_a_200_grant_passes_and_says_it_verified_the_credential(tmp_path, stub_server):
    _StubToken.code = 200
    proc = _run_cli(tmp_path, _env(stub_server))
    assert proc.returncode == 0, proc.stderr
    assert "nos-unit-agent" in proc.stdout and "200" in proc.stdout
    path, body = _StubToken.seen[0]
    assert path == "/application/o/token/", (
        f"the pre-flight asked {path!r}, not the TOKEN endpoint — a liveness "
        "probe has crept back in"
    )
    assert "grant_type=client_credentials" in body


def test_a_refused_credential_fails_closed_and_names_the_client(tmp_path, stub_server):
    _StubToken.code = 400
    proc = _run_cli(tmp_path, _env(stub_server))
    assert proc.returncode == 1, (
        f"HTTP 400 from the token endpoint returned rc {proc.returncode} — "
        "the pre-flight passed a credential the provider refused. This is "
        "the exact failure the liveness probe could not see."
    )
    assert "nos-unit-agent" in proc.stderr and "400" in proc.stderr
    assert "FAKE-unit-secret-value" not in proc.stdout + proc.stderr, (
        "the refusal printed the secret"
    )


def test_a_reference_is_resolved_inside_the_preflight(tmp_path, stub_server):
    """Same code path as the daemon: refs welcome, resolved from the store."""
    _StubToken.code = 200
    nos = tmp_path / ".nos"
    nos.mkdir()
    (nos / "secrets.yml").write_text(
        "agent_unit_client_secret: FAKE-store-resolved-value\n"
    )
    proc = _run_cli(tmp_path, _env(stub_server, "secret:agent_unit_client_secret"))
    assert proc.returncode == 0, proc.stderr
    _, body = _StubToken.seen[0]
    assert "FAKE-store-resolved-value" in body, (
        "the pre-flight did not resolve the reference before the grant — it "
        "would have verified the literal string `secret:…` instead"
    )


def test_an_unresolvable_reference_is_refused_before_any_request(tmp_path, stub_server):
    proc = _run_cli(tmp_path, _env(stub_server, "secret:fake_unit_test_name"))
    assert proc.returncode == 3, proc.stderr
    assert not _StubToken.seen, (
        "the pre-flight sent a literal `secret:…` string to the provider — "
        "it would 400 for the WRONG reason and bury the real fault"
    )


def test_a_credential_less_env_is_a_refusal_not_a_skip(tmp_path, stub_server):
    proc = _run_cli(tmp_path, {"NOS_AUTHENTIK_URL": stub_server})
    assert proc.returncode == 2 and not _StubToken.seen, (
        "an env with no client credential slid through the pre-flight — the "
        "old `if [[ -n $AK_URL ]]` shape, where absence passed silently"
    )


def test_a_missing_authentik_url_is_a_refusal(tmp_path):
    proc = _run_cli(tmp_path, {k: v for k, v in _env("x").items()
                               if k != "NOS_AUTHENTIK_URL"})
    assert proc.returncode == 2


def test_the_shell_shim_reaches_the_same_implementation(tmp_path, stub_server):
    """One end-to-end pass through bash: source the shim, refuse a 400."""
    _StubToken.code = 400
    proc = subprocess.run(
        ["bash", "-c", f'source "{LIB}" && pulse_token_preflight "$1"',
         "bash", json.dumps(_env(stub_server))],
        capture_output=True, text=True, timeout=30,
        # /usr/bin:/bin alone assumed a layout the CI image lacks: python3
        # missing -> 127, read as a broken shim.
        env={"HOME": str(tmp_path),
             "PATH": f"{pathlib.Path(sys.executable).parent}:/usr/bin:/bin"},
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "nos-unit-agent" in proc.stderr


def test_every_agent_runner_calls_the_token_preflight():
    """A resolver every runner shares is only half the doctrine — the grant
    check must be shared the same way. Any tools/run-*.sh that resolves a
    pulse_jobs env (i.e. runs an agent job) must also pre-flight the grant."""
    offenders = []
    for path in sorted(REPO.glob("tools/run-*.sh")):
        src = path.read_text(encoding="utf-8")
        if "resolve_pulse_env_json" in src and "pulse_token_preflight" not in src:
            offenders.append(path.name)
    assert not offenders, (
        "agent runner(s) resolve the job env but never verify the grant: "
        f"{offenders} — their pre-flight can go green on a credential "
        "Authentik refuses."
    )


def test_no_runner_keeps_a_liveness_only_authentik_gate():
    """`/-/health/live/` may not reappear as the runners' Authentik verdict."""
    offenders = [
        p.name for p in sorted(REPO.glob("tools/run-*.sh"))
        if "/-/health/live/" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"liveness-only Authentik gate(s) grew back in {offenders} — the "
        "server answering says nothing about this client's credential"
    )
