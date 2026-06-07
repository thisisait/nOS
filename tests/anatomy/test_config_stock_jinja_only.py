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


# ── Second {{ vars }}-safety gate: every ref must be defined before core-up ───
# A var referenced ONLY through `{{ foo | default(<x>) }}` looks safe, but under
# the eager `template_vars: "{{ vars }}"` resolution a genuinely-undefined var
# aborts the whole run *despite* the default() guard — it does NOT reproduce in an
# isolated `{{ vars }}` finalize, only the full-namespace core-up run does. It bit
# mysqld_exporter_password + the akadmin/oidc seed twins, then app_secrets (whose
# only definition is the apps_runner role default — which loads AFTER core-up) and
# tester_password_prefix (defined nowhere). The robust convention: EVERY identifier
# a committed vars-file references in a value must resolve from something loaded
# BEFORE the core-up loader — a key in default.config.yml / default.credentials.yml
# / tests/config.yml, a main.yml var/set_fact, an ansible fact, or a stock builtin.
# A role default does NOT count (its role is invoked during stack-up, after core-up).
_RUNTIME = {
    "item", "global_password_prefix", "playbook_dir", "inventory_hostname",
    "hostvars", "vars", "ansible_facts", "lookup", "now", "range", "namespace",
    "tenant_domain", "previous_password_prefix", "ansible_become_password",
    "nos_sudo_password", "omit", "undef",
}
_BUILTINS = {
    "default", "trim", "length", "replace", "lower", "upper", "int", "float",
    "join", "list", "map", "select", "selectattr", "reject", "rejectattr",
    "first", "last", "sort", "unique", "min", "max", "sum", "string", "bool",
    "items", "dictsort", "d", "abs", "round", "title", "capitalize", "ternary",
    "equalto", "not", "is", "in", "and", "or", "if", "else", "elif", "for",
    "endif", "endfor", "true", "false", "none", "True", "False", "None",
}


def _defined_before_core_up() -> set[str]:
    names: set[str] = set()
    for path in VARS_FILES + [REPO / "tests" / "config.yml"]:
        for line in path.read_text().splitlines():
            m = re.match(r"^([a-zA-Z_]\w*):", line)
            if m:
                names.add(m.group(1))
    # any key (play var or set_fact, at any indent) defined in main.yml
    for line in (REPO / "main.yml").read_text().splitlines():
        m = re.match(r"^\s*([a-z_]\w*):\s", line)
        if m:
            names.add(m.group(1))
    return names


def _head_refs(path: pathlib.Path) -> dict[str, tuple[int, int]]:
    refs: dict[str, tuple[int, int]] = {}
    for ln, line in enumerate(path.read_text().splitlines(), 1):
        for expr in re.findall(r"\{\{(.*?)\}\}", line) + re.findall(r"\{%(.*?)%\}", line):
            s = re.sub(r"'(?:[^'\\]|\\.)*'", "''", expr)
            s = re.sub(r'"(?:[^"\\]|\\.)*"', '""', s)
            for m in re.finditer(r"(?<![\.\w])([a-z_][a-z0-9_]*)\b", s):
                ident = m.group(1)
                rest = s[m.end():].lstrip()
                # skip filter/function/method names and kwargs (`foo(` / `foo=`)
                if rest.startswith("(") or rest.startswith("="):
                    continue
                cnt, _ = refs.get(ident, (0, ln))
                refs[ident] = (cnt + 1, refs.get(ident, (0, ln))[1])
    return refs


def test_varsfile_refs_resolve_before_core_up():
    known = _defined_before_core_up() | _RUNTIME | _BUILTINS
    offenders: list[str] = []
    for path in VARS_FILES:
        for ident, (n, ln) in sorted(_head_refs(path).items()):
            if ident in known or ident.startswith("ansible_"):
                continue
            offenders.append(f"{path.name}:{ln} `{ident}` referenced {n}x, undefined at core-up")
    assert not offenders, (
        "A var referenced in a committed vars-file value is not defined by anything "
        "that loads BEFORE the core-up `template_vars: \"{{ vars }}\"` loader (role "
        "defaults don't count — they load during stack-up). The eager resolution "
        "aborts on it even behind `| default()`. Add a real default in "
        "default.config.yml / default.credentials.yml. Offenders:\n  "
        + "\n  ".join(offenders)
    )


# ── Third {{ vars }}-safety gate: no ansible filter inside an inline loop dict ─
# A non-stock filter inside an inline `loop:` item (`- { k: "{{ x | bool }}" }`)
# is compiled in a filter-less context on a full ansible-core 2.20.6 run and
# throws "No filter named '<x>'" — exactly the vars-file trap, in a task body
# (it bit tasks/stacks/core-up.yml's data-dir loop, 2026-06-06). It does NOT
# reproduce in isolation, only the live run. Keep inline loop-item fields on
# stock Jinja (default/trim/replace/operators); a real boolean needs no `| bool`.
_NONSTOCK_IN_LOOP_ITEM = re.compile(
    r"^\s*-\s*\{.*\|\s*(bool|regex_replace|regex_search|regex_findall|b64encode|"
    r"b64decode|hash|password_hash|to_uuid|combine|json_query|ipaddr|to_json|"
    r"from_json|to_nice_yaml|from_yaml|to_datetime|strftime|map|zip)\b"
)


def test_no_nonstock_filter_in_inline_loop_items():
    offenders: list[str] = []
    roots = list((REPO / "tasks").rglob("*.yml"))
    roots += [p for d in (REPO / "roles").glob("*/tasks") for p in d.rglob("*.yml")]
    roots.append(REPO / "main.yml")
    for p in roots:
        for ln, line in enumerate(p.read_text().splitlines(), 1):
            if _NONSTOCK_IN_LOOP_ITEM.match(line):
                offenders.append(f"{p.relative_to(REPO)}:{ln}")
    assert not offenders, (
        "A non-stock (ansible) filter sits inside an inline `loop:` dict item. On a "
        "full ansible-core 2.20.6 run that template is compiled in a filter-less "
        "context and throws 'No filter named'. Use stock Jinja in loop-item fields "
        "(a real boolean needs no `| bool`). Offenders:\n  " + "\n  ".join(sorted(offenders))
    )
