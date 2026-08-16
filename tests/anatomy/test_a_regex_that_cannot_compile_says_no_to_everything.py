"""A PHP regex that fails to compile rejects everything, silently.

MEASURED 2026-08-16, while trying to run the first real AgentKit session.

`AgentLoader::isValidModelUri` carried a `/`-delimited pattern with an
unescaped `/` inside its character class:

    /^(<the provider alternation>)-[A-Za-z0-9._:/-]{1,96}$/

(alternation elided here so the one-provider-list sweep does not read a
historical quote as a live copy; the bug is the delimiter, not the list)

PCRE ends the pattern at that slash and reads `-]{1,96}$/` as modifiers:
`preg_match(): Unknown modifier '-'`. On a compile error `preg_match` returns
FALSE — and `(bool) false` is indistinguishable from "this string does not
match". Measured against every shape the estate uses:

    claude-sonnet                 => false
    anthropic-claude-sonnet-4-5   => false
    openclaw-qwen2.5-coder:32b    => false
    garbage                       => false          <- the tell

Rejecting `garbage` looked like the validator working. It was the validator
being unable to run. `AgentLoader::load()` therefore threw
`model.primary invalid` for EVERY agent, and AgentKit has never successfully
loaded one — the four rows in `agent_sessions` were written by the shell
bridge, which does not use this class. Bindings, session ceilings and fallback
attribution had all been built above a floor nothing had ever stood on, and
nothing reported it because nothing ever called it.

WHAT THIS PINS. Not the one pattern — that would be a note, not a gate. Every
PHP regex literal in the AgentKit tree is COMPILED, and one known-good and one
known-bad input are asserted for the validator that hid this. A pattern that
cannot compile must fail loudly here rather than by declining the world.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTKIT = REPO / "files/anatomy/wing/app/AgentKit"

#: `preg_*('…')` first argument, single-quoted PHP literal.
PREG = re.compile(r"preg_(?:match|match_all|replace|split|quote)\(\s*'((?:[^'\\]|\\.)*)'")


def _patterns() -> list[tuple[pathlib.Path, str]]:
    out = []
    for php in sorted(AGENTKIT.rglob("*.php")):
        for m in PREG.finditer(php.read_text(encoding="utf-8")):
            out.append((php, m.group(1)))
    return out


def test_the_sweep_finds_patterns():
    """Positive control: zero patterns would make the compile check vacuous."""
    found = _patterns()
    assert len(found) >= 3, (
        f"only {len(found)} regex literal(s) found under AgentKit; the "
        "extractor has stopped seeing them and this gate proves nothing."
    )


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
def test_every_agentkit_regex_compiles():
    """Ask PHP, not a Python approximation — the delimiter rules are PCRE's."""
    broken = []
    for path, pattern in _patterns():
        # The literal is single-quoted PHP; \' and \\ are its only escapes.
        php_literal = pattern.replace("\\", "\\\\").replace("'", "\\'")
        code = (
            "error_reporting(0);"
            f"$r = @preg_match('{php_literal}', 'x');"
            "echo $r === false ? 'BROKEN' : 'OK';"
        )
        res = subprocess.run(["php", "-r", code], capture_output=True, text=True)
        if res.stdout.strip() != "OK":
            broken.append(f"  {path.relative_to(REPO)}: {pattern}")
    assert not broken, (
        "PHP regex literal(s) that do not compile. preg_match returns FALSE on "
        "a compile error, so the caller reads it as 'no match' and the check "
        "silently rejects everything it is asked about:\n" + "\n".join(broken)
    )


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
def test_the_model_uri_validator_accepts_and_rejects():
    """The validator that hid this must prove it can still say YES.

    A compile-broken pattern says no to everything, which is why "it rejects
    garbage" was not evidence of anything. Both directions, or neither.
    """
    src = (AGENTKIT / "AgentLoader.php").read_text(encoding="utf-8")
    # Anchor on the METHOD DEFINITION, not the name. The first draft matched
    # from the earliest occurrence of `isValidModelUri` — which is its CALL
    # SITE near the top of the file — and so extracted the agent-NAME regex
    # that happens to come first, then reported a mismatch against a pattern
    # this test was never about.
    m = re.search(
        r"function isValidModelUri.*?preg_match\(\s*'((?:[^'\\]|\\.)*)'", src, re.S
    )
    assert m, "isValidModelUri no longer contains a regex literal"
    literal = m.group(1).replace("\\", "\\\\").replace("'", "\\'")
    for uri, expected in (
        ("claude-sonnet", True),
        ("anthropic-claude-sonnet-4-5", True),
        ("openclaw-qwen2.5-coder:32b", True),
        ("garbage", False),
    ):
        code = f"echo (int) (bool) @preg_match('{literal}', '{uri}');"
        got = subprocess.run(["php", "-r", code], capture_output=True, text=True).stdout
        assert got.strip() == str(int(expected)), (
            f"model URI {uri!r}: expected {expected}, got {got.strip()!r}. "
            "If everything now returns 0, the pattern has stopped compiling "
            "again and the loader will refuse every agent."
        )
