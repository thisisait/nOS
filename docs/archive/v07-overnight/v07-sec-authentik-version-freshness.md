# Plan — Authentik version-pin freshness (v0.7 overnight)

**Status:** PLAN (not implemented). Branch: `feat/v0.7-overnight`.
**Owner:** pazny. **Confirmed item:** `v07-sec-authentik-version-freshness`.
**Class:** doc/inventory citation drift around a security-critical version pin —
same shape as the MariaDB CVE-citation gate (`test_mariadb_cve_citation_sync.py`).

---

## 1. Problem / why

Authentik is the **most security-critical** service in nOS — every `native_oidc`,
`header_oidc`, and `forward_auth` route is gated by it (`priority: "critical"` in
`docs/llm/security/versions.json`). Its version pin therefore carries a CVE story,
and that story is duplicated across several surfaces. The operative pin was bumped
to **`2026.5.2`** (supersedes the `2025.12.4` CVE-2026-25227 pin), but the bump did
**not** propagate to every surface. Three surfaces are confirmed drifted today:

| # | Surface | Reads | Should read | Impact |
|---|---|---|---|---|
| 1 | `roles/pazny.authentik/README.md:40` | `2025.12.4` + "Pinned for CVE-2026-25227" | `2026.5.2` | An operator/auditor reading the role README sees a **superseded** version and a **stale CVE rationale** — believes the running SSO core is an older release than it is. |
| 2 | `docs/llm/security/versions.json` (authentik `default_version`) | `2025.12.4` | `2026.5.2` | This file is the **component inventory** consumed by Wing's `/versions` dashboard (`files/anatomy/wing/index.html`, `bin/migrate.php`). The security dashboard reports the wrong version for the platform's most critical service. |
| 3 | `roles/pazny.authentik/templates/compose.yml.j2:19,85` | `{{ authentik_version \| default('2025.2') }}` | `default('2026.5.2')` (or no default — see §3) | The hardcoded **fallback** is a 2-EOL-major-versions-old release that the version-pins-proposal explicitly flags `VULNERABLE — EOL, CVE-2026-25227 no backport`. If `authentik_version` is ever unset, the compose renders a **known-RCE** image. |

The live value (`default.config.yml:2008` + `roles/pazny.authentik/defaults/main.yml:13`)
**agrees** at `2026.5.2`, so this is **not** a runtime regression and **not** a
version-pin-shadow (the `test_version_pin_no_shadow.py` gate is green). It is pure
**citation/inventory drift**: the surfaces that an auditor, the Wing dashboard, and a
fallback render path read are stale. The fix is to (a) reconcile the three drifted
surfaces and (b) add an anatomy gate that **pins all Authentik version surfaces in
sync** so the next bump cannot orphan a surface again — exactly the durable guarantee
`test_mariadb_cve_citation_sync.py` already gives MariaDB.

**Why now / why it's a security item, not cosmetic:** Authentik is the SSO blast
radius. A wrong version on the security dashboard delays CVE response (the operator
thinks they are already patched, or thinks they are on an EOL line when they are not).
The compose fallback (`default('2025.2')`) is a latent **supply-chain regression** —
one unset var away from booting a CVSS-9.1-RCE image.

---

## 2. Scope (explicit)

**In scope (repo edits only — live system stays READ-ONLY):**
- Reconcile the 3 drifted Authentik version surfaces to `2026.5.2`.
- Refresh the README CVE rationale to the truth (`2026.5.2` carries the
  CVE-2026-25227 fix forward; the `2025.12.4` line was the *introduction* of that
  fix, now superseded).
- Add one anatomy pytest gate that keeps every Authentik version surface in sync.

**Out of scope (do NOT do tonight — these are separate items / require live or
network access this run forbids):**
- Bumping Authentik to a *newer* release than `2026.5.2` (that is an upgrade, needs
  the `upgrades/authentik.yml` recipe + a supervised apply; `2026.5.2` is already
  the latest pinned). No version *change* — only **surface reconciliation**.
