"""Service→service dependency edges — declared, and equal to what runs.

Plan: docs/idea/13-relations.md §R1/§R2
Doctrine: docs/doctrine/layers.md §4 — layer is derived, repair before declare.

THE MEASUREMENT THAT MOTIVATES THIS FILE. On 2026-08-07 the anatomy graph held
191 nodes and 151 edges and NOT ONE between two of its 63 service nodes. The
dependency was real and written down four times over — all four as behaviour,
none of them queryable: main.yml's three `Auto-enable <provider>` blocks,
roles/pazny.postgresql/tasks/post.yml's CREATE DATABASE loop,
default.config.yml's mariadb_databases, and two `requires.peer_service` rows
the schema itself calls "documentation-only today".

R1 added a FIFTH, and a fifth representation is only worth having if something
compares it to the others. That is this file's whole job, and it is why it
derives BOTH sides mechanically instead of transcribing either:

  A. auto_enable_pairs()          main.yml's three blocks, parsed
  B. service_edge_probe.sweep()   EVERY (consumer, provider) pair the code
                                  performs, over all 63 manifest services
  C. the committed graph          the declared edges

WHAT R2 CHANGED HERE, AND WHY EACH CHANGE WAS FORCED. Three adversarial reviews
took R1 apart. Two structural defects survived their scrutiny:

  * THE DERIVATION COULD NOT FIND WHAT main.yml HAD NOT HEARD OF. Completeness
    iterated A only, so `mcp_gateway → postgresql` — a full DSN plus a live
    `psql` exec into the estate's own container, default-ON — was outside the
    derivation entirely, and repairing it would have gone red with the gate
    demanding the pair be filed as UNPERFORMED, i.e. recording a lie about the
    live dependency. B is now a SWEEP over the service registry: it starts from
    the estate, not from one place the estate wrote the fact down. It found 30
    undeclared pairs, of which 12 are now declared and 18 refused BY NAME below.
  * NOT ALL 23 CLAIMS HAD THE SAME BACKING. `install_gitea` appears in main.yml
    zero times, so `install_woodpecker: true` + `install_gitea: false` is a
    green converge with a Woodpecker nobody can log into. The compiler now
    refuses a service edge that is neither auto-enabled nor carrying an
    `unenforced:` sentence, and the artifact says which is which.

Offline: no docker, no wing.db, no network.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

from service_edge_probe import (config_layer_keys, performs, provider_aliases,
                                reachable_text, sweep)

REPO = Path(__file__).resolve().parents[2]
GRAPH = REPO / "state" / "anatomy-graph.json"
MAIN = REPO / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"

#: `set_fact` key → the manifest service the block turns on. `install_redis`
#: is deliberately NOT the key here: the Redis toggle is `redis_docker`
#: (roles/pazny.redis/defaults/main.yml:5 says so outright), and the manifest
#: row's `install_flag: install_redis` names a variable that exists in no
#: config file — see test_the_phantom_install_flags_are_named.
PROVIDER_BY_FACT = {
    "install_mariadb": "mariadb",
    "install_postgresql": "postgresql",
    "redis_docker": "redis",
}

#: (consumer, provider) pairs main.yml auto-enables but the consumer's code
#: does not wire. MEASURED, asserted as an equality so the set can neither grow
#: nor shrink unnoticed. Each entry is a repair ticket, not an exemption.
UNPERFORMED = {("onlyoffice", "redis")}

#: (consumer, provider) pairs the code PERFORMS and this estate deliberately
#: does not declare. The other half of the same honesty: a sweep that finds 30
#: undeclared pairs and reports 12 has silently exempted 18. Every one carries
#: the reason, and the set is an equality — a new performing pair appears here
#: with a reason, or as an edge, and never as nothing.
REFUSED = {
    # ── the SSO class: already addressed, one level down ──────────────────
    # These 13 all reach `{{ authentik_domain }}` and every one is a genuine
    # relationship. Declaring them service→service would mint a SECOND address
    # for a fact the graph already carries: `service:authentik →
    # authentik:<slug> → service:<x>`, where the middle node is the provider
    # object OpenTofu applies from state/tofu-authentik-services.yml. R2 gave
    # `service:authentik` the missing first hop (it had out-degree 0 and read
    # as surveyed), so the chain is complete and the layer derivation walks it.
    # A parallel service edge would be padding, which this graph refuses.
    ("bookstack", "authentik"): "SSO — carried by the authentik provider chain",
    ("erpnext", "authentik"): "SSO — carried by the authentik provider chain",
    ("freescout", "authentik"): "SSO — carried by the authentik provider chain",
    ("gitea", "authentik"): "SSO — carried by the authentik provider chain",
    ("gitlab", "authentik"): "SSO — carried by the authentik provider chain",
    ("homeassistant", "authentik"): "SSO — carried by the authentik provider chain",
    ("nextcloud", "authentik"): "SSO — carried by the authentik provider chain",
    ("nodered", "authentik"): "SSO — carried by the authentik provider chain",
    ("paperclip", "authentik"): "SSO — carried by the authentik provider chain",
    ("portainer", "authentik"): "SSO — carried by the authentik provider chain",
    ("smtp_stalwart", "authentik"): "SSO — carried by the authentik provider chain",
    ("superset", "authentik"): "SSO — carried by the authentik provider chain",
    ("wing", "authentik"): "SSO — carried by the authentik provider chain",
    # ── the exporter class: the conditionality runs the other way ─────────
    # roles/pazny.grafana/templates/compose.yml.j2 ships postgres-, mysqld- and
    # redis-exporter sidecars, each inside `{% if install_<provider> %}`. The
    # sidecar exists only BECAUSE the provider does, so the dependency can
    # never go unsatisfied, and Grafana does not stop when Postgres does.
    ("grafana", "postgresql"): "exporter sidecar, gated on the PROVIDER's own flag",
    ("grafana", "mariadb"): "exporter sidecar, gated on the PROVIDER's own flag",
    ("grafana", "redis"): "exporter sidecar, gated on the PROVIDER's own flag",
    # ── embedding origins: a CORS allow-list is not a dependency ──────────
    # Both name `{{ face_domain }}` so the face may IFRAME them. The arrow
    # points the other way, and the face's own manifest declares neither
    # because an iframe host does not depend on its guest.
    ("metabase", "face"): "MB_EMBEDDING_APP_ORIGIN — a CORS origin, not an upstream",
    ("keap", "face"): "KEAP_EMBED_ORIGINS — a CORS origin, not an upstream",
}

#: Declared edges whose provider is NOT one of the three auto-enabled ones.
PEER_SERVICE_PLUGINS = ("woodpecker-base", "portainer-base")

#: Identifiers referenced in committed code and DEFINED IN NO config source.
#: `install_redis` is why the OnlyOffice Redis block has never rendered; the
#: other two surfaced from the same sweep and were unreported by R1.
PHANTOM_FLAGS = {
    # The Kuma monitor was repaired to `redis_docker` (2026-09-01); OnlyOffice
    # stays pinned because flipping it starts Redis for a live service.
    "install_redis": ("roles/pazny.onlyoffice/templates/compose.yml.j2",),
    "freepbx_lan_access": ("roles/pazny.freepbx/templates/compose.yml.j2",),
    "sso_autologin_min_tier_2": (),
}


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


def test_the_two_parsers_of_main_yml_agree(gen):
    """This file and the compiler each parse main.yml's auto-enable blocks —
    one to compare, one to stamp `enforced_by` on the edge. Two parsers of one
    fact is the defect R1 exists to end, so they are held equal rather than
    left to drift on the strength of looking similar."""
    assert set(gen.auto_enabled_pairs()) == auto_enable_pairs()


def test_every_dependency_the_code_performs_is_declared_or_refused(committed):
    """B ⊆ C ∪ REFUSED — the completeness side, derived from the ESTATE.

    The first version of this gate iterated main.yml's three blocks, so a
    dependency those blocks had never heard of could not be discovered by it at
    all. `mcp_gateway → postgresql` is the pair that proved it: enforced,
    default-on, harder-wired than the eight declared postgres edges, and
    invisible to a derivation seeded from the wrong end.
    """
    missing = sweep() - declared_pairs(committed) - set(REFUSED)
    assert not missing, (
        f"the code performs these service→service dependencies and the graph neither "
        f"declares nor refuses them: {sorted(missing)}. Add a top-level `depends_on:` "
        f"to the consumer's files/anatomy/plugins/<svc>-base/plugin.yml and re-run "
        f"tools/anatomy-graph-gen.py — or, if it is not a dependency, add it to "
        f"REFUSED with the reason. Silence is the one option that is not available."
    )


def test_the_refusals_are_still_refusals(committed):
    """REFUSED ∩ C == ∅, and every refusal still describes a live pair.

    A refusal list that quietly accumulates dead entries is an exemption list
    with better manners.
    """
    declared = declared_pairs(committed)
    for pair, reason in sorted(REFUSED.items()):
        assert pair not in declared, (
            f"{pair} is declared AND refused ({reason}) — pick one"
        )
        assert pair in sweep(), (
            f"REFUSED names {pair}, which the code no longer performs — delete the "
            f"row rather than leave a reason attached to nothing"
        )


def test_every_auto_enabled_dependency_that_runs_is_declared(committed):
    """A ∩ B ⊆ C. The estate's oldest dependency statement and its newest must
    name the same set, or one of them is lying."""
    performed = {p for p in auto_enable_pairs() if performs(*p)[0]}
    missing = performed - declared_pairs(committed)
    assert not missing, (
        f"main.yml auto-enables these providers and the consumer's code really points "
        f"at them, but no plugin declares the edge: {sorted(missing)}"
    )


def test_the_unperformed_backlog_is_exactly_what_was_measured():
    """A − B, asserted as an equality.

    (onlyoffice → redis): main.yml:1259 sets `redis_docker: true` for
    install_onlyoffice, so the estate starts a Redis container FOR OnlyOffice —
    and roles/pazny.onlyoffice/templates/compose.yml.j2:38 gates the whole
    REDIS_SERVER_* block on `install_redis`, a variable no config file defines.
    The block has therefore never rendered.

    Deliberately NOT repaired in the same change that declares the edges — the
    fix is a one-token flip to `redis_docker` but it turns Redis on for a live
    service, which is a runtime change and belongs in its own diff.
    """
    unperformed = {p for p in auto_enable_pairs() if not performs(*p)[0]}
    assert unperformed == UNPERFORMED, (
        f"the repair backlog moved: measured {sorted(UNPERFORMED)}, now "
        f"{sorted(unperformed)}. If a pair was FIXED, declare its edge and remove it "
        f"here (that is the gate working). If a NEW pair appeared, read the probe's "
        f"diagnostics before believing the word 'silently': a template refactor into "
        f"an else-branch used to produce this failure on code that renders correctly."
    )


def test_every_declared_edge_is_performed(committed):
    """Repair before declare, applied to every service→service edge there is.

    The compiler checks an edge against the node set; nothing checks it against
    behaviour. This does, mechanically and for all of them — and it is also the
    freshness check that `measured:` is not: it re-runs on every CI, against
    the current tree, rather than trusting a date somebody typed.
    """
    for consumer, provider in sorted(declared_pairs(committed)):
        ok, notes = performs(consumer, provider)
        assert ok, (
            f"service:{consumer} declares a dependency on service:{provider} that the "
            f"code does not perform:\n  " + "\n  ".join(notes or ["(no mention at all)"])
        )


def test_an_unenforced_edge_says_so_and_an_enforced_one_does_not(committed):
    """C's two backings, distinguished in the ARTIFACT rather than in a filter.

    R1 shipped 23 edges with identical fields and non-identical backing: 22 are
    guaranteed by an `Auto-enable …` block, one (`gitea → woodpecker`) is not,
    and the gate that would have caught it filtered itself down to the three
    database providers. Now the compiler refuses silence in either direction.
    """
    enable = auto_enable_pairs()
    for e in committed["edges"]:
        if not (e["from"].startswith("service:") and e["to"].startswith("service:")):
            continue
        pair = (e["to"].split(":", 1)[1], e["from"].split(":", 1)[1])
        if pair in enable:
            assert e.get("enforced_by"), f"{pair} is auto-enabled but carries no enforced_by"
            assert "unenforced" not in e, f"{pair} is auto-enabled AND disclaimed"
        else:
            assert e.get("enforced_by") is None, f"{pair} claims an enable block it lacks"
            assert e.get("unenforced"), (
                f"{pair}: no `Auto-enable …` block backs this edge and it says nothing "
                f"about that — the playbook will bring {pair[0]} up with no "
                f"{pair[1]}, and the declaration reads like the 22 that cannot"
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
        f"only {counts['declared']} services carry a dependency survey — a FLOOR, not "
        f"the measurement: 25 carried one when R2 shipped"
    )
    assert counts["not-surveyed"] > 0, (
        "every service now claims a survey; if that is true, say so by deleting this "
        "assertion deliberately — do not let a silent zero certify 63 unread roles"
    )


def test_the_counts_publish_the_unsurveyed_remainder(committed):
    c = committed["counts"]
    for key in ("edges_service_dependency", "edges_service_dependency_unenforced",
                "services_survey_declared", "services_survey_not_surveyed",
                "services_survey_no_manifest"):
        assert key in c, f"counts lost {key} — the survey's own shape stopped being countable"
    total = (c["services_survey_declared"] + c["services_survey_not_surveyed"]
             + c["services_survey_no_manifest"])
    assert total == c["nodes_service"], (
        f"survey states cover {total} of {c['nodes_service']} services — a service "
        f"fell out of all three buckets"
    )
    assert c["edges_service_dependency"] >= 20, (
        f"only {c['edges_service_dependency']} service→service edges — a FLOOR (35 when "
        f"R2 shipped). The exact set is pinned by the A∩B and sweep gates above; this "
        f"one only catches a wholesale collapse."
    )


def test_service_authentik_is_not_a_leaf(committed):
    """The finding all three R1 reviews opened with, pinned.

    `service:authentik` had out-degree 0 while carrying `dependency_survey:
    declared`, so the graph — asked the question this epic exists to answer —
    replied "nothing depends on Authentik" in the calm voice of a surveyed
    node. The 38 provider objects edged to their services and had no in-edge at
    all: orphan roots, not objects inside a service.
    """
    out = [e for e in committed["edges"] if e["from"] == "service:authentik"]
    assert out, "service:authentik has out-degree 0 again — see derive_authentik_hosting"
    hosted = {e["to"] for e in out if e["to"].startswith("authentik:")}
    orphans = sorted(
        nid for nid, n in committed["nodes"].items()
        if n.get("kind") == "authentik" and nid not in hosted)
    assert not orphans, (
        f"authentik provider objects with no hosting edge: {orphans} — each is an "
        f"object INSIDE Authentik, and one without an in-edge is an orphan root that "
        f"contributes nothing to the blast radius of the service that carries it"
    )


def test_the_phantom_install_flags_are_named():
    """Three identifiers read by committed code and defined in NO config source.

    `install_redis` is why the OnlyOffice Redis block has never rendered. The
    other two came out of the same sweep and R1's write-up named neither, which
    under-reported its own measurement. Pinned rather than fixed: repairing
    install_redis turns Redis on for a live service.
    """
    keys = config_layer_keys()
    for flag, readers in sorted(PHANTOM_FLAGS.items()):
        assert flag not in keys, (
            f"`{flag}` is now a real variable — the phantom was fixed. Re-check its "
            f"readers, declare any edge that starts rendering, and delete this row."
        )
        for rel in readers:
            assert flag in (REPO / rel).read_text(encoding="utf-8"), (
                f"{rel} no longer reads {flag} — if it was repaired, update UNPERFORMED "
                f"and this list together"
            )


# ── the probe's own failure modes, on fixtures ────────────────────────────
#
#   Every case below was RED against the pre-R2 probe. Four are false REDs on
#   correct templates (the expensive direction: a gate that blocks a release
#   while telling the operator a healthy service has lost its database), one is
#   a false GREEN. Reproduced, then fixed.


def _reaches(fixture: str, provider: str, extra_keys: set[str] = frozenset()) -> bool:
    flat, dead = reachable_text(fixture, set(config_layer_keys()) | set(extra_keys))
    from service_edge_probe import host_position_re, is_host_context
    for m in host_position_re(provider).finditer(flat):
        at = m.end() - len(provider)
        if is_host_context(flat, at) and not dead[at]:
            return True
    return False


def test_an_else_branch_is_the_branch_that_renders():
    """The guard stack never popped on `{% else %}`, and 34 role templates use
    one. Moving `DB_HOST: mariadb` into the else-branch of an existing guard —
    byte-identical render for the default case — flipped a true edge to False
    and the equality gate announced "a live dependency has silently stopped
    rendering" about a template that is correct."""
    assert _reaches("""
{% if freepbx_lan_access %}
      DB_HOST: "{{ external_db_host }}"
{% else %}
      DB_HOST: mariadb
{% endif %}
""", "mariadb")


