"""In agent-forge mode (gitea_agent_forge=true) Gitea is a WRITABLE repo, not a
pull-mirror, so `mirror-sync` 400s on it — the real GitHub→Gitea sync is a
fast-forward push (tools/sync-trunk-to-gitea.sh). This pins the wiring that
(a) stops nos-push's misleading unconditional 400, and (b) keeps the loop's
Gitea base from silently lagging origin — the cause of the REM-250 stall.
"""
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_nos_push_runs_trunk_sync_in_agent_forge_mode():
    src = (REPO / "tools" / "nos-push").read_text(encoding="utf-8")
    assert "gitea_agent_forge" in src, "nos-push must branch on agent-forge mode"
    assert "sync-trunk-to-gitea.sh" in src, "agent-forge push must run the trunk sync"
    # The mirror-sync API CALL (the curl, not a comment) must be GATED behind
    # the agent-forge check — never the unconditional default that 400s on a
    # writable forge every push. Anchor on the request line, which lives only in
    # the else branch now.
    call = re.search(r'-X POST -H "Authorization: token', src)
    assert call, "the mirror-sync POST is gone entirely — expected it in the else branch"
    assert src.index("gitea_agent_forge") < call.start(), \
        "the mirror-sync POST must sit after the agent-forge test, in the else branch"


def test_sync_trunk_is_a_clean_noop_off_agent_forge():
    src = (REPO / "tools" / "sync-trunk-to-gitea.sh").read_text(encoding="utf-8")
    assert "gitea_agent_forge" in src and re.search(r"no-?op", src, re.I), \
        "sync-trunk must guard on agent-forge and no-op (not fail) in pull-mirror mode"


import pytest


@pytest.mark.parametrize("forge", ["gitea", "gitlab"])
def test_trunk_sync_pulse_job_is_declared(forge):
    # SUBSTITUTABILITY (forge-topology doctrine): both forges carry the SAME
    # trunk-sync backbone, so present-or-absent either changes nothing.
    doc = yaml.safe_load((REPO / f"files/anatomy/plugins/{forge}-base/plugin.yml").read_text(encoding="utf-8"))
    jobs = (doc.get("pulse") or {}).get("jobs") or []
    match = [j for j in jobs
             if j.get("name") == "trunk-sync" and f"sync-trunk-to-{forge}.sh" in str(j.get("command", ""))]
    assert match, f"{forge}-base must schedule the trunk-sync backbone job"
    # forge-ahead (exit 1) is a promote signal, not a failure — declared so the
    # nightly reader does not paint a legitimate un-promoted merge red.
    assert 1 in (match[0].get("findings_exit_codes") or []), \
        f"exit 1 ({forge} trunk ahead) must be a finding, not a job failure"


def test_nos_push_syncs_gitlab_forge_symmetrically():
    src = (REPO / "tools" / "nos-push").read_text(encoding="utf-8")
    assert "gitlab_agent_forge" in src and "sync-trunk-to-gitlab.sh" in src, \
        "nos-push must sync GitLab too when it is the agent forge (substitutability)"


def test_sync_trunk_gitlab_is_a_clean_noop_off_agent_forge():
    src = (REPO / "tools" / "sync-trunk-to-gitlab.sh").read_text(encoding="utf-8")
    assert "gitlab_agent_forge" in src and re.search(r"no-?op", src, re.I), \
        "sync-trunk-to-gitlab must guard on agent-forge and no-op (not fail) otherwise"
