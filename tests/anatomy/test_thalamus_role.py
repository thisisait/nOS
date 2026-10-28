"""The thalamus on the host: one role builds it, one plist runs `thalamus serve`.

Increment 8 of the thalamus slice-1 definition. The role reuses the receptor's identity map and
never renders one of its own (operator ruling 1: one map, one renderer). The
proxy secret lives only in the 0600 plist env, never in ProgramArguments. The
reader tools/thalamus-status.py says OK only for what it read, UNKNOWN else.

Offline: the plist is rendered with jinja2, the reader is judged on fixtures.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import pathlib
import plistlib
import re
import socket
import subprocess
import sqlite3
import sys
import tempfile

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.thalamus"
READER = REPO / "tools" / "thalamus-status.py"


def _tasks() -> list[dict]:
    return [*yaml.safe_load((ROLE / "tasks" / "main.yml").read_text()), *yaml.safe_load((ROLE / "tasks" / "macos.yml").read_text())]  # macos.yml: the launchd flow


MEDULLA = REPO / "roles" / "pazny.medulla"
BUILD = "[pazny.medulla] build and install the medulla binary"


def _flow() -> list[dict]:
    """The launchd flow in run order, the pazny.medulla include expanded: the build lives there (row medulla-skeleton)."""
    out = []
    for t in _tasks():
        if t.get("ansible.builtin.include_role", {}).get("name") == "pazny.medulla":
            out += [*yaml.safe_load((MEDULLA / "tasks" / "main.yml").read_text()), *yaml.safe_load((MEDULLA / "tasks" / "macos.yml").read_text())]
        else:
            out.append(t)
    return out


def _plist(**over) -> dict:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    ctx = {"thalamus_launchd_label": "eu.thisisait.nos.thalamus", "thalamus_bin": "/h/thalamus/bin/thalamus", "thalamus_serve_bin": "/h/thalamus/bin/nos-thalamus",
           "thalamus_home": "/h/thalamus", "thalamus_log_dir": "/h/thalamus/log",
           "thalamus_data_dir": "/n/platform/services/thalamus/data", "nos_main_checkout": "/repo",
           "nos_tools_venv": "/h/.nos/tools-venv", "homebrew_prefix": "/opt/homebrew",
           "ansible_facts": {"env": {"HOME": "/h"}}, "keap_proxy_shared_secret": "s3cret", "keap_port": 8091,
           "ollama_enabled": True, "install_ollama": True, "ollama_model": "qwen3:14b", "ollama_small_model": "hermes3:8b",
           "authentik_rbac_tiers": _default_config()["authentik_rbac_tiers"], "thalamus_roadmap_table_id": "rt", **over}
    benv = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())["thalamus_binding_env"]
    ctx["thalamus_binding_env"] = {k: env.from_string(v).render(**ctx) for k, v in benv.items()}
    text = env.from_string((ROLE / "templates" / "thalamus.plist.j2").read_text()).render(**ctx)
    return plistlib.loads(text.encode())


def _default_config() -> dict:
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    return nos_identity.default_config()


def test_install_thalamus_defaults_false():
    assert _default_config()["install_thalamus"] is False


def test_the_plist_names_the_tier_one_groups_from_the_rbac_tiers():
    """serve answers approvals/red-status only to tier 1; the groups come from one list, not Rust."""
    tier1 = next(t for t in _default_config()["authentik_rbac_tiers"] if t["tier"] == 1)["groups"]
    assert _plist()["EnvironmentVariables"]["NOS_TIER1_GROUPS"] == ",".join(tier1)
    src = "".join(p.read_text() for p in (REPO / "files/anatomy/thalamus/thalamus/src").glob("*.rs"))
    assert not [g for g in tier1 if f'"{g}"' in src], "a tier-1 group name is hard-coded in Rust"


def test_the_plist_names_the_tier_two_groups_from_the_rbac_tiers():
    """propose_app is a manager's to ask (tier 2); the groups come from the same list, not Rust."""
    tier2 = next(t for t in _default_config()["authentik_rbac_tiers"] if t["tier"] == 2)["groups"]
    assert _plist()["EnvironmentVariables"]["NOS_TIER2_GROUPS"] == ",".join(tier2)
    src = "".join(p.read_text() for p in (REPO / "files/anatomy/thalamus/thalamus/src").glob("*.rs"))
    assert not [g for g in tier2 if f'"{g}"' in src], "a tier-2 group name is hard-coded in Rust"


