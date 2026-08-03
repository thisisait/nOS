"""Anatomy gate — no ratchet input the proposer controls; the diff is persisted.

Contract: docs/idea/11-agentic-loop-contract.md §4 (the ceiling), §5 (budget).
Subjects: files/anatomy/bone/{ledger,budget,looproutes,weaknesses}.py

THE SHAPE UNDER ATTACK: the §4 retry ceiling and the content dedup are the only
things standing between an unattended loop and grinding a non-deterministic
judge until it comes back green — and three of their inputs were the blocked
party's to write (adversarial review, 2026-08-03):

  A2  `diff_text` was Optional end to end. Omit it and the §5 artifact check,
      the size cap and the content-fingerprint dedup all silently skipped,
      while the proposal still 201'd.
  B1  three of the fingerprint's four hash inputs are proposer-chosen, and the
      declaration was never compared against the artifact in the
      declared-but-untouched direction — so PADDING `target_paths` with any
      allowed path minted a fresh fingerprint (fresh ceiling) for a
      byte-identical patch, and the content_fp guard, scoped to priors of the
      SAME fingerprint, could never see the re-offer.
  B4  the unknown-weakness refusal was keyed to files a proposer can edit
      out-of-band: `default_weakness_index()` read docs/hidden_fees/README.md
      (and the per-fee body files, which the review missed) straight off the
      working tree, so one UNCOMMITTED row minted a brand-new weakness_id and
      with it a brand-new ceiling key.

EVERY GATE HERE WAS RUN AGAINST THE PRE-BUNDLE CODE AND WENT RED (the module
was written first, the fixes second; `git stash` replays the measurement).
A gate that would have passed against the broken code certifies the defect.

CI-safe: tmp sqlite + a tmp git repo. No live estate, no network.
"""

from __future__ import annotations

import inspect
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BONE = REPO / "files/anatomy/bone"
if str(BONE) not in sys.path:
    sys.path.insert(0, str(BONE))

import budget  # noqa: E402
import judges  # noqa: E402
import ledger  # noqa: E402

TARGET = "roles/pazny.gitea/defaults/main.yml"
PAD = "roles/pazny.n8n/defaults/main.yml"   # allowed root, never in the diff

TEST_REGISTRY = judges.Registry(
    judges={},
    gate_sets={"fast": judges.GateSetSpec(name="fast", judges=("ansible-lint",))},
)
WEAKNESS_INDEX = {"hidden-fee:08": "sha-08", "REM-137": "sha-137"}


def mkdiff(new: str = "b", path: str = TARGET) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+{new}\n"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "wing.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setenv("WING_DB_PATH", str(path))
    monkeypatch.setenv("WING_EVENTS_HMAC_SECRET", "loop-ratchet-test-secret")
    return path


def _open(role: str, **kw):
    kw.setdefault("registry", TEST_REGISTRY)
    kw.setdefault("weakness_index", WEAKNESS_INDEX)
    return ledger.open_ledger(role, **kw)


def propose(led, **over):
    kw = dict(weakness_id="hidden-fee:08", target_paths=[TARGET],
              intent_class="version-pin-bump", gate_set="fast", tree_sha="a" * 40,
              proposer_id="agent:remediator")
    kw.update(over)
    if "diff_text" not in kw:
        kw["diff_text"] = "".join(mkdiff(path=p) for p in kw["target_paths"])
    return led.record_proposal(**kw)


def raw(db) -> sqlite3.Connection:
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


# ══════════════════════════════════════════════════════════════════════════
# A2 — the artifact is required, at the wire and at the ledger
# ══════════════════════════════════════════════════════════════════════════

def test_the_wire_refuses_a_proposal_without_a_diff():
    """MEASURED pre-bundle: this exact body returned 201 and every artifact
    check silently skipped. A required pydantic field is FastAPI's 422."""
    sys.path.insert(0, str(BONE))
    try:
        import looproutes
    finally:
        sys.path.remove(str(BONE))

    field = looproutes.ProposalIn.model_fields["diff_text"]
    assert field.is_required(), (
        "diff_text is Optional again — a diff-less proposal skips the §5 "
        "artifact check, the size cap and the content-fp dedup, at the "
        "proposer's sole discretion")

    body = dict(weakness_id="hidden-fee:08", target_paths=[TARGET],
                intent_class="version-pin-bump", gate_set="fast",
                tree_sha="a" * 40, proposer_id="agent:remediator")
    with pytest.raises(Exception) as e:
        looproutes.ProposalIn.model_validate(body)
    assert "diff_text" in str(e.value)
    # …and an empty string is not an artifact either.
    with pytest.raises(Exception):
        looproutes.ProposalIn.model_validate({**body, "diff_text": ""})
    looproutes.ProposalIn.model_validate({**body, "diff_text": mkdiff()})  # control


