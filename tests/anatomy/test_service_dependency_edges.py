"""Service→service dependency edges — declared, and equal to what runs.

Plan: docs/idea/13-relations.md §R1
Doctrine: docs/doctrine/layers.md §4 — layer is derived, repair before declare.

THE MEASUREMENT THAT MOTIVATES THIS FILE. On 2026-08-07 the anatomy graph held
191 nodes and 151 edges and NOT ONE between two of its 63 service nodes. The
dependency was real and written down four times over — all four as behaviour,
none of them queryable:

  * main.yml `Auto-enable {MariaDB,PostgreSQL,Redis} for services that require
    it` — three `set_fact`s under a `when:` over the consumers' install flags.
    That IS a dependency statement, in imperative form.
  * roles/pazny.postgresql/tasks/post.yml — a CREATE DATABASE loop over the
    same eight flags.
  * default.config.yml `mariadb_databases` — the same seven schemas again.
  * files/anatomy/plugins/*/plugin.yml `requires.peer_service` — two rows,
    documented in state/schema/plugin.schema.json as "documentation-only
    today; loader doesn't enforce".

R1 adds a FIFTH, and a fifth representation is only worth having if something
compares it to the others. That is this file's whole job, and it is why it
derives BOTH sides mechanically instead of transcribing either:

  A. `auto_enable_pairs()`   parses main.yml's three blocks
  B. `performs()`            reads the consumer role's compose template and
                             asks whether the provider's compose hostname is
                             actually reachable there — not merely present:
                             a line inside `{% if <undefined-var> %}` renders
                             to nothing, which is how (onlyoffice → redis) has
                             been dead for as long as anyone has looked
  C. the graph               the declared edges

and pins  C == A ∩ B,  with  A − B  asserted as an EQUALITY against the
measured repair backlog rather than skipped. So the day someone fixes the
phantom flag, B grows, this file goes red, and the declaration is forced. An
exception list you can lengthen quietly would have been the other shape, and
"a gate you can satisfy by editing the gate is not one".

REPAIR BEFORE DECLARE, mechanically: test_every_declared_edge_is_performed
refuses a declaration whose wiring the code does not carry — the one class of
lie the compiler cannot catch on its own, because the compiler only checks
edges against nodes, never against behaviour.

Offline: no docker, no wing.db, no network.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"
MAIN = REPO / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"

#: `set_fact` key → the manifest service the block turns on. `install_redis`
#: is deliberately NOT the key here: the Redis toggle is `redis_docker`
#: (roles/pazny.redis/defaults/main.yml:5 says so outright), and the manifest
#: row's `install_flag: install_redis` names a variable that exists in no
#: config file — see test_the_redis_install_flag_is_a_phantom.
PROVIDER_BY_FACT = {
    "install_mariadb": "mariadb",
    "install_postgresql": "postgresql",
    "redis_docker": "redis",
}

#: (consumer, provider) pairs that main.yml auto-enables but the consumer's
#: compose template does not actually wire. MEASURED 2026-08-07, asserted as an
#: equality so the set can neither grow nor shrink unnoticed. Each entry is a
#: repair ticket, not an exemption.
UNPERFORMED = {("onlyoffice", "redis")}

#: Declared edges whose provider is NOT one of the three auto-enabled ones —
#: they come from a different existing declaration and are checked against it
#: rather than against main.yml.
PEER_SERVICE_PLUGINS = ("woodpecker-base", "portainer-base")


# ── A: the imperative declaration, parsed ─────────────────────────────────


def _service_by_flag() -> dict[str, str]:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for svc in doc.get("services") or []:
        if isinstance(svc, dict) and svc.get("id") and svc.get("install_flag"):
            out.setdefault(svc["install_flag"], svc["id"])
    return out


def auto_enable_pairs() -> set[tuple[str, str]]:
    """(consumer_service, provider_service) from main.yml's three blocks.

    Text-scan on purpose: the fact lives in a `when:` folded-scalar, and
    yaml.safe_load gives no line numbers to report against.
    """
    lines = MAIN.read_text(encoding="utf-8").splitlines()
    by_flag = _service_by_flag()
    pairs: set[tuple[str, str]] = set()
    provider: str | None = None
    for line in lines:
        fact = re.match(r"^\s{8}([a-z_]+):\s*true\s*$", line)
        if fact and fact.group(1) in PROVIDER_BY_FACT:
            provider = PROVIDER_BY_FACT[fact.group(1)]
            continue
        if provider is None:
            continue
        if re.match(r"^\s{4}- name:", line) or re.match(r"^\s{4}#", line):
            provider = None
            continue
        for flag in re.findall(r"\(install_([a-z_0-9]+)\s*\|", line):
            svc = by_flag.get(f"install_{flag}")
            assert svc, (
                f"main.yml auto-enables {provider} for install_{flag}, which names no "
                f"service in state/manifest.yml — the imperative declaration and the "
                f"registry have drifted apart"
            )
            pairs.add((svc, provider))
    return pairs


# ── B: does the code perform it? ──────────────────────────────────────────


def _config_layer_keys() -> set[str]:
    keys: set[str] = set()
    sources = [REPO / "default.config.yml", REPO / "default.credentials.yml"]
    sources += sorted(REPO.glob("roles/*/defaults/main.yml"))
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([a-z_][a-z0-9_]*):", line)
            if m:
                keys.add(m.group(1))
    return keys


#: Jinja/Ansible names that are not config variables and must not be mistaken
#: for undefined ones when reading an `{% if %}` guard.
_GUARD_BUILTINS = {
    "ansible_facts", "ansible_os_family", "ansible_distribution", "ansible_system",
    "true", "false", "none", "not", "and", "or", "in", "is", "if", "else",
    "defined", "default", "bool", "string", "lower", "upper", "int", "length",
    "trim", "item", "vars", "env", "HOME", "machine", "map", "list", "select",
    "selectattr", "join", "startswith", "endswith", "version",
}


def performs(consumer: str, provider: str) -> tuple[bool, list[str]]:
    """Does `roles/pazny.<consumer>`'s compose template REACH the provider?

    Presence is not enough. The template is Jinja, so a line under a guard
    whose condition names a variable that exists nowhere in the config layer
    renders to nothing however plainly it reads in the source. That is exactly
    the (onlyoffice → redis) case, and treating "the word appears" as evidence
    is how it stayed invisible.

    Returns (reachable, diagnostics).
    """
    tpl = REPO / f"roles/pazny.{consumer}/templates/compose.yml.j2"
    if not tpl.exists():
        return False, [f"no compose template at {tpl.relative_to(REPO)}"]
    keys = _config_layer_keys()
    guards: list[set[str]] = []
    notes: list[str] = []
    reachable = False
    for lineno, line in enumerate(tpl.read_text(encoding="utf-8").splitlines(), 1):
        for m in re.finditer(r"\{%-?\s*(if|endif)\b([^%]*)%\}", line):
            if m.group(1) == "if":
                idents = set(re.findall(r"[a-z_][a-z0-9_]*", m.group(2)))
                guards.append({i for i in idents
                               if i not in keys and i not in _GUARD_BUILTINS})
            elif guards:
                guards.pop()
        if line.strip().startswith("#") or provider not in line:
            continue
        dead = set().union(*guards) if guards else set()
        if dead:
            notes.append(f"{tpl.relative_to(REPO)}:{lineno} is unreachable — guarded by "
                         f"{sorted(dead)}, which the config layer never defines")
        else:
            reachable = True
            notes.append(f"{tpl.relative_to(REPO)}:{lineno} names {provider!r}")
    return reachable, notes


# ── C: the graph ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def declared_pairs(graph: dict) -> set[tuple[str, str]]:
    return {(e["to"].split(":", 1)[1], e["from"].split(":", 1)[1])
            for e in graph["edges"]
            if e["from"].startswith("service:") and e["to"].startswith("service:")}


# ── the equivalence ───────────────────────────────────────────────────────


def test_the_imperative_blocks_still_parse():
    """A positive control on the parser, so a main.yml refactor that empties
    it reads as broken rather than as agreement."""
    pairs = auto_enable_pairs()
    assert len(pairs) >= 20, (
        f"only {len(pairs)} auto-enable pairs parsed out of main.yml — the three "
        f"`Auto-enable <provider> for services that require it` blocks moved or "
        f"changed shape; fix this parser before trusting any comparison below"
    )
    assert {p for _, p in pairs} == {"mariadb", "postgresql", "redis"}


def test_every_auto_enabled_dependency_that_runs_is_declared(committed):
    """A == C, over the pairs B says are real.

    This is the whole point of R1: the estate's oldest dependency statement and
    its newest must name the same set, or one of them is lying.
    """
    auto = auto_enable_pairs()
    performed = {p for p in auto if performs(*p)[0]}
    declared = declared_pairs(committed)
    missing = performed - declared
    assert not missing, (
        f"main.yml auto-enables these providers and the consumer's compose template "
        f"really points at them, but no plugin declares the edge: {sorted(missing)}. "
        f"Add a top-level `depends_on:` to each consumer's "
        f"files/anatomy/plugins/<svc>-base/plugin.yml and re-run "
        f"tools/anatomy-graph-gen.py."
    )


def test_no_database_edge_is_declared_that_main_yml_does_not_enable(committed):
    """C ⊆ A for the three auto-enabled providers.

    The other direction, which matters more: a declared edge that main.yml does
    NOT back means the playbook will happily bring the consumer up with no
    provider — the declaration would be an aspiration wearing a fact's clothes.
    """
    auto = auto_enable_pairs()
    providers = set(PROVIDER_BY_FACT.values())
    extra = {p for p in declared_pairs(committed) if p[1] in providers} - auto
    assert not extra, (
        f"declared but not auto-enabled: {sorted(extra)}. Either add the consumer's "
        f"install flag to the matching `Auto-enable …` block in main.yml, or drop the "
        f"declaration — an estate that declares a dependency it does not enforce has "
        f"gained a second untrue statement, not a graph."
    )


def test_the_unperformed_backlog_is_exactly_what_was_measured():
    """A − B, asserted as an equality.

    (onlyoffice → redis): main.yml:1259 sets `redis_docker: true` for
    install_onlyoffice, so the estate starts a Redis container FOR OnlyOffice —
    and roles/pazny.onlyoffice/templates/compose.yml.j2:38 gates the whole
    REDIS_SERVER_* block on `install_redis`, a variable no config file defines.
    The block has therefore never rendered. Two representations of one fact,
    disagreeing, with nothing comparing them: the exact defect R1 exists to end.

    Deliberately NOT repaired in the same change that declares the edges — the
    fix is a one-token flip to `redis_docker` but it turns Redis on for a live
    service, which is a runtime change and belongs in its own diff with its own
    verification. Until then the edge is written up, not declared.
    """
    auto = auto_enable_pairs()
    unperformed = {p for p in auto if not performs(*p)[0]}
    assert unperformed == UNPERFORMED, (
        f"the repair backlog moved: measured {sorted(UNPERFORMED)}, now "
        f"{sorted(unperformed)}. If a pair was FIXED, declare its edge in the "
        f"consumer's plugin and remove it here (that is the gate working). If a new "
        f"pair appeared, a live dependency has silently stopped rendering."
    )


def test_every_declared_edge_is_performed(committed):
    """Repair before declare, applied to every service→service edge there is.

    The compiler checks an edge against the node set; nothing checks it against
    behaviour. This does, mechanically and for all of them.
    """
    for consumer, provider in sorted(declared_pairs(committed)):
        ok, notes = performs(consumer, provider)
        assert ok, (
            f"service:{consumer} declares a dependency on service:{provider} that the "
            f"code does not perform:\n  " + "\n  ".join(notes or ["(no mention at all)"])
        )


def test_the_peer_service_declaration_and_the_edge_agree(committed):
    """The second seed: `requires.peer_service`, schema-documented as
    "documentation-only today; loader doesn't enforce". Now at least one thing
    reads it — this gate — so the two spellings cannot drift.

    portainer-base's peer (`docker_socket_proxy`) gets NO edge on purpose: it
    is a sibling container inside the portainer role's own compose fragment,
    not a manifest service, so it has no address. A node minted to receive an
    edge would be padding.
    """
    declared = declared_pairs(committed)
    services = {n.split(":", 1)[1] for n in committed["nodes"] if n.startswith("service:")}
    for plugin in PEER_SERVICE_PLUGINS:
        path = REPO / "files/anatomy/plugins" / plugin / "plugin.yml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        peer = (doc.get("requires") or {}).get("peer_service")
        assert peer, f"{plugin} lost its requires.peer_service — update this gate with it"
        consumer = re.sub(r"-base$", "", plugin).replace("-", "_")
        if peer not in services:
            assert (consumer, peer) not in declared, (
                f"{plugin} declares an edge to {peer!r}, which is no manifest service"
            )
            continue
        assert (consumer, peer) in declared, (
            f"{plugin} names peer_service: {peer} and both are manifest services, but "
            f"the graph carries no service:{peer} → service:{consumer} edge"
        )


# ── absence must never render as calm ─────────────────────────────────────


def test_every_service_node_states_its_survey_state(committed):
    """A service with no upstreams and a service nobody read must not look the
    same. Three states, and `not-surveyed` is the honest majority today."""
    states = {"declared", "not-surveyed", "no-manifest"}
    counts = {s: 0 for s in states}
    for nid, node in committed["nodes"].items():
        if node.get("kind") != "service":
            continue
        state = node.get("dependency_survey")
        assert state in states, (
            f"{nid} carries dependency_survey={state!r}; absence has to be one of "
            f"{sorted(states)} and never a missing field, which reads as fine"
        )
        counts[state] += 1
    assert counts["declared"] >= 15, (
        f"only {counts['declared']} services carry a dependency survey — R1 measured "
        f"16 consumers plus the roots"
    )
    assert counts["not-surveyed"] > 0, (
        "every service now claims a survey; if that is true, say so by deleting this "
        "assertion deliberately — do not let a silent zero certify 63 unread roles"
    )


def test_the_counts_publish_the_unsurveyed_remainder(committed):
    c = committed["counts"]
    for key in ("edges_service_dependency", "services_survey_declared",
                "services_survey_not_surveyed", "services_survey_no_manifest"):
        assert key in c, f"counts lost {key} — the survey's own shape stopped being countable"
    total = (c["services_survey_declared"] + c["services_survey_not_surveyed"]
             + c["services_survey_no_manifest"])
    assert total == c["nodes_service"], (
        f"survey states cover {total} of {c['nodes_service']} services — a service "
        f"fell out of all three buckets"
    )
    assert c["edges_service_dependency"] >= 20, (
        f"only {c['edges_service_dependency']} service→service edges; R1 measured 23 "
        f"(22 auto-enabled + 1 peer_service)"
    )


# ── the two refusals a service upstream added to the compiler ─────────────


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "anatomy_graph_gen", REPO / "tools" / "anatomy-graph-gen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _service_pair() -> dict:
    return {
        "service:postgresql": {"kind": "service", "install_flag": "install_postgresql"},
        "service:outline": {"kind": "service", "install_flag": "install_outline"},
    }


def test_run_outcome_words_are_refused_on_a_service_edge(gen):
    """`expects: succeeded` is a claim about a RUN, and a database has none.

    Left unrefused, every service edge would inherit the pulse default and the
    artifact would carry 23 unfalsifiable assertions — the shape of a field
    that looks measured and is not.
    """
    nodes = _service_pair()
    ok = [("service:outline",
           {"upstream": "service:postgresql", "kind": "data", "via": "x"}, "src")]
    edge = gen.compile_declared(ok, nodes)[0]
    assert "expects" not in edge

    for poison in ({"expects": "succeeded"}, {"on_findings": "proceed"}):
        raw = [("service:outline",
                {"upstream": "service:postgresql", "kind": "data", "via": "x", **poison},
                "src")]
        with pytest.raises(SystemExit):
            gen.compile_declared(raw, nodes)


def test_a_temporal_edge_between_two_services_is_refused(gen):
    """A temporal edge's whole content is a margin between two cron minutes.

    Neither endpoint here has one, so `schedules: [null, null]` would have
    satisfied the existing staleness check by matching two absences — a
    measurement that agrees with itself because both sides are empty.
    """
    nodes = _service_pair()
    raw = [("service:outline",
            {"upstream": "service:postgresql", "kind": "temporal",
             "margin_min": 5, "schedules": [None, None]}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


# ── the phantom flag, pinned where it will be seen ────────────────────────


def test_the_redis_install_flag_is_a_phantom():
    """`install_redis` is referenced in four committed places and DEFINED IN
    NONE, which is why the OnlyOffice Redis block never renders.

    Pinned rather than fixed, in this change: the point of R1 is to make the
    disagreement visible and comparable. When the flag is unified, this test
    fails and should be deleted along with the last reference.
    """
    keys = _config_layer_keys()
    assert "install_redis" not in keys, (
        "`install_redis` is now a real variable — the phantom was fixed. Re-check "
        "roles/pazny.onlyoffice/templates/compose.yml.j2, "
        "roles/pazny.uptime_kuma/tasks/monitors.yml, state/manifest.yml and "
        "state/gdpr-erasure-map.yml, declare the (onlyoffice → redis) edge, and "
        "delete this test."
    )
    assert "redis_docker" in keys, "the real Redis toggle vanished"
    readers = [
        "roles/pazny.onlyoffice/templates/compose.yml.j2",
        "roles/pazny.uptime_kuma/tasks/monitors.yml",
    ]
    for rel in readers:
        assert "install_redis" in (REPO / rel).read_text(encoding="utf-8"), (
            f"{rel} no longer reads install_redis — if it was repaired, update "
            f"UNPERFORMED and this list together"
        )
