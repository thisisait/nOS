"""A service plugin with lifecycle hooks says which stack it belongs to.

`load_plugins._plugin_stack` resolves a plugin's stack from
`compose_extension.target_stack`, then `observability.loki.labels.stack`. And
`run_hook` filters with:

    if pstack is not None and pstack not in stack_filter: skip

Read that carefully: a plugin whose stack resolves to **None is never skipped**.
Its hooks run on every stack-scoped pass, doing work for a service that pass is
not bringing up.

MEASURED 2026-08-31: 77 plugins, 22 with no resolvable stack, 11 of those
carrying lifecycle hooks. Eight were composition plugins — `alloy-*`,
`grafana-*` — which are cross-cutting on purpose: they provision datasources
and scrape configs that belong to no single stack, and running on every pass is
what they are for. Three were SERVICE plugins with a definite home:

    jellyfin-base     -> iiab   (state/manifest.yml)
    metabase-base     -> data   (state/manifest.yml)
    spacetimedb-base  -> infra  (no manifest row; the role renders its override
                                 into {{ stacks_dir }}/infra/overrides/)

None of that was new information — every stack was already recorded somewhere
the loader does not read. That is the wiring shape this estate keeps paying
for, and it is the same one as the Traefik auth-mode fall-through fixed the
same day: the answer exists, in a file the consumer never opens.

WHY THIS GATE SPLITS BY KIND rather than demanding a stack from everyone. A
composition plugin genuinely has no stack, and forcing it to invent one would
put a false fact in a manifest to satisfy a test — worse than the gap. The
distinction is the same one `tools/plugin-wiring-report.py` already draws.

Retro-verified 2026-08-31 by removing the three observability blocks.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = REPO / "files/anatomy/plugins"


def _manifest(path: pathlib.Path) -> dict:
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", path.read_text(encoding="utf-8"))
    try:
        return yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}


def _stack(m: dict) -> str | None:
    """The loader's own resolution order, mirrored — not a second opinion."""
    ce = (m.get("compose_extension") or {}).get("target_stack")
    if ce:
        return ce
    return (((m.get("observability") or {}).get("loki") or {}).get("labels") or {}).get("stack")


def _is_service_plugin(m: dict) -> bool:
    """The estate's own classifier, not a second one.

    `tools/plugin-wiring-report.py:94` selects its 60 service plugins with
    `"service" in manifest.type`. A first draft of this file inferred the kind
    from the presence of a gate or an authentik block and mis-sorted both
    directions at once — which is how a gate ends up measuring its own
    heuristic instead of the tree.
    """
    return "service" in (m.get("type") or [])


def _plugins() -> list[tuple[str, dict]]:
    return [(d.name, _manifest(d / "plugin.yml"))
            for d in sorted(PLUGINS.iterdir()) if (d / "plugin.yml").is_file()]


def test_the_reader_sees_the_plugin_tree() -> None:
    all_ = _plugins()
    assert len(all_) >= 60, f"only {len(all_)} plugins parsed — the assertions below would be vacuous"


def test_every_service_plugin_with_hooks_resolves_a_stack() -> None:
    offenders = []
    for name, m in _plugins():
        if not (m.get("lifecycle") or {}):
            continue
        if not _is_service_plugin(m):
            continue                      # composition: cross-cutting by design
        if _stack(m) is None:
            offenders.append(name)
    assert not offenders, (
        "these service plugins have lifecycle hooks and no resolvable stack, so "
        "`run_hook`'s `pstack is not None` test never excludes them and their "
        "hooks fire on every stack-scoped pass:\n  " + "\n  ".join(offenders))


def test_the_three_measured_ones_carry_their_real_stack() -> None:
    """Pinned by name and VALUE: a stack that resolves but is wrong filters the
    plugin out of the pass that should run it, which is the quieter failure."""
    want = {"jellyfin-base": "iiab", "metabase-base": "data", "spacetimedb-base": "infra"}
    got = {n: _stack(m) for n, m in _plugins() if n in want}
    assert got == want, f"expected {want}, got {got}"


def test_composition_plugins_are_still_allowed_to_be_stackless() -> None:
    """The carve-out is real, not a loophole waiting to swallow the rule: at
    least the alloy/grafana composition set must still be exempt, or the gate
    has quietly become 'every plugin invents a stack'."""
    stackless = [n for n, m in _plugins()
                 if (m.get("lifecycle") or {}) and not _is_service_plugin(m)
                 and _stack(m) is None]
    assert len(stackless) >= 5, (
        "the composition carve-out now covers almost nothing — either the "
        "classifier changed or composition plugins have been given invented "
        "stacks to satisfy this gate")
