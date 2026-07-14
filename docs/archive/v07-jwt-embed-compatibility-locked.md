# v0.7 — Lock the ONLYOFFICE JWT embed compatibility contract

- **Branch:** `feat/v0.7-overnight`
- **Item:** `v0.7 / sso / jwt-embed-compatibility-locked`
- **Status:** PLAN (do not implement) — review-ready
- **Author actor:** claude (overnight, unsupervised)
- **Related:** `roles/pazny.onlyoffice/`, `roles/pazny.nextcloud/tasks/post.yml`,
  `docs/plans/v07-euro-office-pilot-onlyoffice-toggle.md` (sibling — image/version
  toggle; THIS item is the *signing-contract* dimension, complementary not
  overlapping), devlog `docs/devlog/nos-core/2026/2026-06-13-euro-office-pilot.md`,
  existing gate `tests/anatomy/test_onlyoffice_connector_urls.py`.

---

## 1. Problem / why

ONLYOFFICE Document Server is **never logged into by end-users**. It is an
iframe-embedded editor backend: each host application (Nextcloud today; Outline /
BookStack are documented as future embedders in the role header) loads the editor
in a browser iframe and the two servers then call **each other server-to-server**.
Those server↔server calls are **not** Authentik-gated (the API endpoints
`/ConvertService.ashx`, `/coauthoring/CommandService.ashx`, etc. are reachable
without SSO by design) — they are secured **only by a shared-secret JWT**.

The trust therefore reduces to a **four-field signing contract** that must agree
on BOTH sides of every embed edge:

| Field | Docserver env | Host-app config |
|-------|---------------|-----------------|
| **secret** | `JWT_SECRET` | `jwt_secret` (NC: `occ config:app:set onlyoffice jwt_secret`) |
| **header** | `JWT_HEADER` (`Authorization`) | the app's `jwtHeader` setting |
| **in-body** | `JWT_IN_BODY` (`true`) | the app's `jwtInBody` / token-in-body setting |
| **algorithm** | `HS256` (docserver fixed) | the app's HMAC alg (HS256) |

Today nOS wires **one** of these four (the secret) and **only for Nextcloud**, and
**none of it is gated**. The concrete exposure:

1. **`JWT_HEADER` / `JWT_IN_BODY` drift is silent and total.** The docserver
   defaults are set as role vars (`onlyoffice_jwt_header: "Authorization"`,
   `onlyoffice_jwt_in_body: true`) and flow into the compose env. But the Nextcloud
   connector is **never told** the matching `jwtHeader` / `jwtInBody` — it relies on
   the NC connector's *own* defaults happening to equal the docserver's. They do
   today (both default to `Authorization` + in-body), so editing works. The instant
   either side's default shifts — a docserver env tweak, a euro-office fork default,
   or an NC connector-app upgrade — the JWT lands in a header/body the other side
   doesn't read → `403 "The document security token is not correctly formed"` on
   every open, with **no test failure and no playbook error** (the `occ` set is
   `failed_when: false`, `changed_when: false`).

2. **The euro-office fork swap is asserted JWT-compatible but ungated.** The sibling
   plan / role header call euro-office "JWT-contract-compatible." That compatibility
   is the load-bearing assumption that lets the image flip without re-wiring the
   embedders — yet **nothing pins** that the fork keeps `JWT_HEADER=Authorization`,
   `JWT_IN_BODY=true`, HS256. If a future euro-office build changes a JWT default,
   the flip silently breaks every embed and the operator sees only a 403 inside the
   iframe (the container is *healthy*, the secret *matches*, so every existing gate
   stays green).