def test_the_plist_runs_serve_and_keeps_the_secret_out_of_argv():
    p = _plist()
    assert p["ProgramArguments"] == ["/h/thalamus/bin/nos-thalamus", "serve",
                                     "--data-dir", "/n/platform/services/thalamus/data"]
    env = p["EnvironmentVariables"]
    assert env["KEAP_PROXY_SHARED_SECRET"] == "s3cret"
    assert env["KEAP_URL"] == "http://127.0.0.1:8091"
    assert env["NOS_REPO_ROOT"] == "/repo"
    assert env["NOS_ARMED_BACKENDS"] == "ollama" and env["NOS_LOCAL_MODEL"] == "qwen3:14b"
    assert "s3cret" not in " ".join(p["ProgramArguments"])
    assert _plist(ollama_enabled=False)["EnvironmentVariables"]["NOS_ARMED_BACKENDS"] == ""


def test_the_plist_carries_the_bound_backends_key_in_env_only():
    """Iris binds mistral-eu (ruling 2026-10-12): its key rides the 0600 plist env, read once by src/cli.rs."""
    p = _plist(mistral_enabled=True, mistral_model="mistral-large-latest",
               thalamus_model_secrets=["mistral_api_key"], thalamus_model_tokens={"mistral_api_key": "sk-eu-91c2"})
    env = p["EnvironmentVariables"]
    assert env["NOS_SECRET_MISTRAL_API_KEY"] == "sk-eu-91c2"
    assert env["NOS_MISTRAL_MODEL"] == "mistral-large-latest"
    assert env["NOS_ARMED_BACKENDS"].split() == ["mistral-eu", "ollama"]
    assert "sk-eu-91c2" not in " ".join(p["ProgramArguments"])
    keyless = _plist(thalamus_model_secrets=[], thalamus_model_tokens={})["EnvironmentVariables"]
    assert not [k for k in keyless if k.startswith("NOS_SECRET_")], "a keyless binding renders no key"


def test_the_role_renders_the_key_iris_binds_and_no_other():
    """The secret vars come from iris's armed rows (auth_secret nos:<var>), their values from those vars.

    Read in tasks (set_fact), not defaults: defaults stay lookup-free. The values' set_fact is no_log.
    """
    tasks = _tasks()
    holder = next(t for t in tasks if "thalamus_model_tokens" in (t.get("ansible.builtin.set_fact") or {}))
    assert holder.get("no_log") is True, "the key's set_fact logs its value"
    plist = tasks.index(next(t for t in tasks if "ansible.builtin.template" in t))
    assert tasks.index(holder) < plist, "the key is read after the plist renders"
    held = {"mistral_api_key": "sk-eu-91c2", "minimax_api_key": "sk-other"}
    assert _key_facts(**held, mistral_enabled=True) == (["mistral_api_key"], {"mistral_api_key": "sk-eu-91c2"})
    assert _key_facts(**held) == ([], {}), "an unarmed row's key stays out"


def _key_facts(**held) -> tuple[list, dict]:
    """The role's two set_facts (key vars, then their values) rendered as Ansible would, `held` = the vars."""
    tasks = _tasks()
    facts = {k: v for t in tasks for k, v in (t.get("ansible.builtin.set_fact") or {}).items()}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["from_yaml"] = yaml.safe_load
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1")
    env.globals["lookup"] = lambda kind, arg, default=None: (
        pathlib.Path(arg).read_text() if kind == "file" else held.get(arg, default))
    secrets = yaml.safe_load(env.from_string(facts["thalamus_model_secrets"]).render(nos_main_checkout=str(REPO)))
    tokens = yaml.safe_load(env.from_string(facts["thalamus_model_tokens"]).render(thalamus_model_secrets=secrets))
    return secrets, tokens


def test_each_armed_cloud_row_of_iris_brings_its_key_and_no_other():
    """Ruling 2026-10-17: anthropic-api and minimax-api join mistral-eu; a key rides only when its row is armed."""
    keys = {"mistral_api_key": "sk-eu", "anthropic_api_key": "sk-ant", "minimax_api_key": "sk-mm", "xai_api_key": "sk-x"}
    assert _key_facts(**keys) == ([], {}), "nothing armed, no key"
    armed = _key_facts(**keys, anthropic_api_enabled=True, minimax_api_enabled=True, xai_enabled=True)
    assert armed == (["anthropic_api_key", "minimax_api_key"], {"anthropic_api_key": "sk-ant", "minimax_api_key": "sk-mm"}), \
        "xai is armed but iris does not allow it: its key stays out"
    assert _key_facts(mistral_enabled=True)[1] == {"mistral_api_key": ""}, "armed and keyless renders empty; the binding refuses"
    p = _plist(anthropic_api_enabled=True, anthropic_api_model="claude-haiku-5-5", minimax_api_enabled=True,
               minimax_model="MiniMax-M2", thalamus_model_secrets=armed[0], thalamus_model_tokens=armed[1])
    env = p["EnvironmentVariables"]
    assert (env["NOS_SECRET_ANTHROPIC_API_KEY"], env["NOS_SECRET_MINIMAX_API_KEY"]) == ("sk-ant", "sk-mm")
    assert {"anthropic-api", "minimax-api"} <= set(env["NOS_ARMED_BACKENDS"].split())
    assert (env["NOS_ANTHROPIC_API_MODEL"], env["NOS_MINIMAX_MODEL"]) == ("claude-haiku-5-5", "MiniMax-M2")
    off = _plist()["EnvironmentVariables"]
    assert not {"anthropic-api", "minimax-api"} & set(off["NOS_ARMED_BACKENDS"].split()), "the flags default off"
    assert not [k for k in off if k.startswith("NOS_SECRET_")]


