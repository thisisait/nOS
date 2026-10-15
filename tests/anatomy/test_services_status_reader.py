"""What nOS offers, for Iris to recommend before it suggests a new install.

tools/services-status.py joins three things no reader joined: the manifest
row (id, category, install_flag), the RESOLVED install_* flag over every
config layer, and the plugin's hub_card description. The thalamus calls it
fixed-argv (`--json`) and treats a non-zero exit as failure, so it exits 0
always and names what it could not read in `unknown` — never an empty list
read as "nothing installed". These tests run it against a fixture estate.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "services-status.py"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

_spec = importlib.util.spec_from_file_location("_services_status", TOOL)
SS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SS)


def _plugin(root: Path, name: str, text: str) -> None:
    p = root / "files/anatomy/plugins" / name / "plugin.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def estate(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    (tmp_path / "state/manifest.yml").write_text(
        "services:\n"
        "  - {id: vaultwarden, category: security, install_flag: install_vaultwarden}\n"
        "  - {id: calibre_web, category: media, install_flag: install_calibreweb}\n"
        "  - {id: gitea, category: devops, install_flag: install_gitea}\n"
        "  - {id: broken, category: misc, install_flag: install_broken}\n",
        encoding="utf-8")
    monkeypatch.setattr(nos_identity, "REPO", tmp_path)
    nos_identity.default_layers()[-1].write_text(
        "install_vaultwarden: false\ninstall_calibreweb: false\n"
        "install_gitea: \"{{ x }}\"\ninstall_broken: true\n", encoding="utf-8")
    (tmp_path / "config.yml").write_text("install_vaultwarden: true\n", encoding="utf-8")
    _plugin(tmp_path, "vaultwarden-base",
            "requires: {feature_flag: install_vaultwarden}\n"
            "ui-extension:\n  hub_card: {description: \"" + "v" * 200 + "\"}\n")
    # the dir name is NOT the manifest id: the join is by feature_flag
    _plugin(tmp_path, "calibreweb-base",
            "requires: {feature_flag: install_calibreweb}\nhub_card: {description: ebooks}\n")
    _plugin(tmp_path, "broken-base", "requires: [unclosed\n")
    monkeypatch.setattr(nos_identity, "MANIFEST", tmp_path / "state/manifest.yml")
    return tmp_path


def _by_id(out):
    return {i["id"]: i for i in out["items"]}


def test_the_join_resolves_the_flag_over_the_layers(estate):
    rows = _by_id(SS.collect())
    assert rows["vaultwarden"]["enabled"] is True  # config.yml wins
    assert rows["calibre_web"]["enabled"] is False
    assert rows["vaultwarden"]["category"] == "security"
    assert rows["vaultwarden"]["install_flag"] == "install_vaultwarden"
    assert rows["calibre_web"]["description"] == "ebooks"


def test_a_jinja_flag_is_unknown_not_false(estate):
    assert _by_id(SS.collect())["gitea"]["enabled"] is None


def test_a_description_is_cut_to_120_chars(estate):
    assert len(_by_id(SS.collect())["vaultwarden"]["description"]) <= 120


def test_an_unreadable_plugin_is_named_in_unknown(estate):
    out = SS.collect()
    assert "files/anatomy/plugins/broken-base/plugin.yml" in out["unknown"]
    assert _by_id(out)["broken"]["description"] is None


def test_a_missing_manifest_is_unknown_not_empty(estate):
    (estate / "state/manifest.yml").unlink()
    out = SS.collect()
    assert out["items"] == [] and "state/manifest.yml" in out["unknown"]


def test_the_cli_exits_0_with_json_on_the_real_repo():
    got = subprocess.run([sys.executable, str(TOOL), "--json"],
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    out = json.loads(got.stdout)
    assert set(out) == {"items", "unknown"} and out["items"]
    assert set(out["items"][0]) == {"id", "category", "install_flag", "enabled", "description"}
