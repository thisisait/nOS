# Plan — v0.7 SEC: remediation-queue pending-14 triage + burn-down

**Status:** PLAN (not implemented). Review-ready. Target branch: `feat/v0.7-overnight`.
**Authoritative source:** `docs/llm/security/remediation-queue.json`
**Scope:** the **14 items requiring manual review** — `status:pending` (12) + `status:vendor-blocked` (2). This is the **umbrella** that classifies every one, routes each to a fix lane, and adds the cross-cutting gates that keep the count honest. Per-item deep-dive plans that already exist are linked, not duplicated.

---

## 1. Problem / why

`remediation-queue.json` is the live security backlog. Its own `summary` block claims `manual_review_required: 14` and `pending: 13`, but a recompute from `items[]` shows **12 pending + 2 vendor-blocked**. The drift between the cached `summary` and the real `items[]` is itself a defect (see §6, finding D). Until each of the 14 has either a shipped fix, a gated mitigation, or an explicitly accepted-risk record, the overnight CVE-drift hook (`hooks/playbook-end.d/20-cve-drift-check.sh`) keeps emitting a non-zero `nos_security_pending_*` gauge with no machine-readable why.

This plan does **not** try to resolve all 14 in one branch. It establishes the **triage contract**: each item lands in exactly one of four lanes, each lane has a definition-of-done and a gate, and nothing can silently regress (a newly-pending CRITICAL must fail a test, an accepted-risk item must carry a structured justification).

### The 14 items (recomputed live from `items[]`, 2026-06-14)

| ID | Component | Sev | Type | auto_fix | Lane | Routing |
|----|-----------|-----|------|----------|------|---------|
| REM-002 | woodpecker | CRITICAL | config_change | no | **B** mitigated, residual | rootless-agent eval; see existing `v07-sec-docker-socket-proxy-enabled.md` is adjacent, not the same |
| REM-004 | multiple | HIGH | version_bump | yes | **A** verify-resolved | 23-image pin sweep already done by C1; reconcile + close |
| REM-008 | erpnext | MEDIUM | config_change | yes | **C** deferred (service OFF) | acceptance-criterion of the ERPNext rework; structured deferral |
| REM-024 | ollama | HIGH | version_bump | yes | **B** mitigated, residual | host brew `state:latest` floats past fix; add `OLLAMA_HOST=127.0.0.1` bind gate |
| REM-035 | nginx | MEDIUM | version_bump | yes | **C** not-applicable | host package, no repo pin; DAV/MP4 modules unused; structured accept |
| REM-037 | uptime_kuma | MEDIUM | version_bump | yes | **A→merge** | superseded by REM-073; merge/cross-ref, close as dup-of |
| REM-044 | uptime_kuma | HIGH | config_change | no | **C** accept-with-doc | admin-only SSRF = tool's core function; net-isolate or accept |
| REM-059 | rustfs | MEDIUM | upstream_patch | no | **C** vendor-track | non-constant-time RPC compare; upstream-fix-track + net-isolate note |
| REM-063 | nginx | HIGH | version_bump | yes | **C** not-applicable | same as REM-035; affected modules not enabled |
| REM-064 | openwebui | HIGH | version_bump | no | **B** mitigated | admin-gated RCE; pin-freshness + admin-trust doc; see `v07-sec-openwebui-code-interpreter-pyodide-pinned.md` |
| REM-073 | uptime_kuma | HIGH | version_bump | no | **D** plan-exists | SSTI bypass; deep plan `v07-sec-uptime-kuma-ssti-pending.md` (v2 breaking migration) |
| REM-074 | calibreweb | HIGH | workaround | no | **B** mitigated | ReDoS on /login; behind forward-auth; rate-limit + fork-migration note |
| REM-014 | freepbx | CRITICAL | version_bump | no | **D** plan-exists | vendor-blocked; gate `v07-sec-freepbx-vendor-blocked-critical.md` |
| REM-046 | freepbx | CRITICAL | version_bump | no | **D** plan-exists | vendor-blocked; same plan as REM-014 |

