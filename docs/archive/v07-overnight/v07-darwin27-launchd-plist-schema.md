# v0.7 — Darwin 27 launchd plist + launchctl schema hardening

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: **repo edits only, no live mutation** —
no playbook run, no `launchctl` against the live system, no service reload.

## Problem / why

nOS deploys **11 launchd LaunchAgent plists** (the host-side daemons that are
*not* Docker services): wing, bone, pulse, hermes, openclaw/ollama, acme-renew,
backup.rustfs, backup.exporter, restic off-site, heartbeat, and the
backup-status exporter. They are loaded into `launchd` by a **mix of two
generations of the `launchctl` CLI** — and the legacy half is on Apple's
deprecation path. Darwin 27 (the next major macOS, one step past the live
26.3 / Darwin 25 box) is the forward-looking removal risk this plan de-risks
**before** an operator's OS bump breaks daemon bring-up on a blank run.

Two concrete, gateable defects exist today:

### Defect 1 — split-brain launchctl API (the load-bearing one)

Apple's modern, per-domain launchctl verbs are `bootstrap` / `bootout` /
`kickstart` / `print` (the `gui/<uid>` domain form). The pre-2014 verbs
`load` / `unload` / `list` / `start` / `stop` are **deprecated** and emit
`Unload failed: 113` / "this API is deprecated" wording today; Apple has
signalled they go away in a future release. nOS uses **both**, inconsistently:

| Agent / call site | API used | File |
|---|---|---|
| wing | `bootstrap` / `kickstart` | `roles/pazny.wing/tasks/main.yml`, `handlers/main.yml` |
| bone | `bootstrap` / `kickstart` / `bootout` | `roles/pazny.bone/tasks/main.yml`, `handlers/main.yml` |
| pulse | `bootstrap` / `bootout` | `roles/pazny.pulse/tasks/main.yml`, `handlers/main.yml` |
| hermes | `bootstrap` / `kickstart` | `roles/pazny.hermes/tasks/main.yml`, `handlers/main.yml` |
| backup.exporter | `bootout` + `bootstrap` | `roles/pazny.backup/tasks/main.yml` |
| **backup.rustfs** | **`load -w` + `list` probe** | `roles/pazny.backup/tasks/main.yml:73-90`, `handlers/main.yml:8-9` |
| **heartbeat** | **`load -w` + `list` probe** | `tasks/heartbeat.yml:33-46` |
| **restic off-site** | **`load -w`** | `tasks/backup.yml:206` |
| **openclaw / ollama** | **`load` / `unload`** | `roles/pazny.openclaw/tasks/main.yml:54-85` |
| **acme-renew** | **`load -w`** | `roles/pazny.acme/tasks/main.yml:191` |
| **blank-reset** | **`unload`** | `tasks/blank-reset.yml:121-163` |

The four playbook-managed agents in **bold** (backup.rustfs, heartbeat, restic
off-site, openclaw/ollama, acme-renew) plus the blank-reset eviction loop still
ride the deprecated API. When Darwin removes `load`/`unload`/`list`, those
daemons **silently fail to load on a blank** — backup, heartbeat, the off-site
restic schedule, the local LLM, and TLS cert renewal all go dark with no error
the operator notices until the dependent thing is missing. This is exactly the
kind of OS-version regression that "a patch-level bump flipped it red with zero
repo change" (the 2026-06-08 CI saga) but on the *operator's* box, overnight.

**Out of scope for Defect 1 — leave untouched (documented boundary):**

- **Homebrew-owned plists** — `files/brew-svc.sh` and the `tasks/php.yml` /
  `tasks/nginx.yml` / `tasks/observability.yml` `launchctl load -w` /
  `launchctl list homebrew.mxcl.*` calls drive **brew's** plists, whose
  filenames + on-disk layout brew controls. `brew services` itself still shells
  `launchctl load`; converting these would fork brew's own contract. Tag them
  as a **separate, brew-tracking follow-up**, not this plan.
- **System LaunchDaemons** — `tasks/system-services.yml` `launchctl load -w
  /System/Library/LaunchDaemons/ssh.plist` (+ smbd) loads **Apple-owned**
  daemons in the **system** domain (`system/<label>`, needs root). The modern
  equivalent is `sudo launchctl bootstrap system <plist>`; converting it is
  correct but touches the `sudo` path + a different domain, so it is a
  **scoped, clearly-labelled second commit** the gate covers but the operator
  can review in isolation.

