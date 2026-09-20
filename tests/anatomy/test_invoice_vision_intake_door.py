"""Praxis vision intake door is honest: Pulse queues, it does not book.

RETRO-RED: a tree without invoice-vision-base, or an intake that called
digest_absorb.absorb / POSTed invoice|posting, or that skipped ensure_table,
fails these greps. A plugin with only intake-sweep (no absorb-approved) fails
the two-job catalog pin. The 400-facet retry lives in digest_absorb.ensure_table
(shared with every absorb caller) — dropping only `view` left
pending-invoice-verify (graph, no view) aborting the sweep as unreadable.

CI-safe: catalog script + source greps. No live KEAP, no VLM, no nos.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/invoice-vision-base/plugin.yml"
INTAKE = REPO / "tools/invoice-vision-intake.py"
VISION = REPO / "tools/digest-import-vision.py"
ABSORB = REPO / "tools/digest_absorb.py"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
BOOK = ("invoice", "posting", "journal-entry")
JOBS = ("intake-sweep", "absorb-approved")


def _catalog() -> list[dict]:
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO)}
    out = subprocess.run(
        ["python3", str(CATALOG)], capture_output=True, text=True, env=env, check=True
    ).stdout
    return json.loads(out)


def _vision_jobs() -> dict[str, dict]:
    hits = [c for c in _catalog() if c.get("source", "").endswith("invoice-vision-base/plugin.yml")]
    assert hits, "invoice-vision Pulse job is missing from the catalog"
    by_name = {h["job"]["name"]: h for h in hits}
    assert set(by_name) == set(JOBS), f"expected {JOBS}, got {sorted(by_name)}"
    return by_name


def _leftover(env: dict) -> list:
    return [v for v in env.values() if isinstance(v, str) and "{{" in v]


def test_pulse_jobs_are_in_the_catalog_with_mapped_tokens():
    jobs = _vision_jobs()
    intake = jobs["intake-sweep"]["job"]
    absorb = jobs["absorb-approved"]["job"]
    assert intake["command"] == str(INTAKE)
    assert absorb["command"] == str(VISION)
    assert "{{" not in intake["command"] and "{{" not in absorb["command"]
    assert "--absorb" in (absorb.get("args") or [])
    assert "invoice-vision-intake" not in absorb["command"]
    assert "invoice-vision-pipeline" not in absorb["command"]
    for job in (intake, absorb):
        env = job.get("env") or {}
        assert env.get("KEAP_AGENT_TOKEN_RW") == "secret:keap_agent_token_rw"
        leftover = _leftover(env)
        assert not leftover, f"unrendered pulse tokens (Wing 400 mid-converge): {leftover}"


def test_plugin_declares_intake_queue_only_and_absorb_books():
    rows = (yaml.safe_load(PLUGIN.read_text()) or {}).get("pulse", {}).get("jobs") or []
    by_name = {j.get("name"): j for j in rows}
    assert set(by_name) == set(JOBS), f"expected {JOBS}, got {sorted(by_name)}"
    intake_targets = [w.get("target") for w in (by_name["intake-sweep"].get("writes") or [])]
    assert intake_targets == ["table:pending-invoice-verify"]
    for banned in BOOK:
        assert f"table:{banned}" not in intake_targets
    absorb_targets = [w.get("target") for w in (by_name["absorb-approved"].get("writes") or [])]
    assert set(absorb_targets) == {f"table:{t}" for t in BOOK}
    via = " ".join(str(w.get("via") or "") for w in (by_name["absorb-approved"].get("writes") or []))
    assert "digest_absorb" in via
    assert "pending-invoice-verify" in via


def test_intake_writes_the_queue_through_digest_absorb_never_books():
    src = INTAKE.read_text()
    # Module docstring names the later absorb door; pin the runnable body.
    body = src.split('if __name__', 1)[0]
    body = body[body.find("def is_held"):]
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert 'TABLE = "pending-invoice-verify"' in src
    assert "digest_absorb.ensure_table(TABLE" in code
    assert "digest_absorb._post_row(TABLE" in code
    assert "digest_absorb.read_rows(TABLE, hdr)" in code
    assert "digest_absorb.absorb(" not in code
    assert "digest-import-vision" not in code
    assert "--absorb" not in code
    for table in BOOK:
        assert f'_post_row("{table}"' not in code
        assert f"_post_row('{table}'" not in code
        assert f'ensure_table("{table}"' not in code


def test_absorb_cli_walks_extracts_not_incoming_and_never_runs_vlm(tmp_path):
    """Pulse passes --absorb with no root; sidecars live in extracts/, not incoming/."""
    spec = importlib.util.spec_from_file_location("digest_import_vision_door", VISION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    extracts = tmp_path / "tenants/t/users/u/inbox/accounting/client/extracts"
    incoming = extracts.parent / "incoming"
    extracts.mkdir(parents=True)
    incoming.mkdir()
    assert mod.discover_extracts(tmp_path) == [extracts]
    src = VISION.read_text()
    body = src.split("def discover_extracts", 1)[1]
    code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
    assert 'nargs="?"' in src or "nargs='?'" in src
    assert "invoice-vision-intake" not in code
    assert "invoice-vision-pipeline" not in code
    assert "invoice-verify" not in code
    assert "emit_audit" not in code


def test_ensure_table_retries_facet_400_without_view_or_graph():
    """A 400 on facets used to abort absorb; graph-only tables need the same drop."""
    fn = ABSORB.read_text().split("def ensure_table", 1)[1].split("\ndef ", 1)[0]
    assert 'e.code == 400' in fn and '"facets"' in fn
    assert 'body.pop("view"' in fn
    assert 'body.pop("graph"' in fn
    assert 'body.get("graph")' in fn  # view-only retry never fired for this table
