"""Gate: a config.yml `nos_synthetic_identities` beats the profile's roster.

Review 2026-10-04 #5: main.yml adopted the profile roster by set_fact BEFORE
config.yml's include_vars; set_fact outranks include_vars, so the operator's
roster was silently shadowed. Rendered here through real Ansible, in main.yml's order.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
NAMES = ("[Identities] Read the synthetic roster the profile declares",
         "[Identities] Adopt it unless config.yml or -e declared its own",
         "Include playbook configuration overrides.")


def _run(tmp: Path, config: str) -> list:
    pre = yaml.safe_load((REPO / "main.yml").read_text())[0]["pre_tasks"]
    tasks = [t for t in pre if t.get("name") in NAMES]
    assert len(tasks) == 3, [t.get("name") for t in tasks]
    (tmp / "profiles").mkdir(exist_ok=True)
    (tmp / "profiles/test-users.yml").write_text("nos_synthetic_identities: [{name: alice}]\n")
    (tmp / "defaults.yml").write_text("nos_synthetic_identities: []\n")
    (tmp / "config.yml").write_text(config)
    out = tmp / "roster.json"
    tasks.append({"ansible.builtin.copy": {"content": "{{ nos_synthetic_identities | to_json }}", "dest": str(out)}})
    play = [{"hosts": "localhost", "gather_facts": False, "connection": "local",
             "vars_files": ["defaults.yml"], "tasks": tasks}]
    (tmp / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp / "play.yml")],
                       capture_output=True, text=True, cwd=tmp)
    assert r.returncode == 0, r.stdout[-800:]
    return [i["name"] for i in json.loads(out.read_text())]


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="renders through real Ansible")
def test_config_roster_wins_and_the_profile_fills_the_gap(tmp_path):
    assert _run(tmp_path, "nos_synthetic_identities: [{name: zed}]\n") == ["zed"], "config.yml roster shadowed"
    assert _run(tmp_path, "nos_test_users_enabled: true\n") == ["alice"], "profile roster no longer adopted"
