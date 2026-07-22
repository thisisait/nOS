# Plan — Gate the blank-reset ⇄ external-storage override contract

Status: PLAN (not implemented). Branch: `feat/v0.7-overnight`.
Scope: repo edits only. No live mutation. No blank. Ships with a pytest anatomy gate.

## 1. Problem / why

A blank reset (`nos --remove=data --confirm`) must wipe a service's
data **wherever that data actually lives**. On an external-storage install
(`configure_external_storage: true`, `external_storage_root: /Volumes/SSD1TB`)
the real data is on the SSD, not under `$HOME`. Two task files cooperate to make
this work:

- `tasks/stacks/external-paths.yml` — a flat list of `set_fact` overrides that
  rewrite every data-path var (`mariadb_data_dir`, `gitea_data_dir`,
  `prometheus_storage_path`, …) to `{{ external_storage_root }}/<svc>`.
- `tasks/blank-reset.yml` — builds `_blank_dirs` (a ~50-clause ternary soup) and
  wipes each path. It `include_tasks: tasks/stacks/external-paths.yml` **first**
  (gated `external_storage_root is defined and …length > 0`) so the overridden
  vars are visible when `_blank_dirs` resolves.

The ordering invariant is already pinned (`test_blank_reset_data_dirs.py ::
test_external_paths_included_before_blank_dirs`) and the install-flag → wipe-clause
contract is pinned (`test_every_bind_mount_service_is_wiped`). **What nothing
pins is that the two var-sets agree** — i.e. that every var
`external-paths.yml` redirects to the SSD is actually consumed by a `_blank_dirs`
clause (or is an explicitly-classified keep), and vice-versa. The two lists are
hand-maintained in different files and drift silently.

Concrete drift measured against the current tree (`tasks/stacks/external-paths.yml`
vs the `_blank_dirs` body), reproducible by the helper in §6:

**(A) Overridden to the SSD but NOT referenced in `_blank_dirs`** (9 vars):

| var | SSD target | verdict |
|-----|-----------|---------|
| `calibreweb_books_dir` | `…/calibre` | **KEEP** — user library (blank doctrine: `~/calibre` survives) |
| `jellyfin_movies_dir` / `…_shows_dir` / `…_music_dir` | `…/media/*` | **KEEP** — user media (`~/media` survives) |
| `ollama_models_dir` | `…/llmModels` | **KEEP** — models (`~/.ollama`-class, opt-in wipe only) |
| `puter_config_dir` | `…/puter/config` | **COVERED** — child of `puter_data_dir` (`…/puter`), parent wipe reaches it |
| `loki_storage_path` | `…/observability/loki` | **ORPHAN BUG** — see below |
| `prometheus_storage_path` | `…/observability/prometheus` | **ORPHAN BUG** |
| `tempo_storage_path` | `…/observability/tempo` | **ORPHAN BUG** |

**(B) Referenced in `_blank_dirs` but NOT overridden in `external-paths.yml`**
(7 vars: `hermes_config_dir`, `pi_config_dir`, `snappymail_data_dir`,
`spacetimedb_data_dir`, `spacetimedb_keys_dir`, `stacks_dir`, `wing_app_dir`) —
these have no SSD override, so on an external install their data stays under
`$HOME`. For `stacks_dir`/`wing_app_dir`/`hermes_config_dir` (`~/.hermes` is
hardcoded upstream) that is **intentional**; for `snappymail`/`spacetimedb` it is
a latent gap (they get an SSD override never, so their bind-mounts stay on the
boot disk — acceptable today, but undocumented).

### The real bug this surfaces

The observability TSDBs are a genuine **orphan-on-external-storage**:
`external-paths.yml` redirects `prometheus_storage_path` / `loki_storage_path` /
`tempo_storage_path` to `{{ external_storage_root }}/observability/<tsdb>`, but
`_blank_dirs`' observability clause wipes only the **hardcoded HOME** path:

```yaml
(install_observability | default(true)) | ternary(
  [ansible_facts['env']['HOME'] + '/observability',
   grafana_data_dir | default(stacks_dir + '/observability/grafana/data')], [])
```

