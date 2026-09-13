# Device digest doctrine — review

**Slug:** `digest-device-doctrine-review`  
**Task type:** review (try to refute, not confirm). Not the doctrine author.  
**Against:** `docs/plans/digest-device-doctrine.md` (operator-approved 2026-09-13) + spine as written (`state/digest-constitution.yml`, `nos_digest.check_bundle` / `resolve_party`, `digest_absorb.absorb`, `records_from_importers`, `legitimate_interests_satisfied`).  
**Date:** 2026-09-13.

**Builder tables in this tree:** uncommitted `state/keap-tables/device.table.yml`, `device-extraction.table.yml`, `state/fixtures/device.seed.yml` (Lane B; not edited here). They match §8’s two-table / owner-B / no-`graph:` shape. No `state/digest-importers/device.importer.yml`. No Wave 2.

---

## Verdict: **REFUTED**

§10: a class of bytes that would absorb without passing (1)–(5). Named below. `check_bundle` returned `[]` for a well-stamped untrusted bundle; `absorb()` POSTs when that list is empty.

Implementation holes are tagged **IMPL-GAP**. They do **not** by themselves refute. The refute is **SPEC-GAP**: the spec assigns refusals to judges that cannot produce them (synthetic-IČO / `resolve_party` under scheme B; Art-30 sweep / 6f-gate as family license).

---

## Scenarios (named bytes)

### 1. Third-party backup still composing deterministic rows — **REFUTED** (SPEC-GAP)

**Bytes:** `friend-iphone-backup.tar.gz` as `meta.source_id` / `_prov.source_id`.

Hand-built untrusted bundle, `_prov` complete:

```yaml
deterministic:
  device:
    - slug: device-friend-iphone
      model: iPhone 14
      os_family: ios
      identifier_hash: "sha256:" + 64×"a"
  device-extraction:
    - slug: ext-friend-unattested
      device: device-friend-iphone
      owner: "Alex Friend"
      subject_kind: third_party          # also tried operator_device
      operator_owns_device: false        # also tried key omitted
```

**Probe:** `check_bundle` → `[]` for (a) `third_party` + owns false, (b) `operator_device` + owns false, (c) missing `operator_owns_device`. `run_importer` on `b"PK\x03\x04" + FAKE_ITUNES_BACKUP*50` also returned `errors=[]` and set `meta.content_hash` to `sha256(zip)` (`a029dc644076e03f…`).

**Why the analog fails:** §1 says refuse with the **synthetic-IČO-class** error. That string is only `resolve_party` (`IČO in reserved synthetic range outside fixture mode`). Scheme **B** emits **no** `party` row, so that judge is never called. `check_bundle` does not read `subject_kind` or `operator_owns_device`. §8’s select is `operator_device | synthetic_fixture` — there is no `third_party` token for the failing case to use.

§9’s future CLI “asserts §1” is **IMPL-GAP**. The spec’s second clause (“if a hand-built bundle still contains them, the **gate** must refuse”) is false against the spine. **SPEC-GAP.**

### 2. Unnamed Health / location / message surviving into the bundle — **mixed**

**Bytes:**

- `sms.tsv` line `sms.tsv\t+420777111222\tHey, meet at the clinic`
- Health `hkQuantityTypeIdentifierHeartRate\t72`
- Significant Locations `50.0755,14.4378\thome`

| Path | `check_bundle` | Tag |
|---|---|---|
| Extra tables `device-health` / `device-message` / `device-significant-location` / `device-artifact` | refused (`no …table.yml definition`) | **SPEC-HOLDS** (deny-by-missing-def; Wave 1 tables do not name those classes) |
| Same TSV concatenated into `device-extraction.notes`, `unnamed_skip_count: 0` | `[]` | **SPEC-GAP** |

§3’s refute (“`unnamed_skip_count >= 1` and those tables’ lists empty”) is evaded by stuffing parse product into an allowed text column. No importer yet → also **IMPL-GAP** for profile skip-count. The notes path is the named absorbable class.

### 3. HTML report bytes reaching `/ingest/v1/capture` — **mixed**

**Bytes:** `<!DOCTYPE html><html><head><title>iLEAPP Report</title></head><body><h1>SMS</h1><p>Meet at clinic</p></body></html>`

| Path | Result | Tag |
|---|---|---|
| `captures: [{path: index.html, bytes: <html>…, mime: text/html}]` | refused (`captures present but check_bundle cannot yet inspect it`) | **SPEC-HOLDS** — this is the `/ingest/v1/capture` envelope; absorb never sees it green |
| Same HTML in `device-extraction.notes` or `report_path` | `[]` | **SPEC-GAP** — §5 also forbids HTML “as deterministic text rows”; the gate does not inspect column bytes |
| Zip magic `PK\x03\x04…` in `notes` | `[]` | **SPEC-GAP** / **IMPL-GAP** (`raw-never-touches-knowledge` still pending) |

Capture-door half of the failing case holds. Deterministic-text half does not.

### 4. Person auto-resolved by display name or phone — **not refuted as stated** (SPEC-HOLDS + adjacent SPEC-GAP)

**Bytes:** display name `Ada Lovelace`; phone `+420777111222`. Index already has `by_name["ada lovelace"] = ["party-ada"]`.

| `resolve_party` ref | status |
|---|---|
| `{kind: person, name: Ada Lovelace}` | `review` (`person: never key/name/auto-resolved`) |
| `{kind: person, name: …, phone: +420777111222}` | `review` (phone is not a key) |
| `{kind: person, ico: 12345679}` | `review` |

