"""Derive-floor: blast-radius (reset.scope) resolution for upgrade recipes.

A pure function over a recipe (or migration) dict. Computes the engine *floor*
from the real step/action enum values, then the resolved scope =
``max(authored_scope, derived_floor)`` over the ordering

    none < container < stack < host_app < host_reboot

The authored ``reset.scope`` may only ESCALATE the floor, never lower it — a
recipe that omits ``reset`` (or under-declares it) must never read as ``none``.
``session_risk`` is *derived*, not authored: ``scope in {host_app, host_reboot}``.

This module is imported by full path (``ansible.module_utils.nos_upgrade_actions.
reset_scope`` / ``module_utils.nos_upgrade_actions.reset_scope``) by the upgrade
engine and the schema gate — it is NOT part of the ``merged_handlers`` dispatch
table, so ``__init__.py`` needs no change.

Spec reference: docs/archive/upgrade-reset-scope-and-session-safety.md.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

# Ordered scope rank — higher wins. session_risk = scope in the top two ranks.
SCOPE_RANK = {
    "none": 0,
    "container": 1,
    "stack": 2,
    "host_app": 3,
    "host_reboot": 4,
}

_SESSION_RISK_SCOPES = ("host_app", "host_reboot")

# Per-type floors keyed off the REAL schema enum values.
# Upgrade recipe step.type (state/schema/upgrade.schema.json) and migration
# action.type (state/schema/migration.schema.json) share this map; the two
# enums are disjoint apart from noop/fs.* (all -> none) so a single table is
# unambiguous.
_CONTAINER_TYPES = frozenset((
    # upgrade step types: blast radius = this container only
    "compose.set_image_tag",
    "compose.recreate",
    "compose.restart_service",
))
_STACK_TYPES = frozenset((
    # migration action: renames a compose override -> recreates that service
    # AND its dependents.
    "docker.compose_override_rename",
))
_HOST_APP_TYPES = frozenset((
    # migration actions: a host launchd daemon bounce can ripple into the
    # operator GUI/terminal.
    "launchd.bootout_and_delete",
    "launchd.kickstart",
))

# exec.shell denylist — regexes over the step's literal cmd/command/shell string,
# case-insensitive. resolve_reset runs on the RAW recipe (before phase token
# render, see nos_migrate._apply_upgrade), so recipes MUST keep host-disruptive
# verbs literal (e.g. `sudo reboot`, not `{{ host_op }}`) for the floor to see them.
_HOST_REBOOT_RE = re.compile(
    r"\breboot\b"
    # shutdown (any except a `-c` cancel) and halt — command-anchored (line-start,
    # after a shell separator/pipe, or after sudo) so a recipe's prose/path doesn't
    # false-match. Covers `shutdown -r`, `shutdown -h now`, bare `shutdown now`
    # (halt on macOS), `/sbin/halt`, etc. — all host-takedowns the bare -r missed.
    r"|(?:^|[\n;&|]|\bsudo\s+)\s*(?:/[\w./-]+/)?shutdown\b(?![^\n;|&]*\s-c\b)"
    r"|(?:^|[\n;&|]|\bsudo\s+)\s*(?:/[\w./-]+/)?halt\b"
    # osascript-driven restart / shut down via System Events.
    r"|osascript[^\n]*System Events[^\n]*\b(?:restart|shut down)\b"
    # softwareupdate install: long --install OR a single-dash short-flag cluster
    # containing 'i' (-i, -ia, -ir, -iaR). The lookbehind rejects the second dash
    # of a long flag, so `softwareupdate --list` is NOT mistaken for an install.
    r"|\bsoftwareupdate\b[^\n;|&]*?(?:--install\b|(?<![\w-])-[a-z]*i[a-z]*\b)",
    re.IGNORECASE,
)
_HOST_APP_RE = re.compile(
    r"\bkillall\b"
    r"|\blaunchctl\s+(kickstart|bootout|kill)\b.*(sshd|com\.openssh|Dock|Finder|loginwindow)"
    # bootout/bootstrap of a whole gui/user/login session domain (e.g. gui/501)
    # names no service token but is more disruptive than booting one agent.
    r"|\blaunchctl\s+(?:bootout|bootstrap)\s+(?:gui|user|login)/"
    r"|(open|osascript).*(Docker|\"Docker Desktop\").*?(quit|restart|--restart)"
    r"|\bosascript\b.*\bquit\b"
    r"|\bpkill\b\s+-?\w*\s*(Dock|Finder|Docker)"
    r"|docker\s+desktop.*(restart|--restart)"
    r"|com\.docker\..*kickstart",
    re.IGNORECASE,
)
_CONTAINER_RE = re.compile(
    r"docker\s+compose\b.*\b(up|restart|recreate)\b"
    r"|docker\s+restart\b",
    re.IGNORECASE,
)


def _exec_shell_floor(step):
    """Classify an exec.shell step from its rendered command string."""
    cmd = step.get("cmd") or step.get("command") or step.get("shell") or ""
    if not isinstance(cmd, str):
        cmd = ""
    if _HOST_REBOOT_RE.search(cmd):
        return "host_reboot"
    if _HOST_APP_RE.search(cmd):
        return "host_app"
    if _CONTAINER_RE.search(cmd):
        return "container"
    # An exec.shell op we cannot statically classify must not read as
    # no-restart — an unknown shell op defaults to container.
    return "container"


def _effective_service(recipe, service):
    """The recipe's own service id. The engine passes it explicitly — the picked
    recipe dict on disk has NO ``service`` key (service lives on ``upgrade``), so
    relying on ``recipe.get('service')`` alone made every non-empty consumer list
    (even one naming only itself) read as cross-service. A falsy ``service`` falls
    back to ``recipe.service`` for helper/test callers that set it there."""
    if service:
        return service
    return recipe.get("service")


def _stack_escalation(step, recipe, service):
    """Step-level stack escalation: a step that declares its own
    ``affected_services`` (a downstream blast-radius hint naming a service OTHER
    THAN the recipe's own) bounces the dependency cascade -> floor ``stack``.
    ``service`` is the recipe's own id, so a hint naming only itself does NOT
    escalate.

    NOTE: ``requires.other_services_healthy`` is deliberately NOT a signal here.
    It is a PRECONDITION (services that must be up before the upgrade runs), which
    for a *consumer* like infisical is its own dependencies (postgres/redis), not
    its dependents — treating it as blast radius wrongly escalated every consumer
    to ``stack`` (caught by the authored-vs-floor consistency gate). ``stack`` for
    a shared-DB *provider* (postgres/redis/mariadb) is a semantic judgment the
    recipe AUTHORS above the mechanical container floor, not something derivable
    from a consumer's precondition list.
    """
    svc = service
    aff = step.get("affected_services")
    if isinstance(aff, list) and any(s != svc for s in aff):
        return True
    return False


def step_floor(step, recipe, service=None):
    """Derived floor (scope name) for a single step, given its parent recipe."""
    if not isinstance(step, dict):
        return "none"
    svc = _effective_service(recipe, service)
    stype = step.get("type")
    if stype == "exec.shell":
        floor = _exec_shell_floor(step)
    elif stype in _CONTAINER_TYPES:
        floor = "container"
    elif stype in _STACK_TYPES:
        floor = "stack"
    elif stype in _HOST_APP_TYPES:
        floor = "host_app"
    else:
        # noop, http.*, backup.*, fs.*, state.*, authentik.*, docker.volume_clone
        floor = "none"
    # Stack escalation can only RAISE a sub-stack floor (it never lowers a
    # host_app/host_reboot exec.shell verdict).
    if SCOPE_RANK["stack"] > SCOPE_RANK[floor] and _stack_escalation(step, recipe, svc):
        floor = "stack"
    return floor


def derive_floor(recipe, service=None):
    """Max derived floor for an upgrade recipe OR a migration record.

    Upgrade recipes carry ``pre``/``apply``/``post`` arrays of steps whose ``type``
    is the action; migration records carry ``steps[]`` whose ``action.{type,
    command,shell}`` carries it. Both shapes are handled (a recipe never has
    ``steps`` and a migration never has the phase arrays, so there is no double
    count). The ``rollback`` phase / a step's ``rollback:`` action is deliberately
    EXCLUDED: it runs only on failure and its blast radius is assumed <= the apply
    floor. Including it would over-escalate a recipe whose recovery merely restores.
    """
    floor = "none"
    if not isinstance(recipe, dict):
        return floor
    svc = _effective_service(recipe, service)

    def _raise(f):
        return f if SCOPE_RANK[f] > SCOPE_RANK[floor] else floor

    # Upgrade-recipe shape.
    for phase in ("pre", "apply", "post"):
        for step in recipe.get(phase) or []:
            floor = _raise(step_floor(step, recipe, svc))

    # Migration-record shape: normalize each step's action into a recipe-like step
    # so step_floor classifies it (launchd.* -> host_app,
    # docker.compose_override_rename -> stack, exec.shell -> denylist scan).
    for step in recipe.get("steps") or []:
        if not isinstance(step, dict):
            continue
        action = step.get("action") or {}
        if not isinstance(action, dict):
            continue
        norm = {"type": action.get("type")}
        for k in ("cmd", "command", "shell"):
            if isinstance(action.get(k), str):
                norm[k] = action[k]
        if step.get("affected_services") is not None:
            norm["affected_services"] = step.get("affected_services")
        floor = _raise(step_floor(norm, recipe, svc))

    return floor


def resolve_reset(recipe, service=None):
    """Resolve the effective reset block for a recipe (or migration) dict.

    ``service`` is the recipe's own service id (the engine passes
    ``upgrade.service``); it is threaded into the stack-escalation check so a
    ``requires.other_services_healthy`` list naming only the service itself does
    not spuriously escalate to ``stack``.

    Returns a dict with always-present keys ``scope`` and ``session_risk``,
    plus the authored pass-through fields (``estimated_sec``,
    ``affected_services``, ``affected_host_apps``, ``reason``) and, when the
    authored scope sat below the derived floor, a ``reset_floor_raised``
    diagnostic. Folds legacy migration ``downtime`` into ``reset`` when
    ``reset`` is absent.
    """
    if not isinstance(recipe, dict):
        recipe = {}
    derived = derive_floor(recipe, _effective_service(recipe, service))
    authored = recipe.get("reset") if isinstance(recipe.get("reset"), dict) else None

    # Legacy migration `downtime` folds into reset only when reset is absent.
    downtime = recipe.get("downtime") if isinstance(recipe.get("downtime"), dict) else None

    authored_scope = None
    if authored is not None:
        authored_scope = authored.get("scope")
        if authored_scope not in SCOPE_RANK:
            authored_scope = None

    if authored_scope is not None and SCOPE_RANK[authored_scope] > SCOPE_RANK[derived]:
        scope = authored_scope
    else:
        scope = derived

    out = {
        "scope": scope,
        "session_risk": scope in _SESSION_RISK_SCOPES,
        "estimated_sec": None,
        "affected_services": None,
        "affected_host_apps": None,
        "reason": None,
    }

    if authored is not None:
        # Pass authored metadata through verbatim.
        out["estimated_sec"] = authored.get("estimated_sec")
        out["affected_services"] = authored.get("affected_services")
        out["affected_host_apps"] = authored.get("affected_host_apps")
        out["reason"] = authored.get("reason")
    elif downtime is not None:
        # Migration legacy alias: fold downtime fields in at the derived floor.
        out["estimated_sec"] = downtime.get("estimated_sec")
        out["affected_services"] = downtime.get("services_affected")

    # Diagnostic: authored present but below the derived floor (escalated, not
    # rejected, at runtime — the schema gate is what rejects it in CI).
    if authored_scope is not None and SCOPE_RANK[authored_scope] < SCOPE_RANK[derived]:
        out["reset_floor_raised"] = {
            "authored": authored_scope,
            "derived": derived,
            "resolved": scope,
        }

    return out
