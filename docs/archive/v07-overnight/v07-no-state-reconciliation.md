# Plan — State observed but never reconciled (v0.7 overnight)

**Status:** PLAN (not implemented). Branch: `feat/v0.7-overnight`.
**Owner:** pazny. **Confirmed item:** `v07-no-state-reconciliation`.
**Class:** framework gap — the State framework *introspects* drift (`installed` vs
`desired`, `healthy=false`, `enabled` mismatch) and persists it to
`~/.nos/state.yml`, but **nothing reconciles or escalates it**. Drift is computed,
buried in a `debug` line, and dropped on the floor. Same shape as the A9 "signal
lived only in events, nothing escalated" gap that A9 notification-fanout closed for
findings — here it's the *state* signal that has no write-seam.

---

## 1. Problem / why

The State framework (`pazny.state_manager` → `nos_state` introspect →
`~/.nos/state.yml`) is **observe-only**. Per run it computes, for every manifest
service:

- `installed` — the running image tag / brew version / launchd-loaded token
  (`nos_state_lib.introspect_service`, `files/anatomy/module_utils/nos_state_lib.py:357`)
- `desired` — the role/config version var (`version_var` resolved against `role_vars`)
- `healthy` — container running / formula present / agent loaded
- `enabled` — the `install_<svc>` flag

These four fields make **drift first-class data**:

| Drift class | Signal in state.yml | What it means |
|---|---|---|
| **version drift** | `installed != desired` (both non-null) | running tag lags the pin — a CVE pin bump that never got applied, or a `--tags <svc>` render-only pass that didn't recreate. The exact silent-revert footgun the upgrade-engine memory warns about. |
| **health drift** | `enabled == true` and `healthy == false` | a service the operator asked for is down. |
| **presence drift** | `enabled == true` and `installed == null` | enabled but never introspected as running (missing container). |

Today **all three are computed and then discarded**. The only consumer is the
`[state] Summary` debug task (`roles/pazny.state_manager/tasks/report.yml:5-15`),
which prints `grafana: 11.2.0 (desired: 11.5.0)` into `ansible.log` and moves on:

- **No assertion** — a run with a stale image is `failed=0`. The version-pin-shadow
  memory (`version-pins-default-config-shadow.md`) is *precisely* this failure mode:
  a pin that "wins" in `default.config.yml` but the **running image never matched it**
  and nobody noticed. We gate the *pin-vs-pin* shadow statically, but never check the
  *pin-vs-running-image* truth that state already has in hand.
- **No A9 notification** — A9 (`notification-fanout`) gives findings/agents a
  severity-routed write-seam to the operator (`wing-inbox`|`ntfy`|`mail`). State drift
  — arguably the highest-signal "your house diverged from its blueprint" event — has
  **no** route into it. `drift-watch.sh` covers **security/CVE** drift only (it shells
  `20-cve-drift-check.sh`), not state-reconciliation drift.
- **No structured drift record** — `~/.nos/state.yml` has no `drift:` block, so Wing /
  Bone / the conductor agent cannot answer "what is currently out of sync?" without
  re-deriving it from `installed`/`desired` per-service by hand.

**Why now / why it matters:** nOS's whole thesis is "the playbook is the single
source of truth; the system is replicable." A framework that *measures* divergence
from the blueprint and then **says nothing** quietly breaks that thesis. The concrete
overnight-relevant failure: an operator bumps a CVE pin in `default.config.yml`, runs
`ansible-playbook main.yml --tags <svc>` with `--skip-tags stacks` (render-only), and
walks away believing they're patched — `installed` still lags `desired`, `failed=0`,
no signal. This is a **reporting/reconciliation gap**, not a live-mutation task: the
fix *reads* the state the framework already produces and turns drift into a
**reported + optionally-asserted** signal. No service is touched, nothing destructive,
fully repo + read-only-introspection scoped — exactly an unsupervised-safe item.

**Scope boundary (critical — this is NOT auto-remediation):** per the destructive-op
safety doctrine (`feedback-destructive-op-safety.md`) and the machinery doctrine, the
*fix* does **not** auto-apply upgrades or recreate containers to "close" drift. That's
the supervised `--tags upgrade` path. This item makes drift **legible and loud** —
record it, notify it, optionally fail-loud in a guarded gate-mode — so the operator
(or the on-demand upgrade-advisor agent) decides. Reconciliation = *surfacing the
delta*, not silently mutating the system to erase it.

