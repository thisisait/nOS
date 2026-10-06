"""nos_edge: lan_tailscale — the host joins the tailnet once, advertises ONE LAN
address, and `--tags verify` says whether the tailnet can reach nOS by name.

Runs the real tasks/tailscale.yml through Ansible in a temp HOME on a sealed PATH;
`tailscale` and `dig` are stubs keeping their state in a JSON file, so the gate
never touches the host's tailnet. Funnel (public exposure) is refused twice: by a
preflight that runs here through Ansible, and by a TEXT gate — acceptable because
the thing forbidden is itself a literal (a command, a variable name). Operator
decisions 2026-10-06, roadmap row edge-tailscale-wiring.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks/tailscale.yml"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

needs_ansible = pytest.mark.skipif(importlib.util.find_spec("ansible") is None, reason="runs the task through real Ansible")
LAN = "192.168.1.10"
ROUTE = f"{LAN}/32"
DOMAIN = "firma.cz"

# One state file stands in for the tailnet: what the node is, what it advertises,
# what an admin approved, what dnsmasq answers.
TAILSCALE = r'''#!{py}
import json, sys
p = "{state}"; s = json.load(open(p)); a = sys.argv[1:]
open("{log}", "a").write("tailscale " + " ".join(a) + "\n")
if a[:2] == ["status", "--json"]:
    print(json.dumps({{"BackendState": s["state"], "Self": {{"PrimaryRoutes": s["approved"]}}}}))
elif a[:2] == ["debug", "prefs"]:
    print(json.dumps({{"AdvertiseRoutes": s["adv"] or None}}))
elif a[:3] == ["serve", "status", "--json"]:
    print(json.dumps(s["serve"]))
elif a[0] in ("up", "set"):
    s["state"] = "Running" if a[0] == "up" else s["state"]
    s["adv"] = [r for x in a if x.startswith("--advertise-routes=") for r in x.split("=", 1)[1].split(",")]
    json.dump(s, open(p, "w"))
else:
    sys.exit(2)
'''
DIG = '#!/bin/sh\necho "dig $*" >> "{log}"\ncat "{answer}"\n'


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _run(tmp: Path, *, edge="lan_tailscale", key="tskey-auth-FAKE", cli=True, tags=None,
         state="NeedsLogin", adv=(), approved=(), serve=None, answer=LAN, **extra):
    home, stubs, brew = tmp / "home", tmp / "stubs", tmp / "brew"
    for d in (home, stubs, brew / "bin"):
        d.mkdir(parents=True, exist_ok=True)
    log, st, ans = tmp / "calls.log", tmp / "ts.json", tmp / "dig.answer"
    log.write_text("")
    st.write_text(json.dumps({"state": state, "adv": list(adv), "approved": list(approved), "serve": serve or {}}))
    ans.write_text(answer + "\n")
    if cli:
        _exe(stubs / "tailscale", TAILSCALE.format(py=sys.executable, state=st, log=log))
    _exe(stubs / "dig", DIG.format(log=log, answer=ans))
    _exe(stubs / "brew", f'#!/bin/sh\necho "brew $*" >> "{log}"\n')
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": sys.executable, "homebrew_prefix": str(brew),
                      "_ts_candidates": [], "nos_edge": edge, "nos_lan_ip": LAN, "tenant_domain": DOMAIN,
                      "tailscale_auth_key": key, "tailscale_hostname": "office.tail-abc.ts.net", **extra},
             "tasks": [{"import_tasks": str(TASKS)}]}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play))
    env = {**os.environ, "HOME": str(home), "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin",
           "ANSIBLE_LOCAL_TEMP": str(tmp / ".ansible")}
    argv = [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp / "play.yml")]
    r = subprocess.run(argv + (["--tags", tags] if tags else []), capture_output=True, text=True, cwd=tmp, env=env, timeout=300)
    return r, log.read_text(), json.loads(st.read_text())


def _calls(log: str, verb: str) -> list[str]:
    return [ln for ln in log.splitlines() if ln.startswith(f"tailscale {verb} ")]


# ── the join ────────────────────────────────────────────────────────────────
@needs_ansible
def test_a_fresh_node_joins_once_and_advertises_the_lan_ip(tmp_path):
    r, log, st = _run(tmp_path, approved=[ROUTE])
    assert r.returncode == 0, r.stdout[-3000:]
    up = _calls(log, "up")
    assert up == [f"tailscale up --auth-key=tskey-auth-FAKE --advertise-routes={ROUTE} --hostname=office"], log
    assert st["adv"] == [ROUTE] and "tskey-auth-FAKE" not in r.stdout, "the auth key is never printed"
    assert f"dig +short +time=2 +tries=1 @{LAN} grafana.{DOMAIN}" in log
    assert "brew" not in log, "a CLI was found; nothing is installed beside it"


@needs_ansible
def test_a_node_that_is_up_is_left_alone(tmp_path):
    r, log, _ = _run(tmp_path, state="Running", adv=[ROUTE], approved=[ROUTE])
    assert r.returncode == 0, r.stdout[-3000:]
    assert not _calls(log, "up") and not _calls(log, "set"), f"a converge re-ran up/set on a node already right:\n{log}"


@needs_ansible
def test_an_up_node_gains_the_route_and_keeps_its_own(tmp_path):
    r, log, st = _run(tmp_path, state="Running", adv=["10.0.0.0/24"], approved=[ROUTE])
    assert r.returncode == 0, r.stdout[-3000:]
    assert _calls(log, "set") == [f"tailscale set --advertise-routes=10.0.0.0/24,{ROUTE}"] and not _calls(log, "up")
    assert st["adv"] == ["10.0.0.0/24", ROUTE]


@needs_ansible
def test_cloudflare_edge_joins_nothing(tmp_path):
    r, log, _ = _run(tmp_path, edge="cloudflare")
    assert r.returncode == 0, r.stdout[-3000:]
    assert not _calls(log, "up") and not _calls(log, "set") and "dig " not in log


@needs_ansible
def test_no_key_no_join_and_the_operator_is_told(tmp_path):
    r, log, _ = _run(tmp_path, key="")
    assert not _calls(log, "up"), "without an auth key `up` would wait for a browser login"
    assert "Open Tailscale and log in" in r.stdout
    assert "RED" in r.stdout and "OK:" not in r.stdout, "a node that never joined is RED, not green"
    assert r.returncode == 0, "a full converge reports RED and goes on to the summary; --tags verify fails"


# ── --tags verify ───────────────────────────────────────────────────────────
@needs_ansible
@pytest.mark.parametrize("approved, answer, broken", [
    ((), LAN, "approved"), ((ROUTE,), "10.9.9.9", "dns"), ((ROUTE,), LAN, None)])
def test_verify_is_red_until_the_route_is_approved_and_dns_answers(tmp_path, approved, answer, broken):
    r, log, _ = _run(tmp_path, tags="verify", state="Running", adv=[ROUTE], approved=approved, answer=answer)
    assert not _calls(log, "up") and not _calls(log, "set"), "--tags verify only reads"
    if broken:
        assert r.returncode != 0 and f"'{broken}': False" in r.stdout, r.stdout[-3000:]
    else:
        assert r.returncode == 0 and f"OK: {ROUTE} advertised and approved" in r.stdout, r.stdout[-3000:]


@needs_ansible
def test_verify_without_tailscale_is_unknown_never_green(tmp_path):
    r, log, _ = _run(tmp_path, tags="verify", cli=False)
    assert r.returncode == 0, r.stdout[-3000:]
    assert "UNKNOWN: no Tailscale CLI" in r.stdout and "OK:" not in r.stdout
    assert "brew" not in log, "--tags verify installs nothing"


@needs_ansible
def test_verify_refuses_a_funnel_that_is_on(tmp_path):
    on = {"AllowFunnel": {f"office.tail-abc.ts.net:443": True}}
    r, _, _ = _run(tmp_path, tags="verify", state="Running", adv=[ROUTE], approved=[ROUTE], serve=on)
    assert r.returncode != 0 and "Funnel is off" in r.stdout, r.stdout[-3000:]
    r, _, _ = _run(tmp_path, tags="verify", state="Running", adv=[ROUTE], approved=[ROUTE], serve={"TCP": {"443": {}}})
    assert r.returncode == 0, "serving on the tailnet alone is not Funnel"


# ── the reader ──────────────────────────────────────────────────────────────
def _reader(tmp: Path, cli=True, **state) -> dict:
    stubs, log, st, ans = tmp / "stubs", tmp / "calls.log", tmp / "ts.json", tmp / "dig.answer"
    log.write_text("")
    st.write_text(json.dumps({"state": "Running", "adv": [ROUTE], "approved": [ROUTE], "serve": {}, **state}))
    ans.write_text(state.get("answer", LAN) + "\n")
    _exe(stubs / "tailscale", TAILSCALE.format(py=sys.executable, state=st, log=log))
    _exe(stubs / "dig", DIG.format(log=log, answer=ans))
    env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "NOS_LAN_IP": LAN, "NOS_TENANT_DOMAIN": DOMAIN,
           "NOS_EDGE": "lan_tailscale", "NOS_TAILSCALE_BIN": str(stubs / "tailscale") if cli else str(tmp / "absent")}
    r = subprocess.run([sys.executable, str(REPO / "tools/tailscale-status.py"), "--json"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    for verb in ("up", "set", "funnel", "serve --"):
        assert f"tailscale {verb}" not in log.read_text(), f"the reader ran a verb that changes something: {verb}"
    return {ln["check"]: ln["state"] for ln in json.loads(r.stdout)}


def test_the_reader_only_reads_and_never_says_green_blind(tmp_path):
    assert _reader(tmp_path) == {"installed": "OK", "up": "OK", "hostname": "UNKNOWN", "route": "OK", "lan dns": "OK", "funnel": "OK"}
    assert _reader(tmp_path, approved=[])["route"] == "RED"
    assert _reader(tmp_path, answer="10.9.9.9")["lan dns"] == "RED"
    assert _reader(tmp_path, serve={"AllowFunnel": {"x:443": True}})["funnel"] == "RED"
    assert _reader(tmp_path, state="NeedsLogin")["up"] == "RED"
    assert _reader(tmp_path, cli=False) == {"installed": "UNKNOWN"}, "absent is UNKNOWN, never green"


# ── Funnel: never ───────────────────────────────────────────────────────────
ALLOWED = {"[Preflight] Refuse Tailscale Funnel", "[Tailscale] Verify: Funnel is off"}
SCANNED = ["main.yml", "default.credentials.yml", "tasks", "roles", "templates",
           *(str(p.relative_to(REPO)) for p in ni.default_layers())]


def funnel_mentions(text: str) -> list[str]:
    """Paragraphs (blank-line separated) naming funnel outside the two allowed tasks."""
    out = []
    for para in re.split(r"\n\s*\n", text):
        names = set(re.findall(r'name:\s*"([^"]+)"', para))
        if re.search(r"funnel", para, re.I) and not names & ALLOWED:
            out.append(para.strip()[:200])
    return out


def test_nothing_turns_funnel_on():
    hits = {}
    for root in SCANNED:
        for p in ([REPO / root] if (REPO / root).is_file() else (REPO / root).rglob("*")):
            if p.is_file() and p.suffix in (".yml", ".yaml", ".j2", ".sh", ".py", ".conf", ""):
                if found := funnel_mentions(p.read_text(encoding="utf-8", errors="ignore")):
                    hits[str(p.relative_to(REPO))] = found
    assert not hits, f"Funnel is never used (operator 2026-10-06); found:\n{json.dumps(hits, indent=1)}"
    # Positive control: the detector sees a task that would turn it on.
    assert funnel_mentions('- name: "Expose"\n  command: tailscale funnel 443')
    assert not funnel_mentions('# Funnel: never.\n- name: "[Preflight] Refuse Tailscale Funnel"\n  when: x')


def _preflight_task() -> dict:
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    return next(t for t in play["pre_tasks"] + play["tasks"] if t.get("name") == "[Preflight] Refuse Tailscale Funnel")


@needs_ansible
@pytest.mark.parametrize("extra, refused", [({}, False), ({"tailscale_funnel": True}, True),
                                            ({"tailscale_funnel_port": 443}, True)])
def test_the_preflight_refuses_any_funnel_variable(tmp_path, extra, refused):
    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
             "vars": {"ansible_python_interpreter": sys.executable, **extra}, "tasks": [_preflight_task()]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path, timeout=120,
                       env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(tmp_path / ".ansible")})
    assert (r.returncode != 0) is refused, r.stdout[-2000:]
    if refused:
        assert "never" in r.stdout and next(iter(extra)) in r.stdout


# ── one LAN address ─────────────────────────────────────────────────────────
def test_the_lan_ip_is_one_declared_fact():
    declared = [layer for layer, _ in ni.resolve_flag("nos_lan_ip") if layer != "config.yml"]
    assert len(declared) == 1, declared
    assert "default_ipv4" in ni.default_config()["nos_lan_ip"], "Ansible's default-route fact, not a shell guess"
    shelled = [str(p.relative_to(REPO)) for p in [REPO / "main.yml", *(REPO / "tasks").rglob("*.yml"), *(REPO / "roles").rglob("tasks/*.yml")]
               if "getifaddr" in p.read_text()]
    assert not shelled, f"a second LAN-IP detector: {shelled}"
    dns = yaml.safe_load((REPO / "tasks/dnsmasq.yml").read_text())
    facts = next(t for t in dns if "_dnsmasq_listen" in (t.get("ansible.builtin.set_fact") or {}))["ansible.builtin.set_fact"]
    assert "nos_lan_ip" in facts["_dnsmasq_listen"] and "nos_lan_ip" in facts["_dnsmasq_target"]
    ts = TASKS.read_text()
    assert "'--advertise-routes=' ~ _ts_route" in ts and '_ts_route: "{{ nos_lan_ip }}/32"' in ts


def test_the_auth_key_is_an_operator_secret():
    creds = yaml.safe_load((REPO / "default.credentials.yml").read_text())
    assert creds["tailscale_auth_key"] == "", "vendor-issued: empty here, set in credentials.yml"
    assert "tailscale_auth_key" not in ni.default_config()
    up = next(t for t in yaml.safe_load(TASKS.read_text()) if "Join the tailnet" in t.get("name", ""))
    assert up.get("no_log") is True
