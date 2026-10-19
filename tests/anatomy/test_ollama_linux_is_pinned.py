"""The Linux model server is the pin, verified, and not on the LAN.

roles/pazny.ollama/tasks/linux.yml replaced `curl install.sh | sh` (which
installs whatever is latest) on the DGX. Three things keep it honest:

- the archive URL carries ollama_version and get_url verifies the release's
  own sha256sum.txt — no unpinned or unverified binary lands;
- the unit binds ollama_bind_host, which on Linux is docker0's address, never
  0.0.0.0 — the API has no authentication;
- the readback asks the RUNNING daemon for the pin, not the unpacked file.
"""
from __future__ import annotations

import pathlib

import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.ollama"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402


def _tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "linux.yml").read_text())


def test_the_archive_is_the_pin_and_verified():
    fetch = [t for t in _tasks() if "ansible.builtin.get_url" in t]
    assert len(fetch) == 1, "exactly one download of the release archive"
    args = fetch[0]["ansible.builtin.get_url"]
    assert "v{{ ollama_version }}" in args["url"]
    assert args["checksum"].startswith("sha256:") and "sha256sum.txt" in args["checksum"]
    shells = " ".join(str(t.get("ansible.builtin.shell", "")) for t in _tasks())
    assert "install.sh" not in shells and "| sh" not in shells


def test_the_unit_binds_the_declared_host_never_all_interfaces():
    unit = (ROLE / "templates" / "ollama.service.j2").read_text()
    assert 'OLLAMA_HOST={{ ollama_bind_host }}:11434' in unit
    cfg = ni.default_config()
    assert cfg["ollama_bind_host"] == "{{ nos_docker_host_ip }}"
    assert "0.0.0.0" not in cfg["nos_docker_host_ip"]
    assert "127.0.0.1" in cfg["nos_docker_host_ip"], "macOS stays on loopback"


def test_the_running_daemon_is_read_back_at_the_pin():
    readback = [t for t in _tasks() if "ansible.builtin.uri" in t]
    assert readback, "the converge must ask the daemon, not the file"
    assert "ollama_version" in readback[-1]["until"]
