"""pazny.openhuman does the desktop recipe itself, and touches nothing it does not own.

2026-10-06: the operator refused a nine-step manual recipe per service. The role
now installs the cask as a SYMBIONT (once, only when absent), merges its keys
into config.toml (a foreign key survives), copies IMPRINT.md to AGENTS.md and
never writes the KEAP RW token. Runs the real role through Ansible in a temp
HOME on a sealed PATH; brew, docker and open are stubs that log their argv.

2026-10-06, first live launch: "login locally" made users/local-studio-local
with the vendor's cloud defaults while the role had written users/local only.
Every profile on disk, and the predicted one, now gets the declared keys, and
`--tags verify` fails on any profile left on the cloud route.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the role through real Ansible")
STUB = '#!/bin/sh\necho "$(basename "$0") $*" >> "{log}"\nexit 0\n'
RW_USE = re.compile(rb"KEAP_AGENT_TOKEN_RW\s*[=:]|printenv\s+KEAP_AGENT_TOKEN_RW")
KEYS = ("homebrew_symbiont_casks", "ollama_small_model", "keap_port", "openhuman_provider",
        "openhuman_model", "openhuman_register_mcp", "openhuman_skills")
HOSTNAME = "Studio.local"   # the core's local_session_user_id() -> "local-studio-local"
# What "login locally" wrote on 2026-10-06 (v0.64.10 defaults), trimmed to the keys that matter.
VENDOR = """default_model = "reasoning-v1"
memory_provider = "cloud"
embeddings_provider = "cloud"
learning_provider = "cloud"
[computer]
decision_model = "jev"
[privacy]
mode = "standard"
[observability]
analytics_enabled = true
share_usage_data = true
[update]
enabled = true
rpc_mutations_enabled = true
[gitbooks]
enabled = true
[memory]
backend = "sqlite"
embedding_provider = "cloud"
embedding_model = "embedding-v1"
embedding_dimensions = 1024
[memory_tree]
llm_extractor_model = "gemma3:4b"
llm_summariser_model = "gemma3:4b"
"""


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _converge(tmp: Path, app_present: bool = False, config: str | None = None,
              caskroom: bool = False, profiles: dict[str, str] | None = None,
              verify_only: bool = False, ok: bool = True) -> tuple[Path, str, str]:
    home, stubs, brew = tmp / "home", tmp / "stubs", tmp / "brew"
    app = tmp / "Applications/OpenHuman.app"
    log = tmp / "calls.log"
    for d in (home, stubs, brew):
        d.mkdir(parents=True, exist_ok=True)
    log.touch()
    for name in ("brew", "docker", "open"):
        _exe(stubs / name, STUB.format(log=log))
    if app_present:
        app.mkdir(parents=True)
    if caskroom:
        (brew / "Caskroom/openhuman").mkdir(parents=True)
    for name, text in (profiles or ({"local": config} if config is not None else {})).items():
        cfg = home / f".openhuman/users/{name}/config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(text)
    defaults = ni.default_config()
    casks = [dict(c, app=str(app)) for c in defaults["homebrew_symbiont_casks"]]
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True, "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable,
                      **{k: defaults[k] for k in KEYS}, "homebrew_symbiont_casks": casks,
                      "install_openhuman": True, "homebrew_prefix": str(brew), "docker_bin": str(stubs / "docker"),
                      "nos_main_checkout": str(REPO), "openhuman_source_dir": str(REPO), "openhuman_app": str(app),
                      "openhuman_hostname": HOSTNAME},
             "tasks": [{"include_role": {"name": "pazny.openhuman"}, "tags": ["verify"] if verify_only else []}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play))
    path = f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin"
    env = {**os.environ, "HOME": str(home), "PATH": path, "ANSIBLE_LOCAL_TEMP": str(tmp / ".ansible"),
           "ANSIBLE_ROLES_PATH": str(REPO / "roles")}
    tags = ["--tags", "verify"] if verify_only else ["--skip-tags", "verify"]
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", *tags,
                        str(tmp / "play.yml")], capture_output=True, text=True, cwd=tmp, env=env, timeout=300)
    assert (r.returncode == 0) == ok, r.stdout[-3000:] + r.stderr[-1000:]
    return home, log.read_text(), r.stdout


@needs_ansible
@pytest.mark.parametrize("where", ["app", "caskroom"])
def test_an_existing_app_is_not_reinstalled(tmp_path, where):
    _, calls, out = _converge(tmp_path, app_present=where == "app", caskroom=where == "caskroom")
    assert not calls.strip(), f"an installer ran although OpenHuman.app was there:\n{calls}"
    assert "PRESENT:" in out, "the run did not report which copy it found"


@needs_ansible
def test_an_absent_app_is_installed_once(tmp_path):
    _, calls, _ = _converge(tmp_path)
    assert calls.splitlines() == ["brew install --cask openhuman"], f"expected one cask install:\n{calls}"


@needs_ansible
def test_config_keeps_foreign_keys_and_gets_the_declared_ones(tmp_path):
    home, _, _ = _converge(tmp_path, app_present=True,
                           config='schema_version = 7\n[privacy]\nmode = "standard"\n[ui]\ntheme = "dark"\n')
    cfg = tomllib.loads((home / ".openhuman/users/local/config.toml").read_text())
    assert cfg["schema_version"] == 7 and cfg["ui"] == {"theme": "dark"}, f"a foreign key was dropped: {cfg}"
    assert cfg["privacy"]["mode"] == "local_only", "the declared privacy mode did not win"
    assert cfg["chat_provider"] == "ollama:" + ni.default_config()["ollama_small_model"]
    assert cfg["observability"] == {"analytics_enabled": False, "share_usage_data": False}


@needs_ansible
def test_agents_md_is_the_imprint_and_no_rw_token_is_written(tmp_path):
    home, calls, _ = _converge(tmp_path, app_present=True)
    head, body = (home / ".openhuman/users/local/workspace/AGENTS.md").read_text().split("\n", 1)
    assert head.startswith("<!-- nOS:") and body == (REPO / "IMPRINT.md").read_text(), "AGENTS.md is not IMPRINT.md"
    assert (home / ".openhuman/skills/nos-datatables/SKILL.md").is_file(), "the skill was not copied"
    assert not (home / ".openhuman/skills/nos-datatables").is_symlink()
    # The copied skill names the RW token in prose; nothing may read or assign it.
    leaks = [str(p) for p in home.rglob("*") if p.is_file() and RW_USE.search(p.read_bytes())]
    assert not leaks, f"the RW token is read or assigned: {leaks}"
    rendered = [home / ".openhuman/users/local" / n for n in ("config.toml", "nos-mcp.json")]
    assert not [p for p in rendered if b"KEAP_AGENT_TOKEN_RW" in p.read_bytes()], "a rendered file names the RW token"
    assert "docker" not in calls, "the converge read a token; it must be read at spawn only"
    mcp = (home / ".openhuman/users/local/nos-mcp.json").read_text()
    assert "printenv KEAP_AGENT_TOKEN_RO" in mcp and str(REPO / "tools/mcp-tables-server.py") in mcp


def _declared(cfg: dict, small: str) -> list[str]:
    want = {"privacy.mode": "local_only", "observability.analytics_enabled": False,
            "observability.share_usage_data": False, "update.enabled": False, "gitbooks.enabled": False,
            "chat_provider": "ollama:" + small, "memory_provider": "ollama:" + small,
            "embeddings_provider": "ollama:nomic-embed-text", "learning_provider": "ollama:" + small,
            "memory.embedding_provider": "ollama", "memory.embedding_model": "nomic-embed-text",
            "memory.embedding_dimensions": 768, "memory_tree.llm_extractor_model": small,
            "memory_tree.llm_summariser_model": small}
    bad = []
    for dotted, val in want.items():
        cur = cfg
        for part in dotted.split("."):
            cur = cur.get(part, {}) if isinstance(cur, dict) else {}
        if cur != val:
            bad.append(f"{dotted}={cur!r}")
    return bad


@needs_ansible
def test_every_profile_and_the_predicted_one_get_the_declared_keys(tmp_path):
    home, _, _ = _converge(tmp_path, app_present=True,
                           profiles={"local": 'schema_version = 7\n[ui]\ntheme = "dark"\n', "u-cloud": VENDOR})
    users = home / ".openhuman/users"
    assert sorted(p.name for p in users.iterdir()) == ["local", "local-studio-local", "u-cloud"], \
        "the profile 'login locally' will create (local-<hostname slug>) was not pre-created"
    small = ni.default_config()["ollama_small_model"]
    for name in ("local", "local-studio-local", "u-cloud"):
        cfg = tomllib.loads((users / name / "config.toml").read_text())
        assert not _declared(cfg, small), f"{name} kept a vendor value: {_declared(cfg, small)}"
        head = (users / name / "workspace/AGENTS.md").read_text().split("\n", 1)[0]
        assert head.startswith("<!-- nOS:"), f"{name} has no AGENTS.md"
        assert b"KEAP_AGENT_TOKEN_RW" not in (users / name / "nos-mcp.json").read_bytes()
    assert tomllib.loads((users / "u-cloud/config.toml").read_text())["computer"] == {"decision_model": "jev"}
    assert tomllib.loads((users / "local/config.toml").read_text())["ui"] == {"theme": "dark"}
    leaks = [str(p) for p in home.rglob("*") if p.is_file() and RW_USE.search(p.read_bytes())]
    assert not leaks, f"the RW token is read or assigned: {leaks}"


@needs_ansible
def test_verify_fails_on_a_profile_left_on_the_cloud_route(tmp_path):
    (tmp_path / "good").mkdir()
    home, _, _ = _converge(tmp_path / "good", app_present=True)
    local = (home / ".openhuman/users/local/config.toml").read_text()
    _, _, out = _converge(tmp_path / "bad", app_present=True, verify_only=True, ok=False,
                          profiles={"local": local, "local-studio-local": VENDOR})
    assert "[local-studio-local] mode=standard" in out, "verify failed, but not on the cloud profile:\n" + out[-3000:]
