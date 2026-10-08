"""A templated credentials.yml fails in preflight, not 40 minutes later.

An operator who copies default.credentials.yml wholesale into credentials.yml
gets ~100 ``{{ }}`` templates in an include_vars'd file. core-up's eager
``nos_plugin_ctx: "{{ vars }}"`` snapshot resolves them where vars_files names
are not visible, and the run died at the snapshot with a bare
``'default_admin_email' is undefined`` (thisisait/nOS#42).

The preflight greps credentials.yml for template lines and fails, naming the
fix, before anything is installed. This gate pins (a) that preflight runs
before credentials.yml is first loaded, and (b) the predicate itself, run
against a copied-defaults file and a values-only file.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
PREFLIGHT = REPO / "tasks/preflight-credentials-shape.yml"
INCLUDE_NAME = "Include credentials overrides."


def _pre_and_tasks():
    play = yaml.safe_load(MAIN.read_text(encoding="utf-8"))[0]
    return list(play.get("pre_tasks") or []) + list(play.get("tasks") or [])


def test_preflight_is_imported_before_credentials_load():
    order = [
        t.get("import_tasks") or t.get("ansible.builtin.import_tasks") or t.get("name")
        for t in _pre_and_tasks()
    ]
    assert "tasks/preflight-credentials-shape.yml" in order, (
        "credentials.yml shape preflight is not imported in main.yml"
    )
    assert INCLUDE_NAME in order
    assert order.index("tasks/preflight-credentials-shape.yml") < order.index(INCLUDE_NAME), (
        "the shape check must run before credentials.yml is first loaded"
    )


def _grep_argv():
    task = yaml.safe_load(PREFLIGHT.read_text(encoding="utf-8"))[0]
    return task["ansible.builtin.command"]["argv"]


@pytest.mark.skipif(shutil.which("grep") is None, reason="grep not on PATH")
@pytest.mark.parametrize(
    "body,found",
    [
        # The real failure: a copy of default.credentials.yml.
        ((REPO / "default.credentials.yml").read_text(encoding="utf-8"), True),
        ('global_password_prefix: "s3cret"\nopenai_api_key: "sk-x"\n', False),
        ('# authentik_bootstrap_email: "{{ default_admin_email }}"\nx: "y"\n', False),
        ('x: "y"\nauthentik_bootstrap_email: "{{ default_admin_email }}"\n', True),
    ],
)
def test_predicate_flags_template_lines_only(tmp_path, body, found):
    creds = tmp_path / "credentials.yml"
    creds.write_text(body, encoding="utf-8")
    argv = [a.replace("{{ playbook_dir }}", str(tmp_path)) for a in _grep_argv()]
    rc = subprocess.run(argv, capture_output=True, text=True).returncode
    assert rc == (0 if found else 1), f"rc={rc} for found={found}"
