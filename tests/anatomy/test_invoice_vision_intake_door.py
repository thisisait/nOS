"""Praxis vision intake door is honest: Pulse queues, it does not book.

RETRO-RED: a tree without invoice-vision-base, or an intake that called
digest_absorb.absorb / POSTed invoice|posting, or that skipped ensure_table,
fails these greps. The 400-facet retry lives in digest_absorb.ensure_table
(shared with every absorb caller) — dropping only `view` left
pending-invoice-verify (graph, no view) aborting the sweep as unreadable.

CI-safe: catalog script + source greps. No live KEAP, no VLM, no nos.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "files/anatomy/plugins/invoice-vision-base/plugin.yml"
INTAKE = REPO / "tools/invoice-vision-intake.py"
ABSORB = REPO / "tools/digest_absorb.py"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
BOOK = ("invoice", "posting", "journal-entry")


def _catalog() -> list[dict]:
    env = {**os.environ, "NOS_PLAYBOOK_DIR": str(REPO)}
    out = subprocess.run(
        ["python3", str(CATALOG)], capture_output=True, text=True, env=env, check=True
    ).stdout
    return json.loads(out)


def _vision_job() -> dict:
    hits = [c for c in _catalog() if c.get("source", "").endswith("invoice-vision-base/plugin.yml")]
    assert hits, "invoice-vision Pulse job is missing from the catalog"
    assert len(hits) == 1, f"expected one invoice-vision job, got {len(hits)}"
    return hits[0]


def test_pulse_job_is_in_the_catalog_with_mapped_tokens():
    item = _vision_job()
    job = item["job"]
    assert job["name"] == "intake-sweep"
    assert job["command"] == str(INTAKE)
    assert "{{" not in job["command"]
    env = job.get("env") or {}
    assert env.get("KEAP_AGENT_TOKEN_RW") == "secret:keap_agent_token_rw"
    leftover = [v for v in env.values() if isinstance(v, str) and "{{" in v]
    assert not leftover, f"unrendered pulse tokens (Wing 400 mid-converge): {leftover}"


def test_plugin_declares_queue_write_only():
    jobs = (yaml.safe_load(PLUGIN.read_text()) or {}).get("pulse", {}).get("jobs") or []
    assert jobs, "invoice-vision-base has no pulse.jobs"
    writes = jobs[0].get("writes") or []
    targets = [w.get("target") for w in writes]
    assert targets == ["table:pending-invoice-verify"]
    joined = " ".join(str(w.get("via") or "") for w in writes)
    assert "digest_absorb" in joined
    for banned in BOOK:
        assert f"table:{banned}" not in targets


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


def test_ensure_table_retries_facet_400_without_view_or_graph():
    """A 400 on facets used to abort absorb; graph-only tables need the same drop."""
    fn = ABSORB.read_text().split("def ensure_table", 1)[1].split("\ndef ", 1)[0]
    assert 'e.code == 400' in fn and '"facets"' in fn
    assert 'body.pop("view"' in fn
    assert 'body.pop("graph"' in fn
    assert 'body.get("graph")' in fn  # view-only retry never fired for this table