def test_the_key_never_reaches_a_log_or_the_preflight():
    """The plist render is no_log (--diff would print the key); the preflight's env holds no key."""
    render = next(t for t in _tasks() if "ansible.builtin.template" in t)
    assert render.get("no_log") is True, "the plist render would show the key under --diff"
    benv = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())["thalamus_binding_env"]
    assert not [k for k, v in benv.items() if k.startswith("NOS_SECRET_") or "thalamus_model_token" in v]
    pre = (ROLE / "tasks" / "llm-requirement.yml").read_text()
    assert "thalamus_model_token" not in pre and "_api_key" not in pre, "the preflight handles the key"


def test_the_plist_names_the_roadmap_table_keap_seeds():
    """serve maps the model's "roadmap" to this id; it must be the one pazny.keap creates.

    Ruling 2026-10-12: keap_roadmap_table_id is declared once in the default layers, so both
    roles read it as a plain var — no lookup('file') into another role, no second literal.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    declared = [p.name for p in nos_identity.default_layers()
                if "keap_roadmap_table_id" in (yaml.safe_load(p.read_text()) or {})]
    assert len(declared) == 1, f"keap_roadmap_table_id is declared in {declared or 'no default layer'}"
    keap = _default_config()["keap_roadmap_table_id"]
    defaults = (ROLE / "defaults" / "main.yml").read_text()
    assert yaml.safe_load(defaults)["thalamus_roadmap_table_id"] == "{{ keap_roadmap_table_id }}"
    assert "lookup(" not in defaults, "the thalamus reaches into another role's file"
    roles = [p for p in REPO.glob("roles/*/**/*") if p.is_file() and keap in p.read_text(errors="ignore")]
    assert not roles, f"a second literal of the id drifts: {roles}"
    assert _plist(thalamus_roadmap_table_id=keap)["EnvironmentVariables"]["NOS_ROADMAP_TABLE_ID"] == keap


def test_the_plist_is_0600_and_the_logs_and_data_0700():
    tasks = _tasks()
    plist = next(t for t in tasks if "plist" in t.get("name", "").lower() and "ansible.builtin.template" in t)
    assert plist["ansible.builtin.template"]["mode"] == "0600"
    dirs = next(t for t in tasks if "directories" in t.get("name", ""))
    modes = {i["path"]: i["mode"] for i in dirs["loop"]}
    assert modes["{{ thalamus_log_dir }}"] == "0700" and modes["{{ thalamus_data_dir }}"] == "0700", modes


def test_the_ledger_dir_derives_from_nos_data_root():
    """Operator ruling: the ledger is data, so it lives under nos_data_root like every service's.

    test_fs_doctrine_paths then holds its class prefix; the binary takes it from --data-dir only.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    cfg = nos_identity.default_config_text()
    assert 'thalamus_data_dir: "{{ nos_data_root }}/platform/services/thalamus/data"' in cfg
    for src in ("src/cli.rs", "src/ledger.rs", "src/serve.rs"):
        rs = (REPO / "files/anatomy/thalamus/thalamus" / src).read_text()
        assert "thalamus/data" not in rs, f"{src} hard-codes the ledger dir"
    assert "thalamus/data" not in READER.read_text(), "the reader guesses the ledger dir"


def test_the_role_renders_no_identity_map_of_its_own():
    """Ruling 1: the receptor role is the one renderer of ~/.nos/identity-map.yml."""
    writes = [str(t.get(m, {})) for t in _tasks() for m in
              ("ansible.builtin.template", "ansible.builtin.copy", "ansible.builtin.file", "ansible.builtin.lineinfile")]
    assert not [w for w in writes if "identity" in w], "only pazny.receptor renders the map"
    assert not list(ROLE.glob("templates/identity*"))


