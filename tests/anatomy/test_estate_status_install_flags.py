"""`estate-status.py --install-flags`: every install_* resolved, in one call.

nos-atlas draws a service whose resolved flag is false as a dark factory, so its
refresh job needs ALL the flags as the playbook resolves them (last layer wins,
config.yml over default.config.yml over role defaults) — not default.config.yml,
whose `install_gitlab: false` once inverted sixteen verdicts (estate-status
docstring). A Jinja value is not a boolean the reader can know: it is omitted
(the atlas then says `unknown`), never guessed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402


def test_last_layer_wins_and_jinja_is_omitted(tmp_path, monkeypatch):
    (tmp_path / "roles/pazny.x/defaults").mkdir(parents=True)
    (tmp_path / "roles/pazny.x/defaults/main.yml").write_text("install_x: true\ninstall_only_role: no\n")
    (tmp_path / "default.config.yml").write_text(
        "install_x: true\ninstall_y: true\ninstall_acme: \"{{ not local }}\"\n  install_nested: true\n")
    (tmp_path / "config.yml").write_text("install_x: false   # off here\n")
    monkeypatch.setattr(nos_identity, "REPO", tmp_path)
    assert nos_identity.install_flags() == {"install_only_role": False, "install_x": False, "install_y": True}


def test_the_cli_answers_every_boolean_flag_of_the_repo():
    r = subprocess.run([sys.executable, str(REPO / "tools/estate-status.py"), "--install-flags"],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr
    flags = json.loads(r.stdout)
    assert flags and all(isinstance(v, bool) for v in flags.values()), flags
    declared = {k for k, v in yaml.safe_load((REPO / "default.config.yml").read_text()).items()
                if k.startswith("install_") and isinstance(v, bool)}
    assert declared <= flags.keys(), f"resolved nowhere: {sorted(declared - flags.keys())}"
    assert "install_acme" not in flags, "a Jinja flag was guessed into a boolean"
