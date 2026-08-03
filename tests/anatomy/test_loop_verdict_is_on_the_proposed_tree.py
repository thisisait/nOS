"""Anatomy gate — an attached verdict is on the PROPOSED tree, never on HEAD.

Contract: docs/idea/11-agentic-loop-contract.md §2.5 (one set, one tree), §11
(replay). Subjects: files/anatomy/bone/{judges,ledger,looproutes}.py.

A1, THE HEADLINE FINDING of the 2026-08-03 adversarial review, verified twice:
`looproutes._execute` called `judges.run_gate_set(gate_set)` with no proposal
data; the sandbox ran `git worktree add --detach HEAD`; the stored `diff_text`
was never read again. So every attached verdict — the reward signal of the
entire loop — described unmodified HEAD, and the ceremony made that PERMANENT:
the skills forbid committing, so the documented flow could never judge a change.
The loop judged nothing, and every green it ever sealed was a success marker
written beside the work rather than about it (the estate's recurring shape).

THE FIX THIS PINS: when a judge job is attached to a proposal, the engine
applies the STORED diff inside the sandbox at an ENGINE-chosen base (current
HEAD — never the proposer's declared tree_sha), via `git apply --index` +
`git write-tree`, so the judged tree has a replayable identity recorded on
every run row and on the sealed verdict (`bases` in evidence, `base_sha` in
`replay_record`). A diff that does not apply is INDETERMINATE with the reason
naming it — never a fallback to unpatched HEAD, never a pass. Unattached
baseline runs keep judging HEAD itself.

RETRO-VERIFIED NON-VACUOUS: with the apply step hand-disabled (the old
behaviour — `proposal_diff` accepted and ignored, judges on unpatched HEAD),
`test_THE_DEFINITIVE_GATE_a_breaking_diff_fails_and_names_its_tree` and
`test_the_sealed_verdict_is_on_the_proposed_tree_end_to_end` both go red:
the canary judge sees the clean file and the verdict is PASS on HEAD's own sha.

CI-safe: throwaway git repos under tmp_path, a canary judge that is a real
`python3 -c` subprocess reading the sandbox tree, FastAPI TestClient + tmp
sqlite. No live estate, no network, no daemon.
"""

from __future__ import annotations

import inspect
import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import judges  # noqa: E402
import ledger  # noqa: E402
import looproutes  # noqa: E402

PROPOSE_TOKEN = "p" * 64
JUDGE_TOKEN = "j" * 64

WEAKNESS_INDEX = {"hidden-fee:08": "sha-08"}

CANARY = "roles/canary/main.yml"
CLEAN = "state: clean\n"

#: A REAL judge: a subprocess that reads the tree it is run in. exit 1 when the
#: canary file says BROKEN, exit 0 otherwise — so the verdict can only be FAIL
#: if the judge actually observed base + diff, which is the whole point.
CANARY_SCRIPT = (
    "import sys, pathlib; "
    f"t = pathlib.Path({CANARY!r}).read_text(); "
    "print('checked 1 file'); "
    "sys.exit(1 if 'BROKEN' in t else 0)"
)

REGISTRY = {
    "version": 1,
    "judges": {
        "canary": {
            "argv": ["python3", "-c", CANARY_SCRIPT],
            "adapter": "exit_zero",
            "pass_exit": [0],
            "fail_exit": [1],
            "work_regex": "checked (\\d+)",
            "min_work": 1,
            "oracle_paths": ["tools/canary-oracle"],
        }
    },
    # Named `fast` on purpose: the acceptance scenario is "an attached proposal
    # judged with gate_set=fast", and the registry is per-repo committed data.
    "gate_sets": {"fast": {"judges": ["canary"]}},
}