def test_the_role_refuses_a_receptor_map_the_binary_does_not_read():
    """serve.rs fixes ~/.nos/identity-map.yml; an overridden receptor_identity_map would refuse everyone."""
    asserts = [str(t["ansible.builtin.assert"]) for t in _tasks() if "ansible.builtin.assert" in t]
    assert any("receptor_identity_map" in a and ".nos/identity-map.yml" in a for a in asserts), asserts
    rs = (REPO / "files/anatomy/thalamus/thalamus/src/serve.rs").read_text()
    assert 'IDENTITY_MAP: &str = ".nos/identity-map.yml"' in rs


def test_the_build_is_locked_and_off_the_checkout():
    """--locked: the converge builds the Cargo.lock dependabot watches, not a fresh resolve."""
    build = next(t for t in _flow() if t.get("name", "").lower() == BUILD)
    sh = build["ansible.builtin.shell"]
    assert "--locked" in sh and "--release" in sh and "CARGO_TARGET_DIR" in sh, sh


def test_the_binary_keeps_one_signing_identity_across_builds():
    """macOS ties a removable-volume grant to the designated requirement. The linker's ad-hoc
    DR is the cdhash, so every rebuild re-asked (measured 2026-10-12). A self-signed identity
    in the login keychain makes the DR identifier + certificate: stable across builds."""
    tasks = _flow()
    names = [t.get("name", "").lower() for t in tasks]
    mint = next(t for t in tasks if "signing identity" in t.get("name", "").lower())
    sh = mint["ansible.builtin.shell"]
    assert "security find-certificate" in sh and sh.index("find-certificate") < sh.index("security import"), \
        "the identity is minted only when the keychain lacks it"
    assert "-T /usr/bin/codesign" in sh and "codeSigning" in sh, sh
    sign = next(t for t in tasks if "sign the binary" in t.get("name", "").lower())
    ssh = sign["ansible.builtin.shell"]
    assert "codesign -f -s" in ssh and "-s -" not in ssh, "ad-hoc (-s -) keeps the cdhash DR"
    assert "Restart thalamus" in str(sign.get("notify")), "a re-signed binary is a new process"
    install = names.index(BUILD)
    boot = next(i for i, n in enumerate(names) if "bootstrap launchd" in n)
    assert install < names.index(sign["name"].lower()) < boot, "sign after the build, before the job starts"


def _reader():
    spec = importlib.util.spec_from_file_location("thalamus_status", READER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_reader_judges_the_socket_by_kind_and_mode():
    r = _reader()
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        path = pathlib.Path(d) / "t.sock"
        assert r.judge_socket(path)["state"] == "RED"            # absent
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(path))
        os.chmod(path, 0o644)
        assert r.judge_socket(path)["state"] == "RED"
        os.chmod(path, 0o600)
        s.listen(1)
        assert r.judge_socket(path)["state"] == "OK"
        s.close()
        # A dead daemon leaves its 0600 socket behind; nobody answers it.
        assert r.judge_socket(path)["state"] == "RED", "a stale socket is not a serving daemon"
        path.unlink()
        path.write_text("x")
        assert r.judge_socket(path)["state"] == "RED"            # a file, not a socket


def test_the_reader_reads_the_ledger_or_says_unknown():
    r = _reader()
    with tempfile.TemporaryDirectory() as d:
        data = pathlib.Path(d)
        os.chmod(data, 0o700)
        db = data / "ledger.db"
        assert r.judge_ledger(db)[0]["state"] == "UNKNOWN"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, uuid TEXT, actor_id TEXT, status TEXT,"
                    " started_at TEXT, ended_at TEXT, stop_reason TEXT)")
        con.commit()
        lines = {x["check"]: x for x in r.judge_ledger(db)}
        assert lines["ledger"]["state"] == "OK" and "none yet" in lines["last session"]["detail"]
        con.execute("INSERT INTO sessions VALUES (1,'u1','user:abc','ended','2026-10-12T10:00:00Z',NULL,'end')")
        con.commit()
        con.close()
        assert "user:abc" in {x["check"]: x for x in r.judge_ledger(db)}["last session"]["detail"]
        os.chmod(data, 0o755)
        assert {x["check"]: x for x in r.judge_ledger(db)}["ledger"]["state"] == "RED"
        db.write_bytes(b"not a database")
        os.chmod(data, 0o700)
        assert r.judge_ledger(db)[0]["state"] == "UNKNOWN"