def test_an_elif_chain_reaches_its_live_branch():
    assert _reaches("""
{% if freepbx_lan_access %}
      DB_HOST: elsewhere
{% elif install_mariadb %}
      DB_HOST: mariadb
{% endif %}
""", "mariadb")


def test_an_or_guard_survives_one_unknown_operand():
    """`{% if phantom or install_mariadb %}` renders. The first probe called it
    dead because it unioned every identifier in the condition."""
    assert _reaches("""
{% if freepbx_lan_access or install_mariadb %}
      DB_HOST: mariadb
{% endif %}
""", "mariadb")


def test_an_inline_if_is_evaluated_at_the_mention():
    """The false GREEN, and it is the one that would have let a dead edge be
    declared. roles/pazny.nextcloud/templates/compose.yml.j2:24 puts the whole
    if/else on one line; the first probe scanned a line's tags before checking
    its text, so an inline guard had already been popped and read as absent."""
    assert not _reaches(
        '      DB_HOST: "{% if install_redis %}mariadb{% else %}127.0.0.1{% endif %}"',
        "mariadb")


def test_a_jinja_comment_block_is_not_evidence():
    """`performs('grafana','redis')` scored compose.yml.j2:93 — the second line
    of a `{# … #}` block. `line.startswith('#')` cannot see a Jinja comment,
    and a comment is not evidence."""
    assert not _reaches("""
{# ─────────────
   the shared network bridges to infra services (postgres,
   DB_HOST: mariadb), which advertise themselves there
   ───────────── #}
      OTHER: "x"
""", "mariadb")