---

## 2. Scope (explicit)

**In scope (repo edits only — live system stays READ-ONLY; introspection is
docker/brew/launchd GETs the framework already does):**

1. A pure-Python drift classifier in `nos_state_lib` that, given the introspected
   services map, returns a structured `drift` list (version / health / presence,
   each with a severity).
2. A new `nos_state` action `reconcile` (read-only) that runs the classifier and
   returns the drift list + a `state` with a persisted `drift:` block.
3. A new `pazny.state_manager` task phase `reconcile.yml` that:
   - persists the `drift:` block into `~/.nos/state.yml`,
   - emits **one A9 notification per drift severity bucket** (best-effort, gated on
     Bone + a new `nos_state_drift_notify` flag, default ON only when `install_bone`),
   - in **gate-mode only** (`nos_state_drift_fail_on: none|version|any`, default
     `none`) fails the play when drift at/above the threshold exists.
4. The drift summary surfaced in the existing `[state] Summary` debug (richer than the
   current per-service line) — replacing the silently-dropped computation with an
   explicit "Drift: N (version: x, health: y, presence: z)" line.
5. **The anatomy gate** (`tests/anatomy/test_state_reconciliation.py`) — the
   non-negotiable.

**Out of scope (do NOT do tonight):**
- **Auto-remediation** of any kind (no `compose up`, no image bump, no restart). The
  classifier *reports*; the operator/`--tags upgrade`/upgrade-advisor *acts*.
- Live A9 wire verification (Bone may be down overnight; the notify task is
  best-effort `failed_when: false` and the gate mocks the emit). The gate proves the
  classifier + payload shape offline.
- Changing introspection itself (`introspect_service` stays as-is — we only *consume*
  its output). No new `version_source` handlers.
- A Wing `/drift` presenter / dashboard view (forward-ready: the `drift:` block + the
  notifications are the data substrate; the view is a follow-up UI item).
- Coexistence-track drift (separate surface; `coexistence.*` has its own active-track
  field — not part of installed-vs-desired).

---

## 3. Approach (exact files + edits)

### 3.1 Drift classifier — `files/anatomy/module_utils/nos_state_lib.py`

Add a pure function (no I/O, no Ansible deps → trivially unit-testable):

```python
# Severity ranks for ordering / thresholding.
DRIFT_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

def classify_drift(services: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Given the introspected services map, return a list of drift records.

    Pure: no docker/network/fs. Consumes only the fields introspect_service
    already populated (installed/desired/healthy/enabled). A service with
    enabled is False, or with insufficient data (installed AND desired both
    None), produces NO record — we never flag a service the operator turned
    off, and never invent drift from missing data.
    """
    drift: List[Dict[str, Any]] = []
    for sid, s in sorted(services.items()):
        if s.get("enabled") is False:
            continue  # operator opted out — not drift
        installed, desired = s.get("installed"), s.get("desired")
        healthy, enabled = s.get("healthy"), s.get("enabled")

        # version drift — both known, and unequal
        if installed and desired and str(installed) != str(desired):
            drift.append({
                "service": sid, "kind": "version",
                "installed": installed, "desired": desired,
                "severity": "high",   # a lagging pin can be a CVE pin
                "detail": f"running {installed}, pinned {desired}",
            })
        # presence drift — asked for, never seen running
        elif enabled is True and installed is None and desired is not None:
            drift.append({
                "service": sid, "kind": "presence",
                "installed": None, "desired": desired,
                "severity": "medium",
                "detail": f"enabled but no running image (pinned {desired})",
            })
        # health drift — asked for, present, but down
        if enabled is True and healthy is False:
            drift.append({
                "service": sid, "kind": "health",
                "installed": installed, "desired": desired,
                "severity": "medium",
                "detail": "enabled but unhealthy/not running",
            })
    return drift


def drift_summary(drift: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts by kind + worst severity rank — for the debug line + gate-mode."""
    out = {"total": len(drift), "version": 0, "health": 0, "presence": 0,
           "worst_rank": 0, "worst_severity": "info"}
    for d in drift:
        out[d["kind"]] = out.get(d["kind"], 0) + 1
        r = DRIFT_SEVERITY_RANK.get(d.get("severity", "info"), 0)
        if r > out["worst_rank"]:
            out["worst_rank"], out["worst_severity"] = r, d["severity"]
    return out
```