def test_a_daemon_serving_without_a_model_is_never_green():
    """serve keeps answering controls with no model; the reader must not call that whole."""
    r = _reader()
    with tempfile.TemporaryDirectory() as d:
        log = pathlib.Path(d) / "launchd.err.log"
        assert r.judge_model(log)["state"] == "UNKNOWN"                 # no log
        log.write_text("thalamus: model bound ollama-qwen3:14b\n200 as x GET /api/tables 3ms\n"
                       "thalamus: model UNBOUND: iris has no model: Disarmed(\"ollama\")\n")
        m = r.judge_model(log)
        assert m["state"] == "UNKNOWN" and "iris has no model" in m["detail"], m
        assert m["detail"].startswith("degraded"), m
        log.write_text(log.read_text() + "thalamus: model bound ollama-qwen3:14b\n")
        assert r.judge_model(log) == r.line("model", "OK", "bound ollama-qwen3:14b", str(log))
        log.write_text("200 as x GET /api/tables 3ms\n")
        assert r.judge_model(log)["state"] == "UNKNOWN", "a log with no start line says nothing"
    assert "judge_model(" in inspect.getsource(r.collect), "the reader never reports the model line"


def test_the_reader_finds_the_ledger_the_plist_serves():
    """The reader reads --data-dir from the deployed plist: the path the daemon opens, not a guess."""
    r = _reader()
    with tempfile.TemporaryDirectory() as d:
        plist = pathlib.Path(d) / "t.plist"
        assert r.ledger_path(plist)[0] is None                    # no plist: no ledger to read
        plist.write_bytes(plistlib.dumps({"ProgramArguments": ["/b/thalamus", "serve"]}))
        assert r.ledger_path(plist)[0] is None                    # no flag: no guess
        plist.write_bytes(plistlib.dumps(_plist()))
        assert r.ledger_path(plist)[0] == pathlib.Path("/n/platform/services/thalamus/data/ledger.db")
        plist.write_bytes(b"garbage")
        assert r.ledger_path(plist)[0] is None


def test_the_reader_says_unknown_when_launchd_cannot_be_asked():
    r = _reader()
    assert r.judge_launchd(None)["state"] == "UNKNOWN"
    assert r.judge_launchd((113, ""))["state"] == "RED"
    assert r.judge_launchd((0, "state = running\n\tpid = 42\n"))["state"] == "OK"
    # Loaded but crash-looping on KeepAlive: no pid is a dead daemon, not a green one.
    assert r.judge_launchd((0, "state = not running\n\tlast exit code = 1\n"))["state"] == "RED"


def _verify_rows(**states) -> str:
    checks = ["socket", "launchd", "model", "ledger", "last session"]
    return json.dumps([{"check": c, "state": states.get(c.replace(" ", "_"), "OK")} for c in checks])


def test_verify_warns_on_an_unbound_model_and_fails_on_anything_else():
    """Ruling 2026-10-12: serving without a model is visible, not green and not a failure."""
    env = jinja2.Environment()
    env.filters["from_json"] = json.loads
    env.filters["bool"] = bool
    tasks = [t for t in _tasks() if "verify" in (t.get("tags") or [])]
    verify = next(t for t in tasks if "ansible.builtin.shell" in t)
    warn = next((t for t in tasks if "ansible.builtin.fail" in t), None)
    assert warn and warn.get("ignore_errors") is True, "no warn task, or one that fails the run"

    def judged(expr: str, out: str) -> bool:
        reg = {"rc": 0, "stdout": out}
        return env.from_string("{{ (" + expr + ") | bool }}").render(_thalamus_verify=reg) == "True"

    unbound = _verify_rows(model="UNKNOWN")
    assert not judged(verify["failed_when"], unbound), "an unbound model failed verify"
    assert judged(warn["when"], unbound), "an unbound model passed silently"
    assert not judged(warn["when"], _verify_rows()), "a bound model warned"
    for bad in ({"socket": "RED"}, {"launchd": "UNKNOWN"}, {"ledger": "RED"}, {"last_session": "UNKNOWN"}):
        assert judged(verify["failed_when"], _verify_rows(model="UNKNOWN", **bad)), bad
    # The wait loop stops on the same rule, or an unbound model costs every run 10 s of polling.
    snippet = re.search(r"python3 -c '([^']+)'", verify["ansible.builtin.shell"])[1]
    assert subprocess.run([sys.executable, "-c", snippet], input=unbound, text=True).returncode == 0
    assert subprocess.run([sys.executable, "-c", snippet], input=_verify_rows(socket="RED"), text=True).returncode == 1


