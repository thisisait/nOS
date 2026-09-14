# Device digest — importer-family doctrine

**Status:** Wave 1 Lane A spec (design). Operator-approved 2026-09-13: two tables (`device` + `device-extraction`), owner scheme **B**, failing cases (1)–(6) as written. Executable by `digest-device-tables`. **No importer code in this slug.**

**Noun:** this is a **device digest** / **device importer family**. It is not an organ. `organs-noun` is still next. Do not add a host daemon, a `pazny.ileapp` role, or a Pulse stomach.

**Also not the device-gateway pairing registry.** `state/keap-tables/device.table.yml` is a physical-unit hash row. A Miyoo / phone / wearable that *calls* nOS is a different noun (`device-client`, dtt `devices-table`). Pairing columns (`paired_at`, `last_seen`, `fingerprint`, Authentik owner) on this table would mix a backup digest with a live client. Pin: `test_digest_device_is_not_the_pairing_registry`.

**Does not wait on** `digest-doctrine`. If that row later contradicts this file, `digest-device-doctrine-review` names the bytes — it does not silently rewrite live doctrine.

**Does not staff Wave 2.** No iLEAPP version pin (`digest-device-ileapp-pin`), no LAVA walker, no artifact-module catalog beyond the deny rule.

**Does not touch** `tools/moderation-drain.py`, `roles/pazny.keap/**`, `default.config.yml` KEAP pins, or `state/keap-tables/device*` (that last path is `digest-device-tables`).

---

## 0. What already exists (reuse, do not fork)

The family joins the digest spine that already has three local/remote importers (`csv-party`, `repos`, `isdoc`):

| Piece | Where | What the device family must do |
|---|---|---|
| Gate-before-absorb | `nos_digest.check_bundle` (`state/digest-constitution.yml` `gate-before-absorb`) | Only a gated bundle may absorb. Device rows are untrusted → every row `_prov`. |
| Spine helper | `nos_digest.run_importer` | Format knowledge in the importer; harness stamps `_prov`. **Not** the enforcement chokepoint (constitution says so). |
| Absorb | `tools/digest_absorb.py` | Call only after the gate is empty. Strip `_prov`. Skip present slugs. |
| Art-30 | `state/digest-importers/<name>.importer.yml` → `nos_gdpr.records_from_importers` (`imp_<name>`) | One new manifest. Sweep already exists. |
| Synthetic-range refusal | `nos_digest.resolve_party` + CSV importer `fixture_mode` | Third-party extraction is the **same class**: data error outside fixture mode. |
| Person identity | `person-never-auto-resolved` | Do not mint a person from a device id. |

Live absorb of this family is **forbidden** until the blockers in §7 exist. Tables and a dry gate may land first; `--absorb` against a real backup may not.

---

## 1. SUBJECT — operator-owned device + consent

**Rule.** Bytes enter this family only when they are an extraction of a **device the operator owns** and the operator has **consented to process that extraction**. A third-party phone dump, a spouse/employee handset, a client forensic image, or “found this zip” is not a source. It is a **data error**, the same class as an IČO in the reserved synthetic range (`000001xx`) outside `fixture_mode`: skip, count, **zero knowledge rows**.

**Attestation (required on the extraction object, before parse):**

- `operator_owns_device: true` (explicit; missing = false)
- `subject_kind: operator_device` (the only production value)
- Art. 6(1)(a) consent recorded for this extraction (see §2)

`fixture_mode` may ingest a **declared synthetic** extraction (parallel to fixture IČOs). Production never does.

**Failing case.** `friend-iphone-backup.tar.gz` with no ownership attestation, or `subject_kind: third_party`, is parsed into `deterministic` rows and `check_bundle` returns `[]` so absorb would write them. **Refute:** those bytes must never reach compose; if a hand-built bundle still contains them, the gate must refuse with the synthetic-IČO-class error (not a warning).

---

## 2. LEGAL BASIS — 6(1)(a) + Art. 9(2)(a) before special-category parse

**Rule.**

- Art. 6 basis is **`consent`** (6(1)(a)), never `legitimate_interests`. Accounting importers may keep 6(1)(f); this family does not copy them.
- **Art. 9(2)(a) explicit consent** must be recorded on the extraction **before any special-category artifact class is parsed**. Health is special-category. A class tagged `special_category: true` in the profile is the same. Parse-then-redact is forbidden.
- Retention is **until consent is withdrawn**, or until `retain_until` on the **raw object** — not `retention_days: 3650`. Knowledge rows die with withdrawal; they do not inherit a ten-year invoice horizon.
- **`gdpr-6f-gate` is not a blocker** for this family. A gate that requires 6(1)(f) of digest importers must carve this family out or stay pending. Do not wait on that row; do not “fix” csv-party/isdoc/repos here.

