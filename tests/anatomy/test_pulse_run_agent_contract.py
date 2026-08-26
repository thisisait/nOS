"""Anatomy gates for the generic pulse-run-agent.sh runner contract.

Lived in test_remediator_agent.py from A9.3 (2026-05-17) until the 2026-08-26
roster close retired the remediator agent (zero events in the wing.db epoch;
its brief is the loop's `rem` weakness source). The runner these gates pin is
agent-agnostic and very much alive — conductor, surveyor, librarian and
upgrade-architect all run through it — so the gates moved here rather than
dying with the agent that first earned them. The remediator-specific gates
(profile shape, read-only scopes, wrapper) were deleted with their subject;
test_agent_roster_close.py pins the retirement itself.
"""

from __future__ import annotations

import pathlib
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── Generic pulse-run-agent.sh contract ────────────────────────────────


def test_pulse_run_agent_hmac_uses_canonical_json():
    """A9.3-fixup (2026-05-17): bash-built HMAC bodies must be canonical
    JSON (sort_keys + compact). Bone re-canonicalizes the parsed dict
    via Python json.dumps(separators=(',',':'), sort_keys=True) before
    re-computing the expected HMAC, so a printf-built unsorted body
    produces a signature that never matches and Bone 401's silently.
    """
    src = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    # The callers that build agent_run_start/end bodies must use jq, not
    # printf '...' — AND must pass -a. 2026-05-17 taught that an unsorted body
    # never matches; 2026-07-27 taught that an unescaped one does not either:
    # Bone's json.dumps defaults to ensure_ascii=True, so a raw UTF-8 byte signs
    # different bytes than it verifies. Sorting was half the canonical form.
    # Tightened, not relaxed: the old literal is a strict prefix of this one.
    assert "jq -a --sort-keys -nc" in src
    assert "jq --sort-keys -nc" not in src.replace("jq -a --sort-keys -nc", ""), (
        "a builder still canonicalises without -a; see tests/anatomy/"
        "test_hmac_signers_canonical.py for why that is a silent 401"
    )
    # And no printf-based JSON construction for HMAC-signed bodies remains.
    # (Allow printf in the HMAC-signature line itself — that's just
    # ts.body concatenation.)
    json_printf_count = sum(
        1 for line in src.splitlines()
        if 'printf' in line
        and ('agent_run_start' in line or 'agent_run_end' in line)
    )
    assert json_printf_count == 0, (
        "pulse-run-agent.sh still has printf-based agent_run_* JSON bodies; "
        "they're not canonical and 401 against Bone")


def test_pulse_run_agent_awk_uses_last_field():
    """A9.3-fixup (2026-05-17): openssl 3.x emits just <hex>; openssl 1.x
    emits '(stdin)= <hex>'. `awk '{print $2}'` works for 1.x but returns
    empty string on 3.x → SIG header empty → Wing returns 'Missing HMAC
    headers'. `$NF` works for both.
    """
    src = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    # No bare `$2` extraction of openssl output.
    for line in src.splitlines():
        if 'openssl' in line:
            continue  # skip the openssl pipe lines themselves
        if "awk '{print $2}'" in line:
            raise AssertionError(
                f"pulse-run-agent.sh still extracts openssl hash via $2 "
                f"(breaks on openssl 3.x): {line.strip()}"
            )
    # Positive: $NF must appear at least once (one awk per HMAC builder).
    assert "awk '{print $NF}'" in src


# test_approvals_presenter_canonicalizes_payload was deleted with its subject:
# ApprovalsPresenter retired 2026-08-08 (A11 → agents-inbox; the retirement is
# pinned by test_approval_queue_event_backed.py). The property it pinned —
# canonical JSON before HMAC signing — matters only for BONE-verified writes
# (Bone re-canonicalizes the parsed dict before computing the expected HMAC).
# The one surviving in-app signer, AdminPresenter::postAuditEvent, posts to
# Wing's /api/v1/events, whose verifier HMACs the RAW body (EventsPresenter),
# so signing the exact string sent is correct there and needs no canonical
# form. Question answers no longer sign anything: AgentQuestionRepository
# emits the decision event in-process, which is what removed the 401-in-silence
# failure mode this test was guarding the edges of.


