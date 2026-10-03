#!/usr/bin/env python3
"""Project KEAP party sites one-way into PostGIS (geo.party_site) — and erase them.

KEAP owns the rows (party-site, entered by the operator; party-registry-status,
ARES's registered seat). This copies their registry keys into geo.party_site in
ONE transaction (TRUNCATE + COPY), so PostGIS never holds a site KEAP no longer
has after the next run. An ARES seat is projected as kind=hq/source=ares only
for a party without an operator-entered hq. The view geo.party_site_geom
resolves the keys to RÚIAN / INSPIRE geometry (EPSG:5514).

  tools/geo-project-sites.py                      # nightly (Pulse geo-sites:project)
  tools/geo-project-sites.py --erase-party SLUG   # GDPR: called by digest-teardown --erase-party --confirm

A KEAP read failure exits 2 BEFORE anything is truncated. Exit 0 done or idle (no
PostGIS / no KEAP here), 1 psql failed or PostgreSQL down.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
from keap_api import agent_base, proxy_header  # noqa: E402
from _geo_db import geo_db_state  # noqa: E402

COLS = ["slug", "party", "kind", "source", "ruian_adm", "ku_kod", "parcel_no", "kod_so"]
DDL = """CREATE SCHEMA IF NOT EXISTS geo;
CREATE TABLE IF NOT EXISTS geo.party_site (
  slug text PRIMARY KEY, party text NOT NULL, kind text NOT NULL, source text NOT NULL,
  ruian_adm bigint, ku_kod int, parcel_no text, kod_so bigint);
CREATE INDEX IF NOT EXISTS party_site_party ON geo.party_site (party);"""
VIEW = """CREATE OR REPLACE VIEW geo.party_site_geom AS
SELECT s.*, a.geom AS adm_geom, c.geom AS parcel_geom, b.geom AS building_geom
FROM geo.party_site s
LEFT JOIN geo.ruian_adm a ON a.kod_adm = s.ruian_adm
LEFT JOIN geo.inspire_cp c ON c.ku_kod = s.ku_kod AND c.parcel_no = s.parcel_no
LEFT JOIN geo.inspire_bu b ON b.kod_so = s.kod_so;"""


def _ro_token() -> str:
    tok = os.environ.get("KEAP_AGENT_TOKEN_RO", "").strip()
    if tok:
        return tok
    return subprocess.run(["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RO"],
                          capture_output=True, text=True).stdout.strip()


def keap_rows(table: str) -> list[dict]:
    """Every row of a KEAP table; 404 (table not created here) is an empty table."""
    req = urllib.request.Request(f"{agent_base()}/agent/v1/tables/{table}/rows",
                                 headers={"Authorization": f"Bearer {_ro_token()}", **proxy_header()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return (d.get("data") or {}).get("rows") or d.get("rows") or []


def project(sites: list[dict], registry: list[dict]) -> list[dict]:
    """KEAP rows -> geo.party_site rows. Operator hq wins over ARES's seat."""
    out = [{"slug": s["slug"], "party": s["party"], "kind": s["kind"], "source": "party-site",
            "ruian_adm": s.get("ruian_adm"), "ku_kod": s.get("ku_kod"),
            "parcel_no": s.get("parcel_no"), "kod_so": s.get("kod_so")}
           for s in sites if s.get("slug") and s.get("party") and s.get("kind")]
    has_hq = {r["party"] for r in out if r["kind"] == "hq"}
    out += [{"slug": r["slug"], "party": r["party"], "kind": "hq", "source": "ares",
             "ruian_adm": r["sidlo_ruian_adm"], "ku_kod": None, "parcel_no": None, "kod_so": None}
            for r in registry
            if r.get("sidlo_ruian_adm") and r.get("party") and r["party"] not in has_hq]
    return out


def _psql(container: str, db: str, script: str, *variables: str) -> int:
    argv = ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-q"]
    for v in variables:
        argv += ["-v", v]
    r = subprocess.run(argv, input=script.encode(), capture_output=True)
    if r.returncode:
        print(f"psql failed: {r.stderr.decode()[-1500:]}", file=sys.stderr)
    return 1 if r.returncode else 0


def write(rows: list[dict], container: str, db: str) -> int:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow(["" if r[c] is None else r[c] for c in COLS])
    script = (f"{DDL}\nBEGIN;\nTRUNCATE geo.party_site;\n"
              f"COPY geo.party_site ({', '.join(COLS)}) FROM STDIN WITH (FORMAT csv);\n"
              f"{buf.getvalue()}\\.\nCOMMIT;\n"
              # The view needs the loader's tables; before the first monthly load it waits.
              "SELECT to_regclass('geo.ruian_adm') IS NOT NULL AND to_regclass('geo.inspire_cp') IS NOT NULL "
              "AND to_regclass('geo.inspire_bu') IS NOT NULL AS ready \\gset\n"
              f"\\if :ready\n{VIEW}\n\\endif\n")
    return _psql(container, db, script)


def erase(party: str, container: str, db: str) -> int:
    """Delete a party's projected sites now (not at the next nightly run)."""
    return _psql(container, db, f"{DDL}\nDELETE FROM geo.party_site WHERE party = :'party';\n", f"party={party}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--container", default="infra-postgresql-1")
    ap.add_argument("--db", default="geo")
    ap.add_argument("--erase-party", metavar="SLUG")
    a = ap.parse_args()
    state = geo_db_state(a.container, a.db)
    if state == "absent":
        print(f"idle: no {a.db} database in {a.container} — nothing projected, nothing to erase")
        return 0
    if state == "down":
        print(f"REFUSING: {a.container} is not answering — geo.party_site untouched", file=sys.stderr)
        return 1
    if a.erase_party:
        return erase(a.erase_party, a.container, a.db)
    if subprocess.run(["docker", "inspect", "iiab-keap-1"], capture_output=True).returncode:
        print("idle: no KEAP container — nothing to project")
        return 0
    try:
        rows = project(keap_rows("party-site"), keap_rows("party-registry-status"))
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: KEAP unreadable ({exc}) — previous projection kept", file=sys.stderr)
        return 2
    rc = write(rows, a.container, a.db)
    if rc == 0:
        print(f"geo.party_site: {len(rows)} rows projected — read back: tools/geo-status.py")
    return rc


if __name__ == "__main__":
    sys.exit(main())
