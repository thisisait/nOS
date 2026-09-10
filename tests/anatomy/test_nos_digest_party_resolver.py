"""party-resolver core: IČO normalize+checksum, org-name normalize, deterministic
slug, and the 3-outcome resolve_party (person/org split, synthetic-range refusal,
trust-gated auto-mint). The identity trust boundary — see the party-resolver row
for the three-review synthesis these pin.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
MOD = REPO / "files" / "anatomy" / "module_utils" / "nos_digest.py"


def _nd():
    spec = importlib.util.spec_from_file_location("nos_digest", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ND = _nd()

VALID_ICO = "12345679"      # mod-11 valid (checked by hand: s=112, r=2, c=9)
BAD_CHECKSUM = "12345670"   # same digits, wrong check digit
FIXTURE_ICO = "00000112"    # synthetic reserved range, checksum-invalid by design


def test_ico_zero_pads_and_checksums():
    assert ND.normalize_ico("112")["value"] == "00000112"      # Excel-stripped → padded
    assert ND.normalize_ico(VALID_ICO)["checksum_ok"] is True
    assert ND.normalize_ico(BAD_CHECKSUM)["checksum_ok"] is False
    assert ND.normalize_ico(FIXTURE_ICO)["synthetic"] is True
    assert ND.normalize_ico(VALID_ICO)["synthetic"] is False
    for junk in ("", "abc", "123456789", None):
        assert ND.normalize_ico(junk) is None


def test_org_name_folds_diacritics_and_strips_suffix():
    assert ND.normalize_org_name("Pekárna Novák s.r.o.") == "pekarna novak"
    assert ND.normalize_org_name("Kolben IT a.s.") == "kolben it"


def test_slug_is_deterministic():
    assert ND.org_slug("00000112") == "party-ico-00000112"
    # same input → same slug is the whole backstop
    assert ND.org_slug(VALID_ICO) == ND.org_slug(VALID_ICO)


def test_person_is_never_auto_resolved():
    r = ND.resolve_party({"kind": "person", "name": "Petr Svoboda", "ico": VALID_ICO},
                         {"by_key": {}, "by_name": {}})
    assert r["status"] == "review" and r["slug"] is None


def test_valid_ico_resolves_to_existing():
    idx = {"by_key": {("ICO", VALID_ICO): "party-ico-" + VALID_ICO}, "by_name": {}}
    r = ND.resolve_party({"kind": "org", "ico": VALID_ICO}, idx)
    assert r["status"] == "resolved" and r["matched_by"] == "ico"
    assert r["slug"] == "party-ico-" + VALID_ICO


def test_new_valid_ico_mints_only_for_authoritative_source():
    idx = {"by_key": {}, "by_name": {}}
    ref = {"kind": "org", "ico": VALID_ICO}
    created = ND.resolve_party(ref, idx, source_authoritative=True)
    assert created["status"] == "create" and created["slug"] == "party-ico-" + VALID_ICO
    weak = ND.resolve_party(ref, idx, source_authoritative=False)
    assert weak["status"] == "review" and weak["slug"] == "party-ico-" + VALID_ICO


def test_synthetic_ico_refused_outside_fixture_mode():
    idx = {"by_key": {("ICO", FIXTURE_ICO): "synthetic-x"}, "by_name": {}}
    assert ND.resolve_party({"kind": "org", "ico": FIXTURE_ICO}, idx)["status"] == "review"
    r = ND.resolve_party({"kind": "org", "ico": FIXTURE_ICO}, idx, fixture_mode=True)
    assert r["status"] == "resolved" and r["slug"] == "synthetic-x"


def test_bad_checksum_ico_is_not_a_key():
    # a real (non-synthetic) IČO that fails checksum must NOT match on the key path
    idx = {"by_key": {("ICO", BAD_CHECKSUM): "should-not-hit"}, "by_name": {}}
    r = ND.resolve_party({"kind": "org", "ico": BAD_CHECKSUM}, idx)
    assert r["status"] == "review" and r["slug"] is None


def test_name_fallback_resolves_unique_and_flags_ambiguous():
    idx = {"by_key": {}, "by_name": {"pekarna novak": ["party-a"], "acme": ["p1", "p2"]}}
    uniq = ND.resolve_party({"kind": "org", "legal_name": "Pekárna Novák s.r.o."}, idx)
    assert uniq["status"] == "resolved" and uniq["slug"] == "party-a"
    amb = ND.resolve_party({"kind": "org", "name": "ACME"}, idx)
    assert amb["status"] == "review" and amb["candidates"] == ["p1", "p2"]