- A network/upstream EOL-or-newer-release lookup gate (no network overnight; that is
  the `upgrade-advisor` agent's job, on-demand — see §6 "deferred").
- Touching `upgrades/authentik.yml` (already correctly targets `2026.5.2`; verified
  at lines 104/169/207).
- The other `default('…')` fallbacks across other roles (separate sweep — this item
  is scoped to Authentik).

---

## 3. Approach (exact files + edits)

### 3.1 Reconcile surface #1 — role README

`roles/pazny.authentik/README.md` line 40, the variables table row:

```
| `authentik_version` | `2025.12.4` | Pinned for CVE-2026-25227 (CVSS 9.1 code injection) |
```
→
```
| `authentik_version` | `2026.5.2` | Latest; carries CVE-2026-25227 (CVSS 9.1 code injection) fix forward from the 2025.12.4 pin |
```

Rationale wording must stay **truthful**: `2026.5.2` is *not* "the fix for
CVE-2026-25227" (that was `2025.12.4`); it is the current release that *retains*
that fix and supersedes the pin. Mirror the comment style already in
`default.config.yml:2008` ("supersedes 2025.12.4 CVE-2026-25227 pin; current latest").

### 3.2 Reconcile surface #2 — security inventory JSON

`docs/llm/security/versions.json`, the `authentik` array element:
```
"default_version": "2025.12.4",
```
→
```
"default_version": "2026.5.2",
```
This is the only field that drifts; `version_var`, `image`, `priority`, etc. are
correct. This file feeds the Wing `/versions` dashboard, so the edit makes the
security dashboard report the truth.

> **Stock-Jinja trap N/A:** `versions.json` is plain JSON consumed by PHP/JS, not a
> var in `default.config.yml`/`default.credentials.yml`, so the
> `test_config_stock_jinja_only.py` rule does not apply. No new Ansible var is
> introduced by this plan at all.

### 3.3 Reconcile surface #3 — compose fallback default

`roles/pazny.authentik/templates/compose.yml.j2` lines 19 + 85:
```
image: ghcr.io/goauthentik/server:{{ authentik_version | default('2025.2') }}
```
**Decision — drop the dangerous literal fallback, fail-loud instead.** Both
`default.config.yml` (via `vars_files`, always loaded) and the role default
*always* define `authentik_version`, so the inline `default('…')` is dead code whose
only effect is to encode a **known-RCE EOL tag** as a silent fallback. Replace with
the mandatory-var form so an unset var fails the render rather than booting a
vulnerable image:
```
image: ghcr.io/goauthentik/server:{{ authentik_version | mandatory }}
```
`mandatory` is a **stock Ansible filter** and this template is *not* in the
`{{ vars }}` eager-resolve namespace (it is a role compose template rendered during
stack-up, not consumed by the plugin loader), so the stock-Jinja trap does not bite.
Both `image:` lines (server + worker) get the same edit — the gate (§4) asserts they
stay identical.

> Conservative alternative if `mandatory` is judged too aggressive for a compose
> template: change the literal to `default(authentik_version)` is circular, so use
> `default('2026.5.2')` (pin the fallback to the live value). The gate then asserts
> the fallback literal == the config pin so it can never re-rot to an EOL tag. The
> **`mandatory` form is preferred** (no second value to keep in sync); pick one in
> review. The gate is written to accept the chosen form (see §4).

### 3.4 No live mutation

Nothing here touches the running Authentik container. The bump to the *running*
image (if ever needed) is the `upgrades/authentik.yml` path under supervision — out
of scope. This item only reconciles **what the repo/docs/dashboard claim** against
the already-live `2026.5.2` pin.

---

## 4. The gate (NON-NEGOTIABLE — every fix ships a gate)

New file: **`tests/anatomy/test_authentik_version_freshness.py`**, modeled 1:1 on
`tests/anatomy/test_mariadb_cve_citation_sync.py` (same project pattern: ROOT-relative
paths, regex pin extraction, multi-surface sync assertions, no network, fast/offline).

A single source-of-truth constant `PINNED_VERSION = "2026.5.2"` drives every
assertion, so the **next** bump is a one-line edit here + the four surfaces, and the
gate fails until they all agree.

Tests:

1. `test_config_and_role_default_pins_agree` — `default.config.yml` `authentik_version`
   == role `defaults/main.yml` `authentik_version` == `PINNED_VERSION`. (Re-asserts
   the no-shadow invariant at the Authentik-specific level; cheap belt-and-suspenders.)
2. `test_readme_table_cites_pinned_version` — the README variables table row for
   `authentik_version` cites `PINNED_VERSION` and **does not** still cite the
   superseded `2025.12.4` as the *current* pin. (Catches surface #1 re-rotting.)
3. `test_security_inventory_reports_pinned_version` — `docs/llm/security/versions.json`
   authentik element `default_version` == `PINNED_VERSION`. (Catches surface #2.)
4. `test_compose_fallback_is_not_an_eol_tag` — neither `image:` line in
   `compose.yml.j2` carries a `default('2025.2')` / `default('2025.12.4')` (any
   superseded literal). Accept either remediation form: `| mandatory`, **or** a
   `default('<PINNED_VERSION>')` literal. Fail on any *other* literal. (Catches
   surface #3 + prevents an EOL fallback ever returning.)
5. `test_both_compose_image_lines_consistent` — the two `ghcr.io/goauthentik/server:`
   lines (server + worker) render the **same** tag expression. (Authentik's two
   containers must always bump together — the `upgrades/authentik.yml` notes call
   this out explicitly.)
6. `test_cve_rationale_is_truthful` — the README/config CVE comment, if it names
   CVE-2026-25227, frames `2026.5.2` as *carrying forward / superseding* the pin, not
   as "the fix" (the fix release was `2025.12.4`). Lightweight substring assertion to
   prevent the rationale re-drifting into a false claim.

Each test carries a docstring in the established surgeon tone naming the drift it
pins (cf. the MariaDB gate's class docstring).

**Why a gate and not just a fix:** the doctrine is explicit — "If you cannot gate it,
it is a PLAN not a fix." The MariaDB precedent proves the pattern works: the value can
agree across files while the *justification* or a *fallback* drifts, and only a
cross-surface sync gate catches it.

---

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `versions.json` is treated as agent-generated and an overnight scan overwrites the manual edit | low | The file is **committed** (`git ls-files` confirms) and last touched by a human commit (`0860fa34`). The scan pipeline is on-demand/agentic, not running overnight. Edit is idempotent — a future regen should emit `2026.5.2` too. |
| `\| mandatory` changes render behaviour if some path *relies* on the silent fallback | very low | Both `vars_files` (config) and role default always define the var; the fallback is provably dead today. The conservative `default('2026.5.2')` form (§3.3) eliminates even this residual risk if review prefers it. Gate accepts both. |
| Gate too strict — pins `2026.5.2` forever, blocking a legit future bump | by design | A real bump edits `PINNED_VERSION` + the four surfaces together; the gate then passes. This is the intended "bump-all-surfaces-atomically" contract, identical to the MariaDB gate. |
| Touching the README CVE wording introduces a *new* false claim | low | Wording is verified against `default.config.yml:2008` (the source-of-truth comment) + the pentest journal entries confirming `2025.12.4` was the CVE-2026-25227 fix release. Gate test #6 pins truthfulness. |
| Stock-Jinja vars trap | N/A | No new var in `default.config.yml`/`default.credentials.yml`. `mandatory` is a stock filter; the template is not in the `{{ vars }}` loader namespace. |

---

## 6. Deferred (explicitly NOT this item)

- **Live upstream EOL / newer-release freshness** (is `2026.5.2` itself stale vs
  upstream?) — needs network + is the `upgrade-advisor` agent's on-demand job
  (`files/anatomy/agents/upgrade-advisor/`), which queues into the upgrade queue for
  supervised apply. Overnight run is offline/no-network and forbids live mutation, so
  a true "is there a newer Authentik" probe is out of scope. This item pins
  **internal surface consistency** only.
- **Generalising the freshness gate to all `priority: critical` components** in
  `versions.json` (redis, traefik, mariadb already partially covered) — a good
  follow-up sweep, but scope tonight is Authentik.
- **Auto-deriving `versions.json` `default_version` from `default.config.yml`** at
  generation time (so the inventory can never drift from the pin) — architectural;
  belongs with the scan-pipeline refactor, not an overnight repo edit.

---

## 7. Verification recipe

All offline, no live system, no network — safe for unsupervised run:

```bash
cd /Users/pazny/projects/nOS

# 1. The new gate passes (and proves it actually fails pre-fix — run it BEFORE
#    editing the surfaces to confirm it catches the drift, then after).
python3 -m pytest tests/anatomy/test_authentik_version_freshness.py -v

# 2. The existing version-pin + MariaDB sibling gates stay green (no regression
#    in the shared pattern).
python3 -m pytest tests/anatomy/test_version_pin_no_shadow.py \
                  tests/anatomy/test_mariadb_cve_citation_sync.py -v

# 3. Full anatomy suite stays green.
python3 -m pytest tests/anatomy/ -q

# 4. Stock-Jinja gate green (proves no var trap introduced).
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 5. Playbook syntax-check clean (the compose.yml.j2 edit must not break render).
ansible-playbook main.yml --syntax-check

# 6. Confirm all four surfaces now read 2026.5.2 and no EOL fallback survives.
grep -n "authentik_version" default.config.yml roles/pazny.authentik/defaults/main.yml \
     roles/pazny.authentik/README.md
grep -n "default_version" docs/llm/security/versions.json | grep -i authentik
grep -n "goauthentik/server" roles/pazny.authentik/templates/compose.yml.j2
#   → none of the above may contain 2025.12.4 / 2025.2 as the operative tag.
```

Expected: gate #1 RED before the §3 edits (proves it catches the drift), GREEN after;
#2–#5 GREEN throughout; #6 shows `2026.5.2` everywhere and no `default('2025.2')`.

---

## 8. Commit shape (when implemented — separate from this plan commit)

```
fix(authentik): reconcile version-pin surfaces to 2026.5.2

- README + versions.json inventory + compose fallback lagged at the
  superseded 2025.12.4 CVE pin (live config is 2026.5.2).
- drop the EOL default('2025.2') compose fallback — a known-RCE tag one
  unset var from rendering; use | mandatory (fail-loud).
- refresh README CVE rationale: 2026.5.2 carries CVE-2026-25227 fix
  forward, it is not the fix release.
- gate: test_authentik_version_freshness pins all 4 surfaces in sync.
```

(Conventional Commits, subject 50 chars, surgeon-tone body, no Co-Authored-By,
no `--author`, branch-only — never pushed.)