def test_the_ledger_refuses_a_missing_or_blank_diff(db):
    """Defense in depth below the wire: a non-HTTP caller of the ledger gets
    the same refusal, and the signature no longer offers a default to omit."""
    param = inspect.signature(
        ledger.ProposerLedger.record_proposal).parameters["diff_text"]
    assert param.default is inspect.Parameter.empty, (
        "diff_text defaults again — optional at any layer is optional")

    led = _open("proposer")
    try:
        with pytest.raises(ledger.ProposalRefused) as e:
            propose(led, diff_text="   \n")
        assert e.value.reason == "missing-diff"
        assert raw(db).execute(
            "SELECT COUNT(*) FROM loop_proposals").fetchone()[0] == 0
    finally:
        led.close()


# ══════════════════════════════════════════════════════════════════════════
# B1 half 1 — target_paths must equal what the diff touches
# ══════════════════════════════════════════════════════════════════════════

def test_a_declared_path_the_diff_never_touches_is_refused():
    """MEASURED pre-bundle: check_paths flagged diff-paths-not-declared and
    never the reverse, so the declaration could be padded freely — and
    `target_paths` is one of the fingerprint's four hash inputs."""
    v = budget.check_paths([TARGET, PAD], intent_class="version-pin-bump",
                           gate_set="repo", repo_root=REPO,
                           diff_text=mkdiff())
    assert [x.reason for x in v] == ["declared-path-untouched"], v
    assert v[0].path == PAD
    # Control in both directions: the honest declaration is clean…
    assert budget.check_paths([TARGET], intent_class="version-pin-bump",
                              gate_set="repo", repo_root=REPO,
                              diff_text=mkdiff()) == []
    # …and without a diff the rule cannot fire (the LEDGER is what makes a
    # diff mandatory; the pure function stays honest about what it was given).
    assert budget.check_paths([TARGET, PAD], intent_class="version-pin-bump",
                              gate_set="repo", repo_root=REPO) == []


def test_ADVERSARIAL_padding_target_paths_does_not_mint_a_fresh_ceiling(db):
    """The whole B1 shape at the enforcement site: same patch, padded
    declaration → different fingerprint — and pre-bundle, a 201 with a fresh
    attempt ceiling. Now the pad is refused on its shape, before any history
    is consulted, so no row exists and nothing was spent or minted."""
    led = _open("proposer")
    try:
        with pytest.raises(ledger.ProposalRefused) as e:
            propose(led, target_paths=[TARGET, PAD], diff_text=mkdiff())
        assert e.value.reason == "budget-violation"
        assert "declared-path-untouched" in e.value.detail
        assert PAD in e.value.detail
        padded_fp = ledger.fingerprint(
            "hidden-fee:08", [TARGET, PAD], "version-pin-bump", "fast")
        assert led.history(padded_fp) == [], "the pad consumed nothing"
    finally:
        led.close()


# ══════════════════════════════════════════════════════════════════════════
# B1 half 2 — the content dedup is global across fingerprints
# ══════════════════════════════════════════════════════════════════════════

def test_ADVERSARIAL_the_same_patch_under_a_new_fingerprint_is_refused(db):
    """MEASURED pre-bundle: byte-identical normalized diff, re-offered under a
    different intent_class (a fingerprint input the proposer chooses freely),
    was ACCEPTED with a fresh ceiling — the content_fp guard only looked at
    priors of the SAME fingerprint. The same-content question has no
    fingerprint in it; now neither does the guard."""
    led = _open("proposer")
    try:
        propose(led, intent_class="version-pin-bump", diff_text=mkdiff())
        with pytest.raises(ledger.ProposalRefused) as e:
            propose(led, intent_class="wiring-fix", diff_text=mkdiff())
        assert e.value.reason == "content-fp-repeat"
        # Different gate set = different fingerprint too; same refusal.
        with pytest.raises(ledger.ProposalRefused) as e2:
            propose(led, gate_set="fast", weakness_id="REM-137",
                    diff_text=mkdiff())
        assert e2.value.reason == "content-fp-repeat"
        # Control: genuinely different content is not caught by THIS guard.
        # (Same fingerprint → attempt-pending, which is the next rule's job.)
        with pytest.raises(ledger.ProposalRefused) as e3:
            propose(led, diff_text=mkdiff("zzz"))
        assert e3.value.reason == "attempt-pending"
    finally:
        led.close()


def test_an_operator_forget_still_lifts_the_content_block(db):
    """§4 "the block lifts": the escape hatch is the OPERATOR's, and the global
    dedup must honour it — a global guard nobody can lift would turn every
    indeterminate first offer into a permanent scar (the B2 shape)."""
    led = _open("proposer")
    try:
        first = propose(led, diff_text=mkdiff())
        with pytest.raises(ledger.ProposalRefused):
            propose(led, intent_class="wiring-fix", diff_text=mkdiff())

        op = _open("operator")
        try:
            op.forget(first["fingerprint"])
        finally:
            op.close()

        again = propose(led, intent_class="wiring-fix", diff_text=mkdiff())
        assert again["attempt_n"] == 1
    finally:
        led.close()


# ══════════════════════════════════════════════════════════════════════════
# A1's prerequisite — the artifact is PERSISTED, not hashed and discarded
# ══════════════════════════════════════════════════════════════════════════

