# v0.7 plan — OpenTofu adopt-path attachment import (close the last punch-list item)

> **Type:** implementation plan (NOT implemented). Review-ready.
> **Branch:** `feat/v0.7-overnight`.
> **Confirmed item:** "Still open: adopt-path attachment import id (existing-tenant
> migrations only)" — CLAUDE.md § Known Tech Debt → OpenTofu post-cutover,
> and `docs/opentofu-authentik-cutover.md` § Open items.

## TL;DR

The adopt-path attachment-import *code* already shipped (commit `4feb1f7e`,
`tools/tofu-authentik-adopt.sh` emits one `authentik_outpost_provider_attachment`
import block per proxy provider with id `"<outpost_uuid>:<provider_pk>"`). But the
item is still flagged OPEN in CLAUDE.md, the runbook already calls it "CONFIRMED +
shipped", and the only gate is a **grep-the-source string match**
(`test_adopt_emits_attachment_imports`) that cannot prove the emitted import blocks
are *structurally* valid HCL or that the id shape is right per provider. There is
also a **latent contradiction** between two gates on how the registry is loaded.
This plan closes the item properly: reconcile the doc-vs-code drift, upgrade the
adopt gate from string-grep to a fixture-driven structural proof, and de-fragilize
the conformance gate's load-mechanism assertion. No live mutation; repo-only.

---

## 1. Problem / why

### 1a. Doc-vs-code drift (the headline)

- `CLAUDE.md:351` still reads *"Still open: adopt-path attachment import id
  (existing-tenant migrations only)."*
- `docs/opentofu-authentik-cutover.md:113-124` already documents it as
  *"~~Adopt-path attachment import id (P3, existing-tenant only)~~ — CONFIRMED +
  shipped."*
- The shipping commit (`4feb1f7e fix(tofu): adopt-path imports outpost attachments`)
  added the emission **and** the gate `test_adopt_emits_attachment_imports`.

So the source-of-truth operator file (CLAUDE.md) lies about the state of the
feature. A future operator/agent reading the tech-debt list will either re-do the
work or distrust the whole list. The "machinery doctrine" says state propagates via
commits — but the *record* of state must stay coherent or the doctrine erodes.

### 1b. The gate is grep-the-source, not structural

`tests/anatomy/test_tofu_registry_bridge.py::test_adopt_emits_attachment_imports`
asserts that four literal substrings exist in `tofu-authentik-adopt.sh`:
`authentik_outpost_provider_attachment`, `/outposts/instances/`,
`authentik Embedded Outpost`, `{op}:{p['pk']}`, `adopt_attach_`.

That pins *intent* but not *behavior*. It cannot catch:

- a regression that emits **malformed** `import {}` blocks (wrong key order, missing
  `to`/`id`, unbalanced braces) — the bash heredoc could drift and the grep stays
  green;
- the **id-shape-per-provider** invariant: the embedded outpost id must prefix
  *every* proxy provider's pk (`<outpost_uuid>:<pk>`), and the OAuth2 providers must
  **not** get an attachment block (they have no outpost binding). A bug that emitted
  an attachment for an oauth2 provider, or used the application slug instead of the
  provider pk, would pass the current grep;
- the **slug-sanitization** contract: `re.sub(r'[^a-z0-9_]','_', name.lower())` is
  what makes the tf address (`adopt_attach_<a>`) a valid HCL identifier. A name with
  a leading digit or a dot would produce an *invalid* tf address; the grep can't see
  it.

