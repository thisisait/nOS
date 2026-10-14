"""A service declared off stays down after a converge.

MEASURED 2026-10-14 on a client host: config.yml set install_nextcloud,
install_infisical, install_observability, apps_runner_enabled … false, the
converge was green, and 31 containers were `Up 5 minutes`. prune-disabled
STOPPED the off services, then stack-up passed every file in overrides/ to
`docker compose up -d`, which started them again. Observability and the apps
stack were never stopped at all: nothing brought them up, nothing took them down.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nos_prune_guard", REPO / "filter_plugins/nos_prune_guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

BASE = {"services": {}}
NEXTCLOUD = {"services": {"nextcloud": {"image": "nextcloud:30"}}}
NEXTCLOUD_EXT = {"services": {"nextcloud": {"environment": {"X": "1"}}}}
KIWIX = {"services": {"kiwix": {"image": "kiwix-serve:3"}}}


def _stack(tmp: pathlib.Path, name: str = "iiab") -> dict:
    stack = tmp / name
    (stack / "overrides").mkdir(parents=True)
    (stack / "docker-compose.yml").write_text(yaml.safe_dump(BASE))
    frags = {"kiwix.yml": KIWIX, "nextcloud.yml": NEXTCLOUD, "nextcloud-onlyoffice.yml": NEXTCLOUD_EXT}
    for fname, doc in frags.items():
        (stack / "overrides" / fname).write_text(yaml.safe_dump(doc))
    return {name: [{"path": str(p)} for p in sorted((stack / "overrides").glob("*.yml"))]}


def _plan(tmp, flags, disabled=("nextcloud",)):
    overrides = {str(tmp / "iiab/overrides/nextcloud.yml"): ["nextcloud"],
                 str(tmp / "iiab/overrides/kiwix.yml"): ["kiwix"]}
    return guard.nos_prune_plan(list(disabled), flags, overrides, ["iiab-nextcloud-1"])


def _names(split, stack="iiab"):
    return sorted(pathlib.Path(f["path"]).name for f in split["keep"][stack])


# ── The filter ──────────────────────────────────────────────────────────────


def test_authored_off_fragment_is_left_out_of_up(tmp_path):
    found = _stack(tmp_path)
    plan = _plan(tmp_path, {"install_nextcloud": False})
    split = guard.nos_split_orphans(found, str(tmp_path), guard.nos_up_excluded(plan))
    # The plugin extension of the off service becomes an orphan, not a merge error.
    assert _names(split) == ["kiwix.yml"]
    assert [pathlib.Path(p).name for p in split["disabled"]] == ["nextcloud.yml"]


def test_unauthored_destructive_excludes_nothing(tmp_path):
    """The 2026-09-01 shape: off for one command only. Nothing is dropped."""
    found = _stack(tmp_path)
    plan = _plan(tmp_path, {"install_nextcloud": True})
    assert plan["unauthored_destructive"] == ["nextcloud"]
    excluded = guard.nos_up_excluded(plan)
    assert excluded == []
    split = guard.nos_split_orphans(found, str(tmp_path), excluded)
    assert _names(split) == ["kiwix.yml", "nextcloud-onlyoffice.yml", "nextcloud.yml"]
    assert split["disabled"] == []


def test_a_refused_dependency_plan_blocks_the_whole_exclusion(tmp_path):
    good = _plan(tmp_path, {"install_nextcloud": False})
    refused = _plan(tmp_path, {"install_nextcloud": True})
    assert guard.nos_up_excluded(good, refused) == []
    assert guard.nos_up_excluded(refused, good) == []


def test_dependency_plan_adds_its_fragments(tmp_path):
    main = _plan(tmp_path, {"install_kiwix": False}, disabled=("kiwix",))
    dep = _plan(tmp_path, {"install_nextcloud": False})
    assert sorted(pathlib.Path(p).name for p in guard.nos_up_excluded(main, dep)) == ["kiwix.yml", "nextcloud.yml"]


def test_no_exclusion_argument_keeps_old_behaviour(tmp_path):
    found = _stack(tmp_path)
    assert _names(guard.nos_split_orphans(found, str(tmp_path))) == [
        "kiwix.yml", "nextcloud-onlyoffice.yml", "nextcloud.yml"]


# ── The rendered up command ─────────────────────────────────────────────────


def _env():
    env = NativeEnvironment()
    env.filters["nos_split_orphans"] = guard.nos_split_orphans
    return env


def _task(path, name):
    for t in yaml.safe_load((REPO / path).read_text()):
        if t.get("name") == name:
            return t
    raise AssertionError(f"{path}: no task named {name!r}")


def _f_list(cmd):
    return sorted(pathlib.Path(p).name for p in re.findall(r'-f "([^"]+)"', cmd))


def test_stack_up_command_skips_the_plan_fragments(tmp_path):
    env = _env()
    found = _stack(tmp_path)
    ctx = {"stacks_dir": str(tmp_path), "_stack_overrides_map": found,
           "_disabled_up_excluded": guard.nos_up_excluded(_plan(tmp_path, {"install_nextcloud": False}))}
    split_task = _task("tasks/stacks/stack-up.yml", "[Stacks] Exclude orphan compose extensions (no base defines the service)")
    ctx["_orphan_split"] = env.from_string(split_task["ansible.builtin.set_fact"]["_orphan_split"]).render(ctx)
    merge = _task("tasks/stacks/stack-up.yml", "[Stacks] Merge only fragments whose services are defined")
    ctx["_stack_overrides_map"] = env.from_string(merge["ansible.builtin.set_fact"]["_stack_overrides_map"]).render(ctx)
    for name in ("[Stacks] Fire docker compose up -d per stack (async, parallel start)",
                 "[Stacks] Start stacks sequentially — up -d (cold-blank safe)"):
        cmd = env.from_string(_task("tasks/stacks/stack-up.yml", name)["ansible.builtin.shell"]).render(
            {**ctx, "item": "iiab", "docker_bin": "docker"})
        assert _f_list(cmd) == ["docker-compose.yml", "kiwix.yml"], name


def test_core_up_command_skips_the_plan_fragments(tmp_path):
    env = _env()
    infra = tmp_path / "infra"
    (infra / "overrides").mkdir(parents=True)
    (infra / "docker-compose.yml").write_text(yaml.safe_dump(BASE))
    for fname in ("infisical.yml", "authentik.yml"):
        (infra / "overrides" / fname).write_text(yaml.safe_dump({"services": {fname[:-4]: {"image": "x"}}}))
    (tmp_path / "observability/overrides").mkdir(parents=True)
    plan = guard.nos_prune_plan(["infisical"], {"install_infisical": False},
                                {str(infra / "overrides/infisical.yml"): ["infisical"]}, [])
    ctx = {"stacks_dir": str(tmp_path), "_disabled_up_excluded": guard.nos_up_excluded(plan),
           "_infra_overrides": {"files": [{"path": str(p)} for p in sorted((infra / "overrides").glob("*.yml"))]},
           "_observability_overrides": {"files": []}}
    split = _task("tasks/stacks/core-up.yml", "[Core] Exclude orphan compose extensions (no base defines the service)")
    ctx["_core_orphan_split"] = env.from_string(split["ansible.builtin.set_fact"]["_core_orphan_split"]).render(ctx)
    merge = _task("tasks/stacks/core-up.yml", "[Core] Merge only fragments whose services are defined")
    ctx["_infra_overrides"] = env.from_string(merge["ansible.builtin.set_fact"]["_infra_overrides"]).render(ctx)
    cmd = env.from_string(_task("tasks/stacks/core-up.yml", "[Core] Start INFRA stack (docker compose up -d)")
                          ["ansible.builtin.shell"]).render({**ctx, "docker_bin": "docker"})
    assert _f_list(cmd) == ["authentik.yml", "docker-compose.yml"]


def test_both_up_paths_report_what_was_left_out():
    for path in ("tasks/stacks/stack-up.yml", "tasks/stacks/core-up.yml"):
        body = (REPO / path).read_text()
        assert "disabled services left out of `up`" in body, path


def test_prune_disabled_computes_the_exclusion_from_the_plan():
    body = (REPO / "tasks/stacks/prune-disabled.yml").read_text()
    assert re.search(r"_disabled_up_excluded:.*nos_up_excluded", body, re.S)
    # Auto-enabled deps (mariadb) honour their RESOLVED flag through the same guard.
    assert re.search(r"_auto_enabled.*nos_prune_plan", body, re.S)


# ── Auto-enabled dependencies: off only when nothing that needs them is on ──
# Review 2026-10-14: `-e install_postgresql=false` with Authentik on left
# postgresql.yml out of infra `up`. default.config.yml's `false` is the auto
# default, and extra-vars outrank main.yml's set_fact; martin and mcp_gateway
# use postgresql but are in no auto-enable block. The graph's data edges decide.

_PRUNE = "tasks/stacks/prune-disabled.yml"
_PG = "/s/infra/overrides/postgresql.yml"


def _deps_ctx(flags, consumers=None):
    """Render the dependency tasks the way Ansible would, flags as resolved."""
    env = NativeEnvironment()
    env.filters.update(bool=lambda v: str(v).lower() in ("true", "yes", "1", "on"),
                       from_json=__import__("json").loads,
                       nos_dep_consumers=guard.nos_dep_consumers,
                       nos_prune_plan=guard.nos_prune_plan,
                       nos_up_excluded=guard.nos_up_excluded)

    def lookup(kind, *terms, default=None, **_):
        if kind == "file":
            return pathlib.Path(terms[0]).read_text()
        return flags.get(terms[0], default)

    env.globals.update(lookup=lookup,
                       query=lambda kind, *t, default=None, **_: [flags.get(x, default) for x in t])
    ctx = {"playbook_dir": str(REPO), "_auto_enabled": ["mariadb", "postgresql"],
           "_on_disk_flags": {"install_postgresql": False, "install_mariadb": True},
           "_override_services": {_PG: ["postgresql"]},
           "_prune_plan": guard.nos_prune_plan([], {}, {}, [])}
    for name in ("[Stacks] Who consumes each auto-enabled dependency (anatomy graph)",
                 "[Stacks] Auto-enabled dependencies off with no consumer on",
                 "[Stacks] Fragments `up` leaves out (declared off, attributed)"):
        for key, expr in _task(_PRUNE, name)["ansible.builtin.set_fact"].items():
            ctx[key] = env.from_string(expr).render(ctx)
            if key == "_dep_consumers" and consumers is not None:
                ctx[key] = consumers
    return ctx


def test_the_graph_names_every_postgresql_consumer():
    graph = __import__("json").loads((REPO / "state/anatomy-graph.json").read_text())
    pg = guard.nos_dep_consumers(graph, ["postgresql"])["postgresql"]
    assert {"install_authentik", "install_infisical", "install_martin", "install_mcp_gateway"} <= set(pg)


def test_one_command_off_database_stays_up_while_authentik_is_on():
    ctx = _deps_ctx({"install_postgresql": False, "install_authentik": True})
    assert "postgresql" not in ctx["_deps_off"]
    assert ctx["_disabled_up_excluded"] == []


def test_a_consumer_outside_the_auto_enable_list_keeps_the_database():
    ctx = _deps_ctx({"install_postgresql": False, "install_martin": True})
    assert "postgresql" not in ctx["_deps_off"]
    assert _PG not in ctx["_disabled_up_excluded"]


def test_a_database_nothing_needs_is_left_out_of_up():
    ctx = _deps_ctx({"install_postgresql": False, "install_mariadb": True})
    assert ctx["_deps_off"] == ["postgresql"]
    assert ctx["_disabled_up_excluded"] == [_PG]


def test_a_dependency_the_graph_knows_no_consumer_of_is_not_judged():
    """No edge is absence of evidence, not proof that nothing needs it."""
    ctx = _deps_ctx({"install_postgresql": False}, consumers={"postgresql": []})
    assert ctx["_deps_off"] == []


def test_an_auto_enabled_database_is_never_left_out():
    ctx = _deps_ctx({"install_postgresql": True, "install_mariadb": True})
    assert ctx["_deps_off"] == []
    assert ctx["_disabled_up_excluded"] == []


# ── Whole stacks switched off: observability, the apps runner ──────────────


def _stop_include(path, project):
    for t in yaml.safe_load((REPO / path).read_text()):
        inc = t.get("ansible.builtin.include_tasks")
        if inc == "stop-project.yml" and (t.get("vars") or {}).get("_stop_project") == project:
            return t
    raise AssertionError(f"{path}: no stop-project.yml include for {project!r}")


def test_observability_off_stops_its_containers():
    t = _stop_include("tasks/stacks/core-up.yml", "observability")
    assert "not (_core_observability_enabled | bool)" in str(t["when"])


def test_apps_runner_off_stops_its_containers():
    t = _stop_include("tasks/stacks/apps-up.yml", "apps")
    assert "not (apps_runner_enabled | default(true) | bool)" in str(t["when"])


def test_stop_project_stops_and_never_removes():
    tasks = yaml.safe_load((REPO / "tasks/stacks/stop-project.yml").read_text())
    body = yaml.safe_dump(tasks)
    assert "label=com.docker.compose.project={{ _stop_project }}" in body, "select by exact project label"
    argvs = [t["ansible.builtin.command"]["argv"] for t in tasks if "ansible.builtin.command" in t]
    verbs = {a[1] for a in argvs}
    assert verbs == {"ps", "stop"}, verbs
    assert not re.search(r"\b(rm|down|volume|prune)\b", " ".join(" ".join(a) for a in argvs))
    assert any("ansible.builtin.debug" in t for t in tasks), "what was stopped is reported"