def test_the_decider_list_names_the_medulla_and_nos_app_on_macos():
    """Operator ruling 2026-10-28: `nos halt` goes through the medulla and nOS.app decides, so both are
    listed by default; the pupil and the terminal stay listed (they decided while the list was off).
    Linux stays empty: SO_PEERCRED fails a set list closed (src/serve.rs decider_refusal). The app is
    signed with the medulla's identity, so the decider it lists is the one the role installed."""
    from jinja2.nativetypes import NativeEnvironment
    env = NativeEnvironment(undefined=jinja2.StrictUndefined)
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
    ctx: dict = {"ansible_facts": {"env": {"HOME": "/h"}}}
    for k in ("thalamus_home", "thalamus_bin", "thalamus_pupil_app", "thalamus_pupil_exe", "thalamus_nos_app", "thalamus_nos_app_exe"):
        ctx[k] = env.from_string(defaults[k]).render(**ctx)
    mdef = yaml.safe_load((MEDULLA / "defaults" / "main.yml").read_text())
    ctx["medulla_bin_dir"] = env.from_string(mdef["medulla_bin_dir"]).render(**ctx)
    medulla_bin = env.from_string(mdef["medulla_bin"]).render(**ctx)
    assert ctx["thalamus_nos_app_exe"] == "/h/Applications/nOS.app/Contents/MacOS/nOS"
    raw = defaults["thalamus_decider_exes"]
    assert env.from_string(raw).render(**ctx, nos_service_manager="systemd") == []
    exes = env.from_string(raw).render(**ctx, nos_service_manager="launchd")
    assert exes == [ctx["thalamus_pupil_exe"], ctx["thalamus_bin"], medulla_bin, ctx["thalamus_nos_app_exe"]]
    assert _plist(thalamus_decider_exes=exes)["EnvironmentVariables"]["NOS_DECIDER_EXES"] == ":".join(exes)
    assert "NOS_DECIDER_EXES" not in _plist(thalamus_decider_exes=[])["EnvironmentVariables"]
    main = (REPO / "files/anatomy/thalamus/thalamus/src/cli.rs").read_text()
    assert '"NOS_DECIDER_EXES"' in main, "serve does not read the list the plist renders"
    # The app is built, installed at thalamus_nos_app and signed after the identity exists, with it.
    flow = [t.get("name", "") for t in yaml.safe_load((MEDULLA / "tasks" / "macos.yml").read_text())]
    imp = [i for i, t in enumerate(yaml.safe_load((MEDULLA / "tasks" / "macos.yml").read_text()))
           if t.get("ansible.builtin.import_tasks") == "app.yml"]
    ident = next(i for i, n in enumerate(flow) if "code-signing identity" in n)
    assert imp and imp[0] > ident, "app.yml is not imported after the signing identity"
    sign = next(t for t in yaml.safe_load((MEDULLA / "tasks" / "app.yml").read_text()) if "codesign -f" in str(t))
    sh = sign["ansible.builtin.shell"]
    assert "_thalamus_signing.stdout_lines[-1]" in sh and "eu.thisisait.nos.app" in sh and "thalamus_nos_app" in sh


def test_a_decider_list_that_admits_nobody_is_refused_at_render():
    """Row thalamus-decider-guard-followups: a string joins its characters, an empty or relative
    entry and a missing file each admit nobody; the role refuses them, before the plist and after
    the pupil is built, rather than serve a guard that silently refuses every decision."""
    env = jinja2.Environment()
    env.tests["match"] = lambda v, pat: re.match(pat, v) is not None
    tasks = _tasks()
    names = [t.get("name", "") for t in tasks]
    shape = next(t for t in tasks if t.get("name", "").endswith("is a list of absolute paths"))
    exists = next(t for t in tasks if t.get("name", "").endswith("A decider that names no file is refused"))
    assert names.index(shape["name"]) < names.index("[pazny.thalamus] Render launchd plist")
    pupil = next(i for i, t in enumerate(tasks) if t.get("ansible.builtin.import_tasks") == "pupil.yml")
    assert pupil < names.index(exists["name"]), "the existence check runs before the pupil is built"

    def ok(that, **ctx) -> bool:
        that = that if isinstance(that, list) else [that]
        return all(env.from_string("{{ (" + e + ") }}").render(**ctx) == "True" for e in that)

    good = ["/h/thalamus/bin/nos-pupil", "/h/thalamus/bin/thalamus"]
    assert ok(shape["ansible.builtin.assert"]["that"], thalamus_decider_exes=[])
    assert ok(shape["ansible.builtin.assert"]["that"], thalamus_decider_exes=good)
    for bad in ("/h/thalamus/bin/nos-pupil", ["/h/x", ""], ["rel/exe"], ["/a:/b"], [7], {"/h/x": 1}):
        assert not ok(shape["ansible.builtin.assert"]["that"], thalamus_decider_exes=bad), bad
    reg = lambda *e: {"results": [{"item": p, "stat": {"exists": x}} for p, x in e]}
    assert ok(exists["ansible.builtin.assert"]["that"], _thalamus_deciders=reg())
    assert ok(exists["ansible.builtin.assert"]["that"], _thalamus_deciders=reg((good[0], True)))
    assert not ok(exists["ansible.builtin.assert"]["that"], _thalamus_deciders=reg((good[0], True), (good[1], False)))