def test_the_proposal_row_carries_the_diff_and_history_returns_it(db):
    """The review claimed diff_text was "stored and never read"; measured, it
    was never stored at all — `content_fp` is a hash whose preimage was thrown
    away, so nothing downstream (the A1 sandbox fix, §11 replay, an operator
    reading /history) could ever see what was actually proposed."""
    led = _open("proposer")
    try:
        p = propose(led, diff_text=mkdiff("pinned"))
        row = raw(db).execute(
            "SELECT diff_text FROM loop_proposals WHERE uuid = ?",
            (p["uuid"],)).fetchone()
        assert row["diff_text"] == mkdiff("pinned")
        hist = led.history(p["fingerprint"])
        assert hist[0]["diff_text"] == mkdiff("pinned"), (
            "GET /history serves rows through ledger.history; the artifact "
            "must come back with them")
    finally:
        led.close()


# ══════════════════════════════════════════════════════════════════════════
# B4 — a weakness minted by an uncommitted edit cannot key a ceiling
# ══════════════════════════════════════════════════════════════════════════

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=gate", "-c",
         "user.email=gate@test", *args],
        check=True, capture_output=True, text=True)


@pytest.fixture()
def fee_repo(tmp_path, monkeypatch):
    """A tmp repo whose ONLY weakness ledger is a committed hidden-fees index
    with one fee. NOS_LOOP_REPO_ROOT points the whole reader at it;
    NOS_LOOP_STATE_DIR keeps ~/.nos out of the measurement."""
    repo = tmp_path / "estate"
    fees = repo / "docs" / "hidden_fees"
    fees.mkdir(parents=True)
    (fees / "README.md").write_text(
        "# Hidden fees\n\n"
        "| # | The fee | The bill comes due when | Status |\n"
        "|---|---------|-------------------------|--------|\n"
        "| [1](01-first.md) | a committed fee | on converge | open |\n",
        encoding="utf-8")
    (fees / "01-first.md").write_text(
        "# 01\n\n## The fee\n\nA committed body.\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    monkeypatch.setenv("NOS_LOOP_REPO_ROOT", str(repo))
    monkeypatch.setenv("NOS_LOOP_STATE_DIR", str(tmp_path / "state"))
    return repo


def test_ADVERSARIAL_an_uncommitted_fee_row_cannot_mint_a_ceiling_key(db, fee_repo):
    """THE B4 MINT, replayed. MEASURED pre-bundle: appending one row to
    docs/hidden_fees/README.md — no commit, no review, no trace in history —
    put `fee:2` into `default_weakness_index()`, and `fee:2` is a brand-new
    (weakness_id, evidence_sha) ceiling key the proposer just wrote for itself.
    """
    # Control first: committed content IS proposable.
    assert "fee:1" in ledger.default_weakness_index()

    readme = fee_repo / "docs" / "hidden_fees" / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        + "| [2](02-minted.md) | a minted fee | whenever I say | open |\n",
        encoding="utf-8")

    index = ledger.default_weakness_index()
    assert "fee:2" not in index, (
        "an uncommitted edit to the fees index minted a proposable weakness")
    assert "fee:1" not in index, (
        "the index served OTHER rows out of a dirty file — the evidence_sha "
        "of every row in it is derived from uncommitted content")

    # …and the refusal reaches the enforcement site, with the default
    # (production) weakness index, not a test double.
    led = ledger.open_ledger("proposer", registry=TEST_REGISTRY)
    try:
        with pytest.raises(ledger.ProposalRefused) as e:
            propose(led, weakness_id="fee:2")
        assert e.value.reason == "unknown-weakness"
    finally:
        led.close()


def test_an_uncommitted_fee_BODY_file_is_the_same_mint(fee_repo):
    """The review said "reads README.md straight from disk" — subtly
    incomplete: `evidence["the_fee"]` is read from the per-fee body file, so
    editing 02-…md alone (README clean) also moves the evidence_sha lift key.
    The source knows every file it read; the flag must cover both."""
    assert "fee:1" in ledger.default_weakness_index()
    (fee_repo / "docs" / "hidden_fees" / "01-first.md").write_text(
        "# 01\n\n## The fee\n\nA quietly rewritten body.\n", encoding="utf-8")
    assert "fee:1" not in ledger.default_weakness_index()


def test_the_worktree_sources_own_weaknesses_are_never_ceiling_keys(fee_repo):
    """The same shape one source over: `git:untracked`'s evidence IS the
    uncommitted state of the tree — one `touch` changes it, so it can never
    key a §4 ceiling. It is still REPORTED (observing is the reader's job)."""
    import weaknesses

    (fee_repo / "minted.txt").write_text("x", encoding="utf-8")
    reports = {r.name: r for r in weaknesses.collect()}
    git_ws = [w for w in reports["git-worktree"].weaknesses
              if w.weakness_id == "git:untracked"]
    assert git_ws, "the reader stopped reporting untracked files — refit this gate"
    assert all(not w.evidence_committed for w in git_ws)
    assert "git:untracked" not in ledger.default_weakness_index()
