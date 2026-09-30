"""The Woodpecker PAT is minted through SSO, not pasted and not by a form.

Every blank ended with "WOODPECKER CI IS NOT WIRED TO THE FORGE". The token
is what the UI shows; a person gets it by signing in to Woodpecker through
Gitea and to Gitea through Authentik. tools/woodpecker-token.py does exactly
that (tools/nos_sso.py). The first version POSTed Gitea's local sign-in form,
which only worked while the gitea-base extension was broken; with the form
really hidden it got 403 (2026-09-30). This gate RUNS the script against three
fake servers — Authentik, Gitea, Woodpecker — and checks the role's order.
"""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools/woodpecker-token.py"
POST_REPO = REPO / "roles/pazny.woodpecker/tasks/post-repo.yml"


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"127.0.0.1:{srv.server_port}"


class _Base(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def cookies(self):
        return dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p)

    def q(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}


HOSTS: dict = {}
STATE = {"broken_wp": False, "password": "pw"}


class Auth(_Base):
    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith("/api/v3/flows/executor/"):
            return self.send(200, b'{"component": "ak-stage-identification"}', [("Content-Type", "application/json")])
        if p == "/application/o/authorize/" and "ak" in self.cookies():
            q = self.q()
            return self.send(302, headers=[("Location", f"{q['redirect_uri']}?code=c1&state={q['state']}")])
        return self.send(403, b"no session")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if "uid_field" in body:
            return self.send(200, b'{"component": "ak-stage-password"}', [("Content-Type", "application/json")])
        if body.get("password") == STATE["password"]:
            return self.send(200, b'{"component": "xak-flow-redirect", "to": "/"}',
                             [("Content-Type", "application/json"), ("Set-Cookie", "ak=1; Path=/")])
        return self.send(200, b'{"component": "ak-stage-password"}', [("Content-Type", "application/json")])


class Gitea(_Base):
    def do_GET(self):
        p, q = urlparse(self.path).path, self.q()
        if p == "/user/oauth2/authentik":
            cb = f"http://{HOSTS['gitea']}/user/oauth2/authentik/callback"
            return self.send(303, headers=[("Location", f"http://{HOSTS['auth']}/application/o/authorize/?"
                                            + urlencode({"redirect_uri": cb, "state": "g"}))])
        if p == "/user/oauth2/authentik/callback" and q.get("code"):
            return self.send(303, headers=[("Location", "/"), ("Set-Cookie", "i_like_gitea=s; Path=/")])
        if p == "/login/oauth/authorize":
            if "i_like_gitea" not in self.cookies():
                return self.send(303, headers=[("Location", "/user/login")])
            return self.send(303, headers=[("Location", f"{q['redirect_uri']}?code=g1&state={q['state']}")])
        if p == "/" and "i_like_gitea" in self.cookies():
            return self.send(200, b"gitea home")
        return self.send(404)


class Woodpecker(_Base):
    def do_GET(self):
        p, q = urlparse(self.path).path, self.q()
        if p == "/authorize" and "code" not in q:
            return self.send(303, headers=[("Location", f"http://{HOSTS['gitea']}/login/oauth/authorize?"
                                            + urlencode({"redirect_uri": f"http://{HOSTS['wp']}/authorize", "state": "w"}))])
        if p == "/authorize":
            if STATE["broken_wp"]:
                return self.send(303, headers=[("Location", "/login?error=oauth_error")])
            return self.send(303, headers=[("Location", "/"), ("Set-Cookie", "user_sess=jwt; Path=/")])
        if p in ("/", "/login"):
            return self.send(200, b"wp")
        if p == "/web-config.js":
            return self.send(200, b'window.WOODPECKER_CSRF = "csrf1";')
        if p == "/api/user":
            ok = self.headers.get("Authorization") == "Bearer tok123"
            return self.send(200 if ok else 401, b'{"login": "akadmin"}' if ok else b"no",
                             [("Content-Type", "application/json")])
        return self.send(404)

    def do_POST(self):
        if self.path == "/api/user/token" and "user_sess" in self.cookies() \
                and self.headers.get("X-CSRF-TOKEN") == "csrf1":
            return self.send(200, b"tok123")
        return self.send(401)


def _run(password="pw", broken_wp=False):
    STATE.update(broken_wp=broken_wp)
    servers = []
    for name, h in (("auth", Auth), ("gitea", Gitea), ("wp", Woodpecker)):
        srv, host = _serve(h)
        servers.append(srv)
        HOSTS[name] = host
    try:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--user=akadmin", f"--auth-host={HOSTS['auth']}",
             f"--gitea-public=http://{HOSTS['gitea']}", f"--woodpecker-public=http://{HOSTS['wp']}"],
            capture_output=True, text=True, env={"SSO_PASSWORD": password, "PATH": "/usr/bin:/bin",
                                                   "HOME": str(Path.home())})
    finally:
        for srv in servers:
            srv.shutdown()


def test_the_sso_walk_prints_the_token_and_nothing_else() -> None:
    r = _run()
    assert r.returncode == 0, r.stderr
    assert r.stdout == "tok123\n" and r.stderr == ""


def test_a_refused_authentik_login_prints_no_token() -> None:
    r = _run(password="wrong")
    assert r.returncode == 1 and r.stdout == "" and "authentik login" in r.stderr


def test_a_woodpecker_callback_without_a_session_prints_no_token() -> None:
    r = _run(broken_wp=True)
    assert r.returncode == 1 and r.stdout == "" and "woodpecker grant" in r.stderr


def test_the_mint_never_posts_a_local_sign_in_form() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    assert "/user/login" not in src and "GITEA_PASSWORD" not in src


def test_the_role_probes_before_it_mints_and_mints_before_it_activates() -> None:
    tasks = yaml.safe_load(POST_REPO.read_text(encoding="utf-8"))
    names = [t["name"] for t in tasks]
    probe = next(i for i, n in enumerate(names) if "Probe the persisted PAT" in n)
    mint = next(i for i, n in enumerate(names) if "Mint the PAT" in n)
    persist = next(i for i, n in enumerate(names) if "Persist the PAT" in n)
    activate = next(i for i, n in enumerate(names) if "Activate nOS repo (token present)" in n)
    assert probe < mint < persist < activate
    mint_task = tasks[mint]
    assert mint_task["environment"]["SSO_PASSWORD"] == "{{ authentik_bootstrap_password }}"
    assert mint_task["no_log"] is True and mint_task["failed_when"] is False
    assert "woodpecker-token.py" in str(mint_task["ansible.builtin.command"]["argv"])
    block = tasks[activate]["block"]
    names = [t["name"] for t in block]
    collab = next(i for i, n in enumerate(names) if "repo admin in Gitea" in n)
    assert collab < next(i for i, n in enumerate(names) if "Activate nOS repo (first run only)" in n)
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
