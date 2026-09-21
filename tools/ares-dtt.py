#!/usr/bin/env python3
"""ARES + ADIS → party-registry-status row payloads.

The n8n PULL template (files/anatomy/n8n/templates/nos-pull-ares-registry.json)
does the same hops in the editor. THIS file is the oracle the gate scores.
Public CZ registers only. Stdlib.

  tools/ares-dtt.py --ares-file tests/fixtures/ares-registry.json \\
      --adis-file tests/fixtures/ares-adis-unreliable.xml --ico 00000131 --party party-ico-00000131
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/"
ADIS_URL = "https://adisrws.mfcr.cz/dpr/axis2/services/rozhraniCRPDPH.rozhraniCRPDPHSOAP"


def _local(el, name: str):
    for e in el.iter():
        if e.tag.split("}")[-1] == name:
            return e
    return None


def parse_ares(raw: str) -> dict | None:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = (data.get("obchodniJmeno") or data.get("nazev") or "").strip()
    dic = (data.get("dic") or "").strip() or None
    ico = "".join(ch for ch in str(data.get("ico") or "") if ch.isdigit()).zfill(8)
    if not name and not dic and ico == "00000000":
        return None
    return {"legal_name": name, "dic": dic, "ico": ico if ico != "00000000" else None}


def parse_adis(raw: str) -> str:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return "unknown"
    status = None
    for tag in ("statusNespolehlivyPlatce", "statusNespolehlivySubjekt", "nespolehlivyPlatce"):
        el = _local(root, tag)
        if el is None:
            continue
        status = (el.get("status") or el.text or "").strip().upper()
        if status:
            break
    if status in ("ANO", "A", "YES"):
        return "unreliable"
    if status in ("NE", "N", "NO"):
        return "reliable"
    return "unknown"


def project(*, ico: str, party: str, ares: dict | None, vat: str, when: int | None = None) -> dict:
    ico8 = "".join(ch for ch in ico if ch.isdigit()).zfill(8)
    row = {
        "slug": f"reg-ico-{ico8}",
        "party": party,
        "ico": ico8,
        "ares_found": bool(ares),
        "vat_reliability": vat if vat in ("reliable", "unreliable", "not_payer", "unknown") else "unknown",
        "checked_at": when if when is not None else int(
            dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        ),
    }
    if ares and ares.get("legal_name"):
        row["legal_name_ares"] = ares["legal_name"]
    if ares and ares.get("dic"):
        row["dic"] = ares["dic"]
    if not ares:
        row["vat_reliability"] = "not_payer"
    elif not ares.get("dic") and row["vat_reliability"] == "unknown":
        row["vat_reliability"] = "not_payer"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ares-file", type=Path)
    ap.add_argument("--adis-file", type=Path)
    ap.add_argument("--ico", required=True)
    ap.add_argument("--party", required=True)
    args = ap.parse_args()
    ares = parse_ares(args.ares_file.read_text(encoding="utf-8")) if args.ares_file else None
    vat = "not_payer"
    if ares and ares.get("dic") and args.adis_file:
        vat = parse_adis(args.adis_file.read_text(encoding="utf-8"))
    row = project(ico=args.ico, party=args.party, ares=ares, vat=vat)
    json.dump(row, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
