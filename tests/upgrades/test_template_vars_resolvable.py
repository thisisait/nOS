"""Gate: every ``{{ token }}`` in an upgrade recipe resolves at apply time.

The engine renders recipe step strings through Jinja2 with ``StrictUndefined``
(``nos_migrate._apply_upgrade``), so a typo'd or undefined variable aborts the
step — and, since the 2026-06-08 dry-run fix, it now also fails the dry-run.
This gate catches that BEFORE merge, which is the safety net the agent
recipe-authoring path (upgrade-architect → PR) relies on.

A reference is considered resolvable when its base identifier is:
  * an engine runtime token (upgrade_id / recipe / installed / ...), or
  * a key defined in default.config.yml / default.credentials.yml /
    tests/config.yml / any role's defaults (these become play-vars the
    controller hands to the engine as tmpl_vars), or
  * guarded by ``| default(...)`` in the same expression (then undefined is
    fine — Jinja falls through to the default).
"""

from __future__ import absolute_import, division, print_function

import os
import re
import glob

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

ENGINE_TOKENS = {"upgrade_id", "recipe", "installed", "run_ts", "service",
                 "from_version_resolved"}

# Jinja2 builtins + the stock filters recipes use — never a "variable".
JINJA_NAMES = {
    "default", "trim", "length", "replace", "lower", "upper", "int", "string",
    "join", "list", "bool", "expanduser", "first", "last", "b64encode",
    "b64decode", "regex_replace", "regex_search", "basename", "dirname",
    "to_json", "from_json", "map", "select", "reject", "unique", "sort", "min",
    "max", "round", "abs", "truncate", "split", "capitalize", "title", "items",
    "true", "false", "none", "True", "False", "None", "and", "or", "not",
    "if", "else", "in", "is",
}

_EXPR = re.compile(r"\{\{(.*?)\}\}", re.S)
_STRLIT = re.compile(r"'[^']*'|\"[^\"]*\"")
_FILTER = re.compile(r"\|\s*[a-zA-Z_][a-zA-Z0-9_]*")
_TOKEN = re.compile(r"(?<![.\w])([a-zA-Z_][a-zA-Z0-9_]*)")   # not after '.' (attr) / word char


def _top_keys(path):
    keys = set()
    try:
        with open(path) as fh:
            for line in fh:
                m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):", line)
                if m:
                    keys.add(m.group(1))
    except FileNotFoundError:
        pass
    return keys


def _known_names():
    known = set(ENGINE_TOKENS)
    for rel in ("default.config.yml", "default.credentials.yml", "tests/config.yml"):
        known |= _top_keys(os.path.join(ROOT, rel))
    for f in glob.glob(os.path.join(ROOT, "roles", "pazny.*", "defaults", "main.yml")):
        known |= _top_keys(f)
    return known


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _unresolved(recipe_path, known):
    with open(recipe_path) as fh:
        data = yaml.safe_load(fh)
    bad = set()
    for s in _strings(data):
        for expr in _EXPR.findall(s):
            if "default(" in expr.replace(" ", ""):
                continue   # guarded — undefined is acceptable
            de = _FILTER.sub("|", _STRLIT.sub("", expr))   # drop literals + filter names
            for ident in _TOKEN.findall(de):
                if ident in known or ident in JINJA_NAMES:
                    continue
                bad.add("%s  <<  {{ %s }}" % (ident, expr.strip()[:70]))
    return sorted(bad)


def test_all_recipe_template_vars_resolvable():
    known = _known_names()
    failures = {}
    for recipe in sorted(glob.glob(os.path.join(ROOT, "upgrades", "*.yml"))):
        if os.path.basename(recipe) == "_template.yml":
            continue   # authoring template carries example placeholders
        bad = _unresolved(recipe, known)
        if bad:
            failures[os.path.basename(recipe)] = bad
    assert not failures, (
        "Upgrade recipe(s) reference variables that won't resolve at apply "
        "(StrictUndefined aborts the step). Define the var, or guard it with "
        "| default(...):\n" + "\n".join(
            "  %s:\n    %s" % (r, "\n    ".join(v)) for r, v in sorted(failures.items())))
