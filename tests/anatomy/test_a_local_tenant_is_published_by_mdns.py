"""A .local tenant on Linux had no resolver at all: tasks/dnsmasq.yml is Darwin-only, so
14 of 20 journeys on the mini died on a name (2026-10-31). tasks/mdns.yml reads back every
Host() Traefik routes, conf.d AND container labels (manifest apps route by label), publishes
them by avahi at nos_lan_ip on physical links only, and maps them to 127.0.0.1 on the host."""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = yaml.safe_load((REPO / "tasks/mdns.yml").read_text())
ENV = jinja2.Environment(trim_blocks=True)
ENV.filters.update(quote=lambda s: shlex.quote(str(s)), regex_escape=re.escape,
                   bool=lambda v: str(v).strip().lower() in ("true", "1", "yes"))
ENV.tests["match"] = lambda v, p: re.match(p, v) is not None
NAMES = ["mini.local", "auth.mini.local", "kiwix.mini.local", "notes.apps.mini.local"]


def _task(prefix: str) -> dict:
    return next(t for t in TASKS if t["name"].startswith(prefix))


def test_the_lan_records_skip_the_name_avahi_already_owns():
    # Live on the mini 11-01: a static /etc/avahi/hosts record also claims the address's PTR,
    # which mini.local already holds -> "Local name collision" for every name. -R publishes none.
    vars_ = dict(_mdns_names=NAMES, ansible_facts={"hostname": "mini"}, nos_lan_ip="192.168.1.252", ansible_managed="x")
    unit = ENV.from_string((REPO / "templates/nos-mdns-names.service.j2").read_text()).render(**vars_)
    published = re.findall(r"avahi-publish -a -R (\S+) (\S+)", unit)
    assert published == [(n, "192.168.1.252") for n in NAMES[1:]], published
    hosts = ENV.from_string((REPO / "templates/avahi-hosts.j2").read_text()).render(**vars_)
    assert not [ln for ln in hosts.splitlines() if ln and not ln.startswith("#")], "a static record collides with the host's PTR"


def test_the_read_back_sees_file_routes_and_label_routes(tmp_path):
    conf = tmp_path / "traefik" / "conf.d"
    conf.mkdir(parents=True)
    (conf / "services.yml").write_text("rule: Host(`auth.mini.local`)\nrule: Host(`other.example.com`)\n")
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\n[ "$1" = ps ] && { echo c1; exit 0; }\n'
                      'echo \'{"traefik.http.routers.notes.rule":"Host(`notes.apps.mini.local`)"}\'\n')
    docker.chmod(0o755)
    script = ENV.from_string(_task("[mdns] Read back")["ansible.builtin.shell"]).render(
        traefik_config_dir=str(tmp_path / "traefik"), nos_docker_bin=str(docker), tenant_domain="mini.local")
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["auth.mini.local", "notes.apps.mini.local"]


def test_a_hostile_label_never_reaches_the_publisher(tmp_path):
    """Any container's label is read back (an upstream image's LABEL too), and the names went
    unquoted into the unit's bash -c: `a;touch${IFS}/tmp/x;b.mini.local` ran as avahi at every
    boot (review 2026-11-03). Only a DNS name leaves the read-back, and the unit drops any other."""
    (tmp_path / "traefik" / "conf.d").mkdir(parents=True)
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\n[ "$1" = ps ] && { echo c1; exit 0; }\n'
                      'echo \'{"r1":"Host(`a;touch${IFS}/tmp/x;b.mini.local`)","r2":"Host(`$(id).mini.local`)",'
                      '"r3":"Host(`ok.mini.local`)","r4":"Host(`x y.mini.local`)"}\'\n')
    docker.chmod(0o755)
    script = ENV.from_string(_task("[mdns] Read back")["ansible.builtin.shell"]).render(
        traefik_config_dir=str(tmp_path / "traefik"), nos_docker_bin=str(docker), tenant_domain="mini.local")
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    assert out.split() == ["ok.mini.local"], out
    vars_ = dict(_mdns_names=["ok.mini.local", "a;b.mini.local"], ansible_facts={"hostname": "mini"},
                 nos_lan_ip="192.168.1.252", ansible_managed="x")
    unit = ENV.from_string((REPO / "templates/nos-mdns-names.service.j2").read_text()).render(**vars_)
    assert "-R ok.mini.local" in unit and "a;b" not in unit, "a non-DNS name reached the unit's bash -c"


def test_it_runs_after_apps_up_and_only_for_a_local_linux_host():
    plays = yaml.safe_load((REPO / "main.yml").read_text())
    tasks = next(p["tasks"] for p in plays if any(t.get("import_tasks") == "tasks/stacks/apps-up.yml"
                                                   for t in p.get("tasks", [])))
    files = [t.get("import_tasks") for t in tasks]
    assert files.index("tasks/mdns.yml") > files.index("tasks/stacks/apps-up.yml")
    when = tasks[files.index("tasks/mdns.yml")]["when"]

    def on(domain, family="Debian", container=False):
        return all(ENV.from_string("{{ %s }}" % w).render(
            tenant_domain=domain, ansible_os_family=family, nos_is_container=container) == "True" for w in when)
    assert on("mini.local")
    assert not any([on("firm.internal"), on("pazny.eu"), on("mini.local", container=True), on("dev.local", "Darwin")])


def test_avahi_answers_on_physical_links_only():
    expr = _task("[mdns] Name the records")["ansible.builtin.set_fact"]["_mdns_ifaces"]
    ifaces = ["lo", "docker0", "br-x", "veth1", "tailscale0", "enp1s0", "wlp2s0"]
    assert ENV.from_string(expr).render(ansible_facts={"interfaces": ifaces}) == "enp1s0,wlp2s0"


def test_the_host_resolves_itself_at_loopback():
    block = ENV.from_string(_task("[mdns] The host resolves")["ansible.builtin.blockinfile"]["block"])
    assert block.render(_mdns_names=NAMES[:2]).split("\n")[:2] == ["127.0.0.1 mini.local", "127.0.0.1 auth.mini.local"]


def test_the_firewall_lets_mdns_in_for_a_local_tenant():
    ufw = yaml.safe_load((REPO / "roles/pazny.linux.hardening/tasks/ufw.yml").read_text())
    rule = next(t for t in ufw if str(t.get("community.general.ufw", {}).get("port")) == "5353")
    assert rule["community.general.ufw"]["proto"] == "udp"
    when = ENV.from_string("{{ %s }}" % rule["when"])
    assert when.render(tenant_domain="mini.local") == "True" and when.render(tenant_domain="pazny.eu") == "False"
