"""One journey through the pazny.keap role: the pin it builds from, the image tag
that names that tree, the data dir the container can open, the query embedder it
is handed, and the tables a fresh KEAP is seeded with.

Absorbed (2026-11-08, roadmap gate-diet-role-journeys), one section each:
  test_keap_pin_not_cancelled, test_the_keap_tag_names_a_tree,
  test_keap_data_dir_owned_by_image_user, test_keap_query_embedder_on_linux,
  test_fresh_keap_has_the_tables_tools_address, test_keap_empty_seed_skips_row_fetch.
Every assert of those files survives here with the same inputs and expectations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

ROLE = REPO / "roles" / "pazny.keap"
TASKS = ROLE / "tasks"
ROLE_DEFAULTS = ROLE / "defaults" / "main.yml"


def _when(task: dict) -> str:
    w = task.get("when")
    if w is None:
        return ""
    if isinstance(w, list):
        return " && ".join(str(x) for x in w)
    return str(w)


# ── test_keap_pin_not_cancelled ─────────────────────────────────────────────
# KEAP v1.19.0 is a published tag carrying the cancelled numeric user-root
# scheme: the slug root `nos` is rejected with a bare null and the self-model
# vanishes with no log line. KEAP kept the tag, so the trap is loud here
# (ssot/doctrine/gates.md applied to itself); slug schema needs >= v1.21.0.

# Tags whose schema was cancelled after release. Append (never remove) if
# another published tag turns out to carry a retracted design.
CANCELLED = {
    "1.19.0": (
        "ships the cancelled numeric user-root scheme (USER_ROOT_MIN set); "
        "the slug root `nos` is rejected with a bare null, so the self-model "
        "constellation vanishes with no log line. Use v1.20.0 or newer."
    ),
}


def _norm(tag: str) -> str:
    return str(tag).strip().lstrip("vV")


def _role_pin() -> str:
    return _norm(yaml.safe_load(ROLE_DEFAULTS.read_text())["keap_repo_ref"])


def _config_pins() -> dict:
    cfg = ni.default_config()
    return {k: _norm(v) for k, v in cfg.items() if k in ("keap_version", "keap_repo_ref")}


def test_role_pin_is_not_a_cancelled_tag():
    pin = _role_pin()
    assert pin not in CANCELLED, (
        f"keap_repo_ref is pinned to v{pin} — {CANCELLED.get(pin, '')}"
    )


def test_config_pins_are_not_cancelled_tags():
    for var, pin in _config_pins().items():
        assert pin not in CANCELLED, (
            f"{var} is pinned to v{pin} — {CANCELLED.get(pin, '')}"
        )


def test_the_trap_is_documented_where_the_pin_is_edited():
    """The hazard fires at pin-bump time, so the warning has to live at the pin
    site — not only in a spec the person bumping a version will not open."""
    src = ROLE_DEFAULTS.read_text()
    assert "v1.19.0" in src and "NEVER PIN" in src.upper(), (
        "the v1.19.0 trap must be documented next to keap_repo_ref itself"
    )


def test_pins_agree_with_each_other():
    """A split pin builds one image and runs another — the version-shadow class."""
    cfg = _config_pins()
    if "keap_version" in cfg:
        assert cfg["keap_version"] == _role_pin(), (
            f"keap_version ({cfg['keap_version']}) != keap_repo_ref ({_role_pin()}) "
            "— the image tag and the built source would disagree"
        )


# v1.20.0 has slug ids but single-pass boot registration; ingest applies domain
# files in directory order (`nos.infra.json` before `nos.json`), so the subtree
# is dropped silently. Dormant until the generator emits the slug tree.
SELFMODEL_MIN = (1, 21, 0)


def _tuple(tag: str) -> tuple:
    parts = _norm(tag).split("-")[0].split(".")
    return tuple(int(p) for p in parts[:3]) if all(p.isdigit() for p in parts[:3]) else (0, 0, 0)


def test_slug_schema_requires_a_boot_fixpoint_keap():
    """Keyed on what the GENERATOR emits, not on a test fixture existing."""
    schema = yaml.safe_load(ROLE_DEFAULTS.read_text()).get("keap_selfmodel_schema", "anchors")
    if schema != "slug":
        return  # generator still emits the legacy anchored tree
    pin = _tuple(_role_pin())
    assert pin >= SELFMODEL_MIN, (
        f"keap_selfmodel_schema is 'slug' but keap_repo_ref is v{_role_pin()} — below "
        "v1.21.0 boot registration is single-pass, so directory order (nos.infra.json "
        "before nos.json) makes children older than their root and the WHOLE TREE is "
        "dropped silently"
    )


# ── test_the_keap_tag_names_a_tree ──────────────────────────────────────────
# hidden_fees/12: `image: nos/keap:{{ keap_version }}` was rebuilt in place on
# every converge, so the tag named the last build, not a tree — no rollback, and
# a hand `git pull` changed the container silently. The tag carries the commit
# from `git rev-parse`, with no `| default(...)` fallback.

COMPOSE = ROLE / "templates" / "compose.yml.j2"
KEAP_MAIN = TASKS / "main.yml"


def test_the_files_this_gate_describes_exist():
    """Positive control — a renamed role makes every check below vacuous."""
    assert COMPOSE.is_file(), "roles/pazny.keap/templates/compose.yml.j2 is gone"
    assert KEAP_MAIN.is_file(), "roles/pazny.keap/tasks/main.yml is gone"
    assert "image: nos/keap:" in COMPOSE.read_text(encoding="utf-8"), (
        "the compose fragment no longer tags a nos/keap image at all"
    )


def test_the_tag_carries_a_resolved_commit():
    src = COMPOSE.read_text(encoding="utf-8")
    match = re.search(r"^\s*image:\s*nos/keap:(.+)$", src, re.M)
    assert match, "no `image: nos/keap:…` line found"
    tag = match.group(1).strip()
    assert "keap_image_tag" in tag, (
        f"the image tag is {tag!r}, which does not use `keap_image_tag`. A tag "
        "built from the version alone is rewritten in place by every "
        "`up -d --build`, so it names the last build and not a tree."
    )


def test_the_tag_has_no_silent_fallback():
    """A `| default(keap_version)` here restores the entire defect while reading
    as caution — which is why it is worth a test of its own."""
    src = COMPOSE.read_text(encoding="utf-8")
    match = re.search(r"^\s*image:\s*nos/keap:(.+)$", src, re.M)
    assert match
    tag = match.group(1)
    assert "default(" not in tag, (
        f"the image tag {tag.strip()!r} falls back when `keap_image_tag` is "
        "unset. The passes where the fact is missing are the `--tags` passes "
        "where someone is iterating, so the fallback would restore the "
        "ambiguity exactly when nobody is looking for it. Let the render fail."
    )


def test_the_commit_is_read_from_the_checkout_not_the_clone_result():
    """`_keap_clone.after` is undefined whenever the clone task did not run this
    pass, so the tag must come from what is on disk."""
    src = KEAP_MAIN.read_text(encoding="utf-8")
    assert "git rev-parse" in src, (
        "the commit is no longer read from the checkout. If it now comes from "
        "the git module's registered result, the tag is undefined on every "
        "pass that did not re-clone."
    )
    assert "keap_image_tag" in src, "tasks/main.yml no longer sets keap_image_tag"
    assert "check_mode: false" in src, (
        "the rev-parse no longer runs in check mode, so `--check` would fail to "
        "render the compose fragment rather than reporting what it would do."
    )


# ── test_keap_data_dir_owned_by_image_user ──────────────────────────────────
# CI run 37265044993 (2026-10-05, first Linux install_keap): keap-1 crash-looped
# on SQLITE_CANTOPEN — the image runs USER node (uid 1000), the /data bind source
# was the runner's (uid 1001, 0755). Docker Desktop maps ownership, so macOS
# never saw it. Off Darwin the dir is owned by keap_container_uid.

def _data_dir_task() -> dict:
    tasks = yaml.safe_load(KEAP_MAIN.read_text(encoding="utf-8"))
    hits = [t for t in tasks if "keap_data_dir" in str(t.get("ansible.builtin.file", {}).get("path", ""))]
    assert len(hits) == 1, "expected one file task whose path is keap_data_dir"
    return hits[0]


def test_data_dir_is_owned_by_the_container_user_off_darwin() -> None:
    t = _data_dir_task()
    f = t["ansible.builtin.file"]
    owner, group = str(f.get("owner", "")), str(f.get("group", ""))
    assert "keap_container_uid" in owner and "Darwin" in owner, (
        "keap_data_dir owner must be keap_container_uid off Darwin — the image "
        "runs as uid 1000 and libsql cannot create keap.db otherwise"
    )
    assert "user_gid" in group and "0775" in str(f.get("mode", "")), (
        "the host user keeps write via group (post.yml touches .fixtures-seeded here)"
    )
    assert "Darwin" in str(t.get("become", "")), "chown to another uid needs become off Darwin"


def test_container_uid_default_is_the_image_user() -> None:
    d = yaml.safe_load(ROLE_DEFAULTS.read_text(encoding="utf-8"))
    assert d.get("keap_container_uid") == 1000, "nos-keap Dockerfile: USER node (uid 1000)"


# ── test_keap_query_embedder_on_linux ───────────────────────────────────────
# spark1 2026-10-21: Iris missed paraphrased knowledge because keap_ollama_url
# defaulted to "" on Linux, so search ran without its vector leg (9/24 -> 13/24
# with it). The default is ollama_url on Linux, host.docker.internal on macOS,
# "" without Ollama. The effect is keap-semantic-search's `[legs: vector …]`.

def _raw() -> str:
    layers = [yaml.safe_load(f.read_text(encoding="utf-8")) or {} for f in ni.default_layers()]
    return next(d["keap_ollama_url"] for d in layers if "keap_ollama_url" in d)


def _render(system: str, install_ollama: bool) -> str:
    raw = _raw()
    ctx = {"ansible_system": system, "install_ollama": install_ollama, "ollama_url": "http://172.17.0.1:11434"}
    return jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(raw).render(ctx)


def test_linux_with_ollama_embeds_queries_on_the_bridge():
    assert _render("Linux", True) == "http://172.17.0.1:11434"


def test_macos_embeds_through_docker_desktop():
    assert _render("Darwin", True) == "http://host.docker.internal:11434"


def test_macos_without_ollama_no_embedder():
    assert _render("Darwin", False) == ""


def test_no_ollama_no_embedder():
    assert _render("Linux", False) == ""


# ── test_fresh_keap_has_the_tables_tools_address ────────────────────────────
# After `nos --remove=data` (2026-10-09) `nos dtt seed --sync` 404'd: the roadmap
# table had been made by hand once and no converge created it; current-state and
# the books spine were missing the same way. Every table the default tools
# address is seeded by a task that runs on install_keap alone.

REQUIRED = ["current-state", "party", "party-tax-identity", "account", "invoice", "invoice-line",
            "journal-entry", "posting", "pending-invoice-verify", "book-access"]


def _roadmap_id() -> str:
    m = re.search(r'NOS_ROADMAP_TABLE_ID", "([^"]+)"', (REPO / "tools/roadmap-seed.py").read_text())
    return m.group(1)


def _seeded_on_keap_alone() -> set[str]:
    out = set()
    for t in yaml.safe_load((TASKS / "post.yml").read_text()):
        inc, when = t.get("ansible.builtin.include_tasks"), t.get("when")
        when = [when] if isinstance(when, str) else (when or [])
        if inc and inc.startswith("seed-") and all("install_keap" in w for w in when):
            text = (TASKS / inc).read_text()
            text = text.replace("{{ keap_roadmap_table_id }}", _default("keap_roadmap_table_id"))
            out |= set(re.findall(r'slug: "([^"{]+)"', text))
    return out


def _default(name: str) -> str:
    """The value the default layers declare (ruling 2026-10-12: no longer a keap role default)."""
    return str(ni.default_config().get(name, ""))


def test_every_addressed_table_is_created_by_a_converge():
    seeded = _seeded_on_keap_alone()
    missing = [s for s in [_roadmap_id()] + REQUIRED if s not in seeded]
    assert not missing, f"a fresh KEAP lacks tables the default tools address: {missing}"


def test_an_existing_roadmap_is_created_never_reshaped():
    """The estate's roadmap predates its definition (refs text, a `when` column);
    a reconcile against it is a 409 that fails the converge. Create only."""
    core = (TASKS / "seed-core-tables.yml").read_text()
    item = core[core.index("keap_roadmap_table_id"):core.index('slug: "current-state"')]
    assert "create_only: true" in item
    seeder = (TASKS / "seed-face-table.yml").read_text()
    assert "create_only" in seeder, "the shared seeder ignores create_only"


# ── test_keap_empty_seed_skips_row_fetch ────────────────────────────────────
# S7, p=54800: caddy-sessions (rows: []) still fetched every chat row (~21s) for
# a WHERE-guard the upsert never used. An empty seed skips the fetch, and resets
# the slug guard so the next table's upsert does not see the previous list.

SEED = TASKS / "seed-face-table.yml"


def _seed_tasks():
    return yaml.safe_load(SEED.read_text(encoding="utf-8"))


def _named_contains(needle: str) -> dict:
    return next(
        t for t in _seed_tasks()
        if isinstance(t, dict) and needle in str(t.get("name", ""))
    )


def test_row_fetch_is_skipped_when_the_seed_is_empty():
    fetch = _named_contains("Fetch existing rows")
    text = _when(fetch)
    assert "_face_tbl.rows" in text and "length" in text, (
        f"{SEED}: fetch must skip when `_face_tbl.rows` is empty; when={text}"
    )


def test_empty_seed_resets_slug_guard_so_the_next_table_is_not_poisoned():
    reset = _named_contains("No row WHERE-guard")
    assert reset.get("ansible.builtin.set_fact", reset.get("set_fact")) == {
        "_face_existing_row_slugs": []
    } or "_face_existing_row_slugs" in str(reset)
    assert "[]" in str(reset.get("ansible.builtin.set_fact") or reset.get("set_fact") or reset)
    assert "== 0" in _when(reset) or "length" in _when(reset)


def test_upsert_when_survives_an_undefined_slug_guard():
    upsert = _named_contains("Upsert MISSING system rows")
    text = _when(upsert)
    assert "_face_existing_row_slugs" in text
    assert "default([])" in text or "default([])" in str(upsert), (
        f"{SEED}: upsert `when` must default the slug list; empty-table skip "
        f"otherwise errors or reuses the prior include's slugs: {text}"
    )
    assert "_face_tbl.rows" in text
