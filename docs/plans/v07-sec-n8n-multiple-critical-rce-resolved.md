# Plan — v0.7 SEC: n8n multiple-critical-RCE pin, gated against regression

**Status:** PLAN (not implemented). Review-ready.
**Branch:** `feat/v0.7-overnight`
**Confirmed item:** the n8n "multiple critical RCE" cluster (REM-011 + 11 siblings)
is marked **resolved** in `docs/llm/security/remediation-queue.json`, pinned at
`n8n_version: "2.26.2"`. This plan does NOT re-do the version bump — it **pins the
resolution against silent regression** with a CVE-floor gate, and fixes a citation
defect on the pin comment. "Resolved with no gate that proves it stays resolved" is
the actual open weakness.

---

## 1. Problem / why

### What is already done (do not redo)
The n8n unauthenticated-RCE cluster is closed in the queue:

| REM | finding_ref | fix_version (floor) | status |
|-----|-------------|---------------------|--------|
| REM-011 | CVE-2026-21858 ("Ni8mare") | 2.0.0 | resolved |
| REM-022 | CVE-2026-25049 | 2.5.2 | resolved |
| REM-040 | CVE-2026-27493+27577 | 2.10.1 | resolved |
| REM-043 | SSRF-001 | (config, not version) | resolved |
| REM-051/052/057/058/079/080 | CVE-2026-336xx cluster | 2.14.1 | resolved |
| REM-062 | CVE-2026-21877 | 1.121.3 | resolved |
| REM-086 | CVE-2026-44789/90/91 | **2.20.7** | resolved |

Live pin is `n8n_version: "2.26.2"` in BOTH source-of-truth surfaces
(`default.config.yml:1384` and `roles/pazny.n8n/defaults/main.yml:10`); they agree,
carry the source-of-truth annotation, and pass every existing gate
(`test_version_pin_no_shadow.py`, `test_image_pin_hygiene.py`,
`test_n8n_ssrf_protection.py` — all green, 10 passed). SSRF egress protection is
wired in the plugin compose-extension
(`files/anatomy/plugins/n8n-base/templates/n8n-base.compose.yml.j2`) and gated.

### The gap this plan closes
Two defects, both gateable, both matching failure classes the repo already
recognises:

1. **No CVE-floor gate.** Nothing asserts the live n8n pin is **≥ the maximum
   `fix_version`** of any *resolved* n8n entry in the remediation queue. A future
   "freshness" bump that moves `n8n_version` to a wrong, older, or differently-tagged
   value (or a botched same-major downgrade) would **silently un-fix the entire RCE
   cluster** and every existing gate would stay green — because today's gates only
   check that the two surfaces *agree* and that the tag is *non-floating*, never that
   it clears the security floor. This is exactly the `version-pins-default-config-shadow`
   memory's failure mode ("dead pin bit a live n8n RCE pin"), just inverted: a live
   pin that drifts *below* the floor. The queue already stores the answer
   (`fix_version` per entry); nothing reads it back against the live pin.

2. **Citation drift on the pin comment.** Both pin lines comment
   `# CVE-2026-4478x RCE pins` — a glob (`4478x`) that matches **no actual CVE** in
   the queue (the cluster is 21858 / 25049 / 27493 / 33660… / 44789-91). An auditor
   reading the pin cannot map the comment to a tracked CVE. This is the same
   class `test_mariadb_cve_citation_consistent_across_surfaces` already guards for
   MariaDB — n8n simply never got the equivalent.

Neither defect changes runtime behaviour today (2.26.2 ≥ 2.20.7). Both are
*regression insurance + audit legibility*, which is precisely what an unsupervised
overnight security batch should ship: a fix that *stays* fixed.

---

## 2. Exact files to touch