def test_the_cell_backend_choice_rides_the_binding_env():
    """iris_backend (default.config.yml; ollama while llm_on_host, "" = the cell's own) reaches serve and the preflight."""
    assert "llm_on_host" in _default_config()["iris_backend"]
    assert _plist(iris_backend="ollama")["EnvironmentVariables"]["NOS_CELL_BACKEND"] == "ollama"
    assert _plist(iris_backend="")["EnvironmentVariables"]["NOS_CELL_BACKEND"] == ""


def test_a_host_without_rustup_gets_a_toolchain_before_the_build():
    """Live 2026-10-14, a fresh client: ~/.cargo/bin/cargo did not exist (rustup never installed), so the
    build died with 'No such file or directory'. The role finds cargo or installs Homebrew's rust first."""
    tasks = _flow()
    names = [t.get("name", "").lower() for t in tasks]
    find = next(i for i, n in enumerate(names) if "find a rust toolchain" in n)
    brew = next(i for i, n in enumerate(names) if "install homebrew's rust" in n)
    build = names.index(BUILD)
    assert find < brew < build, (find, brew, build)
    t = tasks[brew]
    mod = t.get("community.general.homebrew") or t.get("homebrew")
    assert mod and mod["name"] in ("rust", ["rust"]) and mod.get("state", "present") == "present", t
    assert "_thalamus_cargo_stat" in str(t["when"]), "brew installs rust only when cargo is missing"
    fact = next(x for x in tasks if "use homebrew's cargo" in x.get("name", "").lower())
    assert fact["ansible.builtin.set_fact"]["thalamus_cargo"] == "{{ homebrew_prefix }}/bin/cargo"