def test_a_label_field_is_not_a_host():
    """`{'db': 'paperclip'}` inside the PROVIDER's own CREATE DATABASE loop
    (roles/pazny.postgresql/tasks/post.yml:234) read as `postgresql →
    paperclip`: a provider depending on its consumer."""
    assert not _reaches("        - {'db': 'paperclip', 'user': 'paperclip'}", "paperclip")
    assert not _reaches('      image: grafana/loki:{{ loki_version }}', "grafana")


def test_the_two_false_positives_the_reviews_measured_are_refused():
    """Both were certified TRUE by the substring probe, and both are the
    service's OWN bundled database, not the estate's."""
    assert not performs("gitlab", "postgresql")[0], (
        "roles/pazny.gitlab/templates/compose.yml.j2:36 `postgresql['shared_buffers']` "
        "is GitLab Omnibus configuring its own bundled Postgres"
    )
    assert not performs("onlyoffice", "postgresql")[0], (
        "roles/pazny.onlyoffice/templates/compose.yml.j2:29 `/var/lib/postgresql` is "
        "the volume of OnlyOffice's baked internal cluster"
    )


def test_the_probe_reaches_past_the_compose_template():
    """The false NEGATIVE that hid a live dependency: one path was read, and
    mcpo's DSN lives in mcpo-config.json.j2 while its psql exec lives in
    post.yml. `(False, [])` was reported to the operator as "(no mention at
    all)", which is the opposite of true."""
    ok, notes = performs("mcp_gateway", "postgresql")
    assert ok and any("mcpo-config.json.j2" in n for n in notes), notes
    assert any("post.yml" in n for n in notes), notes