**Manifest (when a builder adds `state/digest-importers/device.importer.yml` — not this slug):**

- `gdpr.legal_basis: consent`
- `gdpr.retention_days: -1` (lifecycle / DSAR; already a `nos_gdpr` spelling) plus notes pointing at `retain_until` / withdrawal
- `gdpr.processors: []` (local CLI is the controller’s tool, not a third-party processor)
- `egress: []`

Consent records: reuse Wing `gdpr_consent` / `record-consent.php` as the estate’s Art. 7 ledger. The extraction row stores **refs** (`art6_consent_ref`, `art9_consent_ref`), not a parallel consent store.

**Failing case.** Manifest copies `legal_basis: legitimate_interests` and `retention_days: 3650` from `csv-party.importer.yml`, **or** a named Health module emits TSV→rows while `art9_consent_ref` is empty. **Refute:** Art-30 sweep / profile runner must refuse that manifest or that parse; 6f-gate going green for other importers must not license this one.

---

## 3. PROFILE IS THE PRODUCT — default deny

**Rule.** A **named profile** is the only thing that turns an iLEAPP (or sibling) artifact class into rows. Default is **deny**. An unnamed class is **skipped and counted** (`unnamed_skip_count` on the extraction). It never becomes a row, a capture, or a proposal.

Shipping profile (Wave 1 product): **does not name** Messages, Health, or Significant Locations. Those three start unnamed even if the tool emits them. Health additionally cannot be named until §2 Art. 9 consent exists (`digest-device-art9` / a later profile edit — not Wave 2 staffing here).

Unnamed ≠ “store in a generic `device-artifact` dump table”. Unnamed = **no row**.

**Failing case.** iLEAPP writes `sms.tsv` (or Health / Significant Locations); the profile does not name that class; compose still emits message/health/location rows (or a catch-all artifact table). **Refute:** `unnamed_skip_count >= 1` and those tables’ deterministic lists are empty / absent.

---

## 4. OWNER IDENTITY — pick B

**Pick: B** (lazy default). `party-review-rung` is still next. Do not invent a third scheme. Do not do A.

| | A (refused for now) | **B (this spec)** |
|---|---|---|
| Identity | Consented person slug from a hash of a non-secret device identifier, minted only after operator yes | `extraction.owner` as **text** |
| Party row | Minted after yes | **No `party` row** until `party-review-rung` exists |

**B in tables.** `device-extraction.owner` is a text column (operator-typed display name). It is **not** a `rowRef` to `party`. Device identifiers (UDID, serial, IMEI) are **not** knowledge columns and **not** slug material.

**A is closed** until a later owner slug, after the review rung can hold a person without auto-mint. Migrating B→A later is allowed; hashing a UDID into `party-device-<hex>` now is not.

**Failing case.** Compose emits `party` / `party-tax-identity` (or `party-device-<hash>`) from a UDID/serial, or `device-extraction.owner` is a `rowRef` to `party`. **Refute:** device bundles contain no `party*` keys; owner is a string.

---

## 5. RAW vs KNOWLEDGE — four different objects

| Object | What it is | Where it lives | Absorbed? |
|---|---|---|---|
| Backup / zip / tar / itunes image | Raw source bytes | **raw-archive** only (`raw-archive-store`) | Never |
| LAVA / TSV | Parse **product** of the local CLI | Staging next to the archive object, not KEAP | Never as rows |
| Gated bundle | `meta` + `deterministic` after profile + gate | Printed / `--absorb` | **Only this** |
| iLEAPP HTML (and similar) | Human **report** | Path may be noted as `report_path` on the extraction | Never as capture or rows |

Path (constitution `raw-never-touches-knowledge`, still **pending**): raw-archive → parse → normalize → compose → GATE → absorb.

`run_importer` today hashes `raw` (often file **contents**) into `meta.content_hash`. A device builder must **not** pass zip bytes through that argument into the knowledge plane. Hash the archive object id / file digest **in archive metadata**; the bundle’s `content_hash` is the gated IR, not the backup.

`captures[]` / `proposals[]` stay refuse-closed in `check_bundle` until those validators exist. Device HTML is not a way around that.

**Failing case.** Backup bytes or iLEAPP HTML land in `captures[]` (or as deterministic text rows), **or** TSV lines are upserted without `check_bundle`. **Refute:** those byte classes never appear in a bundle that the gate returns empty.

---

## 6. PROCESSOR vs STOMACH — local CLI, empty egress

