# Straighten the benders

**A workflow spec, not a fix.** A later session runs this after a context
compact; it assumes nothing from the conversation that wrote it.

The findings below were verified on `fix/ci-linux-edge` (== `origin/dev`),
2026-09-01. Every ✅ is a measurement, not a reading.

---

## 1. What is bent

Four shapes, one family: **something is spelled twice and nothing joins the
spellings.**

### B1 — identity is spelled four ways

A service has a flag suffix, a manifest `id`, a compose fragment stem and a
container name. `state/manifest.yml` already carries `id` + `install_flag` +
`container_name(s)` + `stack` + `port_var` + `domain_var` — it is *almost* the
join and no consumer uses it as one.

- ✅ `install_redis` is declared in no config layer (real toggle: `redis_docker`).
  `state/manifest.yml:73` names it; `roles/pazny.uptime_kuma/tasks/monitors.yml:302`
  and `state/gdpr-erasure-map.yml:171` branch on it via `| default(false)`.
  The Redis monitor and the Redis erasure pass have never run. Exit 0 throughout.
  It is the **only** manifest `install_flag` absent from `default.config.yml`
  (checked: 65 rows).
- ✅ 20 declared `install_*` flags have no manifest row. Most are host tooling
  (`install_node`, `install_php`); `install_spacetimedb` and `install_qdrant`
  are services, and `spacetimedb` has a loaded plugin.
- `tasks/stacks/prune-disabled.yml` + `filter_plugins/nos_prune_guard.py::_sep_insensitive`
  guess the fragment stem from the flag; the guess cannot reach `calibre-web`,
  `open-webui`, `tileserver`. (The same file already derives *containers*
  exactly, from the removed fragment's `services:` keys — the flag→fragment hop
  is the only guess left.)
- `roles/pazny.traefik/vars/main.yml:85-86` declares `open_webui` **and**
  `openwebui`; `:306` keeps a hand-maintained exception table for that mapping.

### B2 — gates that assert on source text

✅ Deleting the whole `selectattr('container_name','defined')` harvest from
`prune-disabled.yml` left `test_prune_disabled_guard` **green** (15 passed): the
surviving *comment* satisfies `assert "container_name" in TASK.read_text()`.
✅ 22 asserts across 16 files share that narrow shape; 1119 `read_text()` calls
in `tests/` overall. **Most of them are fine** — §4 bounds which are not.

### B3 — readers disagree about one fact

- ✅ `~/.nos/state.yml` vs `config.yml` cost 24 false smoke failures (fixed,
  `a4d84dd7`).
- ✅ Open: the Wing hub red-count says 10, its own query says 11. `loop:review`
  declares no `findings_exit_codes` (the `[1,3]` in `loop-base` is on
  `propose`), so rc=2 is a failure and the page is wrong.
- `tools/estate-status.py:338` resolves three config layers;
  `discovery-scan.py` and `nos-smoke.py` resolve two and collapse absent→false.
- `cortex_port`, `backrest_port`, `stalwart_port_smtp` resolve `None`; their
  probes are dropped silently.

### B4 — two mechanisms, one outcome

- `authentik_engine` **or** `manage_authentik_with_tofu`, with
  `test_blank_reset_tofu_state.py:113` keeping the legacy name alive.
- Two byte-identical blueprint trees (`roles/pazny.authentik/templates/blueprints/`
  and `files/anatomy/plugins/authentik-base/blueprints/`); the doctrine points
  at the dead one.
- `blank` is both user input and derived fact, arbitrated by 25 lines of assert.
- ✅ `tests/anatomy/test_a_pin_is_declared_once.py:49` keys on
  `_(version|image_version|image_tag|repo_ref)`. Bare `_image` escapes:
  `snappymail_image` (`default.config.yml:2039` + `roles/pazny.snappymail/defaults/main.yml:24`)
  and `backup_alpine_image` (`default.config.yml:3276` +
  `roles/pazny.backup/defaults/main.yml:108`) are each declared twice, gate green.

### B5 — defaults (from `docs/doctrine/organs.md` §4-6)

Declared-and-gated, after derivation was refused on evidence. Census L0 9 /
L1 11 / L2 39 / withheld 6. **Not in scope here** except as a consumer of §3's
reader — its prerequisites (plugin manifests for `ears`/`iiab_terminal`/`opencode`,
the sink-class decision) are operator decisions, not agent work.

---

## 2. Ordering — probe it, do not inherit it

The working hypothesis is *"the manifest row is the single identity join, and it
is upstream of nearly everything."* Partly true and worth narrowing before any
edit:

| workstream | depends on the join? |
|---|---|
| B1 consumers (prune, traefik, kuma, erasure map) | **yes** |
| B3 config-layer disagreement | **shares the reader**, not the manifest |
| B3 `loop:review` exit codes, `None` ports | no |
| B4 duplication (pins, blueprints, engine flag, `blank`) | no |
| B2 gate shape | no — but touches tests the others rewrite, so it runs **last** |

So: one workflow, five phases, and **Phase 0 exists to falsify the table above**
before Phase 1 spends anything on it.

---

## 3. The workflow

One workflow. Serial spine (P0 → P1 → P5), one fan-out (P2), two independents
(P3, P4). Read-only until a phase's gate exists.

### Return schema — every agent, every phase

One JSON object on stdout, nothing else:

```json
{
  "phase": "P2a",
  "findings": [{
    "id": "B1-prune-stem",
    "claim": "prune cannot reach calibre-web",
    "verified": true,
    "evidence": "filter_plugins/nos_prune_guard.py:64 + `pytest -k prune` output",
    "proposal": "read fragment stem from manifest",
    "blocked_on": null
  }],
  "gates_left": [{
    "test": "tests/anatomy/test_x.py",
    "retro_red": "exact mutation that makes it fail, and the observed failure"
  }],
  "human_decision": ["one line each, or []"],
  "touched": ["paths written"]
}
```