def _run_sign(tmp, task_yml, ctx):
    """A sign task on a stub codesign that cannot reach the key, as over SSH (errSecInternalComponent)."""
    import os
    import shlex
    import subprocess
    bin_ = tmp / "stub"
    bin_.mkdir()
    (bin_ / "codesign").write_text("#!/bin/bash\n[ \"$1\" = -d ] && exit 0\n"
                                   "echo \"$3: errSecInternalComponent\" >&2; exit 1\n")
    (bin_ / "codesign").chmod(0o755)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["quote"] = shlex.quote
    sh = env.from_string(task_yml["ansible.builtin.shell"]).render(**ctx)
    return subprocess.run(["/bin/bash", "-c", sh], capture_output=True, text=True,
                          env={**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"})


def test_a_sign_that_cannot_reach_the_key_says_the_one_command(tmp_path):
    """Live 2026-10-14 on a client over SSH: codesign answered errSecInternalComponent — the key's partition
    list never allowed codesign without the GUI prompt SSH cannot show. The task names the fix."""
    tasks = _flow()
    t = next(x for x in tasks if "sign the binary with it" in x.get("name", "").lower())
    ctx = {"_thalamus_signing": {"stdout_lines": ["ABCDEF0123"]}, "medulla_bin": str(tmp_path / "medulla"),
           "thalamus_launchd_label": "eu.thisisait.nos.thalamus", "thalamus_signing_keychain": "/k/login.keychain-db"}
    r = _run_sign(tmp_path, t, ctx)
    assert r.returncode != 0
    assert "security set-key-partition-list -S apple-tool:,apple:,codesign: -s /k/login.keychain-db" in r.stderr, r.stderr
    pupil = yaml.safe_load((ROLE / "tasks" / "pupil.yml").read_text())
    p = next(x for x in pupil if "sign the pupil" in x.get("name", "").lower())
    (tmp_path / "p").mkdir()
    r = _run_sign(tmp_path / "p", p, {**ctx, "thalamus_pupil_app": str(tmp_path / "Iris.app"),
                                      "thalamus_pupil_identifier": "eu.thisisait.nos.pupil"})
    assert r.returncode != 0 and "set-key-partition-list" in r.stderr, r.stderr


def test_the_local_seed_is_a_config_knob_unset_by_default():
    # Deterministic evals pin the sampler; a host that never benches keeps Ollama's own.
    assert _default_config()["iris_local_seed"] == ""
    assert _plist(iris_local_seed="")["EnvironmentVariables"]["NOS_LOCAL_SEED"] == ""
    assert _plist(iris_local_seed=42)["EnvironmentVariables"]["NOS_LOCAL_SEED"] == "42"


def test_the_local_temperature_is_a_config_knob_in_the_plist():
    assert _default_config()["iris_local_temperature"] == 0.3
    assert _plist(iris_local_temperature=0.1)["EnvironmentVariables"]["NOS_LOCAL_TEMPERATURE"] == "0.1"


# --- row thalamus-web-relay: the optic nerve, the face's loopback door into serve ---

def test_the_relay_door_is_rendered_only_beside_the_face():
    """Empty secret = no listener (src/cli.rs): a host without the face renders no secret and no port."""
    for face in (False, True):
        p = _plist(install_face=face, thalamus_relay_secret="relay-s3cret", thalamus_relay_port=8097)
        env = p["EnvironmentVariables"]
        assert "relay-s3cret" not in " ".join(p["ProgramArguments"])
        if face:
            assert env["THALAMUS_RELAY_SECRET"] == "relay-s3cret" and env["THALAMUS_RELAY_PORT"] == "8097"
        else:
            assert "THALAMUS_RELAY_SECRET" not in env and "THALAMUS_RELAY_PORT" not in env, env
    main = (REPO / "files/anatomy/thalamus/thalamus/src/cli.rs").read_text()
    assert 'remove_var("THALAMUS_RELAY_SECRET")' in main, "serve does not drop the secret it read"


def test_the_relay_secret_is_derived_and_its_port_is_nobody_elses():
    creds = yaml.safe_load((REPO / "default.credentials.yml").read_text())
    assert creds["thalamus_relay_secret"] == "{{ nos_derived_secrets.thalamus_relay }}"
    registry = yaml.safe_load((REPO / "files/anatomy/secrets/registry.yml").read_text())["credentials"]
    assert registry["thalamus_relay"] == {"service": "thalamus", "purpose": "relay-secret"}
    cfg = _default_config()
    port = cfg["thalamus_relay_port"]
    assert isinstance(port, int) and 1024 < port < 65536
    ports = {k: v for k, v in cfg.items() if k.endswith("_port") and k != "thalamus_relay_port"}
    for d in REPO.glob("roles/*/defaults/main.yml"):
        ports.update({f"{d.parts[-3]}:{k}": v for k, v in (yaml.safe_load(d.read_text()) or {}).items() if k.endswith("_port")})
    assert port not in ports.values(), [k for k, v in ports.items() if v == port]


def _face_env(**over) -> dict:
    from test_docker_sock_only_behind_proxy import _env, _vars
    text = (REPO / "roles/pazny.face/templates/compose.yml.j2").read_text()
    doc = yaml.safe_load(_env().from_string(text).render(**{**_vars("Darwin"), **over}))
    return doc["services"]["face"]["environment"]


def test_the_face_gets_the_relay_address_and_secret_only_with_the_thalamus():
    on = _face_env(install_thalamus=True, thalamus_relay_secret="relay-s3cret", thalamus_relay_port=8097)
    assert on["THALAMUS_RELAY_SECRET"] == "relay-s3cret"
    assert on["NOS_THALAMUS_RELAY_ADDR"] == "host.docker.internal:8097"
    off = _face_env(install_thalamus=False, thalamus_relay_secret="relay-s3cret", thalamus_relay_port=8097)
    assert "relay-s3cret" not in json.dumps(off) and "NOS_THALAMUS_RELAY_ADDR" not in off, off


def test_the_reader_says_the_relay_is_bound_exactly_when_the_secret_is_set():
    r = _reader()
    with tempfile.TemporaryDirectory() as d:
        log, plist = pathlib.Path(d) / "launchd.err.log", pathlib.Path(d) / "t.plist"
        assert r.judge_relay(log, plist)["state"] == "UNKNOWN"                   # nothing to read
        plist.write_bytes(plistlib.dumps(_plist(install_face=False)))
        assert r.judge_relay(log, plist)["state"] == "UNKNOWN"                   # no start line
        log.write_text("thalamus: relay closed (no THALAMUS_RELAY_SECRET)\n")
        assert r.judge_relay(log, plist)["state"] == "OK"
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            log.write_text(f"thalamus: relay bound 127.0.0.1:{port}\n")
            assert r.judge_relay(log, plist)["state"] == "RED", "bound with no secret in the plist"
            plist.write_bytes(plistlib.dumps(_plist(install_face=True, thalamus_relay_secret="relay-s3cret",
                                                    thalamus_relay_port=port)))
            got = r.judge_relay(log, plist)
            assert got["state"] == "OK" and "relay-s3cret" not in json.dumps(got), got
        assert r.judge_relay(log, plist)["state"] == "RED", "nobody accepts on the bound port"
        log.write_text("thalamus: relay closed (no THALAMUS_RELAY_SECRET)\n")
        assert r.judge_relay(log, plist)["state"] == "RED", "a set secret and a closed door"
        log.write_text("thalamus: relay FAILED 127.0.0.1:1: Address already in use\n")
        assert r.judge_relay(log, plist)["state"] == "RED"
    assert "judge_relay(" in inspect.getsource(r.collect), "the reader never reports the relay line"
