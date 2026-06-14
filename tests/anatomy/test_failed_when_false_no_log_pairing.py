"""Anatomy gate: ``failed_when: false`` + a secret MUST carry ``no_log: true``.

Finding ``no-log-without-failed-when-false-inconsistency`` (low / tech-debt):
roles applied ``no_log`` and ``failed_when`` inconsistently. The dangerous half
of that inconsistency is a task that **swallows its own failure**
(``failed_when: false``) while **substituting a secret** into the executed
command or DB-module args. When such a task fails, Ansible surfaces the module
invocation (args included) in its output — and ``failed_when: false`` turns the
hard failure into a logged result, so the resolved password lands in
``ansible.log`` / console. ``no_log: true`` is the structural guard.

The real leak the finding's cited lines pointed *near* (calibre_web / bluesky_pds
/ open_webui were already compliant) was
``roles/pazny.mariadb/tasks/post.yml`` "Remove test database": a
``community.mysql.mysql_db`` call with ``login_password: {{ mariadb_root_password }}``
+ ``failed_when: false`` and NO ``no_log`` — while its two sibling tasks in the
same file (create databases / create users) both carried ``no_log: true``. This
gate pins the pairing so the inconsistency can't regress.

Scope (deliberately precise — matches the leak class, not generic
inconsistency, so harmless "no_log without failed_when" and "failed_when without
secret" stay green):

  A task in any ``roles/*/tasks/post.yml`` is a VIOLATION iff ALL hold:
    * ``failed_when: false`` (the failure-swallowing half), and
    * a secret is substituted into an executed argument — either a DB module
      with a ``login_password`` arg, or a shell/command/uri whose rendered args
      embed a known secret var ({{ ...password... }} / token / client_secret /
      _pw_ / *_secret), and
    * the task LACKS ``no_log: true``.

Parsing is YAML-structural (PyYAML), not line-regex, so block layout / key order
don't matter. No Ansible execution — stays on the pytest+pyyaml CI stack.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
POST_FILES = sorted((REPO_ROOT / "roles").glob("*/tasks/post.yml"))

# A {{ ... }} substitution carrying a secret. Word-boundaried on the generic
# tokens so "login_redirect", "tokens", "no_secret" don't false-positive.
_SECRET_SUB = re.compile(
    r"\{\{[^}]*?("
    r"login_password|_root_password|_admin_password|admin_password|"
    r"_pw_|password\b|api_token\b|bootstrap_token\b|client_secret\b|"
    r"_secret\b|secret_key\b"
    r")[^}]*?\}\}",
    re.IGNORECASE,
)

# DB modules that accept a literal ``login_password`` arg — failing them prints
# the args.
_DB_MODULES = {
    "community.mysql.mysql_db",
    "community.mysql.mysql_user",
    "community.mysql.mysql_query",
    "community.postgresql.postgresql_db",
    "community.postgresql.postgresql_user",
    "community.postgresql.postgresql_query",
}

# Free-form command modules whose rendered args we scan for a secret sub.
_CMD_MODULES = {
    "ansible.builtin.shell",
    "ansible.builtin.command",
    "ansible.builtin.uri",
    "shell",
    "command",
    "uri",
}


def _is_false(value) -> bool:
    if value is False:
        return True
    return isinstance(value, str) and value.strip().lower() == "false"


def _is_true(value) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() == "true"


def _strings(obj) -> list:
    """Flatten every string leaf of a nested module-args structure."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out: list = []
        for value in obj.values():
            out += _strings(value)
        return out
    if isinstance(obj, list):
        out = []
        for value in obj:
            out += _strings(value)
        return out
    return []


def _substitutes_secret(task: dict) -> bool:
    for key, value in task.items():
        if key in _DB_MODULES and isinstance(value, dict):
            if "login_password" in value:
                return True
            if _SECRET_SUB.search(" ".join(_strings(value))):
                return True
        if key in _CMD_MODULES:
            if _SECRET_SUB.search(" ".join(_strings(value))):
                return True
    return False


def _load_tasks(path: Path) -> list:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - parse failure is a hard error
        pytest.fail(f"{path.relative_to(REPO_ROOT)} is not valid YAML: {exc}")
    return [t for t in (data or []) if isinstance(t, dict)]


def _violations() -> list:
    found = []
    for path in POST_FILES:
        for task in _load_tasks(path):
            if not _is_false(task.get("failed_when")):
                continue
            if _is_true(task.get("no_log")):
                continue
            if _substitutes_secret(task):
                found.append((path.relative_to(REPO_ROOT), task.get("name", "<unnamed>")))
    return found


def test_post_files_present():
    """Sanity: the scan actually globs role post.yml files."""
    assert POST_FILES, "no roles/*/tasks/post.yml found — scan path is wrong"


def test_failed_when_false_with_secret_has_no_log():
    """Any failure-swallowing task that renders a secret MUST set no_log: true."""
    violations = _violations()
    assert not violations, (
        "failed_when:false + a substituted secret WITHOUT no_log:true leaks the "
        "secret into ansible.log on task failure. Add `no_log: true` to:\n  "
        + "\n  ".join(f"{f} :: {name}" for f, name in violations)
    )


def test_mariadb_remove_test_db_is_gated():
    """Regression pin for the exact task the finding surfaced."""
    path = REPO_ROOT / "roles" / "pazny.mariadb" / "tasks" / "post.yml"
    task = next(
        t
        for t in _load_tasks(path)
        if "Remove test database" in (t.get("name") or "")
    )
    assert _is_false(task.get("failed_when")), "task lost its failed_when: false"
    assert _is_true(task.get("no_log")), (
        "mariadb 'Remove test database' substitutes mariadb_root_password under "
        "failed_when:false — it MUST carry no_log: true"
    )