Export both from `__all__`. **No new var, no Jinja** — this is module code, so the
stock-Jinja trap is N/A here.

> **Severity rationale:** version drift = `high` because a stale tag is the
> CVE-pin-never-applied case (version-pin-shadow memory). health/presence = `medium`
> (operationally important but not inherently a security exposure). The exact
> floors live in **one** constant map so a reviewer can retune without code surgery,
> and the gate pins them.

### 3.2 New `nos_state` action `reconcile` — `files/anatomy/library/nos_state.py`

Add `reconcile` to the `choices` list and a handler:

```python
def _action_reconcile(module, params):
    """Read state, classify drift, persist a drift: block, return the list.
    READ-ONLY w.r.t. the live system — consumes already-persisted introspection
    output; the only write is the drift: block back into state.yml."""
    state = load_state(params["state_path"])
    services = state.get("services", {}) or {}
    drift = classify_drift(services)
    summary = drift_summary(drift)
    state["drift"] = {
        "checked_at": utcnow_iso(),
        "summary": summary,
        "items": drift,
    }
    # write only when the drift block content changed (ignoring checked_at)
    prior = (load_state(params["state_path"]).get("drift") or {})
    content_changed = (prior.get("items") != drift) or (prior.get("summary") != summary)
    if not module.check_mode:
        dump_state(state, params["state_path"])
    module.exit_json(
        changed=content_changed,
        drift=to_json_safe(drift),
        summary=to_json_safe(summary),
        state=to_json_safe(state),
    )
```

Wire it into the `main()` dispatch + `argument_spec` choices. Import
`classify_drift`/`drift_summary` alongside the existing `nos_state_lib` imports
(both the Ansible-rewritten and the pytest `module_utils.` fallback import blocks —
mirror the existing dual-import exactly).

`changed_when` semantics: the task sets its own `changed_when` (below); the module
reports `changed` only on *content* change (not the volatile `checked_at`), which is
the honest signal for idempotence.

### 3.3 New task phase — `roles/pazny.state_manager/tasks/reconcile.yml`

Runs **after** `persist.yml` (introspection must be in `state.yml` first). Imported
from `main.yml` with `when: nos_state_reconcile | bool`.

```yaml
---
# Reconcile observed-vs-desired: classify drift, persist it, escalate via A9.
# READ-ONLY w.r.t. the live system. Never auto-remediates.

- name: "[state] Classify drift (installed vs desired / health / presence)"
  nos_state:
    action: reconcile
    state_path: "{{ nos_state_file }}"
  register: _nos_drift
  check_mode: false
  changed_when: false        # reporting pass; persisting a drift: block is not a config change
  tags: ['always', 'state', 'reconcile']

- name: "[state] Drift summary"
  ansible.builtin.debug:
    msg: >-
      Drift: {{ _nos_drift.summary.total }}
      (version: {{ _nos_drift.summary.version }},
       health: {{ _nos_drift.summary.health }},
       presence: {{ _nos_drift.summary.presence }})
      worst={{ _nos_drift.summary.worst_severity }}
  tags: ['always', 'state', 'reconcile']

# A9: one notification per drift item, severity-routed. Best-effort — Bone may
# be down on a cold blank; never fail the play on a cache miss.
- name: "[state] Escalate drift to operator (A9 notification)"
  ansible.builtin.uri:
    url: "{{ nos_state_drift_notify_url }}"
    method: POST
    body_format: json
    body:
      severity: "{{ item.severity }}"
      title: "State drift: {{ item.service }} ({{ item.kind }})"
      body: "{{ item.detail }}"
      source: "state-reconcile"
    headers:
      Authorization: "Bearer {{ _state_oidc_token.json.access_token | default('') }}"
    status_code: [200, 201, 202, 204]
    timeout: 5
  loop: "{{ _nos_drift.drift | default([]) }}"
  loop_control: { label: "{{ item.service }}/{{ item.kind }}" }
  when:
    - nos_state_drift_notify | bool
    - _nos_drift.drift | default([]) | length > 0
    - _state_oidc_token.json.access_token is defined
  failed_when: false
  changed_when: false
  no_log: true
  tags: ['state', 'reconcile', 'report']

# GATE-MODE (opt-in, default OFF): fail-loud when drift at/above the threshold
# exists. Lets CI / a supervised run treat drift as a hard error.
- name: "[state] Fail on drift (gate-mode)"
  ansible.builtin.fail:
    msg: >-
      State drift threshold '{{ nos_state_drift_fail_on }}' exceeded:
      {{ _nos_drift.summary.total }} item(s), worst={{ _nos_drift.summary.worst_severity }}.
      Run `ansible-playbook main.yml --tags upgrade -e upgrade_service=<svc>` (supervised)
      or reconverge the service. See ~/.nos/state.yml drift: block.
  when:
    - nos_state_drift_fail_on | default('none') != 'none'
    - _nos_drift.summary.total | int > 0
    - >-
      (nos_state_drift_fail_on == 'any') or
      (nos_state_drift_fail_on == 'version' and _nos_drift.summary.version | int > 0)
  tags: ['state', 'reconcile']
```

