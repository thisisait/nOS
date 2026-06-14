# v0.7 Plan — Test/harden blank-reset nginx-config removal (platform-aware paths)

**Status:** PLAN (do not implement from this file alone — implement on `feat/v0.7-overnight`, gate it, keep the suite green + syntax-check clean).
**Branch:** `feat/v0.7-overnight`
**Confirmed item:** blank-reset's nginx config-removal block is unconditional and path-fragile — it hardcodes `{{ homebrew_prefix }}/etc/nginx/...` instead of the platform-resolved `nos_nginx_etc_dir` / `nos_nginx_log_dir`, and has no anatomy gate pinning the wipe-paths to the platform contract.

---

## 1. Problem / why

`tasks/blank-reset.yml` (section `── 5. Nginx - reset configuration ──`, lines ~217–236) wipes host-nginx state on every `blank=true` run:

```yaml
- name: "[BLANK] Remove nginx sites-enabled symlinks"
  ansible.builtin.shell: "rm -f {{ homebrew_prefix }}/etc/nginx/sites-enabled/*.conf"
- name: "[BLANK] Remove nginx sites-available configs"
  ansible.builtin.shell: "rm -f {{ homebrew_prefix }}/etc/nginx/sites-available/*.conf"
- name: "[BLANK] Remove nginx SSL certificates"
  ansible.builtin.file:
    path: "{{ homebrew_prefix }}/etc/nginx/ssl"
    state: absent
- name: "[BLANK] Remove nginx logs"
  ansible.builtin.shell: "rm -f {{ homebrew_prefix }}/var/log/nginx/*.log"
```

Two structural defects:

1. **Path abstraction drift (the real bug).** The rest of the playbook converged on `tasks/_platform.yml`, which sets `nos_nginx_etc_dir` and `nos_nginx_log_dir` per OS:
   - macOS → `{{ homebrew_prefix }}/etc/nginx` + `{{ homebrew_prefix }}/var/log/nginx`
   - Debian/Ubuntu → `/etc/nginx` + `/var/log/nginx`

   `tasks/nginx.yml` (the *creator* of this state) renders into `nos_nginx_etc_dir`. blank-reset (the *destroyer*) reaches for `{{ homebrew_prefix }}/etc/nginx` directly. On **Linux** the two paths diverge: `homebrew_prefix` defaults to `/usr/local` (`default.config.yml`: `'/opt/homebrew' if ansible_facts['machine'] == 'arm64' else '/usr/local'` — Linux x86/arm is not `arm64` on macOS terms, so it lands on `/usr/local`). The blank then targets `/usr/local/etc/nginx/...` while the host vhosts/certs/logs that `tasks/nginx.yml` wrote live at `/etc/nginx` and `/var/log/nginx`. **Result: on a Linux host with `install_nginx: true`, blank leaves nginx vhosts, the `ssl/` dir, and logs behind** — the exact cross-run-leakage class of bug `test_blank_reset_data_dirs.py` exists to prevent, but for the config surface instead of data dirs. The confirmation box (`── 1. Confirmation ──`) explicitly promises "Nginx configuration and SSL certificates" are deleted, so this is also a `test_blank_reset_confirmation_accuracy.py`-style box-lies-vs-reality drift on Linux.

2. **No gate.** There is no anatomy test asserting the nginx-removal tasks use the platform-resolved paths. A future edit (or the current drift) ships silently. Per the NON-NEGOTIABLE rule: a fix without a gate is a plan, not a fix.

**Note on the macOS path:** on macOS the two expressions resolve to the *same* string today (`nos_nginx_etc_dir == homebrew_prefix + '/etc/nginx'`), so this is **byte-identical on a Mac** and the change is a pure portability + abstraction-hygiene fix, not a behavior change for the operator's daily driver. That matches the v0.4 linux-port doctrine: "macOS-byte-identical; gates resolve true on a Mac."