**Four lanes:**
- **A — verify-resolved / merge:** the fix is *already in the repo* or the item is a duplicate of one tracked elsewhere; this plan only RECONCILES the queue status + adds a freshness/dup gate. (REM-004, REM-037)
- **B — mitigated, residual hardening:** real exposure is reduced by an existing control (forward-auth, admin-gating, host-floats-to-latest); a small in-repo hardening + a gate closes it. (REM-002, REM-024, REM-064, REM-074)
- **C — accept-with-doc / not-applicable:** no in-repo fix is possible or warranted (host package, disabled service, tool-by-design); convert the prose `decision`/review note into a **structured, gated `accepted_risk` record**. (REM-008, REM-035, REM-044, REM-059, REM-063)
- **D — has a dedicated plan already:** do not re-spec; this umbrella only cross-links and ensures the dedicated plan's gate is wired into the queue-consistency check. (REM-014, REM-046, REM-073)

---

## 2. Exact files / roles to touch

### 2a. Queue schema + reconciliation (the spine of this plan)
- `docs/llm/security/remediation-queue.json` — for each of the 14: either flip `status` (A-lane verified-resolved) or add a **structured** `accepted_risk` object (C-lane) replacing free-text `decision`/review-note prose. Recompute the `summary` block so `pending`/`manual_review_required` match `items[]`.
- **New schema field** `accepted_risk` (C-lane only):
  ```json
  "accepted_risk": {
    "decided_at": "2026-06-..T..Z",
    "decided_by": "operator",
    "rationale": "host package, no repo-pinnable tag; affected modules unused",
    "compensating_controls": ["forward_auth gate", "module not enabled in vhost templates"],
    "review_by": "2026-09-..",            // re-review horizon (quarterly)
    "residual_severity": "LOW"
  }
  ```

### 2b. Lane-B in-repo hardening (small, gated)
- **REM-024 (ollama bind):** `roles/pazny.openclaw/tasks/main.yml` — add `OLLAMA_HOST=127.0.0.1:11434` to the launchd/systemd env map (it sets `OLLAMA_*` vars already at lines ~24-30). New default `ollama_bind_host: "127.0.0.1:11434"` in `default.config.yml` (stock-Jinja, real default — see §5).
- **REM-074 (calibre /login ReDoS):** Calibre-Web is forward-auth-gated (login not reachable pre-SSO), so the *active* mitigation is already in place. In-repo add: a `limit_req` zone on the calibre vhost **only on the host-nginx opt-in path** (`templates/nginx/sites-available/calibre*.conf` if present) — Traefik path is gated by Authentik so no rate-limit needed. If no calibre vhost template exists, this is **doc-only** (accept-with-doc, lane C) — verify in implementation.
- **REM-064 (openwebui admin-RCE):** no version bump available; the residual control is "tool creation is admin-gated". In-repo: confirm `open_webui` env does not enable anonymous tool upload; cross-link the existing pyodide-pin plan. Likely **doc + gate only**.
- **REM-002 (woodpecker):** already has `WOODPECKER_OPEN=false`, `WOODPECKER_REPO_OWNERS`, `WOODPECKER_AUTHENTICATE_PUBLIC_REPOS=false`. Residual = rootless agent backend — that is a **lane-D-style sub-plan** (out of scope to *implement*; record as residual with a tracking note).

### 2c. Gates (new pytest anatomy tests)
- `tests/anatomy/test_remediation_queue_consistency.py` — **NEW** (the load-bearing gate; see §5).
- Optionally extend `tests/anatomy/test_version_pin_no_shadow.py` if REM-004 reconciliation touches any shadowed pin (it should not — C1 already reconciled the sweep).

### 2d. Drift-hook bug fix (finding D)
- `hooks/playbook-end.d/20-cve-drift-check.sh` line ~93: `applied_total` selects `status == "applied"`, but the queue vocabulary is `resolved`. Fix the jq selector to `resolved` (or add both) so the Prometheus/Wing `applied_total` gauge stops reading 0. Gate it in the new consistency test (assert the hook's status vocabulary matches the queue's actual status set).

### 2e. Docs
- This file. Plus a one-line pointer appended under "Known Tech Debt → Security remediation backlog" in `CLAUDE.md` once implemented (NOT in this PLAN commit).

---

## 3. Approach (per lane)

