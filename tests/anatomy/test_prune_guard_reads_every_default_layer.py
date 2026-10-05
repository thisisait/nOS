"""Gate: the prune guard's on-disk flags include every default layer and config.yml.

Review 2026-10-04 (commit 31b6ee6a): `{% set _base = … %}` inside the layer loop
never left the loop, so _base stayed {} and every default-off service read as an
un-authored disablement. Rendered here through real Ansible.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
NAME = "[Stacks] Read the install flags as the ON-DISK config layers declare them"


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="renders through real Ansible")
def test_on_disk_flags_merge_config_d_defaults_and_config(tmp_path):
    # The fixture mirrors the real layer set's shape, named by the helper (never here).
    domain, *_, remainder = [p.relative_to(REPO) for p in ni.default_layers()]
    for rel, body in ((domain, "install_from_config_d: false\n"),
                      (remainder, "install_from_defaults: false\ninstall_overridden: false\n")):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    (tmp_path / "config.yml").write_text("install_overridden: true\n")
    task = next(t for t in yaml.safe_load((REPO / "tasks/stacks/prune-disabled.yml").read_text())
                if t.get("name") == NAME)
    out = tmp_path / "flags.json"
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "tasks": [task, {"ansible.builtin.copy": {"content": "{{ _on_disk_flags | to_json }}",
                                                        "dest": str(out)}}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stdout[-800:]
    assert json.loads(out.read_text()) == {"install_from_config_d": False, "install_from_defaults": False,
                                           "install_overridden": True}