| File | Change | Type |
|------|--------|------|
| `tests/anatomy/test_n8n_cve_floor.py` | **NEW** gate — pin ≥ max resolved-n8n `fix_version`; pin agrees across both surfaces; comment cites a real tracked CVE | gate (required) |
| `default.config.yml` (line 1384) | rewrite pin comment: replace `CVE-2026-4478x` glob with the real floor CVE citation (`CVE-2026-44791`, fix 2.20.7) + the floor note | comment-only |
| `roles/pazny.n8n/defaults/main.yml` (line 10) | mirror the same corrected citation; keep the existing source-of-truth annotation | comment-only |

**Explicitly NOT touched:** `n8n_version` value (already correct at 2.26.2), the
compose template, the plugin compose-extension, the remediation queue JSON (the
entries are already `resolved` — re-stamping them is out of scope and risks churning
`resolved_at`). No live-system writes. No new `*_version`/`install_*` var, so the
stock-Jinja `default.config.yml` trap (`test_config_stock_jinja_only.py`) is not
engaged — we only edit an existing literal's trailing comment.

---

## 3. Approach

### 3.1 The new gate (`test_n8n_cve_floor.py`)

Offline, no Docker, source + JSON scan only. Three assertions:

1. **`test_n8n_pin_clears_cve_floor`** — parse `n8n_version` from
   `default.config.yml` (the source-of-truth layer) with the same `_SEMVER`/literal
   discipline `test_wing_frankenphp_version_pin.py` uses; parse
   `docs/llm/security/remediation-queue.json`; compute
   `floor = max(fix_version for entry where component=="n8n" and status=="resolved"
   and fix_version is a semver)`; assert `parse(pin) >= parse(floor)` using a tuple
   comparison on `(major, minor, patch)`. Floor today = `2.20.7` (REM-086); pin =
   `2.26.2` → passes. If a future bump drops the pin below any resolved n8n CVE's
   fix floor, this **fails loud** with both numbers and the offending REM id.

2. **`test_n8n_pin_agrees_across_surfaces`** — re-assert config pin == role-default
   pin (defence-in-depth with the existing shadow gate; this one is n8n-specific and
   states the security reason inline, so a future contributor editing only one
   surface gets an n8n-RCE-flavoured failure, not a generic shadow message).

3. **`test_n8n_pin_comment_cites_a_tracked_cve`** — read both pin lines; assert each
   trailing comment contains at least one `CVE-\d{4}-\d+` token that is an actual
   `finding_ref` of a resolved n8n entry in the queue. Kills the `4478x` glob class
   permanently: a non-existent CVE citation fails here.

Floor is **derived from the queue, not hardcoded** — when REM-086's successor lands
a higher `fix_version`, the floor rises automatically and the gate keeps the pin
honest with zero test edits. (Hardcoding the floor would itself become a dead pin.)

Reuse the established helpers: `yaml.safe_load` + a `_SEMVER` regex
(`^\d+\.\d+\.\d+$`) exactly as `test_wing_frankenphp_version_pin.py` does, and the
`_CVE_RE = re.compile(r"CVE-\d{4}-\d+")` from `test_version_pin_no_shadow.py`.

### 3.2 The citation fix

Rewrite both comments to a precise, auditor-mappable form, e.g.:

```yaml
n8n_version: "2.26.2"      # RCE cluster floor: CVE-2026-44791 (REM-086, fix 2.20.7); pin ≥ floor — gate test_n8n_cve_floor.py
```

and on the role default, append after the existing source-of-truth note. Pick the
**highest-floor** CVE (REM-086 → 2.20.7) as the anchor citation because it is the
binding constraint; the gate accepts any tracked CVE, so this is a readability choice,
not a correctness one.

---

## 4. Risks

- **Low blast radius.** Comment-only repo edits + one new offline test. No value
  change, no template change, no live mutation, nothing the playbook re-renders
  differently. A `main.yml` run would emit byte-identical compose output.
- **Floor-derivation brittleness:** if the queue ever stores a non-semver
  `fix_version` (e.g. a date or `null`, as REM-043 does), the gate must *skip* those
  entries, not crash. Mitigation: filter `fix_version` through `_SEMVER` before it
  enters the `max()`; `null`/`"see version-pins-proposal.json"`/SSRF-config entries
  are excluded by construction. Add an explicit `test`-level assertion that at least
  one n8n entry contributed a floor (guards against the filter silently emptying the
  set and the gate passing vacuously — the same vacuous-pass trap
  `test_mariadb…` guards with its `CVE-2026-3494 in distinct` check).
