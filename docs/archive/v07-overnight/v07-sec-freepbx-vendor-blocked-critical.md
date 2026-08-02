# Plan — FreePBX vendor-blocked CRITICAL CVEs: gate the role-load behind explicit risk-acceptance

- **Item:** REM-014 (CVE-2025-57819, CVSS 10.0) + REM-046 (CVE-2025-66039 / 61675 / 61678 auth-bypass→SQLi→RCE chain) — both `status: vendor-blocked`.
- **Branch:** `feat/v0.7-overnight`
- **Type:** repo-only (defaults + role guard + docs + anatomy gate). No live mutation. Status: PLAN — do **not** implement under this prompt.
- **Author note:** review-ready; every code change ships with a pytest anatomy gate and keeps `--syntax-check` clean.

---

## 1. Problem / why

`tiredofit/freepbx` is the only Docker image nOS ships for the `voip` stack (FreePBX + Asterisk). The image was **last updated 2022-04-30**; its newest published tag is `5.2.0` (2022). Two confirmed CRITICAL CVE clusters are **UNFIXABLE in this image** because there is no maintained ARM64 FOSS rebuild:

- **REM-014 / CVE-2025-57819** — actively-exploited zero-day, CVSS 10.0; 900+ instances compromised in the wild. Fixed only in upstream FreePBX `16.0.89+`.
- **REM-046 / CVE-2025-66039+61675+61678** — webserver auth bypass (forged `Authorization` header) → authenticated SQLi → file-upload RCE via directory traversal. Public exploit code exists (`github.com/BimBoxH4`). Fixed only in `16.0.92 / 17.0.6 / 17.0.23`.

Today the only protection is **documentation**: `freepbx_version: "latest"` carries an inline ⚠️ comment in `default.config.yml`, `profiles/all-on.yml` excludes it, `profiles/gov-local.yml` forces it off, and `install_freepbx` defaults to `false`. **Nothing in the playbook stops an operator from flipping `install_freepbx: true` and standing up a remotely-exploitable PBX with zero friction.** The role renders and brings the container up exactly like any healthy service.

The defaults already do the right *network* things — the Web UI binds `127.0.0.1:8088:80`, SIP/IAX/RTP bind loopback unless `freepbx_lan_access`/`services_lan_access` is set, Fail2Ban is on. But loopback binding is **not** a mitigation once the operator (the expected use case) exposes it via Traefik or LAN VoIP; the CVE chain is reachable from any client that can reach the Web UI / SIP surface. The correct posture for an unfixable-CRITICAL service is the same one ERPNext already uses for its instability: **refuse to render unless the operator explicitly acknowledges the risk in config**, so enabling it is a conscious, audited choice rather than a one-line toggle.

**Goal:** make FreePBX enablement require a second, intent-revealing opt-in flag whose name states the risk, fail closed with a CVE-citing message otherwise, surface the acceptance in the service registry / state, and pin the whole behaviour with an anatomy gate. This is a *risk-gate*, not a fix — the CVEs stay vendor-blocked; we are closing the "accidental exposure" gap.

---

## 2. Precedent we mirror (do not reinvent)

`roles/pazny.erpnext/tasks/main.yml` already implements the exact shape — a hard guard that `ansible.builtin.fail`s unless `erpnext_experimental_override: true`:

```yaml
- name: "[pazny.erpnext] Hard guard — refuse to render unless experimental override is set"
  ansible.builtin.fail:
    msg: |- ...
  when: not (erpnext_experimental_override | default(false) | bool)
```

We replicate the structure but:
1. The variable name encodes **risk-acceptance**, not "experimental": `freepbx_accept_critical_cve_risk` (reads as a sentence at the call site).
2. The `fail` message **cites the CVE IDs + REM IDs** and points at the remediation queue, so the operator sees *why* it is gated.
3. The guard runs as the **first task** in the role, before the data-dir creation and the compose render, so a blocked run produces zero side effects (no dirs, no override file).

