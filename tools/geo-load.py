#!/usr/bin/env python3
"""Load Czech open cadastral data for the configured regions into PostGIS (`geo` db).

Sources (all open, no account): the ČÚZK KÚ catalogue (which KÚ/obec lies in
which kraj), RÚIAN address points CSV (CC-BY 4.0), INSPIRE Cadastral Parcels
per KÚ and Buildings per obec (GML, "no conditions"). Downloads are conditional
(If-Modified-Since) into --cache-dir; a layer whose files did not change and
whose table exists is not reloaded. Each layer is loaded into a staging table
and swapped in ONE transaction, so a failed run leaves the previous data.
Geometry is stored as delivered, EPSG:5514 (S-JTSK Krovak East North).

  tools/geo-load.py --regions 35 --cache-dir ~/nos-cache/geo
  tools/geo-load.py --regions 35 --cache-dir /tmp/g --container nos-geo-e2e --max-units 5

Success is NOT reported here: tools/geo-status.py reads the row counts back.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import email.utils
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _geo_db import geo_db_state  # noqa: E402

KU_CATALOG = "https://services.cuzk.gov.cz/sestavy/cis/SC_SEZNAMKUKRA_DOTAZ.zip"
# Published monthly as of the last day of the previous month; the HTML index sits
# behind a bot captcha, so the URL is computed, not scraped.
ADM_URL = "https://vdp.cuzk.gov.cz/vymenny_format/csv/{}_OB_ADR_csv.zip"
CP_URL = "https://services.cuzk.gov.cz/gml/inspire/cp/epsg-5514/{}.zip"
BU_URL = "https://services.cuzk.gov.cz/gml/inspire/bu/epsg-5514/{}.zip"
UA = {"User-Agent": "nos-geo-load (open-data loader)"}
BATCH = 100

ADM_COLS = ["kod_adm", "kod_obce", "nazev_obce", "kod_momc", "nazev_momc", "kod_obvodu_prahy",
            "nazev_obvodu_prahy", "kod_casti_obce", "nazev_casti_obce", "kod_ulice", "nazev_ulice",
            "typ_so", "cislo_domovni", "cislo_orientacni", "znak_co", "psc", "y", "x", "plati_od"]


def region_units(catalog_csv: str, regions: set[str]) -> tuple[list[str], list[str]]:
    """(KÚ codes, obec codes) currently valid (no PLATNOST_DO) in the given kraj codes."""
    ku, obec = set(), set()
    for row in csv.DictReader(io.StringIO(catalog_csv), delimiter=";"):
        if row["KRAJ_KOD"] in regions and not row["PLATNOST_DO"]:
            ku.add(row["KU_KOD"])
            obec.add(row["OBEC_KOD"])
    return sorted(ku), sorted(obec)


def adm_body_lines(csv_text: str) -> list[str]:
    """One per-obec RÚIAN CSV without its header; refuses a column drift."""
    lines = csv_text.splitlines()
    if not lines:
        return []
    if len(lines[0].split(";")) != len(ADM_COLS):
        raise SystemExit(f"RÚIAN CSV header changed: {lines[0]!r}")
    return [l for l in lines[1:] if l.strip()]


def adm_candidates(today: datetime.date) -> list[str]:
    """Last day of the previous month, then the one before (publication lag)."""
    first = today.replace(day=1)
    last = first - datetime.timedelta(days=1)
    before = last.replace(day=1) - datetime.timedelta(days=1)
    return [d.strftime("%Y%m%d") for d in (last, before)]


def fetch(url: str, dest: Path) -> bool:
    """Conditional GET into dest; True when a new copy arrived."""
    req = urllib.request.Request(url, headers=dict(UA))
    if dest.exists():
        req.add_header("If-Modified-Since", email.utils.formatdate(dest.stat().st_mtime, usegmt=True))
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
            lm = r.headers.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return False
        raise SystemExit(f"{url}: HTTP {e.code}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    if lm:
        t = email.utils.parsedate_to_datetime(lm).timestamp()
        os.utime(dest, (t, t))
    return True


def fetch_all(urls: dict[str, Path]) -> int:
    with ThreadPoolExecutor(max_workers=4) as pool:
        return sum(pool.map(lambda kv: fetch(*kv), urls.items()))


class Pg:
    def __init__(self, docker: str, container: str, db: str):
        self.base = [docker, "exec", "-i", container]
        self.psql = self.base + ["psql", "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-q"]
        self.db = db

    def sql(self, text: str, stdin: bytes | None = None) -> str:
        argv = self.psql + (["-c", text] if stdin is not None else ["-tA"])
        r = subprocess.run(argv, input=stdin if stdin is not None else text.encode(), capture_output=True)
        if r.returncode:
            raise SystemExit(f"psql failed: {r.stderr.decode()[-2000:]}")
        return r.stdout.decode()

    def current(self, table: str, sig: str) -> bool:
        """The table exists and was last loaded for exactly this set of units."""
        if self.sql(f"SELECT to_regclass('geo.{table}') IS NOT NULL;").strip() != "t":
            return False
        last = self.sql(f"SELECT sig FROM geo.load_log WHERE layer = '{table}' ORDER BY loaded_at DESC LIMIT 1;")
        return last.strip() == sig

    def ogr_append(self, files: list[Path], staging: str, select: str, nlt: str) -> list[str]:
        """Stream a batch of zips into the container's /tmp and ogr2ogr-append each.
        Returns the files that lack the layer (e.g. obce with BuildingPart points only)."""
        layer = select.rsplit(" FROM ", 1)[1]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for f in files:
                tar.add(f, arcname=f.name)
        script = (
            "set -e; d=$(mktemp -d); trap 'rm -rf $d' EXIT; tar -x -C $d; "
            "for f in $d/*.zip; do "
            f"ogrinfo -ro -q /vsizip/$f | grep -qE '^[0-9]+: {layer}( |$)' || {{ echo SKIP $(basename $f); continue; }}; "
            f"ogr2ogr -append -f PostgreSQL 'PG:dbname={self.db} user=postgres' /vsizip/$f "
            f"-nln geo.{staging} -lco GEOMETRY_NAME=geom -lco PRECISION=NO -nlt {nlt} -a_srs EPSG:5514 "
            f"-sql \"{select}\" --config PG_USE_COPY YES; done")
        r = subprocess.run(self.base + ["sh", "-c", script], input=buf.getvalue(), capture_output=True)
        if r.returncode:
            errs = [l for l in r.stderr.decode().splitlines() if "ERROR" in l or "FATAL" in l]
            raise SystemExit("ogr2ogr failed:\n" + "\n".join(errs[-20:] or [r.stderr.decode()[-2000:]]))
        return [l.split()[1] for l in r.stdout.decode().splitlines() if l.startswith("SKIP ")]


def load_gml(pg: Pg, files: list[Path], table: str, ddl: str, select: str, finish: str, nlt: str, sig: str,
             index: str) -> list[str]:
    staging = f"_{table}_load"
    pg.sql(f"DROP TABLE IF EXISTS geo.{staging};")
    skipped: list[str] = []
    for i in range(0, len(files), BATCH):
        skipped += pg.ogr_append(files[i:i + BATCH], staging, select, nlt)
    # TRUNCATE + INSERT, never DROP: geo.party_site_geom (and later readers) depend on the table.
    pg.sql(f"""BEGIN;
