"""Anatomy gate — the wedge has an operator exit, and gate-add means ADD.

Contract: docs/idea/11-agentic-loop-contract.md §4 ("the block lifts"), §5a,
§6.2 (`nos-loop forget` — operator identity only), DECISION 6.
Subjects: files/anatomy/bone/{looproutes,loopauth,ledger,budget}.py and
files/anatomy/bone/bin/nos-loop.

TWO FINDINGS FROM THE 2026-08-03 ADVERSARIAL REVIEW, both HIGH, both verified:

B2 — a fingerprint could become PERMANENTLY unjudgeable with no way out.
    Indeterminate verdicts spend the ceiling; a crashed judge job leaves a
    proposal with zero verdicts, which `check()` reads as `attempt-pending`
    and refuses forever. `OperatorLedger.forget` existed, was tested at the
    Python layer — and had no route, no CLI and no caller. A lift key that no
    identity can turn is decoration, and the wedge was already LIVE: the
    engine's first real turn produced exactly this state.

B3 — the §5a carve-out could not tell a NEW gate from a REWRITE of one.
    `_gate_add_exempt` looked at the PATH alone, so a `gate-add` proposal could
    modify any existing file under tests/anatomy/ except three basenames —
    including the loop's own gates — and under gate set `fast` no judge in the
    set would ever execute the file it changed. "Adding a gate" and "rewriting
    the gate that failed you" shared one permission.

WHAT THIS FILE PINS
    §B2: POST /api/v1/loop/forget exists, is operator-identity-only (the third
    loopauth identity, BONE_LOOP_OPERATOR_TOKEN → {read, forget}), 404s on a
    fingerprint with nothing to cut, and actually un-wedges: after the forget,
    the SAME bytes re-propose 201 (both the attempt ceiling and the global
    content-fp dedup honour the cut). The CLI is a thin HTTP client per
    DECISION 6 — parsed with ast to prove it imports no engine module.
    §B3: the carve-out is granted to the ARTIFACT, not the declaration: every
    tests/anatomy/ path in a gate-add diff must be a pure ADDITION (old side
    /dev/null in the parsed diff structure). A modify, rename or delete of an
    existing gate is refused whatever the intent claims; an add-only gate-add
    is still accepted and still requires_operator.

RETRO-VERIFIED: this whole file was run against the pre-fix tree first.
Every test below failed there — the forget tests on the route 404 (no such
endpoint), the gate-add tests on `check_paths(...) == []` (the rewrite was
allowed), the CLI test on the missing file.

CI-safe: FastAPI TestClient + tmp sqlite + pure path arithmetic. No live
estate, no subprocess, no network.
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import budget  # noqa: E402
import judges  # noqa: E402
import ledger  # noqa: E402
import looproutes  # noqa: E402

CLI = BONE / "bin" / "nos-loop"

PROPOSE_TOKEN = "p" * 64
JUDGE_TOKEN = "j" * 64
OPERATOR_TOKEN = "o" * 64

#: served via a monkeypatched `ledger.default_weakness_index` so the gate does
#: not depend on what the live weakness reader finds in this checkout today
WEAKNESS_INDEX = {"hidden-fee:08": "sha-08"}

ALLOWED = "roles/pazny.gitea/defaults/main.yml"

#: an existing gate — the file B3's carve-out let a proposer rewrite
EXISTING_GATE = "tests/anatomy/test_loop_ledger.py"
NEW_GATE = "tests/anatomy/test_brand_new_gate.py"

PROPOSAL = dict(
    weakness_id="hidden-fee:08",
    target_paths=[ALLOWED],
    intent_class="config-fix",
    gate_set="repo",
    tree_sha="a" * 40,
    proposer_id="agent:remediator",
)


def modify_diff(path: str, new: str = "b") -> str:
    """A change to a file that already exists — old side is the real path."""
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -1 +1 @@\n-a\n+{new}\n")


def add_diff(path: str) -> str:
    """A pure addition — old side /dev/null, `new file mode` present."""
    return (f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            f"--- /dev/null\n+++ b/{path}\n"
            "@@ -0,0 +1,2 @@\n+def test_new_thing():\n+    assert True\n")


def delete_diff(path: str) -> str:
    return (f"diff --git a/{path} b/{path}\n"
            "deleted file mode 100644\n"
            f"--- a/{path}\n+++ /dev/null\n"
            "@@ -1 +0,0 @@\n-a\n")


def hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """The REAL router on a tmp wing.db, all three identities configured."""
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-forget-test-secret")
    monkeypatch.setenv("BONE_LOOP_PROPOSE_TOKEN", PROPOSE_TOKEN)
    monkeypatch.setenv("BONE_LOOP_JUDGE_TOKEN", JUDGE_TOKEN)
    monkeypatch.setenv("BONE_LOOP_OPERATOR_TOKEN", OPERATOR_TOKEN)
    monkeypatch.setattr(ledger, "default_weakness_index",
                        lambda: dict(WEAKNESS_INDEX))
    app = FastAPI()
    app.include_router(looproutes.router)
    return TestClient(app)


@pytest.fixture(scope="module")
def registry() -> judges.Registry:
    return judges.load_registry(REPO)


@pytest.fixture()
def proposer(tmp_path, monkeypatch):
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-forget-test-secret")
    led = ledger.open_ledger("proposer", weakness_index=dict(WEAKNESS_INDEX))
    yield led
    led.close()


# ══════════════════════════════════════════════════════════════════════════
# B2 — the wedge, and the way out
# ══════════════════════════════════════════════════════════════════════════

def test_a_wedged_fingerprint_has_an_operator_exit(client):
    """The acceptance scenario, end to end over the wire: proposal recorded,
    judge job crashed, zero verdicts → attempt-pending forever — then the
    operator forgets and the loop breathes again.

    Before this bundle the POST answered 404: `OperatorLedger.forget` had no
    route and no caller, so step 5 is exactly where the old tree goes red."""
    # 1. a proposal lands
    r = client.post("/api/v1/loop/proposals",
                    json={**PROPOSAL, "diff_text": modify_diff(ALLOWED)},
                    headers=hdr(PROPOSE_TOKEN))
    assert r.status_code == 201, r.text
    first = r.json()
    fp = first["fingerprint"]

    # 2. its judge job starts and CRASHES: the run row exists, no verdict
    #    ever will. This is the live wedge (turn 1 of 2026-08-03).
    ev = ledger.open_ledger("evaluator")
    try:
        ev.begin_judge_run(gate_set="repo", judge_name="ansible-lint",
                           argv=["ansible-lint"], proposal_uuid=first["uuid"])
        assert ev.sweep_crashed() == 1
    finally:
        ev.close()

    # 3. the fingerprint is wedged: a NEW patch at the same intent (different
    #    bytes, so the content dedup is not what refuses) is attempt-pending
    r = client.post("/api/v1/loop/proposals",
                    json={**PROPOSAL, "diff_text": modify_diff(ALLOWED, new="c")},
                    headers=hdr(PROPOSE_TOKEN))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["reason"] == "attempt-pending"

    # 4. neither loop identity can lift it — constraint A extended: the party
    #    whose ceiling it is may not reset the ceiling
    for tok in (PROPOSE_TOKEN, JUDGE_TOKEN):
        r = client.post("/api/v1/loop/forget", json={"fingerprint": fp},
                        headers=hdr(tok))
        assert r.status_code == 403, (
            f"a non-operator identity reached forget: {r.status_code} {r.text}")

    # 5. the operator can
    r = client.post("/api/v1/loop/forget", json={"fingerprint": fp},
                    headers=hdr(OPERATOR_TOKEN))
    assert r.status_code == 200, (
        f"POST /api/v1/loop/forget answered {r.status_code} — the wedge has no "
        f"exit again: {r.text}")
    assert r.json()["through_proposal_id"] >= 1

    # 6. and the lift is real: the SAME bytes re-propose 201, so the forget
    #    cut both the attempt ceiling AND the global content-fp dedup
    r = client.post("/api/v1/loop/proposals",
                    json={**PROPOSAL, "diff_text": modify_diff(ALLOWED)},
                    headers=hdr(PROPOSE_TOKEN))
    assert r.status_code == 201, r.text


def test_forgetting_a_fingerprint_with_nothing_to_cut_is_404(client):
    """A forget that 'succeeds' over a typo is a success marker written over
    nothing — the estate's recurring shape. Nothing recorded, 404 said.

    The detail must be the LEDGER's refusal, not the framework's "Not Found":
    on the pre-fix tree this request also answered 404 — because the route did
    not exist — and a gate that cannot tell those apart certifies the wedge."""
    r = client.post("/api/v1/loop/forget", json={"fingerprint": "f" * 64},
                    headers=hdr(OPERATOR_TOKEN))
    assert r.status_code == 404, r.text
    assert "nothing to lift" in r.json()["detail"], r.text


def test_the_forget_body_refuses_a_field_it_does_not_know(client):
    """Same discipline as ProposalIn/JudgeIn: a misspelt field is a 422, not a
    different operation performed quietly."""
    r = client.post("/api/v1/loop/forget",
                    json={"fingerprint": "f" * 64, "force": True},
                    headers=hdr(OPERATOR_TOKEN))
    assert r.status_code == 422, r.text


def test_the_operator_identity_cannot_propose_or_judge(client):
    """{read, forget} and nothing else — the third identity does not collapse
    into either of the first two."""
    r = client.post("/api/v1/loop/proposals",
                    json={**PROPOSAL, "diff_text": modify_diff(ALLOWED)},
                    headers=hdr(OPERATOR_TOKEN))
    assert r.status_code == 403
    r = client.post("/api/v1/loop/judge", json={"gate_set": "fast"},
                    headers=hdr(OPERATOR_TOKEN))
    assert r.status_code == 403


def test_the_cli_is_a_thin_http_client_with_a_forget_verb():
    """DECISION 6: HTTP is the only implementation, the CLI a thin client over
    it. Parsed with ast, not grepped — the file's own docstring says all this,
    and a substring check would read the sentence as its own evidence."""
    assert CLI.is_file(), (
        "files/anatomy/bone/bin/nos-loop does not exist — §6.2's operator verb "
        "has no client and the wedge exit is curl-only folklore")
    tree = ast.parse(CLI.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    engine = {"judges", "ledger", "budget", "looproutes", "loopauth",
              "weaknesses", "clients"}
    assert not (imported & engine), (
        f"nos-loop imports the engine ({sorted(imported & engine)}) — that is "
        "the shared library DECISION 6 forbids; three other runtimes cannot "
        "import it and would drift from the fourth")
    assert "urllib" in imported, "nos-loop must speak HTTP (stdlib urllib)"

    strings = {n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert any("/api/v1/loop/forget" in s for s in strings), (
        "nos-loop has no forget verb pointing at the route")


# ══════════════════════════════════════════════════════════════════════════
# B3 — gate-add means ADD
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("gate_set", ["fast", "repo", "full"])
def test_a_gate_add_that_rewrites_an_existing_gate_is_refused(registry, gate_set):
    """The finding verbatim: under `fast` no judge in the set ever executes the
    file the diff changed, so the rewrite would not even be noticed by the
    verdict. Refused on shape, in every set, honestly declared or not."""
    v = budget.check_paths([EXISTING_GATE], intent_class="gate-add",
                           gate_set=gate_set, registry=registry,
                           diff_text=modify_diff(EXISTING_GATE))
    assert v, (f"{gate_set}: a gate-add MODIFIED {EXISTING_GATE} and the budget "
               f"allowed it — rewriting a gate is not adding one")
    assert any(x.reason == "gate-add-rewrites-gate" for x in v), v


def test_a_gate_add_that_deletes_an_existing_gate_is_refused(registry):
    """Deleting the gate that failed you is the cheapest rewrite of all."""
    v = budget.check_paths([EXISTING_GATE], intent_class="gate-add",
                           gate_set="fast", registry=registry,
                           diff_text=delete_diff(EXISTING_GATE))
    assert any(x.reason == "gate-add-rewrites-gate" for x in v), v


def test_a_gate_add_with_no_artifact_gets_no_carve_out(registry):
    """The exemption is granted to the ARTIFACT. With no diff there is no proof
    of addition, so the path falls back to the ordinary deny rules — the same
    fail-closed posture as an unknown gate set."""
    v = budget.check_paths([EXISTING_GATE], intent_class="gate-add",
                           gate_set="repo", registry=registry)
    assert v, "a diff-less gate-add was granted the carve-out on its claim alone"


def test_the_rewrite_refusal_reaches_the_proposer_as_409(proposer):
    """At the enforcement site: 409 budget-violation, naming the §5a rule, and
    no proposal row exists afterwards."""
    with pytest.raises(ledger.ProposalRefused) as exc:
        proposer.record_proposal(
            weakness_id="hidden-fee:08", target_paths=[EXISTING_GATE],
            intent_class="gate-add", gate_set="fast", tree_sha="a" * 40,
            proposer_id="agent:remediator",
            diff_text=modify_diff(EXISTING_GATE))
    assert exc.value.reason == "budget-violation"
    assert exc.value.status == 409
    assert "gate-add-rewrites-gate" in exc.value.detail
    fp = ledger.fingerprint("hidden-fee:08", [EXISTING_GATE], "gate-add", "fast")
    assert proposer.history(fp) == [], "a refused proposal must not exist"


def test_the_control_an_add_only_gate_add_still_lands(proposer):
    """The carve-out still exists — §5a's point is that adding gates is among
    the most valuable things the loop can do — and it is still never
    auto-accepted."""
    v = budget.check_paths([NEW_GATE], intent_class="gate-add", gate_set="repo",
                           diff_text=add_diff(NEW_GATE))
    assert v == [], f"an add-only gate-add was refused: {v}"
    p = proposer.record_proposal(
        weakness_id="hidden-fee:08", target_paths=[NEW_GATE],
        intent_class="gate-add", gate_set="repo", tree_sha="a" * 40,
        proposer_id="agent:remediator", diff_text=add_diff(NEW_GATE))
    assert p["requires_operator"] is True


def test_an_addition_elsewhere_does_not_launder_a_gate_rewrite(registry):
    """One diff, two files: a genuinely new test AND a modification of an
    existing gate. The new file must not extend its addition-ness to the
    sibling — the classification is per file block, from the diff structure."""
    diff = add_diff(NEW_GATE) + modify_diff(EXISTING_GATE)
    v = budget.check_paths([NEW_GATE, EXISTING_GATE], intent_class="gate-add",
                           gate_set="fast", registry=registry, diff_text=diff)
    assert any(x.reason == "gate-add-rewrites-gate"
               and x.path.endswith("test_loop_ledger.py") for x in v), v
    assert not any(x.path.endswith("test_brand_new_gate.py") for x in v), (
        f"the honest half of the diff was refused too: {v}")


def test_a_rename_into_tests_anatomy_is_not_an_addition(registry):
    """`git mv roles/x.yml tests/anatomy/test_x.py` creates the path without
    /dev/null on the old side. Existing content moving in is not a new gate."""
    diff = ("diff --git a/roles/pazny.gitea/defaults/main.yml "
            f"b/{NEW_GATE}\n"
            "similarity index 100%\n"
            "rename from roles/pazny.gitea/defaults/main.yml\n"
            f"rename to {NEW_GATE}\n")
    v = budget.check_paths([NEW_GATE, "roles/pazny.gitea/defaults/main.yml"],
                           intent_class="gate-add", gate_set="repo",
                           registry=registry, diff_text=diff)
    assert any(x.path == NEW_GATE for x in v), (
        f"a rename minted a 'new' gate out of moved content: {v}")
