"""Anatomy gate: the Phase-3 session-risk pre-apply pause can NEVER hang a
non-interactive / detached / CI upgrade run, and it gates on the right signal.

Spec: docs/archive/upgrade-reset-scope-and-session-safety.md §"Execution side".

A session_risk upgrade (resolved scope host_app|host_reboot) may restart a host
app or reboot the machine and drop the controlling session. The upgrade engine
runs a dry-run PREVIEW pass to learn each recipe's derived reset, then pauses
ONCE before the real apply — but ONLY interactively. This gate pins:

  1. There IS a session-risk confirm pause, modeled on the breaking-migration
     pause, keyed off `_session_risk_jobs` (the preview's session_risk list).
  2. That pause's `when:` carries the full triple escape hatch — `auto_migrate`,
     `upgrade_confirmed`, AND `upgrade_dry_run` — so a detached / CI / preview
     run NEVER blocks on it.
  3. A dry-run PREVIEW pass (apply_upgrade dry_run:true) runs BEFORE the real
     apply loop so the gate has derived scope to key off, and it is non-mutating
     (changed_when:false, failed_when:false).
  4. The reboot-required marker + A9 notification only fire for host_reboot
     scope and are dry-run-gated.

If this gate FAILS the pause could hang an unattended run (or fire on the wrong
signal) — a real finding, not a flaky test.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE = REPO / "tasks" / "upgrade-engine.yml"


def _load_tasks() -> list[dict]:
    tasks = yaml.safe_load(ENGINE.read_text()) or []
    assert isinstance(tasks, list) and tasks, "upgrade-engine.yml parsed to zero tasks"
    return [t for t in tasks if isinstance(t, dict)]


def _when_clauses(task: dict) -> list[str]:
    """Normalize a task's `when:` into a list of string clauses."""
    w = task.get("when")
    if w is None:
        return []
    if isinstance(w, str):
        return [w]
    if isinstance(w, list):
        return [str(x) for x in w]
    return [str(w)]


def _find(tasks: list[dict], needle: str) -> dict | None:
    for t in tasks:
        if needle.lower() in str(t.get("name", "")).lower():
            return t
    return None


# ── (1) + (2) the session-risk pause: exists, keyed off session_risk, triple-gated


def test_session_risk_pause_is_triple_gated_against_hang():
    tasks = _load_tasks()
    pause = _find(tasks, "Confirm session-risk upgrades")
    assert pause is not None, (
        "no '[Upgrade] Confirm session-risk upgrades' pause — the host_app/"
        "host_reboot pre-apply gate is missing"
    )
    # It is an actual ansible.builtin.pause (would block interactively).
    assert "ansible.builtin.pause" in pause or "pause" in pause, (
        "the session-risk confirm task is not an ansible.builtin.pause"
    )

    clauses = " ; ".join(_when_clauses(pause))
    assert clauses, "session-risk pause has no `when:` — it would ALWAYS pause"

    # The triple escape hatch — ANY of these set true must skip the pause, so a
    # detached / CI / preview run can never block.
    assert "auto_migrate" in clauses, (
        "session-risk pause not gated by auto_migrate — auto-apply would hang"
    )
    assert "upgrade_confirmed" in clauses, (
        "session-risk pause not gated by upgrade_confirmed — the detached "
        "launcher's pre-confirm extra-var would not bypass it (would hang)"
    )
    assert "upgrade_dry_run" in clauses, (
        "session-risk pause not gated by upgrade_dry_run — a preview run would "
        "block on a confirm prompt"
    )

    # It keys off the session-risk job list, NOT severity (the existing breaking
    # pause already covers severity; this is the orthogonal blast-radius gate).
    assert "_session_risk_jobs" in clauses, (
        "session-risk pause does not key off _session_risk_jobs — it would fire "
        "on the wrong signal (e.g. severity, not scope)"
    )

    # POLARITY (not just presence): each boolean escape-hatch clause must be a
    # NEGATION. A dropped `not` would INVERT the gate so the detached launcher's
    # `upgrade_confirmed=true` would CAUSE the hang it exists to prevent — and a
    # presence-only assertion cannot catch that mutation.
    clause_list = _when_clauses(pause)
    for var in ("auto_migrate", "upgrade_confirmed", "upgrade_dry_run"):
        owning = [c for c in clause_list if var in c]
        assert owning, f"session-risk pause has no `when:` clause mentioning {var}"
        for c in owning:
            assert c.strip().startswith("not "), (
                f"escape-hatch clause for {var} is not a negation ({c!r}) — a "
                "dropped `not` would invert the gate and hang the detached run"
            )
    # ansible_check_mode is also negated when present (--check must not prompt).
    for c in clause_list:
        if "ansible_check_mode" in c:
            assert c.strip().startswith("not "), (
                f"ansible_check_mode clause is not a negation ({c!r})"
            )