`grafana_data_dir` IS in the override map (so Grafana's SSD dir is wiped via the
var), but Prometheus/Loki/Tempo are wiped only at `$HOME/observability` — which
on an external install is **empty**. The TSDB data on the SSD survives the blank.
`blank=true` is the replicability contract ("wipes everything and reinstalls from
scratch"); this quietly breaks it for the three TSDBs on every external-storage
box.

So this item is two things: (1) a **gate** that pins the override⇄wipe contract
so it can't drift again, and (2) the **one-line fix** for the observability
TSDB orphan that the gate immediately demands.

## 2. Goal

- Add a pytest anatomy gate that cross-checks `external-paths.yml` against
  `_blank_dirs`, with an explicit, in-test **classification table** (KEEP /
  COVERED-BY-PARENT / WIPED) so every override var has a documented disposition
  and a new unclassified var fails loudly.
- Fix the Prometheus/Loki/Tempo external-storage orphan by wiping the overridden
  `*_storage_path` vars (not just `$HOME/observability`).
- Behaviour-preserving on a non-external (HOME) install; strictly more correct on
  the external-storage path.

## 3. Exact files / roles to touch

| File | Change |
|------|--------|
| `tasks/blank-reset.yml` | Extend the `install_observability` clause in `_blank_dirs` so it also lists `prometheus_storage_path`, `loki_storage_path`, `tempo_storage_path` (each `| default(stacks_dir + '/observability/<tsdb>')`). One clause edit, no new tasks. |
| `tests/anatomy/test_blank_reset_external_storage_override.py` | **New gate.** Parses both files; asserts the contract below. |
| `docs/active-work.md` (or the v0.7 backlog ledger) | Tick the item closed, point at this plan + gate. |

No role templates, no compose, no live mutation. The fix is a single Jinja
list-append inside an existing `set_fact`.

## 4. Approach

### 4.1 The fix (tasks/blank-reset.yml)

Replace the observability clause:

```yaml
(install_observability | default(true)) | ternary(
  [ansible_facts['env']['HOME'] + '/observability',
   grafana_data_dir | default(stacks_dir + '/observability/grafana/data'),
   prometheus_storage_path | default(stacks_dir + '/observability/prometheus'),
   loki_storage_path | default(stacks_dir + '/observability/loki'),
   tempo_storage_path | default(stacks_dir + '/observability/tempo')], [])
```

- On a HOME install these three vars are undefined → the `default()` resolves to
  `{{ stacks_dir }}/observability/<tsdb>`, which lives **under** `stacks_dir`
  (already the first element of `_blank_dirs`, wiped wholesale). So the new lines
  are no-ops on HOME installs — **byte-equivalent outcome**, just redundant-safe.
- On an external install the vars resolve to the SSD path and get wiped. Bug
  closed.
- `influxdb_data_dir` / `influxdb_config_dir` are already covered by the existing
  `install_influxdb` clause, so InfluxDB needs no change — but the gate will
  confirm it.

The `default()` fallbacks must mirror the role-default home (`stacks_dir +
'/observability/<tsdb>'`) so the stock-Jinja trap (CLAUDE.md) is respected:
`default` is a stock filter, the fallback string is literal — no `regex_*`, no
`| bool`. No new var enters `default.config.yml`, so
`test_config_stock_jinja_only.py` is untouched.

### 4.2 The gate (new test)

Static-parse both files (no Ansible/Docker — offline, fast, CI-portable, same
style as the sibling `test_blank_reset_*` gates):

1. **Extract** `override_vars` = the LHS of every `set_fact` key in
   `external-paths.yml` ending in `_dir` / `_path` (regex
   `^\s+([a-z0-9_]+(?:_dir|_path)):`), plus its RHS so we know the SSD subpath.
2. **Extract** `wipe_vars` = every `[a-z0-9_]+(?:_dir|_path)` token inside the
   `_blank_dirs: >-` folded body (reuse the proven extractor from
   `test_blank_reset_data_dirs.py::_extract_blank_dirs_expr`).
3. **Classification table in the test** — a dict assigning each override var one
   of: `WIPED` (must appear in `wipe_vars`), `KEEP` (user data the prompt
   promises survives — must NOT be wiped), `COVERED_BY_PARENT` (its SSD path is a
   child of another wiped dir; the test asserts the parent var is present and the
   subpath is a string-prefix child).
4. **Assertions:**
   - `test_every_override_var_is_classified` — every var the live
     `external-paths.yml` overrides is present as a key in the classification
     table. A new override with no entry fails here (forces the author to decide
     KEEP vs WIPE). This is the anti-drift core.
   - `test_wiped_overrides_appear_in_blank_dirs` — every `WIPED`-classified var is
     in `wipe_vars`. **This is the assertion that fails RED today** on
     prometheus/loki/tempo until §4.1 lands.
   - `test_keep_overrides_are_not_wiped` — every `KEEP` var is absent from any
     `state: absent` / `rm -f` line (mirrors the preserved-user-data doctrine;
     pins media/calibre/ollama).
   - `test_covered_by_parent_subpath_is_child` — for each `COVERED_BY_PARENT`
     var, its RHS SSD subpath starts with the parent var's subpath (so the parent
     wipe genuinely reaches it). Catches a future `puter/config` → `puter2/config`
     rename that escapes the parent.
   - `test_observability_tsdb_paths_wiped` — explicit regression pin for the bug:
     `prometheus_storage_path`, `loki_storage_path`, `tempo_storage_path` each
     appear in the `_blank_dirs` body.
   - (re-affirm) `test_external_paths_runs_before_blank_dirs` already lives in the
     sibling gate; the new test references it in a docstring rather than
     duplicating, to avoid two sources of truth.

