"""Anatomy CI gate — blank-reset must wipe every Docker bind-mount data dir.

tasks/removal-set.yml builds `_blank_dirs` (a set_fact) from ~50 conditional
ternary clauses, each `(install_<svc> | default(false)) | ternary([<dir>...], [])`.
Each clause maps an `install_*` feature flag to the host directories that the
matching service bind-mounts into its container.

A service that bind-mounts a host directory (e.g. `~/snappymail:/snappymail/data`)
is NOT cleaned by the `docker volume prune` step earlier in blank-reset.yml —
prune only removes named/anonymous Docker volumes, never host bind-mount paths.
So if such a service has an `install_*` flag + a `*_data_dir` default but no
clause in `_blank_dirs`, then `blank=true` orphans the old directory: the next
blank inherits stale data → cross-run data leakage / config inconsistency.

This gate:
  1. Asserts the `_blank_dirs` set_fact exists and is Jinja-parseable (the ternary
     soup stays syntactically sound).
  2. Extracts the set of `install_*` flags referenced inside `_blank_dirs`.
  3. Asserts every Docker-service flag that owns a persistent host bind-mount data
     dir (the REQUIRED contract below) is present in `_blank_dirs`.
  4. Verifies external-paths.yml is included BEFORE `_blank_dirs` is built, so
     `external_storage_root` overrides are visible to the wipe list.

The gate auto-fails when a new bind-mount service is added to default.config.yml
with an `install_*` flag + data dir but is not wired into `_blank_dirs`.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
REMOVAL_SET_PATH = REPO_ROOT / "tasks" / "removal-set.yml"
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"

# The contract is no longer a hand list here. A set a test can be edited to
# satisfy is not a gate; the required set is DERIVED from default.config.yml
# (every `*_dir` var) and reconciled against what removal-set.yml removes at
# some level or declares kept (`_removal_keep`, with a reason each).


def _extract_blank_dirs_expr() -> str:
    """Return the raw Jinja expression body of the _blank_dirs set_fact.

    Matches `_blank_dirs: >-` and captures the indented multi-line block that
    follows, up to the next less-indented YAML key.
    """
    src = REMOVAL_SET_PATH.read_text()
    match = re.search(
        r"\n    _blank_dirs:\s*>-\n(?P<body>(?:(?: {6,}.*)?\n)+)",
        src,
    )
    assert match, "could not locate the `_blank_dirs: >-` set_fact block"
    return match.group("body")


def _plays(path):
    return yaml.safe_load(path.read_text()) or []


def test_blank_dirs_set_fact_exists():
    """Parsed, not grepped: a comment naming `_blank_dirs` satisfied the old
    text assert, so the wipe could vanish with the gate still green."""
    assert any(
        "_blank_dirs" in (t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})
        for t in _plays(REMOVAL_SET_PATH)
    ), "_blank_dirs set_fact missing from removal-set.yml"
    assert [
        t for t in _plays(BLANK_RESET_PATH)
        if t.get("loop") == "{{ _blank_dirs }}"
        and (t.get("ansible.builtin.file") or t.get("file") or {}).get("state") == "absent"
    ], "no task removes the paths in _blank_dirs — a blank would leave the data dirs"


def test_blank_dirs_expression_is_jinja_parseable():
    """The ternary soup must stay syntactically sound (no broken edit)."""
    jinja2 = pytest.importorskip("jinja2")
    # The folded-scalar body is already a complete `{{ ... }}` Jinja expression;
    # parse it as-is so Jinja validates the full ternary-soup grammar.
    body = _extract_blank_dirs_expr()
    assert body.lstrip().startswith("{{") and body.rstrip().endswith("}}"), (
        "_blank_dirs body is not a self-contained {{ ... }} expression"
    )
    try:
        jinja2.Environment().parse(body)
    except jinja2.TemplateSyntaxError as exc:  # pragma: no cover - failure path
        pytest.fail(f"_blank_dirs Jinja expression is not parseable: {exc}")


DIR_VAR = re.compile(r"^([a-z0-9_]+_(?:data_dir|config_dir|cache_dir|certs_dir|books_dir|dir)):\s*(.*)$", re.M)
FAKE_HOME = "/H"


def _jinja():
    jinja2 = pytest.importorskip("jinja2")
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["ternary"] = lambda c, a, b: a if c else b
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    return env


def _config_ctx(env) -> dict:
    """default.config.yml with every install_* ON and the Jinja resolved, so a
    dir var like `{{ nos_data_root }}/platform/...` becomes a real path."""
    raw = yaml.safe_load((REPO_ROOT / "default.config.yml").read_text()) or {}
    ctx = {k: v for k, v in raw.items() if isinstance(v, (str, int, bool))}
    ctx.update({k: True for k in ctx if k.startswith("install_")})
    ctx["ansible_facts"] = {"env": {"HOME": FAKE_HOME}, "machine": "arm64"}
    for _ in range(6):  # nested refs settle in a few passes
        for k, v in list(ctx.items()):
            if isinstance(v, str) and "{{" in v:
                try:
                    ctx[k] = env.from_string(v).render(ctx)
                except Exception:
                    pass
    return ctx


def _dir_vars(ctx) -> dict[str, str]:
    text = (REPO_ROOT / "default.config.yml").read_text()
    out = {}
    for name, _ in DIR_VAR.findall(text):
        v = ctx.get(name)
        if isinstance(v, str) and v.startswith("/") and "{{" not in v:
            out[name] = v.rstrip("/")
    return out


def _levels(env, ctx) -> tuple[set[str], set[str], dict[str, dict]]:
    facts = {}
    for t in _plays(REMOVAL_SET_PATH):
        facts.update(t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})
    data = {r.rstrip("/") for r in yaml.safe_load(env.from_string(facts["_blank_dirs"]).render(ctx)) or []}
    all_ = {env.from_string(x).render(ctx).rstrip("/") for x in facts["_uninstall_source"]}
    keep = {k["var"]: k for k in facts["_removal_keep"]}
    assert all(k.get("why") and k.get("level") in ("all", "never") for k in keep.values()), (
        "every _removal_keep entry needs level: all|never and a why")
    return data, all_, keep


def _covered(path: str, removed: set[str]) -> bool:
    return any(path == r or path.startswith(r + "/") for r in removed)


def test_every_dir_var_is_removed_by_blank_or_declared_kept():
    """The reconciliation, at the DATA level — the one a blank runs. Rendered,
    not grepped: every `*_dir` var in default.config.yml resolves to a path,
    and that path is under something remove=data deletes, or it is in
    `_removal_keep` with the level that does remove it and a reason.

    Written against the broken state first: 7 bind-mount dirs (stalwart,
    mailpit, watchtower, hedgedoc config, calibreweb config, both certs dirs)
    survived every blank — all under nos_data_root, which only remove=all
    takes, so a gate that merged the levels was blind to them (the first draft
    of this one was). The calibreweb clause also wiped a literal path the var
    had left behind. The old hand list here was green throughout."""
    env = _jinja()
    ctx = _config_ctx(env)
    dirs = _dir_vars(ctx)
    assert len(dirs) > 40, f"the resolver lost the config: only {len(dirs)} dir vars rendered"
    data, all_, keep = _levels(env, ctx)
    orphans = {k: v for k, v in dirs.items() if not _covered(v, data) and k not in keep}
    assert not orphans, (
        "these default.config.yml dirs survive remove=data and are not declared "
        "in tasks/removal-set.yml `_removal_keep`:\n  "
        + "\n  ".join(f"{k} = {v}" for k, v in sorted(orphans.items()))
    )
    stale = sorted(k for k in keep if k in dirs and _covered(dirs[k], data))
    assert not stale, f"declared kept but remove=data takes them — drop from _removal_keep: {stale}"
    wrong_level = sorted(k for k, e in keep.items() if k in dirs
                         and (e["level"] == "all") != _covered(dirs[k], all_))
    assert not wrong_level, f"_removal_keep level disagrees with what remove=all removes: {wrong_level}"


def test_the_removal_set_names_no_dir_the_config_does_not_have():
    """A clause referencing a var default.config.yml no longer defines wipes
    the fallback literal, i.e. usually nothing (calibreweb did exactly that)."""
    body = _extract_blank_dirs_expr()
    cfg = (REPO_ROOT / "default.config.yml").read_text()
    role_defaults = "".join(p.read_text() for p in (REPO_ROOT / "roles").glob("*/defaults/main.yml"))
    referenced = set(re.findall(r"\b([a-z0-9_]+_dir)\b", body))
    unknown = sorted(v for v in referenced
                     if not re.search(rf"^{v}:", cfg, re.M) and not re.search(rf"^{v}:", role_defaults, re.M))
    assert not unknown, f"_blank_dirs references dir vars nothing defines: {unknown}"


def test_external_paths_included_before_blank_dirs():
    """external-paths.yml must run BEFORE _blank_dirs so storage overrides apply.

    external_storage_root rewrites *_data_dir to /Volumes/... If the include ran
    after the set_fact, blank would wipe the empty ~/service fallbacks and leave
    the real external data behind.
    """
    src = REMOVAL_SET_PATH.read_text()
    ext_idx = src.find("stacks/external-paths.yml")
    blank_idx = src.find("_blank_dirs:")
    assert ext_idx != -1, "external-paths.yml include missing from removal-set.yml"
    assert blank_idx != -1, "_blank_dirs set_fact missing"
    assert ext_idx < blank_idx, (
        "external-paths.yml must be included BEFORE _blank_dirs is built so "
        "external_storage_root overrides are visible to the wipe list"
    )
