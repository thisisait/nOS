"""One journey through the plugin loader: its manifests, the conditions and notes it
evaluates, the commands it runs and the plays that hand it a context.

Absorbed (2026-11-10, roadmap gate-diet), one section each:
  test_plugin_wiring_contract, test_a_plugin_loads_when_its_role_runs,
  test_plugin_templates_are_rendered, test_plugin_conditions_know_ansible_filters,
  test_plugin_docker_exec_splits_like_a_shell, test_plugin_hook_changed_is_measured,
  test_plugin_loader_ctx_is_a_snapshot.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import functools
import json
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402
from _repo_walk import repo_files

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"


# ── test_plugin_wiring_contract ─────────────────────────────────────────────
# Plugins were authored by different passes and coverage drifted: qdrant-base ran
# its wait_health on every run regardless of toggle. Pinned: schema-valid
# manifests, a gate on every service plugin that names a real toggle, an acyclic
# DAG, and the A9 severity shape for notification blocks.

SCHEMA_PATH = REPO / "state" / "schema" / "plugin.schema.json"
CANONICAL_SEVERITIES = {"on_critical", "on_high", "on_medium", "on_low", "on_info"}


def _known_toggles() -> set[str]:
    """Top-level var names in default.config.yml (the toggle namespace)."""
    raw = ni.default_config_text()
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", raw)
    return set((yaml.safe_load(raw) or {}).keys())


@functools.cache  # parametrize + ids re-walked it per use at collection
def _all_plugins() -> list[load_plugins.Plugin]:
    return load_plugins.discover(PLUGINS_ROOT)


def _service_plugins() -> list[load_plugins.Plugin]:
    return [p for p in _all_plugins()
            if "service" in (p.manifest.get("type") or [])]


def _plugin_ids(plugins) -> list[str]:
    return [p.name for p in plugins]


def test_all_manifests_validate_against_schema():
    """Every plugin.yml passes schema validation (jsonschema or fallback)."""
    schema = json.loads(SCHEMA_PATH.read_text())
    failures = {}
    for p in _all_plugins():
        errs = load_plugins.validate_manifest(p.manifest, schema)
        if errs:
            failures[p.name] = errs
    assert not failures, (
        "schema validation failures:\n" +
        "\n".join(f"  {n}: {e}" for n, e in failures.items()))


@pytest.mark.parametrize("plugin", _service_plugins(), ids=_plugin_ids(_service_plugins()))
def test_service_plugin_has_a_gate(plugin):
    """Every service plugin declares requires.feature_flag OR requires.app.

    Without a gate, the loader runs the plugin's lifecycle hooks on every
    playbook run — which is how qdrant-base's :6333 wait_health degraded
    every run before it gained feature_flag: install_qdrant.
    """
    req = plugin.manifest.get("requires") or {}
    assert req.get("feature_flag") or req.get("app"), (
        f"{plugin.name}: service plugin must declare requires.feature_flag "
        f"or requires.app")


@pytest.mark.parametrize("plugin", _service_plugins(), ids=_plugin_ids(_service_plugins()))
def test_feature_flag_resolves_to_real_toggle(plugin):
    """A declared feature_flag must be a real var in default.config.yml."""
    req = plugin.manifest.get("requires") or {}
    flag = req.get("feature_flag")
    if not flag:
        pytest.skip(f"{plugin.name} is app-gated, no feature_flag")
    assert flag in _known_toggles(), (
        f"{plugin.name}: feature_flag {flag!r} is not a toggle in "
        f"default.config.yml (typo?)")


def test_dag_resolves_without_cycles():
    """topological_order must not raise on the real plugin set."""
    load_plugins.topological_order(_all_plugins())


@pytest.mark.parametrize("plugin", _service_plugins(), ids=_plugin_ids(_service_plugins()))
def test_notification_block_uses_canonical_severity_shape(plugin):
    """notification blocks use the A9 severity-routing keys.

    The wing-base aggregator harvests notification blocks into the routing
    sidecar keyed by severity (on_critical/...). The legacy event-key shape
    (on_<event>: {channels, template}) referenced template files that were
    never committed, so those entries were dead. A present block must carry
    at least one canonical severity key.
    """
    n = plugin.manifest.get("notification")
    if not n:
        pytest.skip(f"{plugin.name} has no notification block")
    assert any(k in CANONICAL_SEVERITIES for k in n), (
        f"{plugin.name}: notification block uses no canonical severity key "
        f"(has {sorted(n)}); expected one of {sorted(CANONICAL_SEVERITIES)}")


# ── test_a_plugin_loads_when_its_role_runs ──────────────────────────────────
# 2026-10-01: backup-base declared configure_backup (default off) while main.yml
# imports pazny.backup under install_backup, so the loader skipped the plugin
# that routes the nightly backup's alarms on every default estate.

def _role_flags() -> dict:
    """role name -> the install_*/configure_* flags in the `when` that runs it."""
    out: dict = {}

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            for key in ("ansible.builtin.import_role", "ansible.builtin.include_role", "import_role", "include_role"):
                role = (node.get(key) or {}).get("name") if isinstance(node.get(key), dict) else None
                if role:
                    out.setdefault(role, set()).update(re.findall(r"\b((?:install|configure)_\w+)", str(node.get("when", ""))))
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)
    for f in [REPO / "main.yml", *(REPO / "tasks/stacks").glob("*.yml")]:
        walk(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def test_feature_flag_matches_the_roles_gate():
    flags = _role_flags()
    bad = []
    for f in sorted(PLUGINS_ROOT.glob("*/plugin.yml")):
        req = (yaml.safe_load(f.read_text()) or {}).get("requires") or {}
        role, flag = req.get("role"), req.get("feature_flag")
        if role and flag and flags.get(role) and flag not in flags[role] and not req.get("role_flag_differs"):
            bad.append(f"{f.parent.name}: feature_flag {flag}, but {role} runs under {sorted(flags[role])}")
    assert not bad, "\n".join(bad)
    assert "install_backup" in flags.get("pazny.backup", set()), "the detector lost its positive case"


# ── test_plugin_templates_are_rendered ──────────────────────────────────────
# 2026-10-04: grafana-base's datasources/all.yml.j2 still defined Wing SQLite
# years after per-plugin datasource files replaced it; nothing rendered it, so a
# reader trusted a copy the estate never saw.

def test_no_plugin_template_is_dead():
    dead = []
    for tpl in repo_files(PLUGINS_ROOT, "*.j2"):
        plugin = PLUGINS_ROOT / tpl.relative_to(PLUGINS_ROOT).parts[0]
        rel = str(tpl.relative_to(plugin))
        manifest = (plugin / "plugin.yml").read_text(encoding="utf-8") if (plugin / "plugin.yml").is_file() else ""
        dirs = [d.strip().strip("'\"").rstrip("/") + "/" for d in re.findall(r"source_dir:\s*(\S+)", manifest)]
        if rel not in manifest and not any(rel.startswith(d) for d in dirs):
            dead.append(f"{plugin.name}/{rel}")
    assert not dead, f"templates no plugin.yml renders (delete or wire them): {dead}"


# ── test_plugin_conditions_know_ansible_filters ─────────────────────────────
# _eval_condition built a bare Jinja env, so `install_x | bool` raised "No filter
# named 'bool'"; the plugin went degraded and its post_compose API calls never
# ran (gitea-base, nextcloud-base, portainer-base; 2026-09-30).

def test_bool_filter_in_a_condition():
    lp = load_plugins
    assert lp._eval_condition("install_authentik | bool", {}, {"install_authentik": "true"}) is True
    assert lp._eval_condition("install_authentik | bool", {}, {"install_authentik": "false"}) is False


def test_registers_and_filters_together():
    regs = {"_nc": {"state": "running"}}
    assert load_plugins._eval_condition("_nc.state == 'running' and (flag | bool)", regs, {"flag": "yes"}) is True


def test_every_declared_condition_evaluates():
    """Every `when:` in every plugin hook file evaluates without raising."""
    for f in sorted(PLUGINS_ROOT.glob("*/hooks/*.yml")):
        for call in yaml.safe_load(f.read_text()) or []:
            if isinstance(call, dict) and call.get("when"):
                load_plugins._eval_condition(str(call["when"]), {}, {})   # StrictUndefined → False, never raise


# ── test_plugin_docker_exec_splits_like_a_shell ─────────────────────────────
# 2026-10-01: `cmd.split()` kept the quotes of --clientsecret="…", so Nextcloud
# stored the OIDC secret WITH them and every SSO login failed after a tagged run.

def test_quotes_are_shell_quotes(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(load_plugins.subprocess, "run", fake_run)
    step = {"container": "nextcloud", "compose_project": "iiab",
            "cmd": 'php occ x --clientsecret="{{ s }}" --execute="echo a b"'}
    load_plugins._docker_exec(step, {}, {"s": "abc", "stacks_dir": "/tmp"})
    assert seen["argv"][-3:] == ["x", "--clientsecret=abc", "--execute=echo a b"]


# ── test_plugin_hook_changed_is_measured ────────────────────────────────────
# Before 2026-09-25 any hook note but the literal "no-op" counted as a change, so
# `render_dir: 0 rendered / 7 unchanged` and a bare wait_health made the hooks
# `changed` on every converge (two of the cloud e2e idempotence tier's twelve).

UNCHANGED = [
    "no-op",
    "ensure_dir:/x/y:exists",
    "render_dir:blueprints:0 rendered / 7 unchanged -> /x",
    "render:compose:unchanged -> /x/y.yml",
    "render_compose_extension:ext:unchanged -> /x/y.yml",
    "copy_dir:alerts:0 copied / 3 unchanged -> /x",
    "copy_dashboards:d:0/4 updated -> /x",
    "wait_health:http://127.0.0.1:8082/ping:ok",
    "remove_file:/x/y:absent",
    "conditional_remove_dir:/x:preserved(when=False)",
    "replay_api_calls:seq:skipped(no sequence found)",
    "replay_api_calls:0 executed / 2 skipped",
    "ensure_dir:/a:exists, render_dir:b:0 rendered / 7 unchanged -> /c",
]
CHANGED = [
    "ensure_dir:/x/y:created",
    "render_dir:blueprints:1 rendered / 6 unchanged -> /x",
    "render:compose:changed -> /x/y.yml",
    "copy_dir:alerts:2 copied / 1 unchanged -> /x",
    "copy_dashboards:d:1/4 updated -> /x",
    "remove_dir:/x:removed",
    "conditional_remove_dir:/x:removed",
    "replay_api_calls:3 executed / 0 skipped",
    "some_future_action:did-something",          # unknown shape -> change
    "ensure_dir:/a:exists, render:c:changed -> /d",
]


@pytest.mark.parametrize("note", UNCHANGED)
def test_steady_notes_are_not_changes(note):
    assert load_plugins.note_changed(note) is False


@pytest.mark.parametrize("note", CHANGED)
def test_writes_are_changes(note):
    assert load_plugins.note_changed(note) is True


def test_the_module_uses_it():
    mod = (REPO / "files/anatomy/library/nos_plugin_loader.py").read_text()
    assert "load_plugins.note_changed(" in mod
    assert 'r["note"] != "no-op"' not in mod


def test_ansible_parity_render_drops_the_final_newline(tmp_path):
    """Ansible's template drops the template's final newline; the loader keeps
    it. For a file BOTH write (authentik 00/30 blueprints) the loader must
    match, or each converge rewrites it twice. Both measured endings:"""
    cases = {
        "a:\n{% for x in [1] %}\n  - {{ x }}\n{% endfor %}\n": "a:\n\n  - 1\n",
        "{% if true %}\n{% for x in [1] %}\n  k: {{ x }}\n{% endfor %}\n{% else %}\nno\n{% endif %}\n":
            "\n\n  k: 1\n\n",
    }
    for i, (tpl, want) in enumerate(cases.items()):
        src = tmp_path / f"t{i}.j2"
        src.write_text(tpl)
        dest = tmp_path / f"o{i}.yaml"
        load_plugins._render_file(src, dest, {}, ansible_parity=True)
        assert dest.read_text() == want, repr(dest.read_text())
        assert load_plugins._render_file(src, dest, {}, ansible_parity=True) is False
    # default (every other plugin) is unchanged: keeps the final newline
    load_plugins._render_file(src, tmp_path / "keep.yaml", {})
    assert (tmp_path / "keep.yaml").read_text() == want + "\n"


def test_authentik_blueprints_opt_into_parity():
    m = yaml.safe_load((PLUGINS_ROOT / "authentik-base/plugin.yml").read_text())
    assert m["provisioning"]["blueprints"].get("ansible_parity") is True


# ── test_plugin_loader_ctx_is_a_snapshot ────────────────────────────────────
# 2026-09-14: post_compose paid ~113 s of silence templating the live `vars`
# that core-up had stuffed with register payloads. The loader gets a config-sized
# `nos_plugin_ctx` snapshot taken once; the 190-var generator is the 2.24 track.

LOADER_PLAYS = (
    REPO / "tasks" / "stacks" / "core-up.yml",
    REPO / "tasks" / "stacks" / "stack-up.yml",
    REPO / "tasks" / "blank-reset.yml",
)
CORE_UP = LOADER_PLAYS[0]
BLANK_RESET = LOADER_PLAYS[2]


def _tasks(path: pathlib.Path) -> list[dict]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list), f"{path} must be a task list"
    return data


def _loader(task: dict) -> dict | None:
    body = task.get("nos_plugin_loader")
    return body if isinstance(body, dict) else None


def _set_fact(task: dict) -> dict | None:
    body = task.get("ansible.builtin.set_fact") or task.get("set_fact")
    return body if isinstance(body, dict) else None


def test_every_plugin_loader_passes_the_snapshot_not_live_vars():
    hits = []
    for path in LOADER_PLAYS:
        for i, task in enumerate(_tasks(path)):
            loader = _loader(task)
            if loader is None:
                continue
            tv = loader.get("template_vars")
            if tv != "{{ nos_plugin_ctx }}":
                hits.append(f"{path.name} task[{i}] {task.get('name')!r}: {tv!r}")
    assert not hits, (
        "nos_plugin_loader must pass template_vars: nos_plugin_ctx, not live "
        "`vars` (post_compose eager-finalize of bloated vars is ~113s):\n  "
        + "\n  ".join(hits)
    )


def test_core_up_snapshots_ctx_before_first_loader():
    seen_loader = False
    seen_snapshot = False
    for task in _tasks(CORE_UP):
        fact = _set_fact(task)
        if fact is not None and fact.get("nos_plugin_ctx") == "{{ vars }}":
            seen_snapshot = True
        if _loader(task) is not None:
            assert seen_snapshot, (
                "core-up.yml first nos_plugin_loader runs before nos_plugin_ctx "
                "is snapshotted — post_compose would still eager-finalize live vars"
            )
            seen_loader = True
            break
    assert seen_loader, "core-up.yml has no nos_plugin_loader task"


def test_blank_reset_snapshots_ctx_before_its_loader():
    seen_snapshot = False
    seen_loader = False
    for task in _tasks(BLANK_RESET):
        fact = _set_fact(task)
        if fact is not None and fact.get("nos_plugin_ctx") == "{{ vars }}":
            seen_snapshot = True
        if _loader(task) is not None:
            assert seen_snapshot, (
                "blank-reset.yml loader runs before a nos_plugin_ctx snapshot; "
                "removal can reach this file before core-up"
            )
            seen_loader = True
            break
    assert seen_loader, "blank-reset.yml has no nos_plugin_loader task"


def test_stack_up_snapshots_ctx_before_compose_if_core_did_not():
    """nos-stacks.sh can skip core-up; snapshot must not wait until post_compose."""
    stack = REPO / "tasks" / "stacks" / "stack-up.yml"
    seen_snapshot = False
    for task in _tasks(stack):
        fact = _set_fact(task)
        if fact is not None and fact.get("nos_plugin_ctx") == "{{ vars }}":
            seen_snapshot = True
            cond = str(task.get("when", ""))
            assert "nos_plugin_ctx is not defined" in cond, (
                "stack-up must not re-snapshot after core-up — that would "
                "eager-finalize the bloated vars the snapshot exists to avoid"
            )
            break
        if _loader(task) is not None:
            break
    assert seen_snapshot, (
        "stack-up.yml has no nos_plugin_ctx snapshot before its first loader"
    )
