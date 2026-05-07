"""Jinja-in-heredoc anti-pattern gate (Anatomy 2026-05-07).

Catches inline-Python (or any heredoc'd script) that contains Jinja
braces inside ``ansible.builtin.shell:`` task bodies. Ansible templates
the entire shell body BEFORE bash sees it — embedding ``{{ ... }}`` in
a heredoc dict / regex / string breaks the argument splitter:

    ERROR: Error loading tasks: failed at splitting arguments, either
    an unbalanced jinja2 block or quotes: python3 <<'PY'
    ...
    Origin: roles/pazny.wing/tasks/post.yml:161:3

Triggered by:
    pytest tests/anatomy/test_jinja_heredoc_antipattern.py
And by the full CI run via the `pytest` job.

Background — why this test exists:
    2026-05-07: I (Claude) added a Pulse-catalog discovery task that
    embedded ``SUBSTITUTIONS = {'{{ playbook_dir }}': ...}`` inside a
    bash heredoc inside a shell task. ansible-playbook --syntax-check
    happily passed it (syntax-check doesn't render templates). It
    only blew up DURING a live run, deep into the playbook. The fix
    at source level is "Python scripts live in standalone files,
    invoked via ansible.builtin.command with env vars"; this gate
    makes the workflow self-policing.

Allowlist: empty — there is no legitimate use of Jinja braces inside a
shell heredoc in this codebase. If a legitimate one ever appears, add
the offending file to ``ALLOWED_FILES`` with a comment explaining why
it's safe.
"""

from __future__ import annotations

import os
import re
from glob import glob

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Files explicitly cleared. Keep this list very short and well-justified.
ALLOWED_FILES: set[str] = set()

# Match ANY heredoc in a shell task: `<<'TAG'` ... `TAG`. The
# single-quoted TAG form prevents bash variable expansion but does NOT
# prevent Ansible Jinja templating, which is the actual hazard.
_HEREDOC_RE = re.compile(
    r"<<'(\w+)'\n(.*?)^\s*\1\b",
    re.MULTILINE | re.DOTALL,
)
# Jinja braces inside that body — ``{{ varname }}`` or ``{% block %}``.
_JINJA_RE = re.compile(r"{{\s*\w|{%\s*\w")


def _yaml_files_with_shell_tasks() -> list[str]:
    """Yield every role/task YAML that might contain ansible.builtin.shell."""
    patterns = [
        f"{_REPO}/roles/**/tasks/*.yml",
        f"{_REPO}/tasks/**/*.yml",
        f"{_REPO}/files/anatomy/**/*.yml",
    ]
    files: list[str] = []
    for p in patterns:
        files.extend(glob(p, recursive=True))
    # Skip third-party / vendored / generated trees.
    return [f for f in files if "/vendor/" not in f and "/.git/" not in f]


def test_no_jinja_inside_shell_heredocs():
    """Every shell-task heredoc body must be free of {{ }} / {% %}.

    If a heredoc contains Jinja, Ansible's pre-shell template pass
    expands or chokes on it → either silent value mutation or the
    "failed at splitting arguments" parse error.

    Proper pattern: extract the script to ``files/anatomy/scripts/<name>.py``
    and call it via ``ansible.builtin.command`` with env vars.
    """
    offenders: list[str] = []
    for path in _yaml_files_with_shell_tasks():
        rel = os.path.relpath(path, _REPO)
        if rel in ALLOWED_FILES:
            continue
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        if "ansible.builtin.shell" not in text and "shell:" not in text:
            continue
        for match in _HEREDOC_RE.finditer(text):
            body = match.group(2)
            if _JINJA_RE.search(body):
                line_no = text[: match.start()].count("\n") + 1
                offenders.append(f"{rel}:{line_no} (heredoc tag <<'{match.group(1)}'>>)")

    assert not offenders, (
        "Jinja braces detected inside shell-task heredocs. Ansible templates\n"
        "the shell body BEFORE bash, so {{ }} / {% %} inside a heredoc breaks\n"
        "the argument splitter. Move the script to files/anatomy/scripts/<name>\n"
        "and call it via ansible.builtin.command with env vars.\n\n"
        "Offenders:\n  - " + "\n  - ".join(offenders)
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
