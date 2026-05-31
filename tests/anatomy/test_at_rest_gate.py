"""Anatomy gate: P0-ATREST at-rest disk-encryption preflight (gov-readiness).

Pins that the gate (a) exists, (b) is flag-gated default-OFF so it is inert on
a normal/CI run, (c) has BOTH a Darwin (FileVault) and a non-Darwin (LUKS)
detect branch, (d) hard-fails in the CORRECT direction (require flag true AND
encryption NOT active), and (e) the flag is declared false in default.config.yml
but set true in profiles/gov-local.yml.

Pure file-read / yaml-parse — runs in the no-Docker pytest CI job. Never executes
fdesetup/lsblk, so platform-agnostic + CI-safe.
"""
import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / 'tasks/preflight-at-rest.yml'


def _tasks(path):
    return yaml.safe_load(path.read_text()) or []


def _by_name(path):
    return {t.get('name', ''): t for t in _tasks(path) if isinstance(t, dict)}


def test_gate_file_exists():
    assert GATE.exists(), 'tasks/preflight-at-rest.yml missing'


def test_macos_and_linux_detect_branches_present():
    by_name = _by_name(GATE)
    mac = by_name.get('[Preflight at-rest] Probe macOS FileVault status')
    lin = by_name.get('[Preflight at-rest] Probe Linux LUKS / dm-crypt status')
    assert mac is not None and lin is not None, 'missing per-platform probe task'
    assert any("ansible_os_family == 'Darwin'" in str(c) for c in (mac.get('when') or [])), \
        'mac probe not gated on Darwin'
    assert any("ansible_os_family != 'Darwin'" in str(c) for c in (lin.get('when') or [])), \
        'linux probe not gated on non-Darwin'
    assert 'fdesetup status' in str(mac.get('ansible.builtin.command', mac.get('command', '')))
    assert 'lsblk' in str(lin.get('ansible.builtin.command', lin.get('command', '')))
    for t in (mac, lin):
        assert t.get('changed_when') is False
        assert t.get('failed_when') is False


def test_every_task_is_flag_gated_default_off():
    for t in _tasks(GATE):
        if not isinstance(t, dict):
            continue
        when = t.get('when') or []
        assert any('require_disk_encryption' in str(c) for c in when), \
            f"task not gated on require_disk_encryption: {t.get('name')}"


def test_hard_fail_direction_and_escape_hatch():
    by_name = _by_name(GATE)
    fail = by_name.get('[Preflight at-rest] Refuse a gov run on an unencrypted host')
    assert fail is not None and 'ansible.builtin.fail' in fail, 'hard-fail task missing'
    when = [str(c) for c in (fail.get('when') or [])]
    assert any('require_disk_encryption' in c for c in when)
    assert any('not' in c and 'at_rest_encryption_active' in c for c in when)
    assert any('nos_skip_at_rest_check' in c for c in when)


def test_flag_default_off_in_config_and_on_in_gov_profile():
    cfg = (REPO / 'default.config.yml').read_text()
    assert 'require_disk_encryption: false' in cfg, 'flag not declared default-false'
    gov = (REPO / 'profiles/gov-local.yml').read_text()
    assert 'require_disk_encryption: true' in gov, 'gov-local.yml does not opt in'
