#!/usr/bin/env python3
"""Approve / reject / onboard a pending-invoice-verify row.

The intake job WRITES the queue; VisionImporter READS resolution=approved on
the next digest-import-vision --absorb. This CLI is the missing producer
(verify-writeback-needs-writer). onboard mints party + IČO tax-identity
(party-onboarding-from-invoice) then approves, so an unknown vendor can complete.

  tools/invoice-verify.py approve piv-foo-extract-json
  tools/invoice-verify.py reject  piv-foo-extract-json
  tools/invoice-verify.py onboard piv-foo-extract-json [--side seller|buyer]

Batch semantics: this POSTs KEAP; it does not absorb. HMAC table.upsert to Bone
when WING_EVENTS_HMAC_SECRET is set (same type as the face BFF). Unset → KEAP
write still happens; audit is best-effort.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import digest_absorb  # noqa: E402
from keap_api import proxy_header  # noqa: E402
import nos_digest  # noqa: E402

TABLE = "pending-invoice-verify"


def field_value(fields: dict, key: str):
    v = (fields or {}).get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def coerce_fields(fields):
    """KEAP json columns sometimes round-trip as a string."""
    if fields is None:
        return {}
    if isinstance(fields, str):
        return json.loads(fields) if fields.strip() else {}
    if isinstance(fields, dict):
        return fields
    raise ValueError(f"fields must be a dict or JSON string, got {type(fields).__name__}")


def decision_values(row: dict, resolution: str, actor: str, when: str | int) -> dict:
    if resolution not in ("approved", "rejected"):
        raise ValueError(f"resolution must be approved|rejected, got {resolution!r}")
    out = dict(row)
    out["resolution"] = resolution
    out["resolved_by"] = actor
    out["resolved_at"] = _epoch_seconds(when)
    return out


def _epoch_seconds(when: str | int) -> int:
    """KEAP date columns on this table want epoch seconds, not ISO dates."""
    if isinstance(when, (int, float)):
        return int(when)
    d = dt.date.fromisoformat(str(when)[:10])
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def party_from_fields(fields: dict, side: str = "seller") -> tuple[dict, dict]:
    """Operator-confirmed counterparty from a held sidecar's dotted fields."""
    fields = coerce_fields(fields)
    ico_raw = field_value(fields, f"{side}.ico")
    name = field_value(fields, f"{side}.name") or f"unknown {side}"
    norm = nos_digest.normalize_ico(str(ico_raw) if ico_raw is not None else "")
    if not norm:
        raise ValueError(f"{side}.ico {ico_raw!r} is not digits — refuse to mint")
    if norm.get("synthetic"):
        raise ValueError(f"{side}.ico {norm['value']} is in the synthetic fixture range — refuse to mint")
    if not norm.get("checksum_ok"):
        raise ValueError(f"{side}.ico {ico_raw!r} fails the IČO checksum — refuse to mint")
    ico = norm["value"]
    slug = nos_digest.org_slug(ico)
    party = {"slug": slug, "legal_name": str(name), "party_kind": "org",
             "country": "CZ", "role": "counterparty"}
    tax = {"slug": f"pti-ico-{ico}", "party": slug, "scheme": "ICO", "value": ico}
    return party, tax


def bone_events_url() -> str:
    u = (os.environ.get("NOS_BONE_EVENTS_URL")
         or os.environ.get("BONE_EVENTS_URL")
         or "http://127.0.0.1:8099").rstrip("/")
    return u if u.endswith("/api/v1/events") else u + "/api/v1/events"


def hmac_headers(secret: str, body: bytes, ts: str | None = None) -> dict:
    ts = ts or str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Wing-Timestamp": ts, "X-Wing-Signature": sig, "Content-Type": "application/json"}


def audit_payload(slug: str, resolution: str, actor: str) -> dict:
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": "table.upsert",
        "run_id": f"invoice-verify-{slug}",
        "source": "invoice-verify",
        "actor_id": f"operator:{actor}",
        "actor_action_id": slug,
        "result": {"slug": slug, "table": TABLE, "resolution": resolution},
    }


def hmac_secret() -> str:
    """Env first, then ~/.nos/secrets.yml (CLI has no launchd env)."""
    env = os.environ.get("WING_EVENTS_HMAC_SECRET", "").strip()
    if env:
        return env
    secrets = pathlib.Path.home() / ".nos" / "secrets.yml"
    if not secrets.is_file():
        return ""
    for line in secrets.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("wing_events_hmac_secret:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


def emit_audit(slug: str, resolution: str, actor: str) -> bool:
    secret = hmac_secret()
    if not secret:
        print("WARN: WING_EVENTS_HMAC_SECRET unset — KEAP write has no Bone audit", file=sys.stderr)
        return False
    body = json.dumps(audit_payload(slug, resolution, actor), separators=(",", ":"), sort_keys=True).encode()
    req = urllib.request.Request(bone_events_url(), data=body, headers=hmac_headers(secret, body), method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except (urllib.error.URLError, OSError, urllib.error.HTTPError) as exc:
        print(f"WARN: Bone audit missed ({exc})", file=sys.stderr)
        return False


def _hdr() -> dict:
    return {"Authorization": f"Bearer {digest_absorb.rw_token()}", **proxy_header()}


def _row(slug: str) -> dict:
    for r in digest_absorb.read_rows(TABLE):
        if r.get("slug") == slug:
            return r
    raise SystemExit(f"no pending-invoice-verify row {slug!r}")


def _write(row: dict) -> None:
    body = {k: v for k, v in row.items() if not str(k).startswith("__")}
    digest_absorb._post_row(TABLE, body, _hdr())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["approve", "reject", "onboard"])
    p.add_argument("slug")
    p.add_argument("--side", choices=["seller", "buyer"], default="seller")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    actor = getpass.getuser()
    when = dt.date.today().isoformat()
    row = _row(args.slug)

    if args.action == "onboard":
        party, tax = party_from_fields(row.get("fields") or {}, args.side)
        if args.dry_run:
            json.dump({"party": party, "tax": tax, "then": "approved"}, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        digest_absorb._post_row("party", party, _hdr())
        digest_absorb._post_row("party-tax-identity", tax, _hdr())
        print(f"+ party {party['slug']} ico={tax['value']}", file=sys.stderr)

    resolution = "rejected" if args.action == "reject" else "approved"
    values = decision_values(row, resolution, actor, when)
    if args.dry_run:
        json.dump(values, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    _write(values)
    emit_audit(args.slug, resolution, actor)
    print(f"{args.slug} → {resolution} (next digest-import-vision --absorb honors it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
