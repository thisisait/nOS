"""docs/systems citation gate — keeps the S1 "no card cites a path that does not
exist" exit criterion closed (offline, fast, no live KEAP db).

The S1 reconciliation found three classes of confident-wrong citation in the
docs/systems corpus. Each was a *silent* defect: the text reads plausibly, the
generators embed it happily, and an agent following it dead-ends. Nothing pinned
them, which is exactly why the keap one survived a reconciliation commit. This
gate is the pin:

  1. REPO PATHS RESOLVE — every backticked repo-relative path a card cites must
     exist. Caught 9 bare `tasks/post.yml` citations (the real file is
     `roles/pazny.<svc>/tasks/post.yml`; a repo-root `tasks/` dir DOES exist and
     holds no post-hook, so the bare form looks resolvable and is not) plus a
     bare `tasks/main.yml` in openclaw.

  2. NODE IDS ARE SLUGS — a card citing a KEAP node id must use the slugified
     form. `keap_selfmodel_gen.slugify` maps every non-alnum to `-` and SLUG_RE
     forbids `_`, so `nos.infra.bluesky_pds` resolves to nothing in the corpus.

  3. EXTERNAL-STORAGE CLAIMS ARE TRUE — relocation is per-service and enumerated
     BY HAND in tasks/stacks/external-paths.yml. A card may only claim an
     override if that service actually has a var in that file. keap claimed one
     and has none, so an operator who set external_storage_root would believe the
     ~2400-node taxonomy followed the SSD when keap.db stayed on the internal disk.

Deliberately NOT flagged: `~/stacks/<stack>/...` config references. stacks_dir
really is ~/stacks and compose files really do live there — that is CORRECT and
current; only the DATA row moved to nos_data_root. Gate 1 only considers tokens
whose first segment is a real top-level repo entry, so a `~`-rooted runtime path
is never treated as a repo citation.
"""
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/systems"
MANIFEST = ROOT / "state/manifest.yml"
EXTERNAL_PATHS = ROOT / "tasks/stacks/external-paths.yml"

BACKTICKED = re.compile(r"`([^`\n]+)`")
# a bare path token: no spaces, no placeholder/glob metacharacters
PATH_TOKEN = re.compile(r"^[A-Za-z0-9_./-]+$")
PLACEHOLDER = re.compile(r"[<>{}*]")


def _doc_files():
    return sorted(DOCS.rglob("*.md")) + sorted(DOCS.rglob("*.md.j2"))


def _top_level_entries():
    return {p.name for p in ROOT.iterdir() if not p.name.startswith(".")}


# ── 1: every repo-relative path a card cites must exist ───────────────────────

def test_every_repo_relative_citation_resolves():
    top = _top_level_entries()
    dangling = []
    for path in _doc_files():
        rel = path.relative_to(ROOT)
        for match in BACKTICKED.finditer(path.read_text()):
            token = match.group(1).strip()
            if "/" not in token or not PATH_TOKEN.match(token):
                continue
            if PLACEHOLDER.search(token):
                continue          # `roles/pazny.<svc>/...` is a template, not a claim
            if token.split("/", 1)[0] not in top:
                continue          # container path, URL fragment, or ~/ runtime path
            if not (ROOT / token).exists():
                dangling.append(f"{rel} cites {token!r}, which does not exist")
    assert not dangling, "dangling repo-relative citations:\n  " + "\n  ".join(dangling)


# ── 2: cited KEAP node ids are slugs, never the raw underscored manifest id ────

def test_cited_node_ids_use_the_slug_form():
    """`_` is not a legal KEAP segment char, so an underscored node id resolves
    to nothing. The manifest id (bluesky_pds) is NOT the node id (bluesky-pds)."""
    offenders = []
    node_id = re.compile(r"\bnos(?:\.[A-Za-z0-9_-]+)+\b")
    for path in _doc_files():
        rel = path.relative_to(ROOT)
        for match in node_id.finditer(path.read_text()):
            cited = match.group(0)
            if "_" in cited:
                offenders.append(f"{rel} cites {cited!r} — slugify maps '_' to '-'")
    assert not offenders, "underscored node ids:\n  " + "\n  ".join(offenders)


# ── 3: an external-storage override claim must be backed by external-paths.yml ─

def _external_vars():
    """The vars tasks/stacks/external-paths.yml actually re-points."""
    text = EXTERNAL_PATHS.read_text()
    return set(re.findall(r"^\s+([a-z0-9_]+):\s", text, re.M))


