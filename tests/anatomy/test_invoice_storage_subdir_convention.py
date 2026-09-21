"""storage-subdir unit (2026-09-20) — Model C: a per-client SUBDIRECTORY under
one consultant tenant, never a per-client tenant. Layout documented in
bootstrap/minimal-linux-dgx/kb/digest-importers.md:

    {nos_data_root}/tenants/<t>/users/<uid>/inbox/accounting/<book_owner-slug>/
    ├── incoming/  extracts/  processed/

nos_digest.infer_book_owner_slug() reads the slug off the directory name; the
importer cross-checks it against --book-owner-ico so the two cannot drift.
"""
import copy
import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
VISION_FIXTURE = REPO / "state" / "fixtures" / "vision-fixture"
TABLES = REPO / "state" / "keap-tables"

sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
import nos_digest  # noqa: E402

INDEX = {"by_key": {("ICO", "00000112"): "synthetic-mesto-lipno",
                    ("ICO", "00000113"): "synthetic-svoboda-petr"}, "by_name": {}}


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_infer_book_owner_slug_reads_the_documented_leaves():
    root = pathlib.Path("/nos/tenants/consultant/users/u1/inbox/accounting/synthetic-client-alfa/incoming")
    assert nos_digest.infer_book_owner_slug(root) == "synthetic-client-alfa"
    root2 = root.parent / "extracts"
    assert nos_digest.infer_book_owner_slug(root2) == "synthetic-client-alfa"


def test_infer_book_owner_slug_is_none_for_a_flat_ad_hoc_root():
    assert nos_digest.infer_book_owner_slug(VISION_FIXTURE) is None


def test_dir_only_invocation_resolves_book_owner_from_a_known_slug():
    mod = _load("digest_import_vision_subdir", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True,
                             book_owner_slug_hint="synthetic-svoboda-petr")
    bundle, errors = nos_digest.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert inv["book_owner"] == "synthetic-svoboda-petr"


def test_dir_only_invocation_refuses_an_unknown_slug_never_mints_it():
    mod = _load("digest_import_vision_subdir2", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True,
                             book_owner_slug_hint="not-a-real-client")
    bundle, errors = nos_digest.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert "book_owner" not in inv
    assert any("not-a-real-client" in s for s in imp.skipped), imp.skipped


def test_cli_flag_and_directory_agreeing_is_fine():
    mod = _load("digest_import_vision_subdir3", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True,
                             book_owner_ico="00000113",
                             book_owner_slug_hint="synthetic-svoboda-petr")
    bundle, errors = nos_digest.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert errors == [], errors
    inv = bundle["deterministic"]["invoice"][0]
    assert inv["book_owner"] == "synthetic-svoboda-petr"


def test_cli_flag_and_directory_disagreeing_refuses_the_whole_run():
    """RETRO-RED shape: before this unit --book-owner-ico and a mismatched
    directory silently produced a row stamped with whichever slug the flag
    resolved to — no signal that the operator ran the wrong directory."""
    mod = _load("digest_import_vision_subdir4", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True,
                             book_owner_ico="00000113",           # resolves to svoboda-petr
                             book_owner_slug_hint="synthetic-client-alfa")  # directory says alfa
    bundle, errors = nos_digest.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert errors == [], errors
    assert bundle["deterministic"].get("invoice", []) == []
    joined = " | ".join(imp.skipped)
    assert "drift" in joined and "synthetic-svoboda-petr" in joined and "synthetic-client-alfa" in joined


def test_import_index_is_untouched_by_the_hint_path():
    """Guard against accidental index mutation across the two normalize()
    branches sharing party_index."""
    before = copy.deepcopy(INDEX)
    mod = _load("digest_import_vision_subdir5", "digest-import-vision.py")
    imp = mod.VisionImporter("vision-fixture", INDEX, fixture_mode=True,
                             book_owner_slug_hint="synthetic-svoboda-petr")
    nos_digest.run_importer(imp, str(VISION_FIXTURE), TABLES)
    assert INDEX == before


def test_resolve_data_root_prefers_env_then_config_yml(tmp_path):
    (tmp_path / "config.yml").write_text("nos_data_root: /Volumes/SSD1TB/nOS/data\n", encoding="utf-8")
    assert nos_digest.resolve_data_root(tmp_path, {}) == pathlib.Path("/Volumes/SSD1TB/nOS/data")
    assert nos_digest.resolve_data_root(tmp_path, {"NOS_DATA_ROOT": "/tmp/x"}) == pathlib.Path("/tmp/x")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert nos_digest.resolve_data_root(empty, {}) == pathlib.Path.home() / "nos"


def test_ensure_accounting_inboxes_makes_the_three_leaves(tmp_path):
    nos_digest.ensure_accounting_inboxes(
        tmp_path, "pazny", ["akadmin"], ["synthetic-client-alfa"])
    base = tmp_path / "tenants/pazny/users/akadmin/inbox/accounting/synthetic-client-alfa"
    for leaf in ("incoming", "extracts", "processed"):
        assert (base / leaf).is_dir()


def test_json_from_agent_stdout_skips_a_prefix():
    spec = importlib.util.spec_from_file_location(
        "invoice_vision_pipeline_json", REPO / "tools" / "invoice-vision-pipeline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.json_from_agent_stdout('noise\n{"chain": {"text": "x"}}') == {"chain": {"text": "x"}}
    assert mod.ocr_text_from_agent("Doklad c.: 2026-ALFA-001\nIČO 00000131") == (
        "Doklad c.: 2026-ALFA-001\nIČO 00000131")
    assert mod.ocr_text_from_agent('{"chain": {"text": "hello from json"}}') == "hello from json"


def test_intake_idle_when_root_exists_without_incoming(tmp_path):
    """RETRO-RED: Pulse nightly rc=2 because ~/nos was missing on an SSD estate."""
    spec = importlib.util.spec_from_file_location(
        "invoice_vision_intake_idle", REPO / "tools" / "invoice-vision-intake.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--root", str(tmp_path)]) == 0
    assert mod.main(["--root", str(tmp_path / "missing")]) == 2


def test_park_incoming_moves_the_original_out_of_the_queue(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "invoice_vision_intake_park", REPO / "tools" / "invoice-vision-intake.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    img = incoming / "alfa-001.jpg"
    img.write_bytes(b"x")
    dest = mod.park_incoming(img)
    assert not img.exists()
    assert dest == tmp_path / "processed" / "alfa-001.jpg"
    assert dest.read_bytes() == b"x"
