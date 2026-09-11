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
import pathlib
import re
import unicodedata

import yaml

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
                    errors.append(
                        f"{table}/{slug}.{key}: rowRef target table {ref_table!r} "
                        "is not seeded in this bundle")
                elif order_idx[ref_table] > order_idx[table]:
                    errors.append(
                        f"{table}/{slug}.{key}: FORWARD reference to {ref_table!r} "
                        "(seeded later) — KEAP validates refTable at create, so this "
                        "400s the converge; order the bundle dependency-first")
                elif val not in slugs_by_table.get(ref_table, set()):
                    errors.append(
                        f"{table}/{slug}.{key}: rowRef {val!r} is not a seeded slug "
                        f"of {ref_table!r}")
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
# against an explicit index. ARES verify, the __visibility:system review rung,
# and merge_party choreography are KEAP-integrated and land with repos-importer.

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
    a re-import PATCHes the row instead of forking it."""
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
    place. content_hash is per-row so erasure can walk from a source to exactly
    the derived rows it produced (the erasure-propagation contract)."""
    for rows in deterministic.values():
        for row in rows:
            if isinstance(row, dict):
                row["_prov"] = {"source_id": source_id,
                                "importer_version": importer_version,
                                "content_hash": _content_hash(row)}


def strip_provenance(deterministic: dict) -> dict:
    """The deterministic section with _prov removed from each row — what actually
    upserts into a DataTable. _prov is absorbed into audit lineage separately;
    it is never a table column."""
    return {t: [{k: v for k, v in r.items() if k != "_prov"} for r in rows]
            for t, rows in deterministic.items()}


def run_importer(importer, raw, tables_dir: str | pathlib.Path) -> tuple[dict, list[str]]:
    """Run an importer's three stages, stamp provenance, and GATE. Returns
    (bundle, errors); a non-empty errors list means the bundle is unsafe to
    absorb and the caller must refuse it. The bundle is untrusted (meta.trusted
    is False), so every row must carry _prov — which the harness just stamped."""
    records = importer.parse(raw)
    records = importer.normalize(records)
    deterministic = importer.compose(records)
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