**Why not also gate it behind `when: install_nginx`?** Deliberately *not* doing that. The `rm -f` / `state: absent` removals are idempotent no-ops when nginx was never installed (Traefik-primary default, `install_nginx: false`), and blank's contract is "wipe whatever might be there, regardless of the *current* toggle" — a host could have been provisioned with `install_nginx: true`, then the operator flips the toggle off and runs `blank=true`; the old vhosts must still be cleaned. Adding a `when: install_nginx` guard would *re-introduce* an orphan path. So the fix is **path-correctness only**, keeping the removals unconditional. (This reasoning is captured in the plan so a reviewer doesn't "helpfully" add the guard.)

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `tasks/blank-reset.yml` | Section 5: swap the 4 raw `{{ homebrew_prefix }}/etc/nginx` + `/var/log/nginx` references for `{{ nos_nginx_etc_dir }}` / `{{ nos_nginx_log_dir }}`. No `when:` added. Keep `failed_when/changed_when` as-is. |
| `tasks/blank-reset.yml` | Section 6 (dnsmasq, line ~241): `{{ homebrew_prefix }}/etc/dnsmasq.conf` → resolve via a platform-aware dnsmasq-conf path. **Scope decision below** — likely a follow-up, not this change, unless `_platform.yml` already exposes a dnsmasq path. |
| `tests/anatomy/test_blank_reset_nginx_paths.py` | **NEW** gate (see §4). |
| `tasks/_platform.yml` | **Only if** §2-dnsmasq is in scope and no dnsmasq path var exists yet — add `nos_dnsmasq_conf` (macOS `{{ homebrew_prefix }}/etc/dnsmasq.conf`, Debian `/etc/dnsmasq.conf` or `/etc/dnsmasq.d/nos.conf`). Defer if it widens the blast radius. |

**Scope recommendation:** ship the **nginx path fix + its gate** as the atomic unit (it is the named confirmed item). Treat the dnsmasq `homebrew_prefix` twin as a *noted sibling* in the plan and, if trivially covered by an existing/added `nos_dnsmasq_conf`, fold it in; otherwise file it as a one-line follow-up so the commit stays surgical. Do **not** let dnsmasq balloon the diff.

**Pre-req sanity:** `tasks/_platform.yml` is imported at `main.yml` line ~93; `tasks/blank-reset.yml` is imported at line ~1098 — so `nos_nginx_etc_dir`/`nos_nginx_log_dir` are **already set_fact'd before blank-reset runs**. No ordering work needed. (Confirm with the `import_tasks` line numbers at implementation time; they drift.)

---

## 3. Approach

1. In `tasks/blank-reset.yml` section 5, replace:
   - `{{ homebrew_prefix }}/etc/nginx/sites-enabled/*.conf` → `{{ nos_nginx_etc_dir }}/sites-enabled/*.conf`
   - `{{ homebrew_prefix }}/etc/nginx/sites-available/*.conf` → `{{ nos_nginx_etc_dir }}/sites-available/*.conf`
   - `{{ homebrew_prefix }}/etc/nginx/ssl` → `{{ nos_nginx_etc_dir }}/ssl`
   - `{{ homebrew_prefix }}/var/log/nginx/*.log` → `{{ nos_nginx_log_dir }}/*.log`
2. Leave the tasks **unconditional** (no `when:`), keep `failed_when: false` so a missing dir is a clean no-op on a Traefik-only host.
3. Add the new gate `tests/anatomy/test_blank_reset_nginx_paths.py`.
4. Run the offline suite + `--syntax-check`.
5. (Optional, scoped) dnsmasq sibling per §2.

**No live-system mutation.** This is a repo edit; it changes only what a *future* blank run targets. Nothing touches the running host.

---

## 4. The gate (`tests/anatomy/test_blank_reset_nginx_paths.py`)

Offline, fast, parse-only — mirrors `test_blank_reset_data_dirs.py` / `test_blank_reset_confirmation_accuracy.py` (read the file text, assert with regex). Assertions:

1. **`test_nginx_removal_uses_platform_etc_dir`** — every nginx config-removal task in section 5 references `nos_nginx_etc_dir`, and **none** of the section-5 nginx tasks reference the raw `homebrew_prefix }}/etc/nginx` literal. (Catches a regression back to the hardcoded path.)
2. **`test_nginx_log_removal_uses_platform_log_dir`** — the nginx log-removal task uses `nos_nginx_log_dir`, not `homebrew_prefix }}/var/log/nginx`.
3. **`test_nginx_ssl_dir_removed`** — the `ssl` dir removal still exists and points at `{{ nos_nginx_etc_dir }}/ssl` with `state: absent` (the cert-wipe the confirmation box promises).
4. **`test_nginx_removal_is_unconditional`** — the four nginx-removal tasks carry **no `when:`** (regression-pin the deliberate decision in §1 so nobody re-adds an `install_nginx` guard that would orphan stale vhosts).
5. **`test_platform_defines_nginx_dirs`** — `tasks/_platform.yml` defines both `nos_nginx_etc_dir` and `nos_nginx_log_dir` for macOS and Debian/Ubuntu blocks (pins the contract these paths depend on; if someone deletes the var, this test names the break).
6. **(scope-gated) `test_dnsmasq_path_is_platform_aware`** — only if the dnsmasq sibling is folded in: assert the dnsmasq-conf removal uses `nos_dnsmasq_conf`, not `homebrew_prefix }}/etc/dnsmasq.conf`.

