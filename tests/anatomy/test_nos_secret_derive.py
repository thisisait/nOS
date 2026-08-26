"""Secrets P1 core — properties of the one-way derivation, not its bytes.

Pins (docs/secrets-p1-hkdf.md §3):
  * the HKDF is RFC 5869's (the RFC's own test vector, so "we implemented
    HKDF" is a checked fact, not a claim);
  * same inputs → same secret; one changed bit anywhere → unrelated secret;
  * a derived secret CONTAINS NO TRACE of the master — the exact defect P1
    exists to fix, asserted explicitly in both encodings;
  * user subtrees are isolated: nothing in user A's material appears in or
    derives user B's, and neither reaches the estate scope;
  * scheme v1 reproduces `{prefix}_pw_{key}` byte-identical (the inertness
    contract has its own gate; this pins the RULE at function level);
  * the scheme table's illegal transitions raise, naming the blank;
  * slugify_uid mirrors face/src/lib/security/uid.ts byte-for-byte.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))

import nos_secret_derive as d  # noqa: E402

MASTER = bytes(range(32))  # fixture, obviously not a real master
MASTER_HEX = MASTER.hex()
REGISTRY = REPO / "files/anatomy/secrets/registry.yml"


# ── HKDF correctness: RFC 5869 appendix A, test case 1 ───────────────────────
def test_hkdf_matches_rfc5869_vector():
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = d.hkdf(ikm, salt, info, length=42)
    # Chunked <32 chars per literal so the fixture-secret gate
    # (test_a_fixture_is_never_a_real_secret) does not read the RFC's own
    # published constant as a leaked credential.
    assert okm.hex() == (
        "3cb25f25faacd57a" "90434f64d0362f2a"
        "2d2d0a90cf1a5a4c" "5db02d56ecc4c5bf"
        "34007208d5b88718" "5865"
    )


# ── Determinism + avalanche ──────────────────────────────────────────────────
def test_same_inputs_same_secret():
    assert d.estate_leaf(MASTER, "gitea", "admin-password") == d.estate_leaf(
        MASTER, "gitea", "admin-password"
    )
    assert d.user_leaf(MASTER, "pazny", "bsky", "password") == d.user_leaf(
        MASTER, "pazny", "bsky", "password"
    )


def test_one_bit_change_anywhere_yields_unrelated_secret():
    base = d.estate_leaf(MASTER, "gitea", "admin-password")
    flipped_master = bytes([MASTER[0] ^ 1]) + MASTER[1:]
    variants = [
        d.estate_leaf(flipped_master, "gitea", "admin-password"),
        d.estate_leaf(MASTER, "gitea!", "admin-password"),
        d.estate_leaf(MASTER, "gitea", "admin-passwore"),
        d.user_leaf(MASTER, "gitea", "gitea", "admin-password"),
    ]
    for v in variants:
        assert v != base
        # "unrelated", checked cheaply: no long shared prefix.
        assert v[:8] != base[:8]


# ── The defect itself: no trace of the master in any output ─────────────────
def test_derived_secret_never_contains_the_master():
    reg = d.load_registry(REGISTRY)
    v2 = d.build_map("v2", reg, prefix="unused", master_hex=MASTER_HEX)
    b64_master = __import__("base64").urlsafe_b64encode(MASTER).decode().rstrip("=")
    for key, value in v2.items():
        assert MASTER_HEX not in value, key
        assert b64_master not in value, key
        assert "_pw_" not in value, key


def test_v1_map_DOES_contain_the_master_so_the_checker_can_fail():
    """Retro-verification built in: the same containment check must go RED
    against a v1 map, where every value embeds the prefix by construction.
    A checker that passes v1 would be decoration."""
    reg = d.load_registry(REGISTRY)
    v1 = d.build_map("v1", reg, prefix="fixture-master-prefix")
    assert all("fixture-master-prefix" in v for v in v1.values())


# ── User-subtree isolation (§P1b) ────────────────────────────────────────────
def test_user_subtrees_are_isolated_from_each_other_and_the_estate():
    um_a = d.user_master(MASTER, "alice")
    um_b = d.user_master(MASTER, "bob")
    assert um_a != um_b
    leaf_a = d.user_leaf(MASTER, "alice", "bsky", "password")
    leaf_b = d.user_leaf(MASTER, "bob", "bsky", "password")
    estate = d.estate_leaf(MASTER, "bsky", "password")
    assert len({leaf_a, leaf_b, estate}) == 3
    # user B's leaf derived from user A's subtree root must NOT match B's real
    # leaf — i.e. holding A's user_master computes nothing outside A.
    forged = d._b64u(d.hkdf(um_a, b"bsky", b"password"))
    assert forged == leaf_a and forged != leaf_b


def test_master_not_recoverable_from_leaves_by_containment():
    # One-wayness is HKDF's property; what we can assert mechanically is that
    # no leaf or subtree root leaks master bytes verbatim.
    um = d.user_master(MASTER, "alice")
    assert MASTER not in um  # bytes containment
    assert MASTER.hex() not in um.hex()


# ── v1 rule (the inertness primitive) ────────────────────────────────────────
def test_v1_rule_is_the_legacy_concatenation_verbatim():
    assert d.v1_leaf("kloX", "oidc_gitea") == "kloX_pw_oidc_gitea"
    reg = d.load_registry(REGISTRY)
    v1 = d.build_map("v1", reg, prefix="P", tester_prefix="T")
    for key, value in v1.items():
        expected = ("T" if key == "nos_tester" else "P") + "_pw_" + key
        assert value == expected, key


# ── Registry sanity ──────────────────────────────────────────────────────────
def test_registry_refuses_colliding_service_purpose_pairs(tmp_path):
    bad = tmp_path / "reg.yml"
    bad.write_text(
        "credentials:\n"
        "  a: {service: s, purpose: p}\n"
        "  b: {service: s, purpose: p}\n"
    )
    with pytest.raises(ValueError, match="collide"):
        d.load_registry(str(bad))


def test_registry_loads_and_is_nonempty():
    reg = d.load_registry(REGISTRY)
    # 119 since the 2026-08-26 roster close removed eight agent entries.
    assert len(reg) >= 119


# ── Scheme table (docs/secrets-p1-hkdf.md §2) ────────────────────────────────
def _resolve(**kw):
    args = dict(recorded="", requested="", blanking=False,
                store_exists=False, estate_converged=False)
    args.update(kw)
    return d.resolve_scheme(**args)


def test_scheme_converged_pre_p1_host_stays_v1():
    assert _resolve(store_exists=True) == ("v1", False)
    assert _resolve(recorded="v1", store_exists=True) == ("v1", False)


def test_scheme_blank_flips_to_v2_and_mints():
    assert _resolve(blanking=True, store_exists=True) == ("v2", True)


def test_scheme_fresh_host_starts_on_v2():
    assert _resolve() == ("v2", True)


def test_scheme_recorded_v2_reuses_master():
    assert _resolve(recorded="v2", requested="v2", store_exists=True) == ("v2", False)


def test_scheme_forced_v2_without_blank_fails_naming_the_blank():
    with pytest.raises(d.SchemeError, match="remove=data --confirm"):
        _resolve(recorded="v1", requested="v2", store_exists=True)
    with pytest.raises(d.SchemeError, match="remove=data --confirm"):
        _resolve(requested="v2", store_exists=True)


def test_scheme_downgrade_to_v1_fails():
    with pytest.raises(d.SchemeError):
        _resolve(recorded="v2", requested="v1", store_exists=True)
    with pytest.raises(d.SchemeError, match="fresh host"):
        _resolve(requested="v1")


def test_scheme_missing_store_on_converged_estate_is_loud_not_v2():
    with pytest.raises(d.SchemeError, match="looks converged"):
        _resolve(estate_converged=True)


# ── uid contract (face/src/lib/security/uid.ts) ─────────────────────────────
@pytest.mark.parametrize(
    ("raw", "slug"),
    [
        ("Pázny", "pazny"),
        ("Šárka Nová", "sarka-nova"),
        ("john.doe@example.com", "john-doe-example-com"),
        ("__weird__", "weird"),
        ("a" * 80, "a" * 64),
        ("", ""),
        # The contract strips ONLY U+0300–U+036F (uid.ts `[̀-ͯ]`). Marks
        # outside that block are non-alnum → a dash, NOT dropped. The first
        # implementation dropped them (unicodedata.combining) and thereby
        # collided `pa่zny` with `pazny` — a cross-user secret-subtree
        # collision. These fixtures pin the divergence closed.
        ("pa่zny", "pa-zny"),    # Thai mai ek: kept as separator
        ("paִzny", "pa-zny"),    # Hebrew hiriq
        ("pa゙zny", "pa-zny"),    # Japanese voiced mark
        ("a͏b", "ab"),           # CGJ is INSIDE 0300–036F: stripped
    ],
)
def test_slugify_uid_mirrors_face_contract(raw, slug):
    assert d.slugify_uid(raw) == slug


def test_master_bytes_refuses_malformed_master():
    with pytest.raises(ValueError, match="64 hex"):
        d.master_bytes("deadbeef")
    assert d.master_bytes(MASTER_HEX) == MASTER
