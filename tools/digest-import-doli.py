#!/usr/bin/env python3
"""digest-import-doli — hydrator organelle: Dolibarr thirdparties → KEAP party.

Dolibarr is the CRM desk when installed. This importer projects open
thirdparties (IČO required) through the digest gate into `party` /
`party-tax-identity`. It does not call Dolibarr REST; it reads the MariaDB
schema nOS already created. Bone is not a hydrator. Agents still read tables.

  tools/digest-import-doli.py                    # docker fetch, gate, print (dry)
  tools/digest-import-doli.py --absorb           # upsert (skip slugs already present)
  tools/digest-import-doli.py --from-json f.json # tests / no docker

Exit 0 done/dry/idle (no desk) · 1 gate refused · 2 desk present but unreadable.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import absorb  # noqa: E402
import nos_digest  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"
DOLI_CONTAINER = os.environ.get("DOLI_CONTAINER", "b2b-dolibarr-1")
MARIADB_CONTAINER = os.environ.get("MARIADB_CONTAINER", "infra-mariadb-1")
JOIN = "nos:doli:"

# Dolibarr 21 has no `idprof1` column — the legacy idprof1/2/3 became
# siren/siret/ape in llx_societe (measured against the live 21.0.4 schema,
# 2026-09-21: "Unknown column 's.idprof1'"). CZ "Prof id 1" (IČO) lands in
# `siren`; the parse side keeps the idprof1 KEY for --from-json fixtures.
_SQL = (
    "SELECT s.rowid, s.nom, IFNULL(s.name_alias,''), '', "
    "IFNULL(s.siren,''), IFNULL(c.code,'CZ') "
    "FROM llx_societe s LEFT JOIN llx_c_country c ON c.rowid=s.fk_pays "
    "WHERE s.status=1"
)


class DoliPartyImporter:
    """MariaDB llx_societe rows → EN-16931 party spine. Format knowledge only."""

    name = "doli-party"
    version = "0.1.0"

    def __init__(self, source_id: str = "doli", *, fixture_mode: bool = False):
        self.source_id = source_id
        self.fixture_mode = fixture_mode
        self.skipped: list[str] = []

    def parse(self, raw: str) -> list[dict]:
        data = json.loads(raw or "[]")
        if not isinstance(data, list):
            raise ValueError("doli-party raw must be a JSON array")
        return data

    def normalize(self, records: list[dict]) -> list[dict]:
        out = []
        for r in records:
            name = (r.get("legal_name") or r.get("nom") or "?").strip()
            raw_ico = (r.get("ico") or r.get("idprof1") or r.get("siren") or "")
            norm = nos_digest.normalize_ico(raw_ico)
            if norm is None:
                self.skipped.append(f"{name!r}: no valid IČO")
                continue
            if norm["synthetic"] and not self.fixture_mode:
                self.skipped.append(f"{name!r}: synthetic IČO outside fixture mode")
                continue
            if not self.fixture_mode and not norm["checksum_ok"]:
                self.skipped.append(f"{name!r}: IČO fails mod-11")
                continue
            rowid = r.get("rowid") or r.get("id")
            out.append({
                "ico8": norm["value"],
                "legal_name": (r.get("legal_name") or r.get("nom") or "").strip(),
                "trading_name": (r.get("trading_name") or r.get("name_alias") or "").strip(),
                "country": (r.get("country") or "CZ").strip()[:2].upper() or "CZ",
                "rowid": rowid,
            })
        return out

    def compose(self, records: list[dict]) -> dict:
        parties: dict[str, dict] = {}
        taxes: list[dict] = []
        for r in records:
            slug = nos_digest.org_slug(r["ico8"])
            if slug in parties:
                continue
            notes = f"{JOIN}{r['rowid']}" if r.get("rowid") is not None else f"imported from {self.source_id}"
            row = {
                "slug": slug,
                "legal_name": r["legal_name"],
                "party_kind": "org",
                "country": r["country"],
                "notes": notes,
            }
            if r["trading_name"]:
                row["trading_name"] = r["trading_name"]
            parties[slug] = row
            taxes.append({
                "slug": f"tax-{slug}-ico",
                "party": slug,
                "scheme": "ICO",
                "value": r["ico8"],
            })
        return {"party": list(parties.values()), "party-tax-identity": taxes}


def _docker_exec(container: str, argv: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["docker", "exec"]
    if env:
        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])
    cmd.append(container)
    cmd.extend(argv)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _container_running(name: str) -> bool:
    try:
        p = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0 and p.stdout.strip() == "true"


def fetch_thirdparties() -> list[dict] | None:
    """None = no desk (idle). Empty list = desk with no open orgs."""
    if not _container_running(DOLI_CONTAINER) or not _container_running(MARIADB_CONTAINER):
        return None
    pw_run = _docker_exec(DOLI_CONTAINER, ["printenv", "DOLI_DB_PASSWORD"])
    user_run = _docker_exec(DOLI_CONTAINER, ["printenv", "DOLI_DB_USER"])
    db_run = _docker_exec(DOLI_CONTAINER, ["printenv", "DOLI_DB_NAME"])
    if pw_run.returncode != 0 or not pw_run.stdout.strip():
        raise RuntimeError("desk is up but DOLI_DB_PASSWORD is unreadable")
    user = (user_run.stdout.strip() if user_run.returncode == 0 else "") or "dolibarr"
    db = (db_run.stdout.strip() if db_run.returncode == 0 else "") or "dolibarr"
    q = _docker_exec(
        MARIADB_CONTAINER,
        ["mariadb", "-u", user, "--batch", "--raw", "--skip-column-names", db, "-e", _SQL],
        env={"MYSQL_PWD": pw_run.stdout.strip()},
    )
    if q.returncode != 0:
        raise RuntimeError(f"mariadb query failed: {(q.stderr or q.stdout)[:240]}")
    rows = []
    for line in q.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        rows.append({
            "rowid": parts[0],
            "nom": parts[1],
            "name_alias": parts[2],
            "idprof1": parts[3],
            "siren": parts[4],
            "country": parts[5] or "CZ",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="JSON array of thirdparties (skip docker)")
    ap.add_argument("--absorb", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--fixture-mode", action="store_true")
    args = ap.parse_args()

    if args.from_json:
        path = pathlib.Path(args.from_json)
        if not path.is_absolute():
            path = REPO / path
        raw = path.read_text(encoding="utf-8")
    else:
        try:
            fetched = fetch_thirdparties()
        except RuntimeError as e:
            print(f"doli-party: {e}", file=sys.stderr)
            return 2
        if fetched is None:
            print("doli-party: idle (no Dolibarr desk)", file=sys.stderr)
            return 0
        raw = json.dumps(fetched)

    importer = DoliPartyImporter(fixture_mode=args.fixture_mode)
    bundle, errors = nos_digest.run_importer(importer, raw, TABLES_DIR)
    for s in importer.skipped:
        print(f"skip {s}", file=sys.stderr)
    if errors:
        print("GATE REFUSED the bundle — nothing absorbed:", file=sys.stderr)
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1
    n = sum(len(v) for v in bundle["deterministic"].values())
    print(f"gate OK: {n} row(s) across {len(bundle['deterministic'])} table(s)"
          f"{'  (DRY)' if not args.absorb else ''}", file=sys.stderr)
    if args.absorb:
        return absorb(bundle)
    text = yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True)
    if args.out:
        outp = pathlib.Path(args.out)
        if not outp.is_absolute():
            outp = REPO / outp
        outp.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
