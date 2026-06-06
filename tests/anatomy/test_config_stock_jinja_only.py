"""Anatomy gate — committed vars-files use STOCK Jinja2 filters only.

WHY: the plugin loader is invoked with `template_vars: "{{ vars }}"`
(tasks/stacks/core-up.yml et al.). ansible-core's post-2.19 templating engine
eagerly resolves the ENTIRE play-var namespace during module-arg finalization,
in a context where ANSIBLE filter plugins are NOT loaded. So any value in a
vars-file that uses a non-stock filter (regex_replace, regex_search, bool,
b64encode, hash, …) throws "No filter named '<x>'" and aborts the run — but
only on a host that reaches the loader (ubuntu CI; macOS skips stacks when
Docker is absent). That made it a slow-wet-test-only failure. This gate catches
a reintroduction offline, in the fast Pytest job. See the doctrine note at
`default.config.yml` `_host_alias_normalized` (hotfix 2026-06-06).

If you legitimately need a transform, express it with Jinja2 core builtins
(default, trim, length, replace, .endswith()/.startswith(), operators) — NOT an
ansible filter — for any var that lands in the eagerly-resolved namespace.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

# Files whose values stay LAZY (`{{ }}` strings) until referenced, so they are
# walked by the `{{ vars }}` eager resolver. default.credentials.yml is included
# because it is a committed vars_files entry loaded the same way.
VARS_FILES = [
    REPO / "default.config.yml",
    REPO / "default.credentials.yml",
]

# Jinja2 CORE builtins (always present, even when ansible filter plugins are
# not loaded). Anything NOT here is an ansible filter plugin and is forbidden.
STOCK = {
    "abs", "attr", "batch", "capitalize", "center", "d", "default", "dictsort",
    "e", "escape", "filesizeformat", "first", "float", "forceescape", "format",
    "groupby", "indent", "int", "join", "last", "length", "list", "lower",
    "map", "max", "min", "pprint", "random", "reject", "rejectattr", "replace",
    "reverse", "round", "safe", "select", "selectattr", "slice", "sort",
    "string", "striptags", "sum", "title", "tojson", "trim", "truncate",
    "unique", "upper", "urlencode", "urlize", "wordcount", "wordwrap", "items",
}


def _filters_in(path: pathlib.Path) -> dict[str, int]:
    txt = path.read_text()
    exprs = re.findall(r"\{\{(.*?)\}\}", txt, re.S) + re.findall(r"\{%(.*?)%\}", txt, re.S)
    hits: dict[str, int] = {}
    for e in exprs:
        # blank out quoted string literals so regex-argument `|` alternations
        # (e.g. '^\.+|\.+$') are not mistaken for filter pipes
        s = re.sub(r"'(?:[^'\\]|\\.)*'", "''", e)
        s = re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)
        for m in re.finditer(r"\|\s*([a-zA-Z_]\w*)", s):
            hits[m.group(1)] = hits.get(m.group(1), 0) + 1
    return hits


def test_vars_files_use_stock_jinja_filters_only():
    offenders: list[str] = []
    for path in VARS_FILES:
        for filt, n in sorted(_filters_in(path).items()):
            if filt not in STOCK:
                offenders.append(f"{path.name}: `| {filt}` ({n}x)")
    assert not offenders, (
        "Non-stock (ansible) filters in a vars-file value break the "
        "`template_vars: \"{{ vars }}\"` eager resolution on ubuntu CI. "
        "Rewrite with Jinja2 core builtins. Offenders:\n  " + "\n  ".join(offenders)
    )
