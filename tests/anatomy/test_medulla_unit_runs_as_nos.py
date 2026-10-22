"""On Linux the medulla runs as the `nos` system user, never as the operator (ssot/doctrine/medulla.md §2).

nos_system_user (default.config.yml, the operator's key): "" keeps today's systemd --user unit;
"nos" makes pazny.linux.users create a nologin system account (kind service, realms [unix],
no tier group, never docker) and pazny.medulla run thalamus serve as a system unit under it.

MEASURED 2026-10-22, every path `thalamus serve` reads (files/anatomy/thalamus/thalamus/src):
- $HOME: serve.rs IDENTITY_MAP .nos/identity-map.yml -> HOME=/var/lib/nos, copied at converge;
  the socket is THALAMUS_SOCKET=/run/nos/thalamus.sock (RuntimeDirectory=nos), never ~/.nos.
- NOS_REPO_ROOT=/var/lib/nos/genome: binding.rs files/anatomy/agents/iris/agent.yml and
  state/habitat/llm-backends.yml; serve.rs IMPRINT.md, IMPRINT.short.md, state/keap-tables/,
  state/cortex-lang.gbnf, state/app-scaffolds.yml — each copied root:nos 0640
  (test_every_path_serve_reads_is_copied_to_the_genome scans the source for repo.join).
- the ledger: --data-dir /var/lib/nos/thalamus (ReadWritePaths).
CEILING: with nos_system_user set, nos cannot read ~/wing/app/data/wing.db or ~/.nos (ProtectHome).
serve.rs reader() runs repo tools/*.py that read them, and propose_app needs apps/, roles/,
state/manifest.yml and files/anatomy's parser — none copied. The metrics route, any
Wing-db-reading thread and propose_app stay off on such a host until Wing's data moves under
/var/lib/nos (a later row). The ledger starts empty under /var/lib/nos/thalamus. Offline: templates render to tmp, tasks are parsed, readers get fixtures.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import types

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
UNIT = REPO / "roles/pazny.medulla/templates/nos-medulla.service.j2"
ENV = REPO / "roles/pazny.thalamus/templates/thalamus.env.j2"
MEDULLA_LINUX = REPO / "roles/pazny.medulla/tasks/linux.yml"
USERS = REPO / "roles/pazny.linux.users/tasks/main.yml"
THALAMUS_LINUX = REPO / "roles/pazny.thalamus/tasks/linux.yml"
SRC = REPO / "files/anatomy/thalamus/thalamus/src"
HOME = "/home/op"           # the operator's home: no line of the system unit or env may name it
CHECKOUT = HOME + "/nOS"    # nos_main_checkout
#: serve.rs reader() (tools/*.py) and propose_app (taken_names + app_parser): see the docstring.
CEILING = {"tools", "files/anatomy", "apps", "roles", "state/manifest.yml"}

sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402


def _walk(tasks):
    for t in tasks or []:
        if isinstance(t, dict):
            yield t
            yield from _walk(t.get("block"))


def _tasks(path: pathlib.Path) -> list[dict]:
    return list(_walk(yaml.safe_load(path.read_text()))) if path.is_file() else []


def _env():
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    env.filters["bool"] = bool   # Ansible's; the binding env and the face branch use it
    return env


def _ctx(system_user: str) -> dict:
    cfg = nos_identity.default_config()
    ctx = {"nos_system_user": system_user, "nos_system_home": "/var/lib/nos",
           "ansible_facts": {"env": {"HOME": HOME}}, "ansible_managed": "managed",
           "nos_main_checkout": CHECKOUT, "nos_tools_venv": HOME + "/.nos/tools-venv",
           "keap_proxy_shared_secret": "s3cret", "authentik_rbac_tiers": cfg["authentik_rbac_tiers"],
           "thalamus_roadmap_table_id": "rt", "thalamus_relay_port": cfg["thalamus_relay_port"]}
    defaults = yaml.safe_load((REPO / "roles/pazny.thalamus/defaults/main.yml").read_text())
    for k in ("thalamus_launchd_label", "thalamus_unit_name", "thalamus_shared_socket_dir", "thalamus_decider_exes",
              "thalamus_env_home", "thalamus_repo_root", "thalamus_env_path", "thalamus_shared_socket"):
        if k in defaults:
            v = defaults[k]
            ctx[k] = _env().from_string(v).render(**ctx) if isinstance(v, str) else v
    ctx["thalamus_binding_env"] = {k: _env().from_string(v).render(**ctx)
                                   for k, v in defaults["thalamus_binding_env"].items()}
    return ctx


def _render(path: pathlib.Path, system_user: str = "nos") -> str:
    return _env().from_string(path.read_text()).render(**_ctx(system_user))


def _unit() -> dict[str, list[str]]:
    assert UNIT.is_file(), f"no {UNIT.relative_to(REPO)} renders User=nos (exists: {UNIT.exists()})"
    out: dict[str, list[str]] = {}
    for line in _render(UNIT).splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def test_the_unit_runs_as_nos_confined_to_its_home():
    u = _unit()
    assert u.get("User") == ["nos"] and u.get("Group") == ["nos"], u
    assert "SupplementaryGroups" not in u, "nos joins no group: not a tier group, never docker"
    assert "docker" not in _render(UNIT), "nos is never in the docker group"
    assert u.get("ProtectSystem") == ["strict"] and u.get("ProtectHome") == ["yes"], u
    assert u.get("NoNewPrivileges") == ["yes"], u
    assert u.get("EnvironmentFile") == ["/etc/nos/medulla.env"], u
    exec_start = u["ExecStart"][0].split()
    assert exec_start[0].startswith("/usr/local/libexec/"), "ProtectHome hides ~/thalamus/bin"
    assert exec_start[1:4] == ["thalamus", "serve", "--data-dir"] and exec_start[4].startswith("/var/lib/nos/"), exec_start
    assert u.get("RuntimeDirectory") == ["nos"], "the shared socket dir /run/nos belongs to nos"
    assert u.get("WantedBy") == ["multi-user.target"], u


def test_no_line_of_the_unit_or_env_names_the_operators_home():
    assert UNIT.is_file(), f"no {UNIT.relative_to(REPO)} renders User=nos (exists: {UNIT.exists()})"
    env = _render(ENV)
    for text in (_render(UNIT), env):
        bad = [line for line in text.splitlines() if HOME in line or CHECKOUT in line]
        assert not bad, f"the system unit or env names $HOME / nos_main_checkout: {bad}"
    assert "HOME=/var/lib/nos\n" in env and "NOS_REPO_ROOT=/var/lib/nos/genome\n" in env, env
    today = _render(ENV, "")
    assert f"HOME={HOME}\n" in today and f"NOS_REPO_ROOT={CHECKOUT}\n" in today, "nos_system_user '' keeps today's env"


def test_nos_writes_only_its_ledger_never_what_it_reads():
    """nos owned /var/lib/nos and could rename genome/ or .nos/ and plant its own identity map.
    The home is root:nos 0750 so no entry in it can be renamed by nos; the one writable path is the ledger."""
    u = _unit()
    data = u["ExecStart"][0].split()[4]
    assert u.get("ReadWritePaths") == [data] == ["/var/lib/nos/thalamus"], f"nos may write only its ledger: {u.get('ReadWritePaths')}"
    dirs = _task(_tasks(MEDULLA_LINUX), lambda t: "Its directories" in str(t.get("name")), "no directories task")
    ctx = {"nos_system_home": "/var/lib/nos", "nos_system_user": "nos"}
    got = {}
    for it in dirs["loop"]:
        it = {k: _env().from_string(str(v)).render(**ctx) for k, v in it.items()}
        got[it["path"]] = (it.get("owner", "root"), it["group"], it["mode"])
    owner_expr = str(dirs["ansible.builtin.file"]["owner"])
    assert "item.owner" in owner_expr or owner_expr == "root", owner_expr
    for path in ("/var/lib/nos", "/var/lib/nos/.nos", "/var/lib/nos/genome"):
        assert got.get(path) == ("root", "nos", "0750"), f"{path} must be root:nos 0750 (nos reads, never renames): {got.get(path)}"
    assert got.get(data) == ("nos", "nos", "0700"), f"the ledger dir is nos's own: {got.get(data)}"


def _task(tasks, pred, what):
    hit = [t for t in tasks if pred(t)]
    assert hit, f"{what} (no such task)"
    return hit[0]


def test_the_medulla_renders_its_env_0640_root_nos_and_its_system_unit():
    tasks = _tasks(MEDULLA_LINUX)
    env = _task(tasks, lambda t: (t.get("ansible.builtin.template") or {}).get("dest") == "/etc/nos/medulla.env",
                "pazny.medulla linux.yml renders no /etc/nos/medulla.env")
    tpl = env["ansible.builtin.template"]
    assert tpl["src"].endswith("pazny.thalamus/templates/thalamus.env.j2"), "one env template, not a second"
    assert (str(tpl.get("mode")), tpl.get("owner"), tpl.get("group")) == ("0640", "root", "{{ nos_system_user }}"), tpl
    assert env.get("no_log") is True, "the env holds the KEAP proxy secret"
    unit = _task(tasks, lambda t: "nos-medulla.service.j2" in str((t.get("ansible.builtin.template") or {}).get("src")),
                 "pazny.medulla linux.yml renders no nos-medulla.service.j2")
    assert unit["ansible.builtin.template"]["dest"] == "/etc/systemd/system/{{ thalamus_unit_name }}.service"
    binary = _task(tasks, lambda t: (t.get("ansible.builtin.copy") or {}).get("dest") == "/usr/local/libexec/nos/medulla",
                   "the binary is not installed outside $HOME")
    assert (binary["ansible.builtin.copy"].get("owner"), str(binary["ansible.builtin.copy"].get("mode"))) == ("root", "0755")
    svc = _task(tasks, lambda t: "ansible.builtin.systemd_service" in t, "no systemd_service task starts the unit")
    s = svc["ansible.builtin.systemd_service"]
    assert s.get("enabled") is True and s.get("daemon_reload") is True and "restarted" in str(s.get("state")), s
    assert "scope" not in s, "a system unit, not --user"
    block = _task(yaml.safe_load(MEDULLA_LINUX.read_text()), lambda t: "block" in t, "no system-branch block")
    assert "nos_system_user | length" in str(block.get("when")) and block.get("become") is True, block


def _read_paths() -> set[str]:
    """Every relative path serve/binding read under NOS_REPO_ROOT, from the source itself."""
    text = "\n".join(p.read_text() for p in (SRC / "binding.rs", SRC / "serve.rs"))
    found = set(re.findall(r'repo\.join\("([^"]+)"\)', text)) | set(re.findall(r'"(IMPRINT[^"]*\.md)"', text))
    assert {"state/habitat/llm-backends.yml", "IMPRINT.md"} <= found, f"the source scan went blind: {found}"
    return found - CEILING


def _block() -> dict:
    return _task(yaml.safe_load(MEDULLA_LINUX.read_text()), lambda t: "block" in t, "no system-branch block")


def _genome() -> list[str]:
    """The block's own vars: the list is the system branch's, not a role default."""
    return (_block().get("vars") or {}).get("medulla_genome") or []


def test_every_path_serve_reads_is_copied_to_the_genome():
    genome = _genome()
    missing = sorted(p for p in _read_paths() if not any(g.startswith(p) for g in genome))
    assert not missing, f"serve reads these under NOS_REPO_ROOT and the genome lacks them: {missing}"
    assert "files/anatomy/agents/iris/agent.yml" in genome
    for g in genome:
        assert (REPO / g).exists(), f"{g} is not in the repo"
    copy = _task(_tasks(MEDULLA_LINUX), lambda t: "medulla_genome" in str(t.get("loop")) and "ansible.builtin.copy" in t,
                 "no task copies medulla_genome")
    c = copy["ansible.builtin.copy"]
    assert (c.get("owner"), c.get("group"), str(c.get("mode"))) == ("root", "{{ nos_system_user }}", "0640"), c
    assert str(c["dest"]).startswith("{{ nos_system_home }}/genome/"), c
    imap = _task(_tasks(MEDULLA_LINUX), lambda t: str((t.get("ansible.builtin.copy") or {}).get("dest", "")).endswith(
        "/.nos/identity-map.yml"), "the identity map serve reads under HOME is not copied")
    assert imap["ansible.builtin.copy"]["dest"] == "{{ nos_system_home }}/.nos/identity-map.yml"


needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the genome tasks through real Ansible")


@needs_ansible
def test_the_genome_tasks_copy_into_an_empty_home(tmp_path):
    """copy makes no parent dirs for a single-file dest: the first converge failed at iris/agent.yml.
    Every block task that loops over medulla_genome runs, in order, through real Ansible into an
    empty tmp home (owner/group dropped: no chown unprivileged; the modes are still measured)."""
    genome = _genome()
    for g in genome:  # a mini repo: playbook_dir is the play's own dir
        src, dst = REPO / g, tmp_path / g
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy(src, dst)
    tasks = []
    for t in _block()["block"]:
        if "medulla_genome" not in str(t.get("loop")):
            continue
        t = {k: v for k, v in t.items() if k not in ("register", "become")}
        for mod in ("ansible.builtin.file", "ansible.builtin.copy"):
            if mod in t:
                t[mod] = {k: v for k, v in t[mod].items() if k not in ("owner", "group")}
        tasks.append(t)
    assert tasks, "no block task loops over medulla_genome"
    home = tmp_path / "var/lib/nos"
    home.mkdir(parents=True)
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": sys.executable, "medulla_genome": genome,
                      "nos_system_home": str(home), "nos_system_user": "nos"},
             "tasks": tasks}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "HOME": str(tmp_path / "op"), "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible")}
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
    for g in genome:
        got = home / "genome" / g
        assert got.exists(), f"{g} did not reach the genome"
        for f in [got] if got.is_file() else [p for p in got.rglob("*") if p.is_file()]:
            assert stat.S_IMODE(f.stat().st_mode) == 0o640, f"{f} is {oct(f.stat().st_mode)}"
        d = (home / "genome" / g.rstrip("/")).parent
        while d != home:
            assert stat.S_IMODE(d.stat().st_mode) == 0o750, f"{d} is {oct(d.stat().st_mode)}"
            d = d.parent


def test_the_service_account_is_nologin_tierless_and_no_person():
    tasks = _tasks(USERS)
    acct = _task(tasks, lambda t: (t.get("ansible.builtin.user") or {}).get("name") == "{{ nos_system_user }}",
                 "pazny.linux.users creates no nos_system_user account")
    u = acct["ansible.builtin.user"]
    assert u.get("system") is True and u.get("shell") == "/usr/sbin/nologin", u
    assert u.get("home") == "{{ nos_system_home }}" and u.get("create_home") is True, u
    assert u.get("groups") == [] and "docker" not in yaml.safe_dump(acct) and "_unix_tier_group" not in yaml.safe_dump(acct)
    assert u.get("comment") == "{{ linux_users_marker }}" and "password" not in u, u
    assert "nos_system_user | length" in str(acct.get("when")) and acct.get("become") is True
    people = next(t for t in tasks if "_unix_people" in (t.get("ansible.builtin.set_fact") or {}))
    assert "nos_system_user" not in yaml.safe_dump(people), "the service account is not a person"
    assert nos_identity.default_config()["nos_system_user"] == "", "inert until config.yml says nos"


USER_TASKS = ("The shared socket directory survives a reboot", "Create it now",
              "The daemon's environment", "systemd --user unit", "Restart on a new binary or environment")


def test_the_user_unit_tasks_are_off_on_a_system_host():
    tasks = _tasks(THALAMUS_LINUX)
    for needle in USER_TASKS:
        t = _task(tasks, lambda t: needle in str(t.get("name")), f"thalamus linux.yml: {needle!r}")
        assert "not (nos_system_user | length)" in str(t.get("when")), f"{t['name']} runs beside the system unit"
    verify = _task(tasks, lambda t: "systemctl show -p MainPID" in str(t.get("ansible.builtin.shell")),
                   "no --tags verify task reads the unit's process user")
    assert "verify" in verify.get("tags", []) and "nos_system_user | length" in str(verify.get("when"))
    assert "nos_system_user" in str(verify.get("failed_when")), verify


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_identity_status_shows_nos_as_a_service_account():
    mod = _load("identity_status_nos", "tools/identity-status.py")
    assert "pwd" in inspect.signature(mod.unix_logins).parameters, "unix_logins takes no injected passwd: nos is unseen"
    marker = yaml.safe_load((REPO / "roles/pazny.linux.users/defaults/main.yml").read_text())["linux_users_marker"]
    merged = {"nos_system_user": "nos", "authentik_rbac_tiers": [{"tier": 3, "groups": ["nos-users"]}]}
    pw = {"nos": types.SimpleNamespace(pw_name="nos", pw_gid=990, pw_gecos=marker),
          "eve": types.SimpleNamespace(pw_name="eve", pw_gid=991, pw_gecos="Eve,,,")}
    fake_pwd = types.SimpleNamespace(getpwall=lambda: list(pw.values()),
                                     getpwnam=lambda n: pw[n] if n in pw else (_ for _ in ()).throw(KeyError(n)))
    fake_grp = types.SimpleNamespace(getgrnam=lambda n: (_ for _ in ()).throw(KeyError(n)))
    held = mod.unix_logins(merged, pwd=fake_pwd, grp=fake_grp)
    assert held == ["nos"], f"the marked service account is the realm's: {held}"
    assert mod.unix_logins({**merged, "nos_system_user": "eve"}, pwd=fake_pwd, grp=fake_grp) == [], "unmarked is not ours"
    roster, _ = mod.declared_roster(merged)
    row = [r for r in roster if r["name"] == "nos"]
    assert row and row[0]["kind"] == "service" and row[0]["realms"] == ["unix"], roster
    assert not [r for r in mod.declared_roster({})[0] if r.get("kind") == "service" and r["name"] == ""]