def test_session_risk_jobs_derive_from_scope_host_app_or_reboot():
    """The job list the pause keys off must select recipes whose RESOLVED scope
    is session-risk (host_app|host_reboot) via the preview's session_risk flag —
    not severity, not authored scope."""
    tasks = _load_tasks()
    setfact = _find(tasks, "Identify session-risk recipes")
    assert setfact is not None, "no '[Upgrade] Identify session-risk recipes' set_fact"
    body = yaml.safe_dump(setfact)
    assert "session_risk" in body, (
        "session-risk job set_fact does not filter on session_risk"
    )
    assert "_upgrade_preview" in body, (
        "session-risk job list is not derived from the dry-run PREVIEW pass"
    )


# ── (3) the preview pass: dry-run, before the real apply, non-mutating


def test_preview_pass_is_dry_run_and_non_mutating():
    tasks = _load_tasks()
    preview = _find(tasks, "PREVIEW")
    assert preview is not None, (
        "no '[Upgrade] PREVIEW ...' task — the engine has no reset-scope preview"
    )
    args = preview.get("nos_migrate") or {}
    assert args.get("action") == "apply_upgrade", (
        "preview task is not an apply_upgrade call"
    )
    # dry_run MUST be a literal true (not threaded from upgrade_dry_run) — even a
    # wet run needs the preview to decide the gate without mutating.
    assert str(args.get("dry_run")).lower() in ("true", "yes"), (
        "preview pass is not hard dry_run:true — it could mutate before the gate"
    )
    assert str(preview.get("changed_when")).lower() in ("false", "no"), (
        "preview pass is not changed_when:false"
    )
    assert str(preview.get("failed_when")).lower() in ("false", "no"), (
        "preview pass is not failed_when:false — a recipe failing validation "
        "would abort before the gate could read its reset"
    )


def test_preview_runs_before_real_apply_loop():
    tasks = _load_tasks()
    names = [str(t.get("name", "")) for t in tasks]

    def idx(needle: str) -> int:
        for i, n in enumerate(names):
            if needle.lower() in n.lower():
                return i
        return -1

    i_preview = idx("PREVIEW")
    i_gate = idx("Confirm session-risk upgrades")
    i_apply = idx("Apply each eligible recipe")
    assert i_preview != -1 and i_gate != -1 and i_apply != -1, (
        f"missing task(s): preview={i_preview} gate={i_gate} apply={i_apply}"
    )
    assert i_preview < i_gate < i_apply, (
        "ordering broken — preview + session-risk gate must precede the real "
        f"apply loop (preview={i_preview}, gate={i_gate}, apply={i_apply})"
    )


# ── (4) reboot marker + A9 notification: host_reboot-only, dry-run-gated


def test_reboot_marker_and_notification_are_host_reboot_only_and_dry_run_gated():
    tasks = _load_tasks()
    ident = _find(tasks, "Identify successfully-applied host_reboot")
    marker = _find(tasks, "Write reboot-required marker")
    notify = _find(tasks, "reboot_required' notification")
    assert ident is not None, "no host_reboot success-identification set_fact"
    assert marker is not None, "no reboot-required marker writer"
    assert notify is not None, "no reboot_required A9 notification task"

    # Only host_reboot scope qualifies (host_app needs no reboot).
    ident_body = yaml.safe_dump(ident)
    assert "host_reboot" in ident_body, (
        "reboot job identification does not restrict to host_reboot scope"
    )

    for t, label in ((ident, "ident"), (marker, "marker"), (notify, "notify")):
        clauses = " ; ".join(_when_clauses(t))
        assert "upgrade_dry_run" in clauses, (
            f"reboot {label} task is not dry-run-gated — a preview would write a "
            "marker / fire a notification"
        )

    # The marker is written via a non-command module (copy/template), so it does
    # NOT contribute a host-disruptive command (the host-quiet gate stays green).
    assert ("ansible.builtin.copy" in marker or "copy" in marker
            or "ansible.builtin.template" in marker or "template" in marker), (
        "reboot marker is not written via copy/template"
    )


