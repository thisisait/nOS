"""Every launchd job and systemd unit the estate renders runs an executable named for its organ.

macOS Activity Monitor and `ps -o ucomm`/`top` name a process by the basename of the path launchd
executed: argv[0] does not change it, a symlink shows its target's name, a hardlink keeps its own
name but proc_pidpath reports the first link (measured 2026-10-25, report on feat/medulla-process-names).
Linux sets /proc/<pid>/comm the same way, cut to 15 chars. So `/usr/bin/python3 receptor.py` shows as
`Python`, frankenphp as `frankenphp`: the operator cannot tell an organ from any other process.

The scheme: a self-owned organ's job runs `nos-<organ>` (a copy of the medulla binary, which
dispatches on that argv0), at most 15 chars. A symbiont keeps its vendor's binary (FOREIGN, with
the reason). Today's anonymous jobs are DEBT, listed by name: a debt that is paid must leave the list.
Rendered with every layer's defaults: the gate reads the argv the template produces, not its text.
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

#: The medulla is the binary every self-owned organ moves into (ssot/doctrine/medulla.md); not a manifest row.
ORGANS = {r["id"].replace("_", "-") for r in nos_identity.services() if r.get("software_owner") == "self"} | {"medulla"}
COMM_MAX = 15  # Linux TASK_COMM_LEN - 1; macOS p_comm keeps 16, Activity Monitor 32

#: label -> why the vendor's binary keeps its own name (it is the vendor's process, not an organ).
FOREIGN = {
    "eu.thisisait.nos.backrest": "symbiont: Backrest's own Go binary",
    "eu.thisisait.nos.hermes": "symbiont: Hermes's own venv entry point",
    "com.ollama.agent": "symbiont: Ollama's own binary",
    "ollama": "symbiont: Ollama's own binary (Linux unit)",
    "nos-ollama-loopback": "symbiont: systemd-socket-proxyd forwarding Ollama's port",
    "com.openclaw.agent": "symbiont: OpenClaw's own gateway",
    "com.nginx.nginx-prometheus-exporter": "symbiont: a Homebrew exporter",
    "com.hipages.php-fpm-exporter": "symbiont: a Homebrew exporter",
    "eu.thisisait.nos.acme-renew": "symbiont: acme.sh, run on a calendar",
    "eu.thisisait.nos.dnsmasq-tailnet": "symbiont: Homebrew's dnsmasq",
    "nos-jupyterhub": "symbiont: JupyterHub's own entry point",
    "nos-jupyterhub-proxy": "symbiont: docker runs the proxy container",
    "eu.thisisait.nos.app": "a launcher: /usr/bin/open hands nOS.app to LaunchServices and exits; the process is nOS",
}

#: label -> the basenames it runs today (macOS and Linux). Each is an organ still on an interpreter
#: or a script; paid when its job runs nos-<organ>, and then it leaves this list.
DEBT = {
    "eu.thisisait.nos.receptor": {"python3"},
    "eu.thisisait.nos.device-gateway": {"python3"},
    "eu.thisisait.nos.bone": {"uvicorn", "python"},
    "eu.thisisait.nos.pulse": {"python"},
    "eu.thisisait.nos.wing": {"frankenphp", "@_wing_frankenphp_bin@"},  # a set_fact on Linux
    "eu.thisisait.nos.cortex": {"@_cortex_node_bin@"},  # node, found by a set_fact
    "eu.thisisait.nos.backup.rustfs": {"bash"},
    "eu.thisisait.nos.backup.exporter": {"python3"},
    "eu.thisisait.nos.backup.offsite": {"bash", "backup-run.sh"},
    "eu.thisisait.nos.heartbeat": {"python3"},
    "eu.thisisait.nos.resume": {"bash"},
}


def _context() -> dict:
    raw: dict = {}
    for p in nos_identity.layer_paths():
        if p.name != "config.yml":  # the operator's file is not the repo's truth
            raw.update(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    raw.update(ansible_facts={"env": {"HOME": "/Users/op"}, "os_family": "Darwin"}, homebrew_prefix="/opt/homebrew",
               playbook_dir=str(REPO), ansible_managed="", role_path=str(REPO / "roles/x"), inventory_hostname="h")
    return raw


class Unset(jinja2.ChainableUndefined):
    """A var no layer declares (a set_fact) renders as @name@: visible in the argv, never a pass."""

    def __str__(self):
        return f"@{self._undefined_name}@"


ENV = jinja2.Environment(undefined=Unset)
# Ansible's filters an argv never hangs on render as identity; the path ones are real.
for _f in ("bool", "quote", "to_json", "to_yaml", "to_nice_yaml", "b64encode", "mandatory", "regex_replace", "hash"):
    ENV.filters.setdefault(_f, lambda v, *a, **k: v)
ENV.filters.update(basename=lambda v: os.path.basename(str(v)), dirname=lambda v: os.path.dirname(str(v)))


class Lazy(dict):
    """A var renders when it is read, as Ansible does, so `{{ thalamus_home }}/bin/x` resolves."""

    def __getitem__(self, key):
        return self._r(dict.__getitem__(self, key), 0)

    def _r(self, v, depth):
        if isinstance(v, str) and "{" in v and depth < 8:
            try:
                return self._r(_jinja(v, self), depth + 1)
            except jinja2.TemplateError:
                return v
        if isinstance(v, list):
            return [self._r(x, depth) for x in v]
        if isinstance(v, dict):
            return {k: self._r(x, depth) for k, x in v.items()}
        return v


def _jinja(text: str, ctx: dict) -> str:
    t = ENV.from_string(text)  # shared=True keeps Lazy as the context: render() would copy it to a dict
    return "".join(t.root_render_func(t.new_context(ctx, shared=True)))


CTX = _context()


def _render(text: str, **extra) -> str:
    return _jinja(text, Lazy({**CTX, **extra}))


def _yaml_strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _yaml_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _yaml_strings(v)
    elif isinstance(node, str):
        yield node


def _calls(node):
    if isinstance(node, list):
        for x in node:
            yield from _calls(x)
    elif isinstance(node, dict):
        inc = node.get("ansible.builtin.include_role") or node.get("include_role") or {}
        if isinstance(inc, dict) and inc.get("name") == "pazny.linux.systemd_user":
            yield node.get("vars") or {}
        for k in ("block", "rescue", "always"):
            yield from _calls(node.get(k))


def jobs() -> list[tuple[str, str, str]]:
    """(source, label, argv0) of every job a converge renders."""
    out = []
    tasks = sorted({*REPO.glob("roles/*/tasks/**/*.yml"), *REPO.glob("tasks/**/*.yml")})
    plists = [(p, p.read_text(encoding="utf-8")) for p in sorted(
        {*REPO.glob("roles/*/templates/**/*.plist.j2"), *REPO.glob("templates/*.plist.j2"), *REPO.glob("files/**/*.plist.j2")})]
    for t in tasks:
        doc = yaml.safe_load(t.read_text(encoding="utf-8"))
        plists += [(t, s) for s in _yaml_strings(doc) if "<key>ProgramArguments</key>" in s]
        for v in (c for c in _calls(doc) if "su_exec_start" in c):
            label = _render(str(v.get("su_name", "")))
            out.append((str(t.relative_to(REPO)), label, _render(str(v["su_exec_start"]), **v).split()[0]))
    for src, text in plists:
        doc = plistlib.loads(_render(text).strip().encode())
        if "Label" in doc:  # an Info.plist (ears) is not a job
            out.append((str(src.relative_to(REPO)), doc["Label"], (doc.get("ProgramArguments") or [doc.get("Program")])[0]))
    for unit in sorted(REPO.glob("roles/*/templates/**/*.service.j2")):
        line = next(x for x in _render(unit.read_text(encoding="utf-8")).splitlines() if x.startswith("ExecStart="))
        out.append((str(unit.relative_to(REPO)), unit.name.removesuffix(".service.j2"),
                    line.split("=", 1)[1].lstrip("-@:+!").split()[0]))
    return out


JOBS = jobs()


def _named(argv0: str) -> bool:
    name = Path(argv0).name
    return name.startswith("nos-") and name[4:] in ORGANS and len(name) <= COMM_MAX


def test_the_gate_sees_the_estate():
    labels = {label for _, label, _ in JOBS}
    assert {"eu.thisisait.nos.thalamus", "eu.thisisait.nos.wing", "ollama"} <= labels, sorted(labels)


@pytest.mark.parametrize("src,label,argv0", JOBS, ids=[f"{label}@{src}" for src, label, _ in JOBS])
def test_a_job_runs_its_organ_name(src, label, argv0):
    if label in FOREIGN or label in DEBT:
        return
    assert _named(argv0), (
        f"{src}: {label} runs {argv0!r}, shown as {Path(argv0).name!r} in Activity Monitor and top. "
        f"An organ runs nos-<organ> (one of {sorted(ORGANS)}, <= {COMM_MAX} chars): copy the medulla "
        "there and dispatch on that argv0 (medulla/src/main.rs). A vendor binary goes in FOREIGN with why.")


def test_the_debt_list_holds_only_debt():
    debt = [(label, Path(argv0).name) for _, label, argv0 in JOBS if label in DEBT]
    stale = [k for k in DEBT if all(_named(f"/{n}") for lb, n in debt if lb == k)]
    assert not stale, f"paid or gone, take them off DEBT: {stale}"
    drift = sorted({(lb, n) for lb, n in debt if n not in DEBT[lb]})
    assert not drift, f"DEBT records what each runs today; it changed: {drift}"
