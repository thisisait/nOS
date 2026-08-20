"""P1 gate — SAFE TO NOT RUN: the one the operator depends on right now.

The estate is live, converged, scheme v1, and there is no scheduled blank
(the restore drill it is gated on last FAILED, 2026-08-16). So the P1 code
must be provably a no-op on that estate:

1. With scheme v1, EVERY credential resolves byte-identical to the pre-P1
   value. The assertion is built from the v1 RULE (`{prefix}_pw_{key}`), never
   from a captured snapshot, so it stays true as credentials are added.
2. The illegal transitions are LOUD: v1 state + a requested v2 without a blank
   must fail naming the blank command — never silently re-derive; and a
   missing store on a converged estate must refuse rather than guess "fresh".
3. The wiring holds the shape the guarantee depends on: the derivation runs in
   main.yml BEFORE the earliest consumer, under no_log, and every
   `nos_derived_secrets.<key>` reference in the repo has a registry row (and
   every registry row a reference) — one table, no drift (the Pulse-catalog
   lesson).

Live reading for an operator: `tools/nos-secret.py --status` answers
"v1 (implicit — no marker recorded)" on a pre-P1 converged host.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))

import nos_secret_derive as d  # noqa: E402

REGISTRY = REPO / "files/anatomy/secrets/registry.yml"


# ── 1. Byte-identity under v1, from the rule ─────────────────────────────────
def test_every_v1_value_is_byte_identical_to_the_legacy_concatenation():
    reg = d.load_registry(str(REGISTRY))
    prefix, tester = "op-fixture-prefix", "tester-fixture-prefix"
    v1 = d.build_map("v1", reg, prefix=prefix, tester_prefix=tester)
    assert set(v1) == set(reg)
    for key, value in v1.items():
        base = tester if key == "nos_tester" else prefix
        assert value == f"{base}_pw_{key}", (
            f"scheme v1 broke byte-identity for {key!r} — a converge on the "
            "live estate would change a password a running service holds"
        )


def test_v1_user_leaf_matches_the_historical_bsky_concatenation():
    # The P1b bridge passes v1_suffix="bsky_<username>"; the module must
    # reproduce `<prefix>_pw_bsky_<username>` exactly.
    assert d.v1_leaf("op-fixture-prefix", "bsky_pazny") == "op-fixture-prefix_pw_bsky_pazny"


# ── 1b. Byte-identity THROUGH THE REAL MODULE, not just the pure functions ──
def _run_module(args: dict) -> dict:
    """Execute nos_secret_map the way Ansible does: as a subprocess with
    ANSIBLE_MODULE_ARGS, through the real AnsibleModule including its return
    scrubber. This exists because the first cut declared `prefix` a no_log
    PARAMETER, and AnsibleModule.exit_json() then rewrote every v1 value to
    `********_pw_<key>` — the pure-function tests above stayed green while
    the play would have rotated the whole estate to a public constant
    (adversarial review, reproduced). A gate that stops at the module
    boundary is decoration for a defect that lives ON the boundary."""
    import json
    import subprocess

    payload = json.dumps({"ANSIBLE_MODULE_ARGS": args})
    proc = subprocess.run(
        [sys.executable, str(REPO / "files/anatomy/library/nos_secret_map.py")],
        input=payload, capture_output=True, text=True, timeout=60,
    )
    out = proc.stdout.strip().splitlines()
    assert out, f"module produced no output; stderr: {proc.stderr[:400]}"
    return json.loads(out[-1])


def test_module_boundary_keeps_v1_values_byte_identical(tmp_path):
    result = _run_module({
        "mode": "map",
        "registry_path": str(REGISTRY),
        "store_path": str(tmp_path / "absent.yml"),
        "prefix": "op-fixture-prefix",
        "tester_prefix": "tester-fixture-prefix",
        "scheme": "v1",
        "mint": False,
    })
    assert not result.get("failed"), result.get("msg")
    m = result["map"]
    reg = d.load_registry(str(REGISTRY))
    assert set(m) == set(reg)
    for key, value in m.items():
        base = "tester-fixture-prefix" if key == "nos_tester" else "op-fixture-prefix"
        assert value == f"{base}_pw_{key}", (
            f"{key!r} came back {value!r} through the REAL module boundary — "
            "if it contains asterisks, a no_log parameter's value is being "
            "scrubbed out of the returned map again"
        )


def test_module_boundary_user_leaf_v1_is_byte_identical():
    result = _run_module({
        "mode": "user_leaf",
        "scheme": "v1",
        "prefix": "op-fixture-prefix",
        "username": "alice",
        "service": "bsky",
        "purpose": "password",
        "v1_suffix": "bsky_alice",
    })
    assert not result.get("failed"), result.get("msg")
    assert result["value"] == "op-fixture-prefix_pw_bsky_alice"


def test_resolve_mode_returns_no_secret_material(tmp_path):
    """The resolve task runs WITHOUT no_log so SchemeError guidance stays
    readable — legal only while its result carries nothing secret."""
    store = tmp_path / "secrets.yml"
    store.write_text("nos_secret_scheme: v2\nnos_secret_master: '%s'\n" % ("ab" * 32))
    result = _run_module({
        "mode": "resolve",
        "registry_path": str(REGISTRY),
        "store_path": str(store),
        "stacks_dir": str(tmp_path),
        "requested_scheme": "v2",
        "blanking": False,
    })
    assert not result.get("failed"), result.get("msg")
    assert result.get("scheme") == "v2"
    leaked = {k for k in result if k in ("map", "master")}
    assert not leaked, f"resolve mode returned secret-bearing keys: {leaked}"
    assert ("ab" * 32) not in json_dumps(result)


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj)


# ── 2. The illegal transitions are loud ──────────────────────────────────────
def test_v1_host_with_v2_request_fails_naming_the_blank():
    with pytest.raises(d.SchemeError) as exc:
        d.resolve_scheme(recorded="v1", requested="v2", blanking=False,
                         store_exists=True, estate_converged=True)
    assert "remove=data --confirm" in str(exc.value)
    with pytest.raises(d.SchemeError) as exc2:
        d.resolve_scheme(recorded="", requested="v2", blanking=False,
                         store_exists=True, estate_converged=True)
    assert "remove=data --confirm" in str(exc2.value)


def test_missing_store_on_converged_estate_refuses_rather_than_rederives():
    with pytest.raises(d.SchemeError, match="looks converged"):
        d.resolve_scheme(recorded="", requested="", blanking=False,
                         store_exists=False, estate_converged=True)


def test_only_a_blank_or_a_fresh_host_reaches_v2():
    assert d.resolve_scheme("", "", True, True, True) == ("v2", True)      # blank
    assert d.resolve_scheme("", "", False, False, False) == ("v2", True)   # fresh
    assert d.resolve_scheme("", "", False, True, True) == ("v1", False)    # converged
    assert d.resolve_scheme("v2", "v2", False, True, True) == ("v2", False)  # post-blank


# ── 3. Wiring shape ──────────────────────────────────────────────────────────
def _main() -> str:
    return (REPO / "main.yml").read_text()


def test_derivation_runs_before_the_earliest_consumer_and_under_no_log():
    main = _main()

    def task(name_fragment: str) -> str:
        m = re.search(
            r"- name: \"" + re.escape(name_fragment) + r".*?(?=\n    - name|\n    #|\n# )",
            main, re.S,
        )
        assert m, f"task {name_fragment!r} left main.yml"
        return m.group(0)

    # The RESOLVE task must NOT be censored — its whole reason to exist as a
    # separate call is that SchemeError remediation text stays readable
    # (adversarial-review finding: one no_log task censored the guidance).
    resolve = task("[Secrets] Resolve the secret scheme")
    assert "no_log" not in resolve, (
        "no_log on the resolve task censors the SchemeError guidance; it "
        "returns no secret material (pinned by "
        "test_resolve_mode_returns_no_secret_material) and must stay loud"
    )
    assert "tags: ['always']" in resolve

    # The MAP task and both set_facts ARE censored — their results are the
    # credential set.
    derive_task = task("[Secrets] Derive the credential map (P1)")
    assert "no_log: true" in derive_task, "the derived map would land in logs/telemetry"
    assert "tags: ['always']" in derive_task
    expose = task("[Secrets] Expose the derived map")
    assert "no_log: true" in expose
    reconcile = task("[Secrets] Reconcile store-shadowed derived names")
    assert "no_log: true" in reconcile

    # Before the earliest consumer (tasks/restore.yml reads mariadb_root_password).
    assert main.index("[Secrets] Resolve the secret scheme") < main.index(
        "import_tasks: tasks/restore.yml"
    ), "the derivation moved BELOW restore.yml — a restore run would abort"


def test_scheme_and_master_are_persisted_by_the_store_template():
    tpl = (REPO / "templates/secrets.yml.j2").read_text()
    assert 'nos_secret_scheme: "{{ nos_secret_scheme | default(\'\') }}"' in tpl
    assert 'nos_secret_master: "{{ nos_secret_master | default(\'\') }}"' in tpl


#: Vars-file declarations: name -> map key, parsed from the committed files so
#: the reconcile check below cannot drift from what the estate declares.
_DECL = re.compile(r"^([a-z0-9_]+):\s*\"\{\{ nos_derived_secrets\.([a-z0-9_]+) \}\}\"", re.M)


def test_store_persisted_map_names_are_reconciled_after_derivation():
    """The store-shadow hole, pinned. ~/.nos/secrets.yml persists some
    map-backed names (for Pulse `secret:` refs) and include_vars loads them at
    a precedence that outranks the vars-file declarations — so WITHOUT the
    reconcile set_fact in main.yml, a blank would flip to v2 while those names
    silently kept their stale pre-P1 `_pw_` literals and re-persisted them
    (found by the adversarial review against the live store). Every persisted
    name whose declaration resolves via the map must appear in the reconcile
    task, mapped to the SAME key its declaration uses."""
    decls = {}
    for f in ("default.credentials.yml", "default.config.yml"):
        decls.update({m.group(1): m.group(2) for m in _DECL.finditer((REPO / f).read_text())})

    tpl = (REPO / "templates/secrets.yml.j2").read_text()
    persisted = set(re.findall(r"^([a-z0-9_]+):", tpl, re.M))
    shadowed = {n: k for n, k in decls.items() if n in persisted}
    assert shadowed, "parser broke — no persisted map-backed names found"

    main = (REPO / "main.yml").read_text()
    m = re.search(
        r"- name: \"\[Secrets\] Reconcile store-shadowed derived names.*?no_log: true",
        main, re.S,
    )
    assert m, "the store-shadow reconcile task left main.yml — the blank-path hole is open again"
    task = m.group(0)
    missing, wrong_key = [], []
    for name, key in sorted(shadowed.items()):
        row = re.search(rf"^\s+{name}: \"(.*)\"$", task, re.M)
        if not row:
            missing.append(f"{name} (key {key})")
        elif f"nos_derived_secrets.{key}" not in row.group(1):
            wrong_key.append(f"{name}: expected key {key}")
    assert not missing and not wrong_key, (
        "persisted map-backed names not reconciled after derivation — a blank "
        "would keep their stale store literals:\n  missing: "
        + ", ".join(missing) + "\n  wrong key: " + ", ".join(wrong_key)
    )


# ── 3b. References ↔ registry, both directions ───────────────────────────────
_REF = re.compile(r"nos_derived_secrets\.([a-z0-9_]+)")

#: Where references live. Scanned exhaustively; a reference anywhere else is
#: still collected (rglob over the repo's yml/j2 surface).
def _references() -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in {".yml", ".yaml", ".j2"}:
            continue
        rel = str(path.relative_to(REPO))
        if rel.startswith((".git/", ".ci-venv/", "tests/")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in _REF.finditer(text):
            refs.setdefault(m.group(1), set()).add(rel)
    return refs


def test_every_reference_has_a_registry_row_and_vice_versa():
    reg = set(d.load_registry(str(REGISTRY)))
    refs = _references()
    unknown = {k: sorted(v) for k, v in refs.items() if k not in reg}
    assert not unknown, (
        "references to keys the registry does not derive — those values would "
        f"be undefined at render time: {unknown}"
    )
    orphans = reg - set(refs)
    assert not orphans, (
        "registry rows nothing references — dead derivations drift silently; "
        f"delete the row or wire the consumer: {sorted(orphans)}"
    )
