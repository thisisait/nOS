"""A plugin with post-start wiring carries an effect probe, or says why it cannot.

A green converge proves tasks ran; the 2026-09-29/30 blank found ~10 dead
wirings behind failed=0. "Post-start wiring" is read from ARTIFACTS, never
from a description, as what the estate executes once the container is up:

  1. `lifecycle.post_compose` actions the loader DISPATCHES (the `if action ==`
     table in files/anatomy/module_utils/load_plugins.py, read from its source
     here) minus `wait_health`, which only waits and changes nothing. An action
     the loader does not know returns `unknown:<action>` and is not wiring —
     qdrant-base's five custom actions are exactly that.
  2. an `authentik:` block with a mode — SSO provider/application/outpost
     objects provisioned by authentik-base's aggregator (blueprint or tofu).
  3. `pulse.jobs` — rows upserted into Wing's catalog by wing/tasks/post.yml.
  4. `gitea_oauth2` — the OAuth2 app created in Gitea (woodpecker-base).
  5. the owning role's tasks/post.yml (`requires.role`): the imperative half
     of the same wiring (admin accounts, OIDC sources, datasources).

Such a plugin must carry `e2e.probes` (>= 1, rendered to a runnable shape by
tools/e2e-plan.py — test_e2e_plan_is_the_manifests pins that) OR an
`e2e_none` reason: >= 40 chars, not TODO-shaped, naming why no outside probe
can observe the wiring. Never both.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files/anatomy/plugins"
LOADER = REPO / "files/anatomy/module_utils/load_plugins.py"
TODO_SHAPED = re.compile(r"\b(todo|tbd|fixme|xxx|placeholder|n/?a|wip|later)\b", re.I)


def dispatched_actions() -> set[str]:
    acts = set(re.findall(r'if action == "([a-z_]+)"', LOADER.read_text(encoding="utf-8")))
    assert "replay_api_calls" in acts and "wait_health" in acts, acts
    return acts - {"wait_health"}


def wiring(doc: dict, acts: set[str]) -> list[str]:
    out = []
    for a in ((doc.get("lifecycle") or {}).get("post_compose") or []):
        keys = set(a) & acts if isinstance(a, dict) else set()
        out += [f"post_compose.{k}" for k in sorted(keys)]
    if (doc.get("authentik") or {}).get("mode"):
        out.append("authentik")
    if ((doc.get("pulse") or {}).get("jobs") if isinstance(doc.get("pulse"), dict) else None):
        out.append("pulse")
    if doc.get("gitea_oauth2"):
        out.append("gitea_oauth2")
    # Only the plugin's OWN role: pulse-base requires pazny.wing, but Wing's
    # post.yml is wing-base's wiring, not pulse-base's.
    role = (doc.get("requires") or {}).get("role")
    own = "pazny." + str(doc.get("name", "")).removesuffix("-base").replace("-", "_")
    if role == own and (REPO / "roles" / role / "tasks/post.yml").is_file():
        out.append(f"roles/{role}/tasks/post.yml")
    return out


def verdict(doc: dict, acts: set[str]) -> str | None:
    """None when the manifest satisfies the gate, else what is wrong."""
    w = wiring(doc, acts)
    probes = (doc.get("e2e") or {}).get("probes") or []
    reason = doc.get("e2e_none")
    if probes and reason:
        return "carries both e2e.probes and e2e_none; pick one"
    if not w:
        return None
    if probes:
        return None
    if not isinstance(reason, str) or len(reason.strip()) < 40:
        return f"post-start wiring {w} with no e2e.probes and no e2e_none reason (>= 40 chars)"
    if TODO_SHAPED.search(reason):
        return f"e2e_none is TODO-shaped: {reason.strip()[:60]!r}"
    return None


MANIFESTS = sorted(PLUGINS.glob("*/plugin.yml"))


@pytest.mark.parametrize("path", MANIFESTS, ids=[p.parent.name for p in MANIFESTS])
def test_post_start_wiring_has_a_probe_or_a_reason(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    assert verdict(doc, dispatched_actions()) is None, f"{path.parent.name}: {verdict(doc, dispatched_actions())}"


def test_the_gate_goes_red_when_a_probe_or_reason_is_removed():
    acts = dispatched_actions()
    gitea = yaml.safe_load((PLUGINS / "gitea-base/plugin.yml").read_text(encoding="utf-8"))
    assert verdict(gitea, acts) is None
    del gitea["e2e"]
    assert "no e2e.probes" in (verdict(gitea, acts) or "")
    gitea["e2e_none"] = "TODO: write a real reason here once somebody has looked at the wiring"
    assert "TODO-shaped" in (verdict(gitea, acts) or "")
    gitea["e2e_none"] = "x" * 39
    assert "no e2e_none reason" in (verdict(gitea, acts) or "")
    # an undispatched action alone is not wiring, but a dispatched one is
    assert wiring({"lifecycle": {"post_compose": [{"bootstrap_collections": "x"}, {"wait_health": "u"}]}}, acts) == []
    assert wiring({"lifecycle": {"post_compose": [{"replay_api_calls": "hooks/post_compose.yml"}]}}, acts) == ["post_compose.replay_api_calls"]


def test_the_wiring_definition_reaches_most_of_the_estate():
    """Sanity: the artifact reading is not vacuous — dozens of plugins qualify."""
    acts = dispatched_actions()
    n = sum(1 for p in MANIFESTS if wiring(yaml.safe_load(p.read_text(encoding="utf-8")) or {}, acts))
    assert n >= 50, n