def _git(repo: Path, *argv: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=gate", "-c", "user.email=gate@test", *argv],
        cwd=str(repo), capture_output=True, text=True, timeout=60, check=False)
    if check:
        assert proc.returncode == 0, f"git {argv}: {proc.stderr}"
    return proc.stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway repo with a committed canary file and a committed registry."""
    repo = tmp_path / "estate"
    (repo / "roles/canary").mkdir(parents=True)
    (repo / "state").mkdir()
    (repo / CANARY).write_text(CLEAN, encoding="utf-8")
    (repo / "state/judge-sets.yml").write_text(
        yaml.safe_dump(REGISTRY), encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "genesis")
    return repo, _git(repo, "rev-parse", "HEAD")


def canary_diff(new: str, old: str = "state: clean") -> str:
    return (f"diff --git a/{CANARY} b/{CANARY}\n"
            f"--- a/{CANARY}\n+++ b/{CANARY}\n"
            f"@@ -1 +1 @@\n-{old}\n+{new}\n")


BREAKING_DIFF = canary_diff("state: BROKEN")
BENIGN_DIFF = canary_diff("state: still clean")
CONFLICTING_DIFF = canary_diff("state: BROKEN", old="state: never-was")


def _always(_r: str) -> bool:
    return True


def _run(repo: Path, diff: str | None, **kw):
    return judges.run_gate_set(
        "fast", registry=judges.load_registry(repo), repo_root=repo,
        probe=_always, proposal_diff=diff, **kw)


# ══════════════════════════════════════════════════════════════════════════
# Engine layer
# ══════════════════════════════════════════════════════════════════════════


def test_THE_DEFINITIVE_GATE_a_breaking_diff_fails_and_names_its_tree(tmp_path):
    """A proposal that breaks a judged invariant must FAIL — which is only
    possible if the judge observed base + diff. Before the fix the judge ran on
    unmodified HEAD, saw the clean canary, and this verdict was PASS."""
    repo, head = make_repo(tmp_path)
    verdict = _run(repo, BREAKING_DIFF)

    assert verdict.result is judges.Result.FAIL, (
        f"verdict is {verdict.result} on a diff that deliberately breaks the "
        f"judged invariant — the judge never saw the proposal: {verdict.reason}")

    run = verdict.runs[0]
    # The judged tree has its own identity, and it is not HEAD's.
    assert run.base_sha == head, "the engine base must be the repo's HEAD"
    assert run.tree_sha and re.fullmatch(r"[0-9a-f]{40}", run.tree_sha)
    assert run.tree_sha != head, (
        "the run records HEAD as the judged tree — the verdict cannot tell a "
        "judged proposal from a baseline")
    assert "base_sha" in run.identity(), "replay identity dropped the base"

    # Replayability, proven against git itself: the recorded tree id is a real
    # object in the shared object db, and ITS canary blob carries the diff.
    listing = _git(repo, "ls-tree", "-r", run.tree_sha)
    blob = next(ln.split()[2] for ln in listing.splitlines()
                if ln.endswith(CANARY))
    assert "BROKEN" in _git(repo, "cat-file", "-p", blob), (
        "the recorded tree id does not contain the proposed change — the "
        "identity is a label, not a measurement")


def test_a_benign_diff_still_passes_so_fail_is_not_hardwired(tmp_path):
    """The counterweight: an attached run is not rigged to refuse. A diff the
    judge accepts is a PASS, on a tree that is still not HEAD."""
    repo, head = make_repo(tmp_path)
    verdict = _run(repo, BENIGN_DIFF)
    assert verdict.result is judges.Result.PASS, verdict.reason
    assert verdict.runs[0].base_sha == head
    assert verdict.runs[0].tree_sha != head


def test_a_conflicting_diff_is_indeterminate_and_no_judge_ever_runs(tmp_path):
    """Apply failure must end the set BEFORE any judge runs: the only tree left
    is the one the proposal is not, and judging it anyway is the A1 defect with
    an extra step."""
    repo, _head = make_repo(tmp_path)
    spawned: list = []

    def spy(argv, cwd, timeout_s):
        spawned.append(argv)
        return judges.Completed(exit_code=0, stdout="checked 1 file\n")

    verdict = _run(repo, CONFLICTING_DIFF, spawn=spy)
    assert verdict.result is judges.Result.INDETERMINATE
    assert verdict.result is not judges.Result.PASS
    assert "diff does not apply at engine base" in verdict.reason, verdict.reason
    assert spawned == [], (
        "a judge ran after the apply failed — that is a fallback to unpatched "
        "HEAD wearing an error message")
    assert all(r.status == "skipped" for r in verdict.runs)


def test_an_attached_run_with_no_stored_diff_never_judges_head(tmp_path):
    """A legacy proposal row with no artifact fails closed: attached means the
    proposal is what gets judged, and with nothing to apply there is nothing to
    judge — HEAD is not a stand-in."""
    repo, _head = make_repo(tmp_path)
    spawned: list = []

    def spy(argv, cwd, timeout_s):
        spawned.append(argv)
        return judges.Completed(exit_code=0, stdout="checked 1 file\n")

    verdict = _run(repo, "", spawn=spy)
    assert verdict.result is judges.Result.INDETERMINATE
    assert "no stored diff" in verdict.reason
    assert spawned == []


def test_an_unattached_baseline_still_judges_head_itself(tmp_path):
    """Baseline behaviour is unchanged: no proposal, no apply — HEAD is judged
    and the run says so, base and tree alike."""
    repo, head = make_repo(tmp_path)
    verdict = _run(repo, None)
    assert verdict.result is judges.Result.PASS, verdict.reason
    assert verdict.runs[0].tree_sha == head
    assert verdict.runs[0].base_sha == head


def test_no_caller_can_choose_the_base_or_the_judged_tree():
    """The base is ENGINE-chosen. There is no parameter for it — on the runner
    or on the wire body — so the proposer's declared tree_sha can never select
    what a verdict is about."""
    params = set(inspect.signature(judges.run_gate_set).parameters)
    forbidden = {"tree_sha", "base_sha", "base", "ref", "commit"}
    assert not (params & forbidden), (
        f"run_gate_set accepts a tree-selecting input: {params & forbidden}")
    assert set(looproutes.JudgeIn.model_fields) == {"gate_set", "proposal_uuid"}, (
        "JudgeIn grew a field — if it selects a diff, a tree or a base, the "
        "judged tree stops being the STORED proposal")


# ══════════════════════════════════════════════════════════════════════════
# Wire layer — the stored diff is what the sealed verdict is about
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def wire(tmp_path, monkeypatch):
    """The REAL router judging a throwaway repo: NOS_LOOP_REPO_ROOT points the
    engine's own root resolver at it, so `_execute` runs the canary registry."""
    repo, head = make_repo(tmp_path)
    db = tmp_path / "wing.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setenv("WING_DB_PATH", str(db))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "proposed-tree-test-secret")
    monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", PROPOSE_TOKEN)
    monkeypatch.setenv("BONE_LOOP_JUDGE_TOKEN", JUDGE_TOKEN)
    monkeypatch.setenv("NOS_LOOP_REPO_ROOT", str(repo))
    monkeypatch.setattr(ledger, "default_weakness_index",
                        lambda: dict(WEAKNESS_INDEX))
    app = FastAPI()
    app.include_router(looproutes.router)
    return {"client": TestClient(app), "repo": repo, "head": head}


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _propose(client, diff: str) -> dict:
    r = client.post("/api/v1/loop/proposals", json={
        "weakness_id": "hidden-fee:08",
        "target_paths": [CANARY],
        "intent_class": "config-fix",
        "gate_set": "fast",
        # Deliberately NOT the repo's HEAD: the engine must ignore it.
        "tree_sha": "a" * 40,
        "proposer_id": "agent:gate",
        "diff_text": diff,
    }, headers=_hdr(PROPOSE_TOKEN))
    assert r.status_code == 201, r.text
    return r.json()