CREATE TABLE IF NOT EXISTS geo.{table} ({ddl});
CREATE INDEX IF NOT EXISTS {table}_geom ON geo.{table} USING gist (geom);
{index}
TRUNCATE geo.{table};
INSERT INTO geo.{table} {finish.format(staging=f'geo.{staging}')};
DROP TABLE geo.{staging};
INSERT INTO geo.load_log(layer, files, rows, sig) SELECT '{table}', {len(files) - len(skipped)}, count(*), '{sig}' FROM geo.{table};
COMMIT;""")
    return skipped


def load_adm(pg: Pg, zip_path: Path, obce: set[str], sig: str) -> int:
    body: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            m = re.search(r"_OB_(\d+)_ADR\.csv$", name)
            if m and m.group(1) in obce:
                body += adm_body_lines(z.read(name).decode("cp1250"))
    cols = ", ".join(f"{c} text" for c in ADM_COLS)
    pg.sql(f"DROP TABLE IF EXISTS geo._adm_load; CREATE TABLE geo._adm_load ({cols});")
    pg.sql("\\copy geo._adm_load FROM pstdin WITH (FORMAT csv, DELIMITER ';')",
           stdin=("\n".join(body) + "\n").encode())
    pg.sql(f"""BEGIN;
CREATE TABLE IF NOT EXISTS geo.ruian_adm (
  kod_adm bigint PRIMARY KEY, kod_obce int NOT NULL, nazev_obce text, kod_casti_obce int,
  nazev_casti_obce text, kod_ulice int, nazev_ulice text, typ_so text, cislo_domovni int,
  cislo_orientacni int, znak_co text, psc int, plati_od date, geom geometry(Point, 5514));
TRUNCATE geo.ruian_adm;
INSERT INTO geo.ruian_adm SELECT kod_adm::bigint, kod_obce::int, nazev_obce, nullif(kod_casti_obce,'')::int,
  nazev_casti_obce, nullif(kod_ulice,'')::int, nullif(nazev_ulice,''), typ_so, nullif(cislo_domovni,'')::int,
  nullif(cislo_orientacni,'')::int, nullif(znak_co,''), nullif(psc,'')::int, left(plati_od,10)::date,
  CASE WHEN y <> '' THEN ST_SetSRID(ST_MakePoint(-y::float8, -x::float8), 5514) END
