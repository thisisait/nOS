"""The Woodpecker agent's identity survives a container recreate.

WHY. A Woodpecker agent registers via the shared WOODPECKER_AGENT_SECRET and
receives a server-issued agent ID, which it persists to
/etc/woodpecker/agent.conf. When that path lives only in the container
filesystem, every `compose up --force-recreate` mints a NEW agent row and
orphans the old one — measured 2026-08-19: FOUR server rows for ONE running
container, i.e. the server scheduled against 16 workflow slots when 4
existed. The row's name defaulted to the container hostname (the Docker ID),
so the roster was illegible on top of being wrong.

Three properties are pinned, and the loss of any one silently regresses:

1. The identity PERSISTS — the agent service bind-mounts a host directory at
   /etc/woodpecker, and the role creates that directory before compose runs
   (a missing bind source becomes a root-owned auto-created dir on some
   backends, or a failed mount).
2. The name is DECLARED — WOODPECKER_HOSTNAME is set from a variable, not
   left to default to the ephemeral Docker ID.
3. The sweep of already-orphaned rows CANNOT eat a live agent — the DELETE
   in post-agents.yml is conditioned on BOTH `last_contact` and `created`
   being stale, is gated on the operator-minted woodpecker_api_token, and an
   unreadable roster is reported as unknown, never treated as empty-and-fine
   (the `0/0 ready` shape, docs/hidden_fees/08).

WHAT THIS GATE CANNOT DO: it cannot prove the running estate's rows are
clean — that is a live act (`tools/rem-status.py` doctrine: ask the estate,
not the repo). It pins the source so the next recreate stops making more.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.woodpecker"
COMPOSE = ROLE / "templates/compose.yml.j2"
MAIN = ROLE / "tasks/main.yml"
POST = ROLE / "tasks/post.yml"
SWEEP = ROLE / "tasks/post-agents.yml"


def _agent_block(text: str) -> str:
    """The woodpecker-agent service block only — the server must not match."""
    m = re.search(r"^  woodpecker-agent:.*", text, re.S | re.M)
    assert m, "woodpecker-agent service block is gone from compose.yml.j2"
    return m.group(0)


def test_the_agent_conf_is_bind_mounted_from_the_data_dir():
    block = _agent_block(COMPOSE.read_text())
    assert re.search(
        r"woodpecker_data_dir\s*\}\}/agent:/etc/woodpecker", block
    ), (
        "the agent no longer persists /etc/woodpecker — every recreate will "
        "mint a new agent row again (4-rows-for-1-container, 2026-08-19)"
    )


def test_the_bind_source_directory_is_created_before_compose():
    text = MAIN.read_text()
    assert "{{ woodpecker_data_dir }}/agent" in text, (
        "tasks/main.yml no longer creates the agent-identity dir; the bind "
        "source must exist before `docker compose up`"
    )


def test_the_agent_name_is_declared_not_the_docker_id():
    block = _agent_block(COMPOSE.read_text())
    assert "WOODPECKER_HOSTNAME" in block, (
        "WOODPECKER_HOSTNAME is gone — the agent row's name falls back to "
        "the ephemeral container hostname (the Docker ID)"
    )
    assert "woodpecker_agent_hostname" in block


def test_the_sweep_exists_and_is_wired_into_post():
    assert SWEEP.is_file(), "tasks/post-agents.yml is gone"
    assert "post-agents.yml" in POST.read_text(), (
        "post.yml no longer includes the orphan-row sweep"
    )


def test_the_sweep_cannot_delete_a_live_or_registering_agent():
    text = SWEEP.read_text()
    delete_task = re.search(
        r"- name:.*Delete agent rows.*?(?=\n- name:|\Z)", text, re.S
    )
    assert delete_task, "the DELETE task is gone from post-agents.yml"
    body = delete_task.group(0)
    assert "method: DELETE" in body
    # BOTH staleness stamps must gate the delete: last_contact protects the
    # live agent, created protects a row registered seconds ago.
    assert re.search(r"item\.last_contact.*<", body), (
        "the DELETE no longer checks last_contact staleness"
    )
    assert re.search(r"item\.created.*<", body), (
        "the DELETE no longer checks created staleness — it can race a "
        "just-registered agent"
    )


def test_the_sweep_is_token_gated_and_absence_is_reported():
    text = SWEEP.read_text()
    assert re.search(r"woodpecker_api_token.*length\s*>\s*0", text), (
        "the sweep block is no longer gated on woodpecker_api_token"
    )
    # A missing token and an unreadable roster must each be SAID, not passed
    # over — "no data" and "no problem" are different readings.
    assert re.search(r"woodpecker_api_token.*length\s*==\s*0", text), (
        "the no-token case is silent — absence must be reported"
    )
    assert re.search(r"status.*!=\s*200", text), (
        "an unreadable agent roster is no longer reported as unknown"
    )