**Lane A (REM-004, REM-037):** Read each cited fix site (e.g. for REM-004, the 23 image pins in `default.config.yml` / role defaults the C1 sweep landed; for REM-037, confirm REM-073 supersedes it). Flip `status:resolved` with a `resolved_by` that names the exact pin line + commit, OR add `superseded_by:"REM-073"`. **No new runtime code** — pure queue reconciliation, but each closure must cite a *grep-able* repo fact, never "trust me".

**Lane B (REM-024, REM-064, REM-074, REM-002):** Land the smallest reversible in-repo control that measurably reduces residual exposure, gate it, then downgrade the item to `resolved` with `residual_severity` recorded. The ollama bind is the only one with a concrete config edit; the rest are confirm-existing-control + structured-residual.

**Lane C (REM-008, REM-035, REM-044, REM-059, REM-063):** Convert the existing free-text `decision`/review prose into the structured `accepted_risk` object (§2a). This is the key change — an auditor (or the A8 conductor) can then machine-read *why* a pending item is acceptable and *when* it must be re-reviewed, instead of parsing English. Status moves `pending → accepted_risk` (new terminal status) OR stays `pending` with the `accepted_risk` block attached (decide in review — see Risks §4). Recommendation: **new terminal status `accepted-risk`** so the drift hook can exclude it from `pending_*` gauges.

**Lane D (REM-014, REM-046, REM-073):** No spec work. Add `tracked_by:"docs/plans/v07-sec-…md"` to each item so the queue points at its plan; ensure the consistency gate (§5) asserts that every item whose plan exists actually references it.

---

## 4. Risks

1. **Status-vocabulary expansion.** Adding `accepted-risk` as a terminal status touches every consumer of `status`: the drift hook (§2d), `tools/plugin-wiring-report.py`-style readers, any Wing ingest of the queue, and the summary recompute. **Mitigation:** the consistency gate enumerates the allowed status set and every consumer is grepped for hard-coded `"pending"`/`"resolved"` string comparisons before merge. If expansion is too invasive, fall back to `status:pending` + `accepted_risk` block and teach ONLY the drift hook to subtract items-with-`accepted_risk` from the pending gauges.
2. **Lane-A false-close.** Flipping an item to `resolved` without the fix truly in the running image is exactly the dead-pin trap (memory `version-pins-default-config-shadow`). **Mitigation:** every lane-A `resolved_by` must cite a line that `test_version_pin_no_shadow.py` already validates; the consistency gate cross-checks that a `version_bump` item marked resolved names a `*_version` var that exists and is not shadowed.
3. **REM-024 bind breaks OpenClaw/Hermes/Open WebUI → Ollama.** Pinning `OLLAMA_HOST=127.0.0.1` could break a container that reaches Ollama over the host bridge. **Mitigation:** audit who connects to Ollama (Open WebUI runs in a container → needs `host.docker.internal` or the bridge IP, NOT loopback). The bind must stay reachable by legitimate clients; verify before changing the default. If containers need it, the correct bind is the docker-bridge gateway, not `127.0.0.1` — re-scope to a firewall/`pf` note instead. **This is the single highest-risk edit in the plan; gate it behind a connectivity check in the verification recipe.**
4. **No live mutation.** All edits are repo-only (queue JSON, role defaults, a vhost template, a pytest, a hook script). Zero live-system writes; overnight-safe.
5. **Overlap with existing plans.** REM-073/014/046/064 already have dedicated plans. **Mitigation:** this umbrella is explicitly cross-link-only for those (lane D / B-link); no duplicate spec.

---

## 5. Gates it needs

