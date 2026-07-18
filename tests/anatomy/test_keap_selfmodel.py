"""KEAP self-model generator — contract gate (offline, fast).

Pins the nOS→stack→service knowledge-tree generator that feeds KEAP's fs-sync
mirror (docs/plans/keap-selfmodel.md). Asserts: the generator renders the
expected folder shape + per-card fields, real taxonomy node-id anchors, cross-
link object-ids that match KEAP v1.7.0's `fs:<uid>:sha1(relPath)[:16]` scheme,
byte-determinism (so fs-sync's size+mtime skip holds), and that the role wiring
(task include, compose mount, KEAP_FS_SYNC_DIRS, defaults) is present.
"""
import hashlib
import importlib.util
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
GEN = ROOT / "files/anatomy/scripts/keap_selfmodel_gen.py"
MANIFEST = ROOT / "state/manifest.yml"
PLUGINS = ROOT / "files/anatomy/plugins"


def _load_gen():
    spec = importlib.util.spec_from_file_location("keap_selfmodel_gen", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A sample of the REAL Ansible-resolved facts tasks/selfmodel.yml passes as
# --facts-json (version/image/port/domain/data_path/mem/cpu per service id).
SAMPLE_FACTS = {
    "gitea": {
        "image": "gitea/gitea", "version": "1.26.4", "port": 3003,
        "domain": "git.pazny.eu", "data_path": "/srv/nos/gitea",
        "mem_limit": "1g", "cpus": "1.0",
    },
    "postgresql": {"image": "postgres", "version": "16", "port": 5432},
}


def _generate(tmp_path, uid="nos-docs", top="nOS", facts=None):
    gen = _load_gen()
    model = gen.build_model(str(MANIFEST), str(PLUGINS), {}, {},
                            facts if facts is not None else SAMPLE_FACTS)
    res = gen.generate(model, str(tmp_path), uid, top)
    return gen, model, res


def test_generator_and_sources_exist():
    assert GEN.is_file(), "generator script missing"
    assert MANIFEST.is_file() and PLUGINS.is_dir()


def test_folder_shape_and_cards(tmp_path):
    gen, model, res = _generate(tmp_path)
    top = "nOS"
    # platform root + one card per stack + one card per service.
    assert (tmp_path / top / "_platform.md").is_file()
    assert len(model["services"]) > 40
    for stack, members in model["stacks"].items():
        assert (tmp_path / top / stack / "_stack.md").is_file(), f"missing {stack} card"
        for sid in members:
            assert (tmp_path / top / stack / f"{sid}.md").is_file()
    # created everything, changed nothing spuriously.
    assert res["created"] > 0 and res["updated"] == 0 and res["removed"] == 0


def test_service_card_fields_and_anchor(tmp_path):
    _generate(tmp_path)
    # gitea: native OIDC, devops stack — must anchor to CS + depend on authentik.
    card = (tmp_path / "nOS/devops/gitea.md").read_text()
    assert card.startswith("# "), "card needs an H1 display name"
    assert "**Stack:** devops" in card
    # Whole-map CS-root anchor renders as a taxonomy ray ([[NN.NN]] dotted 2-digit).
    assert "[[02.02]]" in card
    anchors = re.findall(r"\[\[(\d{2}(?:\.\d{2})*)\]\]", card)
    assert anchors and all(re.fullmatch(r"\d{2}(?:\.\d{2})*", a) for a in anchors)
    assert "depends-on" in card and "Authentik" in card


def test_real_facts_land_in_card(tmp_path):
    """The operator refinement: cards carry REAL deployed state, not just prose.
    The Ansible-resolved facts (version/image/port/domain/…) must render in a
    State section AND enrich the embedded description."""
    _generate(tmp_path, facts=SAMPLE_FACTS)
    card = (tmp_path / "nOS/devops/gitea.md").read_text()
    assert "## State" in card
    assert "1.26.4" in card and "gitea/gitea" in card          # image:version
    assert "git.pazny.eu" in card and "3003" in card           # domain + port
    assert "/srv/nos/gitea" in card                            # data path
    assert "1g" in card                                        # mem limit
    # real state also folded into the description line (→ embedded body).
    assert "Deployed as gitea/gitea:1.26.4" in card
    # a service with NO facts renders no State section (facts are optional).
    nofacts = (tmp_path / "nOS/infra/redis.md").read_text()
    assert "## State" not in nofacts


def test_crosslink_ids_match_keap_scheme(tmp_path):
    """belongs-to/depends-on object-ids must equal fs:<uid>:sha1(relPath)[:16]."""
    uid, top = "nos-docs", "nOS"
    _generate(tmp_path, uid, top)
    card = (tmp_path / "nOS/devops/gitea.md").read_text()
    # gitea belongs to the devops stack card.
    want = "fs:%s:%s" % (
        uid, hashlib.sha1(f"{top}/devops/_stack.md".encode()).hexdigest()[:16])
    assert f"[[object:{want}]]" in card, "belongs-to id must match KEAP relPath hash"
    # gitea depends on infra/authentik.
    dep = "fs:%s:%s" % (
        uid, hashlib.sha1(f"{top}/infra/authentik.md".encode()).hexdigest()[:16])
    assert f"[[object:{dep}]]" in card


def test_deterministic_rerun_is_noop(tmp_path):
    gen, model, _ = _generate(tmp_path)
    res2 = gen.generate(model, str(tmp_path), "nos-docs", "nOS")
    assert res2 == {"created": 0, "updated": 0, "unchanged": res2["unchanged"],
                    "removed": 0}
    assert res2["unchanged"] > 40


def test_prune_removes_stale_cards(tmp_path):
    gen, model, _ = _generate(tmp_path)
    zombie = tmp_path / "nOS/infra/ZOMBIE.md"
    zombie.write_text("stale")
    res = gen.generate(model, str(tmp_path), "nos-docs", "nOS")
    assert not zombie.exists() and res["removed"] == 1


def test_role_wiring():
    # task file exists and is included behind the toggle.
    assert (ROOT / "roles/pazny.keap/tasks/selfmodel.yml").is_file()
    main = (ROOT / "roles/pazny.keap/tasks/main.yml").read_text()
    assert "selfmodel.yml" in main and "keap_selfmodel" in main
    # compose mounts the class-2 tree as the reserved fs-sync uid.
    compose = (ROOT / "roles/pazny.keap/templates/compose.yml.j2").read_text()
    assert "keap_selfmodel_root" in compose and "keap_selfmodel_uid" in compose
    # The self-model is a NESTED mount under the RO /user-files — runc cannot
    # mkdir its mountpoint inside a read-only parent (iiab up rc=1, 2026-07-18).
    # The keap role MUST pre-create the users/<uid> mountpoint dir on the host.
    tasks_main = (ROOT / "roles/pazny.keap/tasks/main.yml").read_text()
    assert "users/{{ keap_selfmodel_uid" in tasks_main, \
        "keap must pre-create the users/<uid> nested-mount mountpoint dir"
    # defaults define the toggle + class-2 root + the fs-sync top-class allowlist.
    defaults = (ROOT / "roles/pazny.keap/defaults/main.yml").read_text()
    assert re.search(r"^keap_selfmodel:\s*true", defaults, re.M)
    assert "shared/nos-docs" in defaults, "self-model must be class-2 shared, not users/"
    assert re.search(r"^keap_fs_sync_dirs:.*nOS", defaults, re.M), \
        "fs-sync top-class allowlist must include nOS"