def test_reboot_marker_records_boot_id_and_clear_compares_it():
    """The 'clears on restart' contract (the other half of the marker): the write
    must embed boot_id in the marker, and the clear task's `when:` must compare a
    marker's stored boot_id against the live _nos_boot_id capture — so a marker
    written before a reboot is removed once the host has restarted."""
    tasks = _load_tasks()
    marker = _find(tasks, "Write reboot-required marker")
    clear = _find(tasks, "Clear stale reboot-required markers")
    boot = _find(tasks, "Capture current boot id")
    assert marker is not None, "no reboot-required marker writer"
    assert clear is not None, "no stale-marker clear task"
    assert boot is not None, "no boot-id capture task (clear has nothing to compare)"

    assert "boot_id" in yaml.safe_dump(marker), (
        "reboot marker does not record boot_id — the clear task cannot detect a "
        "restart and the banner would persist forever"
    )
    clause = " ".join(_when_clauses(clear))
    assert "boot_id" in clause and "_nos_boot_id" in clause, (
        "clear task `when:` does not compare a stored boot_id against the live "
        "_nos_boot_id — stale markers would never be cleared"
    )


def test_reboot_notification_payload_is_literal_and_signed():
    """The A9 reboot_required notification must use a LITERAL title+body (NOT
    template+context — a template name 404s in Bone's _lookup_template -> 400 ->
    silently dropped under failed_when:false), page severity high on both
    wing-inbox+ntfy, HMAC-sign a sort-keys-canonical body, AND receive the secret
    via `environment:` (else the shell self-skips with the secret unset)."""
    tasks = _load_tasks()
    notify = _find(tasks, "reboot_required' notification")
    assert notify is not None, "no reboot_required A9 notification task"
    shell = notify.get("ansible.builtin.shell") or notify.get("shell") or {}
    cmd = shell.get("cmd", "") if isinstance(shell, dict) else str(shell)

    assert 'severity: "high"' in cmd or "severity: 'high'" in cmd, (
        "notification does not page severity high"
    )
    assert "wing-inbox" in cmd and "ntfy" in cmd, (
        "notification does not list both wing-inbox and ntfy channels"
    )
    assert "title:" in cmd and "body:" in cmd, (
        "notification does not set a literal title/body"
    )
    assert "template:" not in cmd and "context:" not in cmd, (
        "notification uses template:/context: — Bone's _lookup_template would 404 "
        "(no upgrade-engine plugin) -> 400 -> the notification is silently dropped"
    )
    assert "X-Wing-Signature" in cmd and "--sort-keys" in cmd, (
        "notification is not HMAC-signed over a sort-keys-canonical body"
    )
    env = notify.get("environment") or {}
    assert "WING_EVENTS_HMAC_SECRET" in env, (
        "notify task has no environment WING_EVENTS_HMAC_SECRET — the shell's "
        "$WING_EVENTS_HMAC_SECRET would be unset and the task ALWAYS self-skips"
    )


# ── (5) whole-file tag discipline preserved


def test_engine_tasks_stay_upgrade_tagged():
    """Every new task must keep the 'upgrade' tag so the file stays isolated
    behind --tags upgrade (the host-quiet contract depends on tag isolation)."""
    tasks = _load_tasks()
    offenders = []
    for t in tasks:
        tg = t.get("tags")
        tagset = {tg} if isinstance(tg, str) else set(tg or [])
        if "upgrade" not in tagset:
            offenders.append(t.get("name", "<unnamed>"))
    assert not offenders, (
        f"upgrade-engine task(s) missing the 'upgrade' tag: {offenders}"
    )
