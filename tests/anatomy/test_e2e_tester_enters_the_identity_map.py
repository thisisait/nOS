"""An e2e tester may stand in the thalamus identity map for one run, and nobody else is touched.

Operator ruling 2026-10-22: the face/Iris Playwright journeys log in as an ephemeral
`nos-tester-e2e-*` user, which the thalamus refuses unless ~/.nos/identity-map.yml names it.
tests/e2e/lib/iris_map.py adds that login for the run and removes it at teardown.
"""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "e2e"))
from lib import iris_map  # noqa: E402

ROSTER = {"logins": {"pza2bj": {"username": "admin", "groups": ["nos-admins"]},
                     "test-dave": {"username": "test-dave", "groups": ["nos-users"]}}}


@pytest.fixture
def mapfile(tmp_path, monkeypatch):
    p = tmp_path / "identity-map.yml"
    p.write_text(json.dumps(ROSTER))
    os.chmod(p, 0o600)
    monkeypatch.setenv("NOS_IDENTITY_MAP", str(p))
    return p


def test_a_tester_is_added_and_removed_and_the_roster_stays(mapfile):
    assert iris_map.add("nos-tester-e2e-ab12cd34", "nos-users")
    logins = json.loads(mapfile.read_text())["logins"]
    assert logins["nos-tester-e2e-ab12cd34"] == {"username": "nos-tester-e2e-ab12cd34", "groups": ["nos-users"]}
    assert stat.S_IMODE(mapfile.stat().st_mode) == 0o600, "the rewrite keeps the map's mode"
    assert iris_map.remove("nos-tester-e2e-ab12cd34")
    assert json.loads(mapfile.read_text()) == ROSTER


def test_only_tester_names_are_touched(mapfile):
    with pytest.raises(ValueError):
        iris_map.add("test-dave", "nos-admins")
    with pytest.raises(ValueError):
        iris_map.remove("pza2bj")
    assert json.loads(mapfile.read_text()) == ROSTER


def test_sweep_drops_leftover_testers_only(mapfile):
    iris_map.add("nos-tester-e2e-11111111", "nos-users")
    iris_map.add("nos-tester-e2e-22222222", "nos-guests")
    assert iris_map.sweep()
    assert json.loads(mapfile.read_text()) == ROSTER


def test_no_map_no_thalamus_nothing_written(tmp_path, monkeypatch):
    monkeypatch.setenv("NOS_IDENTITY_MAP", str(tmp_path / "absent.yml"))
    assert not iris_map.add("nos-tester-e2e-ab12cd34", "nos-users")
    assert not (tmp_path / "absent.yml").exists()
