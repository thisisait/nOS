"""Anatomy gate — tofu self-reconcile preflight (the durable desync fix).

tofu tracks each Authentik provider by integer PK (resource id). Those PKs drift
out from under the state on a non-blank converge, so `tofu plan` reads a dangerous
in-place client_id/external_host flip and the destroy guard REFUSES every re-run
(proven live 2026-06-15; providers are managed=None, so no single churner exists
to eliminate). The fix makes the engine self-reconcile: a DRIFT-CONDITIONAL,
IDENTITY-ONLY preflight re-points module.service[*] at the live PK before plan,
via the stable application.slug→provider bridge. This gate pins:

  * the preflight runs BEFORE `tofu plan`, gated to engine=tofu;
  * the reconcile tool is identity-only + drift-conditional + has --preflight;
  * the tool NEVER runs `tofu apply` (import/state ops only — the safety rail
    that lets it run unattended on every converge).
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK = (REPO / "tasks/tofu-authentik.yml").read_text(encoding="utf-8")
TOOL = (REPO / "tools/tofu-authentik-reconcile.sh").read_text(encoding="utf-8")


def test_preflight_runs_before_plan():
    pre = TASK.find("Self-reconcile state PKs to live")
    plan = TASK.find("tofu plan (-out so apply can be destroy-gated)")
    assert pre != -1, "the reconcile preflight task must exist in tofu-authentik.yml"
    assert plan != -1, "the tofu plan task must exist"
    assert pre < plan, "reconcile must run BEFORE the plan (it fixes PK identity so plan reads real drift)"


def test_preflight_invokes_the_tool_in_preflight_mode():
    assert "tofu-authentik-reconcile.sh --preflight" in TASK, \
        "preflight must call the reconcile tool in --preflight mode"


def test_preflight_is_gated_to_tofu_engine():
    # The preflight block must be guarded so the imperative (blueprint) engine —
    # which has no tofu state — never runs it.
    seg = TASK[TASK.find("Self-reconcile state PKs to live"):TASK.find("tofu plan (-out")]
    assert "authentik_engine" in seg and "== 'tofu'" in seg, \
        "the reconcile preflight must be gated to engine=tofu"


def test_preflight_is_best_effort_not_a_silent_apply_path():
    # It may fail soft (the plan+guard below are the authoritative rails), but it
    # must NEVER be the thing that mutates the tenant — that stays the guarded apply.
    seg = TASK[TASK.find("Self-reconcile state PKs to live"):TASK.find("tofu plan (-out")]
    assert "failed_when: false" in seg, \
        "preflight must degrade gracefully (plan+guard are the rails), not hard-fail the converge"
    # A loud summary keeps the soft-fail visible (no silent-failure anti-pattern).
    assert "Reconcile preflight summary" in TASK, \
        "a visible summary must surface the reconcile result (no silent failure)"


def test_tool_is_drift_conditional():
    # It must compare state PK vs live PK and act only on drift — cheap enough to
    # run every converge. A blanket re-import every run would churn the serial and
    # mask the no-drift case.
    assert "statepk_for" in TOOL, "tool must read the state's recorded PK per slug"
    assert 'if [ "$spk" = "$pk" ]; then ALIGNED' in TOOL, \
        "tool must SKIP services whose state PK already equals the live PK"
    assert "reconciled=" in TOOL and "aligned=" in TOOL, \
        "tool must report reconciled vs aligned counts"


def test_tool_uses_the_stable_slug_provider_bridge():
    # The source of truth is the application (imports by slug, never desyncs) →
    # its bound provider PK. NOT a provider-name match (names can collide / drift).
    assert "core/applications/" in TOOL, "tool must read live applications for the slug→provider bridge"
    assert "a.get('provider')" in TOOL, "tool must take the provider PK from the application binding"


def test_tool_never_applies():
    # The unattended-safety invariant: import + state ops ONLY. A stray `tofu apply`
    # would make a best-effort preflight able to mutate the tenant.
    assert "tofu apply" not in TOOL, \
        "reconcile tool must NEVER run `tofu apply` — import/state ops only"
    assert "--preflight" in TOOL, "tool must support the --preflight mode the playbook calls"


def test_tool_backs_up_state_before_mutating():
    assert "reconcile-bak-" in TOOL, "tool must back up terraform.tfstate before any state op"
