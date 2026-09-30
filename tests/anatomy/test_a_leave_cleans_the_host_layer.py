"""A leave removes the host layer, and a reader refuses one that did not.

The 2026-09-29 exit audit found the removal set covered directories only:
brew service registrations (dnsmasq as a root daemon on :53), the mkcert
root CA trusted in the System keychain, the `home` SSH account and its sshd
Match block, and brew-bin symlinks into removed trees. This gate pins each
removal, runs the symlink sweep against a temp tree, and checks the reader
asks about every item it removes.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "tasks/remove-source.yml"


def _block() -> list[dict]:
    tasks = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    return next(t for t in tasks if t.get("name") == "[Remove:host] Host layer")["block"]


def _task(needle: str) -> dict:
    return next(t for t in _block() if needle in t["name"])


def test_the_host_layer_runs_before_done_and_only_on_macos() -> None:
    tasks = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    names = [t.get("name", "") for t in tasks]
    assert names.index("[Remove:host] Host layer") < names.index("[Remove:source] Done")
    host = tasks[names.index("[Remove:host] Host layer")]
    assert "Darwin" in host["when"]


def test_privileged_binaries_are_called_by_absolute_path() -> None:
    """sudo's secure_path has no /opt/homebrew/bin: a bare `mkcert` under
    become is 'command not found' and the leave dies mid-way."""
    untrust = _task("Untrust the mkcert root CA")
    assert untrust["become"] is True
    assert "{{ homebrew_prefix }}/bin/mkcert" in untrust["ansible.builtin.shell"]


def test_the_reader_asks_about_everything_the_block_removes() -> None:
    reader = _task("Read back the host layer")
    script = reader["ansible.builtin.shell"]
    for probe in ("homebrew.mxcl.", "eu.thisisait.nos", "mkcert", "id \"", "ANSIBLE MANAGED - iiab-terminal"):
        assert probe in script, probe
    assert "LEFT: none" in reader["failed_when"]


def test_the_symlink_sweep_takes_only_dangling_links_into_home(tmp_path: Path) -> None:
    home, bindir, outside = tmp_path / "home", tmp_path / "bin", tmp_path / "elsewhere"
    for d in (home, bindir, outside):
        d.mkdir()
    (home / "alive").write_text("x")
    (bindir / "gone-home").symlink_to(home / "bone/bin/nos-loop")      # dangling, into HOME → removed
    (bindir / "alive-home").symlink_to(home / "alive")                 # resolves → kept
    (bindir / "gone-elsewhere").symlink_to(outside / "missing")        # dangling, outside HOME → kept
    script = jinja2.Environment().from_string(_task("Drop brew-bin symlinks")["ansible.builtin.shell"]).render(
        nos_cli_install_dir=str(bindir))
    r = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True,
                       env={**os.environ, "HOME": str(home)})
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in bindir.iterdir()) == ["alive-home", "gone-elsewhere"]


def test_the_cert_sweep_takes_only_this_hosts_mkcert_ca(tmp_path: Path) -> None:
    """mkcert -uninstall leaves the certificate; the sweep deletes it, and only
    the one whose label names this host. Runs the task under a fake `security`."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "deleted.log"
    (bindir / "security").write_text(f"""#!/bin/bash
case "$1" in
  find-certificate) cat <<'OUT'
SHA-1 hash: AAAA
    "labl"<blob>="mkcert root@thishost.local (System Administrator)"
SHA-1 hash: BBBB
    "labl"<blob>="mkcert alice@otherbox.local (Alice)"
OUT
  ;;
  delete-certificate) echo "$3" >> "{log}";;
esac
""")
    (bindir / "hostname").write_text("#!/bin/bash\necho thishost.local\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    script = jinja2.Environment().from_string(_task("Untrust the mkcert root CA")["ansible.builtin.shell"]).render(
        homebrew_prefix=str(tmp_path / "nobrew"))
    r = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "CAROOT": str(tmp_path / "gone")})
    assert r.returncode == 0, r.stderr
    assert log.read_text().split() == ["AAAA"], "deleted another host's CA, or not this one"


def test_the_reader_waits_out_directory_services() -> None:
    reader = _task("Read back the host layer")
    assert reader.get("retries", 0) >= 3 and "LEFT: none" in reader["until"]
