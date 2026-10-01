"""Gate: an extra Jellyfin library mounts at its host path; a missing one is skipped.

2026-10-01: the library picker browses the CONTAINER, so /Volumes/SSD1TB/... read
as "invalid" — nothing but /media/{movies,shows,music} was ever mounted. A dir on
an unplugged disk must not fail the run or be created as a phantom.
"""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.jellyfin"


@pytest.mark.skipif(not shutil.which("ansible-playbook"), reason="renders through real Ansible")
def test_present_dirs_mount_at_their_path_missing_ones_are_skipped(tmp_path):
    lib = tmp_path / "Disk With Space" / "Filmy"
    lib.mkdir(parents=True)
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    keep = [t for t in tasks if "media librar" in t.get("name", "").lower() or "Mount only" in t.get("name", "")]
    v = {"jellyfin_version": "x", "jellyfin_config_dir": "/c", "jellyfin_cache_dir": "/k",
         "stacks_shared_network": "n", "stacks_dir": "/s", "jellyfin_lan_access": False}
    play = [{"hosts": "localhost", "gather_facts": True, "connection": "local",
             "vars_files": [str(ROLE / "defaults/main.yml")],
             "vars": {"jellyfin_extra_media_dirs": [f"{lib}/", str(tmp_path / "unplugged/x")]},
             "tasks": keep + [{"name": "render", "ansible.builtin.template": {
                 "src": str(ROLE / "templates/compose.yml.j2"), "dest": str(tmp_path / "out.yml")}, "vars": v}]}]
    (tmp_path / "play.yml").write_text(yaml.safe_dump(play))
    r = subprocess.run(["ansible-playbook", "-i", "localhost,", str(tmp_path / "play.yml")],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout[-800:]
    vols = yaml.safe_load((tmp_path / "out.yml").read_text())["services"]["jellyfin"]["volumes"]
    assert f"{lib}:{lib}:ro" in vols, vols
    assert not any("unplugged" in m for m in vols) and "is missing" in r.stdout


def test_a_removable_disk_dir_is_never_created():
    create = next(t for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text())
                  if "directories exist" in t.get("name", ""))
    assert "reject('match', '/Volumes/')" in create["loop"]