- **Version-tuple comparison correctness:** n8n is plain `MAJOR.MINOR.PATCH`
  (no pre-release/`-rc` suffixes in any pin or fix_version observed), so a
  `tuple(int(x) for x in v.split("."))` comparison is exact. If a future tag carries
  a suffix, the `_SEMVER` literal check fails first with a clear message rather than
  mis-comparing. Document this assumption in the gate docstring.
- **No upstream-truth claim.** The gate proves *internal consistency* (pin clears the
  floor the repo itself tracks). It deliberately does NOT assert "2.26.2 is the latest
  upstream n8n" — that is the security-scan pipeline's job (S2 freshness), out of scope
  here. Stating this in the docstring prevents a future reader over-reading the gate.

---

## 5. Gates it needs (the hard rule)

- **New:** `tests/anatomy/test_n8n_cve_floor.py` (3 tests above) — the gate that
  *is* the fix. Without it this is a doc change, not a remediation.
- **Must stay green:** `tests/anatomy/test_version_pin_no_shadow.py`,
  `tests/anatomy/test_image_pin_hygiene.py`, `tests/anatomy/test_n8n_ssrf_protection.py`,
  `tests/anatomy/test_config_stock_jinja_only.py`, and the full `tests/anatomy/` suite.
- **Must stay clean:** `ansible-playbook main.yml --syntax-check`.

---

## 6. Verification recipe

```bash
cd /Users/pazny/projects/nOS

# 1. the new gate passes (pin 2.26.2 ≥ floor 2.20.7; comments cite real CVEs)
python3 -m pytest tests/anatomy/test_n8n_cve_floor.py -q

# 2. it actually BITES — temporarily prove a downgrade is caught (revert after!)
#    edit default.config.yml n8n_version -> "2.10.0" (below REM-086 floor 2.20.7)
python3 -m pytest tests/anatomy/test_n8n_cve_floor.py::test_n8n_pin_clears_cve_floor -q
#    EXPECT: FAIL naming pin=2.10.0 floor=2.20.7 REM-086 — then `git checkout default.config.yml`

# 3. it bites the citation glob — temporarily restore `CVE-2026-4478x`, expect
#    test_n8n_pin_comment_cites_a_tracked_cve to FAIL; revert.

# 4. no shadow / floating-tag / SSRF regression
python3 -m pytest tests/anatomy/test_version_pin_no_shadow.py \
                  tests/anatomy/test_image_pin_hygiene.py \
                  tests/anatomy/test_n8n_ssrf_protection.py -q

# 5. full anatomy suite + syntax
python3 -m pytest tests/anatomy/ -q
ansible-playbook main.yml --syntax-check

# 6. (read-only, live, OPTIONAL) confirm the running image already matches the pin —
#    NO writes, observation only:
docker inspect iiab-n8n-1 --format '{{ .Config.Image }}'   # expect n8nio/n8n:2.26.2
```

Steps 2–3 are manual "make-it-fail" confirmations the operator runs once during
review; they are NOT committed (revert each before commit). The committed artefact is
the green gate + the corrected comments.

---

## 7. Commit (lands on `feat/v0.7-overnight` only — never pushed)

```
test(n8n): gate pin against resolved-RCE CVE floor

- queue marks the n8n RCE cluster resolved at 2.26.2 but no gate
  proved the pin stays >= the fix floor — a freshness bump could
  silently un-fix it (the version-pin-shadow class, inverted)
- new test_n8n_cve_floor.py: pin >= max resolved-n8n fix_version
  (floor derived from remediation-queue, REM-086 = 2.20.7), both
  surfaces agree, comment cites a tracked CVE
- fix pin comment: CVE-2026-4478x glob -> real CVE-2026-44791 cite
```

(Subject 49 chars; body 5 bullets; no Co-Authored-By, no `--author`.)