The fix for an existing-tenant migration is load-bearing: if the adopt path emits a
bad attachment import, the operator's `tofu plan` reads `N to add` for the
attachments (instead of no-op), they apply, and the read-modify-write outpost race
(trap #3) can silently drop forward_auth bindings → 9 services 404. The whole point
of the adopt path is a **no-op plan**; an untested emitter undermines that.

### 1c. Latent contradiction between two registry-load gates

While verifying the above I found a fragile assertion that is not red *today* but is
a trap:

- `test_tofu_registry_bridge.py::test_registry_loaded_via_template_lookup` asserts
  the task loads the registry via `lookup('template', ...)` **and**
  `lookup('file', ...)` is **absent**.
- `test_tofu_authentik_conformance.py::test_registry_not_play_scoped_loaded` (last
  line) asserts `"lookup('file'" in task and "from_yaml" in task`.

Both pass **only because** `tasks/tofu-authentik.yml` contains the string
`lookup('file'` inside a **comment** (line 70: *"lookup('template'), NOT
lookup('file')…"*). The conformance gate is matching documentation prose, not code.
If someone reflows that comment, the conformance gate flips red spuriously while the
code is correct — and worse, it currently *green-lights* a real `lookup('file')`
regression as long as the explanatory comment survives. This belongs in the same
fix because it is the same surface (the registry-load mechanism for the tofu engine)
and a reviewer touching adopt-path tests will trip over it.

---

## 2. Exact files / roles to touch

All repo-only. No role tasks change behavior; no live system touched.

| File | Change |
|---|---|
| `CLAUDE.md` | Line ~351: move "adopt-path attachment import id" from *Still open* to *shipped* (strike it through in the punch-list sentence, matching the runbook). |
| `docs/opentofu-authentik-cutover.md` | Tighten § Open items so it does not read as both "shipped" and listed under a "Still open" heading — confirm the strikethrough is under a clearly-closed sub-section, and add a one-line pointer to the new structural gate. |
| `tools/tofu-authentik-adopt.sh` | Extract the three python emitter snippets (proxy+attachment, oauth2, application) into a **single importable helper** so they can be unit-tested without curl/a live tenant. Smallest viable shape: a `tools/tofu_authentik_adopt_emit.py` module exposing pure functions `proxy_import_blocks(providers, outpost_id)`, `oauth2_import_blocks(providers)`, `application_import_blocks(apps)`, each returning a `list[dict]` of `{to,id}` (or rendered `import {}` text). The bash script `python3 -c`-imports them so behavior stays 1:1. (If extraction is judged too invasive for v0.7, fall back to a fixture-driven gate that *runs the existing inline python* over canned JSON via `subprocess` — see §3 option B.) |
| `tests/anatomy/test_tofu_registry_bridge.py` | Replace/augment `test_adopt_emits_attachment_imports` with the structural proof (see §4). Keep the existing string asserts as a cheap first line of defense. |
| `tests/anatomy/test_tofu_authentik_conformance.py` | Fix `test_registry_not_play_scoped_loaded`: assert against **code lines only** (strip `#` comments before matching `lookup(...)`), and align it with the registry-bridge truth — the load mechanism is `lookup('template')`, not `lookup('file')`. |

> No `default.config.yml` / `default.credentials.yml` vars are added, so the
> stock-Jinja trap (`test_config_stock_jinja_only.py`) is not in scope — but the
> suite still runs it green.

---

## 3. Approach

### Option A (preferred) — extract the emitter to a tested pure module

1. Create `tools/tofu_authentik_adopt_emit.py` with three pure functions that take
   already-parsed JSON (`results` lists from the Authentik API) plus the resolved
   `outpost_id`, and return the import blocks. Mirror the *exact* current logic:
   - slug sanitize `re.sub(r'[^a-z0-9_]','_', name.lower())`;
   - proxy → TWO blocks (`authentik_provider_proxy.adopt_<a>` id `<pk>`,
     `authentik_outpost_provider_attachment.adopt_attach_<a>` id `<outpost>:<pk>`);
   - oauth2 → ONE block (`authentik_provider_oauth2.adopt_<a>` id `<pk>`), **no**
     attachment;
   - application → ONE block (`authentik_application.adopt_app_<a>` id `<slug>`).
2. Rewrite the three `curl … | python3 -c "…"` blocks in the bash script to
   `curl … | python3 -c "import sys,json; from tofu_authentik_adopt_emit import …"`
   (with `PYTHONPATH` pointed at `tools/`), preserving the `while read … emit` shape
   OR have the module emit the full `import {}` text directly. **Behavior must stay
   byte-identical** — verify by diffing generated output before/after against a
   captured fixture (operator-side, manual; not in CI since CI has no tenant).
3. Keep `emit()` in bash as the single heredoc writer so the on-disk
   `imports.generated.tf` format is unchanged.

Why extraction: it converts an untestable shell pipeline into a unit-testable
contract, which is the only way to *gate* the id-shape and no-attachment-for-oauth2
invariants. This matches the repo's existing pattern (the gen-registry logic lives
in a python tool, not inline shell).

### Option B (fallback if extraction is rejected in review)

Drive the **existing** inline emitters via `subprocess`: the gate writes canned
provider/app JSON to a temp file, runs the relevant `python3 -c` snippet (copied
from the script, or `sed`-sliced) over it, and asserts on the emitted text. Less
clean (duplicates the snippet or couples to script line ranges) but needs zero
production code change. Use only if §A is deemed out-of-scope for an overnight v0.7
slice.

### 3c. Doc reconciliation

Mechanical: flip the CLAUDE.md sentence and verify the runbook's § Open items reads
unambiguously closed. Add the new gate name to the runbook trap list so future
archaeology finds it.

---

## 4. The gates it needs (NON-NEGOTIABLE — every fix ships a gate)

New / changed `tests/anatomy/` gates (all offline, no tenant, no network):

1. **`test_adopt_proxy_emits_provider_and_attachment`** — given a fixture proxy
   provider `{pk: "P1", name: "Calibre Web"}` and `outpost_id="O1"`, assert the
   emitter returns exactly two blocks: `authentik_provider_proxy.adopt_calibre_web`
   id `P1`, and `authentik_outpost_provider_attachment.adopt_attach_calibre_web` id
   `O1:P1`. Pins the **id shape per provider** and the **slug sanitization**
   (space → `_`, lowercased).
2. **`test_adopt_oauth2_emits_no_attachment`** — given a fixture oauth2 provider,
   assert exactly ONE block (the provider) and **zero** attachment blocks. Pins that
   native_oidc providers never get an outpost binding (mode coherence — the same
   invariant `test_module_never_creates_oauth2_for_forward_auth` enforces for the
   steady-state module).
3. **`test_adopt_application_imports_by_slug`** — assert `authentik_application`
   import id is the **slug** (not pk), tf address `adopt_app_<sanitized-slug>`.
4. **`test_adopt_import_blocks_are_wellformed_hcl`** — render the emitted blocks
   through the bash `emit()` format (or assert the helper's text form) and check each
   block has exactly `to =` and `id =`, balanced braces, and a tf address matching
   `^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$` (valid HCL resource address). This is the
   structural proof the current grep cannot give.
5. **Keep** the existing literal-substring asserts inside
   `test_adopt_emits_attachment_imports` (cheap regression tripwire on the script
   wiring) — they complement, not replace, the structural gate.
6. **`test_registry_load_mechanism_consistent`** (in conformance, replacing the
   fragile tail of `test_registry_not_play_scoped_loaded`) — strip `#`-comment lines
   from `tasks/tofu-authentik.yml`, then assert on the **remaining code**:
   `lookup('template'` present, `from_yaml` present, and a bare `lookup('file'` in
   code is **absent**. This makes the conformance gate and the registry-bridge gate
   agree and immune to comment edits.

> If Option B is taken, gates 1-4 run the inline snippet via `subprocess` over the
> fixture JSON and assert on stdout — same assertions, different driver.

### Suite + syntax invariants (must stay green)

- `python3 -m pytest tests/anatomy/ -q` — full anatomy suite green.
- `ansible-playbook main.yml --syntax-check` — clean (no task changes, but the
  bash-extraction must not alter `tasks/tofu-authentik.yml`; if it does not, syntax
  is unaffected — verify regardless).
- `tools/ci-local.sh` (filter-load probe + syntax-check) optional but recommended
  before the eventual release push (not part of this overnight slice).

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| **Extraction drifts behavior** — the refactored emitter produces different `import {}` output than the inline snippet, silently breaking a future operator's adopt run. | Capture a fixture of real API JSON (operator-side, one-time) and diff old-vs-new emitter output to byte-equality before merging. The unit gates lock the contract going forward. If any doubt, take Option B (zero production change). |
| **Adopt path is operator-run, never CI-run** — there is no live tenant in CI, so the *end-to-end* no-op-plan proof stays manual. | This is inherent (documented in the runbook). The plan does NOT claim to gate the live no-op; it gates the **emitter correctness**, which is the part that was untestable. The live no-op verification stays an operator step (§6). |
| **Touching two test files at once** — risk of a merge-time contradiction reappearing. | The whole point of gate #6 is to make the two registry-load assertions *agree*; land them in one commit and run the full suite. |
| **CLAUDE.md edit conflicts** with other v0.7 overnight branches editing the same tech-debt block. | The edit is a single-line strike; rebase-friendly. Land it in its own commit so a conflict is trivial to resolve. |
| **Over-scoping** — turning a doc-reconcile into a refactor. | Option B exists precisely to keep the slice small if review wants minimal production-code churn. The doc reconcile + gate #6 alone already close the *stated* item; §A is the quality upgrade. |

---

## 6. Verification recipe

**Repo-side (CI-equivalent, runs in the sandbox, no tenant):**

```bash
cd /Users/pazny/projects/nOS

# 1. New + changed gates pass
python3 -m pytest tests/anatomy/test_tofu_registry_bridge.py \
                  tests/anatomy/test_tofu_authentik_conformance.py -q

# 2. The two registry-load gates now agree (no comment-dependence):
#    temporarily prove gate #6 by stripping the comment line and re-running —
#    it must STILL pass (code, not prose, carries the assertion).

# 3. Full anatomy suite green
python3 -m pytest tests/anatomy/ -q

# 4. Playbook still parses
ansible-playbook main.yml --syntax-check
```

**Operator-side (one-time, against the live tenant — NOT part of CI, NOT run
overnight, requires the running Authentik + `~/.nos/secrets.yml`):**

```bash
# Confirms the emitter still produces a no-op adopt plan end-to-end.
# READ-ONLY: import + plan only, never applies (script is set -e, no apply path).
tools/tofu-authentik-adopt.sh --plan
# Expect: generated.tf written, /tmp/adopt-plan.txt → "Plan: 0 to add, 0 to
# change, 0 to destroy" once attributes are reconciled. The attachment blocks
# must appear as IMPORTED (in state), not "N to add".
```

**Doc coherence check:**

```bash
grep -n "adopt-path attachment import" CLAUDE.md         # must read as shipped/struck
grep -n "Adopt-path attachment import id" docs/opentofu-authentik-cutover.md
```

---

## 7. Commit shape (when implemented — land on `feat/v0.7-overnight`, never push)

Conventional Commits, ≤50-char subject, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`. Suggested split:

1. `test(tofu): structural gate for adopt-path import blocks`
   - grep gate proved only intent; emitter was untestable shell.
   - extract emitter to `tofu_authentik_adopt_emit.py` (behavior 1:1).
   - pin id shape `<outpost>:<pk>`, oauth2-no-attachment, slug sanitize, HCL addr.
2. `fix(tofu): de-fragilize registry-load conformance gate`
   - conformance asserted `lookup('file')` against a COMMENT, not code.
   - strip comments before matching; align with the registry-bridge truth.
3. `docs(tofu): mark adopt-path attachment import shipped`
   - CLAUDE.md still listed it open; runbook already says shipped.
   - reconcile + point at the new structural gate.
