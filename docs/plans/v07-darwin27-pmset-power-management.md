# v0.7 — Darwin 27 `pmset` power-management hardening

Status: PLAN (not implemented). Target branch: `feat/v0.7-overnight`.
Owner: overnight agent batch. Scope: repo edits only, no live mutation.

> Sibling plan: `docs/plans/v07-darwin27-softwareupdate-script.md` covers host
> **OS updates** (`softwareupdate`). This plan is its power-posture twin — the
> same Darwin-27 forcing function applied to `pmset(8)`. They are independent:
> neither blocks the other, and they deliberately share no files.

## Problem / why

nOS turns an Apple-Silicon Mac into an always-on server running ~50 services +
the launchd daemons (Wing/Bone/Pulse) + the Docker VM. The single task that
keeps that box reachable overnight is `tasks/power-management.yml`, which fires
one fixed `pmset -c …` blob. Three problems, all sharpened by Darwin 27:

1. **The current task is not idempotent and masks failures.** It runs the full
   `pmset -c sleep 0 displaysleep 20 … ttyskeepawake 1` blob every converge with
   `changed_when: false` (see `tasks/power-management.yml` L7–L19). So:
   - It always reports `ok` even when it changed nothing — and, worse, it
     reports `ok` even if pmset **rejected a key** (the `command` module's rc is
     swallowed because there's no `failed_when` and `changed_when` is hard-false).
     A single unknown/renamed key silently no-ops the *entire* remaining blob on
     some pmset builds (pmset stops at the first bad token).
   - There is no record of what the host's power posture actually *is* — Wing /
     the run summary never sees it; an operator can't tell from a converge
     whether `sleep` is really `0`.

2. **Darwin 27 changes the `pmset` key surface.** macOS 27 (Darwin kernel 27.x,
   Apple Silicon) reworks the power subsystem: several keys this blob hard-codes
   are deprecated, renamed, or now no-op on Apple Silicon (notably the
   historically x86-only / battery-only ones — `networkoversleep`, parts of
   `powernap`/`tcpkeepalive` semantics — plus new knobs around low-power /
   sleep-services). The blob is a **flat literal**: a key that 27 rejects either
   errors (currently masked) or silently drops the rest of the line. nOS pins
   every other layer per Darwin version (`dnsmasq_version` is annotated "macOS 27
   validated" at `default.config.yml` L1607–L1609; the Homebrew bottle path
   assumes `arm64_sequoia` at L570) — but the power posture is version-blind.

3. **A bad power posture on an unattended box is silently catastrophic.** If a
   pmset key flip lets the Mac sleep, every service + every launchd daemon goes
   dark at 02:00 with zero nOS awareness — the exact overnight-surprise class the
   safety doctrine exists to prevent. We want the posture to be **asserted and
   verified**, not fire-and-forget.

### Doctrine alignment

`pmset -c` on AC power is a **non-destructive, trivially-reversible host
setting** (no data loss, no reboot) — so unlike the softwareupdate `apply` path,
*applying* it on a normal converge is allowed under the overnight rules. What's
missing is **idempotence + verification + Darwin-awareness**, not a safety gate.
This plan keeps the apply-on-converge behaviour, makes it idempotent and
fail-loud, and adds a Darwin-27-aware key set. No new auto-scheduled job, no
destructive op.

## Approach

Three cooperating changes, modeled on the **`preflight-at-rest.yml`** host-probe
shape (Darwin-gated, default-safe) and the **idempotence idioms** already proven
in `tasks/system-services.yml` (real `changed_when`/`failed_when`, not blanket
false):

### A. Record the host Darwin version once (shared seam)

Add a tiny, read-only fact-record at the top of `tasks/power-management.yml`
(or, preferably, lift it into `tasks/_platform.yml` so the softwareupdate plan
can reuse it — see "Coordination" below):

```
nos_host_darwin_major  =  ansible_facts['kernel'].split('.')[0] | int   # e.g. 27
nos_host_os_version    =  ansible_facts['distribution_version']         # e.g. 27.0
```

`ansible_facts['kernel']` is already gathered (no `uname` shell-out needed); this
is pure fact arithmetic, byte-inert on Linux (the whole file stays Darwin-gated).

### B. Darwin-aware key map, idempotent apply

Replace the single flat blob with a **declarative key→value map** plus a
**Darwin-floor filter**, applied key-by-key with a real diff:

1. Define the desired posture as a dict in `default.config.yml`
   (`pmset_settings:` — keyed by pmset token), built from the existing
   `pmset_*` scalars so **no behaviour changes on Darwin ≤ 26**. Each entry
   carries an optional `min_darwin` / `max_darwin` so a key that 27 drops is
   simply not emitted on 27, and a 27-only key can be added later without
   touching ≤ 26 hosts. (All stock-Jinja scalars/dicts — no non-stock filter —
   so `test_config_stock_jinja_only.py` stays green.)
2. **Read current state first**: `pmset -g custom` (read-only, `changed_when:
   false`, `failed_when: false`) → parse the AC (`-c`) block into a
   `current_pmset` dict.
3. Compute the **delta**: only the keys whose live value differs from desired
   AND whose `min_darwin`/`max_darwin` window includes `nos_host_darwin_major`.
4. Apply **only the delta** in one `pmset -c k1 v1 k2 v2 …` call, with
   `changed_when: <delta is non-empty>` and `failed_when: rc != 0` (so a
   rejected key now **fails loud** instead of silently no-opping). If the delta
   is empty the task is a true `changed=0` no-op — fixing the idempotence churn.
5. **Verify**: a second `pmset -g custom` read asserts every desired key now
   matches (failed_when on mismatch). This is the "asserted, not fire-and-forget"
   guarantee.

### C. Surface the posture into state

Write the resolved posture (desired + observed-after + `nos_host_darwin_major`)
into the run summary and, when Bone is reachable, an A9 `on_info` notification —
mirroring how backup status surfaces. **Read-only** w.r.t. the live system
(it only POSTs telemetry to the local Bone bridge, same vein every framework
event already uses). No new scheduler.

This keeps the change **macOS-byte-identical on Linux** (every task Darwin-gated;
the Linux wet-test executes zero pmset lines) and **behaviour-identical on
Darwin ≤ 26** (the key map is derived from today's scalars; the Darwin filter is
a no-op below 27). The only visible change on a ≤ 26 host is: idempotent
(`changed=0` on a steady-state re-run) and fail-loud on a rejected key.

## Files to touch

New:

- `tests/anatomy/test_pmset_idempotent_darwin_aware.py` — **the gate** (below).

Edited:

- `tasks/power-management.yml` — replace the flat blob with the
  read→delta→apply→verify flow (A + B). Keep the file Darwin-gated (its
  `import_tasks` guard in `main.yml` L1387–L1390 already pins
  `ansible_os_family == 'Darwin'` + `configure_power_management`; preserve those
  tags `['power', 'pmset', 'power-management']`). Record `nos_host_darwin_major`
  here if not lifted to `_platform.yml`.
- `default.config.yml` — add `pmset_settings:` (the declarative key map, built
  from the existing `pmset_*` scalars, each with optional `min_darwin`/
  `max_darwin`) and `pmset_darwin27_keys_deprecated:` (the list of keys to drop
  on `>= 27`). Keep the legacy `pmset_*` scalars as the source values so nothing
  downstream that reads them breaks. **All stock-Jinja, real defaults, defined
  before core-up** (satisfies both variants of `test_config_stock_jinja_only.py`).
  Add `pmset_verify: true` (the post-apply assert; operator can disable on an
  exotic host). Annotate the block "macOS 27 validated" like `dnsmasq_version`.
- `tasks/_platform.yml` *(optional, preferred)* — set `nos_host_darwin_major` /
  `nos_host_os_version` in the macOS branch so both this plan and the
  softwareupdate plan consume one fact (avoids a double-definition seam). If
  done here, drop the local record in `power-management.yml`.
- `docs/security-baseline.md` — a paragraph: host power posture is now
  idempotent + verified + Darwin-version-aware; a rejected pmset key fails the
  converge loudly instead of silently degrading the always-on guarantee.
- `docs/active-work.md` — one-line pointer.

Explicitly **not** touched: `main.yml` (the existing `import_tasks` guard +
tags already do the right thing); `profiles/gov-local.yml` (power posture isn't a
gov gate — leave it). No new role (this is a host task, not a Docker service —
keeping it in `tasks/power-management.yml` matches the existing footprint and
avoids role sprawl for a single `pmset` call).

## Coordination with the softwareupdate plan

Both plans want `nos_host_darwin_major` / `nos_host_os_version`. To avoid a
merge collision:

- **Preferred:** whichever lands first adds the two facts to the macOS branch of
  `tasks/_platform.yml`; the second consumes them. The gate for *this* plan
  asserts the facts are *available where pmset uses them*, not *where* they're
  defined — so either definition site passes.
- If they land in parallel and both define the facts, the `_platform.yml`
  definition wins (runs first in `pre_tasks`); a local re-`set_fact` in
  `power-management.yml` is harmless (same value). The gate tolerates both.

## Gates it needs

New `tests/anatomy/test_pmset_idempotent_darwin_aware.py` — **offline,
source-level** (no playbook run, no `pmset`, no Docker), parsing the task YAML +
`default.config.yml` the way `test_config_stock_jinja_only.py` does:

1. **`test_power_task_has_real_changed_and_failed_when`** — parse
   `tasks/power-management.yml`; the `pmset -c` **apply** task MUST NOT carry
   `changed_when: false` (the bug), MUST define a non-trivial `changed_when`
   (delta-driven) AND a `failed_when` that keys off `rc` (fail-loud on a rejected
   key). The read/verify tasks MAY use `changed_when: false` (they're reads).
   This is the load-bearing pin: the silent-failure regression can't come back.
2. **`test_apply_reads_current_state_first`** — assert a `pmset -g custom` (or
   `-g`) read task exists *before* the apply task in file order (the
   read→delta→apply flow). Pins idempotence-by-construction.
3. **`test_post_apply_verify_present`** — assert a verify task exists after the
   apply that asserts the desired keys (a `failed_when` referencing the
   post-read). Guarded by `pmset_verify | default(true)` so the gate also checks
   the escape hatch exists.
4. **`test_darwin_filter_present`** — assert the apply path references
   `nos_host_darwin_major` (or `min_darwin`/`max_darwin`) so the key set is
   Darwin-version-filtered, not a flat literal. Pins the Darwin-27 readiness.
5. **`test_every_task_is_darwin_gated`** — every task in
   `tasks/power-management.yml` is reachable only on `ansible_os_family ==
   'Darwin'` (file-level `import_tasks` guard in `main.yml` counts; assert that
   guard is intact) AND no task shells `uname`/`sw_vers` (uses
   `ansible_facts['kernel']`). Pins Linux-byte-inert.
6. **`test_pmset_settings_stock_jinja_and_legacy_preserved`** — assert
   `default.config.yml` declares `pmset_settings` + the legacy `pmset_*` scalars,
   that `pmset_settings` values derive from the scalars (so Darwin ≤ 26 posture
   is byte-identical), and that nothing in the new block uses a non-stock filter
   (belt-and-suspenders alongside `test_config_stock_jinja_only.py`).

The full anatomy suite must stay green and `ansible-playbook main.yml
--syntax-check` must pass. Because every task is Darwin-gated, the **Linux
integration wet-test runs zero pmset lines**; the **macOS integration
idempotence re-run stays `changed=0`** (the delta is empty on the second pass —
this is the whole point of read→delta→apply, and is what the existing
`changed_when: false` was *faking*).

## Risks

- **Parsing `pmset -g custom` output is format-sensitive.** The block layout
  (` AC Power:` vs ` Battery Power:`, indentation, key alignment) shifts across
  macOS versions — and Darwin 27 is exactly where it shifts. Mitigation: the
  parser keys off the `-c` (AC) section header and token-splits each line
  defensively; an unparseable line → that key is treated as "unknown, force-set"
  (safe: at worst we re-apply a value that's already correct, a no-op on the
  host). The parser never crashes the converge (`failed_when: false` on the
  read); only the *apply* and *verify* fail loud.
- **A Darwin-27-deprecated key still in the desired map.** Handled by
  `min_darwin`/`max_darwin` on each entry + the `pmset_darwin27_keys_deprecated`
  drop-list — a key 27 rejects is filtered out *before* the apply, so the apply
  never sends it (no rc-failure). The gate (#4) pins that the filter exists; the
  operator updates the drop-list as Apple finalizes 27's key surface.
- **Fail-loud could break a converge a rejected key used to silently tolerate.**
  That's intended (the silent tolerance is the bug), but to avoid a hard stop on
  a genuinely-unknown host, `pmset_verify: true` is operator-disable-able and the
  apply only sends the *filtered* delta — so a converge fails only if a key that
  *passed* the Darwin filter is *still* rejected, which is a real
  misconfiguration worth failing on. The escape hatch is documented.
- **Idempotence depends on read-parse symmetry.** If `pmset -g custom` reports a
  value in a different unit/format than `pmset -c` accepts (rare, but e.g.
  boolean `1`/`0` vs a word), the delta could be perpetually non-empty →
  `changed=1` churn forever. Mitigation: the comparison normalizes both sides
  (string-cast, strip) and the gate's idempotence note + a manual `--check`
  re-run in the verification recipe catches it before merge.
- **`_platform.yml` coordination collision** with the softwareupdate plan (both
  want the Darwin facts). Mitigated by the "definition-site-agnostic gate" +ordering
  note above; worst case both define the same value (harmless).
- **No Jinja brace-hash trap** — no host **shell script** is rendered here (this
  is an Ansible `command`, not a `template:`-rendered `.sh`), so the
  `${#arr[@]}` `{#` trap (memory `jinja-rendered-shell-brace-hash-trap`) does
  not apply. The gate still greps the task file for any rendered `${#` defensively.

## Verification recipe

```bash
# 0. On the right branch
git switch feat/v0.7-overnight

# 1. The new gate + the stock-Jinja gate (offline, fast — no pmset run)
python3 -m pytest tests/anatomy/test_pmset_idempotent_darwin_aware.py \
                  tests/anatomy/test_config_stock_jinja_only.py -q

# 2. Full anatomy suite stays green
python3 -m pytest tests/anatomy/ -q

# 3. Syntax-check clean (rewritten task file is valid YAML/Jinja)
ansible-playbook main.yml --syntax-check

# 4. READ-ONLY live spot-check (no mutation): see the CURRENT host posture
#    + Darwin major the new code will key off — pure reads:
pmset -g custom | sed -n '/AC Power/,/Battery Power/p'
uname -r          # Darwin kernel; major = first dotted field (e.g. 27)
sw_vers -productVersion

# 5. Prove the apply is idempotent + fail-loud (dry, source-level):
#    the old bug — confirm the rewritten task NO LONGER hard-codes changed_when:false
grep -nA12 "pmset -c" tasks/power-management.yml | grep -E "changed_when|failed_when"
#    expect: a delta-driven changed_when + an rc-based failed_when, NOT "changed_when: false"

# 6. Idempotence dry-run on the live Mac (NO mutation under --check):
ansible-playbook main.yml --tags power-management --check --diff --skip-tags stacks
#    --check means pmset is not actually called to set anything; eyeball that the
#    delta the playbook reports matches step-4's observed-vs-desired diff.

# 7. (Operator, supervised, NOT overnight) Real idempotence proof — first run
#    applies the delta, immediate re-run reports changed=0:
ansible-playbook main.yml --tags power-management --skip-tags stacks   # run twice
#    second run MUST be changed=0 (was always "ok" before, now genuinely no-op).

# 8. Frozen 1:1 pre-release probe (optional, before any eventual release push)
tools/ci-local.sh
```

Acceptance: gates #1–#2 green, full suite green, syntax-check clean; step-5 shows
a real `changed_when`/`failed_when` (no blanket `changed_when: false` on the
apply); step-7's second run is `changed=0`; on a Darwin-27 host the apply sends
only the filtered delta and the verify passes (no rejected-key failure).

## Follow-ups (NOT this plan)

- Export `nos_macos_power_posture` (sleep/displaysleep/womp + `nos_host_darwin_major`)
  to the `node_exporter_textfile_dir` `.prom` so Grafana can alert if the host's
  `sleep` ever drifts off `0` — same observability vein backups use
  (`backup.prom`). Deferred: needs its own exporter task, out of scope for the
  pmset-correctness fix.
- Fold `nos_host_darwin_major` into `tasks/export-state.yml` (it already records
  `os` from `distribution_version` at L149) so the host Darwin major is part of
  the audited Art-30 systems-register state shape — shared with the
  softwareupdate plan's identical follow-up.
- A `caffeinate`-based "hold-awake during a converge / backup window" wrapper so
  a long blank/backup never races a displaysleep-triggered NIC drop. Separate
  concern from the steady-state posture this plan fixes.
