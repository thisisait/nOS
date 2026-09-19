#!/usr/bin/env python3
"""digest-import-isdoc — the THIRD digest importer (ISDOC e-invoices → invoice facet).

Proves a third source on the same spine and the seller/buyer DUAL party resolve:
each invoice header attributes to TWO parties, both resolved against the live spine
(never minted). Walks a directory of *.isdoc.xml, reads the invoice header + both
PartyIdentification IČOs, and emits {party: [stubs], invoice: [headers]} through
run_importer. Lines are deferred — the header + dual resolve is the money axis.

  tools/digest-import-isdoc.py state/fixtures/isdoc-fixture --fixture-mode
  tools/digest-import-isdoc.py state/fixtures/isdoc-fixture --fixture-mode --absorb

An invoice whose seller OR buyer does not resolve to a KNOWN party is skipped for
review — the importer never mints a counterparty. DRY by default. Exit 0 · 1 gate
refused · 2 KEAP unreadable.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import sys
import urllib.error
import xml.etree.ElementTree as ET

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
from digest_absorb import absorb, build_party_index  # noqa: E402
import nos_digest  # noqa: E402

TABLES_DIR = REPO / "state" / "keap-tables"


def _slug(*parts: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", "-".join(str(p) for p in parts if p).lower()).strip("-")
    return re.sub(r"-+", "-", s)


def _epoch(iso_date: str) -> int | None:
    """ISDOC dates are ISO YYYY-MM-DD; the estate's date columns hold epoch seconds
    (kolben/party fixtures). Convert so a re-import is byte-stable."""
    try:
        return int(_dt.datetime.strptime(iso_date.strip(), "%Y-%m-%d")
                   .replace(tzinfo=_dt.timezone.utc).timestamp())
    except (ValueError, AttributeError):
        return None


def _local(el, name):
    """First descendant whose tag localname == name (namespace-agnostic — real
    ISDOC carries the http://isdoc.cz/namespace/... ns, the fixture may not)."""
    for e in el.iter():
        if e.tag.split("}")[-1] == name:
            return e
    return None


def _localtext(el, name):
    e = _local(el, name)
    return (e.text or "").strip() if e is not None and e.text else None


def _party(subtree):
    """{ico, name} from an AccountingSupplierParty/CustomerParty subtree."""
    if subtree is None:
        return {"ico": None, "name": None}
    pid = _local(subtree, "PartyIdentification")
    return {"ico": _localtext(pid, "ID") if pid is not None else None,
            "name": _localtext(subtree, "Name")}


def _num(text) -> float | None:
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return None


def _tax_subtotals(doc) -> list[dict]:
    """multi-rate-vat unit: real Czech invoices mix VAT rates, so TaxTotal can
    carry MULTIPLE TaxSubTotal children. `_localtext(doc, "TaxableAmount")`
    (the single-rate reading this replaces) walks the whole document and
    returns only the FIRST match — silently mis-sums a two-rate invoice.
    Returns one {rate?, base, vat} per TaxSubTotal, base/vat rounded 2dp
    (money path)."""
    out = []
    for sub in doc.iter():
        if sub.tag.split("}")[-1] != "TaxSubTotal":
            continue
        base, vat = _num(_localtext(sub, "TaxableAmount")), _num(_localtext(sub, "TaxAmount"))
        if base is None and vat is None:
            continue
        entry = {"base": base or 0.0, "vat": vat or 0.0}
        rate = _num(_localtext(sub, "VATRate"))
        if rate is not None:
            entry["rate"] = rate
        out.append(entry)
    return out


class IsdocImporter:
    """ISDOC e-invoice XML → the invoice facet. Format knowledge only."""

    name = "isdoc"
    version = "0.1.0"

    def __init__(self, source_id: str, party_index: dict, *, fixture_mode: bool = False,
                 book_owner_ico: str | None = None):
        self.source_id = source_id
        self.party_index = party_index
        self.fixture_mode = fixture_mode
        self.skipped: list[str] = []
        self.party_reviews: list[dict] = []
        # book_owner (invoice-vision-intake unit): a DATA-ORGANIZATION attribute —
        # which client's book this import run is FOR — resolved by IČO like any
        # other party, never minted. NOT a tenant/RBAC column (model C: isolation
        # stays with the analytical accounts, docs/idea comment in the wf def).
        self.book_owner_ico = book_owner_ico
        self.book_owner_slug: str | None = None

    def parse(self, root) -> list[dict]:
        root = pathlib.Path(root)
        out = []
        for f in sorted(root.glob("*.isdoc.xml")):
            try:
                doc = ET.parse(f).getroot()
            except ET.ParseError as exc:
                self.skipped.append(f"{f.name}: unparsable XML ({exc})")
                continue
            inv_id = _localtext(doc, "ID")   # the invoice ID is the first ID in document order
            if not inv_id:
                self.skipped.append(f"{f.name}: no invoice ID")
                continue
            subtotals = _tax_subtotals(doc)
            out.append({
                "file": f.name, "id": inv_id,
                "issue": _localtext(doc, "IssueDate"),
                "due": _localtext(doc, "DueDate"),
                "currency": _localtext(doc, "LocalCurrencyCode"),
                "payable": _localtext(doc, "PayableAmount"),
                # TaxTotal breakdown, SUMMED across every TaxSubTotal (multi-rate-vat
                # unit) — net/vat are the sums; vat_breakdown carries the per-rate rows.
                "net": round(sum(s["base"] for s in subtotals), 2) if subtotals else None,
                "vat": round(sum(s["vat"] for s in subtotals), 2) if subtotals else None,
                "vat_breakdown": subtotals,
                "seller": _party(_local(doc, "AccountingSupplierParty")),
                "buyer": _party(_local(doc, "AccountingCustomerParty")),
            })
        return out

    def _resolve(self, ref_party, role, rec):
        ref = {"kind": "org", "ico": ref_party.get("ico"), "legal_name": ref_party.get("name")}
        res = nos_digest.note_party_resolve(self, ref, self.party_index,
                                            source_authoritative=False,
                                            fixture_mode=self.fixture_mode)
        if res["status"] != "resolved":
            self.skipped.append(
                f"{rec['file']}: {role} unresolved ({res['status']}: {res['reason']}) "
                "— ISDOC resolve-only, routed to review")
            return None
        return res["slug"]

    def normalize(self, records: list[dict]) -> list[dict]:
        if self.book_owner_ico and self.book_owner_slug is None:
            res = nos_digest.note_party_resolve(
                self, {"kind": "org", "ico": self.book_owner_ico}, self.party_index,
                source_authoritative=False, fixture_mode=self.fixture_mode)
            if res["status"] == "resolved":
                self.book_owner_slug = res["slug"]
            else:
                self.skipped.append(
                    f"book-owner IČO {self.book_owner_ico}: {res['status']} "
                    f"({res['reason']}) — resolve-only, routed to review; rows carry no book_owner")
        out = []
        for r in records:
            seller = self._resolve(r["seller"], "seller", r)
            buyer = self._resolve(r["buyer"], "buyer", r)
            if not (seller and buyer):
                continue
            r["seller_slug"], r["buyer_slug"] = seller, buyer
            out.append(r)
        return out

    def compose(self, records: list[dict]) -> dict:
        parties: dict[str, dict] = {}
        invoices = []
        for r in records:
            for slug, ref in ((r["seller_slug"], r["seller"]), (r["buyer_slug"], r["buyer"])):
                parties.setdefault(slug, {"slug": slug, "legal_name": ref.get("name") or slug,
                                          "party_kind": "org", "country": "CZ"})
            row = {"slug": _slug("invoice", r["seller_slug"], r["id"]),
                   "document_number": r["id"], "seller": r["seller_slug"], "buyer": r["buyer_slug"],
                   "currency": r["currency"] or "CZK"}
            if r["issue"] and _epoch(r["issue"]) is not None:
                row["issue_date"] = _epoch(r["issue"])
            if r["due"] and _epoch(r["due"]) is not None:
                row["due_date"] = _epoch(r["due"])
            if r.get("payable"):
                try:
                    row["payable_amount"] = round(float(r["payable"]), 2)
                except ValueError:
                    pass
            if r.get("net") is not None:
                row["net_amount"] = round(r["net"], 2)
            if r.get("vat") is not None:
                row["vat_amount"] = round(r["vat"], 2)
            if r.get("vat_breakdown"):
                row["vat_breakdown"] = r["vat_breakdown"]
            if self.book_owner_slug:
                row["book_owner"] = self.book_owner_slug
            invoices.append(row)
        return {"party": list(parties.values()), "invoice": invoices}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="a directory of *.isdoc.xml e-invoices")
    ap.add_argument("--source-id")
    ap.add_argument("--absorb", action="store_true", help="upsert into KEAP (default dry)")
    ap.add_argument("--out", help="write the gated bundle YAML here (default stdout, dry)")
    ap.add_argument("--fixture-mode", action="store_true",
                    help="resolve synthetic-range IČOs (000001xx) — for the fixture spine only")
    ap.add_argument("--book-owner-ico",
                    help="IČO of the client this import run is FOR (data-org attribute, "
                         "stamped as invoice.book_owner; resolved, never minted)")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if not root.is_absolute():
        root = REPO / root
    try:
        index = build_party_index()
    except (urllib.error.URLError, OSError) as exc:
        print(f"REFUSING: cannot build party index from KEAP ({exc})", file=sys.stderr)
        return 2

    importer = IsdocImporter(args.source_id or root.name, index, fixture_mode=args.fixture_mode,
                             book_owner_ico=args.book_owner_ico)
    bundle, errors = nos_digest.run_importer(importer, str(root), TABLES_DIR)

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
    out = args.out and (REPO / args.out if not pathlib.Path(args.out).is_absolute()
                        else pathlib.Path(args.out))
    out.write_text(text) if out else print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
