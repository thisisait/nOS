"""A container that calls a host daemon through host.docker.internal reaches it on Linux too.

On macOS host.docker.internal is the host's loopback (Docker Desktop), so a daemon bound to
127.0.0.1 answers. On Linux it is the docker bridge address (nos_docker_host_ip): the daemon
must also bind that address, and ufw (incoming deny) must let the container side through
(roles/pazny.linux.hardening, hardening_ufw_from_containers). Live 2026-10-22 on the DGX: face's
/bff/userstate timed out against Bone on 127.0.0.1 only, so Iris layouts were never saved, and
/bff/tables timed out against KEAP's loopback-only publish.

Every port a container template dials on host.docker.internal is a declared door, or is named
below as known debt with its reason. A container-to-container call goes over the docker network.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
HARDENING = ROOT / "roles/pazny.linux.hardening/defaults/main.yml"
# What containers render: role compose templates and plugin provisioning, not prose or plists.
SOURCES = [*ROOT.glob("roles/*/templates/compose*.j2"), *ROOT.glob("files/anatomy/plugins/*/provisioning/*.j2")]
DIAL = re.compile(r"host\.docker\.internal:(?:\{\{\s*([a-z_]+)|(\d+))")
# Not doors yet: each would time out on Linux the way Bone did. Fix, then delete the line.
KNOWN_DEBT = {
    "cortex_port": "KEAP's cortex cutover (keap_cortex_cutover); cortex binds loopback only",
    "alloy_ui_port": "Prometheus scrape of host Alloy; macOS-only today",
    "nginx_exporter_port": "Prometheus scrape of host nginx exporter; host nginx is opt-in",
    "phpfpm_exporter_port": "Prometheus scrape of host php-fpm; host PHP installer is gone",
}


def _doors() -> set[str]:
    ports = yaml.safe_load(HARDENING.read_text())["hardening_ufw_from_containers"]["ports"]
    # "{{ wing_port | default(9000) }}" opens wing_port and 9000; a bare 11434 opens 11434.
    return {t for p in ports for t in re.findall(r"[a-z_]+_port|\d+", str(p))}


def _dialled() -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for f in SOURCES:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for var, num in DIAL.findall(line):
                seen.setdefault(var or num, []).append(f"{f.relative_to(ROOT)}:{n}")
    return seen


def test_every_dialled_host_port_is_a_door():
    doors, open_ = _doors(), []
    for port, where in sorted(_dialled().items()):
        if port not in doors and port not in KNOWN_DEBT:
            open_.append(f"{port} ({', '.join(where)})")
    assert not open_, ("dialled on host.docker.internal but not in hardening_ufw_from_containers.ports "
                       "(and its daemon not bound to nos_docker_host_ip): " + "; ".join(open_))


def test_known_debt_is_still_dialled():
    """A debt line whose dial is gone is a stale excuse: delete it."""
    stale = sorted(set(KNOWN_DEBT) - set(_dialled()))
    assert not stale, f"KNOWN_DEBT names ports no template dials any more: {stale}"


def test_bone_binds_the_bridge_on_linux():
    """Bone keeps 127.0.0.1 (host callers dial it there) and adds nos_docker_host_ip for containers."""
    tasks = (ROOT / "roles/pazny.bone/tasks/main.yml").read_text()
    start = re.search(r'su_exec_start:\s*"([^"]+)"', tasks).group(1)
    assert "bone_bind_hosts" in start, f"the Linux unit binds one fixed host: {start}"
    defaults = (ROOT / "roles/pazny.bone/defaults/main.yml").read_text()
    hosts = re.search(r"^bone_bind_hosts:\s*(.+)$", defaults, re.M)
    assert hosts and "127.0.0.1" in hosts.group(1) and "nos_docker_host_ip" in hosts.group(1)


def test_face_reaches_keap_over_the_docker_network():
    """KEAP is a container on face's gated_net; its loopback publish is the host agents' surface."""
    face = (ROOT / "roles/pazny.face/templates/compose.yml.j2").read_text()
    line = next(x for x in face.splitlines() if "NOS_KEAP_TABLES_URL" in x and "default('http" in x)
    assert "host.docker.internal" not in line and "keap:" in line, line
