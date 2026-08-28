"""Anatomy gate — a repaired output is never a clean one (Q9, 2026-08-29).

Three stages, in order: a hardcoded deterministic parser that repairs SHAPE
only, then ONE bounded format-only re-ask, then UNPARSEABLE. This drives the
real `App\\AgentKit\\Outcome\\OutputRepair` — malformed content in, verdict
out — because a gate that asserted the stages exist would pass against a
parser that fixed nothing.

The load-bearing claim is the flag. Silent repair is a success marker written
by the thing that failed: a session whose output had to be rescued must say so,
whether the rescue was mechanical or cost a second model call.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
AUTOLOAD = WING / "vendor" / "autoload.php"

pytestmark = [
    pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH"),
    pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed"),
]

# Real shapes, all seen from models: a fenced block, a prose preamble, a
# trailing comma, a truncation mid-object, and all of it at once.
FIXABLE = {
    "fenced": '```json\n{"result": "satisfied", "feedback": "all criteria met"}\n```',
    "preamble": 'Sure! Here is the grade:\n{"result": "satisfied", "feedback": "all criteria met"}',
    "postamble": '{"result": "satisfied", "feedback": "all criteria met"}\n\nLet me know if you want more detail.',
    "trailing_comma": '{"result": "satisfied", "feedback": "all criteria met",}',
    "truncated": '{"result": "satisfied", "feedback": "all criteria met"',
    "truncated_key": '{"result": "satisfied", "feedback": "all criteria met", "notes":',
    "everything": 'Here you go:\n```json\n{"result": "satisfied", "feedback": "all criteria met",\n```',
}


def _parse(tmp_path: pathlib.Path, raw: str, reask: str | None = None) -> dict:
    """Run OutputRepair::parse for real. `reask` is the stub second answer."""
    probe = tmp_path / "probe.php"
    reask_php = (
        "null"
        if reask is None
        else f"function (string $orig) {{ return {json.dumps(reask)}; }}"
    )
    probe.write_text(
        "<?php\n"
        f"require {str(AUTOLOAD)!r};\n"
        "use App\\AgentKit\\Outcome\\OutputRepair;\n"
        f"$got = OutputRepair::parse({json.dumps(raw)}, {reask_php});\n"
        "echo json_encode($got);\n",
        encoding="utf-8",
    )
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)


def test_clean_json_is_not_reported_as_repaired(tmp_path):
    """The control. If everything counted as repaired the flag would say
    nothing, which is the same as not having it."""
    got = _parse(tmp_path, '{"result": "satisfied", "feedback": "fine"}')
    assert got["status"] == "ok"
    assert got["stage"] == "clean"
    assert got["value"]["result"] == "satisfied"


@pytest.mark.parametrize("name", sorted(FIXABLE))
def test_the_deterministic_parser_repairs_shape_and_says_so(tmp_path, name):
    """No model in this step: the re-ask is null, so anything that parses was
    parsed mechanically. Content survives unchanged — a repair that rewrote the
    feedback would be an edit nobody authorised."""
    got = _parse(tmp_path, FIXABLE[name], reask=None)
    assert got["status"] == "repaired", f"{name} was not repaired: {got}"
    assert got["stage"] == "parser", f"{name} needed a model to fix a shape fault"
    assert got["value"]["result"] == "satisfied"
    assert got["value"]["feedback"] == "all criteria met"


def test_a_brace_inside_a_string_is_not_structure(tmp_path):
    """Balancing that ignores string state turns a truncated string into a
    different string — the repair becoming the defect."""
    got = _parse(tmp_path, '{"result": "failed", "feedback": "rubric says {count} of 3"}')
    assert got["status"] == "ok"
    assert got["value"]["feedback"] == "rubric says {count} of 3"


def test_one_format_only_reask_when_the_parser_cannot(tmp_path):
    """Stage 2: exactly one, and its success is still a repair."""
    got = _parse(
        tmp_path,
        "I could not grade this, sorry.",
        reask='{"result": "needs_revision", "feedback": "no artifact was produced"}',
    )
    assert got["status"] == "repaired"
    assert got["stage"] == "reask"
    assert got["value"]["result"] == "needs_revision"


def test_both_stages_failing_is_unparseable_never_satisfied(tmp_path):
    """Stage 3. The run records UNPARSEABLE — the one outcome that must not be
    reachable is a quiet pass on output nobody could read."""
    got = _parse(tmp_path, "I could not grade this, sorry.", reask="Still no. Sorry!")
    assert got["status"] == "unparseable"
    assert got["value"] is None
    assert got["stage"] == "reask_failed"


def test_no_reask_available_is_unparseable_not_ok(tmp_path):
    """A missing second stage is a missing measurement, not a passing one."""
    got = _parse(tmp_path, "prose, and nothing JSON-shaped anywhere")
    assert got["status"] == "unparseable"
    assert got["stage"] == "no_reask"


def test_the_grader_reports_the_repair_to_its_caller(tmp_path):
    """The wiring, read off the artifact: Grader::grade returns `repaired`, and
    Runner stamps agent_sessions via markOutputRepaired. Without the last hop
    the parser is honest and the session still looks clean."""
    grader = (WING / "app/AgentKit/Outcome/Grader.php").read_text(encoding="utf-8")
    assert "OutputRepair::parse" in grader, "the grader parses model JSON on its own again"
    assert "'repaired' =>" in grader, "grade() no longer tells its caller about a repair"
    runner = (WING / "app/AgentKit/Runner.php").read_text(encoding="utf-8")
    assert "markOutputRepaired" in runner, "nothing writes the flag to the session row"
    repo = (WING / "app/Model/AgentSessionRepository.php").read_text(encoding="utf-8")
    assert "output_repaired" in repo, "the repository cannot write the column"