# test_approvals_presenter_canonicalizes_payload was deleted with its subject:
# ApprovalsPresenter retired 2026-08-08 (A11 → agents-inbox; the retirement is
# pinned by test_approval_queue_event_backed.py). The property it pinned —
# canonical JSON before HMAC signing — matters only for BONE-verified writes
# (Bone re-canonicalizes the parsed dict before computing the expected HMAC).
# The one surviving in-app signer, AdminPresenter::postAuditEvent, posts to
# Wing's /api/v1/events, whose verifier HMACs the RAW body (EventsPresenter),
# so signing the exact string sent is correct there and needs no canonical
# form. Question answers no longer sign anything: AgentQuestionRepository
# emits the decision event in-process, which is what removed the 401-in-silence
# failure mode this test was guarding the edges of.


def test_pulse_run_agent_reads_nos_agent_env():
    """The runner accepts NOS_AGENT_* env (canonical post-A9.3) and
    falls back to NOS_CONDUCTOR_* for backward compat with existing
    Pulse jobs.
    """
    src = (REPO / "files/anatomy/scripts/pulse-run-agent.sh").read_text()
    assert "NOS_AGENT_NAME" in src
    assert "NOS_AGENT_CLIENT_ID" in src
    assert "NOS_AGENT_CLIENT_SECRET" in src
    assert "NOS_AGENT_PROFILE" in src
    assert "NOS_AGENT_TASK" in src
    # Backward-compat aliases (conductor's existing env still works).
    assert "NOS_CONDUCTOR_CLIENT_ID" in src
    assert "NOS_CONDUCTOR_CLIENT_SECRET" in src
    # AGENT_NAME drives the source/origin tagging. Post-A9.3-fixup the
    # event body is built via jq --sort-keys (canonical JSON for Bone HMAC
    # match), so the source field appears as `source:$src` rather than
    # the earlier printf '%s' shape.
    assert "source:$src" in src
    assert "$AGENT_NAME" in src


def test_pulse_run_agent_bash_lint_clean():
    result = subprocess.run(
        ["bash", "-n", str(REPO / "files/anatomy/scripts/pulse-run-agent.sh")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_conductor_uses_nos_agent_env():
    """Conductor profile must use the canonical NOS_AGENT_* shape."""
    profile = yaml.safe_load(
        (REPO / "files/anatomy/agents/conductor.yml").read_text()
    )
    env = (profile["pulse"]["jobs"][0].get("env") or {})
    assert env.get("NOS_AGENT_NAME") == "conductor"
    assert env.get("NOS_AGENT_CLIENT_ID") == "nos-conductor"
    assert "NOS_AGENT_TASK" in env
    assert "NOS_AGENT_PROFILE" in env



# ── Wing-side pulse job upsert contract ────────────────────────────────


def test_pulse_jobs_upsert_propagates_args_and_paused():
    """A9.4-fixup (2026-05-17): the Ansible POST body to /api/v1/pulse_jobs
    MUST forward both args[] and paused/paused_reason — previously they
    were silently dropped, leaving wing:dispatch-notifications with
    args_json=[] (and `php` execing with no script).
    """
    src = (REPO / "roles/pazny.wing/tasks/post.yml").read_text()
    # Body keys (under the pulse_jobs upsert task).
    assert "args: " in src and "item.job.args" in src
    assert "paused:" in src and "item.job.paused" in src
    assert "paused_reason:" in src and "item.job.paused_reason" in src


def test_pulse_repository_persists_paused_on_first_insert():
    """PulseRepository::upsertJob must honor manifest's paused-by-default
    on first insert but preserve operator manual-pause state on updates
    (re-running playbook shouldn't silently un-pause a job)."""
    src = (REPO / "files/anatomy/wing/app/Model/PulseRepository.php").read_text()
    # First-insert branch writes the field unconditionally.
    assert "array_key_exists('paused', $payload)" in src
    # Update branch only writes when manifest explicitly pauses.
    assert "$payload['paused'] === 1" in src or "(int) $payload['paused'] === 1" in src
