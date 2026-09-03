"""Anatomy CI gate — an agent's token scopes derive from its manifest.

Ruling 3 executed 2026-09-03 (docs/doctrine/agentkit.md §6.3): the scope was
declared three times and the gates compared two. Now the manifest is the ONE
authority: every mint task whose --name has an agents/<name>/agent.yml must
compute --scopes FROM that file, never restate them. Wired-in measurement:
surveyor's literal said wing.read while its manifest said wing.write — its
report writes were riding the main-token fallback.

Door/operator tokens (no agent.yml) declare literals; that is their authority.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = REPO / "roles" / "pazny.wing" / "tasks" / "post.yml"


def _mints() -> list[tuple[str, str]]:
    src = POST.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in re.finditer(
        r"--name=([a-z0-9-]+)\n(?:(?!--name=).*\n)*?.*--scopes=([^\n]+)", src)]


def test_agent_mints_derive_never_restate():
    agents = {p.parent.name for p in
              (REPO / "files/anatomy/agents").glob("*/agent.yml")}
    offenders = []
    for name, scopes in _mints():
        if name not in agents:
            continue  # door/operator token — the literal IS its declaration
        if "capability_scopes" not in scopes or "agent.yml" not in scopes:
            offenders.append(f"{name}: --scopes={scopes[:50]}")
    assert not offenders, (
        "agent mint(s) restate scopes instead of deriving from the manifest "
        "(a third copy of one fact — the surveyor gap):\n  "
        + "\n  ".join(offenders))


def test_the_derivation_reads_its_own_manifest():
    """A copy-paste of conductor's lookup under surveyor's mint would derive
    the wrong manifest, silently."""
    for name, scopes in _mints():
        if "capability_scopes" in scopes:
            assert f"/agents/{name}/agent.yml" in scopes, (
                f"{name}'s mint derives from a DIFFERENT agent's manifest: "
                f"{scopes[:90]}")


def test_the_population_is_real():
    derived = [n for n, s in _mints() if "capability_scopes" in s]
    assert len(derived) >= 5, (
        f"only {derived} derive — the mint blocks moved or the regex is blind")