### Defect 2 — plist XML schema drift (low-risk, gateable hygiene)

The 11 plist `.j2` templates are individually valid but **inconsistent**, and
no gate proves any of them is even well-formed XML or a valid plist:

- **`ProcessType` spread:** ollama=`Interactive`, backup=`Background`,
  backup.exporter=`Background`, the long-lived servers (wing/bone/pulse/hermes)
  set **none** (so launchd assumes `Standard`). For a loopback-bound HTTP
  daemon that *should* be `Adaptive` or left `Standard`; the absence is fine but
  undocumented — a future contributor can't tell intent from omission.
- **No `<?xml … standalone?>` / DOCTYPE uniformity check** and no
  `plutil -lint` equivalent gate. A typo'd `<key>`/`<string>` mismatch (the
  classic odd-element plist corruption) renders to on-disk garbage that
  `launchctl bootstrap` rejects with a cryptic `Bootstrap failed: 5: Input/output
  error` — discovered only mid-blank.
- **`AssociatedBundleIdentifiers`** (the modern key that lets a daemon surface
  under System Settings → Login Items / Background, mandatory-ish UX on
  Ventura+ and louder on each release) is set on **zero** plists. Not a
  functional break, but the daemons show up as opaque "eu.thisisait.nos.*"
  with no app association — worth a single shared key now that we're touching
  every template.

Defect 2 is **hygiene + future-proofing**, not a live break. It ships behind
the same gate so the schema can't silently rot again.

## Approach

Two ordered commits on `feat/v0.7-overnight`, each independently gated. **No
behaviour change to the modern-API agents** — they are already correct and only
get the Defect-2 schema touch-ups.

### Commit 1 — converge every playbook-managed agent onto `bootstrap`/`bootout`

Mechanical, behaviour-preserving (the modern verbs do the same load/unload, just
in the `gui/<uid>` domain). The established in-repo idiom is already proven by
bone/pulse/wing/hermes/backup.exporter — copy it exactly:

- **Idempotent (re)load** — replace each `launchctl load -w <plist>` (+ its
  `launchctl list <label>` probe) with the bone/backup.exporter idiom:

  ```yaml
  - name: "[<svc>] (Re)load agent (bootout + bootstrap, idempotent)"
    ansible.builtin.shell: |
      UID_NUM="$(id -u)"
      launchctl bootout "gui/${UID_NUM}/{{ <svc>_label }}" 2>/dev/null || true
      launchctl bootstrap "gui/${UID_NUM}" "{{ <svc>_plist }}"
    register: _<svc>_reload
    changed_when: true
    when:
      - (nos_service_manager | default('launchd')) == 'launchd'
      - _<svc>_plist is changed          # only reload when the template changed
  ```

  Gating the reload on `_<svc>_plist is changed` (the `template` task's
  register) keeps the macOS idempotence re-run at `changed=0` — same discipline
  the v0.4 idempotence fix established (`wing_api_token` churn lesson). For the
  calendar-scheduled agents (backup.rustfs `RunAtLoad=false`, restic off-site,
  acme `RunAtLoad=false`) a `bootout`+`bootstrap` on change is correct: the
  next scheduled wake re-reads the freshly bootstrapped definition.

- **Drop the `launchctl list <label>` probe tasks** where they only fed the old
  `load -w` changed_when — the `_<plist> is changed` register replaces them
  (cleaner + no version-dependent stderr-wording fragility, which is *why* the
  probe existed in the first place; bootstrap/bootout removes that fragility).
  Keep `launchctl list homebrew.mxcl.*` probes untouched (brew domain, scope).

- **blank-reset eviction** — `tasks/blank-reset.yml:163`
  `launchctl unload {{ item.path }}` → `launchctl bootout
  gui/<uid>/<label-from-path>` (derive the label by basename-minus-`.plist`,
  or bootout the plist path form `launchctl bootout gui/<uid> <plist>` which
  modern launchctl accepts). The shell loop at `:121` (`launchctl unload`)
  converts the same way. **Keep `failed_when: false` / `|| true`** — a blank
  must tolerate an already-absent agent.

