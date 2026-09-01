"""Every plugin that renders config into a running container has a way to reload it.

THE DEFECT, measured 2026-08-31. Plugins render config into a bind
mount of a running container. Nothing made the process re-read it: `docker
compose up -d` is a no-op when the service DEFINITION is unchanged, and
Prometheus's `/-/reload` answers 403 because the lifecycle API is off on
purpose. A converge rewrote `prometheus.yml` with a new Traefik scrape job,
finished `failed=0`, and Prometheus went on serving the previous config. The
target simply never appeared, and every surface said the run had succeeded.

Every one of these services already HAD a `Restart <svc>` handler. The handlers
are notified by the role task that renders the compose OVERRIDE — never by the
plugin loader that renders the CONFIG. So the machinery existed and the wire to
it did not, which is the shape that survives longest: a reviewer greps for
"Restart prometheus", finds it, and moves on.

WHAT THIS PINS.

1. The converge actually runs the reconciler, after the stacks are up.
2. The reconciler is wired to the READER rather than to a hand-maintained list,
   so a plugin added tomorrow — or a user's own extension — is covered without
   editing anything here.
3. Any manifest that opts OUT of the restart gives a reason and names its
   services, because "this one doesn't need it" is a claim about a running
   process and claims like that rot silently.

It does NOT check that a restart happened — that needs a live estate and
belongs to `--tags verify`, not to pytest (division of labour, CLAUDE.md).
"""

from __future__ import annotations

import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
PLUGINS = ROOT / "files/anatomy/plugins"
ACTOR = ROOT / "tools/reload-stale-config.py"
READER = ROOT / "tools/stale-config-status.py"
MAIN = ROOT / "main.yml"


def test_the_actor_and_the_reader_both_exist() -> None:
    assert READER.is_file(), "tools/stale-config-status.py is gone — nothing detects staleness"
    assert ACTOR.is_file(), "tools/reload-stale-config.py is gone — nothing acts on it"


def test_the_actor_uses_the_reader_rather_than_a_list() -> None:
    """A hand-maintained list of services is the thing this must not become.

    The whole reason the defect survived is that the estate had per-service
    wiring and one service was missing from it. A reconciler that enumerates
    services has the same failure mode one level up.
    """
    body = ACTOR.read_text(encoding="utf-8")
    assert "stale-config-status.py" in body, (
        "the actor no longer loads the reader — it must derive its work from "
        "the live mounts, not from a list that can omit a service")
    assert ".scan()" in body, "the actor no longer calls the reader's scan()"


def test_the_converge_runs_it_after_the_stacks() -> None:
    body = MAIN.read_text(encoding="utf-8")
    assert "reload-stale-config.py --apply" in body, (
        "main.yml does not run the reconciler — a converge can still render "
        "config that the running container never reads, and report failed=0")

    # After the stacks: a container this run started is already fresh, and the
    # reconciler compares against StartedAt. Running it before stack-up would
    # restart containers that are about to be recreated anyway.
    reload_at = body.index("reload-stale-config.py --apply")
    stacks_at = body.rindex("tasks/stacks/stack-up.yml")
    assert reload_at > stacks_at, (
        "the reconciler runs BEFORE stack-up.yml — it must come after, or it "
        "compares config against containers that have not started yet")


def _manifests_with_reload() -> list[tuple[str, dict]]:
    out = []
    for manifest in sorted(PLUGINS.glob("*/plugin.yml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        if isinstance(data.get("reload"), dict):
            out.append((manifest.parent.name, data["reload"]))
    return out


def test_an_opt_out_names_its_services_and_says_why() -> None:
    for plugin, declared in _manifests_with_reload():
        assert declared.get("mode") == "self", (
            f"{plugin}: reload.mode is {declared.get('mode')!r}; `self` is the "
            "only value the reconciler understands. An unknown one is NOT "
            "treated as exempt — reload-stale-config.py:78 `continue`s past "
            "it, so the service lands in `todo` and gets restarted. That is "
            "the safe direction the opt-OUT polarity chose; what this refuses "
            "is a manifest that LOOKS like an opt-out and silently is not")
        services = declared.get("services")
        assert isinstance(services, list) and services, (
            f"{plugin}: reload declares no `services` list, so it exempts "
            "nothing and the opt-out is decorative")
        reason = (declared.get("reason") or "").strip()
        assert len(reason) > 40, (
            f"{plugin}: reload has no substantive `reason`. This is a claim "
            "that a running process re-reads its own config; without the "
            "evidence, nobody can tell later whether it is still true")