The A9 notify reuses the **same `_state_oidc_token`** that `report.yml` already
fetches — so `reconcile.yml` is imported in `main.yml`/`tasks/main.yml` *after*
`report.yml`'s token fetch, OR the token fetch is hoisted. **Decision:** import
`reconcile.yml` from the role's `main.yml` after `report.yml`, and reference the
token only inside the `when:` guard (already done — guarded on
`_state_oidc_token.json.access_token is defined`, so it no-ops when the token wasn't
fetched). This keeps the change additive and avoids reordering `report.yml`.

### 3.4 Wire into the role — `roles/pazny.state_manager/tasks/main.yml`

Add after the `report.yml` import:

```yaml
- name: Reconcile drift (observed vs desired)
  ansible.builtin.import_tasks: reconcile.yml
  when: nos_state_reconcile | bool
  tags: ['always', 'state', 'reconcile']
```

### 3.5 New defaults — `roles/pazny.state_manager/defaults/main.yml`

```yaml
# Reconciliation: classify observed-vs-desired drift, persist + escalate.
# Read-only — NEVER auto-remediates. Default ON (cheap, pure-Python).
nos_state_reconcile: true

# Emit one A9 notification per drift item. Default tracks Bone availability
# (no Bone → nothing to notify). Best-effort regardless.
nos_state_drift_notify: "{{ install_bone | default(false) }}"
nos_state_drift_notify_url: "http://localhost:{{ bone_port | default(8099) }}/api/v1/notifications"

# Gate-mode: fail the play on drift. none | version | any. Default none
# (report-only). CI / supervised runs can set 'version' to treat a lagging
# pin as a hard error.
nos_state_drift_fail_on: "none"
```

These are **role defaults**, not `default.config.yml` vars. The stock-Jinja
"resolves-before-core-up" trap applies only to vars that land in the `{{ vars }}`
loader namespace *before* core-up — these are state_manager role defaults consumed in
`post_tasks` (well after core-up), so the trap doesn't bite (same class as the
existing `nos_state_push_bone` default). All use stock filters (`default`) only.

> **Belt-and-suspenders:** the gate (§4) includes a static check that every new
> default uses stock Jinja filters, mirroring `test_config_stock_jinja_only.py`'s
> rule, so the trap can't sneak in via a future edit.

---

## 4. The gate (NON-NEGOTIABLE — every fix ships a gate)

New file: **`tests/anatomy/test_state_reconciliation.py`** — offline, fast, no
network, no live system. Imports `classify_drift` / `drift_summary` directly from
`module_utils.nos_state_lib` (the existing nos_state tests already import the lib this
way; add the repo `files/anatomy` to `sys.path` per the established conftest pattern).

Tests:

1. `test_version_drift_flagged_high` — `{installed:"11.2.0", desired:"11.5.0",
   enabled:True}` → one `version` record, `severity == "high"`,
   `installed`/`desired` carried through.
2. `test_matching_version_is_clean` — `installed == desired` → empty drift list.
3. `test_disabled_service_never_drifts` — `enabled:False` with any installed/desired
   mismatch → **no** record (operator opt-out is not drift).
4. `test_presence_drift_when_enabled_but_missing` — `enabled:True, installed:None,
   desired:"x"` → one `presence` record, `medium`.
5. `test_health_drift_when_enabled_but_unhealthy` — `enabled:True, healthy:False` →
   a `health` record (`medium`); and combined with a version mismatch yields **both**
   a version and a health record (independent axes).
