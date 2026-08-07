#!/usr/bin/env python3
"""Compile the anatomy graph — every declared actor and edge, one address space.

WHAT THIS IS
------------
The estate's automated actors (pulse jobs, judges, gate sets, weakness
sources, host daemons, services, mutex resources) and the edges between them
(`depends_on` in the pulse-job manifests) compiled into ONE artifact:
`state/anatomy-graph.json`. Design + measurement:
docs/archive/nos-anatomy-graph.md; the address space is §2(b), the refusals
the gate enforces are §2(c).

This is the estate's regenerate-and-diff pattern (genome-codegen,
tofu-authentik-gen-registry, gdpr-dpa-register --check) pointed at a new
source — not new machinery. The committed JSON is byte-stable: no timestamps,
sorted keys, sorted edges. CI goes red on drift via
tests/anatomy/test_anatomy_graph_is_sound.py, which imports build() from here.

ONE DIVERGENCE FROM THE SURVEY'S EDGE SHAPE (§2a): the edge field is
`upstream:`, not `on:`. PyYAML implements YAML 1.1, where a bare `on` key is
the BOOLEAN True — `yaml.safe_load("on: x")` returns `{True: "x"}` — so the
surveyed spelling silently loses the field name in every reader in the estate.
Same trap class as the Norway problem; refused rather than accommodated.

ADDRESS SPACE (kind-prefixed, local ids verbatim — §2b)
-------------------------------------------------------
    pulse:<owner>:<job>     owner = plugin name minus -base, or agent_id
                            (matches wing.db pulse_jobs id, e.g. keap:keap-lint)
    judge:<name>            state/judge-sets.yml key
    gateset:<name>          state/judge-sets.yml gate_sets key
    weakness:<id>           files/anatomy/bone/weaknesses.py SOURCE_ORDER
    daemon:<launchd label>  eu.thisisait.nos.* labels from role defaults
    service:<manifest id>   state/manifest.yml services[].id
    resource:<name>         mutex/capability resources (claims + requires)
    repo:<name>             git surfaces jobs touch (curated, each node pinned
                            to the code that touches it — see REPO_SURFACES)
    tofu:<name>             OpenTofu state roots (terraform/<name>/)
    authentik:<slug>        state/tofu-authentik-services.yml registry rows
    table:<name>            state/keap-tables/<name>.table.yml definitions
    faceapp:<slug>          nOS-face apps, from the face's own registry — the
                            `form` axis (view|utility|widget|frame) and the
                            independent `build` axis (F1–F4/H). Frames are NOT
                            emitted: a hub service already has a service: node
                            and a second address for it would be padding.

SERVICE→SERVICE DEPENDENCIES (docs/idea/13-relations.md R1)
-----------------------------------------------------------
A service plugin declares, at its TOP level, what its service cannot run
without — same key, same shape and same refusals as a pulse job's
`depends_on`, one level up. The declarations are TRANSCRIBED from the four
places the estate already held the fact as behaviour (main.yml's three
auto-enable blocks, roles/pazny.postgresql/tasks/post.yml's CREATE DATABASE
loop, default.config.yml's mariadb_databases, requires.peer_service), never
authored from memory.

Every service node therefore carries `dependency_survey`, because a service
with no upstreams must not be indistinguishable from one nobody looked at:

    declared       the plugin carries a depends_on: block. An EMPTY block is
                   the positive statement "surveyed, no upstreams" — that is
                   what makes a node an L0 root rather than an unread one.
    not-surveyed   a plugin exists and carries no block
    no-manifest    no <id>-base plugin at all

WRITES (the second declared channel)
------------------------------------
`depends_on` declares what a job READS (consumer-side, upstream → job).
`writes:` declares what a job WRITES (actor-side, job → target): the job is
the one actor that knows its own output, and the target (a repo ref, a KEAP
table) is passive substrate that cannot declare anything. Same refusals as
depends_on: the target must resolve, `via:` must name the artifact. Each
shipped writes edge additionally carries a code pin in
test_anatomy_graph_is_sound.py (repair before declare — the edge exists only
while the command it describes still performs the write).

WHAT IS DERIVED, NOT DECLARED
-----------------------------
  * mutex pairs — from `claims:` on nodes (pairwise edges are REFUSED as
    declarations, §2a: with N claimants they take N(N-1)/2 edges to stay true)
  * the agent-run-lock claim — any job whose command runs pulse-run-agent.sh
    or scan-runner.sh takes ~/.nos/agent-run.lock via agent-run-lock.sh
    (one law, one implementation — commit ba7a9471)
  * daemon:eu.thisisait.nos.pulse → job dispatch edges (structural: the
    daemon fires every unpaused job; pulse/daemon.py list_due_jobs)
  * judge capability edges — judge-sets `requires:` become data edges from
    resource:* nodes (satisfied or not, never exclusive)
  * temporal debt — for every temporal edge, the worst-case DECLARED margin
    (cron gap − upstream jitter − upstream max_runtime) and whether the
    declared budgets already permit inversion (§1.4 col 4)

Usage:
    python3 tools/anatomy-graph-gen.py            # write state/anatomy-graph.json
    python3 tools/anatomy-graph-gen.py --check    # exit 1 if the artifact is stale
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "state" / "anatomy-graph.json"
#: Byte-identical vendored copy for the face. The face container's build
#: context is files/anatomy/face/ ONLY (roles/pazny.face synchronize task), so
#: the definition screen's build-time JSON import cannot reach state/ — the
#: generator writes both and --check refuses drift between them.
FACE_TARGET = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "anatomy" / \
    "anatomy-graph.json"

#: The face's app registry — the declaration site of the `form` axis
#: (view | utility | widget | frame) and the `build` axis (F1–F4/H).
FACE_REGISTRY = REPO / "files" / "anatomy" / "face" / "src" / "lib" / "apps" / \
    "native" / "registry.ts"

JOB_SOURCES = ("files/anatomy/plugins/*/plugin.yml", "files/anatomy/agents/*.yml")
JUDGE_SETS = REPO / "state" / "judge-sets.yml"
WEAKNESSES = REPO / "files" / "anatomy" / "bone" / "weaknesses.py"
MANIFEST = REPO / "state" / "manifest.yml"
TOFU_REGISTRY = REPO / "state" / "tofu-authentik-services.yml"
KEAP_TABLES = REPO / "state" / "keap-tables"

#: The git surfaces the estate's jobs and operator tools touch (operator ask,
#: 2026-08-06). Curated because no committed file declares remotes — each node
#: names the code that is its evidence, and each carries `automated_writers`
#: so ABSENCE of an automated writer is a stated fact, not an omission:
#: nothing automated may push the public trunk (promote-public.sh is
#: gh-auth-gated operator-only, :39-40), and that is doctrine, not a gap.
REPO_SURFACES: dict[str, dict] = {
    "github-origin": {
        "role": "public trunk (github.com/thisisait/nOS)",
        "automated_writers": [],
        "operator_tools": ["tools/promote-public.sh", "tools/nos-push"],
        "evidence": "tools/promote-public.sh:39-40 (gh-auth operator-only gate)",
    },
    "gitea-forge": {
        "role": "local writable forge + Woodpecker CI source (T32.2 Model A)",
        "hosted_by": "service:gitea",
        "automated_writers": [],
        "operator_tools": ["tools/nos-push", "tools/sync-trunk-to-gitea.sh"],
        "evidence": "tools/sync-trunk-to-gitea.sh:2-8 (operator-host-only, FF-only)",
    },
    "gitlab-forge": {
        "role": "agent forge / MR review surface (T32.2)",
        "hosted_by": "service:gitlab",
        "operator_tools": ["tools/migration-pr.sh", "tools/recipe-pr.sh"],
        "evidence": "default.config.yml nos_agent_forge + tools/migration-pr.sh:19-21",
    },
    "scan-data": {
        "role": "orphan branch — nightly security snapshot ledger (local ref only; "
                "the recording job passes no --push)",
        "ref": "refs/heads/scan-data",
        "evidence": "tools/scan-state-snapshot.py:90 (BRANCH), :237 (moves one ref)",
    },
}

TAXONOMY_BUNDLE = REPO / "state" / "fable" / "taxonomy-bundle.json"

#: KEAP taxonomy anchors (ids from state/fable/taxonomy-bundle.json `anchor`,
#: the committed 362-anchor spine). Every node gets one so a KEAP import is
#: never 179 `orphan-object` findings — keap-lint measured 26/27 findings as
#: exactly that against unanchored fixtures ("invisible in the universe").
#: Per-kind default, refined per category where the branch is unambiguous;
#: everything else is honestly generic Software Engineering rather than a
#: guessed leaf. The soundness gate refuses an anchor the bundle does not hold.
PULSE_ANCHORS = {
    "security": "02.02.08",       # Computer Security
    "agents": "02.02.09",         # Artificial Intelligence
    "knowledge": "09",            # Reference & Documentation
    "notification": "03.08",      # Telecommunications
    "compliance": "04.06",        # Law
    "platform": "02.02.06",       # Operating Systems
}
SERVICE_ANCHORS = {
    "database": "02.02.05", "cache": "02.02.05",
    "security": "02.02.08", "vault": "02.02.08", "identity": "02.02.08",
    "ai": "02.02.09", "agent": "02.02.09",
    "observability": "02.02.06", "monitoring": "02.02.06",
    "proxy": "02.02.07", "vpn": "02.02.07",
    "mail": "03.08", "messaging": "03.08", "notifications": "03.08", "pbx": "03.08",
    "knowledge": "09", "wiki": "09",
    "storage": "11.04",
}
KIND_ANCHORS = {
    "judge": "02.02.04", "gateset": "02.02.04",
    "weakness": "02.02.08",
    "daemon": "02.02.06",
    "resource": "02.02.06",       # concurrency primitives are an OS concept
    "repo": "02.02.04",
    "tofu": "02.02.04",
    "authentik": "02.02.08",
    "table": "02.02.05",
    "doctrine": "09",             # Reference & Documentation — the law shelf
    # No HCI / user-interface branch exists in the 362-anchor spine (checked
    # 2026-08-07: only Computer Graphics and Graphic Design come close, and
    # neither is what a face app is). Honestly generic rather than a guessed
    # leaf, exactly as this table's header says.
    "faceapp": "02.02.04",
}
FALLBACK_ANCHOR = "02.02.04"      # Software Engineering

#: What each host daemon IS — curated because launchd labels carry no prose
#: anywhere in the repo. One line each, estate vocabulary.
DAEMON_DESC = {
    "acme-renew": "renews the estate's TLS certificates on schedule",
    "backrest": "Backrest backup orchestrator (restic UI spike)",
    "backup.exporter": "exports backup outcome metrics for Prometheus scraping",
    "backup.offsite": "ships the nightly backup set to the offsite target",
    "backup.rustfs": "nightly backup of service data into RustFS",
    "bone": "Bone — the local FastAPI bridge between Ansible runs and Wing's SQLite store",
    "cortex": "cortex organ server — the KEAP-facing knowledge mirror API",
    "heartbeat": "host heartbeat — periodic liveness signal into the estate's telemetry",
    "hermes": "Hermes web-UI daemon (loopback-only, opt-in) — cross-channel agent gateway",
    "pulse": "Pulse — the host-side scheduled-job runner dispatching every unpaused pulse job",
    "resume": "post-boot resume hook — re-establishes host state after a reboot",
    "wing": "Wing — the Nette/FrankenPHP dashboard and state-framework UI",
}


#: Commands that spawn a claude CLI go through the one mkdir mutex
#: (files/anatomy/scripts/agent-run-lock.sh). Derived, not declared: the claim
#: is a fact about the code, and the code has exactly two spawn sites.
AGENT_LOCK_COMMANDS = ("pulse-run-agent.sh", "scan-runner.sh")
AGENT_LOCK_RESOURCE = "agent-run-lock"

EDGE_KINDS = ("data", "trigger", "temporal")


def _die(msg: str) -> None:
    print(f"anatomy-graph-gen: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _iso(v) -> str | None:
    """yaml gives `measured: 2026-08-06` as a date object; normalise to str."""
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


# ── harvest: pulse jobs ───────────────────────────────────────────────────


def _owner(doc: dict, path: Path) -> str:
    return re.sub(r"-base$", "", str(doc.get("name") or doc.get("agent_id") or path.stem))


def harvest_pulse(nodes: dict, raw_edges: list, raw_writes: list) -> None:
    for pattern in JOB_SOURCES:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(doc, dict):
                continue
            owner = _owner(doc, path)
            for job in (doc.get("pulse") or {}).get("jobs") or []:
                if not (isinstance(job, dict) and job.get("name")):
                    continue
                nid = f"pulse:{owner}:{job['name']}"
                claims = sorted(set(job.get("claims") or []))
                cmd = str(job.get("command") or "")
                if any(cmd.endswith(s) for s in AGENT_LOCK_COMMANDS):
                    claims = sorted(set(claims) | {AGENT_LOCK_RESOURCE})
                nodes[nid] = {
                    "kind": "pulse",
                    "source": str(path.relative_to(REPO)),
                    "schedule": job.get("schedule"),
                    "jitter_min": job.get("jitter_min", 0),
                    "max_runtime_s": job.get("max_runtime_s", 300),
                    "category": job.get("category"),
                    "paused": bool(job.get("paused", False)),
                    "findings_exit_codes": job.get("findings_exit_codes"),
                    # Basename only — the full path is host layout (the same
                    # allow-list judgement the face's pulse projection makes).
                    "command_name": cmd.rsplit("/", 1)[-1] or None,
                    "claims": claims,
                }
                for dep in job.get("depends_on") or []:
                    raw_edges.append((nid, dep, str(path.relative_to(REPO))))
                for w in job.get("writes") or []:
                    raw_writes.append((nid, w, str(path.relative_to(REPO))))


# ── harvest: judges + gate sets ───────────────────────────────────────────


def harvest_judges(nodes: dict, edges: list) -> None:
    doc = yaml.safe_load(JUDGE_SETS.read_text(encoding="utf-8"))
    for name, j in (doc.get("judges") or {}).items():
        claims = [j["exclusive_resource"]] if j.get("exclusive_resource") else []
        nodes[f"judge:{name}"] = {
            "kind": "judge",
            "source": "state/judge-sets.yml",
            "deterministic": j.get("deterministic"),
            "mutates_worktree": j.get("mutates_worktree"),
            "min_work": j.get("min_work"),
            "argv": list(j.get("argv") or []),
            "claims": claims,
            "requires": list(j.get("requires") or []),
        }
        for cap in j.get("requires") or []:
            edges.append({
                "from": f"resource:{cap}",
                "to": f"judge:{name}",
                "kind": "data",
                "via": "capability requirement (judge-sets requires:) — satisfied or not, never exclusive",
                "derived": "judge-sets.requires",
            })
    for name, gs in (doc.get("gate_sets") or {}).items():
        nodes[f"gateset:{name}"] = {
            "kind": "gateset",
            "source": "state/judge-sets.yml",
            "judges": list(gs.get("judges") or []),
            "unattended": bool(gs.get("unattended", False)),
        }


# ── annotate: taxonomy anchor + one-line description per node ─────────────
#    (KEAP-import shaping, 2026-08-06: an unanchored object is an
#    `orphan-object` — invisible to KEAP search and panels — and a body of
#    `{"kind": "daemon"}` gives hybrid search nothing to embed. The anchor
#    ids come from the committed taxonomy bundle and the gate refuses one
#    the bundle does not hold.)


def _anchor(nid: str, n: dict) -> str:
    kind = n["kind"]
    if kind == "pulse":
        return PULSE_ANCHORS.get(n.get("category"), FALLBACK_ANCHOR)
    if kind == "service":
        return SERVICE_ANCHORS.get(n.get("category"), FALLBACK_ANCHOR)
    if kind == "daemon" and ".backup." in nid:
        return "11.04"  # Backup Strategies
    return KIND_ANCHORS.get(kind, FALLBACK_ANCHOR)


def _describe(nid: str, n: dict) -> str:
    kind, local = n["kind"], nid.split(":", 1)[1]
    if kind == "pulse":
        bits = [f"Pulse scheduled job ({n.get('category') or 'uncategorised'}):",
                f"runs {n.get('command_name') or 'an undeclared command'}",
                f"on cron `{n.get('schedule')}`"]
        if n.get("paused"):
            bits.append("— PAUSED (deliberate operator decision, not a health state)")
        if n.get("findings_exit_codes"):
            bits.append(f"— exits {n['findings_exit_codes']} mean findings, not failure")
        return " ".join(bits)
    if kind == "judge":
        return (f"Loop judge: gate command `{' '.join(n.get('argv') or [])}` — "
                f"work floor min_work={n.get('min_work')}, "
                f"deterministic={n.get('deterministic')}")
    if kind == "gateset":
        u = "may run unattended" if n.get("unattended") else "requires an attended host"
        return f"Judge gate set over [{', '.join(n.get('judges') or [])}] — {u}"
    if kind == "weakness":
        need = "required" if n.get("required") else "optional"
        return (f"Bone weakness source '{local}' ({need}) — one of the readers whose "
                f"findings become loop_proposals rows")
    if kind == "daemon":
        label = local.removeprefix("eu.thisisait.nos.")
        what = DAEMON_DESC.get(label, "host daemon")
        return f"Host launchd daemon {local} — {what}"
    if kind == "service":
        return (f"Docker service '{local}' ({n.get('category')}) in the "
                f"{n.get('stack')} compose stack, toggled by {n.get('install_flag')}")
    if kind == "resource":
        if "requires" in str(n.get("source")):
            return (f"Capability resource '{local}' — required by judges, satisfied "
                    f"or not, never exclusive")
        return (f"Exclusion resource '{local}' — nodes claiming it are pairwise "
                f"mutually exclusive (mutex edges derived from claims)")
    if kind == "repo":
        return f"Git surface: {n.get('role')}"
    if kind == "tofu":
        return (f"OpenTofu state root {n.get('source')} — the declarative authority "
                f"over Authentik providers/applications/outposts; plan daily, "
                f"apply only at converge behind the destroy-guard")
    if kind == "authentik":
        svc = (f"gates service:{n['service']}" if n.get("service")
               else "no manifest service (Tier-2 app or excluded install)")
        return (f"Authentik {n.get('mode')} client '{n.get('client_id')}' "
                f"(RBAC tier {n.get('tier')}) — {svc}; provider+application "
                f"managed by OpenTofu from the committed registry")
    if kind == "faceapp":
        # Two axes in one line, named as two, because the field they replaced
        # was one boolean pretending to be both.
        build = n.get("build") or "no build tier (not an agent-built app)"
        scopes = ", ".join(n.get("api_scopes") or []) or "no declared BFF scope"
        return (f"nOS-face app '{n.get('title')}' — form: {n.get('form')} "
                f"(what it is on screen), build: {build} (what it cost to "
                f"build, docs/doctrine/face-app-tiers.md); reads {scopes}")
    if kind == "table":
        return f"KEAP DataTable definition '{n.get('title')}' ({n['source']})"
    if kind == "doctrine":
        head = n.get("heading") or "(unheaded table-row address)"
        return (f"Constitution paragraph {n.get('section')} of {n['source']}: "
                f"{head}")
    return f"{kind} node {local}"


def annotate_nodes(nodes: dict) -> None:
    for nid, n in nodes.items():
        n["anchor"] = _anchor(nid, n)
        n["description"] = _describe(nid, n)


# ── harvest: weakness sources (regex over the reader — it declares its own
#    order and this must not import a FastAPI app to read a tuple) ─────────


def harvest_weaknesses(nodes: dict) -> None:
    text = WEAKNESSES.read_text(encoding="utf-8")
    m = re.search(r"SOURCE_ORDER:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\)", text, re.S)
    if not m:
        _die("weaknesses.py SOURCE_ORDER not found — the reader moved, update the harvest")
    names = re.findall(r'"([a-z\-]+)"', m.group(1))
    req = re.search(r"SOURCE_REQUIRED:\s*dict\[str,\s*bool\]\s*=\s*\{(.*?)\}", text, re.S)
    required = dict(re.findall(r'"([a-z\-]+)":\s*(True|False)', req.group(1))) if req else {}
    for name in names:
        nodes[f"weakness:{name}"] = {
            "kind": "weakness",
            "source": "files/anatomy/bone/weaknesses.py",
            "required": required.get(name) == "True",
        }


# ── harvest: daemons (launchd labels are declared as role-default values;
#    the resume plist is the one template with a literal filename) ─────────


def harvest_daemons(nodes: dict) -> None:
    labels: set[str] = set()
    for pattern in ("roles/*/defaults/main.yml", "default.config.yml"):
        for path in sorted(REPO.glob(pattern)):
            for line in path.read_text(encoding="utf-8").splitlines():
                lm = re.match(r'(\w+):\s*"(eu\.thisisait\.nos\.[a-z.\-]+)"', line.strip())
                if lm and "legacy" not in lm.group(1):
                    labels.add(lm.group(2))
    for path in sorted(REPO.glob("templates/eu.thisisait.nos.*.plist.j2")):
        labels.add(path.name.removesuffix(".plist.j2"))
    for label in sorted(labels):
        nodes[f"daemon:{label}"] = {"kind": "daemon", "source": "launchd label (role defaults)"}


# ── harvest: services ─────────────────────────────────────────────────────


def harvest_services(nodes: dict) -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    for svc in doc.get("services") or []:
        if isinstance(svc, dict) and svc.get("id"):
            nodes[f"service:{svc['id']}"] = {
                "kind": "service",
                "source": "state/manifest.yml",
                "stack": svc.get("stack"),
                "category": svc.get("category"),
                "install_flag": svc.get("install_flag"),
            }


# ── harvest: service→service dependencies, consumer-side (R1) ─────────────


def _consumer_service(doc: dict, path: Path, nodes: dict) -> str | None:
    """Which service node this plugin speaks for.

    Slug rule first (`<x>-base` → `service:<x with dashes→underscores>`,
    which resolves for 59 of the 63 manifest services), `requires.feature_flag`
    as the fallback and only when it names EXACTLY one service —
    install_observability names five, and a graph must not guess which.
    """
    slug = re.sub(r"-base$", "", str(doc.get("name") or path.parent.name))
    for cand in (slug, slug.replace("-", "_")):
        if f"service:{cand}" in nodes:
            return f"service:{cand}"
    flag = (doc.get("requires") or {}).get("feature_flag")
    if flag:
        hits = [nid for nid, n in nodes.items()
                if n["kind"] == "service" and n.get("install_flag") == flag]
        if len(hits) == 1:
            return hits[0]
    return None


#: Top-level keys a plugin might mean as `depends_on` and spell otherwise.
#: plugin.schema.json is `additionalProperties: true` at the top level, so
#: `depends-on:` / `dependsOn:` VALIDATES at converge and is then dropped
#: silently here, leaving the node reading `not-surveyed` — an absence caused
#: by a typo, wearing the same face as an absence caused by nobody looking.
#: Compared against the key with every non-letter stripped, so `depends-on`,
#: `dependsOn`, `depends_On` and `DEPENDS-ON` all land on `dependson`.
_DEPENDS_ON_NEAR_MISSES = ("dependson", "dependencies", "dependencyies",
                           "dependon", "requiresservice", "depends")


def harvest_service_deps(nodes: dict, raw_edges: list) -> None:
    """Top-level `depends_on:` on a service plugin → service→service edges.

    Runs AFTER harvest_services (it resolves against the compiled service
    nodes) and marks the survey state of every service node, including the
    ones no plugin speaks for.
    """
    surveyed: dict[str, str] = {}
    for path in sorted(REPO.glob("files/anatomy/plugins/*/plugin.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        for key in doc:
            if str(key) != "depends_on" and re.sub(
                    r"[^a-z]", "", str(key).lower()) in _DEPENDS_ON_NEAR_MISSES:
                _die(f"{path.relative_to(REPO)}: top-level key {key!r} looks like a "
                     f"misspelling of `depends_on` — the plugin schema accepts unknown "
                     f"top-level keys, so this would validate at converge and be dropped "
                     f"here, leaving the service reading 'not-surveyed'")
        consumer = _consumer_service(doc, path, nodes)
        if consumer is None:
            # A composition plugin (alloy-*, grafana-*) or a Tier-2 app plugin
            # speaks for no manifest service. Declaring a dependency from a
            # plugin with no address is refused loudly rather than dropped.
            if "depends_on" in doc:
                _die(f"{path.relative_to(REPO)}: declares depends_on but resolves to no "
                     f"service node — a graph lying at birth (add the service to "
                     f"state/manifest.yml, or move the declaration to the plugin that "
                     f"owns the consuming service)")
            continue
        if "depends_on" not in doc:
            surveyed.setdefault(consumer, "not-surveyed")
            continue
        surveyed[consumer] = "declared"
        for dep in doc.get("depends_on") or []:
            raw_edges.append((consumer, dep, str(path.relative_to(REPO))))

    for nid, n in nodes.items():
        if n["kind"] != "service":
            continue
        # Three states, none of which is a calm default: a service nobody has
        # looked at reads differently from one measured to have no upstreams.
        n["dependency_survey"] = surveyed.get(nid, "no-manifest")


# ── harvest: git surfaces + tofu state (operator ask, 2026-08-06) ─────────


def harvest_repos_and_tofu(nodes: dict) -> None:
    # repo:scan-data exists only while the recorder still writes that branch —
    # the same repair-before-declare shape as the halt edge, applied at
    # compile time: the node vanishes with the code, and the writes edge
    # pointing at it then fails compilation loudly.
    snapshot = (REPO / "tools" / "scan-state-snapshot.py")
    scan_data_backed = snapshot.exists() and 'BRANCH = "scan-data"' in snapshot.read_text(
        encoding="utf-8")
    for name, facts in REPO_SURFACES.items():
        if name == "scan-data" and not scan_data_backed:
            continue
        nodes[f"repo:{name}"] = {"kind": "repo", "source": "curated (anatomy-graph-gen "
                                 "REPO_SURFACES)", **facts}

    # The OpenTofu Authentik state root. Guards are converge-time scripts, not
    # automated actors, so they are FACTS on the node, not edges — the only
    # scheduled actor touching this state is the plan-only drift job, and that
    # edge is declared consumer-side in its own manifest.
    if (REPO / "terraform" / "authentik").is_dir():
        nodes["tofu:authentik-state"] = {
            "kind": "tofu",
            "source": "terraform/authentik/",
            "engine_flag": "authentik_engine: tofu (default.config.yml)",
            "guards": [
                "reconcile-preflight: tools/tofu-authentik-reconcile.sh --preflight "
                "(identity-only PK re-sync before every plan)",
                "destroy-guard: tasks/tofu-authentik.yml (refuses DESTROY + dangerous "
                "in-place UPDATE outside a supervised apply)",
            ],
            "registry": "state/tofu-authentik-services.yml "
                        "(tools/tofu-authentik-gen-registry.py)",
        }


# ── harvest: authentik registry rows (providers/applications, tofu-owned) ──


def harvest_authentik(nodes: dict) -> None:
    doc = yaml.safe_load(TOFU_REGISTRY.read_text(encoding="utf-8"))
    for row in doc.get("tofu_authentik_services") or []:
        if not (isinstance(row, dict) and row.get("slug")):
            continue
        slug = str(row["slug"])
        # Registry slugs use dashes; manifest service ids use underscores
        # (calibre-web → service:calibre_web). Tier-2 apps (documenso, qdrant,
        # roundcube, …) have no manifest row at all — `service: null` states
        # that, rather than an edge to a node that does not exist.
        service = next((c for c in (slug, slug.replace("-", "_"))
                        if f"service:{c}" in nodes), None)
        nodes[f"authentik:{slug}"] = {
            "kind": "authentik",
            "source": "state/tofu-authentik-services.yml",
            "mode": row.get("mode"),
            "tier": row.get("tier"),
            "client_id": row.get("client_id"),
            "service": service,
            "managed_by": "tofu:authentik-state",
        }


def derive_authentik_hosting(nodes: dict) -> list[dict]:
    """service:authentik → authentik:<slug>, one per registry row.

    THE MEASUREMENT THAT FORCED THIS, and all three adversarial reviews of R1
    opened with it: `service:authentik outgoing: []`. The 43 provider objects
    edged TO their services and had ZERO in-edges, so they were orphan roots
    rather than objects living inside Authentik — and the graph, asked the
    question this whole epic exists to answer ("what breaks if I remove X?"),
    replied "nothing depends on Authentik" about the estate's single most
    load-bearing service, in the calm voice of a surveyed node.

    An `authentik:<slug>` node is not an actor. It is a provider+application
    pair INSIDE the Authentik service, applied there by OpenTofu — which is
    why the node already carried `service:` and `managed_by:` facts and no
    address for its host. Derived, never declared: the registry row IS the
    declaration, and a second hand-written one would be the fifth-place
    problem R1 exists to end.
    """
    if "service:authentik" not in nodes:
        return []
    out = []
    for nid, n in sorted(nodes.items()):
        if n.get("kind") != "authentik":
            continue
        out.append({
            "from": "service:authentik",
            "to": nid,
            "kind": "data",
            "via": f"provider+application object hosted by Authentik "
                   f"(mode={n.get('mode')}) — applied into the running service by "
                   f"terraform/authentik from state/tofu-authentik-services.yml",
            "derived": "authentik-hosting",
        })
    return out


# ── harvest: KEAP DataTable definitions ───────────────────────────────────


# ── harvest: face apps (the `form` axis, docs/doctrine/face-app-tiers.md) ──
#
#    Regex over the registry module, the same shape as harvest_weaknesses over
#    weaknesses.py: the declaration lives in TypeScript, this compiler is
#    Python, and importing a Svelte-flavoured module to read five literals is
#    not worth a toolchain. If the registry is refactored past this pattern
#    the harvest DIES LOUDLY (_die below) rather than silently emitting zero
#    face apps.
#
#    ONLY component-backed apps are emitted. The ~37 hub services the shell
#    renders as `form: frame` are ALREADY nodes — `service:<id>` — and minting
#    a second address for the same thing would be padding, which is the one
#    thing this graph refuses. Their form is recorded in the face, where the
#    render path that establishes it lives.


def harvest_faceapps(nodes: dict) -> None:
    if not FACE_REGISTRY.exists():
        return
    text = FACE_REGISTRY.read_text(encoding="utf-8")
    blocks = re.findall(r"registerNativeApp\(\{(.*?)\n\t\}\);", text, re.S)
    if not blocks:
        _die("face registry: no registerNativeApp({…}) blocks matched — the registry "
             "moved, update harvest_faceapps rather than shipping zero face apps")
    for body in blocks:
        def field(name: str) -> str | None:
            m = re.search(rf"\b{name}:\s*'([^']*)'", body)
            return m.group(1) if m else None

        slug, form = field("slug"), field("form")
        if not slug or not form:
            continue
        scopes = re.search(r"apiScopes:\s*\[([^\]]*)\]", body)
        nodes[f"faceapp:{slug}"] = {
            "kind": "faceapp",
            "source": str(FACE_REGISTRY.relative_to(REPO)),
            # The two axes, kept apart on purpose: `form` is what the thing IS,
            # `build` is what it COST. Neither is derived from the other, here
            # or in the face.
            "form": form,
            "build": field("build"),
            "title": field("title"),
            "api_scopes": re.findall(r"'([^']+)'", scopes.group(1)) if scopes else [],
        }


def harvest_tables(nodes: dict) -> None:
    for path in sorted(KEAP_TABLES.glob("*.table.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        name = path.name.removesuffix(".table.yml")
        nodes[f"table:{name}"] = {
            "kind": "table",
            "source": str(path.relative_to(REPO)),
            "title": doc.get("title"),
        }


# ── edges: validate declarations, derive structure ────────────────────────


def _cron_minute(schedule: str | None) -> int | None:
    parts = (schedule or "").split()
    if len(parts) != 5 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return int(parts[1]) * 60 + int(parts[0])


#: `set_fact` key → the service that fact turns on, for main.yml's three
#: `Auto-enable <provider> for services that require it` blocks. `install_redis`
#: is deliberately absent: the Redis toggle is `redis_docker`, and the manifest
#: row's `install_flag: install_redis` names a variable no config file defines.
_AUTO_ENABLE_FACTS = {
    "install_mariadb": "mariadb",
    "install_postgresql": "postgresql",
    "redis_docker": "redis",
}


def auto_enabled_pairs() -> dict[tuple[str, str], str]:
    """(consumer_flag_service, provider) → the block that guarantees it.

    Parsed from main.yml so the ARTIFACT can say which declared edges the
    playbook actually backs. Without it all service edges read as one claim
    with one backing, and they are not: `install_woodpecker: true` with
    `install_gitea: false` brings Woodpecker up pointed at nothing, and
    roles/pazny.woodpecker/tasks/post.yml:14 then skips the OAuth wiring in
    silence. A declaration nothing enforces is an aspiration in a fact's
    clothes, and the reader must be able to tell which is which.
    """
    text = (REPO / "main.yml").read_text(encoding="utf-8")
    by_flag = {}
    for svc in (yaml.safe_load(MANIFEST.read_text(encoding="utf-8")).get("services") or []):
        if isinstance(svc, dict) and svc.get("id") and svc.get("install_flag"):
            by_flag.setdefault(svc["install_flag"], svc["id"])
    out: dict[tuple[str, str], str] = {}
    provider = None
    block = ""
    for line in text.splitlines():
        name = re.match(r"^\s{4}- name:\s*(.+?)\s*$", line)
        if name:
            provider, block = None, name.group(1)
            continue
        fact = re.match(r"^\s{8}([a-z_]+):\s*true\s*$", line)
        if fact and fact.group(1) in _AUTO_ENABLE_FACTS:
            provider = _AUTO_ENABLE_FACTS[fact.group(1)]
            continue
        if provider is None:
            continue
        for flag in re.findall(r"\(install_([a-z_0-9]+)\s*\|", line):
            svc = by_flag.get(f"install_{flag}")
            if svc:
                out[(svc, provider)] = f"main.yml: {block}"
    return out


def compile_declared(raw_edges: list, nodes: dict) -> list[dict]:
    enable = auto_enabled_pairs()
    edges = []
    for consumer, dep, src in raw_edges:
        if not isinstance(dep, dict):
            _die(f"{consumer} ({src}): depends_on entry is not a mapping: {dep!r}")
        if True in dep or "on" in dep:
            # YAML 1.1: a bare `on:` key parses as boolean True. The field is
            # `upstream:` for exactly this reason — refuse the trap loudly.
            _die(f"{consumer} ({src}): depends_on uses `on:` — YAML 1.1 parses that "
                 f"key as boolean True; the field is `upstream:`")
        on = dep.get("upstream")
        kind = dep.get("kind")
        if kind == "mutex":
            _die(f"{consumer} ({src}): kind: mutex is refused on depends_on — "
                 f"declare `claims:` on the node; the graph derives the pairs (§2a)")
        if kind not in EDGE_KINDS:
            _die(f"{consumer} ({src}): unknown edge kind {kind!r} (allowed: {EDGE_KINDS})")
        if on not in nodes:
            _die(f"{consumer} ({src}): depends_on names {on!r}, which resolves to no "
                 f"declared node — a graph lying at birth")
        edge = {
            "from": on,
            "to": consumer,
            "kind": kind,
            "measured": _iso(dep.get("measured")),
        }
        if kind in ("data", "trigger"):
            via = str(dep.get("via") or "").strip()
            if kind == "data" and not via:
                _die(f"{consumer} ({src}): data edge from {on} names no artifact (via:) — "
                     f"schedule adjacency with better clothes")
            edge["via"] = via or None
        if kind == "data":
            up = nodes[on]
            if up["kind"] == "pulse":
                edge["expects"] = dep.get("expects", "succeeded")
                if (edge["expects"] == "succeeded" and up.get("findings_exit_codes")
                        and "on_findings" not in dep):
                    _die(f"{consumer} ({src}): upstream {on} declares findings_exit_codes "
                         f"{up['findings_exit_codes']} — the edge must say whether a "
                         f"findings exit satisfies it (on_findings: proceed|block)")
                if "on_findings" in dep:
                    edge["on_findings"] = dep["on_findings"]
            elif "expects" in dep or "on_findings" in dep:
                # `succeeded` is a word about a RUN. A service is not a run: it
                # is up or it is not, and an edge that says "expects: succeeded"
                # of a database has borrowed a vocabulary that cannot be
                # checked against anything.
                _die(f"{consumer} ({src}): edge from {on} carries expects/on_findings, "
                     f"which describe a run outcome — only a pulse upstream has runs")
            if consumer.startswith("service:") and on.startswith("service:"):
                pair = (consumer.split(":", 1)[1], on.split(":", 1)[1])
                block = enable.get(pair)
                reason = str(dep.get("unenforced") or "").strip()
                if block and reason:
                    _die(f"{consumer} ({src}): edge from {on} declares `unenforced:` but "
                         f"{block} DOES enable it — drop the field rather than carry a "
                         f"disclaimer the playbook contradicts")
                if not block and not reason:
                    _die(f"{consumer} ({src}): no `Auto-enable …` block in main.yml turns "
                         f"{on} on for this consumer, so the playbook can bring the "
                         f"consumer up with no provider. Say so in `unenforced:` (one "
                         f"sentence, what happens when it is missing) or add the flag to "
                         f"the block — silence would make this read like the 22 edges the "
                         f"playbook does guarantee")
                edge["enforced_by"] = block
                if reason:
                    edge["unenforced"] = reason
        if kind == "temporal":
            for end in (on, consumer):
                if not nodes[end].get("schedule"):
                    _die(f"{consumer} ({src}): temporal edge from {on} touches {end}, "
                         f"which has no cron schedule — a measured margin between two "
                         f"things only one of which fires is arithmetic on a guess")
            if dep.get("margin_min") is None:
                _die(f"{consumer} ({src}): temporal edge from {on} carries no margin_min — "
                     f"run tools/anatomy-measure-margins.py")
            schedules = dep.get("schedules")
            expect = [nodes[on].get("schedule"), nodes[consumer].get("schedule")]
            if schedules != expect:
                _die(f"{consumer} ({src}): temporal edge schedules {schedules!r} != current "
                     f"cron pair {expect!r} — a schedule changed without re-measuring; "
                     f"run tools/anatomy-measure-margins.py --stamp")
            edge["margin_min"] = dep["margin_min"]
            edge["schedules"] = schedules
            # temporal debt (§1.4 col 4): what the DECLARED budgets permit
            um, dm = _cron_minute(expect[0]), _cron_minute(expect[1])
            if um is not None and dm is not None:
                gap = (dm - um) % 1440
                up = nodes[on]
                declared_margin = gap - (up.get("jitter_min") or 0) \
                    - (up.get("max_runtime_s") or 0) / 60.0
                edge["gap_min"] = gap
                edge["declared_margin_min"] = round(declared_margin, 1)
                edge["can_invert"] = declared_margin <= 0
        edges.append(edge)
    return edges


def compile_writes(raw_writes: list, nodes: dict) -> list[dict]:
    """Actor-declared output edges (job → repo ref / KEAP table).

    Same refusals as depends_on: the target must resolve against the compiled
    node set and `via:` must name the artifact. Direction is writer → reader,
    consistent with every other data edge.
    """
    edges = []
    for actor, w, src in raw_writes:
        if not isinstance(w, dict):
            _die(f"{actor} ({src}): writes entry is not a mapping: {w!r}")
        target = w.get("target")
        if target not in nodes:
            _die(f"{actor} ({src}): writes names {target!r}, which resolves to no "
                 f"declared node — a graph lying at birth")
        via = str(w.get("via") or "").strip()
        if not via:
            _die(f"{actor} ({src}): writes edge to {target} names no artifact (via:)")
        if not w.get("measured"):
            _die(f"{actor} ({src}): writes edge to {target} carries no measured: "
                 f"stamp — nobody verified the code still performs this write")
        edges.append({
            "from": actor,
            "to": target,
            "kind": "data",
            "via": via,
            "measured": _iso(w.get("measured")),
            "declared": "writes",
        })
    return edges


def _load_doctrine_cite():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "doctrine_cite", REPO / "tools" / "doctrine-cite.py")
    mod = importlib.util.module_from_spec(spec)
    # 3.13 dataclasses resolve their module via sys.modules at class creation.
    sys.modules["doctrine_cite"] = mod
    spec.loader.exec_module(mod)
    return mod


def _block_ranges_yaml_list(lines: list[str], list_key: str,
                            item_re: str) -> list[tuple[str, int, int]]:
    """(name, start, end) line ranges for items of one top-level YAML list —
    text-scan on purpose: yaml.safe_load has no line numbers, and these two
    shapes (pulse job entries, judge-sets blocks) are the whole need."""
    out: list[tuple[str, int, int]] = []
    in_region = False
    current: tuple[str, int] | None = None
    pat = re.compile(item_re)
    for i, line in enumerate(lines, 1):
        if re.match(rf"^{list_key}:", line):
            in_region = True
            continue
        if in_region and re.match(r"^[a-zA-Z_-]+:", line):   # next top-level key
            if current:
                out.append((current[0], current[1], i - 1))
                current = None
            in_region = False
        if not in_region:
            continue
        if m := pat.match(line):
            if current:
                out.append((current[0], current[1], i - 1))
            current = (m.group(1), i)
    if current:
        out.append((current[0], current[1], len(lines)))
    # Comments directly ABOVE an item document THAT item — the universal
    # convention in these files ("# --no-ledger --json … (DECISION 2e)" sits
    # above cortex-corpus-diff's key and describes it, and the naive ranges
    # handed that citation to nos-smoke). Walk each start backward over
    # comment/blank lines; the previous item's range shrinks to match.
    adjusted: list[tuple[str, int, int]] = []
    for i, (name, a, b) in enumerate(out):
        start = a
        while start - 2 >= 0 and re.match(r"^\s*(#|$)", lines[start - 2]):
            start -= 1
        if adjusted and start <= adjusted[-1][2]:
            prev = adjusted[-1]
            adjusted[-1] = (prev[0], prev[1], start - 1)
        adjusted.append((name, start, b))
    return adjusted


def derive_doctrine(nodes: dict) -> list[dict]:
    """`governed_by` edges: node → constitution paragraph, from the citations
    the node's OWN manifest block carries — resolved by tools/doctrine-cite.py
    (one resolver; the gate and this graph must never disagree on an address).

    Attribution is PER BLOCK, not per file: judge-sets.yml cites M7 inside
    exactly two judges' comment blocks, and smearing that over all five would
    be the picture-filling this graph refuses. File-header citations
    (attributable only to the whole file) are deliberately NOT edges.

    Weakness sources (weaknesses.py function blocks) are named as not done:
    per-function attribution needs an AST walk this pass does not buy.
    """
    dc = _load_doctrine_cite()
    corpus = dc.build_corpus()

    ranges_by_file: dict[str, list[tuple[str, int, int]]] = {}

    # pulse jobs — the region under `pulse:`, blocks at `- name: <job>`
    for nid, n in list(nodes.items()):
        if n["kind"] != "pulse":
            continue
        src = n["source"]
        if src not in ranges_by_file:
            lines = (REPO / src).read_text(encoding="utf-8").splitlines()
            # `pulse:` may be nested one level (agents yml: top-level too)
            ranges_by_file[src] = [
                (name, a, b) for (name, a, b) in _block_ranges_yaml_list(
                    lines, "pulse", r"^\s{2,6}- name:\s*([A-Za-z0-9_-]+)")]

    # judges + gate sets — blocks at two-space keys under their region
    js_lines = JUDGE_SETS.read_text(encoding="utf-8").splitlines()
    judge_ranges = _block_ranges_yaml_list(js_lines, "judges",
                                           r"^\s{2}([a-z0-9-]+):")
    gs_ranges = _block_ranges_yaml_list(js_lines, "gate_sets",
                                        r"^\s{2}([a-z0-9-]+):")

    def owner_for(src: str, line: int) -> str | None:
        if src == "state/judge-sets.yml":
            for name, a, b in judge_ranges:
                if a <= line <= b and f"judge:{name}" in nodes:
                    return f"judge:{name}"
            for name, a, b in gs_ranges:
                if a <= line <= b and f"gateset:{name}" in nodes:
                    return f"gateset:{name}"
            return None
        for name, a, b in ranges_by_file.get(src, []):
            if a <= line <= b:
                owner = next((k for k in nodes
                              if k.startswith("pulse:") and k.endswith(f":{name}")
                              and nodes[k]["source"] == src), None)
                if owner:
                    return owner
        return None

    sources = {"state/judge-sets.yml"} | set(ranges_by_file)
    pairs: dict[tuple[str, str], dict] = {}
    for src in sorted(sources):
        cites = dc.harvest_file(REPO / src, src, corpus)
        dc.resolve(cites, corpus)
        for c in cites:
            if c.status not in ("resolved", "moved") or c.shape in ("external", "sec"):
                continue
            owner = owner_for(src, c.line)
            if owner is None:
                continue   # file-header/prose citation — not a block's edge
            key = c.key.replace(" ", "-") if c.shape != "constraint" \
                else f"constraint-{c.key}"
            target = f"doctrine:{c.doc}#{key}"
            if target not in nodes:
                nodes[target] = {
                    "kind": "doctrine",
                    "source": c.doc,
                    "section": key,
                    "heading": c.heading or None,
                }
            pk = (owner, target)
            if pk not in pairs:
                pairs[pk] = {
                    "from": owner, "to": target, "kind": "governed_by",
                    "via": f"cited at {src}:{c.line}",
                    "citations": 1,
                    "derived": "doctrine-cite",
                }
            else:
                pairs[pk]["citations"] += 1
    return [pairs[k] for k in sorted(pairs)]


def derive_registry_bindings(nodes: dict) -> list[dict]:
    """authentik:<slug> → service:<id> for every registry row whose slug maps
    onto a manifest service. The 43 uniform tofu→authentik pairs are NOT
    emitted — `managed_by` on each node already states that fact once, and 43
    identical edges would be picture-filling, not wiring."""
    edges = []
    for nid in sorted(nodes):
        n = nodes[nid]
        if n["kind"] == "authentik" and n.get("service"):
            edges.append({
                "from": nid,
                "to": f"service:{n['service']}",
                "kind": "data",
                "via": f"SSO gate (mode={n['mode']}) — provider+application applied "
                       f"by tofu from the registry row",
                "derived": "tofu-authentik-registry",
            })
    return edges


def derive_substrate(nodes: dict) -> list[dict]:
    """Cross-substrate edges whose evidence is role/task code, each emitted
    only while the code that backs it still exists (repair before declare,
    compile-time form)."""
    edges = []
    wp = REPO / "roles" / "pazny.woodpecker" / "templates" / "compose.yml.j2"
    if ("repo:gitea-forge" in nodes and "service:woodpecker" in nodes
            and wp.exists() and "WOODPECKER_GITEA_URL" in wp.read_text(encoding="utf-8")):
        edges.append({
            "from": "repo:gitea-forge",
            "to": "service:woodpecker",
            "kind": "data",
            "via": "CI clone/fetch of pushed branches (WOODPECKER_GITEA_URL, "
                   "roles/pazny.woodpecker/templates/compose.yml.j2:31-34; "
                   "Gitea OAuth2 client auto-created, A16/A19)",
            "derived": "role-config",
        })
    if ("tofu:authentik-state" in nodes and "service:authentik" in nodes
            and (REPO / "tasks" / "tofu-authentik.yml").exists()):
        edges.append({
            "from": "tofu:authentik-state",
            "to": "service:authentik",
            "kind": "data",
            "via": "converge-time `tofu apply` writes providers/applications/outpost "
                   "attachments into the live tenant (tasks/tofu-authentik.yml, "
                   "destroy-guarded, -parallelism=1); read back daily by the "
                   "plan-only drift job",
            "derived": "tofu-apply-path",
        })
    return edges


def derive_face_edges(nodes: dict) -> list[dict]:
    """Face-app edges, each emitted ONLY while the code that performs it is
    still there (repair before declare, compile-time form — the same shape as
    derive_substrate). A comment is not evidence: every edge below names the
    file whose content was read to justify it, and the read happens here.

    WHAT IS A FACT, NOT AN EDGE. Every face app lives in the face, and every
    one of the two that read the graph artifact reads the same vendored copy.
    Uniform relationships are recorded ON the node (`hosted_by`,
    `reads_artifact`) exactly as `managed_by` is for the 43 authentik rows —
    43 identical edges were refused there for being picture-filling, and five
    identical hosting edges would be the same mistake at a smaller scale.

    WHAT IS AN EDGE. Only the relationships that are NOT uniform:
      * a widget is mounted at the desktop root with no user action — a view
        exists only once someone launches it. Different code path, different
        fact.
      * the widget's click-through into the Anatomy view.
      * what the widget actually READS at runtime.
    """
    face_src = FACE_REGISTRY.parents[3]          # …/face/src
    page = face_src / "routes" / "+page.svelte"
    widget = face_src / "lib" / "apps" / "widgets" / "AnatomyWidget.svelte"
    bff_pulse = face_src / "routes" / "bff" / "pulse" / "+server.ts"
    page_txt = page.read_text(encoding="utf-8") if page.exists() else ""
    widget_txt = widget.read_text(encoding="utf-8") if widget.exists() else ""
    bff_txt = bff_pulse.read_text(encoding="utf-8") if bff_pulse.exists() else ""

    # Uniform facts, stated once per node rather than drawn N times.
    for nid, n in nodes.items():
        if n["kind"] != "faceapp":
            continue
        n["hosted_by"] = "service:face"
        if nid == "faceapp:anatomy-widget" and "anatomy-graph.json" in widget_txt:
            n["reads_artifact"] = (
                "src/lib/anatomy/anatomy-graph.json — the byte-identical vendored copy "
                "of state/anatomy-graph.json this generator writes; imported at BUILD "
                "time, so the surface is as fresh as the converge that built it"
            )

    edges: list[dict] = []
    wid = "faceapp:anatomy-widget"
    if wid not in nodes:
        return edges

    if "service:face" in nodes and "<WidgetLayer" in page_txt:
        edges.append({
            "from": "service:face",
            "to": wid,
            "kind": "data",
            "via": "mounted at the desktop root — <WidgetLayer /> in "
                   "src/routes/+page.svelte resolves every form=widget app through "
                   "the registry seam; unlike a view it is on screen with no user "
                   "action, which is what form=widget records",
            "derived": "face-desktop-root",
        })
    if ("faceapp:anatomy" in nodes
            and "requestAnatomy('graph'" in widget_txt
            and "launchNative('anatomy')" in widget_txt):
        edges.append({
            "from": wid,
            "to": "faceapp:anatomy",
            "kind": "trigger",
            "via": "click-through: open() calls requestAnatomy('graph', undefined, id) "
                   "then launchNative('anatomy'), so the Graph view opens with the "
                   "clicked node already selected "
                   "(src/lib/apps/widgets/AnatomyWidget.svelte)",
            "derived": "face-click-through",
        })
    if ("daemon:eu.thisisait.nos.wing" in nodes
            and "loadPulse" in widget_txt and "pulseJobs" in bff_txt):
        edges.append({
            "from": "daemon:eu.thisisait.nos.wing",
            "to": wid,
            "kind": "data",
            "via": "60 s poll of /bff/pulse, a PROJECTION (never a proxy) of Wing's "
                   "pulse_jobs + run summary; joined onto the pulse: nodes on screen "
                   "so a scheduled job's real state colours its dot "
                   "(src/routes/bff/pulse/+server.ts → $lib/server/upstream.pulseJobs)",
            "derived": "face-bff-projection",
        })
    return edges


def derive_structural(nodes: dict) -> list[dict]:
    edges = []
    pulse_daemon = "daemon:eu.thisisait.nos.pulse"
    if pulse_daemon in nodes:
        for nid, n in nodes.items():
            if n["kind"] == "pulse" and not n["paused"]:
                edges.append({
                    "from": pulse_daemon,
                    "to": nid,
                    "kind": "trigger",
                    "via": "list_due_jobs dispatch (files/anatomy/pulse/pulse/daemon.py)",
                    "derived": "daemon-dispatch",
                })
    return edges


def derive_mutex(nodes: dict) -> list[dict]:
    by_resource: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        for c in n.get("claims") or []:
            by_resource.setdefault(c, []).append(nid)
    edges = []
    for resource, members in sorted(by_resource.items()):
        rid = f"resource:{resource}"
        nodes.setdefault(rid, {"kind": "resource", "source": "derived from claims"})
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                edges.append({
                    "from": a, "to": b, "kind": "mutex",
                    "resource": resource, "derived": "claims",
                })
    return edges


def ensure_capability_resources(nodes: dict, edges: list[dict]) -> None:
    for e in edges:
        for end in ("from", "to"):
            nid = e[end]
            if nid.startswith("resource:") and nid not in nodes:
                nodes[nid] = {"kind": "resource", "source": "derived from judge-sets requires"}


# ── cycles ────────────────────────────────────────────────────────────────


def find_cycle(edges: list[dict], kinds: set[str]) -> list[str] | None:
    adj: dict[str, list[str]] = {}
    for e in edges:
        if e["kind"] in kinds:
            adj.setdefault(e["from"], []).append(e["to"])
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}
    stack_path: list[str] = []

    def dfs(u: str) -> list[str] | None:
        colour[u] = GREY
        stack_path.append(u)
        for v in adj.get(u, []):
            if colour.get(v, WHITE) == GREY:
                return stack_path[stack_path.index(v):] + [v]
            if colour.get(v, WHITE) == WHITE:
                got = dfs(v)
                if got:
                    return got
        stack_path.pop()
        colour[u] = BLACK
        return None

    for u in sorted(adj):
        if colour.get(u, WHITE) == WHITE:
            got = dfs(u)
            if got:
                return got
    return None


# ── R2: layer, DERIVED (docs/doctrine/layers.md §3, docs/idea/13-relations.md) ──


#: The one place the layer arithmetic is written down. `graphLayout.ts`
#: `rankNodes` runs the same longest-path walk for the canvas; this is that
#: walk restricted to the service projection and mapped onto §3's four names.
LAYER_BASIS = (
    "longest path over the service projection of the dependency edges: every "
    "service→service data edge, plus the SSO chain service:authentik → "
    "authentik:<slug> → service:<x> collapsed onto its endpoints (an "
    "authentik:<slug> is an object inside Authentik, not an actor). "
    "height = longest path to a leaf; L2 = no dependents, L1 = has dependents "
    "and upstreams, L0 = has dependents and no upstreams."
)


def _service_projection(edges: list[dict]) -> dict[str, set[str]]:
    """provider service → the services that depend on it, SSO chain collapsed."""
    out: dict[str, set[str]] = {}
    hosted: dict[str, str] = {}      # authentik:<slug> → hosting service
    gated: dict[str, set[str]] = {}  # authentik:<slug> → services it gates
    for e in edges:
        if e["kind"] != "data":
            continue
        f, t = e["from"], e["to"]
        if f.startswith("service:") and t.startswith("service:"):
            out.setdefault(f, set()).add(t)
        elif f.startswith("service:") and t.startswith("authentik:"):
            hosted[t] = f
        elif f.startswith("authentik:") and t.startswith("service:"):
            gated.setdefault(f, set()).add(t)
    for provider_node, consumers in gated.items():
        host = hosted.get(provider_node)
        if host:
            out.setdefault(host, set()).update(c for c in consumers if c != host)
    return out


def derive_layers(nodes: dict, edges: list[dict]) -> None:
    """Stamp `layer` on every service node the estate is entitled to place.

    REFUSAL, and it is the point of the whole field. `layer` is longest path
    over the DECLARED edges, so a node nobody surveyed contributes exactly what
    a measured root contributes — nothing — and the arithmetic answers anyway.
    MEASURED with the refusal disabled: `service:traefik` derives **L2
    application**, "a leaf whose failure is felt where it happens", about the
    process that binds 80/443 and is the sole edge proxy on Linux; and
    `service:grafana`, which nobody surveyed either but which mcp_gateway
    depends on, derives **L0 substrate**. Same absence of evidence, opposite
    verdicts, both stated calmly. So a node whose own upstreams were never read
    gets NO layer and a `layer_withheld` reason instead.

    L3 is NOT derivable here and is never emitted: §3 defines it by DELIVERY
    ("small per-tenant apps, manifest-shipped"), which is a different axis
    leaking into this one. The Tier-2 apps have no `service:` node at all.
    """
    down = _service_projection(edges)
    up: dict[str, set[str]] = {}
    for provider, consumers in down.items():
        for c in consumers:
            up.setdefault(c, set()).add(provider)

    height: dict[str, int] = {}
    stack: set[str] = set()

    def walk(nid: str) -> int:
        if nid in height:
            return height[nid]
        if nid in stack:
            return 0
        stack.add(nid)
        h = 0
        for nxt in down.get(nid, ()):
            if nxt in stack:
                continue
            h = max(h, walk(nxt) + 1)
        stack.discard(nid)
        height[nid] = h
        return h

    for nid, n in nodes.items():
        if n.get("kind") == "service":
            walk(nid)

    for nid, n in sorted(nodes.items()):
        if n.get("kind") != "service":
            continue
        survey = n.get("dependency_survey")
        dependents, upstreams = len(down.get(nid, ())), len(up.get(nid, ()))
        if survey != "declared":
            n["layer"] = None
            n["layer_withheld"] = (
                f"dependency_survey={survey} — nobody has read this role's upstreams, "
                f"and a longest path over edges that were never looked for derives L0 "
                f"substrate from an absence of evidence"
            )
            continue
        if height[nid] == 0:
            layer = "L2"
        elif upstreams == 0:
            layer = "L0"
        else:
            layer = "L1"
        n["layer"] = layer
        n["layer_basis"] = {"height": height[nid], "dependents": dependents,
                            "upstreams": upstreams}


# ── build ─────────────────────────────────────────────────────────────────


def build() -> dict:
    nodes: dict[str, dict] = {}
    raw: list = []
    raw_writes: list = []
    harvest_pulse(nodes, raw, raw_writes)
    harvest_judges(nodes, edges := [])
    harvest_weaknesses(nodes)
    harvest_daemons(nodes)
    harvest_services(nodes)
    harvest_service_deps(nodes, raw)   # after services — resolves against them
    harvest_repos_and_tofu(nodes)
    harvest_authentik(nodes)   # after services — slug→service binding needs them
    harvest_tables(nodes)
    harvest_faceapps(nodes)

    declared = compile_declared(raw, nodes)
    writes = compile_writes(raw_writes, nodes)
    bindings = derive_registry_bindings(nodes)
    substrate = derive_substrate(nodes)
    face = derive_face_edges(nodes)
    structural = derive_structural(nodes)
    doctrine = derive_doctrine(nodes)
    mutex = derive_mutex(nodes)
    ensure_capability_resources(nodes, edges)
    # After every node exists (derive_mutex/ensure_capability_resources mint
    # resource nodes): taxonomy anchor + embeddable one-liner, every node.
    annotate_nodes(nodes)
    hosting = derive_authentik_hosting(nodes)
    all_edges = (declared + writes + edges + bindings + substrate + face
                 + structural + doctrine + mutex + hosting)
    derive_layers(nodes, all_edges)

    # Per-kind cycles are a compile error (§2c-2): there is no legitimate
    # same-night cycle in a cron estate.
    for kind in EDGE_KINDS:
        cyc = find_cycle(all_edges, {kind})
        if cyc:
            _die(f"cycle through {kind} edges: {' -> '.join(cyc)}")

    # A union-kind cycle is a real feedback loop crossing a night boundary
    # (e.g. the corpus-diff halt). Flagged for human eyes, never auto-refused.
    warnings = []
    union = find_cycle([e for e in all_edges if e["kind"] != "mutex"], set(EDGE_KINDS))
    if union:
        warnings.append("union-kind cycle (feedback loop, review-not-refuse): "
                        + " -> ".join(union))

    all_edges.sort(key=lambda e: (e["kind"], e["from"], e["to"]))
    counts = {"nodes": len(nodes), "edges": len(all_edges)}
    for k in ("pulse", "judge", "gateset", "weakness", "daemon", "service", "resource",
              "repo", "tofu", "authentik", "table", "doctrine", "faceapp"):
        counts[f"nodes_{k}"] = sum(1 for n in nodes.values() if n["kind"] == k)
    for k in EDGE_KINDS + ("mutex", "governed_by"):
        counts[f"edges_{k}"] = sum(1 for e in all_edges if e["kind"] == k)
    counts["edges_service_dependency"] = sum(
        1 for e in all_edges
        if e["from"].startswith("service:") and e["to"].startswith("service:"))
    # The survey's own shape, countable. `services_not_surveyed` is the honest
    # remainder — nobody has read those roles for upstreams yet, and a zero
    # here would be the only calm reading of this line.
    for state in ("declared", "not-surveyed", "no-manifest"):
        counts[f"services_survey_{state.replace('-', '_')}"] = sum(
            1 for n in nodes.values()
            if n["kind"] == "service" and n.get("dependency_survey") == state)
    counts["edges_service_dependency_unenforced"] = sum(
        1 for e in all_edges if "unenforced" in e)
    # R2. `layer_withheld` is counted beside the three layers precisely so the
    # census cannot be read as a complete inventory: today it is the majority.
    for layer in ("L0", "L1", "L2", "L3"):
        counts[f"services_layer_{layer}"] = sum(
            1 for n in nodes.values()
            if n["kind"] == "service" and n.get("layer") == layer)
    counts["services_layer_withheld"] = sum(
        1 for n in nodes.values()
        if n["kind"] == "service" and n.get("layer") is None)

    return {
        "version": 1,
        "generated_by": "tools/anatomy-graph-gen.py",
        "doctrine": "docs/archive/nos-anatomy-graph.md",
        "layer_basis": LAYER_BASIS,
        "counts": counts,
        "warnings": warnings,
        "nodes": {k: nodes[k] for k in sorted(nodes)},
        "edges": all_edges,
    }


def render(graph: dict) -> str:
    return json.dumps(graph, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="compile state/anatomy-graph.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if the artifact is stale")
    args = ap.parse_args()
    text = render(build())
    if args.check:
        for target in (TARGET, FACE_TARGET):
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != text:
                print(f"anatomy-graph: {target.relative_to(REPO)} STALE — "
                      f"regenerate with tools/anatomy-graph-gen.py", file=sys.stderr)
                return 1
        print(f"anatomy-graph current ({json.loads(text)['counts']['nodes']} nodes, "
              f"{json.loads(text)['counts']['edges']} edges)")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    FACE_TARGET.write_text(text, encoding="utf-8")
    c = json.loads(text)["counts"]
    print(f"wrote {TARGET.relative_to(REPO)} + face vendored copy "
          f"({c['nodes']} nodes, {c['edges']} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
