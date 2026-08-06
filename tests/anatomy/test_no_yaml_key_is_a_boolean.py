"""`on:` is not a key. It is `True`.

YAML 1.1 — which is what PyYAML parses, and therefore what Ansible parses —
coerces a bare `on`, `off`, `yes`, `no`, `y`, `n`, `true` and `false` to
booleans. As a VALUE that is merely surprising. As a KEY it is a silent rename:
the mapping you wrote as `{file: x, on: y}` becomes `{file: x, True: y}`, and
every later `item.on` looks up a field that does not exist.

TWICE IN ONE DAY, 2026-08-06:

  1. The anatomy graph's edge field was drafted as `on:` and had to become
     `upstream:`; it was reported the same morning, with the reproduction
     `yaml.safe_load("on: x")` → `{True: "x"}`.
  2. Hours later a mu-plugin removal loop in `roles/pazny.wordpress` was
     written with `on:` anyway. Every item failed the converge with
     "object of type 'dict' has no attribute 'on'", and the rendered item
     printed as `{file: ..., true: true}` — the tell, for anyone who knew to
     look for it.

Being told about a trap and walking into it hours later is an argument for a
gate, not for more care. This is that gate.

WHY THE EXISTING GATE COULD NOT SEE IT: `test_a_flag_removes_what_it_staged.py`
reads the same loop and looks for `.php` filenames among each item's VALUES.
That is true whatever the KEY is called, so it stayed green while the task was
unrunnable. It tested the shape and not the runtime — which is worth stating
plainly, because a green gate over broken code is the thing this suite exists
to prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

#: Every directory whose YAML is consumed by Ansible, the plugin loader, the
#: agent runtime or the manifest parsers. A boolean key in any of them is a
#: field nobody can address.
ROOTS = ("roles", "tasks", "files/anatomy/plugins", "files/anatomy/agents",
         "state", "apps", "upgrades", "profiles")


def _yaml_files() -> list[Path]:
    out: list[Path] = []
    for root in ROOTS:
        base = REPO / root
        if base.is_dir():
            out += [p for p in base.rglob("*.yml") if "node_modules" not in p.parts]
    return sorted(out)


def _boolean_keys(node, path: str, found: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            # `is True` / `is False` rather than `in (True, False)`: 1 and 0
            # compare equal to the booleans in Python and are legitimate keys.
            if key is True or key is False:
                found.append((path, repr(key)))
            _boolean_keys(value, f"{path}.{key}", found)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _boolean_keys(value, f"{path}[{i}]", found)


def test_no_mapping_key_was_coerced_to_a_boolean():
    files = _yaml_files()
    assert len(files) > 300, (
        f"only {len(files)} YAML files found — this gate has gone blind rather "
        f"than green; check ROOTS still points at the estate"
    )

    offenders: list[str] = []
    for path in files:
        try:
            docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue  # a file that will not parse is another gate's problem
        for doc in docs:
            found: list[tuple[str, str]] = []
            _boolean_keys(doc, "", found)
            for where, key in found:
                offenders.append(f"{path.relative_to(REPO)}:{where or '<root>'} → key {key}")

    assert not offenders, (
        "these mappings have a key YAML 1.1 turned into a boolean. The field "
        "you wrote cannot be addressed by the name you wrote it with — "
        "`item.on` raises \"object of type 'dict' has no attribute 'on'\" at "
        "converge time, not at lint time:\n  " + "\n  ".join(offenders)
    )


#: MEASURED, not taken from the YAML 1.1 spec. The spec also lists `y` and `n`,
#: and PyYAML's resolver does NOT coerce those — this control test said it did
#: until it was run, which is the whole reason a positive control exists.
@pytest.mark.parametrize("word", ["on", "off", "yes", "no", "true", "false"])
def test_the_coercion_this_gate_guards_against_is_real(word):
    """Positive control, per word. If PyYAML ever stopped coercing these, the
    gate above would be guarding nothing and should be re-derived rather than
    left as decoration."""
    parsed = yaml.safe_load(f"{word}: value")
    assert isinstance(next(iter(parsed)), bool), (
        f"PyYAML no longer coerces the key {word!r} to a boolean — YAML 1.1 "
        f"behaviour changed, and this gate's premise needs re-checking"
    )


def test_the_wordpress_loop_is_addressable():
    """The instance that broke a converge, pinned directly.

    The generic scan above would catch it, but a named regression test is what
    tells the next reader WHY the key is spelled `enabled`.
    """
    tasks = yaml.safe_load((REPO / "roles/pazny.wordpress/tasks/main.yml").read_text(encoding="utf-8"))
    loops = [t for t in tasks
             if isinstance(t, dict) and isinstance(t.get("ansible.builtin.file"), dict)
             and t["ansible.builtin.file"].get("state") == "absent"]
    assert loops, "the mu-plugin removal task is gone"
    for task in loops:
        for item in task.get("loop") or []:
            assert isinstance(item, dict), f"loop item is not a mapping: {item!r}"
            assert all(isinstance(k, str) for k in item), (
                f"a loop item key was coerced: {item!r}"
            )
            when = str(task.get("when", ""))
            for key in item:
                if key != "file":
                    assert f"item.{key}" in when, (
                        f"the loop declares {key!r} and the condition {when!r} "
                        f"does not read it — the item field and the condition "
                        f"have drifted apart, which is how this broke"
                    )
