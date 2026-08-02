"""A JSON `null` is DEFINED — the one-arg `default('')` does not catch it.

Jinja's `default(x)` substitutes an UNDEFINED value. An API that answers
`{"setup-token": null}` therefore yields a key that IS defined, holding None,
and the filter hands the None straight to whatever comes next. When that is
`| length`, the play does not take the fallback branch — it ABORTS:

    The filter plugin 'ansible.builtin.length' failed:
    object of type 'NoneType' has no len()

Metabase does exactly this once setup completes (2026-08-02), which meant its
setup task had never once run against an already-configured Metabase. The
two-arg form `default('', true)` is the one that treats null as empty.

The defect has two shapes and the second is why this is not a one-line regex:

  same-line   `_r.json.paths | default({}) | length > 0`
  cross-line  `set_fact: tok: "{{ _r.json['setup-token'] | default('') }}"`
              … later …  `when: tok | default('') | length > 0`

The metabase bug was the cross-line shape, so a scanner that only reads single
expressions would have shipped green against the very defect it was written
for. This one carries the laundered fact name forward within its file.

Scope is deliberately narrow: only filters that RAISE on None. Jinja's `int`
and `float` catch TypeError and return their default, and `trim` stringifies —
those produce wrong values, not aborted runs, and belong to a different gate.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEARCH_DIRS = ("roles", "tasks", "files/anatomy/plugins")

#: Filters that raise rather than degrade when handed None.
NULL_INTOLERANT = ("length", "b64decode", "from_json")
_FILT = "|".join(NULL_INTOLERANT)

#: one-arg default() — the negative case is the two-arg form, which is correct
_ONE_ARG_DEFAULT = r"""\|\s*default\(\s*(?:'[^']*'|"[^"]*"|\[\]|\{\}|0)\s*\)"""

#: `<reg>.json…` or `<reg>.content` — a registered HTTP response body
_RESPONSE_BODY = r"\w+\.(?:json|content)\b[^|{}]*?"

SAME_LINE = re.compile(
    rf"({_RESPONSE_BODY}){_ONE_ARG_DEFAULT}\s*\|\s*({_FILT})\b"
)

#: `set_fact:` entry laundering a response body through a one-arg default
LAUNDER = re.compile(
    rf"^\s*(?P<fact>\w+):\s*[\"']?\{{\{{\s*(?P<expr>{_RESPONSE_BODY}){_ONE_ARG_DEFAULT}"
)


def _yaml_files() -> list[Path]:
    out: list[Path] = []
    for d in SEARCH_DIRS:
        root = REPO / d
        if root.is_dir():
            out.extend(p for p in root.rglob("*.yml") if p.is_file())
    return sorted(out)


def _scan(text: str) -> list[tuple[int, str]]:
    """Return (lineno, message) for every null-unsafe use in one file."""
    found: list[tuple[int, str]] = []
    laundered: dict[str, tuple[int, str]] = {}
    lines = text.splitlines()

    for lineno, line in enumerate(lines, 1):
        if "default(" not in line:
            continue

        m = SAME_LINE.search(line)
        if m:
            found.append(
                (lineno, f"{m.group(1).strip()} | default(…) | {m.group(2)}")
            )

        lm = LAUNDER.match(line)
        if lm:
            laundered[lm.group("fact")] = (lineno, lm.group("expr").strip())

    if not laundered:
        return found

    # Second pass: does a laundered fact ever meet a null-intolerant filter?
    consumer = re.compile(
        rf"\b(?P<fact>{'|'.join(re.escape(f) for f in laundered)})\b"
        rf"(?:\s*{_ONE_ARG_DEFAULT})?\s*\|\s*(?P<filt>{_FILT})\b"
    )
    for lineno, line in enumerate(lines, 1):
        cm = consumer.search(line)
        if cm:
            src_line, src_expr = laundered[cm.group("fact")]
            found.append(
                (
                    lineno,
                    f"{cm.group('fact')} | {cm.group('filt')} — laundered from "
                    f"`{src_expr}` at line {src_line}",
                )
            )
    return found


def test_no_response_body_reaches_a_null_intolerant_filter_through_a_one_arg_default():
    offenders: list[str] = []
    for path in _yaml_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, msg in _scan(text):
            offenders.append(f"{path.relative_to(REPO)}:{lineno}: {msg}")

    assert not offenders, (
        "One-arg default() cannot absorb a JSON null; the next filter aborts the "
        "play instead of taking the fallback branch. Use default(x, true):\n  "
        + "\n  ".join(offenders)
    )


def test_the_scanner_catches_the_defect_it_was_written_for():
    """Retro-check against the real pre-fix metabase text, both shapes."""
    pre_fix = """
- name: Get setup token
  ansible.builtin.set_fact:
    _mb_setup_token: "{{ _mb_props.json['setup-token'] | default('') }}"

- name: Run initial setup
  when:
    - _mb_setup_token | default('') | length > 0
"""
    hits = _scan(pre_fix)
    assert hits, "the cross-line shape — the actual metabase bug — must be caught"
    assert any("laundered from" in msg for _, msg in hits)

    fixed = pre_fix.replace("default('')", "default('', true)")
    assert _scan(fixed) == [], "the two-arg form is the fix and must pass"

    assert _scan("  when: _r.json.paths | default({}) | length > 0"), (
        "the same-line shape must be caught too"
    )