FROM geo._adm_load;
CREATE INDEX IF NOT EXISTS ruian_adm_geom ON geo.ruian_adm USING gist (geom);
DROP TABLE geo._adm_load;
INSERT INTO geo.load_log(layer, files, rows, sig) SELECT 'ruian_adm', 1, count(*), '{sig}' FROM geo.ruian_adm;
COMMIT;""")
    return len(body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regions", required=True, help="VÚSC kraj codes, comma-separated (35 = Jihočeský)")
    ap.add_argument("--cache-dir", required=True, type=Path)
    ap.add_argument("--container", default="infra-postgresql-1")
    ap.add_argument("--db", default="geo")
    ap.add_argument("--layers", default="adm,cp,bu")
    ap.add_argument("--max-units", type=int, default=0, help="smoke runs: first N KÚ/obce only")
    a = ap.parse_args()
    regions = {r.strip() for r in a.regions.split(",") if r.strip()}
    layers = set(a.layers.split(","))
    cache = a.cache_dir.expanduser()
    state = geo_db_state(a.container, a.db)
    if state == "absent":
        print(f"idle: no {a.db} database in {a.container} (install_postgis off)")
        return 0
    if state == "down":
        raise SystemExit(f"{a.container} exists but is not answering — not loading")
    pg = Pg("docker", a.container, a.db)
    pg.sql("CREATE SCHEMA IF NOT EXISTS geo; CREATE TABLE IF NOT EXISTS geo.load_log ("
           "loaded_at timestamptz NOT NULL DEFAULT now(), layer text NOT NULL, files int, rows bigint, sig text);")

    fetch(KU_CATALOG, cache / "ku-catalog.zip")
    with zipfile.ZipFile(cache / "ku-catalog.zip") as z:
        ku, obce = region_units(z.read(z.namelist()[0]).decode("cp1250"), regions)
    if not ku:
        raise SystemExit(f"no KÚ found for regions {sorted(regions)} — wrong VÚSC code?")
    if a.max_units:
        ku, obce = ku[:a.max_units], obce[:a.max_units]
    print(f"regions {sorted(regions)}: {len(ku)} KÚ, {len(obce)} obcí")
    sig = lambda codes: hashlib.sha1(",".join(codes).encode()).hexdigest()[:16]
    t0 = time.time()

    if "adm" in layers:
        for stamp in adm_candidates(datetime.date.today()):
            dest = cache / "ruian" / f"{stamp}_OB_ADR_csv.zip"
            try:
                new = fetch(ADM_URL.format(stamp), dest)
                break
            except SystemExit as e:
                if "HTTP 404" not in str(e):
                    raise
        else:
            raise SystemExit("no RÚIAN address CSV for the last two months")
        if new or not pg.current("ruian_adm", sig([dest.name] + obce)):
            print(f"ruian_adm: {load_adm(pg, dest, set(obce), sig([dest.name] + obce))} rows from {dest.name}")
        else:
            print(f"ruian_adm: {dest.name} unchanged, kept")

    # Some INSPIRE buildings carry only a point (no footprint), so BU is GEOMETRY.
    gml = {
        "cp": ("inspire_cp", CP_URL, ku, "MULTIPOLYGON",
               "local_id text, ku_kod int, parcel_no text, ncr text, area_m2 bigint, geom geometry(MultiPolygon, 5514)",
               "SELECT localId AS local_id, label AS parcel_no, nationalCadastralReference AS ncr, "
               "areaValue AS area_m2 FROM CadastralParcel",
               "SELECT local_id, split_part(ncr, '-', 1)::int, parcel_no, ncr, area_m2, geom FROM {staging}",
               "CREATE INDEX IF NOT EXISTS inspire_cp_parcel ON geo.inspire_cp (ku_kod, parcel_no);"),
        "bu": ("inspire_bu", BU_URL, obce, "GEOMETRY",
               "kod_so bigint, local_id text, units int, floors text, geom geometry(Geometry, 5514)",
               "SELECT localId AS local_id, numberOfBuildingUnits AS units, "
               "numberOfFloorsAboveGround AS floors FROM Building",
               "SELECT substr(local_id, 4)::bigint, local_id, units, floors, geom FROM {staging}",
               "CREATE INDEX IF NOT EXISTS inspire_bu_kod_so ON geo.inspire_bu (kod_so);"),
    }
    for key, (table, url, codes, nlt, ddl, select, finish, index) in gml.items():
        if key not in layers:
            continue
        files = {url.format(c): cache / key / f"{c}.zip" for c in codes}
        new = fetch_all(files)
        if new or not pg.current(table, sig(codes)):
            skipped = load_gml(pg, sorted(files.values()), table, ddl, select, finish, nlt, sig(codes), index)
            print(f"{table}: {new} new of {len(files)} files, reloaded"
                  + (f"; {len(skipped)} without the layer, skipped: {' '.join(skipped)}" if skipped else ""))
        else:
            print(f"{table}: {len(files)} files unchanged, kept")
    print(f"done in {time.time() - t0:.0f}s — row counts: tools/geo-status.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
