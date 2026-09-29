"""The Woodpecker PAT is minted by walking the Gitea OAuth grant, not pasted.

Every blank ended with "WOODPECKER CI IS NOT WIRED TO THE FORGE" and a note
to mint the token in a browser. The token is what the UI shows; the UI gets
it through the same OAuth dance tools/woodpecker-token.py now performs. This
gate RUNS the script against a fake that plays both Gitea and Woodpecker,
with the Secure cookie flag both services really set, and then checks the
role probes a persisted token before trusting it.
"""
from __future__ import annotations

import http.server
import subprocess
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools/woodpecker-token.py"
POST_REPO = REPO / "roles/pazny.woodpecker/tasks/post-repo.yml"
GITEA_PUBLIC, WP_PUBLIC = "https://git.example", "https://ci.example"


class Fake(http.server.BaseHTTPRequestHandler):
    """One server, two roles; `broken_callback` makes Woodpecker set no session."""
    broken_callback = False

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cookies(self):
        return dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/authorize" and "code" not in u.query:            # woodpecker start
            loc = f"{GITEA_PUBLIC}/login/oauth/authorize?client_id=c&redirect_uri={WP_PUBLIC}/authorize&response_type=code&state=s"
            return self._send(303, headers=[("Location", loc), ("Set-Cookie", "wp_state=1; Path=/; Secure")])
        if u.path == "/login/oauth/authorize":                            # gitea grant page
            if "i_like_gitea" not in self._cookies():
                return self._send(303, headers=[("Location", "/user/login")])
            form = b'<form method="post" action="/login/oauth/grant"><input type="hidden" name="client_id" value="c"><input type="hidden" name="state" value="s"><input type="hidden" name="redirect_uri" value="' + WP_PUBLIC.encode() + b'/authorize"></form>'
            return self._send(200, form)
        if u.path == "/authorize":                                        # woodpecker callback
            if "wp_state" not in self._cookies() or self.broken_callback:
                return self._send(303, headers=[("Location", "/login?error=oauth_error")])
            return self._send(303, headers=[("Location", "/"), ("Set-Cookie", "user_sess=jwt; Path=/; HttpOnly; Secure")])
        if u.path == "/web-config.js":
            return self._send(200, b'window.WOODPECKER_CSRF = "csrf1";')
        if u.path == "/api/user":
            if self.headers.get("Authorization") == "Bearer tok123":
                return self._send(200, b'{"login": "pazny"}', [("Content-Type", "application/json")])
            return self._send(401, b"Unauthorized")
        return self._send(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if self.path == "/user/login":
            if parse_qs(body).get("password") == ["pw"]:
                return self._send(303, headers=[("Location", "/"), ("Set-Cookie", "i_like_gitea=sess; Path=/; HttpOnly; Secure")])
            return self._send(303, headers=[("Location", "/user/login")])
        if self.path == "/login/oauth/grant":
            q = parse_qs(body)
            if "i_like_gitea" in self._cookies() and q.get("granted") == ["true"] and q.get("state") == ["s"]:
                return self._send(303, headers=[("Location", f"{WP_PUBLIC}/authorize?code=abc&state=s")])
            return self._send(400)
        if self.path == "/api/user/token":
            if "user_sess" in self._cookies() and self.headers.get("X-CSRF-TOKEN") == "csrf1":
                return self._send(200, b"tok123")
            return self._send(401)
        return self._send(404)


def _run(broken=False, password="pw"):
    Fake.broken_callback = broken
    srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        return subprocess.run(
            ["python3", str(SCRIPT), "--user=pazny", f"--woodpecker={base}", f"--gitea={base}",
             f"--gitea-public={GITEA_PUBLIC}", f"--woodpecker-public={WP_PUBLIC}"],
            capture_output=True, text=True, env={"GITEA_PASSWORD": password, "PATH": "/usr/bin:/bin"},
        )
    finally:
        srv.shutdown()


def test_the_grant_walk_prints_the_token_and_nothing_else() -> None:
    r = _run()
    assert r.returncode == 0, r.stderr
    assert r.stdout == "tok123\n" and r.stderr == ""


def test_a_callback_without_a_session_prints_no_token() -> None:
    r = _run(broken=True)
    assert r.returncode == 1 and r.stdout == "" and "session" in r.stderr


def test_a_refused_login_stops_before_the_grant() -> None:
    r = _run(password="wrong")
    assert r.returncode == 1 and r.stdout == "" and "login refused" in r.stderr


def test_the_role_probes_before_it_mints_and_mints_before_it_activates() -> None:
    tasks = yaml.safe_load(POST_REPO.read_text(encoding="utf-8"))
    names = [t["name"] for t in tasks]
    probe = next(i for i, n in enumerate(names) if "Probe the persisted PAT" in n)
    mint = next(i for i, n in enumerate(names) if "Mint the PAT" in n)
    persist = next(i for i, n in enumerate(names) if "Persist the PAT" in n)
    activate = next(i for i, n in enumerate(names) if "Activate nOS repo (token present)" in n)
    assert probe < mint < persist < activate
    mint_task = tasks[mint]
    assert mint_task["environment"]["GITEA_PASSWORD"] == "{{ gitea_admin_password }}"
    assert mint_task["no_log"] is True and mint_task["failed_when"] is False
    assert "woodpecker-token.py" in " ".join(mint_task["ansible.builtin.command"]["argv"])
    assert "_woodpecker_pat_probe.status" in mint_task["when"], "a stale token must trigger a re-mint"
    assert tasks[persist]["no_log"] is True


def test_the_activating_run_also_knows_the_repo_id() -> None:
    """Secrets are seeded on the run that activates the repo: the lookup
    answered 404 then, so the id must fall through to the activation response."""
    import jinja2
    tasks = yaml.safe_load(POST_REPO.read_text(encoding="utf-8"))
    block = next(t for t in tasks if "Activate nOS repo (token present)" in t["name"])["block"]
    expr = next(t for t in block if "Resolve the repo id" in t["name"])["ansible.builtin.set_fact"]["_woodpecker_repo_id"]
    render = lambda **ctx: jinja2.Environment(undefined=jinja2.ChainableUndefined).from_string(expr).render(**ctx).strip()
    assert render(_woodpecker_repo_check={"json": {}}, _woodpecker_activate={"json": {"id": 7}}) == "7"
    assert render(_woodpecker_repo_check={"json": {"id": 3}}, _woodpecker_activate={}) == "3"
    assert render(_woodpecker_repo_check={}, _woodpecker_activate={}) == "0"
    secrets = (REPO / "roles/pazny.woodpecker/tasks/post-secrets.yml").read_text(encoding="utf-8")
    assert "_woodpecker_repo_id" in secrets and "_woodpecker_repo_check" not in secrets
