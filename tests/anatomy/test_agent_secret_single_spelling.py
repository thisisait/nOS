"""One spelling for an agent's OAuth client secret, end to end.

MEASURED 2026-08-25, on the live estate: every one of the 11 agent Pulse jobs
carried NOS_AGENT_CLIENT_SECRET spelled TWICE — the manifest re-derived it by
concatenating `{{ global_password_prefix }}_pw_agent_<name>`, while Authentik's
registration read `nos_derived_secrets.agent_<name>` (default.config.yml →
30-agent-clients blueprint). Under secret scheme v1 the two spellings are
byte-identical BY COINCIDENCE (v1 = legacy prefix concatenation), and a
ten-entry whole-literal table in discover-pulse-catalog.py bridged them into
`secret:` references. Three string-matched spellings of one credential:
change the scheme (v2 HKDF is the planned blank), change the prefix, or add
an agent without a table entry, and what Pulse presents is no longer what
Authentik accepts — HTTP 400 invalid_grant, zero agent sessions, and a
liveness-only pre-flight that stays green throughout.

The settled shape (2026-08-25):

    manifest  env NOS_AGENT_CLIENT_SECRET: "secret:agent_<x>_client_secret"
    store     templates/secrets.yml.j2
              agent_<x>_client_secret: "{{ nos_derived_secrets.agent_<x> }}"
    authentik default.config.yml authentik_agent_clients[client_id=nos-<x>]
              client_secret: "{{ nos_derived_secrets.agent_<x> }}"

One `nos_derived_secrets` leaf, two readers. The manifest holds a POINTER
resolved at exec time (pulse/secrets.py) from the same file the converge
renders from the same leaf Authentik registers. No spelling can drift alone.

Everything here parses YAML — the artifact, not the prose (a comment naming
the old concatenation must not satisfy or fail anything).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AGENTS = sorted((REPO / "files/anatomy/agents").glob("*.yml"))
PLUGINS = sorted(REPO.glob("files/anatomy/plugins/*/plugin.yml"))
STORE_TEMPLATE = REPO / "templates/secrets.yml.j2"
CONFIG = REPO / "default.config.yml"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"

DERIVED = "{{ global_password_prefix }}_pw_"


def _pulse_jobs(path: pathlib.Path) -> list[dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ((doc.get("pulse") or {}).get("jobs")) or []


def _agent_credentialed_jobs() -> list[tuple[str, dict]]:
    out = []
    for path in AGENTS:
        for job in _pulse_jobs(path):
            env = job.get("env") or {}
            if "NOS_AGENT_CLIENT_ID" in env or "NOS_AGENT_CLIENT_SECRET" in env:
                out.append((f"{path.name}:{job.get('name')}", env))
    return out


def test_there_are_agent_credentialed_jobs_at_all() -> None:
    """Positive control — an empty sweep would make every gate below vacuous."""
    jobs = _agent_credentialed_jobs()
    # >= 6 since the 2026-08-26 roster close (was >= 9).
    assert len(jobs) >= 6, (
        f"only {len(jobs)} agent-credentialed Pulse jobs found under "
        "files/anatomy/agents/ — the sweep this file gates has gone missing."
    )


def test_the_manifest_references_the_named_secret_never_a_derivation() -> None:
    """The one spelling: `secret:agent_<client-id-sans-nos->_client_secret`."""
    offenders = []
    for job_id, env in _agent_credentialed_jobs():
        cid = env.get("NOS_AGENT_CLIENT_ID", "")
        secret = env.get("NOS_AGENT_CLIENT_SECRET", "")
        assert cid.startswith("nos-"), f"{job_id}: client id {cid!r} off-scheme"
        expected = "secret:agent_" + cid[len("nos-"):].replace("-", "_") + "_client_secret"
        if secret != expected:
            offenders.append(f"{job_id}: {secret!r} (expected {expected!r})")
    assert not offenders, (
        "agent manifest(s) no longer point at the named store entry — a "
        "second spelling of the credential is exactly what authenticated "
        "nothing the day the derivation scheme moved:\n  "
        + "\n  ".join(offenders)
    )


def test_no_pulse_block_re_derives_any_credential_from_the_prefix() -> None:
    """Shape over list: NO pulse-visible string may concatenate the prefix.

    Covers plugins too, and covers agents that do not exist yet — the day a
    new manifest ships a `{{ global_password_prefix }}_pw_…` env value, this
    fails, instead of a table somewhere needing an eleventh entry.
    """
    def walk(value, trail, sink):
        if isinstance(value, str) and DERIVED in value:
            sink.append(trail)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{trail}.{k}", sink)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{trail}[{i}]", sink)

    offenders: list[str] = []
    for path in AGENTS + PLUGINS:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        walk(doc.get("pulse"), str(path.relative_to(REPO)), offenders)
    assert not offenders, (
        "pulse-visible content re-derives a credential by concatenating the "
        "prefix. Point it at a `secret:<name>` the store declares:\n  "
        + "\n  ".join(offenders)
    )


def _store_leaves() -> dict[str, str]:
    """store key -> nos_derived_secrets leaf, from templates/secrets.yml.j2."""
    pat = re.compile(
        r"^(agent_\w+_client_secret):\s*\"\{\{ nos_derived_secrets\.(\w+) \}\}\"",
        re.M,
    )
    return dict(pat.findall(STORE_TEMPLATE.read_text(encoding="utf-8")))


def test_every_referenced_name_is_declared_and_reads_the_derived_map() -> None:
    leaves = _store_leaves()
    for job_id, env in _agent_credentialed_jobs():
        name = env["NOS_AGENT_CLIENT_SECRET"][len("secret:"):]
        assert name in leaves, (
            f"{job_id} references {name!r} but templates/secrets.yml.j2 does "
            "not declare it from nos_derived_secrets — the job refuses at "
            "exec time on a machine that converged this template."
        )


def test_pulse_and_authentik_read_the_same_derived_leaf() -> None:
    """The divergence-proof itself: one leaf, two readers.

    What the store persists (and Pulse resolves) and what Authentik registers
    (authentik_agent_clients → 30-agent-clients blueprint) must be the SAME
    `nos_derived_secrets.<leaf>` — not equal-today strings, the same name.
    """
    leaves = _store_leaves()
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    roster = {
        c.get("client_id"): c.get("client_secret", "")
        for c in config.get("authentik_agent_clients") or []
    }
    assert roster, "authentik_agent_clients is empty/unparseable in default.config.yml"
    for job_id, env in _agent_credentialed_jobs():
        cid = env["NOS_AGENT_CLIENT_ID"]
        store_key = env["NOS_AGENT_CLIENT_SECRET"][len("secret:"):]
        assert cid in roster, (
            f"{job_id}: client_id {cid!r} has no authentik_agent_clients "
            "entry — Pulse would present a credential Authentik never registered."
        )
        m = re.fullmatch(r"\{\{ nos_derived_secrets\.(\w+) \}\}", roster[cid])
        assert m, (
            f"{job_id}: authentik_agent_clients[{cid}].client_secret is "
            f"{roster[cid]!r}, not a nos_derived_secrets leaf — the two sides "
            "no longer share a source."
        )
        assert m.group(1) == leaves[store_key], (
            f"{job_id}: Authentik registers leaf {m.group(1)!r} but the store "
            f"persists {leaves[store_key]!r} under {store_key!r} — the two "
            "spellings have diverged at the source."
        )


def test_the_catalog_refuses_a_manifest_that_still_concatenates(tmp_path) -> None:
    """Run the ARTIFACT against the broken state, not just the fixed one.

    A synthetic playbook tree with one stale manifest (prefix-concatenated
    secret) must make discover-pulse-catalog.py refuse the whole catalog
    (rc 2, empty stdout — no secret written anywhere); the same tree with the
    reference spelling must sail through with the ref untouched.
    """
    agents = tmp_path / "files/anatomy/agents"
    agents.mkdir(parents=True)
    (tmp_path / "files/anatomy/plugins").mkdir(parents=True)
    base_env = {
        **os.environ,
        "NOS_PLAYBOOK_DIR": str(tmp_path),
        "NOS_GLOBAL_PASSWORD_PREFIX": "unit-test-prefix",
    }

    def run() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CATALOG)],
            env=base_env, capture_output=True, text=True, timeout=30,
        )

    # Broken direction first — the stale concatenation.
    (agents / "stale.yml").write_text(
        "pulse:\n  jobs:\n    - name: j\n      env:\n"
        "        NOS_AGENT_CLIENT_ID: nos-stale\n"
        '        NOS_AGENT_CLIENT_SECRET: "{{ global_password_prefix }}_pw_agent_stale"\n'
    )
    broken = run()
    assert broken.returncode == 2, (
        f"the catalog ACCEPTED a prefix-concatenated secret (rc "
        f"{broken.returncode}) — the rendered credential would now sit in "
        f"wing.db in the clear.\nstderr: {broken.stderr}"
    )
    assert "unit-test-prefix" not in broken.stdout + broken.stderr, (
        "the refusal itself printed the rendered credential"
    )

    # Fixed direction — the reference passes through untouched.
    (agents / "stale.yml").write_text(
        "pulse:\n  jobs:\n    - name: j\n      env:\n"
        "        NOS_AGENT_CLIENT_ID: nos-stale\n"
        '        NOS_AGENT_CLIENT_SECRET: "secret:agent_stale_client_secret"\n'
    )
    fixed = run()
    assert fixed.returncode == 0, f"clean tree refused: {fixed.stderr}"
    catalog = json.loads(fixed.stdout)
    assert catalog[0]["job"]["env"]["NOS_AGENT_CLIENT_SECRET"] == (
        "secret:agent_stale_client_secret"
    ), "the catalog rewrote a `secret:` reference it should pass through"