`verified: true` requires a command in `evidence`. A finding without one is
`verified: false` and does not authorise an edit.

### P0 — ordering probe (1 agent, read-only, ~30 min)

Build the real dependency edges between B1–B4 by grepping consumers, not by
reasoning. Output: the §2 table, confirmed or corrected, with evidence per row.
**Human checkpoint:** operator accepts the order or reorders. Nothing else runs
until this returns.

### P1 — the identity join (1 agent, serial)

The manifest row becomes the only place a service's four spellings meet.

1. Close coverage: `redis` (decide with the operator — declare `install_redis`,
   or point the row at `redis_docker`), `spacetimedb`, `qdrant`.
2. Add the one missing field: the compose fragment stem (`fragment:`), defaulted
   to `id` and stated explicitly only where they differ (~6 rows). Schema
   (`state/schema/manifest.schema.json`) is `additionalProperties: false` — it
   must be extended in the same commit.
3. **One reader**, not a framework: extend `tools/estate-status.py`'s existing
   three-layer `resolve_flag` into a small importable module used by P2 and P3.
   No new dependency, no class hierarchy.

Gates in §5: G1, G2.

### P2 — consumers switch to the reader (fan-out ×4, after P1)

| id | consumer |
|---|---|
| P2a | `tasks/stacks/prune-disabled.yml` + `nos_prune_guard._sep_insensitive` |
| P2b | `roles/pazny.traefik/vars/main.yml` (the dual declaration + the `:306` table) |
| P2c | `roles/pazny.uptime_kuma/tasks/monitors.yml` + `state/gdpr-erasure-map.yml` |
| P2d | `tools/discovery-scan.py`, `tools/nos-smoke.py` (two layers → three) |

Each returns the schema above independently. P2a touches a **destructive** path:
it may propose but must not merge without the operator reading the plan (§6).

### P3 — readers disagree (1 agent, independent of P1)

`loop:review` declares `findings_exit_codes`; the `None`-resolving ports
(`cortex_port`, `backrest_port`, `stalwart_port_smtp`) either resolve or their
probes report **dropped**, never silently vanish. Gate G4, G5.

### P4 — duplication (1 agent, independent)

Pin regex hole (G3). Then *report only*, no deletion: which blueprint tree is
live, whether `manage_authentik_with_tofu` has any live reader,
whether `blank`'s 25 asserts collapse. Deleting a blueprint tree needs a
converge to prove which one renders — out of scope here (§6).

### P5 — gate shape (1 agent, LAST)

Bounded by §4.

---

## 4. Where the gate-shape fix stops

**Rule.** A source-text assert is rewritten only if the artifact it guards can
**destroy, expose, or silently skip**. Everything else keeps its assert and gets
one line in the report.

- destroy: prune, `nos --remove=*`, tofu destroy guard, blank reset
- expose: auth, tokens, secrets, TLS, forward-auth stacking
- silently skip: a guard whose failure mode is exit 0 with nothing done

Of the ✅ 22 narrow-shape asserts, the expected qualifying set is single digits.
**If more than 10 qualify, P5 stops and reports** rather than opening a
refactor. The 91 general-shape asserts are explicitly out of scope.

Replacement shape: assert on the **parsed artifact** — the loaded YAML, the
rendered template, the tool's `--json`. Per the standing doctrine, a detector
that matches text reports the description as the fact.

---

## 5. Gates, and how each is retro-verified RED

Every gate is run against the **pre-fix tree** (`git stash` the fix, run, observe
the failure, restore). A gate never observed failing is not a gate.

| id | gate | retro-RED mutation |
|---|---|---|
| G1 | `test_every_manifest_flag_is_declared.py` — every `install_flag` in `state/manifest.yml` resolves in a config layer | already RED today on `install_redis`; re-verify by reverting the row |
| G2 | `test_manifest_is_the_identity_join.py` — the reader returns a fragment stem for `calibre-web`, `open-webui`, `tileserver`, and the prune plan for each is non-empty | delete the `fragment:` field from one row → that service's plan goes empty |
| G3 | widen `test_a_pin_is_declared_once.py` KEY to include bare `_image` | RED today: `snappymail_image`, `backup_alpine_image` |
| G4 | `test_readers_resolve_the_same_layers.py` — estate-status / discovery-scan / nos-smoke agree on one flag's resolved value and layer trail | point one tool back at two layers |
| G5 | extend `test_every_job_declares_what_it_is.py` — a job whose consumer counts non-zero exits as failure must declare `findings_exit_codes` | delete the declaration from `loop:review` |
| G6 | (P5) whichever asserts §4 admits, re-expressed against the parsed artifact | re-apply the ✅ P0 mutation: delete the harvest, keep the comment — must go RED |

G2 and G6 are the two that matter: both are gates written *because* the old one
passed on a broken tree.

---

## 6. What must NOT be automated

- `files/anatomy/apex/ruling.yml` — signed. Read it; propose a diff to the
  operator; never write it.
- `config.yml` — operator property. Every P1/P2 proposal that would change it is
  a `human_decision` line, not an edit.
- Anything destructive: no converge, no `nos --remove`, no `docker`, no sudo,
  no `tofu apply`. P2a proposes a prune plan; it does not run one.
- Deleting either blueprint tree — needs a converge to prove which renders.
- The organs §6 decisions (sink class, the three missing plugin manifests).
- `install_redis` vs `redis_docker`: the rename direction is the operator's.

## 7. Honest ceiling

No phase here can prove a live effect — there is no converge. Every gate proves
**shape**. The Redis monitor and the Redis erasure pass stay unproven until
something converges; G1 only proves they would now be *reached*.