The classification dict is the load-bearing artifact: it turns "two lists must
agree" into a reviewed, single-file contract that a new service author must edit
deliberately.

## 5. Risks

- **False KEEP entries.** If a future var is wrongly classified `KEEP`, the gate
  would let its SSD data orphan. Mitigation: the KEEP set is tiny and tied to the
  prompt's "Will remain" promise (media/calibre/ollama); the test docstring
  names the doctrine and the verdict table in §1 is the review record. Any add to
  KEEP is an explicit, reviewable diff.
- **`COVERED_BY_PARENT` brittleness.** Prefix-child matching on rendered subpaths
  assumes both vars use the same `{{ external_storage_root }}/…` shape. They do
  today (single source of truth in `external-paths.yml`). If a var stops using
  that root the prefix check fails loudly — desired (forces re-review), not a
  silent pass.
- **HOME-install redundancy.** The fix adds three list entries that resolve under
  `stacks_dir` on HOME installs (already wiped). Pure redundancy, zero behaviour
  change — verified by the syntax-check + the gate's HOME-path reasoning, not by
  a live blank.
- **No live verification of the actual wipe.** Per overnight rules we cannot run
  `blank=true`. The gate proves the *wipe list contains the right paths*; an
  operator-side external-storage blank is the only thing that proves the SSD dir
  physically disappears. Documented in §6 as a manual, operator-gated follow-up —
  NOT run here.
- **`stacks_dir` token in `wipe_vars`.** It is the first `_blank_dirs` element and
  is not a per-service override; the gate's classification table simply omits it
  (it is not in `override_vars`), so it needs no entry. No risk.

## 6. Gates it needs + verification recipe

Ships with: `tests/anatomy/test_blank_reset_external_storage_override.py` (the new
gate above). The change is gateable end-to-end → it is a fix, not a plan-only.

```bash
cd /Users/pazny/projects/nOS

# 0. Reproduce the drift the plan is built on (pre-fix diagnostic — should print
#    the prometheus/loki/tempo orphans under list (A)):
python3 - <<'PY'
import re
from pathlib import Path
ext = Path("tasks/stacks/external-paths.yml").read_text()
blank = Path("tasks/blank-reset.yml").read_text()
ext_vars = set(re.findall(r'^\s+([a-z0-9_]+(?:_dir|_path)):', ext, re.M))
body = re.search(r'_blank_dirs:\s*>-\n(.*?)\n- name:', blank, re.S).group(1)
blank_vars = set(re.findall(r'([a-z0-9_]+(?:_dir|_path))', body))
print("override-but-not-wiped:", sorted(ext_vars - blank_vars))
PY

# 1. New gate must be RED before §4.1, GREEN after.
python3 -m pytest tests/anatomy/test_blank_reset_external_storage_override.py -q

# 2. Full anatomy suite stays green (no sibling gate regressed).
python3 -m pytest tests/anatomy/ -q

# 3. Playbook still parses.
ansible-playbook main.yml --syntax-check

# 4. (manual, operator-gated, NOT part of this change) On a real external-storage
#    box: ls /Volumes/SSD1TB/observability/{prometheus,loki,tempo} before a blank,
#    run `nos --remove=data --confirm`, confirm the three dirs are gone.
```

Acceptance: step 1 GREEN after the §4.1 edit, step 0 prints an EMPTY
override-but-not-wiped set for the three TSDBs (KEEP/COVERED entries remain by
design), steps 2–3 clean.

## 7. Commit

One commit on `feat/v0.7-overnight` (this plan only, per the task — the fix +
gate land in a follow-up implementation commit):

```
docs(plan): gate blank-reset ⇄ external-storage drift

- external-paths.yml SSD overrides + _blank_dirs wipe list drift silently
- measured orphan: prometheus/loki/tempo TSDB data survives an external blank
- plan: classification-table gate + one-clause observability wipe fix
```
