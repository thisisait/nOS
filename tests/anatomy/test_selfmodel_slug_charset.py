"""KEAP slug charset gate — closes hidden_fees/03 (offline, fast).

The self-model producer already carries `slug_or_die`: every id segment it emits
for a KEAP anchor must match `^[a-z][a-z0-9-]*$` (first char a LETTER), or KEAP
drops the anchor SILENTLY and the node never appears in the constellation. The
guard existed but nothing exercised it, so the estate was "clean only because
nobody named a service after a number recently" (fee 03). This pins it:

  1. every service id + stack in the REAL manifest slugifies to a valid slug —
     this is fee 03's "run every emitted slug through the KEAP charset";
  2. a leading-digit id (2fauth, 3d-printer) raises loudly, not silently;
  3. the diacritic fold and the pattern itself are what we think they are.

The Cortex docs schema (docs/archive/cortex-docs-schema.md §5) routes every doc
node id through this SAME `slug_or_die`, so this gate pins docs too — there is
no second charset to drift.
"""
import importlib.util
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
GEN = ROOT / "files/anatomy/scripts/keap_selfmodel_gen.py"
MANIFEST = ROOT / "state/manifest.yml"


def _load_gen():
    spec = importlib.util.spec_from_file_location("keap_selfmodel_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _estate_segments():
    """Every id segment the slug producer emits for a KEAP anchor: service ids
    and their stacks (host-native services bucket under 'host')."""
    manifest = yaml.safe_load(MANIFEST.read_text()) or {}
    services = manifest.get("services", [])
    ids = [s["id"] for s in services]
    stacks = sorted({(s.get("stack") or "host") for s in services})
    assert ids and stacks, "manifest yielded no services — wrong path?"
    return ids, stacks


def test_every_estate_slug_is_keap_valid():
    """The whole estate passes the charset — no member relies on spelling-around
    a leading digit. If this fails, a service/stack id would drop silently."""
    gen = _load_gen()
    ids, stacks = _estate_segments()
    for segment in ids + stacks:
        slug = gen.SLUG_OVERRIDES.get(segment) or gen.slug_or_die(segment, "estate id")
        assert gen.SLUG_RE.match(slug), f"{segment!r} → {slug!r} escaped the gate"


@pytest.mark.parametrize("bad", ["2fauth", "3d-printer", "7zip", "1password"])
def test_leading_digit_dies_loudly(bad):
    """A digit-initial name must raise, not slug into a dropped anchor (fee 03)."""
    gen = _load_gen()
    with pytest.raises(SystemExit) as exc:
        gen.slug_or_die(bad, "service id")
    assert "LETTER" in str(exc.value), "the failure must name the real rule"


def test_slugify_folds_diacritics_not_splits():
    """Port of uid.ts: accents are dropped, not decomposed into a stray letter."""
    gen = _load_gen()
    assert gen.slugify("Pázny") == "pazny"
    assert gen.slugify("bluesky_pds") == "bluesky-pds"


def test_charset_pattern_is_the_keap_rule():
    """The pattern is the contract, byte-for-byte — first char a letter."""
    gen = _load_gen()
    assert gen.SLUG_RE.pattern == r"^[a-z][a-z0-9-]*$"
    assert gen.SLUG_RE.match("gitea") and not gen.SLUG_RE.match("2fauth")
