"""Ansible reads a custom module's shebang as an interpreter PATH, not a command.

THE MEASUREMENT (2026-08-20). The first converge after Secrets P1 landed died
on P1's own task:

    TASK [[Secrets] Resolve the secret scheme (loud — no secret in this result)]
    fatal: The module interpreter '/usr/bin/env python3' was not found.
    module_stderr: /bin/sh: /usr/bin/env python3: No such file or directory

`nos_secret_map.py` opened with `#!/usr/bin/env python3`. Every module beside it
opens with `#!/usr/bin/python3`. The kernel resolves the first form fine — that
is the whole point of `env` — but Ansible does not exec the file: it reads the
shebang, takes the remainder as the interpreter's PATH, and runs
`<path> <module>`. A path containing a space is not a path, so the module never
starts, and the failure names the interpreter rather than the module, which
sends a reader to `ansible.cfg` (`interpreter_python`) where nothing is wrong.

WHY NOTHING CAUGHT IT. The module was correct Python, imported cleanly, had unit
tests, and passed `--syntax-check`. It had simply never been executed BY
ANSIBLE — the change shipped without a converge, which is exactly the
repo-vs-runtime gap CLAUDE.md opens with. A single converge is the cheapest test
that exists for this and it costs half an hour; this gate costs milliseconds and
covers the one property that converge would have checked first.

WHAT IT PINS. Every module under the configured `library` path starts with a
shebang Ansible can use as a path — no `env`, no arguments, and pointing at a
python. Not "matches the majority": a majority vote would have been won by the
broken form the moment a second one was added.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Read from ansible.cfg rather than hardcoded — if the library path moves, this
#: gate must move with it or say so, instead of quietly scanning nothing.
def _library_dir() -> Path:
    cfg = (REPO / "ansible.cfg").read_text(encoding="utf-8")
    match = re.search(r"^\s*library\s*=\s*(\S+)", cfg, re.M)
    assert match, "ansible.cfg declares no `library` path — this gate is blind"
    return (REPO / match.group(1).lstrip("./")).resolve()


def _modules() -> list[Path]:
    return sorted(
        p for p in _library_dir().glob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    )


#: An absolute path to a python, with NO arguments after it. `#!/usr/bin/python`
#: (no 3) is the classic Ansible sentinel and is CORRECT — the module builder
#: rewrites that line to the discovered interpreter. Three live modules use it
#: and converge daily; an earlier draft of this regex demanded `python3` and
#: called them broken, which is how a gate starts arguing with a working estate.
#: What Ansible cannot rewrite is a shebang with an ARGUMENT, because it takes
#: the remainder as a path.
GOOD_SHEBANG = re.compile(r"^#!(/\S*/)?python3?(\.\d+)?$")


def test_the_library_path_resolves_and_holds_modules():
    """Positive control: a broken glob would pass every assertion below."""
    lib = _library_dir()
    assert lib.is_dir(), f"library path {lib} does not exist"
    assert len(_modules()) >= 5, (
        f"only {len(_modules())} modules found under {lib} — the scan is broken"
    )


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_the_shebang_is_a_path_ansible_can_exec(module: Path):
    first = module.read_text(encoding="utf-8").splitlines()[0] if module.read_text(
        encoding="utf-8") else ""
    assert first.startswith("#!"), (
        f"{module.name} has no shebang; Ansible has no interpreter to use"
    )
    assert " " not in first[2:].strip(), (
        f"{module.name} declares {first!r}. Ansible treats everything after "
        f"`#!` as the interpreter PATH, so a space makes it a path that cannot "
        f"exist — this is the exact line that killed the 2026-08-20 converge "
        f"with \"The module interpreter '/usr/bin/env python3' was not found\". "
        f"Use `#!/usr/bin/python3`, as every sibling module does."
    )
    assert GOOD_SHEBANG.match(first), (
        f"{module.name} declares {first!r}; expected an absolute path to a "
        f"python with no arguments (`#!/usr/bin/python3` or `#!/usr/bin/python`)"
    )


def test_env_shebangs_are_rejected_by_name():
    """The specific spelling, so a future rewrite of the regex keeps catching it."""
    assert not GOOD_SHEBANG.match("#!/usr/bin/env python3")
    assert not GOOD_SHEBANG.match("#!/usr/bin/env python")
    assert GOOD_SHEBANG.match("#!/usr/bin/python3")
    assert GOOD_SHEBANG.match("#!/usr/bin/python3.13")
    assert GOOD_SHEBANG.match("#!/usr/bin/python"), (
        "the classic Ansible sentinel must stay valid — three live modules use "
        "it and converge daily"
    )


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_the_module_is_readable_by_the_user_ansible_runs_as(module: Path):
    """A module Ansible cannot read fails the same way, one layer further in."""
    assert module.stat().st_mode & stat.S_IRUSR, f"{module.name} is not readable"
