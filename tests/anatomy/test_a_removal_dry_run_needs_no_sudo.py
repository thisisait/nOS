"""`nos --remove=data` (no --confirm) is a READER: it prints the inventory and
exits 0. Measured 2026-09-28: it died in the `roles:` section on
"sudo: a password is required" (pazny.mac.homebrew's first task is become)
before run-mode.yml ever ran, so nobody without the operator's password —
an agent, a reviewer, a fresh operator on a locked box — could see what a
blank would remove. Parsed, not grepped."""
from pathlib import Path
import yaml

REPO = Path(__file__).resolve().parents[2]
PLAY = yaml.safe_load((REPO / "main.yml").read_text())[0]


def test_the_dry_run_flag_is_derived_before_the_roles():
    facts = [t for t in PLAY["pre_tasks"] if "nos_dry_removal" in (t.get("ansible.builtin.set_fact") or t.get("set_fact") or {})]
    assert facts, "no pre_task derives nos_dry_removal"
    expr = facts[0]["ansible.builtin.set_fact"]["nos_dry_removal"]
    for tok in ("remove", "blank", "confirm", "assume_yes"):
        assert tok in expr, f"the derivation ignores `{tok}`"
    assert "always" in facts[0].get("tags", []), "a --tags run would lose the flag and sudo-die again"


def test_every_host_role_skips_on_a_dry_run():
    bare = [r["role"] for r in PLAY["roles"]
            if not any("nos_dry_removal" in str(w) for w in ([r.get("when")] if isinstance(r.get("when"), str) else r.get("when") or []))]
    assert not bare, f"host roles that would run (and sudo) before a dry run prints its inventory: {bare}"