6. `test_insufficient_data_no_phantom_drift` — `installed:None, desired:None` → no
   record (never invent drift from missing introspection).
7. `test_summary_counts_and_worst_severity` — a mixed list → `drift_summary` returns
   correct per-kind counts + `worst_severity == "high"` (version present).
8. `test_severity_floors_pinned` — assert the `DRIFT_SEVERITY_RANK` map + the
   per-kind floors (version=high, health=medium, presence=medium) match the spec, so
   a silent retune of a floor fails the gate (the floors are a contract).
9. `test_reconcile_action_persists_drift_block` — invoke the module's `reconcile`
   handler against a temp `state.yml` seeded with a drifted service (call the handler
   logic directly or via a thin `run_module` harness like the other nos_state tests);
   assert a `drift:` block with `summary` + `items` is written and `changed` is True;
   re-run → `changed` False (content-idempotent, ignoring `checked_at`).
10. `test_reconcile_action_is_read_only_to_live` — assert `classify_drift` /
    `drift_summary` perform no subprocess/network/docker calls (no `subprocess`,
    `socket`, `requests` imports invoked — monkeypatch-guard or AST-assert the
    functions reference none), pinning the read-only contract.
11. `test_new_state_manager_defaults_stock_jinja` — parse
    `roles/pazny.state_manager/defaults/main.yml`; the four new keys exist and any
    `{{ … }}` they contain uses only stock filters (`default`) — mirrors the
    stock-Jinja rule for the role-default surface.
12. `test_reconcile_task_is_read_only_and_guarded` — parse
    `roles/pazny.state_manager/tasks/reconcile.yml`; assert it contains **no**
    `command`/`shell`/`docker`/`compose up`/`fail`-without-guard mutation: the only
    `uri` is the notification POST (best-effort `failed_when: false`), and the `fail`
    task is guarded by `nos_state_drift_fail_on != 'none'`. Pins the "reports, never
    remediates" contract at the task level.

Each test carries a surgeon-tone docstring naming the contract it pins.

**Why a gate and not just a fix:** the classifier *is* the fix — its correctness (what
counts as drift, what severity, what is deliberately *not* drift) is exactly what can
silently rot. Tests 3/6/10/12 pin the safety invariants (no phantom drift, opt-out
respected, read-only, never auto-remediate) that make this unsupervised-safe; 1/4/5/8
pin the detection + severity contract; 9/11 pin persistence + the var-trap guard.

