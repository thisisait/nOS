"""Anatomy CI gate — upgrade reset-scope derive-floor (Phase 1).

Pins the pure derive-floor helper
(files/anatomy/module_utils/nos_upgrade_actions/reset_scope.py):

  * an image-bump recipe (compose.set_image_tag) derives `container`
  * a recipe of only no-op / http.* / backup.* steps derives `none`
  * an authored host_reboot escalation survives (authored may raise the floor)
  * an authored `none` on a compose.set_image_tag recipe is RAISED to container
    (authored may never lower the derived floor) + emits reset_floor_raised
  * session_risk is derived from the resolved scope, not authored

Spec: docs/plans/upgrade-reset-scope-and-session-safety.md.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_MODUTILS = os.path.join(_REPO, "files", "anatomy")
if _MODUTILS not in sys.path:
    sys.path.insert(0, _MODUTILS)

from module_utils.nos_upgrade_actions.reset_scope import (  # noqa: E402
    SCOPE_RANK,
    derive_floor,
    resolve_reset,
    step_floor,
)


def test_image_bump_derives_container():
    recipe = {
        "service": "grafana",
        "apply": [{"id": "bump", "type": "compose.set_image_tag", "tag": "11.0"}],
    }
    assert derive_floor(recipe) == "container"
    r = resolve_reset(recipe)
    assert r["scope"] == "container"
    assert r["session_risk"] is False


def test_noop_http_backup_only_derives_none():
    recipe = {
        "service": "grafana",
        "pre": [
            {"id": "dump", "type": "backup.volume", "label": "g"},
            {"id": "wait", "type": "http.wait", "url": "http://x"},
        ],
        "post": [{"id": "done", "type": "noop"}],
    }
    assert derive_floor(recipe) == "none"
    assert resolve_reset(recipe)["scope"] == "none"


def test_authored_host_reboot_escalation_survives():
    recipe = {
        "service": "docker",
        "reset": {"scope": "host_reboot", "reason": "major Docker Desktop"},
        "apply": [{"id": "bump", "type": "compose.set_image_tag", "tag": "v2"}],
    }
    # derived floor is only container; authored escalates to host_reboot.
    assert derive_floor(recipe) == "container"
    r = resolve_reset(recipe)
    assert r["scope"] == "host_reboot"
    assert r["session_risk"] is True
    assert r["reason"] == "major Docker Desktop"
    assert "reset_floor_raised" not in r  # authored is ABOVE floor, not below


def test_authored_none_raised_to_container_floor():
    recipe = {
        "service": "grafana",
        "reset": {"scope": "none"},
        "apply": [{"id": "bump", "type": "compose.set_image_tag", "tag": "11.0"}],
    }
    r = resolve_reset(recipe)
    # authored 'none' may not lower the container floor.
    assert r["scope"] == "container"
    assert r["session_risk"] is False
    assert r["reset_floor_raised"] == {
        "authored": "none",
        "derived": "container",
        "resolved": "container",
    }


def test_exec_shell_reboot_is_host_reboot():
    recipe = {
        "service": "host",
        "allow_shell": True,
        "apply": [{"id": "rb", "type": "exec.shell", "cmd": "sudo reboot"}],
    }
    assert step_floor(recipe["apply"][0], recipe) == "host_reboot"
    r = resolve_reset(recipe)
    assert r["scope"] == "host_reboot"
    assert r["session_risk"] is True


def test_exec_shell_killall_is_host_app():
    recipe = {
        "service": "host",
        "apply": [{"id": "k", "type": "exec.shell", "cmd": "killall Dock"}],
    }
    assert resolve_reset(recipe)["scope"] == "host_app"


def test_unknown_exec_shell_defaults_to_container_not_none():
    recipe = {
        "service": "svc",
        "apply": [{"id": "x", "type": "exec.shell", "cmd": "/opt/do-a-thing.sh"}],
    }
    assert resolve_reset(recipe)["scope"] == "container"


def test_requires_other_services_is_precondition_not_blast_radius():
    # requires.other_services_healthy is a PRECONDITION (deps that must be up),
    # NOT a downstream blast-radius signal — a consumer (infisical) requiring
    # postgres+redis healthy still only restarts its own container. It must NOT
    # auto-escalate to stack (that over-escalation is what the consistency gate
    # caught on the shipped infisical recipes). Shared-DB providers AUTHOR stack.
    recipe = {
        "requires": {"other_services_healthy": ["postgresql", "redis"]},
        "apply": [{"id": "bump", "type": "compose.set_image_tag", "tag": "v2"}],
    }
    assert resolve_reset(recipe, service="infisical")["scope"] == "container"


def test_step_affected_services_hint_escalates_to_stack():
    # The one mechanical stack path for an upgrade recipe: a step that DECLARES
    # affected_services naming a downstream service other than self.
    recipe = {
        "apply": [{
            "id": "bump", "type": "compose.set_image_tag", "tag": "17",
            "affected_services": ["authentik", "outline"],
        }],
    }
    assert resolve_reset(recipe, service="postgresql")["scope"] == "stack"


def test_migration_downtime_folds_when_reset_absent():
    migration = {
        "service": "postgresql",
        "downtime": {"estimated_sec": 90, "services_affected": ["authentik"]},
        "apply": [{"id": "noop", "type": "noop"}],
    }
    r = resolve_reset(migration)
    assert r["estimated_sec"] == 90
    assert r["affected_services"] == ["authentik"]


def test_scope_rank_total_order():
    assert SCOPE_RANK == {
        "none": 0,
        "container": 1,
        "stack": 2,
        "host_app": 3,
        "host_reboot": 4,
    }


def test_softwareupdate_install_short_flags_are_host_reboot():
    # `softwareupdate -ia` (install + agree, the common single-token form) and
    # its variants must classify as host_reboot — a macOS update can reboot.
    for cmd in ("softwareupdate -ia", "softwareupdate -i -a",
                "softwareupdate --install --all", "softwareupdate -i"):
        step = {"id": "su", "type": "exec.shell", "cmd": cmd}
        assert step_floor(step, {}, "host") == "host_reboot", cmd


def test_softwareupdate_list_is_not_host_reboot():
    # --list / -l must not be mistaken for install; an unknown shell op floors at
    # container (never none), so this stays container, not host_reboot.
    step = {"id": "su", "type": "exec.shell", "cmd": "softwareupdate --list"}
    assert step_floor(step, {}, "host") == "container"


def test_launchctl_gui_domain_bootout_is_host_app():
    # Booting the operator's whole GUI session domain (gui/501) names no service
    # token but is host_app-class — more disruptive than booting one agent.
    step = {"id": "bo", "type": "exec.shell", "cmd": "launchctl bootout gui/501"}
    assert step_floor(step, {}, "host") == "host_app"


def test_host_takedown_variants_are_host_reboot():
    # The full host-takedown set must classify host_reboot (the bare `shutdown -r`
    # missed `-h`/bare/halt/osascript — an under-classification in the DANGEROUS
    # direction that would skip the session-risk pause). Engine must agree with the
    # host-quiet test denylist.
    for cmd in ("sudo shutdown -h now", "sudo halt", "shutdown now",
                "/sbin/halt", "shutdown -r now",
                "osascript -e 'tell app \"System Events\" to restart'"):
        step = {"id": "td", "type": "exec.shell", "cmd": cmd}
        assert step_floor(step, {}, "host") == "host_reboot", cmd


def test_shutdown_cancel_is_not_host_reboot():
    # `shutdown -c` cancels a pending shutdown — it is NOT a host-takedown.
    step = {"id": "c", "type": "exec.shell", "cmd": "sudo shutdown -c"}
    assert step_floor(step, {}, "host") == "container"


def test_authored_low_scope_cannot_lower_host_reboot_floor():
    # Safety-critical inverse: an authored 'container' under a derived host_reboot
    # floor must STAY host_reboot (authored may escalate, never lower).
    recipe = {
        "reset": {"scope": "container"},
        "allow_shell": True,
        "apply": [{"id": "rb", "type": "exec.shell", "cmd": "sudo reboot"}],
    }
    r = resolve_reset(recipe, service="host")
    assert r["scope"] == "host_reboot"
    assert r["session_risk"] is True
    assert r["reset_floor_raised"] == {
        "authored": "container", "derived": "host_reboot", "resolved": "host_reboot",
    }


def test_shipped_recipes_author_scope_at_or_above_floor():
    """The Wing matrix/plan-choice displays the AUTHORED scope verbatim (ingest
    stores it, does NOT derive; a missing reset shows the NULL->'container'
    default). Two ways that could understate the blast radius, both flagged here:

      1. A recipe that AUTHORS reset must author scope >= its derived floor.
      2. A recipe that OMITS reset must have a derived floor <= 'container' — else
         Wing shows 'container' for a recipe the engine will treat as stack/
         host_app/host_reboot, hiding the session-risk callout. Such a recipe MUST
         author an explicit reset block.

    This makes the authored display path provably safe; the engine still escalates
    at apply time as a backstop."""
    import glob as _glob
    import yaml as _yaml

    offenders = []
    for path in sorted(_glob.glob(os.path.join(_REPO, "upgrades", "*.yml"))):
        if os.path.basename(path) == "_template.yml":
            continue
        with open(path) as fh:
            data = _yaml.safe_load(fh) or {}
        service = data.get("service")
        for recipe in data.get("recipes") or []:
            if not isinstance(recipe, dict):
                continue
            rid = recipe.get("id", "?")
            floor = derive_floor(recipe, service=service)
            reset = recipe.get("reset")
            if not isinstance(reset, dict):
                # No authored reset → Wing renders the NULL->'container' default.
                # Honest only when the mechanical floor is <= container.
                if SCOPE_RANK[floor] > SCOPE_RANK["container"]:
                    offenders.append(
                        "%s::%s omits reset but derives floor '%s' (> container) — "
                        "Wing would understate it; author an explicit reset block"
                        % (os.path.basename(path), rid, floor)
                    )
                continue
            authored = reset.get("scope")
            if authored not in SCOPE_RANK or SCOPE_RANK[authored] < SCOPE_RANK[floor]:
                offenders.append(
                    "%s::%s authored '%s' < derived floor '%s'"
                    % (os.path.basename(path), rid, authored, floor)
                )
    assert not offenders, (
        "recipe reset.scope would understate the blast radius in Wing:\n  - "
        + "\n  - ".join(offenders)
    )
