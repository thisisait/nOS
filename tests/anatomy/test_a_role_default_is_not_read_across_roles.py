"""A role may not freeze another role's COMPUTED default into a constant guess.

WHAT HAPPENED. On 2026-06-14 a commit pinned `sslmode=require` for the
PostgreSQL clients — "fix(postgresql): require-pin hedgedoc+paperclip SSL",
with a gate. Two months later REM-217 measured the estate and found the vault,
Outline, HedgeDoc and 22 of Authentik's backends reaching PostgreSQL in
cleartext.

The pin had never rendered. Every one of those templates decides with

    {{ 'require' if (postgresql_ssl_enabled | default(false)) else 'prefer' }}

and `postgresql_ssl_enabled` was declared in `roles/pazny.postgresql/defaults/
main.yml` as `{{ ansible_os_family == 'Darwin' }}`. A role default is not in
scope for a DIFFERENT role's render, so in all four consumers the name resolved
to nothing and `| default(false)` supplied the answer. Confirmed in the rendered
artifacts rather than reasoned from the templates: `~/stacks/*/overrides/
{hedgedoc,paperclip,authentik}.yml` all say `prefer` on a macOS host, and the
live paperclip container's env agrees — while the server override two
directories away says `ssl=on`.

The existing gate read the TEMPLATE and passed for two months. That is the
estate's standing division of labour failing in the direction it warns about:
pytest owns the shape, `--tags verify` owns the effect. The shape was perfect.

THE PRECISE DEFECT, which is narrower than "cross-role read". Reading another
role's default is often harmless — `pazny.postgresql/tasks/post.yml` reads
`hedgedoc_db_name | default('hedgedoc')` and the fallback IS the declaration,
so the wrong-scope path produces the right value. What is never harmless is a
CONSTANT fallback standing in for a COMPUTED declaration: the owner works the
value out from the host, the reader hard-codes a guess, and the guess wins
silently on every host where the two disagree. `false` against
`{{ ansible_os_family == 'Darwin' }}` is that shape exactly, and the direction
it failed was open.

THE FIX this gate protects: `postgresql_ssl_enabled` now lives in
`default.config.yml`, at play scope, where every consumer can see it. The role
default stays as a fallback so the role remains usable alone.

WHAT THIS GATE CANNOT DO. It cannot tell whether a value that IS in scope is
correct, and it cannot see a render that never happened. Only
`tools/tls-uptake.py` and a converge can say what the estate actually
negotiates.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

PLAY_SCOPE_FILES = ("default.config.yml", "default.credentials.yml")

#: A declaration Ansible has to WORK OUT — from facts, from another var, from a
#: filter. A constant standing in for one of these is the failure mode.
COMPUTED = re.compile(r"\{\{|\{%")

#: A fallback that is a bare LITERAL: a bool, a number, a quoted string, or an
#: empty container. Anything else — a bare name, a subscript, a filter — is the
#: reader computing too, which is not the shape this gate is about.
#:
#: The braces test is not enough on its own, and the first cut of this gate
#: proved it: inside a Jinja expression `default(ansible_facts['env']['HOME'] +
#: '/x')` needs no `{{`, so three benign sites were reported as offenders. Two
#: of them differ from their declaration only in spelling `~` as `+`.
LITERAL = re.compile(
    r"""^(?: true|false|none|null|omit          # keywords
        | -?\d+(?:\.\d+)?                        # numbers
        | '[^']*' | "[^"]*"                      # quoted strings
        | \[\s*\] | \{\s*\}                      # empty containers
        )$""",
    re.X | re.I)

#: `name | default(<fallback>)` inside a Jinja expression.
FALLBACK = re.compile(r"([a-z_][a-z0-9_]{2,})\s*\|\s*default\(\s*([^()]*?)\s*\)")
EXPRESSION = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.S)


def _play_scope() -> set[str]:
    names: set[str] = set()
    for name in PLAY_SCOPE_FILES:
        data = yaml.safe_load((REPO / name).read_text(encoding="utf-8")) or {}
        names |= set(data)
    return names


def _role_declarations() -> tuple[dict[str, set[str]], dict[str, object]]:
    owner: dict[str, set[str]] = {}
    value: dict[str, object] = {}
    for path in sorted(REPO.glob("roles/*/defaults/main.yml")):
        role = path.relative_to(REPO).parts[1]
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key, val in data.items():
            owner.setdefault(key, set()).add(role)
            value[key] = val
    return owner, value


def _consumers():
    yield from sorted(REPO.glob("roles/*/templates/**/*.j2"))
    yield from sorted(REPO.glob("roles/*/tasks/*.yml"))


def test_no_constant_fallback_stands_in_for_a_computed_default():
    play = _play_scope()
    owner, declared = _role_declarations()
    offenders: list[str] = []

    for path in _consumers():
        role = path.relative_to(REPO).parts[1]
        text = path.read_text(encoding="utf-8", errors="ignore")
        blob = "\n".join((a or b) for a, b in EXPRESSION.findall(text))
        for name, fallback in FALLBACK.findall(blob):
            if name in play or name not in owner or role in owner[name]:
                continue
            declaration = str(declared[name])
            if not COMPUTED.search(declaration):
                continue                      # the owner's value is a constant too
            if not LITERAL.match(fallback.strip()):
                continue                      # the reader computes as well — not this shape
            offenders.append(
                f"{path.relative_to(REPO)}: `{name} | default({fallback})` — "
                f"{'/'.join(sorted(owner[name]))} computes it as {declaration!r}, "
                "and that role's defaults are not in scope here")

    assert not offenders, (
        "a constant is standing in for a value another role works out from the "
        "host, and it wins silently wherever the two disagree:\n  "
        + "\n  ".join(offenders)
        + "\n(this is how `sslmode=require` was pinned in June and rendered "
          "`prefer` on every host until 2026-08-23 — move the declaration to "
          "default.config.yml so every consumer resolves the same value)")


def test_the_variable_this_gate_was_written_for_is_at_play_scope():
    """The specific regression, named. If `postgresql_ssl_enabled` ever goes
    back to being only a role default, four templates silently return to
    permitting cleartext and the gate above would not fire — the name would
    simply be unknown again, which is the state that caused this."""
    assert "postgresql_ssl_enabled" in _play_scope(), (
        "postgresql_ssl_enabled is no longer declared in default.config.yml; "
        "authentik, hedgedoc, infisical and paperclip all read it to decide "
        "their sslmode and none of them can see a pazny.postgresql role default")
