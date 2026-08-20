# -*- coding: utf-8 -*-
"""Secrets P1 — the one-way derivation core (docs/secrets-p1-hkdf.md).

`{prefix}_pw_{service}` is concatenation, not derivation: the rendered
credential contains the master in clear, so one leaked value yields the estate
(REM-144). This module replaces it with HKDF-SHA256 so a leaked credential is
32 random bytes that reveal nothing about the master or any sibling.

Pure functions, stdlib only (hashlib/hmac/base64/unicodedata) — no new
dependency for a mechanism the whole estate boots through. Consumed by
`files/anatomy/library/nos_secret_map.py` (the Ansible module),
`tools/nos-secret.py` (the operator reader) and the anatomy gates, so the rule
exists exactly once.

Scheme discipline (docs/secrets-p1-hkdf.md §2):
  v1 = legacy concatenation, byte-identical — the INERT mode every
       already-converged host stays on until a confirmed blank.
  v2 = HKDF leaves of a random 32-byte master that is never rendered.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets as _secrets
import unicodedata

_HASH = hashlib.sha256
_HASHLEN = 32
#: Output length of every leaf, bytes. 32 → 43 base64url chars.
LEAF_LEN = 32

SCHEME_V1 = "v1"
SCHEME_V2 = "v2"
SCHEMES = (SCHEME_V1, SCHEME_V2)

#: Domain-separation prefixes (docs/secrets-p1-hkdf.md §3). Changing either
#: changes every derived credential on every v2 host — they are contract.
_ESTATE_SALT = b"nos/estate|"
_USER_SALT = b"nos/user|"
_USER_ROOT_INFO = b"user-root"


# ── HKDF (RFC 5869), pinned by the RFC's own test vector in the unit tests ──
def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt or b"\x00" * _HASHLEN, ikm, _HASH).digest()


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), _HASH).digest()
        out += block
        counter += 1
    return out[:length]


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int = LEAF_LEN) -> bytes:
    return _hkdf_expand(_hkdf_extract(salt, ikm), info, length)


def _b64u(raw: bytes) -> str:
    """URL-safe base64, unpadded — env-var-, URL- and YAML-safe (43 chars)."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# ── The master ───────────────────────────────────────────────────────────────
def mint_master() -> str:
    """32 random bytes, hex-encoded for the persisted store."""
    return _secrets.token_hex(32)