3. **The secret-identity contract ("docserver `JWT_SECRET` == every embedder's
   `jwt_secret`") is enforced by prose, not a gate.** `main.yml` auto-generates
   `onlyoffice_jwt_secret` once and the Nextcloud `occ` task reuses that same var —
   correct today. But a future embedder (Outline/BookStack) added with a *different*
   secret var, or a copy-paste that points NC at the wrong secret, would not trip
   anything. The single-source-of-truth ("one secret, every embedder references the
   SAME var") is exactly the kind of cross-role invariant the anatomy gates exist to
   pin.

4. **No embedder beyond Nextcloud is wired at all, yet the role header advertises
   three.** The role docstring lists "Nextcloud, Outline, BookStack" as JWT-sharing
   embedders. Only Nextcloud is actually wired. This plan does **not** add the
   Outline/BookStack wiring (that is feature work, out of scope), but it **does**
   pin the contract shape so that when an embedder IS added it is forced through the
   same secret/header/in-body/alg source of truth — closing the door before the bug
   walks through it.

**Why now (v0.7):** the euro-office pilot makes the docserver image a moving target
for the first time. The signing contract was implicitly safe while there was exactly
one image with one set of JWT defaults and one embedder. The pilot breaks that
assumption. This item locks the contract **before** the flip is taken live, so a
JWT-default drift in the fork fails a fast offline gate instead of a silent 403 in
production.

This is a **gate-first, render-hardening** item — the canonical v0.7 `verify-ok` /
`-locked` class: the behaviour is believed correct **today** but is **ungated** and
one default-shift away from a silent embed outage. Per the overnight rule "if you
cannot gate it, it is a plan not a fix," the deliverable is (a) make the contract
**explicit on both sides** (push the docserver's `jwtHeader`/`jwtInBody` into the NC
connector so it stops relying on coincidental defaults), and (b) a **structural gate**
that pins all four fields across the docserver env and every embedder.

---

## 2. Exact files / roles to touch

All edits are **repo-only**; no live-system writes; nothing destructive.

### 2.1 `roles/pazny.onlyoffice/defaults/main.yml`
- The four contract vars already exist (`onlyoffice_jwt_enabled`,
  `onlyoffice_jwt_header`, `onlyoffice_jwt_in_body`, `onlyoffice_jwt_secret` lives in
  credentials). **ADD** an explicit, documented `onlyoffice_jwt_algorithm: "HS256"`
  var (currently implicit — the docserver hard-codes HS256; making it a named var
  gives the gate a single oracle and documents the contract). Stock-Jinja safe: a
  role default, loaded at stack-up (after core-up), plain literal, no filters.
- Strengthen the existing JWT comment block to name the **four-field contract** and
  point at the new gate + this plan as the authority.

### 2.2 `roles/pazny.nextcloud/tasks/post.yml`
- The "Point OnlyOffice connector at the document server (+ shared JWT)" loop
  currently sets `DocumentServerUrl`, `DocumentServerInternalUrl`, `StorageUrl`,
  `jwt_secret`. **ADD two more `occ config:app:set onlyoffice` items** so the
  connector is told the *matching* header + in-body, instead of relying on its own
  coincidental defaults:
  - `php occ config:app:set onlyoffice jwt_header --value={{ onlyoffice_jwt_header | default('Authorization') }}`
  - (in-body is the NC connector's default-on behaviour; set it explicitly only if
    the connector exposes a settable key — **verify the exact `occ` key name first**,
    see §3.1. If the connector has no settable in-body key, document that the
    docserver's `JWT_IN_BODY=true` matches the NC default and the gate asserts the
    docserver side stays `true`.)
- Keep `no_log: true` on the loop (the secret item is still present). The
  `loop_control.label` already slices `item.split(' ')[4]` for a readable,
  secret-free task label — the two new items keep that shape.

> **Live-key caveat (do this first):** the precise `occ` setting keys for the
> ONLYOFFICE NC connector are `jwt_secret`, and (to confirm) `jwt_header`. The
> implementer MUST confirm the exact key names against the deployed connector
> READ-ONLY before writing the task — `docker compose -p iiab exec -T -u www-data
> nextcloud php occ config:app:list onlyoffice` lists every current key. Do NOT
> invent a key name; if `jwt_header`/in-body keys don't exist in the installed
> connector version, fall back to "pin the docserver side + assert NC defaults match"
> and record that in the plan's §7.

### 2.3 `tests/anatomy/test_jwt_embed_contract.py` (NEW gate) — see §4.

### 2.4 `roles/pazny.onlyoffice/README.md` (+ one devlog cross-ref line)
- Document the four-field contract, the single-secret-source rule, and the euro-office
  JWT-compat assumption that the gate now pins. One-line "v0.7" note appended to the
  euro-office devlog tail (devlog is append-context only) so the narrative stays
  honest.

**Explicitly NOT touched (out of scope):**
- **Adding Outline / BookStack embedder wiring.** Feature work; this item only pins
  the contract shape so a future embedder is forced through the same source of truth.
  A gate sub-check asserts that IF an embedder references an onlyoffice JWT secret it
  references the canonical `onlyoffice_jwt_secret` var (not a private one).
- **The image/version `onlyoffice_flavor` toggle** — sibling plan
  `v07-euro-office-pilot-onlyoffice-toggle.md`. The two are complementary: that one
  flips the image safely; THIS one guarantees the JWT contract survives the flip.
- **Rotating the JWT secret on a live install** (a destructive-adjacent re-key that
  would need a coordinated docserver-env + every-embedder update). Out of scope;
  flagged in §7 as a separate, operator-gated track.

---

## 3. Approach

### 3.1 Make the contract explicit on both sides
The root structural defect is that **only one of the four fields crosses the edge**.
Today: docserver gets `JWT_SECRET`/`JWT_HEADER`/`JWT_IN_BODY` from compose env; NC
gets `jwt_secret` from `occ` and **infers** the rest. The fix pushes the header (and
in-body, if settable) into the NC connector explicitly so both sides are configured
from the **same role vars** — no coincidental-default reliance. After verifying the
real `occ` key names (§2.2 caveat), add the two `occ` items to the existing loop.

### 3.2 Name the algorithm var (single oracle)
Add `onlyoffice_jwt_algorithm: "HS256"` to onlyoffice defaults. The docserver hard-codes
HS256; naming it gives the gate one place to assert "the contract is HS256" and makes a
future euro-office alg change a one-line, gate-visible edit rather than a tribal fact.

### 3.3 Structural gate (the actual deliverable)
`tests/anatomy/test_jwt_embed_contract.py` (Python, stdlib + PyYAML only, fully
offline — reads files, renders no live system). It pins:

1. **Docserver env carries all four fields** — parse
   `roles/pazny.onlyoffice/templates/compose.yml.j2`; assert `JWT_ENABLED`,
   `JWT_SECRET`, `JWT_HEADER`, `JWT_IN_BODY` env keys are present and that
   `JWT_SECRET` is rendered from `{{ onlyoffice_jwt_secret }}` (the canonical var),
   `JWT_HEADER` from `onlyoffice_jwt_header`, `JWT_IN_BODY` from
   `onlyoffice_jwt_in_body`.
2. **Contract defaults are the locked values** — from
   `roles/pazny.onlyoffice/defaults/main.yml`: `onlyoffice_jwt_enabled: true`,
   `onlyoffice_jwt_header: "Authorization"`, `onlyoffice_jwt_in_body: true`,
   `onlyoffice_jwt_algorithm: "HS256"`. These are the four values every embedder
   must agree with; a drift here is the gate's headline failure.
3. **Single-secret source of truth** — assert exactly one `onlyoffice_jwt_secret`
   credential definition in `default.credentials.yml`, that `main.yml`'s
   secret-regeneration block regenerates `onlyoffice_jwt_secret` (so it's never the
   weak `_pw_` placeholder on a real run), and that the Nextcloud `occ` task sets
   `jwt_secret` from `{{ onlyoffice_jwt_secret ... }}` — i.e. docserver and NC read
   the **same** var, not two literals.
4. **Embedder header/in-body crosses the edge** — assert the NC `post.yml` loop sets
   `onlyoffice jwt_header` from `onlyoffice_jwt_header` (and `jwt_in_body` from
   `onlyoffice_jwt_in_body` IF the connector key exists — gate adapts to the §2.2
   finding; if it doesn't exist, the gate instead asserts the docserver `JWT_IN_BODY`
   stays `true` so it matches the NC default).
5. **No rogue embedder secret** — a repo-wide scan: any role that sets an
   `onlyoffice ... jwt_secret` (the embedder pattern) must source it from
   `onlyoffice_jwt_secret`, never a private/literal secret. Today only Nextcloud
   matches; the assert is forward-looking (catches a future Outline/BookStack wiring
   that forgets the shared var).
6. **euro-office compat pin** — a focused assert that the docserver JWT env block is
   image-agnostic (renders the same four env keys regardless of
   `onlyoffice_image`/`onlyoffice_flavor`), so the fork flip cannot drop a JWT field.

This makes the gate fail on every drift vector in §1: header/in-body desync, a
euro-office JWT-default change, a wrong-secret embedder, or a dropped env field.

### 3.4 No behavioural change on the stock path
Setting `jwt_header` explicitly to the value the NC connector already defaults to
(`Authorization`) is a no-op on the live system today (idempotent — same value), so
a stock blank converge is behaviourally identical. The change only *prevents future
divergence* — it does not alter current working state.

---

## 4. Gates it needs (the fix is not a fix without these)

**NEW** `tests/anatomy/test_jwt_embed_contract.py` (offline, fast, no live system) —
the six checks in §3.3, named:

- `test_docserver_env_carries_all_four_jwt_fields`
- `test_jwt_contract_defaults_are_locked` (enabled/header/in-body/algorithm values)
- `test_single_jwt_secret_source_of_truth` (one cred def + regenerated in main.yml)
- `test_nextcloud_connector_reads_same_secret_var`
- `test_embedder_header_inbody_crosses_the_edge` (or the docserver-side fallback per §2.2)
- `test_no_embedder_uses_a_private_onlyoffice_jwt_secret`
- `test_jwt_env_block_is_image_agnostic` (euro-office flip can't drop a field)

**Suite + syntax invariants (must stay green, per the hard rules):**
- `python3 -m pytest tests/anatomy/ -q` — full anatomy suite green.
- The pre-existing `test_onlyoffice_connector_urls.py` keeps passing **unchanged** —
  the new `occ` items append to the loop; they must not reorder/rename the existing
  four items or the `index: 3` / `idx + 4` trusted-domain asserts (those are in a
  *different* task and unaffected, but verify no collateral).
- `ansible-playbook main.yml --syntax-check` — clean.
- `ansible-lint` production profile — clean (new `occ` items follow the loop's
  existing `changed_when: false` / `failed_when: false` / `no_log` conventions).
- `test_config_stock_jinja_only.py` — the only new var is the role-local
  `onlyoffice_jwt_algorithm` (stack-up scope, plain literal, no filters) → the
  `{{ vars }}` eager-resolve trap does NOT apply; run the gate anyway to confirm no
  regression.

---

## 5. Risks

- **R1 — wrong `occ` key name.** If `jwt_header` / in-body are not real ONLYOFFICE-NC
  connector keys in the installed version, the new `occ` set is a silent no-op
  (`failed_when: false`) and the gate would pin a phantom. *Mitigation:* §2.2 caveat
  mandates confirming key names READ-ONLY via `occ config:app:list onlyoffice`
  BEFORE writing the task; the gate adapts (header-crosses-edge OR docserver-side
  fallback). This is the one step that must not be guessed.
- **R2 — euro-office actually changes a JWT default.** Then the gate goes red on the
  flip — which is the **intended** behaviour (a loud, fast offline failure beats a
  silent 403). *Mitigation:* the failure message names the exact field + this plan so
  the operator re-pins the contract deliberately. Out of scope to *auto-adapt* to a
  fork that breaks the contract — that's a human decision.
- **R3 — explicit `jwt_header` set churns idempotence.** It must be a no-op when the
  value already equals the connector default. *Mitigation:* the loop is already
  `changed_when: false` (every `occ` set in it is reporting-neutral by design), so the
  v0.4 `changed=0` idempotence invariant is unaffected. Verified by the idempotence
  re-run (§6 step 5).
- **R4 — `no_log` hides a real failure.** The loop is `no_log: true` (secret in the
  `jwt_secret` item). Adding non-secret items under the same `no_log` means a header
  typo is also masked in logs. *Mitigation:* the gate asserts the rendered value at
  the source-var level offline, so a typo is caught pre-converge without needing log
  visibility. (Splitting the secret item into its own `no_log` task to un-mask the
  rest is a reasonable refactor but higher churn — default plan keeps the single loop
  and leans on the offline gate.)
- **R5 — touching `post.yml` risks the trusted-domain index asserts.** The
  `index: 3` / `idx + 4` logic in `test_onlyoffice_connector_urls.py` is in a
  **separate** task block. *Mitigation:* edits are confined to the JWT loop; the old
  gate runs in the same suite and catches any accidental shift.
- **R6 — only Nextcloud is a real embedder.** The "no rogue secret" + "header crosses
  edge" checks are partly forward-looking (no Outline/BookStack wiring exists). That
  is intentional — the gate pins the *contract shape* so the next embedder can't drift
  it. No false green: every assert that references NC has a live target today.

---

## 6. Verification recipe (repo-only; live system READ-ONLY)

```bash
# 0. On the right branch
git -C /Users/pazny/projects/nOS branch --show-current        # feat/v0.7-overnight

# 1. New + pre-existing gates green
python3 -m pytest tests/anatomy/test_jwt_embed_contract.py \
                  tests/anatomy/test_onlyoffice_connector_urls.py -q

# 2. Prove the gate BITES — temporarily flip onlyoffice_jwt_header to "X-Custom"
#    in onlyoffice defaults (the exact silent-403 drift) → rerun step 1 → expect
#    RED on test_jwt_contract_defaults_are_locked → git restore.

# 3. Prove the euro-office pin BITES — temporarily delete the JWT_HEADER line from
#    compose.yml.j2 → rerun → expect RED on
#    test_docserver_env_carries_all_four_jwt_fields / image-agnostic → git restore.

# 4. Full anatomy suite still green
python3 -m pytest tests/anatomy/ -q

# 5. Syntax + lint + stock-Jinja gate clean
ansible-playbook main.yml --syntax-check
ansible-lint roles/pazny.onlyoffice roles/pazny.nextcloud
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q

# 6. READ-ONLY live cross-check (only if the operator already runs OnlyOffice):
#    Confirm the deployed connector keys + that docserver env matches NC config.
docker compose -p iiab exec -T -u www-data nextcloud \
  php occ config:app:list onlyoffice 2>/dev/null            # READ-ONLY: lists jwt_* keys
docker inspect b2b-onlyoffice-1 --format '{{range .Config.Env}}{{println .}}{{end}}' \
  2>/dev/null | grep -E '^JWT_'                             # docserver JWT_HEADER/IN_BODY
docker compose -p iiab exec -T -u www-data nextcloud \
  php occ onlyoffice:documentserver --check 2>/dev/null || true   # "successfully connected"
#   ^ ALL READ-ONLY; never write to the live system.
```

A full wet-test (blank converge → open a NC document in the embedded editor → confirm
no `403 security token` in the iframe) is **operator-gated** on a scratch host — NOT
run overnight, per the no-live-mutation rule. The plan ships the explicit wiring +
the offline gate; the wet confirmation is left to the operator.

---

## 7. Out of scope (explicit) + follow-ups

- **JWT secret rotation on a live install** — re-keying needs a coordinated docserver
  `JWT_SECRET` env update + every embedder's `jwt_secret` update in one pass; a
  destructive-adjacent transition that must be operator-gated (dry-run default per the
  destructive-op safety memory). Separate track.
- **Outline / BookStack embedder wiring** — feature work; this item only pins the
  contract so a future embedder is forced through the shared secret/header/in-body/alg.
- **The `onlyoffice_flavor` image toggle** — sibling plan
  `v07-euro-office-pilot-onlyoffice-toggle.md`; complementary, not duplicated.
- **Connector in-body key (`jwt_in_body`)** — set explicitly ONLY if the installed NC
  connector exposes a settable key (confirm per §2.2); else the gate pins the
  docserver side (`JWT_IN_BODY=true`) and asserts it matches the NC default.

---

## 8. Commit (plan doc only — implementation lands separately)

Single commit on `feat/v0.7-overnight`, Conventional Commits, subject ≤50 chars,
surgeon-tone body ≤6 bullets, no Co-Authored-By, no `--author`, **no push**:

```
docs(plan): lock onlyoffice JWT embed contract

- JWT secures the ungated docserver<->embedder server calls
- only the secret crosses the edge; header/in-body/alg inferred
- euro-office flip asserted JWT-compat but nothing pins it
- push header to NC connector; name HS256; one-secret source
- gated by tests/anatomy/test_jwt_embed_contract.py
```
