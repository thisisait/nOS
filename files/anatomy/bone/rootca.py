"""The root-CA comparison, ONE copy (row nos-root-ca-fingerprint-second-channel): Bone's
/api/v1/estate/root-ca and tools/estate-status.py axis_root_ca both call verdict(), so the face
and the reader cannot disagree on "the edge serves the CA this host signs with". Stdlib only:
estate-status loads this file by path with the system python3."""

from __future__ import annotations

import hashlib
import ssl

BEGIN = "-----BEGIN CERTIFICATE-----"


def fingerprint(pem: str) -> str | None:
    """sha256 of exactly one public certificate, colon hex; None for anything else (a key too)."""
    if pem.count(BEGIN) != 1 or "PRIVATE KEY" in pem:
        return None
    try:
        der = ssl.PEM_cert_to_DER_cert(pem.strip())
    except ValueError:
        return None
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


def verdict(trusted_pem: str, served_body: str) -> dict:
    """{trusted, served, agree, why}: trusted = the CA the host signs with (mkcert rootCA.pem),
    served = what the edge answers at /nos-root-ca.crt. `why` names the first thing wrong."""
    want, got = fingerprint(trusted_pem), fingerprint(served_body)
    if want is None:
        why = "the mkcert rootCA.pem is not exactly one public certificate"
    elif served_body.count(BEGIN) != 1:
        why = "does not serve exactly one certificate"
    elif got is None:
        why = "serves an unparseable certificate"
    elif got != want:
        why = (f"serves sha256 {got[:23]}…, the mkcert CA is {want[:23]}… "
               "(a stale copy in shared-certs, or another host's CA)")
    else:
        why = ""
    return {"trusted": want, "served": got, "agree": bool(want) and got == want, "why": why}
