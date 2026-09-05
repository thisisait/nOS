"""Every shell/command body survives Ansible's argument splitter (2026-09-05).

Ansible runs ``split_args()`` on a ``shell:``/``command:`` module's free-form
body at TASK-LOAD time, before templating and before bash ever sees it. If the
body has an odd quote count or an unbalanced Jinja block, the load aborts with:

    ERROR: Error loading tasks: failed at splitting arguments, either an
    unbalanced jinja2 block or quotes: <body...>

``--syntax-check`` does NOT catch it (it does not split module args the same
way), so it only blows up at the START of a live converge — refusing the whole
run. This bit us twice: a Jinja heredoc in May 2026 (its own gate,
test_jinja_heredoc_antipattern.py, covers the {{ }} class), and on 2026-09-05 a
single apostrophe in a COMMENT line inside a hermes handler shell block —
"the cortex handler's precedent" — whose lone ' left the quote count odd.

This gate is the general detector for the whole class: it calls the SAME
``split_args`` Ansible calls, on every shell/command body, and asserts it does
not raise. A failure here is a real load failure, never a false positive — the
tool is the oracle, not a heuristic. Comments belong OUTSIDE the shell body
(as YAML ``# ...`` lines above the task) when they would carry a stray quote.
"""

from __future__ import annotations

import os
from glob import glob

import pytest
import yaml
from ansible.parsing.splitter import split_args

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# The module keys whose scalar value is a free-form body split_args() chews.
_FREEFORM = {"shell", "command", "ansible.builtin.shell", "ansible.builtin.command"}


def _yaml_files() -> list[str]:
    seen: set[str] = set()
    for pat in (
        "roles/**/tasks/*.yml",
        "roles/**/tasks/**/*.yml",
        "roles/**/handlers/*.yml",
        "tasks/**/*.yml",
        "tasks/*.yml",
        "main.yml",
    ):
        for f in glob(os.path.join(_REPO, pat), recursive=True):
            seen.add(os.path.abspath(f))
    return sorted(seen)


def _shell_bodies(node, path):
    """Yield (task_name, body) for every free-form shell/command string."""
    if isinstance(node, list):
        for item in node:
            yield from _shell_bodies(item, path)
    elif isinstance(node, dict):
        for key, val in node.items():
            if key in _FREEFORM and isinstance(val, str):
                # A dict-form `cmd:` under the module isn't split this way; only
                # the scalar free-form body is. That is what `val` is here.
                yield (node.get("name", "<unnamed>"), val)
            else:
                yield from _shell_bodies(val, path)


def _cases():
    out = []
    for f in _yaml_files():
        try:
            docs = list(yaml.safe_load_all(open(f, encoding="utf-8")))
        except (yaml.YAMLError, UnicodeDecodeError):
            continue  # not our parser's job — a broken YAML fails elsewhere
        for doc in docs:
            for name, body in _shell_bodies(doc, f):
                out.append((os.path.relpath(f, _REPO), name, body))
    return out


_CASES = _cases()


@pytest.mark.parametrize(
    "relpath,name,body",
    _CASES,
    ids=[f"{r}::{n}" for r, n, _ in _CASES],
)
def test_shell_body_splits(relpath, name, body):
    try:
        split_args(body)
    except Exception as exc:  # noqa: BLE001 — split_args raises a bare Exception
        first = str(exc).splitlines()[0]
        pytest.fail(
            f"{relpath} task {name!r}: shell body would abort task-load.\n"
            f"  split_args said: {first}\n"
            f"  Most common cause: a stray ' or \" (often in a # comment line) "
            f"leaving the quote count odd, or a {{{{ }}}} block inside the body. "
            f"Move the comment to a YAML line above the task, or balance the quote."
        )


def test_gate_sees_shell_bodies():
    """Guard against the walker silently finding nothing (a green vacuum)."""
    assert _CASES, "found no shell/command bodies — the walker is broken, not the tree"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