---

## 3. Exact files / roles to touch

| # | File | Change |
|---|------|--------|
| 1 | `roles/pazny.freepbx/tasks/main.yml` | Prepend a hard-guard `ansible.builtin.fail` task gated on `not (freepbx_accept_critical_cve_risk | default(false) | bool)`. CVE/REM-citing message. Runs before data-dir + render. |
| 2 | `roles/pazny.freepbx/defaults/main.yml` | Add `freepbx_accept_critical_cve_risk: false` with a comment pointing at REM-014/046. (Role default is fine here — the var is only read inside the role's own `when:`, never in the `{{ vars }}` core-up eager-resolve namespace; see §6 risk note.) |
| 3 | `default.config.yml` | Add `freepbx_accept_critical_cve_risk: false` next to the existing `freepbx_*` block (~line 1884), so it is documented in the committed config surface and survives the stock-Jinja "every-ref-resolves-before-core-up" gate with a real default. Keep/refresh the existing ⚠️ comment, add a one-liner pointing at the new flag. |
| 4 | `roles/pazny.freepbx/README.md` | Document the gate: what the flag is, the CVE list, the loopback-binding caveat, and the explicit "you accept the risk" sentence. Mirror the ERPNext README tone (`> freepbx_accept_critical_cve_risk: true   # acknowledge unfixable CRITICAL CVEs`). |
| 5 | `tests/anatomy/test_freepbx_cve_risk_gate.py` | **NEW** anatomy gate (see §5). |
| 6 | `docs/llm/security/remediation-queue.json` | Append a `risk_gate` note to REM-014 + REM-046 `blocked_reason` (or a new field `mitigation`) recording that role-load is now gated behind explicit acceptance. **JSON-only edit — keep it valid + the file's existing key ordering.** Status stays `vendor-blocked` (the CVEs are not fixed; only the accidental-exposure path is closed). |
| 7 | `docs/security-baseline.md` *(if it has a "risk-accepted services" section — verify; the file exists per CLAUDE.md but grep returned no freepbx hits)* | Add a short "Risk-accepted / vendor-blocked services" subsection naming FreePBX, the flag, and the CVEs. Optional but recommended for operator discoverability. |

**Explicitly NOT touched:**
- `state/manifest.yml` freepbx block — no schema change needed for the gate itself. *(Optional stretch, §7: a `risk_gated: true` advisory field if the manifest schema permits it — but only if a manifest-consumer reads it; otherwise it is dead metadata and we skip it.)*
- `tasks/stacks/stack-up.yml` — the existing `when: install_freepbx | default(false)` include stays. The guard lives **inside** the role so it fires only when the operator already asked for FreePBX, giving a precise, contextual failure rather than a silent skip.
- Compose template, ports, networks, Fail2Ban, loopback bindings — all unchanged (already correct).

---

## 4. Approach (step by step)

1. **Role default** (`defaults/main.yml`): add
   ```yaml
   # ⚠️  UNFIXABLE CRITICAL CVEs (REM-014 CVE-2025-57819 CVSS 10.0; REM-046
   # CVE-2025-66039/61675/61678 auth-bypass→SQLi→RCE). tiredofit/freepbx image
   # abandoned upstream 2022-04-30. Enabling FreePBX requires explicit opt-in.
   freepbx_accept_critical_cve_risk: false
   ```

2. **Hard guard** (`tasks/main.yml`), as the **first** task:
   ```yaml
   - name: "[pazny.freepbx] Hard guard — refuse to render unless CVE risk is explicitly accepted"
     ansible.builtin.fail:
       msg: |-
         FreePBX is gated: the only available image (tiredofit/freepbx, abandoned
         upstream 2022-04-30) carries UNFIXABLE CRITICAL CVEs:
           - REM-014 / CVE-2025-57819 (CVSS 10.0, actively exploited)
           - REM-046 / CVE-2025-66039+61675+61678 (auth-bypass → SQLi → RCE)
         No maintained ARM64 FOSS alternative exists. To stand it up anyway you must
         accept the risk: set `freepbx_accept_critical_cve_risk: true` in config.yml.
         See docs/llm/security/remediation-queue.json (REM-014/046).
     when: not (freepbx_accept_critical_cve_risk | default(false) | bool)
   ```

3. **Committed config surface** (`default.config.yml`): add `freepbx_accept_critical_cve_risk: false` in the `freepbx_*` block so the flag is part of the documented, committed config (and has a real default before core-up — satisfies the stock-Jinja gate). Stock filters only (`| default(false) | bool`).

4. **README** + **security-baseline** doc updates — operator-facing, English (Documentation Language rule).

5. **Remediation-queue note** — append a `mitigation` line to REM-014/046 so the security paper-trail records the gate; **status unchanged** (`vendor-blocked`). Validate the JSON parses after the edit.

6. **Anatomy gate** (§5) — pin every load-bearing fact so the gate cannot silently regress.

7. **Verify** — run the new gate + the full anatomy suite + `--syntax-check` (§ verification recipe).

---

## 5. The gate (`tests/anatomy/test_freepbx_cve_risk_gate.py`)

Offline, repo-only, fast — no live system, no Ansible run. Mirrors the existing `test_security_file_modes.py` / config-assert style (parse the repo files, assert structural facts). Cases:

- **`test_role_default_is_locked_false`** — `roles/pazny.freepbx/defaults/main.yml` defines `freepbx_accept_critical_cve_risk: false` (parse YAML, assert key present + value is `False`). Fail-closed default is the whole point.
- **`test_committed_config_has_real_default`** — `default.config.yml` defines `freepbx_accept_critical_cve_risk` with a `false`/`False` literal (real default before core-up; defends the stock-Jinja "every-ref-resolves" invariant for this var if it ever migrates into the eager-resolve namespace).
- **`test_guard_task_is_first_and_fails_closed`** — load `roles/pazny.freepbx/tasks/main.yml` as YAML; assert the **first** task is an `ansible.builtin.fail` whose `when` is `not (freepbx_accept_critical_cve_risk | default(false) | bool)` (string-normalize whitespace). Guarantees zero side effects on a blocked run.
- **`test_guard_message_cites_cves`** — the `fail.msg` mentions both `REM-014` and `REM-046` **and** the CVE IDs (`CVE-2025-57819`, `CVE-2025-66039`). Keeps the operator-facing message honest if someone reword-drifts it.
- **`test_remediation_queue_still_vendor_blocked`** — `docs/llm/security/remediation-queue.json` parses as JSON and REM-014 + REM-046 still have `status == "vendor-blocked"` (the gate is *not* a fix; this catches an accidental status flip to "resolved").
- **`test_default_install_flag_off`** — `install_freepbx` default is `false` in `default.config.yml` (belt-and-suspenders: the service is off by default, and even when on it is gated).

All assertions read committed files via `pathlib` + `yaml.safe_load` / `json.load` against `REPO = Path(__file__).resolve().parents[2]`, exactly like the existing anatomy gates. No network, no Docker, no Ansible.

---

## 6. Risks & how the plan handles them

- **Stock-Jinja `{{ vars }}` eager-resolve trap** — the new var must have a real default that loads *before* core-up if it ever lands in the eager-resolve namespace. *Mitigation:* it is read **only** inside the role's own `when:` (stack-up time, after core-up), so a role default already suffices; we additionally add it to `default.config.yml` with a `false` literal so the committed surface is gate-clean. Stock filters only (`default`, `bool`). `test_config_stock_jinja_only.py` stays green.
- **Breaking existing FreePBX operators** — anyone currently running `install_freepbx: true` will start failing at the guard until they add the new flag. *This is intended* (the whole point is to force conscious acceptance of an actively-exploited RCE), and it matches the ERPNext precedent. *Mitigation:* the `fail` message is explicit and actionable; documented in README + security-baseline + RELEASE notes for v0.7. Because `install_freepbx` defaults `false` and `all-on`/`gov` profiles already exclude it, the blast radius is only operators who deliberately enabled an unfixable-CRITICAL service.
- **`continue-on-error` macOS CI / Linux gating wet-test** — this change adds no compose/network surface and no live behaviour on the default path (FreePBX stays off in CI profiles), so the Linux integration wet-test (`ok=` end-to-end) is unaffected. The guard only fires when `install_freepbx` is on, which CI never sets.
- **JSON edit corrupting the remediation queue** — the security scan-drift hook + downstream tooling read this file. *Mitigation:* the anatomy gate parses it as JSON (catches a syntax break); keep existing key ordering and only append a field.
- **Gate brittleness (whitespace / reword drift)** — the `when`-string assertion normalizes whitespace and the message assertion checks for substrings (CVE/REM IDs) rather than exact text, so legitimate rewording survives while removal of the citation or the guard does not.
- **False sense of "fixed"** — explicitly keep REM-014/046 `vendor-blocked`; the gate is a *mitigation note*, not a resolution. The plan forbids flipping status to resolved (and the gate asserts it).

---

## 7. Optional stretch (only if cheap + consumed)

- **Service-registry / state advisory** — if the post-provision service registry or `~/.nos/state.yml` has a place for a per-service advisory, record `risk_accepted: true` when the flag is set so Wing / the registry surfaces it. **Skip unless a consumer already reads such a field** — otherwise it is dead metadata (machinery doctrine: no speculative surface).
- **A9 notification on enable** — emit an `on_high` notification ("FreePBX enabled with accepted CRITICAL CVE risk") via the plugin notification block on first converge. Defer unless the plugin notification path is trivially extendable; not required for the gate.

Both are explicitly out of scope for the core fix; listed so a reviewer knows they were considered and parked.

---

## 8. Verification recipe

```bash
# 1. The new gate passes (and actually exercises the guard)
python3 -m pytest tests/anatomy/test_freepbx_cve_risk_gate.py -v

# 2. Full anatomy suite stays green (no collateral)
python3 -m pytest tests/anatomy/ -q

# 3. Stock-Jinja invariant intact for the new var
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 4. Playbook still parses
ansible-playbook main.yml --syntax-check

# 5. Manual negative proof (no live mutation — dry render path):
#    With install_freepbx=true and the flag UNSET, the role must fail at the
#    guard BEFORE creating dirs / rendering the override. Confirm via a
#    --check + --tags freepbx dry-run (read-only); expect the fail task to fire.
ansible-playbook main.yml --check --tags freepbx \
  -e install_freepbx=true   # expect: hard-guard fail, no override written

#    With the flag SET, the guard passes and render proceeds (check mode, no
#    container brought up):
ansible-playbook main.yml --check --tags freepbx \
  -e install_freepbx=true -e freepbx_accept_critical_cve_risk=true
```

The `--check` runs are read-only (no `docker compose up`, no live writes) and satisfy the "live system = READ-ONLY" rule; they prove the guard fires/clears as designed.

---

## 9. Commit (when implemented — not under this prompt)

Single commit on `feat/v0.7-overnight`, Conventional Commits, subject ≤50:

```
fix(freepbx): gate role-load behind CVE risk-accept
```

Body (surgeon-tone, ≤6 bullets):
- tendon: voip stack-up role-load; symptom: `install_freepbx=true` stands up an actively-exploited RCE with zero friction.
- structural: hard-guard `fail` unless `freepbx_accept_critical_cve_risk: true`; mirrors the ERPNext override precedent, fail-closed before any side effect.
- cites REM-014/046; status stays vendor-blocked (mitigation, not fix).
- gate: `tests/anatomy/test_freepbx_cve_risk_gate.py` pins default-false + guard-first + CVE citation.

No Co-Authored-By, no `--author`, commit only — never pushed.