---

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Accidental auto-remediation creep** — a future edit "closes" drift by mutating the system | low | Gate tests 10 + 12 hard-pin read-only at both the function and task level. The task phase has zero `command`/`shell`/`compose`; the `fail` task only *reports*. Doctrine (`feedback-destructive-op-safety.md`) cited inline. |
| **False-positive drift floods A9** (e.g. launchd `installed:"loaded"` vs a version `desired`) | medium | `classify_drift` only flags version drift when **both** `installed` and `desired` are real strings *and unequal*; launchd's `installed` token (`"loaded"`) has no `desired` version_var in practice → no record. Test 6 + 2 pin "no phantom drift." If a launchd service does carry a version_var, that's genuine drift worth one notification. |
| **A9 notify spam on a multi-drift run** | low | One notification per drift item, severity-routed (A9's own dedup/inbox handles repeats). Best-effort + `no_log`. If volume is a concern, a follow-up can roll up to one digest notification per severity bucket — noted in §6, not blocking. |
| **`reconcile` runs before introspection populated state** | low | `reconcile.yml` is imported **after** `persist.yml` in the role; it reads `state.yml`'s `services` map (already written by persist). Empty/partial services → empty drift, not an error (`classify_drift` tolerates missing fields). |
| **Gate-mode (`fail_on`) breaks an existing green run** | none (default off) | Default `nos_state_drift_fail_on: none` — pure report-only out of the box. A run only fails if the operator/CI opts in. The CI integration wet-test keeps the default, so it stays green. |
| **Stock-Jinja vars trap** | N/A → pinned | New keys are **role defaults** (consumed post-core-up), not `default.config.yml`. They use only `default`. Test 11 pins it anyway. |
| **`changed=true` churn breaks the macOS idempotence (`changed=0`) CI re-run** | low | Module reports `changed` only on drift-*content* change (not `checked_at`); the task sets `changed_when: false` on the reconcile + notify + summary steps. A steady-state second run is `changed=0`. Test 9 pins content-idempotence. |

---

## 6. Deferred (explicitly NOT this item)

- **Auto-remediation / self-healing** (apply the pinned version when drift detected) —
  deliberately excluded: that is the supervised `--tags upgrade` path + the upgrade
  engine's backup/rollback machinery, gated behind operator confirmation
  (`feedback-destructive-op-safety.md`). The conductor / upgrade-advisor agent can
  *propose* from the `drift:` block on-demand; it must not auto-apply.
- **Wing `/drift` presenter + dashboard widget** — the `drift:` block in `state.yml`
  + the A9 notifications are the data substrate; the read-model UI (a `DriftPresenter`
  + Latte view, mirroring the migrations/upgrades views in `framework-plan.md` §6) is
  a follow-up. Forward-ready, not built tonight.
- **Digest roll-up** (one notification per severity bucket instead of per item) — a
  noise-tuning refinement; ship per-item first, observe, roll up if needed.
- **Coexistence-track drift** (active-track vs expected) — separate surface
  (`coexistence.*`), separate classifier; not installed-vs-desired.
- **Live upstream "is the pin itself stale" check** — network-bound, the
  upgrade-advisor agent's on-demand job; this item compares *running* vs *pinned*,
  not *pinned* vs *upstream-latest*.
- **Pulse-scheduled standalone drift sweep** (like `drift-watch.sh` for CVEs) — once
  the classifier exists, a thin `state-drift-watch.sh` Pulse job could refresh the
  `drift:` block + notify between playbook runs. Natural follow-up; not tonight.

---

## 7. Verification recipe

All offline, no live system, no network — safe for unsupervised run:

```bash
cd /Users/pazny/projects/nOS

# 1. The new gate passes (and prove it actually catches drift: run BEFORE wiring
#    classify_drift to confirm the import fails / tests are red, then after).
python3 -m pytest tests/anatomy/test_state_reconciliation.py -v

# 2. Existing state + config + notification gates stay green (no regression to the
#    shared nos_state_lib surface or the A9 path).
python3 -m pytest \
  tests/anatomy/test_a9_run_state_notifications.py \
  tests/anatomy/test_notification_fanout.py \
  tests/anatomy/test_config_stock_jinja_only.py -q

# 3. Full anatomy suite stays green.
python3 -m pytest tests/anatomy/ -q

# 4. Playbook syntax-check clean (the new reconcile.yml import + module action
#    choice must not break parse).
ansible-playbook main.yml --syntax-check

# 5. Module smoke (offline): the new action classifies a seeded drift state.
python3 - <<'PY'
import sys; sys.path.insert(0, "files/anatomy")
from module_utils.nos_state_lib import classify_drift, drift_summary
svcs = {
  "grafana": {"installed": "11.2.0", "desired": "11.5.0", "enabled": True, "healthy": True},
  "loki":    {"installed": "3.0.0",  "desired": "3.0.0",  "enabled": True, "healthy": True},
  "n8n":     {"installed": None,      "desired": "1.2.3",  "enabled": True, "healthy": None},
  "kiwix":   {"installed": "old",     "desired": "new",    "enabled": False, "healthy": True},
}
d = classify_drift(svcs); print(d); print(drift_summary(d))
# expect: grafana version(high), n8n presence(medium); kiwix SKIPPED (disabled);
#         loki clean. summary worst_severity == "high".
PY
```

Expected: gate #1 RED before §3 (import error / failing assertions, proving it
catches the gap), GREEN after; #2–#4 GREEN throughout; #5 prints exactly the grafana
version-drift + n8n presence-drift records, kiwix skipped, loki clean,
`worst_severity == "high"`.

---

## 8. Commit shape (when implemented — separate from this plan commit)

```
feat(state): reconcile observed-vs-desired drift

- introspection computed installed/desired/healthy then dropped it in a
  debug line — drift never asserted, never escalated.
- nos_state_lib.classify_drift + new reconcile action persist a drift:
  block (version=high / health+presence=medium); read-only, never remediates.
- state_manager reconcile.yml escalates each item via A9 (best-effort) +
  opt-in gate-mode (nos_state_drift_fail_on); default report-only.
- gate: test_state_reconciliation pins detection, severity floors,
  no-phantom-drift, read-only + never-remediate contracts.
```

(Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`, branch-only — never pushed.)