**Rule.** iLEAPP (or a sibling local extractor) is **declared on the importer manifest** as the parse tool: local CLI, **egress: []**. nOS does **not** grow a forensics daemon, a Docker service, a launchd/systemd unit, or a Pulse job that runs the extractor. The operator (or a one-shot CLI the operator starts) runs the tool; digest consumes the parse product.

- Do **not** pin iLEAPP (`digest-device-ileapp-pin` is a later row).
- Do **not** put iLEAPP in `gdpr.processors` as if it were a third party (empty processors, named in `notes` / a `parse_tool:` key).
- Do **not** add `roles/pazny.*` for this.

**Failing case.** A Pulse catalog entry / launchd plist / compose service runs ileapp on a schedule, **or** `egress` lists a hosted forensics API, **or** processors name a cloud lab. **Refute:** manifest `egress: []` and no new organ/daemon; parse is operator-invoked CLI.

---

## 7. Live-proof BLOCKERS (cite; do not edit them here)

These rows are **blockers for live proof** (`--absorb` of a real extraction). They are not files this slug edits.

1. **`digest-absorb-chokepoint`** — `raw-never-touches-knowledge` is pending. `run_importer` is a helper, not a no-bypass chokepoint. Until that judge exists, a second caller can still absorb ungated bytes.
2. **`raw-archive-store`** — backup/zip has no committed store. Without it, the raw object and `retain_until` have nowhere honest to live; stuffing the zip into KEAP would violate §5.
3. **`party-review-rung`** — why §4 is B. Person-shaped owners cannot go on `party` until review exists. Do not wait by inventing scheme A.

`digest-device-tables` may add **definitions** under `state/keap-tables/` (that slug, not this file). Definitions ≠ live absorb.

---

## 8. What `digest-device-tables` should author (minimum)

Operator 2026-09-13: **two tables**, frozen. A second backup of the same unit, a later LEAPP, a profile change — hang off the same `device`. Owner scheme B is a **column on extraction**, not a third table.

Visibility: `tier-managers`. **No `graph:` block** (no public row-projection of personal device facts).

**`device`** — one physical unit. Never raw UDID / IMEI / serial as a column.

- `slug` (text, required)
- `model` (text)
- `os_family` (select: `ios` | `android` | `other`)
- `identifier_hash` (text) — hash of a non-secret device identifier; CONCEPTLESS until KEAP grows a word (do not stretch `identity.name`)
- `notes` (text)

**`device-extraction`** — one parse run. `device` is a `rowRef` (`onDelete: restrict`).

- `slug` (text, required)
- `device` (rowRef → `device`, required)
- `owner` (text, required) — scheme B; **not** a `rowRef` to `party`
- `subject_kind` (select: `operator_device` | `synthetic_fixture`)
- `operator_owns_device` (boolean / select; production rows true)
- `profile_id` (text)
- `art6_consent_ref` (text)
- `art9_consent_ref` (text, empty until a special-category class is named)
- `retain_until` (text ISO date, or empty = until withdrawal)
- `raw_archive_ref` (text; empty until `raw-archive-store`)
- `report_path` (text; human HTML path, not ingested)
- `unnamed_skip_count` (number)
- `notes` (text)

**Do not create in Wave 1:** `device-message`, `device-health`, `device-significant-location`, a generic dump table, or any `party` rowRef from these tables.

Named-class tables wait until a profile names a class (`digest-artifact-modules`).

---

## 9. Builder sequence (later slugs, not this one)

1. Tables files for `device` + `device-extraction` (`digest-device-tables`).
2. Manifest `state/digest-importers/device.importer.yml` with §2 / §6 fields.
3. CLI that: asserts §1, requires Art. 6 consent, runs local ileapp **only after** that, applies profile (§3), composes **only** named classes, `check_bundle`, default dry. `--absorb` refused until §7 blockers land.
4. Fixture synthetic extraction only under `fixture_mode` (`digest-device-fixture`).
5. Review: `digest-device-doctrine-review`.

---

## 10. Review gate

`digest-device-doctrine-review` can **REFUTE** this doctrine by naming a **class of bytes** that would absorb without passing (1)–(5).

If the reviewer cannot name such a class against this file plus the spine as written, the doctrine holds. Implementation that later opens a hole fails the same gate.

Byte classes that must remain un-absorbable without (1)–(5): third-party / unattested backups; any parse before Art. 6 consent; special-category module output before Art. 9 consent; unnamed-class TSV/LAVA; raw backup/zip; iLEAPP HTML as capture; ungated TSV-as-rows; bytes that mint a `party` from a device identifier.
