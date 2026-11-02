"""The experimental host installer renders a valid autoinstall seed from parameters, and the
repo holds nothing personal (the 2026-11-01 one-off carried the operator's keys and names).

Runs tools/installer/build-usb.sh --render-only (no download, no disk) with a throwaway key.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools/installer/build-usb.sh"


def _render(tmp: Path, *extra: str) -> dict:
    key = tmp / "k.pub"
    key.write_text("ssh-ed25519 AAAAfakekeyfortest someone@test\n")
    out = tmp / "out"
    env = {**os.environ, "NOS_INSTALLER_PASSWORD_HASH": "$6$fake$notarealhash"}
    r = subprocess.run(["bash", str(TOOL), "--host", "mini", "--user", "alice", "--keys", str(key),
                        "--render-only", str(out), *extra], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    text = (out / "nocloud/user-data").read_text()
    assert text.startswith("#cloud-config") and "__" not in text
    return yaml.safe_load(text)["autoinstall"]


def test_the_seed_carries_the_parameters(tmp_path):
    a = _render(tmp_path)
    assert a["identity"]["hostname"] == "mini" and a["identity"]["username"] == "alice"
    assert a["identity"]["password"] == "$6$fake$notarealhash"
    assert a["ssh"]["authorized-keys"] == ["ssh-ed25519 AAAAfakekeyfortest someone@test"]
    assert any("git clone https://github.com/thisisait/nOS.git /home/alice/nOS" in c for c in a["late-commands"])
    assert not any("bcmwl" in c for c in a["late-commands"])


def test_the_broadcom_driver_is_opt_in(tmp_path):
    assert any("bcmwl-kernel-source" in c for c in _render(tmp_path, "--broadcom-wifi")["late-commands"])


def test_a_bad_hostname_is_refused(tmp_path):
    r = subprocess.run(["bash", str(TOOL), "--host", "Bad Host", "--user", "alice", "--render-only", str(tmp_path)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 64


def test_nothing_personal_in_the_installer():
    for f in (REPO / "tools/installer").iterdir():
        text = f.read_text(encoding="utf-8")
        assert "ssh-ed25519 AAAA" not in text and "ssh-rsa AAAA" not in text, f"a real key in {f.name}"
        assert "pazny" not in text.lower(), f"a personal name in {f.name}"