- **openclaw / ollama** — `roles/pazny.openclaw/tasks/main.yml:54,59,85`
  `unload`/`load` → bootout/bootstrap. The brew-plist *rename-to-`.disabled`*
  dance at `:56` stays (that's file-move, not launchctl). The bootout of the
  brew `homebrew.mxcl.ollama` label must stay tolerant (brew may not have
  loaded it).

- **acme** — `roles/pazny.acme/tasks/main.yml:191` `load -w` → the
  bootout+bootstrap idiom; `handlers/main.yml` already uses
  `bootout`/`bootstrap`, so this just aligns the task path with the handler.

Diagnostic comments in each role's task header that say *"Reload: launchctl
kickstart …"* already document the modern path — extend that to the converted
agents so the runbook strings match the code.

### Commit 2 — plist XML schema convergence + a lint gate

- **Add `AssociatedBundleIdentifiers`** (array with the agent's own Label) to
  every `eu.thisisait.nos.*` plist — one consistent block. Skip the brew/ollama
  `com.*` labels (not nOS bundle IDs). Purely additive; launchd ignores it on
  older macOS, surfaces the daemon cleanly on Ventura+/Darwin 27.

- **Normalise `ProcessType`:** make it explicit on the long-lived servers
  (`Adaptive` for wing/bone/pulse/hermes — loopback HTTP daemons that should
  yield under memory pressure but stay responsive) and leave the existing
  `Background` (backup/exporter) / `Interactive` (ollama, GPU-bound) as-is with
  a one-line comment stating the intent. No value *changes* for an existing
  key; only the missing ones are filled, so rendered output for already-set
  agents is byte-identical → no reload churn for them.

- **DOCTYPE / XML header uniformity:** the off-site template wraps the DOCTYPE
  across two lines; normalise all 11 to the single canonical header. Cosmetic,
  but the gate (below) asserts it so it can't drift.

## Files to touch

**Commit 1 (launchctl API):**

- `roles/pazny.backup/tasks/main.yml` — backup.rustfs `load -w`+`list` →
  bootout/bootstrap.
- `roles/pazny.backup/handlers/main.yml` — `Reload backup launchd` handler.
- `tasks/heartbeat.yml` — `load -w` + `list` probe.
- `tasks/backup.yml:206` — restic off-site `load -w`.
- `roles/pazny.openclaw/tasks/main.yml` — `load`/`unload`.
- `roles/pazny.acme/tasks/main.yml:191` — `load -w`.
- `tasks/blank-reset.yml` — `unload` eviction (shell loop + find loop).
- (Commit 1b, scoped) `tasks/system-services.yml` — Apple system-domain
  `load -w` → `sudo launchctl bootstrap system …` (separate, clearly-labelled).

**Commit 2 (plist schema):**

- All 11 `*.plist.j2`:
  `roles/pazny.{wing,bone,pulse,hermes,openclaw,acme,backup}/templates/*.plist.j2`,
  `roles/pazny.backup/templates/backup-exporter.plist.j2`,
  `templates/eu.thisisait.nos.heartbeat.plist.j2`,
  `templates/eu.thisisait.nos.backup.offsite.plist.j2`.

**Gates (both commits):**

- `tests/anatomy/test_launchctl_modern_api.py` — **new**.
- `tests/anatomy/test_plist_schema_valid.py` — **new**.

**Docs:**

- `CLAUDE.md` "Operator gotchas" — one bullet: *"Playbook-managed launchd
  agents load via `launchctl bootstrap`/`bootout` (gui domain); the deprecated
  `load`/`unload`/`list` verbs are forbidden in playbook-managed agent tasks
  (Darwin-27-safe) — brew/system-domain calls are the documented exception."*

## Gates it needs

Both new gates are **offline, source-level** (no playbook run, no `launchctl`,
no live system), mirroring `test_blank_reset_plist_discovery.py` style.

### `tests/anatomy/test_launchctl_modern_api.py`

1. **`test_no_legacy_launchctl_in_managed_agent_tasks`** — grep every role
   `tasks/*.yml` + `handlers/*.yml` + the top-level `tasks/{heartbeat,backup,
   blank-reset,system-services}.yml` for `launchctl (load|unload|list|start|
   stop)\b`. **Allowlist** (the documented out-of-scope boundary):
   - any line referencing `homebrew.mxcl.` (brew domain),
   - `files/brew-svc.sh` (brew wrapper),
   - the `system/` domain conversions once Commit-1b lands (asserted by name).
   Every other hit is a failure with a "use bootstrap/bootout" message. This is
   the anti-regression pin: a new agent can't reintroduce `load -w`.
2. **`test_every_managed_agent_has_bootstrap_path`** — for each of the 11
   plist labels (reuse the `PLAYBOOK_AGENTS` map already in
   `test_blank_reset_plist_discovery.py`, import it), assert *some* task/handler
   bootstraps it (`launchctl bootstrap` referencing its label or plist var).
3. **`test_blank_reset_evicts_via_bootout`** — assert `tasks/blank-reset.yml`
   uses `bootout`, not `unload`, for the playbook-managed eviction loop.

### `tests/anatomy/test_plist_schema_valid.py`

1. **`test_all_plists_are_wellformed_after_render`** — for each `*.plist.j2`,
   strip Jinja (`{{…}}`/`{%…%}`/`{#…#}` → harmless placeholders, mirroring the
   stock-Jinja test's render trick) then parse with
   `xml.dom.minidom.parseString` **and** `plistlib.loads` (after substituting
   placeholders that keep `<integer>`/`<string>` bodies valid). Catches the
   odd-element `<key>`/`<string>` mismatch class.
2. **`test_each_dict_key_has_a_value_sibling`** — count `<key>` vs value
   elements per `<dict>` to catch the classic "key with no value" corruption a
   plain XML well-formedness check misses.
3. **`test_canonical_xml_header`** — every template opens with the canonical
   `<?xml …?>` + single-line DOCTYPE + `<plist version="1.0">`.
4. **`test_associated_bundle_ids_on_nos_agents`** — every
   `eu.thisisait.nos.*` plist carries an `AssociatedBundleIdentifiers` block
   whose entry equals its own Label (the `com.*` brew/ollama labels are
   exempt). Pins the Defect-2 addition so it can't be dropped.
5. **`test_processtype_explicit_or_documented`** — every plist either sets
   `ProcessType` or carries a `<!-- ProcessType: … -->` rationale comment.

The full anatomy suite must stay green and
`ansible-playbook main.yml --syntax-check` must pass (the task edits are valid
YAML; the plist edits are valid XML/Jinja). No stock-Jinja-trap exposure: no
new var lands in `default.config.yml`/`default.credentials.yml` (the
`AssociatedBundleIdentifiers` value reuses the existing `*_launchd_label`
vars, all already defined before core-up).

## Risks

- **Behaviour change to live daemon reload semantics.** `bootout`+`bootstrap`
  is a hard stop-then-start vs `load -w`'s gentler enable. For the long-lived
  servers this is already how bone/pulse/wing/hermes reload (proven), so
  parity, not novelty. For the calendar agents (backup, acme) it's a no-op
  between scheduled wakes. **Mitigation:** gate the reload on `_plist is
  changed` so steady-state runs don't bounce a healthy daemon; document the
  one-time bounce on the converge that ships this.
- **`bootout` of a never-loaded agent returns non-zero.** Mitigation: keep the
  `2>/dev/null || true` / `failed_when: false` tolerance the existing
  bone/backup.exporter idiom already uses — *do not* tighten it.
- **System-domain conversion needs `sudo`** (`bootstrap system`). Risk: a
  privilege-path regression. **Mitigation:** ship it as the **separate
  Commit 1b** so it can be reviewed / reverted independently; if the reviewer
  is uneasy, Commit 1b can be dropped and only the user-domain `gui/<uid>`
  conversions land (the agents that actually break on Darwin 27 are the
  user-domain ones — system ssh/smbd are Apple's to keep working).
- **macOS idempotence re-run churn.** Converting `load -w` → bootout/bootstrap
  must not flip `changed=0` → `changed=1` on a no-op re-run. The `_plist is
  changed` guard is exactly what prevents it; verify on the macOS Integration
  idempotence leg (it's `continue-on-error`, but the Linux leg skips launchd
  entirely so this is macOS-observed-only — eyeball the second-run recap).
- **plistlib strictness vs Jinja placeholders.** A naive `{{ … }}` → empty
  substitution can turn `<integer>{{ x }}</integer>` into `<integer></integer>`
  (invalid). **Mitigation:** the render-strip must substitute integer-typed
  placeholders with `0` and string-typed with a token (the stock-Jinja test
  already solves this substitution shape — reuse its helper rather than
  reinventing).
- **No live `launchctl` available in CI / unsupervised run** — by design. The
  gate is **purely static** (parse + grep). The functional proof is deferred to
  the operator's next supervised blank (see verification §live).
- **Forward-looking, not reproduced-today.** Darwin 27 doesn't exist on the box
  yet (live is 26.3 / Darwin 25). This hardens *ahead* of the break. The legacy
  verbs already emit deprecation noise on 26.x, so the change is also a
  log-cleanliness win today, not purely speculative.

## Verification recipe

```bash
# 0. Right branch
git switch feat/v0.7-overnight

# 1. The two new gates (offline, fast, no launchctl, no live system)
python3 -m pytest tests/anatomy/test_launchctl_modern_api.py \
                  tests/anatomy/test_plist_schema_valid.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (task + handler edits are valid YAML)
ansible-playbook main.yml --syntax-check

# 4. Prove zero legacy verbs survive in playbook-managed agent tasks
#    (homebrew.mxcl + system/ domain are the allowed exceptions). Should
#    print only brew/system lines — NOTHING for wing/bone/pulse/hermes/
#    backup/heartbeat/restic/openclaw/acme.
grep -rnE 'launchctl (load|unload|list|start|stop)\b' \
     roles/*/tasks roles/*/handlers tasks/ \
  | grep -vE 'homebrew\.mxcl\.|system/Library|brew-svc'

# 5. Spot-render one plist offline to confirm it's a valid plist
#    (READ-ONLY — no launchctl, no load). The gate does this for all 11;
#    this is the human spot-check:
python3 - <<'PY'
import plistlib, re, pathlib
t = pathlib.Path("roles/pazny.wing/templates/wing.plist.j2").read_text()
# crude Jinja strip for the spot-check (the gate's helper is the real one)
t = re.sub(r"\{%.*?%\}", "", t, flags=re.S)
t = re.sub(r"<integer>\{\{.*?\}\}</integer>", "<integer>0</integer>", t, flags=re.S)
t = re.sub(r"\{\{.*?\}\}", "x", t, flags=re.S)
t = re.sub(r"\{#.*?#\}", "", t, flags=re.S)
print("VALID PLIST" if plistlib.loads(t.encode()) else "PARSED EMPTY")
PY

# 6. Frozen 1:1 pre-release probe (optional, before any eventual release)
tools/ci-local.sh
```

### Live verification (operator, supervised — NOT this overnight run)

Deferred to the operator's next **supervised** converge (the agent must not
run a playbook or touch launchd):

```bash
# After a supervised `ansible-playbook main.yml`:
for L in wing bone pulse hermes backup.rustfs backup.exporter acme-renew; do
  launchctl print "gui/$(id -u)/eu.thisisait.nos.$L" >/dev/null 2>&1 \
    && echo "OK  $L" || echo "ABSENT $L"
done
# Expect OK for every enabled agent; no 'load -w' deprecation lines in the
# converge's ansible.log.
```

Acceptance (this overnight run): gates #1 green, full suite green,
syntax-check clean, step-4 grep prints only brew/system lines. Live
verification is a documented hand-off, not a blocker.

## Follow-ups (NOT this plan)

- **brew-svc.sh / `tasks/{php,nginx}.yml` brew-domain `load`** — convert when
  brew itself moves off `launchctl load` (track upstream `brew services`);
  forking brew's contract now is riskier than the deprecation.
- **`LaunchEvents` / `MachServices` on-demand activation** — none of the nOS
  agents use socket/launch-on-demand; if any daemon later wants lazy start,
  that's a separate schema epic.
- **Unify the off-site restic agent under `pazny.backup`** — the off-site plist
  lives in top-level `templates/` while its sibling lives in the role; a future
  consolidation, orthogonal to the launchctl-API fix.
