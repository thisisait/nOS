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
touch nothing live. It validates ONLY the deterministic section for now (the rung
seed-bundle.yml consumes); captures/proposals validation lands with their doors.

WHY A SHARED FUNCTION (importer-spine decision, 2026-09-10): normalize/provenance/
gate are written ONCE and reused by every importer, so the load-bearing checks
can't drift per importer. It is a plain function, not a framework (YAGNI).

TRUST (digest-bundle-ir decision, 2026-09-10): meta.trusted==True marks a
git-authored fixture bundle — already gated by the fixture ORDER gates — so the
per-row provenance stamp is NOT required. An importer bundle is untrusted and
every deterministic row must carry a _prov{source_id,importer_version,content_hash}.
"""
from __future__ import annotations

import pathlib

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
