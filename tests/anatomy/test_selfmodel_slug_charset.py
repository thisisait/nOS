"""KEAP slug charset gate — closes hidden_fees/03 (offline, fast).

WHY THIS EXISTS. The upstream brand is 2FAuth. nOS ships it as `twofauth`
(`apps/twofauth.yml`), not `2fauth`, because a KEAP node id must match
`^[a-z][a-z0-9-]*$` per segment — first character a LETTER. KEAP drops a
digit-initial anchor SILENTLY (`objects.ts`); the card never appears. That
rename is the exception this gate remembers: nothing else recorded *why* the
file is not named after the brand, so the next `3d-printer` / `7zip` would
repeat the miss invisibly. Live services are not renamed; the gate fails the
next one instead.

The self-model producer already carries `slug_or_die`. This file pins both
ends of the fee:

  1. every service id + stack in the REAL manifest slugifies to a valid slug;
  2. a leading-digit id (2fauth, 3d-printer) raises loudly, not silently;
  3. no role / plugin / app slug or `taxonomy_anchor` on those trees starts
     with a digit (the twofauth workaround, enforced);
  4. the diacritic fold and the pattern itself are what we think they are.

The Cortex docs schema (docs/archive/cortex-docs-schema.md §5) routes every doc
node id through this SAME `slug_or_die`, so this gate pins docs too — there is
no second charset to drift.
"""
import importlib.util
import pathlib
import re

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


# ── source slugs (role / plugin / app / taxonomy_anchor) ─────────────────────
#
# The producer gate above cannot see a role directory `pazny.2fauth` that is
# not yet a manifest service. Fee 03 bit at the filename (`2fauth.yml` →
# `twofauth.yml`); this walk is that check.

_TAXONOMY_ANCHOR = re.compile(
    r"^[ \t]*taxonomy_anchor:[ \t]*['\"]?([^'\"#\s]+)",
    re.MULTILINE,
)


def _source_slugs(root: pathlib.Path) -> list[tuple[str, str]]:
    """Identifiers that would become KEAP node ids if they started with a digit."""
    found: list[tuple[str, str]] = []
    roles = root / "roles"
    if roles.is_dir():
        for d in roles.iterdir():
            if d.is_dir() and d.name.startswith("pazny."):
                found.append(("role", d.name[len("pazny."):]))
    plugins = root / "files/anatomy/plugins"
    if plugins.is_dir():
        for d in plugins.iterdir():
            if d.is_dir() and (d / "plugin.yml").is_file():
                found.append(("plugin", d.name))
    apps = root / "apps"
    if apps.is_dir():
        for f in apps.glob("*.yml"):
            if f.name.startswith("_"):
                continue
            found.append(("app", f.stem))
    for base in (roles, plugins, apps):
        if not base.is_dir():
            continue
        for f in base.rglob("*.yml"):
            text = f.read_text(encoding="utf-8")
            for m in _TAXONOMY_ANCHOR.finditer(text):
                found.append(("taxonomy_anchor", m.group(1)))
    return found


def _digit_initial(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(kind, slug) for kind, slug in entries if slug[:1].isdigit()]


def test_no_role_plugin_app_slug_starts_with_a_digit():
    """The twofauth spelling is the exception; a digit-initial slug is the next fee."""
    found = _source_slugs(ROOT)
    assert len(found) > 50, (
        "source-slug collector went blind — a green run on an empty walk pins nothing"
    )
    assert ("app", "twofauth") in found, (
        "apps/twofauth.yml vanished. That file IS the 2FAuth → twofauth workaround "
        "this gate exists to remember; do not rename live services, restore the stem."
    )
    bad = _digit_initial(found)
    assert not bad, (
        "digit-initial slug/taxonomy_anchor — KEAP would drop the node silently "
        f"(fee 03; see twofauth): {bad}"
    )


def test_a_fake_2fauth_slug_fails_the_gate(tmp_path):
    """Retro-red: injecting the brand slug `2fauth` must fail, as the real file does not."""
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "2fauth.yml").write_text(
        "meta:\n  name: 2fauth\ntaxonomy_anchor: 2fauth\n", encoding="utf-8"
    )
    (tmp_path / "roles" / "pazny.2fauth").mkdir(parents=True)
    plugin = tmp_path / "files/anatomy/plugins" / "2fauth-base"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yml").write_text("name: 2fauth-base\n", encoding="utf-8")
    bad = _digit_initial(_source_slugs(tmp_path))
    assert ("app", "2fauth") in bad, f"app slug missed: {bad}"
    assert ("role", "2fauth") in bad, f"role slug missed: {bad}"
    assert ("plugin", "2fauth-base") in bad, f"plugin slug missed: {bad}"
    assert ("taxonomy_anchor", "2fauth") in bad, f"taxonomy_anchor missed: {bad}"


def test_every_manifest_service_has_handwritten_system_en():
    """p=64644: cortex store:materialise died — no SYSTEM_EN for device-gateway.

    A new manifest row without prose lands as a generic vector; the generator
    refuses rather than ship filler. Pin that refusal here so the next organ
    fails pytest, not a wet converge.
    """
    gen = _load_gen()
    services = yaml.safe_load(MANIFEST.read_text()).get("services") or []
    missing = [
        f"{s['id']} → {gen.SLUG_OVERRIDES.get(s['id']) or gen.slugify(s['id'])}"
        for s in services
        if (gen.SLUG_OVERRIDES.get(s["id"]) or gen.slugify(s["id"]))
        not in gen.SYSTEM_EN
    ]
    assert not missing, (
        "keap_selfmodel_gen.SYSTEM_EN has no entry for: " + ", ".join(missing)
    )
