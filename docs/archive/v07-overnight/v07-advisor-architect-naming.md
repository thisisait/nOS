# Plan — advisor / architect agent naming: pin the dual-surface name & version contract

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Item: `v0.7 / advisor-architect-naming`
Author context: nOS, AIT. AgentKit A14 + the claude-CLI Pulse runtime are two
surfaces over ONE agent identity; this plan keeps them from drifting apart.

---

## 1. Problem / why

Every built-in agent exists as **two artifacts** that must agree on identity:

1. **Loose profile** `files/anatomy/agents/<name>.yml` — read by
   `files/anatomy/scripts/pulse-run-agent.sh` (the live claude-CLI Pulse
   runtime) and harvested into the Pulse catalog by
   `files/anatomy/scripts/discover-pulse-catalog.py` (it globs
   `files/anatomy/agents/*.yml` and keys each entry off the doc's `name:`).
2. **AgentKit definition** `files/anatomy/agents/<name>/agent.yml` — validated
   against `state/schema/agent.schema.yaml` by
   `tests/anatomy/test_agent_schema.py`; loaded by `App\AgentKit\AgentLoader`.

The two surfaces share the directory `files/anatomy/agents/` and are meant to
describe the **same** agent. Today they silently disagree on the two fields that
constitute the agent's stable identity — `name` and `version` — and nothing
gates the agreement. Verified divergences (live, this branch):

- **`version` field type mismatch (every agent).** Loose profiles use a
  **semver string** (`version: 0.1.0`) while the schema-bound dir `agent.yml`
  requires an **integer** (`version: 1`, `minimum: 1`). Two different meanings
  of "version" for one agent — the AgentKit value is a breaking-change counter
  (schema docstring: "Bumped on every breaking change to system prompt or tool
  roster"); the loose value reads like product semver. An operator reading
  `/agents` (dir) vs an audit log line from `pulse-run-agent.sh` (loose) sees
  conflicting version strings for the same run.
- **`upgrade-advisor.yml` / `upgrade-architect.yml` carry NO `version:` at
  all** — `grep -L '^version:' files/anatomy/agents/*.yml` returns exactly those
  two. Their dir `agent.yml` siblings DO (`version: 1`). So the version field is
  not just inconsistently typed, it's absent on one surface for the two
  upgrade-* agents that are the namesakes of this item.
- **Name-set divergence is silent.** Five loose profiles exist
  (`conductor`, `remediator`, `scout`, `upgrade-advisor`, `upgrade-architect`)
  but **seven** dir `agent.yml` files (those five + `inspektor` + `librarian`).
  That asymmetry is *correct today* by design — `inspektor`/`librarian` are
  `metadata.runner_status: deferred`, AgentKit-contract-only, no Pulse runner
  (CLAUDE.md "Known Tech Debt"; `test_scout_inspektor_librarian.py`). But the
  asymmetry is **load-bearing and ungated**: nothing asserts "every loose
  profile has a same-named dir `agent.yml`" or "every loose profile that lacks a
  dir sibling is a bug." Add a sixth loose profile with a typo'd name
  (`upgrade_advisor.yml`, `remediater.yml`) and the Pulse catalog would register
  a phantom agent with no AgentKit identity, no schema validation, and a
  `nos-<typo>` client_id that won't resolve in `authentik_agent_clients` — all
  green.
- **The `authentik_agent_clients` slug set is a THIRD copy of the name list**
  (`default.config.yml` ~L2227–2312): `nos-inspektor`, `nos-librarian`,
  `nos-scout`, `nos-upgrade-advisor`, `nos-upgrade-architect`, `nos-conductor`,
  `nos-remediator`. `pulse-run-agent.sh` derives `CLIENT_ID="nos-${AGENT_NAME}"`
  by default (L39). So the loose-profile `name:` is the join key into the
  Authentik client registry — a name typo on the loose profile breaks attributed
  identity at runtime (`actor=nos-<typo>` resolves to zero client rows), exactly
  the failure the SSO-attribution gate (`test_sso_doctrine.py`
  `…register_all_runners`) was built to prevent for the *clients* side but which
  is unguarded on the *profile* side.

Why it matters for an UNSUPERVISED overnight fleet: the agent name is the audit
join key across four stores (loose profile → Pulse catalog → `wing.db` events
`actor_id`/`source` → `authentik_agent_clients`). A drift here doesn't crash; it
**mis-attributes or strands** an autonomous run, which is worse than a crash for
a security/compliance posture. This is a naming-contract gap, not a behaviour
bug — the fix is a gate + minimal normalization, no live mutation.

Existing coverage and the exact hole:
- `tests/anatomy/test_agentkit_naming.py` pins tables, PHP namespace, the
  dir-layout `agents/<name>/{agent.yml,...}`, and the dash-URI scheme — but only
  on the **dir** surface; it never looks at the loose `*.yml` profiles.
- `tests/anatomy/test_agent_schema.py` validates each dir `agent.yml` against the
  schema — but the schema doesn't apply to loose profiles.
- `tests/anatomy/test_scout_inspektor_librarian.py` and
  `test_sso_doctrine.py` cover the deferred-runner contract and the client
  registry — but neither cross-checks loose-profile `name`/`version` against the
  dir sibling.

So: **no gate asserts the two on-disk surfaces agree on the agent's identity.**
That is the item.

---

## 2. Exact files / roles to touch

Repo-only. No role tasks, no live system, no playbook behaviour change beyond
data normalization that the playbook already tolerates.

**A. Normalize the loose profiles (data, 2 fields):**
- `files/anatomy/agents/conductor.yml` — `version:` field
- `files/anatomy/agents/remediator.yml` — `version:` field
- `files/anatomy/agents/scout.yml` — `version:` field
- `files/anatomy/agents/upgrade-advisor.yml` — ADD `version:` field
- `files/anatomy/agents/upgrade-architect.yml` — ADD `version:` field

**B. New gate (the fix's teeth):**
- `tests/anatomy/test_agent_name_version_contract.py` — NEW

**C. Documentation (record the contract so it's discoverable):**
- `docs/sso-and-attribution.md` — add a short "Two-surface name/version
  contract" note next to the existing agent-matrix / client-convention section
  (the doc the SSO gate already points operators to).
- Optionally one CLAUDE.md "Recently shipped doctrine" one-liner pointer (only
  if the operator wants it in the changelog; keep it a pointer, not prose).

**Read-only / no edit (confirm during impl, do not change):**
- `state/schema/agent.schema.yaml` — already correct (`version` integer ≥1); the
  fix conforms the loose profiles to *its* notion, it does not change the schema.
- `files/anatomy/scripts/pulse-run-agent.sh` / `discover-pulse-catalog.py` — the
  consumers; the gate locks what they rely on, no code change needed.

---

## 3. Approach

Decide the **canonical contract** first, then make data + gate enforce it. Two
defensible options for the `version` field; the plan picks one and the gate
encodes it. Open this for review explicitly:

**Decision (recommended): the loose-profile `version` becomes the SAME integer
breaking-change counter as the dir `agent.yml`, and the two MUST be equal.**
Rationale: one agent, one version number, one audit string. The semver `0.1.0`
on the loose profiles is cosmetic — nothing parses it (verified: no consumer
reads `version` from the loose profile; `pulse-run-agent.sh` and
`discover-pulse-catalog.py` key only on `name`). Collapsing to the integer
counter removes a meaningless second versioning vocabulary and makes the gate a
clean equality check.

Normalization edits (mechanical, behaviour-preserving):
- `conductor.yml` / `remediator.yml` / `scout.yml`: `version: 0.1.0` →
  `version: 1` (match the dir sibling, which is already `1`).
- `upgrade-advisor.yml` / `upgrade-architect.yml`: insert `version: 1` directly
  under the `name:` line (match the dir sibling).

The new gate `test_agent_name_version_contract.py` asserts, by walking
`files/anatomy/agents/` once:

1. **Loose ⊆ dir on name.** For every loose `*.yml`, a dir
   `<name>/agent.yml` exists whose `name:` equals the loose `name:` equals the
   filename stem. (Catches typo'd / orphan loose profiles — the phantom-agent
   failure mode.)
2. **Version present + integer + equal.** Every loose profile has a `version:`,
   it's an `int` (not a string), and it equals the dir sibling's `version:`.
   (Catches the `0.1.0`-vs-`1` drift and the two missing-version files.)
3. **Dir-runner-but-no-loose is allowed ONLY for deferred runners.** For every
   dir `<name>/agent.yml` WITHOUT a loose sibling, assert
   `metadata.runner_status == 'deferred'`. (Locks the
   `inspektor`/`librarian` asymmetry as intentional, and flips loud the instant
   someone adds a live-runner dir agent but forgets its loose Pulse profile —
   the inverse phantom.)
4. **Client-registry join key resolves.** For every loose profile `name:`,
   assert `nos-<name>` is present as a `slug`/`client_id` in
   `authentik_agent_clients` (parse `default.config.yml` with the repo's
   existing yaml-load helper used by other gates). This closes the loop on the
   `actor=nos-<name>` attribution join — the loose-profile counterpart to the
   existing client-side `…register_all_runners` gate.

The gate is **pure file read + yaml parse**, offline, no network, no docker —
fits the anatomy-gate mold (mirrors `test_agentkit_naming.py` structure: module
constants for paths, small focused functions, `pytest.skip` when an expected
file is legitimately absent so the suite stays green on partial checkouts).

Sequencing within the gate: read all loose + dir docs once into dicts keyed by
name, then run the four assertions over the dicts — avoids re-parsing and makes
the failure messages name the exact offending file.

---

## 4. Risks

- **Picking the wrong canonical `version` semantics.** If a future consumer
  *does* want product-semver on the loose profile, collapsing to integer is a
  one-way-ish call. Mitigation: it's reversible (re-add a distinct `semver:` key
  later); and the audit value of one number per agent outweighs a hypothetical
  unbuilt semver consumer. Flagged here for the operator to veto.
- **Over-tight gate strands a legitimate future shape.** E.g. a coordinator
  agent (schema supports `multiagent.type: coordinator`) that intentionally has
  no Pulse loose profile. Mitigation: assertion #3 already carves out
  "dir-without-loose is fine if deferred" — but a *live* coordinator with no
  loose profile would trip it. Resolve by widening the carve-out to
  `runner_status in {'deferred','agentkit-only'}` if/when such an agent lands;
  document the carve-out inline so the next author knows the lever.
- **`authentik_agent_clients` parse fragility.** `default.config.yml` is large
  and Jinja-laced (`{{ global_password_prefix }}_pw_…`). The gate must
  `yaml.safe_load` it the same way the existing config gates do (they tolerate
  the `{{ }}` because those sit inside quoted scalars) — reuse that loader, do
  NOT hand-roll a regex. If safe_load proves brittle, fall back to a scoped
  `slug:`-line grep within the `authentik_agent_clients:` block (lower fidelity
  but offline-stable).
- **No live behaviour change** — normalization touches only the `version`
  scalar, which no runtime code reads on the loose surface (verified). Zero risk
  to a running fleet; zero risk to `--syntax-check` (these files aren't loaded by
  the playbook directly — `discover-pulse-catalog.py` runs them at Pulse-register
  time and ignores `version`).
- **Stock-Jinja vars trap: N/A.** No new var in
  `default.config.yml`/`default.credentials.yml`; nothing for
  `test_config_stock_jinja_only.py` to catch.

---

## 5. Gates it needs (non-negotiable)

1. **`tests/anatomy/test_agent_name_version_contract.py`** (NEW) — the four
   assertions in §3. This IS the fix's gate; without it this is a plan, not a
   fix.
2. **Existing suite stays green** — in particular `test_agentkit_naming.py`,
   `test_agent_schema.py`, `test_scout_inspektor_librarian.py`,
   `test_sso_doctrine.py` must continue to pass (the normalization touches data
   they already read; the new integer `version` on loose profiles is invisible to
   them, but run them to be sure).
3. **`ansible-playbook main.yml --syntax-check` clean** — unchanged; the edited
   files aren't in the playbook load path, but the rule requires the check.

---

## 6. Verification recipe

```bash
# 0. Confirm the divergence the plan targets (pre-change, expect drift)
grep -E '^name:|^version:' files/anatomy/agents/*.yml
grep -L '^version:' files/anatomy/agents/*.yml          # upgrade-advisor, upgrade-architect
for d in files/anatomy/agents/*/; do \
  grep -HE '^name:|^version:' "${d}agent.yml" 2>/dev/null; done

# 1. New gate FAILS before the data fix (proves it bites)
python3 -m pytest tests/anatomy/test_agent_name_version_contract.py -q   # RED

# 2. Apply §2.A normalization, then the gate PASSES
python3 -m pytest tests/anatomy/test_agent_name_version_contract.py -q   # GREEN

# 3. Sibling naming/schema gates unaffected
python3 -m pytest \
  tests/anatomy/test_agentkit_naming.py \
  tests/anatomy/test_agent_schema.py \
  tests/anatomy/test_scout_inspektor_librarian.py \
  tests/anatomy/test_sso_doctrine.py -q                  # GREEN

# 4. Full anatomy suite + syntax (the standing overnight bar)
python3 -m pytest tests/anatomy -q                       # GREEN
ansible-playbook main.yml --syntax-check                 # clean

# 5. (read-only sanity) the Pulse catalog harvester still names each agent
#    off `name:` and ignores `version:` — no behaviour change
PYTHONPATH=files/anatomy python3 files/anatomy/scripts/discover-pulse-catalog.py \
  | python3 -c 'import sys,json;[print(e["plugin_name"]) for e in json.load(sys.stdin)]' \
  | sort -u                                              # names unchanged
```

Done-when: the new gate is RED on pre-change data and GREEN after the five
one-line normalizations; the four sibling gates + full anatomy suite +
`--syntax-check` stay green; no live system touched.

---

## 7. Commit (single, on `feat/v0.7-overnight`)

```
test(agents): pin loose↔AgentKit name/version contract

- loose agent profiles + dir agent.yml disagreed on name/version,
  ungated — a typo'd loose profile registers a phantom Pulse agent
- normalize 5 loose profiles to the integer version counter (was
  semver 0.1.0; upgrade-* carried none)
- new gate asserts loose⊆dir on name, version int+equal, dir-only is
  deferred-runner, nos-<name> resolves in authentik_agent_clients
- doc the two-surface contract in sso-and-attribution.md
```
(Subject ≤50, surgeon-tone bullets ≤6, no Co-Authored-By, no --author.
Lands on the branch only — never push.)
