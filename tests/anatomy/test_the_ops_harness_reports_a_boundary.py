"""Anatomy gate — the nos-ops harness answers WHERE, and says UNKNOWN honestly.

`tools/nos-ops-harness.py` exists to answer one question: at which model size
does one_shot chain emission stop reproducing hand-written labels. Two ways it
could lie, and this gate runs it against both:

  * report a size as fine when nothing ran there (unarmed backend, dead
    runner, no agent) — absence must render as UNKNOWN, never as a pass;
  * let the model near the score. The oracle is exact label comparison in the
    harness itself, so a runner that emits a confident wrong chain scores 0.

Executed against the emitted JSON artifact, with a fake runner standing in for
a local model — the harness never sees the difference, which is the point.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HARNESS = REPO / "tools" / "nos-ops-harness.py"
FAMILY = REPO / "state" / "ops-task-families" / "invoice-extract"
REGISTRY = REPO / "state" / "llm-backends.yml"

FAKE = """\
import json, os, sys
prompt = next(a[9:] for a in sys.argv if a.startswith("--prompt="))
size = os.environ["NOS_OPS_SIZE_B"]
mode = json.loads(os.environ["FAKE_MODE_BY_SIZE"])[size]
if mode == "dead":
    sys.stderr.write("the model is not running\\n")
    sys.exit(1)
samples = [json.loads(l) for l in open(os.environ["FAKE_SAMPLES"]) if l.strip()]
hit = next(s for s in samples if s["input"] in prompt)
chain = {"exact": hit["expect"], "wrong": {"invoice_no": "0", "total": 0, "currency": "EUR"},
         "invalid": None}[mode]
print(json.dumps({"session_uuid": "fake", "status": "idle", "chain": chain,
                  "stop_reason": "one_shot_valid" if chain else "one_shot_failed",
                  "error": None}))
"""

FIXTURE_REGISTRY = """\
backends:
  anthropic:
    default: true
  ollama-local:
    local: true
    sizes_b:
      1: "qwen2.5:1.5b"
      3: "qwen2.5:3b"
      7: "qwen2.5:7b"
"""


def run_harness(tmp_path, *, registry, armed="", modes=None, agent=None,
                limit=4) -> dict:
    out = tmp_path / "report.json"
    fake = tmp_path / "fake_runner.py"
    fake.write_text(FAKE, encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "NOS_ARMED_BACKENDS": armed,
        "NOS_OPS_HARNESS_CMD": f"{sys.executable} {fake}",
        "FAKE_MODE_BY_SIZE": json.dumps(modes or {}),
        "FAKE_SAMPLES": str(FAMILY / "samples.jsonl"),
    })
    cmd = [sys.executable, str(HARNESS), "--family", str(FAMILY),
           "--registry", str(registry), "--out", str(out), "--limit", str(limit)]
    if agent:
        cmd += ["--agent", agent]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    assert proc.returncode == 0, f"a reader must exit 0:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_task_family_is_hand_labelled_and_big_enough():
    meta = (FAMILY / "family.yml").read_text(encoding="utf-8")
    samples = [json.loads(l) for l in
               (FAMILY / "samples.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(samples) >= 20, f"a boundary read off {len(samples)} samples is noise"
    assert len({s["id"] for s in samples}) == len(samples), "duplicate sample ids"
    for s in samples:
        assert set(s["expect"]) == {"invoice_no", "total", "currency"}, s["id"]
        assert isinstance(s["expect"]["total"], (int, float)), s["id"]
        assert s["expect"]["currency"] in ("EUR", "CZK"), s["id"]
    assert "{input}" in meta, "the prompt template never interpolates the sample"


def test_an_unarmed_backend_is_unknown_not_a_pass(tmp_path):
    reg = tmp_path / "backends.yml"
    reg.write_text(FIXTURE_REGISTRY, encoding="utf-8")
    report = run_harness(tmp_path, registry=reg, armed="", agent="whatever")

    assert report["declared_sizes_b"] == [1.0, 3.0, 7.0]
    for size, row in report["by_model_size_b"].items():
        assert row["status"] == "UNKNOWN", f"size {size} claimed a status nobody measured"
        assert "NOS_ARMED_BACKENDS" in row["reason"]
    assert report["boundary"]["status"] == "UNKNOWN"
    assert report["boundary"]["chain_tier_floor_b"] is None
    assert report["header"]["ops_plane_tool_surface"] == "CLOSED"
    assert "3-7B" in report["header"]["closed_because"]


def test_the_boundary_is_the_smallest_size_that_reproduces_the_labels(tmp_path):
    reg = tmp_path / "backends.yml"
    reg.write_text(FIXTURE_REGISTRY, encoding="utf-8")
    report = run_harness(
        tmp_path, registry=reg, armed="ollama-local", agent="ops-extract",
        modes={"1.0": "invalid", "3.0": "wrong", "7.0": "exact"},
    )
    sizes = report["by_model_size_b"]

    assert sizes["1.0"]["accuracy"] == 0.0 and sizes["1.0"]["invalid_chain"] == 4
    assert sizes["3.0"]["accuracy"] == 0.0 and sizes["3.0"]["wrong_labels"] == 4, (
        "a confident wrong chain scored above zero — the oracle is not exact"
    )
    assert sizes["7.0"]["accuracy"] == 1.0 and sizes["7.0"]["exact"] == 4
    assert report["boundary"] == {
        "threshold": 0.9, "status": "MEASURED", "chain_tier_floor_b": 7.0,
        "unmeasured_sizes_b": [], "note": "smallest size at or above the threshold",
    }
    # The tier has a number now — and the harness still does not open anything.
    assert report["header"]["ops_plane_tool_surface"] == "CLOSED"
    assert "operator's decision" in report["header"]["closed_because"]


def test_a_dead_runner_is_unknown_not_zero_accuracy(tmp_path):
    """A model that never answered has no score. Reporting 0.0 would rank it
    beside a model that answered wrong on every sample — a different fact."""
    reg = tmp_path / "backends.yml"
    reg.write_text(FIXTURE_REGISTRY, encoding="utf-8")
    report = run_harness(
        tmp_path, registry=reg, armed="ollama-local", agent="ops-extract",
        modes={"1.0": "dead", "3.0": "dead", "7.0": "dead"},
    )
    for size, row in report["by_model_size_b"].items():
        assert row["status"] == "UNKNOWN", f"{size} scored a run that never happened"
        assert row["accuracy"] is None and row["runner_errors"] == 4
    assert report["boundary"]["status"] == "UNKNOWN"


def test_the_shipped_registry_reports_what_it_actually_declares(tmp_path):
    """Read against the committed state/llm-backends.yml. No local row is armed
    today, so the honest report is UNKNOWN everywhere — and it stays honest
    when one lands: an unmeasured size may never reach the boundary."""
    report = run_harness(tmp_path, registry=REGISTRY, armed="")
    measured = [s for s, r in report["by_model_size_b"].items() if r.get("status") == "measured"]
    assert measured == [], "a size was scored without --agent and without arming"
    assert report["boundary"]["status"] == "UNKNOWN"
    assert report["header"]["ops_plane_tool_surface"] == "CLOSED"
    if not report["declared_sizes_b"]:
        assert report["boundary"]["note"] == "no local binding is declared at any size"
