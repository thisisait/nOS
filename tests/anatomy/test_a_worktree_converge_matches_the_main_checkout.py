"""A converge from a worktree persists the MAIN checkout's paths, so the two must hold one commit.

MEASURED 2026-10-14 on a client host. The estate was converged from a linked worktree on fresh
upstream/dev, while the main worktree (the contributor's development checkout) sat 354 commits
behind. nos_main_checkout resolves to the main worktree by design (test_persisted_paths_pin_the_
main_checkout.py), so the thalamus role read files/anatomy/agents/iris/agent.yml from the stale
tree and died "File not found" — and had it not died, serve would have run the cell record and the
LLM register of a week-old tree. The only signal was a debug line at minute zero.

THE RULE: when playbook_dir is a worktree, its HEAD and the main checkout's HEAD are the same
commit, or the run refuses up front, names both and the fix. -e allow_worktree_converge=true is
the named way through for a deliberate split.
"""

from __future__ import annotations

import pathlib
import subprocess

import jinja2
import shlex
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PREFLIGHT = REPO / "tasks" / "preflight-checkout-current.yml"


def _tasks() -> list[dict]:
    return yaml.safe_load(PREFLIGHT.read_text())


def _named(needle: str) -> dict:
    return next(t for t in _tasks() if needle in t.get("name", "").lower())


def test_the_heads_are_compared_after_the_main_checkout_is_known_and_refused():
    names = [t.get("name", "").lower() for t in _tasks()]
    at_main = next(i for i, n in enumerate(names) if "set nos_main_checkout" in n)
    at_read = next(i for i, n in enumerate(names) if "compare this tree with the main checkout" in n)
    at_fail = next(i for i, n in enumerate(names) if "refuse: a worktree ahead of or apart from" in n)
    assert at_main < at_read < at_fail
    fail = _tasks()[at_fail]
    assert "ansible.builtin.fail" in fail, "a warning nobody reads is what let this through"
    assert "allow_worktree_converge" in str(fail["when"]) and "allow_worktree_converge=true" in fail["ansible.builtin.fail"]["msg"]
    assert all("always" in t.get("tags", []) for t in (_tasks()[at_read], fail))


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _compare(tmp: pathlib.Path, here: pathlib.Path, main: pathlib.Path) -> str:
    sh = _named("compare this tree with the main checkout")["ansible.builtin.shell"]
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["quote"] = shlex.quote
    return subprocess.run(["/bin/bash", "-c", env.from_string(sh).render(playbook_dir=str(here), nos_main_checkout=str(main))],
                          capture_output=True, text=True).stdout.strip()


def test_the_comparison_reads_real_heads(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "dev")
    _git(main, "-c", "user.email=a@example.test", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "one")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "estate", str(wt))
    assert _compare(tmp_path, wt, main).startswith("SAME"), "one commit in both is no split"
    _git(wt, "-c", "user.email=a@example.test", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "two")
    out = _compare(tmp_path, wt, main)
    assert out.startswith("SPLIT") and _git(wt, "rev-parse", "--short", "HEAD") in out and _git(main, "rev-parse", "--short", "HEAD") in out, out
    assert _compare(tmp_path, main, main).startswith("SAME"), "the main checkout is never split from itself"
