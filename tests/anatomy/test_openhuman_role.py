"""pazny.openhuman does the desktop recipe itself, and touches nothing it does not own.

2026-10-06: the operator refused a nine-step manual recipe per service. The role
now installs the cask as a SYMBIONT (once, only when absent), merges its keys
into config.toml (a foreign key survives), copies IMPRINT.md to AGENTS.md and
never writes the KEAP RW token. Runs the real role through Ansible in a temp
HOME on a sealed PATH; brew, docker and open are stubs that log their argv.

2026-10-06, first live launch: "login locally" made users/local-studio-local
with the vendor's cloud defaults while the role had written users/local only.
Every profile on disk, and the predicted one, now gets the declared keys, and
`--tags verify` fails on any profile left on the cloud route. The local session
itself is made by the bundle's own CLI (`OpenHuman core call`): credential, then
config, then onboarding — never while the app runs, never over an existing login.

2026-10-09, the twin: a role install left every opt-in tool on (no stored
enabled_tools, user_filter.rs "Empty list means all tools are enabled"), cron on,
and an in-app local re-login resets onboarding_completed (credential.rs). The
role stores the wizard's default tool list, declares [cron] enabled = false and
re-asserts onboarding on the next converge.
"""
import base64
import importlib.util
import json
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
# The wizard's completeAndExit default, getEnabledRustToolNames(getDefaultEnabledTools())
# (app/src/utils/toolDefinitions.ts at v0.64.10: every catalog entry with defaultEnabled: true).
WIZARD_TOOLS = ["shell", "git_operations", "file_read", "read_diff", "csv_export", "file_write", "update_memory_md",
                "image_info", "web_search_tool", "memory_store", "memory_recall", "memory_forget", "cron_add",
                "cron_list", "cron_remove", "cron_update", "cron_run", "cron_runs", "schedule"]
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
auto_save = true
embedding_provider = "cloud"
embedding_model = "embedding-v1"
embedding_dimensions = 1024
[memory_tree]
llm_extractor_model = "gemma3:4b"
llm_summariser_model = "gemma3:4b"
[[mcp_client.servers]]
name = "mine"
command = "/usr/local/bin/my-mcp"
"""


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _converge(tmp: Path, app_present: bool = False, config: str | None = None,
              caskroom: bool = False, profiles: dict[str, str] | None = None,
              verify_only: bool = False, ok: bool = True, cli: bool = False, running: bool = False,
              marker: str | None = None, app_state: dict[str, dict] | None = None,
              onboard_writes: str | None = None, extra: dict | None = None) -> tuple[Path, str, str]:
    home, stubs, brew = tmp / "home", tmp / "stubs", tmp / "brew"
    app = tmp / "Applications/OpenHuman.app"
    log = tmp / "calls.log"
    for d in (home, stubs, brew):
        d.mkdir(parents=True, exist_ok=True)
    log.touch()
    for name in ("brew", "docker", "open"):
        _exe(stubs / name, STUB.format(log=log))
    # ps answers from a file, so a real OpenHuman on the test host never decides the run.
    (tmp / "ps.txt").write_text(f"{app}/Contents/MacOS/OpenHuman\n" if running else "/sbin/launchd\n")
    _exe(stubs / "ps", f'#!/bin/sh\ncat "{tmp / "ps.txt"}"\n')
    if app_present or cli:
        app.mkdir(parents=True)
    if cli:
        body = STUB.format(log=log)
        if onboard_writes is not None:   # the vendor RPC saves the whole active profile
            (tmp / "onboard.toml").write_text(onboard_writes)
            cfg = home / f".openhuman/users/{marker}/config.toml"
            body = body.replace("exit 0", f'case "$*" in *config_set_onboarding_completed*) '
                                          f'cp "{tmp / "onboard.toml"}" "{cfg}";; esac\nexit 0')
        _exe(app / "Contents/MacOS/OpenHuman", body)
    if marker is not None:
        (home / ".openhuman").mkdir(parents=True, exist_ok=True)
        (home / ".openhuman/active_user.toml").write_text(f'user_id = "{marker}"\n')
    if caskroom:
        (brew / "Caskroom/openhuman").mkdir(parents=True)
    for name, text in (profiles or ({"local": config} if config is not None else {})).items():
        cfg = home / f".openhuman/users/{name}/config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(text)
    for name, state in (app_state or {}).items():   # <workspace>/state/app-state.json (app_state/ops/state_file.rs)
        f = home / f".openhuman/users/{name}/workspace/state/app-state.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(state))
    defaults = ni.default_config()
    casks = [dict(c, app=str(app)) for c in defaults["homebrew_symbiont_casks"]]
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": True, "gather_subset": ["!all", "min"],
             "vars": {"ansible_python_interpreter": sys.executable,
                      **{k: defaults[k] for k in KEYS}, "homebrew_symbiont_casks": casks,
                      "install_openhuman": True, "homebrew_prefix": str(brew), "docker_bin": str(stubs / "docker"),
                      "nos_main_checkout": str(REPO), "openhuman_source_dir": str(REPO), "openhuman_app": str(app),
                      "openhuman_hostname": HOSTNAME, **(extra or {})},
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
@pytest.mark.parametrize("caskroom", [False, True])
def test_an_existing_app_is_not_reinstalled(tmp_path, caskroom):
    _, calls, out = _converge(tmp_path, app_present=True, caskroom=caskroom)
    assert not calls.strip(), f"an installer ran although OpenHuman.app was there:\n{calls}"
    assert "PRESENT:" in out, "the run did not report which copy it found"


@needs_ansible
def test_a_brew_record_without_its_app_is_reinstalled(tmp_path):
    """The app dragged to the Trash leaves Caskroom/openhuman behind; reading
    that as installed skipped the session, the onboarding and the imprint, and
    verify said nothing (blank converge 2026-10-09)."""
    _, calls, _ = _converge(tmp_path, caskroom=True)
    assert calls.splitlines() == ["brew reinstall --cask openhuman"], f"expected one reinstall:\n{calls}"


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
    rendered = home / ".openhuman/users/local/config.toml"
    assert b"KEAP_AGENT_TOKEN_RW" not in rendered.read_bytes(), "config.toml names the RW token"
    assert "docker" not in calls, "the converge read a token; it must be read at spawn only"
    # [[mcp_client.servers]] is the static set the core reads at boot (mcp::host::static_registry).
    servers = {s["name"]: s for s in tomllib.loads(rendered.read_text())["mcp_client"]["servers"]}
    cmd = " ".join(servers["nos-tables"]["args"])
    assert "printenv KEAP_AGENT_TOKEN_RO" in cmd and str(REPO / "tools/mcp-tables-server.py") in cmd


def _declared(cfg: dict, small: str) -> list[str]:
    want = {"privacy.mode": "local_only", "observability.analytics_enabled": False,
            "observability.share_usage_data": False, "update.enabled": False, "gitbooks.enabled": False,
            "chat_provider": "ollama:" + small, "memory_provider": "ollama:" + small,
            "embeddings_provider": "ollama:nomic-embed-text", "learning_provider": "ollama:" + small,
            "memory.engine": "none", "memory.embedding_provider": "ollama", "memory.embedding_model": "nomic-embed-text",
            "memory.embedding_dimensions": 768}
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
        assert "nos-tables" in [s["name"] for s in cfg["mcp_client"]["servers"]], f"{name} has no nos-tables MCP"
    cloud = tomllib.loads((users / "u-cloud/config.toml").read_text())
    assert cloud["computer"] == {"decision_model": "jev"}
    assert [s["name"] for s in cloud["mcp_client"]["servers"]] == ["mine", "nos-tables"], "a foreign MCP server was dropped"
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


def _cli_calls(calls: str) -> list[tuple[str, dict]]:
    out = []
    for row in calls.splitlines():
        if row.startswith("OpenHuman "):
            m = re.fullmatch(r"OpenHuman core call --method (\S+) --params (.*)", row)
            assert m, f"not a `core call`: {row}"
            out.append((m.group(1), json.loads(m.group(2))))
    return out


def _b64(part: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


@needs_ansible
def test_the_local_session_is_made_by_the_vendor_cli_in_order(tmp_path):
    home, calls, _ = _converge(tmp_path, cli=True)
    got = _cli_calls(calls)
    assert [m for m, _ in got] == ["openhuman.auth_set_credential", "openhuman.app_state_update_local_state",
                                   "openhuman.config_set_onboarding_completed"], got
    cred, tasks, onboard = got[0][1], got[1][1]["onboardingTasks"], got[2][1]
    assert tasks["enabledTools"] == WIZARD_TOOLS, "not the wizard's default tool list"
    head, claims, sig = cred["token"].split(".")
    assert sig == "local" and _b64(head) == {"alg": "none", "typ": "JWT"}, "not localSession.ts's token shape"
    assert claims_ok(_b64(claims)), _b64(claims)
    assert cred["kind"] == "local" and cred["user"]["email"] == "local@openhuman.local"
    assert onboard == {"value": True}
    cfg = tomllib.loads((home / ".openhuman/users/local-studio-local/config.toml").read_text())
    assert cfg["privacy"]["mode"] == "local_only", "the session's profile did not get the declared keys"


def claims_ok(c: dict) -> bool:
    return c["sub"] == c["user_id"] == "local" and c["exp"] - c["iat"] == 31536000


@needs_ansible
def test_a_session_already_there_is_not_touched(tmp_path):
    _, calls, _ = _converge(tmp_path, cli=True, marker="local-studio-local",
                            profiles={"local-studio-local": "onboarding_completed = true\n"},
                            app_state={"local-studio-local": {"onboardingTasks": {"enabledTools": ["shell"]}}})
    assert not _cli_calls(calls), f"the CLI ran against an existing session:\n{calls}"
    _, calls, _ = _converge(tmp_path / "cloud", cli=True, marker="u-cloud", profiles={"u-cloud": VENDOR})
    assert not _cli_calls(calls), f"a cloud login was replaced by a local session:\n{calls}"


@needs_ansible
def test_nothing_is_written_while_the_app_runs(tmp_path):
    home, calls, out = _converge(tmp_path, cli=True, running=True, profiles={"local-studio-local": VENDOR})
    assert not _cli_calls(calls), f"the CLI ran while the app was running:\n{calls}"
    cfg = tomllib.loads((home / ".openhuman/users/local-studio-local/config.toml").read_text())
    assert cfg["privacy"]["mode"] == "standard", "config.toml was rewritten under a running app"
    assert "OpenHuman is running" in out


@needs_ansible
def test_a_local_relogin_reset_is_reasserted(tmp_path):
    # credential.rs (CredentialKind::Local) set onboarding_completed=false; the tool list survived.
    _, calls, _ = _converge(tmp_path, cli=True, marker="local-studio-local",
                            profiles={"local-studio-local": "onboarding_completed = false\n"},
                            app_state={"local-studio-local": {"onboardingTasks": {"enabledTools": ["shell"]}}})
    assert _cli_calls(calls) == [("openhuman.config_set_onboarding_completed", {"value": True})], calls


@needs_ansible
def test_a_session_without_a_tool_list_gets_the_wizard_one_and_keeps_its_tasks(tmp_path):
    _, calls, _ = _converge(tmp_path, cli=True, marker="local-studio-local",
                            profiles={"local-studio-local": "onboarding_completed = true\n"},
                            app_state={"local-studio-local": {"onboardingTasks": {
                                "accessibilityPermissionGranted": True, "connectedSources": ["gmail"]}}})
    got = _cli_calls(calls)
    assert [m for m, _ in got] == ["openhuman.app_state_update_local_state"], got
    tasks = got[0][1]["onboardingTasks"]
    assert tasks["enabledTools"] == WIZARD_TOOLS
    assert tasks["accessibilityPermissionGranted"] is True and tasks["connectedSources"] == ["gmail"], \
        "update_local_state replaces onboardingTasks whole; a stored task field was dropped"


@needs_ansible
def test_the_twin_is_quiet_cron_is_off_in_every_profile(tmp_path):
    home, _, _ = _converge(tmp_path, app_present=True, profiles={"u-cloud": VENDOR + "[cron]\nenabled = true\n"})
    for name in ("local", "local-studio-local", "u-cloud"):
        cfg = tomllib.loads((home / f".openhuman/users/{name}/config.toml").read_text())
        assert cfg.get("cron", {}).get("enabled") is False, f"{name}: cron left on (config/schema/cron.rs defaults it on)"


# OpenHuman 0.64.15 (2026-10-09) made [memory.conversations] and [memory.recall] real keys,
# default on; the role declared only auto_save, and verify went RED on a fresh install.
V0_64_15_MEMORY = "[memory]\nengine = \"tinyhumans\"\nauto_save = true\n[memory.conversations]\nenabled = true\n" \
                  "[memory.recall]\nenabled = true\nbudget_tokens = 1200\n"


@needs_ansible
def test_conversations_and_recall_are_declared_off(tmp_path):
    home, _, _ = _converge(tmp_path, app_present=True, profiles={"local": V0_64_15_MEMORY})
    mem = tomllib.loads((home / ".openhuman/users/local/config.toml").read_text())["memory"]
    assert mem["conversations"]["enabled"] is False and mem["recall"]["enabled"] is False, mem
    assert mem["recall"]["budget_tokens"] == 1200, "a vendor key beside the declared one was dropped"


@needs_ansible
def test_the_declared_keys_outlive_the_onboarding_rpc(tmp_path):
    """config_set_onboarding_completed saves the whole profile with the app's defaults;
    the merge ran before it, so the fresh install of 2026-10-09 kept auto_save on."""
    home, _, _ = _converge(tmp_path, cli=True, marker="local-studio-local",
                           profiles={"local-studio-local": "onboarding_completed = false\n"},
                           app_state={"local-studio-local": {"onboardingTasks": {"enabledTools": ["shell"]}}},
                           onboard_writes="onboarding_completed = true\n" + V0_64_15_MEMORY)
    cfg = tomllib.loads((home / ".openhuman/users/local-studio-local/config.toml").read_text())
    assert cfg["memory"]["engine"] == "none" and cfg["onboarding_completed"] is True, cfg


# OpenHuman v0.64.15 has no local memory: KEAP's hippocampus (v2.1.0) is the cortexdb engine.
HIPPO = {"install_keap": True, "keap_port": 8091, "keap_hippocampus_key_openhuman": "SECRET-K"}


@needs_ansible
def test_memory_is_bound_to_the_keap_hippocampus(tmp_path):
    home, calls, _ = _converge(tmp_path, cli=True, marker="local-studio-local",
                               profiles={"local-studio-local": "onboarding_completed = true\n"},
                               app_state={"local-studio-local": {"onboardingTasks": {"enabledTools": ["shell"]}}},
                               extra=HIPPO)
    raw = (home / ".openhuman/users/local-studio-local/config.toml").read_text()
    mem = tomllib.loads(raw)["memory"]
    assert mem["engine"] == "cortexdb", mem
    assert mem["engines"]["cortexdb"]["endpoint"] == "http://127.0.0.1:8091/hippocampus", mem
    assert mem["conversations"]["enabled"] is True and mem["recall"]["enabled"] is True, mem
    assert "SECRET-K" not in raw, "the key belongs in the keychain, not config.toml"
    bind = [ln for ln in calls.splitlines() if "openhuman.memory_engine_set" in ln]
    assert bind and "SECRET-K" in bind[0] and "/hippocampus" in bind[0], calls


@needs_ansible
def test_without_keap_memory_stays_off(tmp_path):
    home, calls, _ = _converge(tmp_path, cli=True, marker="local-studio-local",
                               profiles={"local-studio-local": "onboarding_completed = true\n"},
                               app_state={"local-studio-local": {"onboardingTasks": {"enabledTools": ["shell"]}}},
                               extra={"install_keap": False})
    mem = tomllib.loads((home / ".openhuman/users/local-studio-local/config.toml").read_text())["memory"]
    assert mem["engine"] == "none" and "memory_engine_set" not in calls, mem