def test_a_provider_is_reachable_by_its_manifest_domain_var():
    """Woodpecker reaches Gitea by `{{ gitea_domain }}`, never by the compose
    hostname. A probe that only knows hostnames calls that edge false, so the
    aliases come from the manifest's own `domain_var`/`port_var`."""
    assert "gitea_domain" in provider_aliases()["gitea"]
    ok, notes = performs("woodpecker", "gitea")
    assert ok and any("gitea_domain" in n for n in notes), notes


def test_the_config_layer_reads_more_than_three_sources():
    """A guard is called DEAD when its identifiers exist nowhere, so a narrow
    reading of "nowhere" produces false REDs on correct templates. These four
    live outside the original three sources."""
    keys = config_layer_keys()
    for name in ("redis_docker", "install_mariadb", "install_postgresql"):
        assert name in keys, f"{name} (a main.yml set_fact) reads as undefined"


# ── the compiler's refusals ───────────────────────────────────────────────


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
        "service:gitea": {"kind": "service", "install_flag": "install_gitea"},
    }


def test_run_outcome_words_are_refused_on_a_service_edge(gen):
    """`expects: succeeded` is a claim about a RUN, and a database has none.

    Left unrefused, every service edge would inherit the pulse default and the
    artifact would carry 35 unfalsifiable assertions.
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
    satisfied the existing staleness check by matching two absences.
    """
    nodes = _service_pair()
    raw = [("service:outline",
            {"upstream": "service:postgresql", "kind": "temporal",
             "margin_min": 5, "schedules": [None, None]}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


def test_an_unbacked_service_edge_must_declare_its_own_weakness(gen):
    """No auto-enable block ties install_gitea to anything, so an edge from it
    that says nothing would read exactly like the 22 the playbook guarantees."""
    nodes = _service_pair()
    silent = [("service:outline",
               {"upstream": "service:gitea", "kind": "data", "via": "x"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(silent, nodes)

    spoken = [("service:outline",
               {"upstream": "service:gitea", "kind": "data", "via": "x",
                "unenforced": "nothing turns gitea on for outline"}, "src")]
    edge = gen.compile_declared(spoken, nodes)[0]
    assert edge["enforced_by"] is None and edge["unenforced"]


def test_a_disclaimer_the_playbook_contradicts_is_refused(gen):
    """The other direction: `unenforced:` on an edge main.yml DOES enable is a
    warning about a risk that does not exist, and it ages into folklore."""
    nodes = _service_pair()
    raw = [("service:outline",
            {"upstream": "service:postgresql", "kind": "data", "via": "x",
             "unenforced": "nothing enables it"}, "src")]
    with pytest.raises(SystemExit):
        gen.compile_declared(raw, nodes)


def test_a_misspelled_depends_on_key_is_refused(gen, tmp_path):
    """plugin.schema.json is `additionalProperties: true` at the top level, so
    `depends-on:` VALIDATES at converge and was then dropped here in silence,
    leaving the service reading `not-surveyed` — an absence caused by a typo,
    wearing the same face as an absence caused by nobody looking."""
    plugin = tmp_path / "files" / "anatomy" / "plugins" / "ghost-base"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yml").write_text("name: ghost-base\ndependsOn:\n  - x\n")
    original = gen.REPO
    try:
        gen.REPO = tmp_path
        with pytest.raises(SystemExit):
            gen.harvest_service_deps({}, [])
    finally:
        gen.REPO = original