def _manifest_services():
    data = yaml.safe_load(MANIFEST.read_text())
    services = data["services"] if isinstance(data, dict) else data
    return [s for s in services if isinstance(s, dict) and "id" in s]


def _doc_dir_to_manifest_id(doc_dir, by_id):
    for candidate in (doc_dir, doc_dir.replace("-", "_"), doc_dir.replace("-", "")):
        if candidate in by_id:
            return candidate
    return None


# An AFFIRMATIVE relocation claim, in the two shapes the corpus actually uses:
# naming the `external_storage_root` var (which only ever appears when a card
# shows a concrete relocated target), or "external-storage override" + an
# assertion verb. Deliberately NOT triggered by loose prose about external
# storage in general — erpnext correctly explains that its Docker named volume
# moves with the Docker Desktop disk image and is "not a path in
# external-paths.yml", and a gate that fires on that correct line is a
# regression, not a cleanup.
AFFIRMS = re.compile(
    r"external_storage_root"
    r"|external-storage override\b[^.\n]{0,80}?(?:relocates|applies|re-points|use|→)",
    re.I,
)
NEGATED = re.compile(
    r"\bno\s+external-storage\s+override\b|\bnot\s+a\s+path\s+in\b", re.I
)


def _vars_owned_by(doc_dir, by_id, ext):
    """The external-paths vars belonging to this service.

    Ownership is by NAME, normalised — the file's vars are named after the
    service (calibreweb_books_dir, firefly_upload_dir, uptime_kuma_data_dir),
    but the separator convention differs from the docs dir (calibre-web,
    uptime-kuma), so both sides drop `-`/`_` before comparing. The manifest
    `data_path_var` is added as a candidate for any var that does NOT follow
    the naming convention.
    """
    key = doc_dir.replace("-", "").replace("_", "")
    owned = {v for v in ext if v.replace("_", "").startswith(key)}
    mid = _doc_dir_to_manifest_id(doc_dir, by_id)
    if mid and by_id[mid].get("data_path_var") in ext:
        owned.add(by_id[mid]["data_path_var"])
    return owned


def test_external_storage_claims_are_backed_by_source():
    """An AFFIRMATIVE override claim requires the service to actually own a var
    in external-paths.yml. This is the keap defect: the card asserted a
    relocation that the file never performs."""
    by_id = {s["id"]: s for s in _manifest_services()}
    ext = _external_vars()
    unbacked = []
    for readme in sorted(DOCS.glob("*/README.md")):
        svc = readme.parent.name
        text = readme.read_text()
        if not AFFIRMS.search(text) or NEGATED.search(text):
            continue
        if not _vars_owned_by(svc, by_id, ext):
            unbacked.append(
                f"{readme.relative_to(ROOT)} claims an external-storage override, but no "
                f"{svc} var appears in tasks/stacks/external-paths.yml"
            )
    assert not unbacked, "unbacked external-storage claims:\n  " + "\n  ".join(unbacked)


def test_external_storage_denials_are_also_true():
    """The inverse direction, so a card cannot escape the gate above by simply
    writing "No external-storage override". A denial must ALSO match source."""
    by_id = {s["id"]: s for s in _manifest_services()}
    ext = _external_vars()
    wrong = []
    for readme in sorted(DOCS.glob("*/README.md")):
        svc = readme.parent.name
        if not NEGATED.search(readme.read_text()):
            continue
        owned = _vars_owned_by(svc, by_id, ext)
        if owned:
            wrong.append(
                f"{readme.relative_to(ROOT)} denies an external-storage override, but "
                f"{sorted(owned)} IS in tasks/stacks/external-paths.yml"
            )
    assert not wrong, "false denials:\n  " + "\n  ".join(wrong)


def test_the_external_paths_allowlist_is_actually_parsed():
    """Guard the guard: if the parse ever returns nothing, test 3 would pass
    vacuously for every card. Pin that the allowlist is non-trivial and that a
    known-overridden var and a known-NOT-overridden var land on opposite sides."""
    ext = _external_vars()
    assert len(ext) > 40, f"external-paths allowlist looks unparsed: {len(ext)} vars"
    assert "grafana_data_dir" in ext          # Wave A, genuinely relocated
    assert "keap_data_dir" not in ext         # the defect this gate exists to pin
