"""An -e @profile silently outranked config.yml: the wrapper printed only the
profile name. It must name each toggle where config.yml loses, both values and
the real winner (the last -e that sets it) before ansible-playbook runs."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _nos(tmp_path, config, *argv):
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "profiles" / "core.yml").write_text(
        (REPO / "profiles" / "core.yml").read_text())
    (tmp_path / "config.yml").write_text(config)
    env = dict(os.environ, HOME=str(tmp_path / "home"), NOS_SRC=str(tmp_path))
    r = subprocess.run([str(REPO / "tools" / "nos"), "--print-cmd", *argv],
                       env=env, capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, r.stderr
    return r.stderr


def _line(err, key):
    return next((l for l in err.splitlines() if key in l), "")


def test_profile_conflict_with_config_is_named(tmp_path):
    # core.yml sets install_observability: false too: agreeing keys stay quiet.
    err = _nos(tmp_path, "install_kiwix: true   # mine\ninstall_observability: false\n",
               "-e", "@profiles/core.yml")
    line = _line(err, "install_kiwix")
    assert "true" in line and "false" in line and "profiles/core.yml wins" in line, err
    assert "install_observability" not in err


def test_a_later_e_is_named_as_the_winner(tmp_path):
    err = _nos(tmp_path, "install_kiwix: true\ninstall_mailpit: true\n",
               "-e", "@profiles/core.yml", "-e", "install_kiwix=true")
    assert "install_kiwix" not in err, err  # the later -e restores config.yml's value
    assert "profiles/core.yml wins" in _line(err, "install_mailpit"), err


def test_quoted_value_is_no_conflict_and_attached_form_is_read(tmp_path):
    err = _nos(tmp_path, 'install_observability: "false"\ninstall_kiwix: true\n',
               "-e@profiles/core.yml")
    assert "install_observability" not in err, err
    assert "wins" in _line(err, "install_kiwix"), err
