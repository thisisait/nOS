"""nos_digest — the shared spine of the digest importers (digest-bundle-ir,
importer-spine). This module holds the LOAD-BEARING judge: check_bundle().

A BUNDLE is the importer IR (digest-bundle-ir):

    {
      "meta": {"source_id", "importer", "importer_version", "content_hash",
               "trusted": bool},          # trusted => git-authored fixture, no per-row _prov
      "deterministic": {"<table-slug>": [ {row}, ... ], ...},  # KEY ORDER = dependency order
      "captures":   [ ... ],              # -> /ingest/v1/capture (not checked here yet)
      "proposals":  [ ... ],              # -> SERE propose      (not checked here yet)
    }

check_bundle() is the GATE-before-absorb firebreak: a bundle that fails it must
touch nothing live. It validates the deterministic section (the rung seed-bundle.yml
consumes) and REFUSES a non-empty captures/proposals — those absorb doors are not
built, so a gate that passed them would greenlight sections it never read. Their
real validators (and the refusal lifting) land with their doors.

WHY A SHARED FUNCTION (importer-spine decision, 2026-09-10): normalize/provenance/
gate are written ONCE and reused by every importer, so the load-bearing checks
can't drift per importer. It is a plain function, not a framework (YAGNI).

TRUST (digest-bundle-ir decision, 2026-09-10): meta.trusted==True marks a
git-authored fixture bundle — already gated by the fixture ORDER gates — so the
per-row provenance stamp is NOT required. An importer bundle is untrusted and
every deterministic row must carry a _prov{source_id,importer_version,content_hash}.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys
import unicodedata

import yaml

_MOD_DIR = pathlib.Path(__file__).resolve().parent
if str(_MOD_DIR) not in sys.path:
    sys.path.insert(0, str(_MOD_DIR))
import nos_accounting  # noqa: E402  — posting balance at the same firebreak as check_bundle

#: The only top-level sections a bundle may carry.
ALLOWED_TOP = {"meta", "deterministic", "captures", "proposals"}
#: Minimum provenance a row of an UNTRUSTED bundle must carry (grows over time —
#: legal_basis / retain_until / transfer_endpoint ride the same dict, see the row).
PROV_REQUIRED = {"source_id", "importer_version", "content_hash"}


def _load_def(tables_dir: pathlib.Path, slug: str) -> dict | None:
    p = tables_dir / f"{slug}.table.yml"
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _rowref_cols(tdef: dict) -> list[dict]:
    return [c for c in (tdef.get("schema", {}).get("columns") or [])
            if c.get("kind") == "rowRef"]


# Device-family gate (digest-device-doctrine-review SPEC-GAP). Scheme B never
# calls resolve_party; these checks live on check_bundle so absorb cannot POST.
_DEVICE_FAMILY = frozenset({"device", "device-extraction"})
_DEVICE_DUMP_COLS = ("notes", "report_path", "raw_archive_ref")
_HTML_MARK = re.compile(r"(?is)<!DOCTYPE\s+html|<html[\s>]")
_ZIP_MAGIC = "PK\x03\x04"
#: A free-text device column is a human note or a path — never a data table.
#: Magic only caught HTML/zip; plain-text `sms.tsv\t+420…` or `heartRate\t72`
#: slipped through as "notes". A tab, a handful of newlines, or an over-cap
#: length is a smuggled dump, not a note. ponytail: char cap + delimiter
#: heuristic; a real class needs a NAMED profile, never a notes blob.
_DEVICE_TEXT_MAX = 1024
#: Special-category (Art. 9) signals — health / messages / precise location.
#: Their presence in a free-text device column IS a special-category class
#: surfacing outside the named-profile path; the consent rule demands Art. 9(2)(a) consent
#: (a non-empty art9_consent_ref) before it may exist at all.
_ART9_SIGNAL = re.compile(
    r"(?i)\b(heart[\s_-]?rate|bpm|blood[\s_-]?(?:pressure|glucose|oxygen)|spo2"
    r"|steps?|sleep|menstrual|health(?:kit)?|medical|diagnos|sms|imessage"
    r"|whatsapp|call[\s_-]?log|latitude|longitude"
    r"|significant[\s_-]?location|geo(?:location)?)\b")


def _device_dump_kind(val) -> str | None:
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("latin-1", "replace")
    if not isinstance(val, str) or not val:
        return None
    if val.startswith(_ZIP_MAGIC) or _ZIP_MAGIC in val[:64]:
        return "zip"
    if _HTML_MARK.search(val):
        return "html"
    if "\t" in val:
        return "tsv"
    if val.count("\n") >= 3:
        return "table"
    if len(val) > _DEVICE_TEXT_MAX:
        return "oversized"
    return None


def device_family_basis_satisfied(manifest: dict) -> tuple[bool, str]:
    """Device-family importer MUST be Art. 6(1)(a) consent + retention -1
    (the digest-device consent rule: consent + retention -1). N/A (True, "")
    for every non-device importer,
    keyed on the importer NAME being in the device family — so a device.importer
    cloned from csv-party (legitimate_interests / retention 3650) is REFUSED even
    though it passes ``legitimate_interests_satisfied`` (the 6f gate) green."""
    name = (manifest or {}).get("name")
    if name not in _DEVICE_FAMILY:
        return True, ""
    gdpr = (manifest or {}).get("gdpr") or {}
    basis = gdpr.get("legal_basis")
    if basis != "consent":
        return False, (
            f"device-family importer {name!r} must be legal_basis: consent "
            f"(Art. 6(1)(a)), not {basis!r} — a person's "
            "device extraction is never legitimate_interests)")
    if gdpr.get("retention_days") != -1:
        return False, (
            f"device-family importer {name!r} must set retention_days: -1 "
            f"(until consent withdrawn), not {gdpr.get('retention_days')!r} — "
            "(no ten-year accounting horizon on device rows)")
    return True, ""


def _check_device_family(bundle: dict, det: dict, errors: list[str]) -> None:
    tables = set(det)
    if not tables & _DEVICE_FAMILY:
        return
    party_keys = sorted(t for t in tables if t == "party" or t.startswith("party-"))
    if party_keys:
        errors.append(
            f"device bundle must not contain party* keys {party_keys} "
            "(owner scheme B: owner is text, no party row)")
    meta = bundle.get("meta") or {}
    trusted = bool(meta.get("trusted"))
    fixture_mode = bool(meta.get("fixture_mode"))
    for r in det.get("device-extraction") or []:
        if not isinstance(r, dict):
            continue
        slug = r.get("slug", "?")
        if isinstance(r.get("owner"), dict):
            errors.append(
                f"device-extraction/{slug}.owner: must be text, not a rowRef")
        if r.get("operator_owns_device") is not True:
            errors.append(
                f"device-extraction/{slug}: operator_owns_device must be true "
                "(missing or false is a data error — third-party extraction)")
        kind = r.get("subject_kind")
        if kind == "third_party" or kind not in ("operator_device", "synthetic_fixture"):
            errors.append(
                f"device-extraction/{slug}: subject_kind {kind!r} is not a "
                "production attestation (operator_device, or synthetic_fixture "
                "in trusted fixture / fixture_mode)")
        elif kind == "synthetic_fixture" and not (trusted or fixture_mode):
            errors.append(
                f"device-extraction/{slug}: synthetic_fixture only with "
                "trusted fixture or fixture_mode")
    for table in ("device", "device-extraction"):
        for r in det.get(table) or []:
            if not isinstance(r, dict):
                continue
            slug = r.get("slug", "?")
            art9_ref = str(r.get("art9_consent_ref") or "").strip()
            for key in _DEVICE_DUMP_COLS:
                val = r.get(key)
                kind = _device_dump_kind(val)
                if kind:
                    errors.append(
                        f"{table}/{slug}.{key}: {kind} content in a text column "
                        "is refused (path-only for report_path; no HTML/zip/TSV "
                        "dump — a named class needs a profile)")
                if isinstance(val, str) and _ART9_SIGNAL.search(val) and not art9_ref:
                    errors.append(
                        f"{table}/{slug}.{key}: special-category (Art. 9) content "
                        "with empty art9_consent_ref — Art. 9(2)(a) consent must be "
                        "on the row before a special-category class may exist")


def check_bundle(bundle: dict, tables_dir: str | pathlib.Path) -> list[str]:
    """Return a list of human-facing error strings; empty means the bundle is
    safe to absorb. Deterministic-section only (see module docstring).
    """
    tables_dir = pathlib.Path(tables_dir)
    errors: list[str] = []

    if not isinstance(bundle, dict):
        return ["bundle is not a mapping"]
    unknown = set(bundle) - ALLOWED_TOP
    if unknown:
        errors.append(f"unknown top-level bundle key(s): {sorted(unknown)}")

    # FAIL-CLOSED on sections this gate cannot yet inspect. captures[] and
    # proposals[] belong to the IR envelope, but check_bundle validates ONLY the
    # deterministic section — their absorb doors (/ingest/v1/capture, SERE) are
    # not built. Passing a bundle that carries them GREEN would greenlight
    # content nothing read: the estate's #1 anti-pattern (a gate you pass without
    # doing the thing). So a non-empty captures/proposals is REFUSED here until a
    # real validator for it lands. "gate OK" must never cover an unread section.
    for section in ("captures", "proposals"):
        if bundle.get(section):
            errors.append(
                f"{section} present but check_bundle cannot yet inspect it — refused "
                f"(no {section} validator built; see the raw-never-touches-knowledge rule)")

    trusted = bool((bundle.get("meta") or {}).get("trusted"))
    det = bundle.get("deterministic")
    if det is None:
        return errors  # a bundle with no deterministic section is valid here
    if not isinstance(det, dict):
        return errors + ["deterministic section is not a mapping"]

    order = list(det.keys())
    order_idx = {t: i for i, t in enumerate(order)}

    # ── pass 1: defs, rows, slugs, provenance ────────────────────────────────
    defs: dict[str, dict] = {}
    slugs_by_table: dict[str, set] = {}
    for table in order:
        rows = det[table]
        tdef = _load_def(tables_dir, table)
        if tdef is None:
            errors.append(f"{table}: no {table}.table.yml definition")
            continue
        defs[table] = tdef
        if not isinstance(rows, list):
            errors.append(f"{table}: rows is not a list")
            continue
        table_slugs: set = set()
        for r in rows:
            if not isinstance(r, dict):
                errors.append(f"{table}: a row is not a mapping")
                continue
            slug = r.get("slug")
            if not slug:
                errors.append(f"{table}: a row has no slug (the upsert keys on it)")
                continue
            if slug in table_slugs:
                errors.append(f"{table}: duplicate row slug {slug!r}")
            table_slugs.add(slug)
            if not trusted:
                prov = r.get("_prov")
                if not isinstance(prov, dict) or not PROV_REQUIRED <= set(prov):
                    errors.append(
                        f"{table}/{slug}: untrusted bundle row missing "
                        f"_prov{{{', '.join(sorted(PROV_REQUIRED))}}}")
        slugs_by_table[table] = table_slugs

    # ── pass 2: rowRef resolution + no forward reference ─────────────────────
    for table in order:
        tdef = defs.get(table)
        if tdef is None:
            continue
        refcols = _rowref_cols(tdef)
        if not refcols:
            continue
        for r in det[table]:
            if not isinstance(r, dict):
                continue
            slug = r.get("slug", "?")
            for col in refcols:
                key, ref_table = col["key"], col.get("refTable")
                val = r.get(key)
                if val in (None, ""):
                    if col.get("required"):
                        errors.append(f"{table}/{slug}.{key}: required rowRef is empty")
                    continue
                if ref_table not in order_idx:
                    # EXTERNAL reference — the target table is not in this bundle, so
                    # the row it names is a PRE-EXISTING KEAP row (e.g. a derivation
                    # bundle's posting → an already-seeded account, or entry → invoice).
                    # KEAP validates refTable at create, so a dangling external ref
                    # 400s loudly at absorb — not silent. We only own ORDER *within*
                    # the bundle (the dependency-order rule); an external ref is not
                    # "seeded later". (A self-contained bundle still catches its own
                    # missing/forward refs below, because it includes its own tables.)
                    continue
                elif order_idx[ref_table] > order_idx[table]:
                    errors.append(
                        f"{table}/{slug}.{key}: FORWARD reference to {ref_table!r} "
                        "(seeded later) — KEAP validates refTable at create, so this "
                        "400s the converge; order the bundle dependency-first")
                elif val not in slugs_by_table.get(ref_table, set()):
                    errors.append(
                        f"{table}/{slug}.{key}: rowRef {val!r} is not a seeded slug "
                        f"of {ref_table!r}")
    postings = det.get("posting")
    if (isinstance(det.get("journal-entry"), list) and det.get("journal-entry")
            and isinstance(postings, list)):
        errors.extend(nos_accounting.check_entries(postings))
    invoices = det.get("invoice")
    if isinstance(invoices, list) and invoices:
        lines = det.get("invoice-line")
        if not isinstance(lines, list):
            errors.append("invoice rows require invoice-line rows")
        else:
            errors.extend(nos_accounting.lines_cover_invoices(invoices, lines))
    _check_device_family(bundle, det, errors)
    return errors


def check_fixture_seed(seed: dict, tables_dir: str | pathlib.Path) -> list[str]:
    """Convenience: validate a state/fixtures/<name>.seed.yml as a TRUSTED bundle
    (its {slug:[rows]} IS the deterministic section; fixtures carry no _prov)."""
    return check_bundle({"meta": {"trusted": True}, "deterministic": seed}, tables_dir)


# ── party-resolver: the identity trust boundary ──────────────────────────────
# Synthesis of three reviews (party-resolver row, 2026-09-10). The bundle gate
# above guards STRUCTURE; this guards IDENTITY, and identity has no store-level
# unique index — so a DETERMINISTIC org slug (party-ico-<8digit>) is the real
# backstop: slug-as-row-id upsert turns a two-importer mint race into an
# idempotent PATCH instead of a duplicate (a fork). Content-hash-of-name slugs
# are a FOOTGUN (they shift when normalization improves) — never used.
#
# TWO resolvers, not one: an ORG has a public-registry key (IČO/VAT); a PERSON
# has none you may use (CZ person-DIČ IS rodné číslo — redacted at normalize,
# never a key here), so a person reference NEVER key/name/auto-mints — always
# review. Conflate AND fork are both cardinal sins; the review rung (system-
# visibility rows, staged with repos-importer) is the ENFORCEMENT mechanism.
#
# This module is the PURE core (normalize + checksum + slug + 3-outcome resolve)
# against an explicit index. compose_party_review is the __visibility:system
# review rung: proposed spine rows, not /ingest/v1/capture. KEAP peels the
# meta key on POST and appends table_row_history; ARES verify and merge_party
# stay later.

#: IČO reserved for synthetic fixtures (docs/idea/15): (CZ)?000001\d\d. A real
#: document carrying this range is a data error, not a match — refused outside
#: fixture mode.
_SYNTHETIC_ICO = re.compile(r"^000001\d\d$")
#: Czech legal-form suffixes stripped before a name-exact fallback compare.
_LEGAL_SUFFIXES = re.compile(
    r"[\s,]+(s\.?\s?r\.?\s?o\.?|spol\.?\s?s\s?r\.?\s?o\.?|a\.?\s?s\.?|v\.?\s?o\.?\s?s\.?"
    r"|k\.?\s?s\.?|z\.?\s?s\.?|z\.?\s?ú\.?|o\.?\s?p\.?\s?s\.?|p\.?\s?o\.?|se|SE)\.?$",
    re.IGNORECASE)


def _ico_checksum_ok(ico8: str) -> bool:
    """Czech IČO mod-11 check digit. ico8 is exactly 8 digits."""
    s = sum(int(ico8[i]) * (8 - i) for i in range(7))
    return int(ico8[7]) == (11 - (s % 11)) % 10


def normalize_ico(raw) -> dict | None:
    """Canonicalize a raw IČO value. Returns None if it isn't 1..8 digits.
    Otherwise {value: 8-digit zero-padded, checksum_ok: bool, synthetic: bool}.

    Zero-padding is load-bearing: CSV/XLSX importers see 112 where the store
    holds 00000112 (Excel drops leading zeros) — a raw string compare then
    MISSES the existing party and forks it. Pad both sides before any compare.
    """
    if raw is None:
        return None
    digits = str(raw).strip()
    if not digits.isdigit() or not 1 <= len(digits) <= 8:
        return None
    value = digits.zfill(8)
    return {"value": value,
            "checksum_ok": _ico_checksum_ok(value),
            "synthetic": bool(_SYNTHETIC_ICO.match(value))}


def normalize_org_name(name: str) -> str:
    """Fold diacritics, strip legal-form suffix, lowercase, collapse whitespace.
    For a name-EXACT fallback only (never a person, never a fuzzy match)."""
    if not name:
        return ""
    folded = "".join(c for c in unicodedata.normalize("NFKD", str(name))
                     if not unicodedata.combining(c))
    stripped = _LEGAL_SUFFIXES.sub("", folded).strip()
    return re.sub(r"\s+", " ", stripped).lower()


def org_slug(ico8: str) -> str:
    """The deterministic org slug — the store backstop. Same IČO → same slug →
    a re-import ADDRESSES the same row instead of forking it (it dedups; absorb
    skips a present slug, so field updates are not propagated yet)."""
    return f"party-ico-{ico8}"


def _review(slug=None, matched_by=None, match_value=None, candidates=None, reason=""):
    return {"status": "review", "slug": slug, "matched_by": matched_by,
            "match_value": match_value, "candidates": candidates or [], "reason": reason}


def resolve_party(ref: dict, party_index: dict, *,
                  source_authoritative: bool = False,
                  fixture_mode: bool = False) -> dict:
    """Resolve an importer's party reference against an explicit index.

    ref: {kind: "org"|"person", name/legal_name, ico?, ...}
    party_index: {"by_key": {("ICO", "<8digit>"): slug, ...},   # party ⋈ party-tax-identity, scheme-scoped
                  "by_name": {"<normname>": [slug, ...]}}         # org legal_name only
    Returns {status: resolved|create|review, slug, matched_by, match_value,
             candidates, [reason]}. NEVER auto-merges on ambiguity or a fuzzy
             guess; a person is never auto-resolved.
    """
    by_key = party_index.get("by_key", {})
    by_name = party_index.get("by_name", {})

    if ref.get("kind") == "person":
        # Person-DIČ is rodné číslo (redacted upstream); a name isn't identifying.
        return _review(reason="person: never key/name/auto-resolved — always review")

    norm = normalize_ico(ref.get("ico"))
    if norm is not None:
        if norm["synthetic"] and not fixture_mode:
            return _review(match_value=norm["value"],
                           reason="IČO in reserved synthetic range outside fixture mode")
        usable = norm["synthetic"] if fixture_mode else norm["checksum_ok"]
        if usable:
            key = ("ICO", norm["value"])
            hit = by_key.get(key)
            if hit:
                return {"status": "resolved", "slug": hit, "matched_by": "ico",
                        "match_value": norm["value"], "candidates": [hit]}
            slug = org_slug(norm["value"])
            if source_authoritative:
                return {"status": "create", "slug": slug, "matched_by": "ico",
                        "match_value": norm["value"], "candidates": []}
            return _review(slug=slug, matched_by="ico", match_value=norm["value"],
                           reason="valid IČO, new org, non-authoritative source → confirm")
        # a real IČO that fails its checksum is NOT a key — fall through to name.

    name = ref.get("legal_name") or ref.get("name")
    if name:
        nn = normalize_org_name(name)
        cands = by_name.get(nn, [])
        if len(cands) == 1:
            return {"status": "resolved", "slug": cands[0], "matched_by": "legal_name",
                    "match_value": nn, "candidates": cands}
        if len(cands) > 1:
            return _review(match_value=nn, candidates=cands,
                           reason="name matches more than one org — ambiguous")

    return _review(reason="no valid key and no unique name — needs review")


#: Row-level grade the review rung stamps. Not a table column — KEAP peels
#: `__visibility` the way it peels `__id` (agent.ts extractRowSharing).
REVIEW_VISIBILITY = "system"
_DEVICE_REF_KEYS = ("device_id", "udid", "imei", "serial", "identifier_hash")


def _is_device_ref(ref: dict) -> bool:
    """Owner scheme B: a device identifier is not party slug material."""
    if not isinstance(ref, dict):
        return False
    if any(ref.get(k) not in (None, "") for k in _DEVICE_REF_KEYS):
        return True
    if ref.get("kind") == "device":
        return True
    blob = " ".join(str(ref.get(k) or "") for k in ("slug", "name", "legal_name"))
    return "party-device-" in blob


def _batch_slug(batch_id: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", str(batch_id).lower()).strip("-")
    return (s or "batch")[:40]


def compose_party_review(items: list, *, batch_id: str) -> dict:
    """Turn resolve_party review outcomes into proposed party-spine rows.

    Clustered by batch_id (autoskola-trio: one batch, many spine rows). Born
    `__visibility:system` so they are not normal-visibility parties. Device
    identifiers, synthetic-range data errors, resolved, and create mint nothing.
    Returns a deterministic mapping (party, then tax when an IČO is the key);
    never captures[] / proposals[].
    """
    parties: list[dict] = []
    taxes: list[dict] = []
    seq = 0
    token = _batch_slug(batch_id)
    for item in items or []:
        ref = (item or {}).get("ref") or {}
        res = (item or {}).get("result") or {}
        if res.get("status") != "review" or _is_device_ref(ref):
            continue
        reason = res.get("reason") or ""
        if "synthetic range" in reason:
            continue
        name = (ref.get("legal_name") or ref.get("name") or "").strip()
        kind = "person" if ref.get("kind") == "person" else "org"
        if res.get("matched_by") == "ico" and res.get("slug"):
            slug = res["slug"]
        else:
            if not name and not res.get("candidates"):
                continue
            seq += 1
            slug = f"party-review-{token}-{seq}"
        if kind == "person" and not name:
            continue
        notes = f"review-batch:{batch_id} | {reason}"
        cands = res.get("candidates") or []
        if cands:
            notes += f" | candidates:{','.join(cands)}"
        row = {
            "slug": slug,
            "legal_name": name or slug,
            "party_kind": kind,
            "country": (ref.get("country") or "CZ").strip() or "CZ",
            "notes": notes,
            "__visibility": REVIEW_VISIBILITY,
        }
        parties.append(row)
        if kind == "org" and res.get("matched_by") == "ico" and res.get("match_value"):
            taxes.append({
                "slug": f"tax-{slug}-ico",
                "party": slug,
                "scheme": "ICO",
                "value": res["match_value"],
                "__visibility": REVIEW_VISIBILITY,
            })
    out: dict = {}
    if parties:
        out["party"] = parties
    if taxes:
        out["party-tax-identity"] = taxes
    return out


# ── teardown: the inverse of seed-bundle.yml (cleanup / from-blank / firm removal) ──
# A bundle seeds in dependency order (party before the domain rows that rowRef it);
# tearing it down is the SAME list REVERSED — leaf rows first, the party spine last —
# so onDelete:restrict never refuses a delete whose referrer is still present. The
# executor still probes each row's referrers (the is-delete-safe check) and RETAINS a
# row another firm shares, so a firm-scoped teardown of a shared spine is safe by
# construction. Same primitive serves from-blank test reset AND agency client-removal.
def teardown_plan(bundle: dict) -> list[tuple[str, str]]:
    """Return [(table_slug, row_slug), ...] to delete, leaf-first (reverse of the
    bundle's dependency order). Accepts a full bundle or a raw {slug:[rows]} seed."""
    det = bundle.get("deterministic", bundle) if isinstance(bundle, dict) else {}
    plan: list[tuple[str, str]] = []
    for table in reversed(list(det.keys())):
        for row in det[table]:
            slug = row.get("slug") if isinstance(row, dict) else None
            if slug:
                plan.append((table, slug))
    return plan


def retained_by_survivors(referrers: list, planned: set) -> list:
    """teardown-fork-free's load-bearing half: a row is RETAINED when any referrer
    is NOT itself being removed — a surviving (other-firm) row still needs it, so a
    firm-scoped teardown never breaks another firm. referrers: [{fromTable, fromRow,
    ...}] (the KEAP referrers probe); planned: the set of (table, slug) this run is
    removing. Returns the SURVIVING referrers; non-empty ⇒ retain the row. Pure, so
    the retention decision — not just teardown_plan's ordering — has a real judge."""
    return [r for r in referrers
            if (r.get("fromTable"), r.get("fromRow")) not in planned]


# ── erasure: the rowRef-DOWN closure of what importers wrote about a party ────
# GDPR Art-17 for the digest organ (gdpr-digestion-stage, erasure-party-subject).
# Given a party, enumerate every row any importer wrote that hangs off it — walk
# the rowRef graph DOWNWARD from the party across the table defs' refTable edges:
# party-tax-identity/address/contact (facets), repo → application → package, and
# any FUTURE derived table (invoice → line, …) with zero rework, because the edge
# set is READ from the table defs, not hard-coded (the closure auto-covers a table
# the day it is added). The party ROW itself is never in the closure — it is the
# root of the walk, not a child, and whether to delete it (a person vs an s.r.o.)
# is a deliberate downstream decision, not this enumeration's.
#
# Enumeration is over the LIVE rowRef graph (where the derived data actually is),
# NOT a replay of _prov (which is stripped before absorb — never a column). The
# rowRef graph IS the derivation lineage. The result feeds teardown_plan (leaf-
# first) + the referrers-gated executor, so a row another surviving party still
# shares is retained. Pure over an injected table_reader → offline-testable; the
# CLI wires table_reader to KEAP.
_DISPLAY_FIELDS = ("legal_name", "name", "title", "value", "slug")


def _row_label(row: dict) -> str:
    for f in _DISPLAY_FIELDS:
        if row.get(f):
            return str(row[f])
    return row.get("slug", "?")


def _rowref_closure(party_slug: str, table_reader, tables_dir: str | pathlib.Path):
    """The ONE rowRef-DOWN walk from a party — erasure_plan and party_graph are both
    projections of it (one walk, not two). Reads the rowRef edges FROM the table defs
    (so a future table is covered with no rework) and BFS-collects every row that
    transitively references the party. Returns (rows_by_table, edges): rows_by_table
    {table: [rows]} in dependency order (parents before children, so teardown_plan
    reverses it to leaf-first); edges [{from, to, column}] with ids '<table>:<slug>',
    each pointing from a referencing row IN to the row it references. The party row
    itself is never in rows_by_table (it is the walk's root); its id is an edge
    endpoint. Every edge endpoint is the party root or a row in rows_by_table."""
    tables_dir = pathlib.Path(tables_dir)
    incoming: dict[str, list[tuple[str, str]]] = {}   # refTable -> [(table, column_key)]
    for p in sorted(tables_dir.glob("*.table.yml")):
        tdef = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        tbl = p.name[: -len(".table.yml")]
        for col in _rowref_cols(tdef):
            if col.get("refTable"):
                incoming.setdefault(col["refTable"], []).append((tbl, col["key"]))

    rows_by_table: dict[str, dict] = {}   # table -> {slug: row}, insertion order = dep order
    edges: list[dict] = []
    queue: list[tuple[str, set]] = [("party", {party_slug})]
    while queue:
        ref_table, targets = queue.pop(0)
        for tbl, col in incoming.get(ref_table, []):
            fresh = set()
            for r in table_reader(tbl):
                if not (isinstance(r, dict) and r.get(col) in targets and r.get("slug")):
                    continue
                edges.append({"from": f"{tbl}:{r['slug']}", "to": f"{ref_table}:{r[col]}",
                              "column": col})
                bucket = rows_by_table.setdefault(tbl, {})
                if r["slug"] not in bucket:
                    bucket[r["slug"]] = r
                    fresh.add(r["slug"])
            if fresh:
                queue.append((tbl, fresh))
    return {t: list(v.values()) for t, v in rows_by_table.items()}, edges


def erasure_plan(party_slug: str, table_reader, tables_dir: str | pathlib.Path) -> dict:
    """{table_slug: [rows]} — every row transitively referencing party_slug, in
    dependency order (teardown_plan reverses it to leaf-first). The party row itself
    is excluded. A projection of _rowref_closure (the rows half)."""
    rows_by_table, _edges = _rowref_closure(party_slug, table_reader, tables_dir)
    return rows_by_table


def party_graph(party_slug: str, table_reader, tables_dir: str | pathlib.Path) -> dict:
    """{'nodes': [{id, table, slug, label}], 'edges': [{from, to, column}]} for the
    rowRef closure around a party — the visual-control shaper (data-graph-view /
    kmenová data). The party node is the centre; edges point from a referencing row
    IN. A projection of _rowref_closure (rows → labelled nodes + the party root);
    the same {nodes, edges} a host tool renders to mermaid and a face view consumes."""
    rows_by_table, edges = _rowref_closure(party_slug, table_reader, tables_dir)
    label = party_slug
    for r in table_reader("party"):
        if isinstance(r, dict) and r.get("slug") == party_slug:
            label = _row_label(r)
            break
    nodes = {f"party:{party_slug}": {"id": f"party:{party_slug}", "table": "party",
                                     "slug": party_slug, "label": label}}
    for tbl, rows in rows_by_table.items():
        for r in rows:
            nid = f"{tbl}:{r['slug']}"
            nodes[nid] = {"id": nid, "table": tbl, "slug": r["slug"], "label": _row_label(r)}
    return {"nodes": list(nodes.values()), "edges": edges}


# ── importer-spine: parse → normalize → compose → GATE (the harness) ─────────
# The reusable spine every importer shares (importer-spine decision, 2026-09-10).
# An IMPORTER supplies only format knowledge as three stages; the harness owns
# everything shared — provenance stamping and the gate — so the load-bearing
# checks (per-row _prov, structure, dependency order) are written ONCE and cannot
# drift per importer. This is the judge for the `raw-never-touches-knowledge`
# constitutional rule: only a bundle that PASSES check_bundle is returned to be
# absorbed; raw records never reach a live door un-gated. It stays a plain
# function over a duck-typed importer, not a framework (YAGNI).
#
# An importer is any object carrying:  source_id, name, version (strings)
#   parse(raw)      -> list[record]           # format-specific, the only quirky part
#   normalize(recs) -> list[record]           # party resolution / redaction / folding
#   compose(recs)   -> {"<table-slug>": [row, ...], ...}   # KEY ORDER = dependency order
# Rows compose WITHOUT provenance; the harness stamps _prov so an importer cannot
# forget it.

def _content_hash(obj) -> str:
    """Stable sha256 of a row's content (canonical JSON, sans _prov)."""
    payload = {k: v for k, v in obj.items() if k != "_prov"} if isinstance(obj, dict) else obj
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def stamp_provenance(deterministic: dict, *, source_id: str, importer_version: str) -> None:
    """Attach _prov{source_id, importer_version, content_hash} to every row, in
    place. content_hash is per-row provenance for future audit reconciliation —
    NOT yet consumed: erasure walks the live rowRef graph (erasure_plan), not
    _prov. The gate requires it (untrusted-row completeness); it is cheap."""
    for rows in deterministic.values():
        for row in rows:
            if isinstance(row, dict):
                row["_prov"] = {"source_id": source_id,
                                "importer_version": importer_version,
                                "content_hash": _content_hash(row)}


def strip_provenance(deterministic: dict) -> dict:
    """The deterministic section with _prov removed from each row — what actually
    upserts into a DataTable. _prov is stripped because it is never a table
    column; capturing it into an audit-lineage store is not built yet."""
    return {t: [{k: v for k, v in r.items() if k != "_prov"} for r in rows]
            for t, rows in deterministic.items()}


#: storage-subdir unit (2026-09-20): the invoice import-inbox layout is
#: {nos_data_root}/tenants/<t>/users/<uid>/inbox/accounting/<book_owner-slug>/
#: {incoming,extracts,processed}/ (ssot/doctrine/filesystem.md class 3, KEAP
#: inbox precedent) — Model C: the slug is a data-organization label inside
#: the consultant's ONE tenant, never a per-client tenant/RBAC boundary.
BOOK_OWNER_LEAVES = ("incoming", "extracts", "processed")


def resolve_data_root(repo: pathlib.Path, environ: dict | None = None) -> pathlib.Path:
    """Runtime nos_data_root. Env wins; else config.yml (the estate override);
    else ~/nos. default.config.yml is Jinja — not a path we can walk."""
    env = (environ if environ is not None else os.environ).get("NOS_DATA_ROOT", "").strip()
    if env:
        return pathlib.Path(env).expanduser()
    cfg = repo / "config.yml"
    if cfg.is_file():
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        v = data.get("nos_data_root") if isinstance(data, dict) else None
        if isinstance(v, str) and v.strip() and "{{" not in v:
            return pathlib.Path(v.strip()).expanduser()
    return pathlib.Path.home() / "nos"


def infer_book_owner_slug(root: str | pathlib.Path) -> str | None:
    """The book_owner-slug an importer `root` sits under, IF `root` follows
    the documented .../accounting/<slug>/{incoming,extracts,processed} shape
    — else None (a flat/ad-hoc root, e.g. a fixture directory, names nothing).
    Purely a filename read — never resolves or mints; that's the importer's
    job, comparing this against --book-owner-ico so the two cannot drift."""
    p = pathlib.Path(root)
    if p.name in BOOK_OWNER_LEAVES and p.parent.name:
        return p.parent.name
    return None


def note_party_resolve(importer, ref: dict, party_index: dict, **kw) -> dict:
    """resolve_party and stash review/ambiguous outcomes for the harness rung.

    Importers call this instead of resolve_party so run_importer can compose
    proposed spine rows once — not a copy of compose_party_review in each CLI.
    """
    result = resolve_party(ref, party_index, **kw)
    if result.get("status") == "review":
        sink = getattr(importer, "party_reviews", None)
        if sink is None:
            importer.party_reviews = []
            sink = importer.party_reviews
        sink.append({"ref": ref, "result": result})
    return result


def _party_review_items(importer, records) -> list:
    items = list(getattr(importer, "party_reviews", None) or [])
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if "ref" in rec and "result" in rec:
            items.append({"ref": rec["ref"], "result": rec["result"]})
    return items


def _merge_party_review(deterministic: dict, extra: dict) -> None:
    """Fold review-rung tables into compose output; party stays first."""
    if not extra:
        return
    parties = list(deterministic.get("party") or [])
    taxes = list(deterministic.get("party-tax-identity") or [])
    seen_p = {r.get("slug") for r in parties}
    seen_t = {r.get("slug") for r in taxes}
    for r in extra.get("party") or []:
        if r.get("slug") not in seen_p:
            parties.append(r)
            seen_p.add(r.get("slug"))
    for r in extra.get("party-tax-identity") or []:
        if r.get("slug") not in seen_t:
            taxes.append(r)
            seen_t.add(r.get("slug"))
    rest = {k: v for k, v in deterministic.items() if k not in ("party", "party-tax-identity")}
    deterministic.clear()
    if parties:
        deterministic["party"] = parties
    if taxes:
        deterministic["party-tax-identity"] = taxes
    deterministic.update(rest)


# ── isdoc-vision-crosscheck: DETECT + SURFACE, never auto-resolve ────────────
# Two independently-extracted records of the same invoice (ISDOC XML vs a
# vision extraction) can disagree — a scanned total mis-OCR'd, a supplier ICO
# transposed. invoice_cross_check is the pure field-level comparator;
# reconcile_invoices partitions a batch so a mismatching invoice never reaches
# deterministic invoice[] (DROPPED, routed to invoice-review instead); a clean
# match, or an invoice with no vision extract at all, absorbs unchanged.
# compose_invoice_review is the minimal review sink this needs — there is no
# compose_party_review to mirror (that rung lands with repos-importer, not
# shipped) — a NEW __visibility: tier-managers facet (invoice-review.table.yml).

#: Compliance-relevant fields compared field-by-field. Amounts use amount_tol
#: (relative) with a fixed 1-haler/1-cent floor (money path: 2dp, no float
#: drift); everything else is an exact post-normalize compare.
def _amounts_mismatch(a, b, amount_tol: float) -> bool:
    if a is None or b is None:
        return a != b
    a, b = float(a), float(b)
    return abs(a - b) > max(0.01, amount_tol * max(abs(a), abs(b)))


def invoice_cross_check(isdoc_row: dict, vision_extract: dict, amount_tol: float = 0.01) -> list[dict]:
    """Field-level disagreements between an ISDOC record and a vision-extracted
    record (both the isdoc-record.schema.yaml dict shape). Returns
    [{field, isdoc_value, vision_value}, ...] — empty means clean. Pure;
    never auto-resolves, only reports."""
    out: list[dict] = []
    if _amounts_mismatch(isdoc_row.get("payable"), vision_extract.get("payable"), amount_tol):
        out.append({"field": "payable", "isdoc_value": isdoc_row.get("payable"),
                    "vision_value": vision_extract.get("payable")})
    a_cur, b_cur = isdoc_row.get("currency"), vision_extract.get("currency")
    if (a_cur or None) != (b_cur or None):
        out.append({"field": "currency", "isdoc_value": a_cur, "vision_value": b_cur})
    a_id, b_id = isdoc_row.get("id"), vision_extract.get("id")
    if (a_id or None) != (b_id or None):
        out.append({"field": "document_number", "isdoc_value": a_id, "vision_value": b_id})
    for role in ("seller", "buyer"):
        a_ref, b_ref = isdoc_row.get(role) or {}, vision_extract.get(role) or {}
        a_ico, b_ico = normalize_ico(a_ref.get("ico")), normalize_ico(b_ref.get("ico"))
        a_val = a_ico["value"] if a_ico else a_ref.get("ico")
        b_val = b_ico["value"] if b_ico else b_ref.get("ico")
        if (a_val or None) != (b_val or None):
            out.append({"field": f"{role}.ico", "isdoc_value": a_ref.get("ico"),
                        "vision_value": b_ref.get("ico")})
        a_name, b_name = normalize_org_name(a_ref.get("name") or ""), normalize_org_name(b_ref.get("name") or "")
        if a_name and b_name and a_name != b_name:
            out.append({"field": f"{role}.name", "isdoc_value": a_ref.get("name"),
                        "vision_value": b_ref.get("name")})
    return out


def reconcile_invoices(isdoc_records: list[dict], vision_records: list[dict],
                       amount_tol: float = 0.01) -> tuple[list[dict], list[dict]]:
    """Partition an ISDOC batch against a vision batch, matched by `id`.
    Returns (clean, review_items): clean = ISDOC records with no vision extract
    OR a within-tolerance match (absorb unchanged); review_items =
    [{document_number, mismatches}] for every match that disagrees — those
    ISDOC records are DROPPED from clean, never a silent absorb."""
    by_id = {v.get("id"): v for v in vision_records if v.get("id")}
    clean, review_items = [], []
    for rec in isdoc_records:
        vision = by_id.get(rec.get("id"))
        if vision is None:
            clean.append(rec)
            continue
        mismatches = invoice_cross_check(rec, vision, amount_tol)
        if mismatches:
            review_items.append({"document_number": rec.get("id"), "mismatches": mismatches})
        else:
            clean.append(rec)
    return clean, review_items


def compose_invoice_review(review_items: list[dict], *, batch_id: str) -> dict:
    """review_items ([{document_number, mismatches}]) -> {"invoice-review": [row]},
    one row per mismatching invoice — never captures[] / proposals[]."""
    token = _batch_slug(batch_id)
    rows = []
    for item in review_items or []:
        doc = item.get("document_number") or "?"
        rows.append({
            "slug": f"invoice-review-{token}-{_batch_slug(doc)}",
            "document_number": doc,
            "mismatches": item.get("mismatches") or [],
        })
    return {"invoice-review": rows} if rows else {}


def run_importer(importer, raw, tables_dir: str | pathlib.Path) -> tuple[dict, list[str]]:
    """Run an importer's three stages, stamp provenance, and GATE. Returns
    (bundle, errors); a non-empty errors list means the bundle is unsafe to
    absorb and the caller must refuse it. The bundle is untrusted (meta.trusted
    is False), so every row must carry _prov — which the harness just stamped."""
    records = importer.parse(raw)
    records = importer.normalize(records)
    deterministic = importer.compose(records)
    _merge_party_review(
        deterministic,
        compose_party_review(
            _party_review_items(importer, records),
            batch_id=getattr(importer, "source_id", None) or importer.name,
        ),
    )
    raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8")
    bundle = {
        "meta": {
            "source_id": importer.source_id,
            "importer": importer.name,
            "importer_version": importer.version,
            "content_hash": hashlib.sha256(raw_bytes).hexdigest(),
            "trusted": False,
        },
        "deterministic": deterministic,
    }
    stamp_provenance(deterministic, source_id=importer.source_id,
                     importer_version=importer.version)
    return bundle, check_bundle(bundle, tables_dir)