def master_bytes(master_hex: str) -> bytes:
    """Decode + validate the stored master. Raises ValueError on malformation
    rather than deriving from garbage — a truncated master must be loud."""
    m = (master_hex or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", m):
        raise ValueError(
            "nos_secret_master is not 64 hex chars — the persisted store is "
            "corrupt or truncated; refusing to derive from it"
        )
    return bytes.fromhex(m)


# ── Leaves ───────────────────────────────────────────────────────────────────
def estate_leaf(master: bytes, service: str, purpose: str) -> str:
    return _b64u(hkdf(master, _ESTATE_SALT + service.encode("utf-8"),
                      purpose.encode("utf-8")))


def user_master(master: bytes, uid: str) -> bytes:
    """The per-user subtree root (§P1b). A container holding this can derive
    that user's leaves and NOTHING else — not the master, not a sibling."""
    return hkdf(master, _USER_SALT + uid.encode("utf-8"), _USER_ROOT_INFO)


def user_leaf(master: bytes, uid: str, service: str, purpose: str) -> str:
    return _b64u(hkdf(user_master(master, uid), service.encode("utf-8"),
                      purpose.encode("utf-8")))


def v1_leaf(prefix: str, key: str) -> str:
    """The legacy rule, verbatim. Byte-identity with this IS the inertness
    contract — see test_secret_scheme_inert_until_blank.py."""
    return "%s_pw_%s" % (prefix, key)


# ── uid — MUST mirror face/src/lib/security/uid.ts slugifyUid byte-for-byte ──
#: uid.ts strips EXACTLY the Combining Diacritical Marks block (U+0300–U+036F)
#: — `.replace(/[̀-ͯ]/g, '')` — NOT everything Unicode calls combining. The
#: first cut here used `unicodedata.combining()` and diverged on 522 BMP code
#: points (Thai/Hebrew/Arabic/Kana marks, and U+034F CGJ the other way), which
#: would have salted a user's secret subtree on a DIFFERENT uid than the one
#: that owns their file tree and KEAP rows — and collided e.g. `pa่zny`
#: with `pazny` (adversarial review, reproduced). The regex below is the
#: contract; `files/anatomy/scripts/keap_selfmodel_gen.py` carries the same one.
_COMBINING_0300_036F = re.compile("[̀-ͯ]")


def slugify_uid(value: str) -> str:
    """NFKD → strip U+0300–U+036F → lowercase → non-[a-z0-9] runs → '-' →
    trim dashes → cap 64 → re-trim. `Pázny` → `pazny`. Salting user subtrees
    on anything less stable orphans every user secret on a blank (S-0)."""
    s = unicodedata.normalize("NFKD", value or "")
    s = _COMBINING_0300_036F.sub("", s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")[:64].rstrip("-")
    return s


# ── Registry + map ───────────────────────────────────────────────────────────
def load_registry(path):
    """The committed key → (service, purpose) table. ONE file, consumed by the
    module, the gates and the reader tool — no second allow-list to drift."""
    import yaml  # deferred: the loader preflight guarantees it on the host

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    rows = data.get("credentials")
    if not isinstance(rows, dict) or not rows:
        raise ValueError("secret registry %s has no `credentials:` map" % path)
    seen_pairs = {}
    for key, row in rows.items():
        if not re.fullmatch(r"[a-z0-9_]+", key):
            raise ValueError("registry key %r is not [a-z0-9_]+" % key)
        if not isinstance(row, dict) or not row.get("service") or not row.get("purpose"):
            raise ValueError("registry key %r lacks service/purpose" % key)
        pair = (row["service"], row["purpose"])
        if pair in seen_pairs:
            raise ValueError(
                "registry keys %r and %r share (service, purpose)=%r — their "
                "derived values would collide" % (seen_pairs[pair], key, pair)
            )
        seen_pairs[pair] = key
    return rows


def build_map(scheme, registry, prefix, tester_prefix="", master_hex=""):
    """The whole derived map, {key: value}, for the resolved scheme."""
    if scheme == SCHEME_V1:
        out = {}
        for key in registry:
            base = tester_prefix if (key == "nos_tester" and tester_prefix) else prefix
            out[key] = v1_leaf(base, key)
        return out
    if scheme == SCHEME_V2:
        master = master_bytes(master_hex)
        return {
            key: estate_leaf(master, row["service"], row["purpose"])
            for key, row in registry.items()
        }
    raise ValueError("unknown secret scheme %r" % scheme)


# ── Scheme resolution (docs/secrets-p1-hkdf.md §2, the table verbatim) ───────
class SchemeError(ValueError):
    """A transition that must fail LOUDLY rather than half-apply."""


_BLANK_HINT = (
    "The only supported path to scheme v2 on an existing estate is a confirmed "
    "blank: `nos --remove=data --confirm` (see docs/secrets-p1-hkdf.md §2)."
)


def resolve_scheme(recorded, requested, blanking, store_exists, estate_converged):
    """Returns (scheme, mint_master: bool). Raises SchemeError on the illegal
    transitions. `recorded` is what ~/.nos/secrets.yml holds; `requested` is
    whatever the play passed (== recorded on a normal run)."""
    recorded = (recorded or "").strip()
    requested = (requested or "").strip()
    for name, val in (("recorded", recorded), ("requested", requested)):
        if val and val not in SCHEMES:
            raise SchemeError("%s secret scheme %r is not one of %s" % (name, val, SCHEMES))

    if blanking:
        # A confirmed removal is the sanctioned rotation event: new estate
        # identity, fresh master, scheme v2. Dry runs never reach this code —
        # run-mode ends the play first.
        return SCHEME_V2, True

    if requested and recorded and requested != recorded:
        raise SchemeError(
            "refusing the scheme transition %s -> %s without a blank: the live "
            "estate holds %s credentials and re-deriving them mid-flight would "
            "change every service password at once. %s"
            % (recorded, requested, recorded, _BLANK_HINT)
        )

    if recorded == SCHEME_V2:
        return SCHEME_V2, False
    if recorded == SCHEME_V1:
        return SCHEME_V1, False

    # No recorded scheme from here on.
    if requested == SCHEME_V2 and store_exists:
        raise SchemeError(
            "nos_secret_scheme=v2 was requested but ~/.nos/secrets.yml records "
            "no scheme — this is a pre-P1 converged host on implicit v1. %s"
            % _BLANK_HINT
        )
    if store_exists:
        # Every pre-P1 converged host: implicit v1. THE inertness row.
        return SCHEME_V1, False
    if estate_converged:
        raise SchemeError(
            "cannot determine the secret scheme: ~/.nos/secrets.yml is missing "
            "but the estate looks converged (stacks dir is non-empty). "
            "Re-deriving would rotate every live service password. Restore "
            "~/.nos/secrets.yml from backup, or run a confirmed blank. %s"
            % _BLANK_HINT
        )
    if requested == SCHEME_V1:
        raise SchemeError(
            "nos_secret_scheme=v1 was requested on a fresh host — v1 "
            "(prefix concatenation) exists only so pre-P1 estates stay "
            "untouched until they blank; a new estate must not re-open the "
            "REM-144 defect. Drop the override."
        )
    # Genuinely fresh host (or CI runner): start life on v2.
    return SCHEME_V2, True