def _judge_to_verdict(client, proposal_uuid: str) -> dict:
    r = client.post("/api/v1/loop/judge",
                    json={"gate_set": "fast", "proposal_uuid": proposal_uuid},
                    headers=_hdr(JUDGE_TOKEN))
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        r = client.get(f"/api/v1/loop/judge/{job}", headers=_hdr(JUDGE_TOKEN))
        body = r.json()
        if body["state"] != "running":
            assert body["state"] == "done", body
            return body["verdict"]
        time.sleep(0.2)
    pytest.fail("judge job never finished — see _JOBS notes in looproutes")


def test_the_sealed_verdict_is_on_the_proposed_tree_end_to_end(wire):
    """The acceptance scenario over the wire: propose a breaking diff, judge it
    with gate_set=fast, and the SEALED verdict is FAIL with a tree identity
    that is neither HEAD nor the proposer's declared tree_sha. On the pre-fix
    tree this verdict is 'pass' and its tree_sha IS HEAD."""
    proposal = _propose(wire["client"], BREAKING_DIFF)
    verdict = _judge_to_verdict(wire["client"], proposal["uuid"])

    assert verdict["result"] == "fail", (
        f"sealed {verdict['result']!r} for a proposal that breaks the judged "
        f"invariant — the loop is still judging HEAD: {verdict['evidence']}")
    assert verdict["tree_sha"] != wire["head"]
    assert verdict["tree_sha"] != "a" * 40, (
        "the verdict adopted the PROPOSER'S declared tree_sha — the base must "
        "be engine-chosen")

    evidence = json.loads(verdict["evidence"])
    assert evidence["bases"] == [wire["head"]], (
        f"evidence must record the engine base: {evidence.get('bases')}")

    # §11 — replay_record returns both halves of the judged tree's lineage.
    led = ledger.open_ledger("reader")
    try:
        replay = led.replay_record(verdict["uuid"])
    finally:
        led.close()
    assert replay["base_sha"] == wire["head"]
    assert replay["tree_sha"] == verdict["tree_sha"]
    assert replay["runs"][0]["base_sha"] == wire["head"]
    assert replay["runs"][0]["tree_sha"] == verdict["tree_sha"]


def test_a_diff_outrun_by_head_is_sealed_indeterminate_not_judged_as_head(wire):
    """The proposal was written against yesterday's tree and HEAD moved: the
    stored diff no longer applies. The sealed answer is INDETERMINATE with the
    apply failure named — the proposal is not wedged (it HAS a verdict), and
    HEAD was not quietly judged in its place."""
    proposal = _propose(wire["client"], BREAKING_DIFF)

    # HEAD moves out from under the stored diff.
    (wire["repo"] / CANARY).write_text("state: moved-on\n", encoding="utf-8")
    _git(wire["repo"], "add", "-A")
    _git(wire["repo"], "commit", "-q", "-m", "estate moved")

    verdict = _judge_to_verdict(wire["client"], proposal["uuid"])
    assert verdict["result"] == "indeterminate", verdict
    evidence = json.loads(verdict["evidence"])
    assert "diff does not apply at engine base" in evidence["reason"], evidence
