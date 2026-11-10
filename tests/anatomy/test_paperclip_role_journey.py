"""One journey through the Paperclip role: the compose it renders, the drain before a
restart, the post-start steps (onboarding, hostname, leases) and a followed workspace.

Absorbed (2026-11-10, roadmap gate-diet), one section each:
  test_paperclip_agents_reach_their_own_api, test_paperclip_healthcheck_is_reachability_not_hostname,
  test_paperclip_drains_before_a_restart, test_paperclip_onboarding_reaches_an_invite,
  test_paperclip_serves_its_own_hostname, test_paperclip_releases_orphaned_leases,
  test_paperclip_workspace_follows_its_branch.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.paperclip"
TPL = ROLE / "templates/compose.yml.j2"
MAIN = ROLE / "tasks" / "main.yml"
POST = ROLE / "tasks" / "post.yml"


def _tasks():
    return yaml.safe_load(POST.read_text(encoding="utf-8"))


# ── test_paperclip_agents_reach_their_own_api ───────────────────────────────
# 2026-10-23: every agent failed "Could not connect" on PAPERCLIP_API_URL derived
# from the hostname + LISTEN port, where 3100 is not published. Agents run in the
# container, so their API is the loopback listener; BETTER_AUTH_URL was unset.

def _env() -> dict:
    env = jinja2.Environment(undefined=jinja2.Undefined)
    env.filters["urlencode"] = str
    text = env.from_string(TPL.read_text()).render(paperclip_domain="paperclip.example.eu", paperclip_version="v",
                                                  paperclip_port=3006)
    return next(iter(yaml.safe_load(text)["services"].values()))["environment"]


def test_agents_get_the_loopback_api_of_their_own_container():
    env = _env()
    assert env.get("PAPERCLIP_API_URL") == f"http://localhost:{env['PAPERCLIP_LISTEN_PORT']}", env.get("PAPERCLIP_API_URL")


def test_the_server_knows_its_public_url():
    assert _env().get("BETTER_AUTH_URL") == "https://paperclip.example.eu"


# ── test_paperclip_healthcheck_is_reachability_not_hostname ─────────────────
# post.yml writes the hostname allow-list AFTER the strict health-wait, so a check
# that needed it stalled the first blank (2026-09-29, devops 4/5). The rendered
# check runs with a stub curl: 403 is up, a refused connection (000) is down.

def _test_cmd() -> str:
    env = jinja2.Environment(undefined=jinja2.Undefined)
    env.filters["urlencode"] = str
    text = env.from_string(TPL.read_text()).render(paperclip_domain="paperclip.example.eu", paperclip_version="v", paperclip_port=3100)
    svc = next(iter(yaml.safe_load(text)["services"].values()))
    kind, cmd = svc["healthcheck"]["test"]
    assert kind == "CMD-SHELL"
    return cmd


def _run_check(cmd: str, code: str, tmp_path: Path) -> int:
    (tmp_path / "curl").write_text(f"#!/bin/sh\nprintf '{code}'\n")
    (tmp_path / "hostname").write_text("#!/bin/sh\necho 172.23.0.7 172.30.0.43\n")
    for f in ("curl", "hostname"):
        (tmp_path / f).chmod(0o755)
    return subprocess.run(["sh", "-c", cmd], env={"PATH": f"{tmp_path}:/usr/bin:/bin"}).returncode


def test_a_403_before_the_hostname_is_registered_is_up(tmp_path):
    assert _run_check(_test_cmd(), "403", tmp_path) == 0


def test_a_refused_connection_is_down(tmp_path):
    assert _run_check(_test_cmd(), "000", tmp_path) == 1


def test_the_check_still_targets_the_published_interface():
    assert "hostname -i" in _test_cmd() and "localhost" not in _test_cmd()


# ── test_paperclip_drains_before_a_restart ──────────────────────────────────
# 2026-10-23: one restart killed six agent runs and their files. The role waits
# (paperclip_drain_timeout_s) for no run to be going before it renders the
# fragment that recreates, and refuses on timeout.

def _names():
    return [t.get("name", "") for t in yaml.safe_load(MAIN.read_text(encoding="utf-8"))]


def test_the_drain_comes_before_the_render_and_refuses_on_timeout():
    names = _names()
    wait = next(i for i, n in enumerate(names) if "Drain: wait" in n)
    refuse = next(i for i, n in enumerate(names) if "Drain: refuse" in n)
    render = names.index("[pazny.paperclip] Render compose override fragment")
    assert wait < refuse < render, names


def test_the_wait_counts_every_run_not_yet_over():
    tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
    sql = next(t for t in tasks if "Drain: wait" in t.get("name", ""))["ansible.builtin.shell"]
    assert "status NOT IN ('succeeded', 'failed', 'cancelled', 'interrupted')" in sql, sql


def test_the_timeout_has_a_default():
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity as ni
    assert ni.resolve_flag("paperclip_drain_timeout_s", ni.default_layers()), "no default for the drain timeout"


# ── test_paperclip_onboarding_reaches_an_invite ─────────────────────────────
# `onboard --yes` writes config.json as local_trusted while the server runs
# authenticated, so `auth bootstrap-ceo` declined and every blank had no login.
# The align step runs before the bootstrap; its node snippet runs here: once.

def test_the_align_step_precedes_the_bootstrap():
    names = [t["name"] for t in _tasks()]
    align = names.index("[pazny.paperclip Post] Align config.json with the mode the server runs under")
    onboard = names.index("[pazny.paperclip Post] Initialize Paperclip instance (non-interactive onboard)")
    boot = names.index("[pazny.paperclip Post] Bootstrap CEO admin invite (first-run only)")
    assert onboard < align < boot


def test_the_snippet_aligns_a_quickstart_config_once(tmp_path):
    task = next(t for t in _tasks() if t["name"].endswith("mode the server runs under"))
    js = task["ansible.builtin.shell"].split("node -e '", 1)[1].rsplit("'", 1)[0]
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"server": {"deploymentMode": "local_trusted", "bind": "loopback", "allowedHostnames": ["x"]}}))
    js = js.replace("/paperclip/instances/default/config.json", str(cfg))
    run = lambda: subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()
    assert run() == "ALIGNED"
    got = json.loads(cfg.read_text())["server"]
    assert got["deploymentMode"] == "authenticated" and got["allowedHostnames"] == ["x"]
    assert run() == "aligned"


def test_the_invite_is_kept_not_only_printed():
    keep = next(t for t in _tasks() if "Keep the CEO invite URL" in t["name"])
    assert keep["no_log"] is True and keep["ansible.builtin.copy"]["mode"] == "0600"
    assert "Invite URL" in keep["ansible.builtin.copy"]["content"]


# ── test_paperclip_serves_its_own_hostname ──────────────────────────────────
# 2026-10-11: config.json allowed the hostname, the server still answered 403;
# registration said "already allowed", so the changed-keyed handler never fired.
# Pinned: ask the server (Host header, body read), restart now, fail if it refuses.

REFUSAL = "not allowed"


def _index(pred) -> int:
    return next((i for i, t in enumerate(_tasks()) if pred(t)), -1)


def _register_i() -> int:
    return _index(lambda t: t.get("name", "").endswith("Register primary allowed hostname"))


def test_the_server_is_asked_after_registration():
    probe = _index(lambda t: "ansible.builtin.uri" in t
                   and t["ansible.builtin.uri"].get("return_content")
                   and "Host" in (t["ansible.builtin.uri"].get("headers") or {}))
    assert probe > _register_i() >= 0, (
        "no Host-header probe that reads the body after the hostname is "
        "registered; the file can say allowed while the server refuses")


def test_a_refusal_restarts_now_not_via_a_handler():
    tasks = _tasks()
    restart = next((t for t in tasks[_register_i() + 1:]
                    if "restart" in str(t.get("ansible.builtin.shell", ""))
                    and REFUSAL in str(t.get("when", ""))), None)
    assert restart is not None, (
        f"no restart conditioned on the server's '{REFUSAL}' answer; a "
        "handler keyed on `changed` is lost when the play fails later")
    assert "notify" not in tasks[_register_i()], (
        "registration still notifies a handler; the probe owns the restart now, "
        "so the notify would restart twice")


def test_a_refusal_after_restart_fails_the_run():
    tasks = _tasks()[_register_i() + 1:]
    assert any("fail" in " ".join(t) and REFUSAL in str(t.get("when", "")) + str(t.get("failed_when", ""))
               for t in tasks), (
        "nothing fails the run when Paperclip still refuses its hostname after "
        "the restart; the 403 would surface only in smoke")


# ── test_paperclip_releases_orphaned_leases ─────────────────────────────────
# 2026-10-24: 9 leases stood `active` on runs a restart reaped to `interrupted`,
# so every retry refused (upstream paperclipai/paperclip#14672). The role
# releases those after the server is up, and only those.

def _release():
    return next((t for t in _tasks() if "orphaned" in t.get("name", "")), None)


def test_the_role_releases_orphaned_leases():
    t = _release()
    assert t, "no task releases the leases a restart orphaned"
    sql = " ".join(t["ansible.builtin.shell"].split())
    assert "UPDATE environment_leases" in sql and "released_at = now()" in sql
    assert "l.released_at IS NULL" in sql, "would re-release leases that are already released"
    assert "r.status = 'interrupted'" in sql, "must release only leases whose run is over"
    assert "ON_ERROR_STOP=1" in sql, "a failed UPDATE would exit 0 and read as done"


def test_it_runs_after_the_server_is_up():
    names = [t.get("name", "") for t in _tasks()]
    up = names.index("[pazny.paperclip Post] Verify Paperclip HTTP (with correct Host header)")
    assert names.index(_release()["name"]) > up, "startup recovery marks runs interrupted; release after it"


# ── test_paperclip_workspace_follows_its_branch ─────────────────────────────
# 2026-11-01: the HnedWeb oponent reviewed a hand clone never moved since 10-24.
# The role task's real shell runs against throwaway repos: behind moves to the
# tip, local changes are refused, a non-clone is refused. CEILING: file:// only.

FOLLOW_TASK = "[pazny.paperclip] A followed workspace sits at its branch's tip"


def _script(path: Path) -> str:
    tasks = yaml.safe_load(MAIN.read_text())
    t = next(t for t in tasks if t.get("name") == FOLLOW_TASK)
    env = jinja2.Environment()
    env.filters["quote"] = lambda s: "'" + str(s).replace("'", "'\\''") + "'"
    return env.from_string(t["ansible.builtin.shell"]).render(item={"name": "nos", "path": str(path), "follow": "dev"})


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                               "HOME": str(cwd)}).stdout.strip()


def _origin_and_clone(tmp: Path) -> tuple[Path, Path]:
    origin = tmp / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "dev")
    (origin / "f").write_text("1\n")
    _git(origin, "add", "f")
    _git(origin, "commit", "-qm", "one")
    clone = tmp / "clone"
    _git(tmp, "clone", "-q", "-b", "dev", str(origin), str(clone))
    (origin / "f").write_text("2\n")
    _git(origin, "commit", "-qam", "two")
    return origin, clone


def _run_follow(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", _script(path)], capture_output=True, text=True, timeout=60)


def test_a_clone_behind_moves_to_the_tip(tmp_path):
    origin, clone = _origin_and_clone(tmp_path)
    out = _run_follow(clone)
    assert out.returncode == 0, out.stderr
    assert "moved" in out.stdout and _git(clone, "rev-parse", "HEAD") == _git(origin, "rev-parse", "HEAD")
    assert "at " in _run_follow(clone).stdout, "a second converge at the tip must report no change"


def test_local_changes_are_refused_not_reset(tmp_path):
    _, clone = _origin_and_clone(tmp_path)
    (clone / "f").write_text("mine\n")
    out = _run_follow(clone)
    assert out.returncode != 0 and "local changes" in out.stderr
    assert (clone / "f").read_text() == "mine\n"


def test_a_folder_that_is_no_clone_is_refused(tmp_path):
    (tmp_path / "plain").mkdir()
    out = _run_follow(tmp_path / "plain")
    assert out.returncode != 0 and "no git clone" in out.stderr
