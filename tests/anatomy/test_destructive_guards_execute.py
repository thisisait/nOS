"""G-3 — destructive-token guards EXECUTE-refuse every removal token.

Runs each guard script with each token UNDER A PATH-STUBBED ansible-playbook
(exit 99). Two reasons (gate-audit): (1) a guard MISS must never launch — or,
for upgrade-detached, nohup-DETACH — a live playbook run from pytest (the gate
must not be able to damage what it guards); (2) ansible's own task-failure rc
is ALSO 2 (post-C2 the always-tagged R4 assert fails under --tags core), so a
bare rc==2 assert would be green over a deleted guard. With the stub, a miss
is observed as rc 99; refusal is asserted message-primary (rc 2 AND
"refusing"). For ansible-bridge.sh the only possible property (B4: no
extra-var surface) is tag-based: blocked tags exit 1, and no removal tag is
in ALLOWED_TAGS.
"""
import re, stat as statmod, subprocess, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOKENS = ["blank=true", "destroy_state=true", "remove=data", "remove=deep",
          "remove=all", "flush=true", "flush=deep", "uninstall=true",
          "confirm=true"]
# Documented launcher-reachable workflow tokens that the ANCHORED confirm glob
# must NOT refuse (O1 — substring collateral):
ALLOWED_TOKENS = ["retention_confirm=true", "export_confirm=true",
                  "forget_confirm=true", "restore_auto_confirm=true",
                  "upgrade_confirmed=true"]

def _stub_env(tmp_path):
    stub = tmp_path / "ansible-playbook"
    stub.write_text("#!/bin/sh\nexit 99\n")
    stub.chmod(stub.stat().st_mode | statmod.S_IEXEC)
    return dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")

def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)

def test_nos_stacks_refuses_every_token(tmp_path):
    env = _stub_env(tmp_path)
    for tok in TOKENS:
        r = _run([str(REPO / "tools/nos-stacks.sh"), "core", "-e", tok], env=env)
        assert r.returncode == 2, f"nos-stacks.sh accepted '-e {tok}' (rc={r.returncode})"
        assert "refusing" in r.stderr

def test_nos_stacks_confirm_glob_has_no_collateral(tmp_path):
    env = _stub_env(tmp_path)
    for tok in ALLOWED_TOKENS:
        r = _run([str(REPO / "tools/nos-stacks.sh"), "stacks", "-e", tok], env=env)
        assert r.returncode != 2 and "refusing" not in r.stderr, (
            f"'{tok}' was collaterally refused — the confirm glob lost its anchor (O1)")
        assert r.returncode == 99, f"'{tok}' did not reach the stub (rc={r.returncode})"

def test_upgrade_detached_refuses_every_token(tmp_path):
    env = _stub_env(tmp_path)
    for tok in TOKENS:
        r = _run([str(REPO / "tools/nos-upgrade-detached.sh"), f"gitea -e {tok}", "r1"],
                 env=env)
        assert r.returncode == 2, f"nos-upgrade-detached.sh accepted '{tok}'"
        assert "refusing" in r.stderr, (
            "rc 2 without the refusal message — rc 2 is also this script's "
            "usage/ansible-not-found exit; the message is the guard's signature")

def test_bridge_blocks_removal_tags_executed(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), PLAYBOOK_DIR=str(REPO))
    for tag in ("blank", "reset", "flush", "uninstall"):
        r = _run([str(REPO / "files/openclaw/ansible-bridge.sh"), "run-tag", tag], env=env)
        assert r.returncode == 1, f"bridge ran blocked tag '{tag}'"
        assert "BLOCKED" in r.stdout + r.stderr

def test_bridge_allowlist_never_contains_removal_tags():
    src = (REPO / "files/openclaw/ansible-bridge.sh").read_text()
    allowed = re.search(r'^ALLOWED_TAGS="([^"]*)"', src, re.M).group(1).split(",")
    for tag in ("blank", "reset", "flush", "uninstall"):
        assert tag not in allowed, f"'{tag}' must never be in ALLOWED_TAGS"

def test_doctrine_texts_name_the_ladder():
    assert "remove=data/deep/all" in (REPO / "tools/workflows/v07-overnight-review.mjs").read_text()
    assert "any `remove=` level" in (REPO / "docs/bones-and-wings-refactor.md").read_text()