**Primary gate — `tests/anatomy/test_remediation_queue_consistency.py` (NEW):**
1. `test_summary_matches_items` — recompute `by_status` / `pending` / `manual_review_required` from `items[]`; assert the cached `summary` block agrees (closes finding D / the 14-vs-13 drift).
2. `test_status_vocabulary_closed` — every `items[].status` ∈ `{resolved, pending, vendor-blocked, accepted-risk}`; no typos, no new statuses without updating the allowlist.
3. `test_pending_items_have_routing` — every `pending`/`vendor-blocked` item carries EITHER `accepted_risk`, `tracked_by` (a real file under `docs/plans/`), or a `decision` string; no silently-orphaned pending item.
4. `test_accepted_risk_shape` — any `accepted_risk` block has all required keys (`decided_at`, `rationale`, `compensating_controls`, `review_by`, `residual_severity`) and `review_by` parses as a date.
5. `test_resolved_version_bumps_cite_a_real_pin` — for `remediation_type:version_bump` + `status:resolved`, the `resolved_by` text names a `*_version` var that actually exists in `default.config.yml` or a role default (catches lane-A false-close + dead pins).
6. `test_tracked_by_points_at_existing_plan` — every `tracked_by` path exists on disk (lane-D items don't dangle).
7. `test_drift_hook_status_vocab_in_sync` — parse `20-cve-drift-check.sh`; assert the status strings it selects on (`pending`, `resolved`) are a subset of the queue's actual status set (catches the `applied` bug + future drift).

**Existing gates that must stay green:** `test_version_pin_no_shadow.py`, `test_postgresql_version_pin.py`, `test_mariadb_cve_citation_sync.py`, the full `tests/anatomy/` suite.

**Stock-Jinja gate:** the only new `default.config.yml` var is `ollama_bind_host: "127.0.0.1:11434"` — a plain string literal, stock filters only, real default. Passes `test_config_stock_jinja_only.py` by construction. (If REM-074 adds a `calibre_login_rate_limit` var, same constraint.)

**Syntax:** `ansible-playbook main.yml --syntax-check` must stay clean (the ollama env edit is a list-item, low blast radius).

---

## 6. Verification recipe

```bash
# 0. Branch (already on feat/v0.7-overnight)
git rev-parse --abbrev-ref HEAD            # feat/v0.7-overnight

# 1. The live count this plan is built on (must read 12 pending + 2 vendor-blocked = 14)
python3 -c "import json,collections; d=json.load(open('docs/llm/security/remediation-queue.json')); \
print(collections.Counter(i['status'] for i in d['items']))"

# 2. New + existing anatomy gates green
python3 -m pytest tests/anatomy/test_remediation_queue_consistency.py \
                  tests/anatomy/test_version_pin_no_shadow.py -q

# 3. Whole anatomy suite still green
python3 -m pytest tests/anatomy/ -q

# 4. Playbook still parses
ansible-playbook main.yml --syntax-check

# 5. Drift hook now emits correct counts (resolved_total non-zero, pending matches §1)
NOS_REPO="$(pwd)" bash hooks/playbook-end.d/20-cve-drift-check.sh | python3 -m json.tool

# 6. REM-024 connectivity guard (READ-ONLY — do NOT change live env):
#    confirm who actually talks to Ollama before pinning the bind.
docker ps --format '{{.Names}}' | grep -i 'open.webui\|openwebui' || echo "no openwebui container"
#    If a container reaches Ollama, the bind MUST be the bridge gateway, not 127.0.0.1.
#    Verify the host's current Ollama bind (read-only):
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:11434/api/version || echo "ollama not reachable on loopback"

# 7. accepted_risk blocks parse + carry a review horizon
python3 -c "import json; d=json.load(open('docs/llm/security/remediation-queue.json')); \
[print(i['id'], i['accepted_risk']['review_by']) for i in d['items'] if 'accepted_risk' in i]"
```

**Definition of done for the umbrella (not all items resolved — the *triage* is complete):**
- Every one of the 14 has a lane + a machine-readable routing (`resolved` / `accepted_risk` / `tracked_by`).
- `summary` recomputes to match `items[]` (no more 14-vs-13 drift).
- The drift hook reads the correct status vocabulary.
- The consistency gate is green and pins all of the above.
- Lane-B in-repo edits (ollama bind iff connectivity-safe; calibre rate-limit iff a vhost template exists) shipped + gated, or explicitly downgraded to lane-C with a recorded reason.

---

## 7. Out of scope (explicit)

- Implementing the woodpecker rootless-agent backend (REM-002 residual) — separate spike.
- The uptime-kuma v1→v2 breaking migration (REM-073) — owned by `v07-sec-uptime-kuma-ssti-pending.md`.
- FreePBX vendor-block gating (REM-014/046) — owned by `v07-sec-freepbx-vendor-blocked-critical.md`.
- Any live-system mutation, image re-pull, or container recreate. Repo-only.
