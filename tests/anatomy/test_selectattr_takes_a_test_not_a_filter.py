"""`selectattr` takes a TEST. `extract` is a FILTER. Nothing rendered the difference.

THE MEASUREMENT (2026-08-20). A full converge died 31 minutes in:

    TASK [pazny.keap : Services that are absent by every test we can run]
    The filter plugin 'ansible.builtin.rejectattr' failed: No test named 'extract'.

The expression was `rejectattr('install_flag', 'extract', vars)` — intended as
"drop the services whose install flag resolves true". It cannot work and never
could: `selectattr`/`rejectattr` dispatch their second argument through Jinja's
TEST registry, and `extract` lives in the FILTER registry. The line was committed
on 2026-08-18 and sat green for two days.

WHY TWO DAYS OF GREEN. Nothing in this repository renders a role task's
templates:

  * pytest reads files; it does not run the playbook.
  * `ansible-playbook --syntax-check` parses YAML and task structure. A template
    string is opaque to it — this exact file passed --syntax-check throughout.
  * CI's wet-test does not reach `pazny.keap`.

So the first thing to evaluate the expression was a converge, and a converge is
the most expensive possible place to learn it: 31 minutes in, on the operator's
live estate, mid-way through recreating stacks.

WHAT THIS GATE DOES, AND WHAT IT DELIBERATELY DOES NOT. It cannot render
templates — that needs a play's variables, which is what a converge is. It
checks the one thing that is decidable from the source alone: the second
argument of `selectattr`/`rejectattr` must NAME A TEST. That is a narrow claim
and it is exactly the claim the converge disproved.

THE ALLOW-LIST IS TWO SETS, ONE OF THEM DERIVED. Jinja's builtin tests come from
Jinja itself, so the gate cannot drift from the library. Ansible's additions are
listed explicitly, because `ansible.plugins.loader.test_loader` yields no test
names on the pinned ansible-core (measured: 0) and a gate that silently learns
an empty set from a broken probe is the failure shape this estate keeps paying
for. If a genuinely new Ansible test is adopted, add it here — one line, with
the name in a commit message rather than discovered by a dead converge.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]

#: Where role/task templates live. Vendored trees are not ours to edit.
SEARCH_ROOTS = ("roles", "tasks", "files/anatomy/plugins", "upgrades", "state")
EXCLUDE_PARTS = {"node_modules", ".git", "__pycache__", "vendor"}

#: Tests Ansible adds on top of Jinja's. Kept literal — see the docstring for
#: why this is not probed from the plugin loader.
ANSIBLE_TESTS = frozenset({
    "abs", "all", "any", "changed", "contains", "directory", "exists", "failed",
    "falsy", "file", "finished", "link", "match", "mount", "nan", "search",
    "skipped", "started", "subset", "succeeded", "superset", "truthy",
    "unreachable", "uri", "url", "vault_encrypted", "version", "version_compare",
})

#: `selectattr('x', 'name'` / `rejectattr("x", "name"` — the second positional
#: argument only. A call with no second argument (truthiness form) is legal and
#: is not matched.
CALL = re.compile(
    r"""(select|reject)attr\(\s*['"][^'"]*['"]\s*,\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
)


def _valid_tests() -> frozenset[str]:
    return frozenset(Environment().tests) | ANSIBLE_TESTS


def _files() -> list[Path]:
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() not in (".yml", ".yaml", ".j2"):
                continue
            if EXCLUDE_PARTS & set(path.parts):
                continue
            out.append(path)
    return out


def test_the_scan_reaches_real_files():
    """Positive control: a glob that matches nothing would pass every assertion."""
    files = _files()
    assert len(files) > 200, f"only {len(files)} files scanned — the globs are broken"
    hits = sum(len(CALL.findall(p.read_text(encoding="utf-8", errors="replace")))
               for p in files)
    assert hits > 50, (
        f"only {hits} selectattr/rejectattr calls found; the regex has stopped "
        f"matching and this gate is asserting about nothing"
    )


def test_extract_is_a_filter_and_would_be_caught():
    """The specific 2026-08-20 defect, as a property of the allow-list.

    If `extract` ever enters the valid set, the gate below stops catching the
    thing it was written for while still passing.
    """
    assert "extract" not in _valid_tests(), (
        "`extract` is in the valid-test set — it is a FILTER, and the converge "
        "that died on 2026-08-20 would now pass this gate"
    )
    for name in ("map", "join", "extract", "default", "regex_replace"):
        assert name not in _valid_tests(), f"{name} is a filter, not a test"


def test_every_selectattr_names_a_real_test():
    valid = _valid_tests()
    offenders: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for _, name in CALL.findall(line):
                if name not in valid:
                    rel = path.relative_to(REPO)
                    offenders.append(f"  {rel}:{lineno}  selectattr/rejectattr → {name!r}")
    assert not offenders, (
        "these pass something that is not a Jinja test to selectattr/rejectattr:\n"
        + "\n".join(sorted(offenders))
        + "\n\nThe second argument is dispatched through the TEST registry. A "
          "filter name there raises \"No test named ...\" at RENDER time, which "
          "on this estate means 31 minutes into a converge. If the name is a "
          "genuine Ansible test, add it to ANSIBLE_TESTS in this file."
    )


@pytest.mark.parametrize("name", ["eq", "equalto", "ne", "defined", "in",
                                  "search", "match", "truthy", "none", "contains"])
def test_the_tests_this_repo_actually_uses_are_all_valid(name):
    """Guards the allow-list from the other side.

    If a future edit trims ANSIBLE_TESTS or the Jinja version drops a builtin,
    this fails naming the missing one rather than letting the main gate go red
    across sixty call sites at once.
    """
    assert name in _valid_tests()