**SPEC-HOLDS** for `person-never-auto-resolved` when `kind == person`. Scheme B does not call the resolver on `owner` (text column on the uncommitted table — not a `rowRef`).

Adjacent holes (not the stated scenario, but §4 / §10 “mint a party from a device identifier”):

- `{name: Ada Lovelace, phone: +420…}` **without** `kind: person` → `resolved` / `matched_by=legal_name` / `party-ada`. Spine footgun if a builder “helpfully” resolves owner.
- Bundle with `party` slug `party-device-` + `sha256("00008030-001A21E21A88002E")[:12]` plus device rows → `check_bundle` `[]`. No bundle-type; **SPEC-GAP** for “device bundles contain no `party*` keys” as a **gate** claim. **IMPL-GAP** until compose exists.

### 5. `legal_basis: legitimate_interests` because importer default — **REFUTED** (SPEC-GAP)

**Bytes:** `csv-party.importer.yml` copied as `name: device` (includes current LIA + `data_source: not_from_subject`, `retention_days: 3650`).

- `records_from_importers(tmp)` → `imp_device` / `legitimate_interests` / `3650`. Sweep **harvests**; it does not refuse.
- `legitimate_interests_satisfied(copied)` → `(True, "")`. The 6f gate **licenses** the copy. `tests/anatomy/test_gdpr_6f_gate.py` parametrizes every `*.importer.yml` and only checks the LIA predicate — a committed `device.importer.yml` clone would go **green**.
- Bare `{legal_basis: legitimate_interests, retention_days: 3650}` without LIA is refused by 6f — that is not the realistic default. The live default **is** csv-party + LIA.
- `{legal_basis: consent, retention_days: -1}` is N/A-true on 6f, as the spec wanted — and as `test_consent_importer_is_not_forced_onto_6f` already pins. That does **not** refuse 6f-on-device.

§2: “Art-30 sweep / profile runner must refuse that manifest” and “6f-gate going green for other importers must not license this one.” Neither judge does the second. **SPEC-GAP.** No device manifest yet: **IMPL-GAP** as well, not a save.

Empty `art6_consent_ref` / `art9_consent_ref` plus Health TSV in `notes` also `check_bundle` `[]` — consent-before-parse is not a gate field.

### 6. Processor vs stomach (not in the operator’s five, §6) — **SPEC-HOLDS** (vacuous)

No `pazny.ileapp` role, no Pulse ileapp job, no `device.importer.yml` `egress`. Nothing to refute until a manifest exists. **IMPL-GAP** for the empty-egress pin.

---

## Hole location (not “missing code = refute”)

| Claim | Location |
|---|---|
| Third-party / unattested rows must not absorb | **SPEC-GAP** — wrong judge (`resolve_party` IČO); `check_bundle` has no extraction attestation rule |
| Unnamed classes as extra tables | **SPEC-HOLDS** |
| Unnamed classes as `notes` / skip_count lie | **SPEC-GAP** |
| HTML in `captures[]` | **SPEC-HOLDS** |
| HTML / zip as deterministic text | **SPEC-GAP** (`raw-never-touches-knowledge` pending is honest **IMPL-GAP** for archive, not a substitute column check) |
| Person + `kind: person` | **SPEC-HOLDS** |
| `party*` / UDID slug in the same bundle | **SPEC-GAP** (gate) |
| 6f copy of csv-party | **SPEC-GAP** — 6f-gate and Art-30 sweep are not a family deny |
| `run_importer(raw=zip)` hashes backup into `meta.content_hash` | Spec §5 already forbids passing zip into that argument — **SPEC-HOLDS** as builder constraint; helper is a trap, not a doctrine error |

---

## Patch the doctrine needs (do not start Wave 2)

Do **not** silently rewrite live doctrine from `digest-doctrine` if it later differs — name bytes here instead. Patches for **this** file:

1. **Drop the synthetic-IČO analog for §1.** Scheme B never calls `resolve_party`. Name a device-extraction judge that `absorb` / `check_bundle` actually runs, e.g. production rows require `operator_owns_device is true` and `subject_kind == operator_device`; `synthetic_fixture` only with fixture_mode / trusted fixture; missing attestation = refuse (not warn). Do not use `subject_kind: third_party` as the production token unless §8 grows that option (today it must not).
2. **Hand-built bundle is in scope.** If §1’s gate clause stays, list the exact `check_bundle` (or absorb preflight) checks. A future CLI assert is not the hand-built path.
3. **§2 6f:** say the 6f-gate going green for csv-party/isdoc/repos **must not** apply to `name: device` / this family. Name a **family deny** (legal_basis must be `consent`, retention not 3650) — not `records_from_importers` and not `legitimate_interests_satisfied` (those accept a csv-party clone). Keep “6f-gate is not a blocker” for the consent manifest.
4. **§3 / §5 column dump:** unnamed TSV/LAVA/HTML/zip must not land in `notes` or `report_path` (path-only for report). `unnamed_skip_count` cannot be 0 when unnamed classes were present. Extra tables without defs already fail — keep that.
5. **§4 gate:** if the bundle contains `device` / `device-extraction`, refuse `party*` keys (and any `owner` `rowRef`). Owner stays text until `party-review-rung`.
6. **§5 `run_importer`:** keep the “do not pass zip bytes as `raw`” rule; one line that `meta.content_hash` of a zip is a failed compose, not a gated IR hash.

No importer. No Wave 2. No `state/keap-tables/device*` edits in this slug.