Implementation note: extract section 5 by slicing the file text between the `── 5. Nginx` and `── 6. dnsmasq` banner comments, then run the regexes against that slice so assertions don't bleed into other sections.

This is a **static gate** (no Ansible run, no Docker, no network) — it runs in the existing `pytest` CI job and locally via `python3 -m pytest tests/anatomy/test_blank_reset_nginx_paths.py`.

---

## 5. Risks

- **Low blast radius.** macOS path is byte-identical → zero behavior change on the operator's Mac. Linux is *currently broken*; this makes it correct.
- **`failed_when: false` masks a wrong path.** If `nos_nginx_etc_dir` were ever undefined, the `rm -f` would no-op silently. Mitigation: gate #5 pins that `_platform.yml` defines it for every supported OS, and `_platform.yml` runs first. Low risk.
- **Scope creep via dnsmasq.** Mitigated by the explicit "ship nginx atomically, dnsmasq is a noted sibling" decision in §2.
- **Confirmation-box coupling.** The box already says "Nginx configuration and SSL certificates" — no box edit needed; this fix makes the box *true on Linux*, so `test_blank_reset_confirmation_accuracy.py` stays green and the new behavior aligns with it. No new lie introduced.
- **No `when: install_nginx`** is intentional; gate #4 protects it. The only "risk" is a reviewer disagreeing with the doctrine — addressed in §1.

---

## 6. Verification recipe

```bash
# 1. New gate passes, and the whole blank-reset gate cluster stays green
python3 -m pytest \
  tests/anatomy/test_blank_reset_nginx_paths.py \
  tests/anatomy/test_blank_reset_data_dirs.py \
  tests/anatomy/test_blank_reset_confirmation_accuracy.py \
  tests/anatomy/test_blank_reset_plist_discovery.py \
  tests/anatomy/test_blank_reset_autodeps_sync.py \
  -q

# 2. Stock-Jinja trap guard (no new vars added, but the suite must stay green)
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 3. Full anatomy suite stays green
python3 -m pytest tests/anatomy -q

# 4. Playbook still parses
ansible-playbook main.yml --syntax-check

# 5. (manual, read-only) Confirm the paths resolve as expected per OS — DO NOT RUN blank.
#    Just eyeball the rendered values; never execute the blank path.
grep -n "nos_nginx_etc_dir\|nos_nginx_log_dir" tasks/blank-reset.yml
grep -n "nos_nginx_etc_dir\|nos_nginx_log_dir" tasks/_platform.yml
```

**Forbidden during verification:** no `blank=true`, no live nginx restart, no `rm` on the host. The gate is static; that is the whole point.

---

## 7. Commit

Single surgical commit on `feat/v0.7-overnight` (Conventional Commits, subject ≤50, body ≤6 bullets, no Co-Authored-By, no --author, **no push**):

```
fix(blank): platform-aware nginx wipe paths

- blank-reset hardcoded {{ homebrew_prefix }}/etc/nginx — on Linux
  that is /usr/local, but host nginx lives at /etc/nginx → vhosts,
  ssl/, logs orphaned on a Linux blank
- swap to nos_nginx_etc_dir / nos_nginx_log_dir (already set by
  _platform.yml before blank-reset runs); macOS byte-identical
- keep removals unconditional (a flipped install_nginx must still
  wipe stale vhosts) — pinned by the new gate
- gate: tests/anatomy/test_blank_reset_nginx_paths.py
```

If the dnsmasq sibling is *not* folded in, add a one-line `# TODO(v0.7): dnsmasq path twin` note in the plan's follow-up tracker rather than the code.
