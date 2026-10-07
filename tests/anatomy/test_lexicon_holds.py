"""Anatomy gate — each word has one meaning, and the lexicon describes the repo.

WHY (2026-10-05, read-only naming study; rulings accepted 2026-10-06). nOS names
its parts after a living body, and several words had drifted into two or three
meanings: "organ" was a manifest row, a host daemon, an apex group and a model;
"memory" was KEAP, a database group and the immune verdict log; KEAP was also
called "the cortex". A model reading two meanings learns whichever it read
first. `state/genome/lexicon.yml` holds the one meaning; this gate keeps it true.

What it checks, all from artifacts, never from prose about them:
  (a) every `names:` surface exists (path, YAML key, graph kind, manifest field,
      launchd label, anchor prefix);
  (b) every `retired.surfaces` entry is gone;
  (c) every node kind in state/anatomy-graph.json is named by exactly one word,
      and that word is a body level, cross-cutting or internal (the same
      map tools/body-plan-gen.py projects; test_body_plan_is_a_projection.py);
  (d) `retired_phrases` do not appear in the files models are told to trust
      (TRUSTED below: the briefs, doctrine, system and anatomy docs, skills,
      agent prompts and agent.yml, plugin.yml, the apex ruling, genes, schemas,
      state tables, the default config layers, and the docstrings of tools/ and
      tests/anatomy/) — exact phrase, any case, across emphasis and line breaks;
  (e) every word that is not legacy or a proper name has a surface (or a
      written `no_surface_reason`), a `not` list and a `counter_example`
      (ssot/doctrine/body-plan.md §7: a word without one is a slogan).
Today's violations are pinned below and can only shrink (the ratchet in
test_genome_contract.py): fixing one fails until its line is deleted here.

CEILING. (d) matches exact phrases only: a new paraphrase of a retired sense
passes. It reads tracked files only, and ignores code, comments and history
("cell" in face grids, Python `self`, sha "digest", docs/archive, devlog,
RELEASE.md, hidden_fees, the KEAP corpus, state/fixtures/fable) — a gate that cried wolf
there would be switched off. A comment in code is not seen.
"""
from __future__ import annotations

import ast
import functools
import json
import pathlib
import re
import subprocess
import sys
import warnings

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LEXICON = REPO / "state" / "genome" / "lexicon.yml"
GRAPH = REPO / "state" / "anatomy-graph.json"
MANIFEST = REPO / "state" / "manifest.yml"
BODY_LEVELS = ("genome", "cell", "tissue", "organ", "organ system", "organism", "habitat")

# ── pending: today's violations, measured 2026-10-06. Only ever delete lines. ──

#: Retired surfaces that still exist; the rename steps (3–5) remove them.
PENDING_SURFACES: set[str] = set()

#: "file :: phrase" → occurrences, in the files models are told to trust.
#: Seeded 2026-10-07 when TRUSTED widened; the default config layers were fixed instead.
#: Spine phrases seeded 2026-10-07 (I-13) only in files other agents held that round.
PENDING_PHRASES: dict[str, int] = {
    'IMPRINT.md :: public organ': 1,
    'docs/systems/dolibarr/README.md :: praxis pack': 1,
    'files/anatomy/agents/invoice-extract/agent.yml :: party spine': 1,
    'files/anatomy/apex/ruling.yml :: cortex-query': 1,
    'files/anatomy/docs/grafana-wiring-inventory.md :: vessel': 3,
    'files/anatomy/plugins/bookstack-base/plugin.yml :: vessel': 1,
    'files/anatomy/plugins/crm-hydrate-base/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/dolibarr-base/plugin.yml :: backoffice pack': 1,
    'files/anatomy/plugins/freescout-base/plugin.yml :: vessel': 1,
    'files/anatomy/plugins/gitea-base/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/grafana-base/plugin.yml :: vessel': 2,
    'files/anatomy/plugins/grafana-keap/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/grafana-loki/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/grafana-prometheus/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/grafana-wing/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/hedgedoc-base/plugin.yml :: vessel': 1,
    'files/anatomy/plugins/hermes-base/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/infisical-base/plugin.yml :: vessel': 1,
    'files/anatomy/plugins/miniflux-base/plugin.yml :: vessel': 1,
    'files/anatomy/plugins/outline-base/plugin.yml :: tendon': 1,
    'files/anatomy/plugins/outline-base/plugin.yml :: vessel': 2,
    'files/anatomy/plugins/portainer-base/plugin.yml :: tendon': 5,
    'files/anatomy/plugins/portainer-base/plugin.yml :: vessel': 2,
    'files/anatomy/plugins/vaultwarden-base/plugin.yml :: tendon': 3,
    'files/anatomy/plugins/vaultwarden-base/plugin.yml :: vessel': 2,
    'files/anatomy/plugins/woodpecker-base/plugin.yml :: tendon': 5,
    'files/anatomy/plugins/woodpecker-base/plugin.yml :: vessel': 5,
    'files/anatomy/plugins/wordpress-base/plugin.yml :: vessel': 1,
    'state/digest-constitution.yml :: digest organ': 1,
    'state/digest-constitution.yml :: party spine': 1,
    'state/keap-tables/application.table.yml :: digest organ': 1,
    'state/keap-tables/invoice-line.table.yml :: digest organ': 1,
    'state/keap-tables/invoice-review.table.yml :: digest organ': 1,
    'state/keap-tables/invoice.table.yml :: digest organ': 1,
    'state/keap-tables/invoice.table.yml :: party spine': 1,
    'state/keap-tables/package.table.yml :: digest organ': 1,
    'state/keap-tables/package.table.yml :: party spine': 1,
    'state/keap-tables/party-registry-status.table.yml :: party spine': 3,
    'state/keap-tables/party.table.yml :: party spine': 1,
    'state/keap-tables/repo.table.yml :: digest organ': 1,
    'state/keap-tables/repo.table.yml :: party spine': 1,
    'state/habitat/llm-backends.yml :: spine redirect': 1,
    'tests/anatomy/test_digest_constitution.py :: digest organ': 1,
    'tests/anatomy/test_gitea_oauth_source_cli_register.py :: tendon': 1,
    'tests/anatomy/test_nos_digest_erasure.py :: digest organ': 1,
    'tests/anatomy/test_pulse_knowledge_contract.py :: cortex store': 1,
    'tests/anatomy/test_skills_prune_dangling_links.py :: cortex-query': 2,
    'tools/party-graph.py :: digest organ': 1,
}


# ── reading the artifacts ─────────────────────────────────────────────────


@functools.lru_cache(maxsize=None)
def _yaml(rel: str):
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _defaults() -> dict:
    """The committed config defaults, every layer (tools/nos_identity.py)."""
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity  # noqa: PLC0415
    return nos_identity.default_config()


def _words() -> dict:
    return _yaml(str(LEXICON.relative_to(REPO)))["words"]


@functools.lru_cache(maxsize=None)
def _graph_kinds() -> frozenset[str]:
    nodes = json.loads(GRAPH.read_text(encoding="utf-8"))["nodes"]
    return frozenset(n["kind"] for n in nodes.values())


def _has_key(doc, keys: list[str]) -> bool:
    if not keys:
        return True
    k, rest = keys[0], keys[1:]
    if k == "*":
        kids = doc.values() if isinstance(doc, dict) else doc if isinstance(doc, list) else []
        return any(_has_key(c, rest) for c in kids)
    return isinstance(doc, dict) and k in doc and _has_key(doc[k], rest)


def _text_under(globs: tuple[str, ...]) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for g in globs for p in sorted(REPO.glob(g)) if p.is_file())


#: Keys a surface may carry beside its one typed key.
_SURFACE_EXTRAS = {"reason", "values"}


def _typed(surface: dict) -> tuple[str, str]:
    (kind, value), = ((k, v) for k, v in surface.items() if k not in _SURFACE_EXTRAS)
    return kind, value


def _exists(surface: dict) -> bool:
    kind, value = _typed(surface)
    if kind == "path":
        p = REPO / value
        return p.is_dir() if value.endswith("/") else p.exists()
    if kind in ("yaml_key", "config_key"):
        if kind == "yaml_key":
            rel, _, dotted = value.partition("#")
            if not (REPO / rel).is_file():
                return False
            doc = _yaml(rel)
        else:
            doc, dotted = _defaults(), value
        if not _has_key(doc, dotted.split(".")):
            return False
        if "values" not in surface:
            return True
        for k in dotted.split("."):
            doc = doc[k]
        return set(doc.values()) == set(surface["values"])
    if kind == "graph_kind":
        return value in _graph_kinds()
    if kind == "manifest_field":
        schema = json.loads((REPO / "state/schema/manifest.schema.json").read_text(encoding="utf-8"))
        return (value in schema["definitions"]["service"]["properties"]
                and any(value in s for s in _yaml("state/manifest.yml")["services"]))
    if kind == "launchd_label":
        rows = {s.get("launchd_label") for s in _yaml("state/manifest.yml")["services"]}
        return value in rows or value in _text_under(
            ("templates/*.j2", "roles/*/defaults/main.yml", "roles/*/templates/*.j2"))
    if kind == "anchor_prefix":
        return value in _text_under(("docs/systems/*/*.md",))
    raise AssertionError(f"unknown surface type {kind!r} — add it here, do not skip it")


def _label(word: str, surface: dict) -> str:
    kind, value = _typed(surface)
    return f"{word}: {kind} {value}" + (f" = {surface['values']}" if "values" in surface else "")


#: The files models are told to trust, as git glob pathspecs over TRACKED files
#: only, so a sibling worktree, node_modules or vendor/ is never read.
TRUSTED = (
    "CLAUDE.md", "IMPRINT.md", "AGENTS.md", "tools/README.md",
    "ssot/README.md", "ssot/doctrine/**/*.md", "docs/doctrine/**/*.md", "docs/systems/*/*.md", "files/anatomy/docs/*.md",
    "files/anatomy/skills/*/SKILL.md", ".claude/skills/*/SKILL.md", ".claude/plugins/*/skills/*/SKILL.md",
    "files/anatomy/agents/*/system.md", "files/anatomy/agents/*/agent.yml",
    "files/anatomy/plugins/*/plugin.yml", "files/anatomy/apex/ruling.yml",
    "state/*.yml", "state/habitat/*.yml", "state/fixtures/local-model-bench.yml",
    "state/genome/genes/**", "state/schema/**", "state/digest-importers/**",
    "state/keap-tables/**", "default.credentials.yml")
#: Only the docstrings of these are trusted text; code and comments are not.
DOCSTRINGS = ("tools/*.py", "tests/anatomy/*.py")


def _tracked(globs: tuple[str, ...]) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", *(f":(glob){g}" for g in globs)],
                         cwd=REPO, capture_output=True, check=True).stdout.decode()
    return sorted(r for r in out.split("\0") if r and (REPO / r).is_file())


def _docstrings(src: str) -> str:
    """Only the docstring lines of a Python file, every other line blanked so
    line numbers still point into the file."""
    lines = src.splitlines()
    keep = [""] * len(lines)
    with warnings.catch_warnings():  # a tool's own escape warnings are not this gate's
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and ast.get_docstring(node) is not None):
            expr = node.body[0]
            keep[expr.lineno - 1:expr.end_lineno] = lines[expr.lineno - 1:expr.end_lineno]
    return "\n".join(keep)


@functools.lru_cache(maxsize=None)
def _trusted() -> tuple[tuple[str, str], ...]:
    """(repo path, text) of every trusted file. The lexicon, the glossary and
    history (archive, devlog, RELEASE.md, hidden_fees, the KEAP corpus,
    state/fixtures/fable) are outside TRUSTED: they may name retired senses."""
    rels = _tracked(TRUSTED)
    _defaults()  # puts tools/ on sys.path; the default layers come from nos_identity
    import nos_identity  # noqa: PLC0415
    rels += [str(p.relative_to(REPO)) for p in nos_identity.default_layers()]
    out = [(r, (REPO / r).read_text(encoding="utf-8", errors="replace")) for r in rels]
    me = str(pathlib.Path(__file__).resolve().relative_to(REPO))
    out += [(r, _docstrings((REPO / r).read_text(encoding="utf-8")))
            for r in _tracked(DOCSTRINGS) if r != me]
    return tuple(out)


def _phrase_rx(phrase: str) -> re.Pattern:
    """Exact words in order; between them any run of space, line break, `*`,
    backtick or blockquote `>`, so markdown emphasis cannot hide a phrase."""
    body = r"[\s*`>]+".join(re.escape(w) for w in phrase.split())
    return re.compile(rf"(?<![\w-]){body}(?:s|es)?(?![\w-])", re.IGNORECASE)


def _phrase_hits() -> dict[str, list[int]]:
    """'file :: phrase' → line numbers of each occurrence."""
    phrases = [p for w in _words().values() for p in w.get("retired_phrases") or []]
    hits: dict[str, list[int]] = {}
    for rel, text in _trusted():
        for ph in phrases:
            lines = [text.count("\n", 0, m.start()) + 1 for m in _phrase_rx(ph).finditer(text)]
            if lines:
                hits[f"{rel} :: {ph}"] = lines
    return hits


# ── the lexicon's own shape ───────────────────────────────────────────────


def test_every_word_has_a_level_and_one_plain_meaning():
    order = _yaml(str(LEXICON.relative_to(REPO)))["order"]
    assert tuple(order[: len(BODY_LEVELS)]) == BODY_LEVELS
    bad, seen = [], {}
    for word, w in _words().items():
        if w.get("level") not in order:
            bad.append(f"{word}: level {w.get('level')!r} not in order")
        if not str(w.get("means", "")).strip():
            bad.append(f"{word}: no `means`")
        for r in w.get("retired") or []:
            if not (r.get("sense") and r.get("replacement")):
                bad.append(f"{word}: a retired sense without sense+replacement")
        for ph in w.get("retired_phrases") or []:
            if ph.lower() in seen:
                bad.append(f"phrase {ph!r} retired by both {seen[ph.lower()]} and {word}")
            seen[ph.lower()] = word
    assert not bad, "\n  ".join(["lexicon shape:", *bad])


#: Levels whose words are names kept as spelled; they owe no counter-example.
_NAMES_KEPT = ("legacy", "proper-name")


def test_every_word_has_a_surface_a_not_list_and_a_counter_example():
    bad = []
    for word, w in _words().items():
        if w.get("level") in _NAMES_KEPT:
            continue
        if not (w.get("names") or str(w.get("no_surface_reason") or "").strip()):
            bad.append(f"{word}: no `names` and no `no_surface_reason`")
        if not w.get("not"):
            bad.append(f"{word}: no `not` list")
        if not str(w.get("counter_example") or "").strip():
            bad.append(f"{word}: no `counter_example`")
    assert not bad, "\n  ".join(["a word without a counter-example is a slogan (body-plan.md §7):", *bad])


# ── (a) named surfaces exist ──────────────────────────────────────────────


def test_every_named_surface_exists():
    missing = [_label(word, s) for word, w in _words().items()
               for s in w.get("names") or [] if not _exists(s)]
    assert not missing, (
        "the lexicon names surfaces that are not in the repo — fix the lexicon "
        "or the surface:\n  " + "\n  ".join(missing))


# ── (b) retired surfaces are gone ─────────────────────────────────────────


def test_retired_surfaces_are_gone_and_the_pending_list_only_shrinks():
    present = {_label(word, s) for word, w in _words().items()
               for r in w.get("retired") or [] for s in r.get("surfaces") or [] if _exists(s)}
    assert present == PENDING_SURFACES, (
        f"new retired surfaces still present: {sorted(present - PENDING_SURFACES)}; "
        f"pending ones now gone (delete them from PENDING_SURFACES): "
        f"{sorted(PENDING_SURFACES - present)}")


# ── (c) every graph kind maps to one ruled word ───────────────────────────


def test_every_graph_kind_maps_to_exactly_one_level():
    named: dict[str, list[str]] = {}
    for word, w in _words().items():
        for s in w.get("names") or []:
            if "graph_kind" in s:
                named.setdefault(s["graph_kind"], []).append(word)
    twice = {k: v for k, v in named.items() if len(v) > 1}
    assert not twice, f"graph kinds named by more than one word: {twice}"

    words = _words()
    ruled = {k for k, (w,) in named.items()
             if words[w]["level"] in BODY_LEVELS + ("cross", "internal")}
    unruled = sorted(set(_graph_kinds()) - ruled)
    assert not unruled, (
        f"graph kinds with no body level, cross or internal ruling: {unruled} — "
        f"name each under one word's `names: graph_kind` in state/genome/lexicon.yml")


# ── (d) retired phrases, in the files models trust ────────────────────────


def test_retired_phrases_in_trusted_files_only_shrink():
    hits = _phrase_hits()
    have = {k: len(v) for k, v in hits.items()}
    if have == PENDING_PHRASES:
        return
    grew = {k: (n, PENDING_PHRASES.get(k, 0)) for k, n in have.items()
            if n > PENDING_PHRASES.get(k, 0)}
    shrank = {k: (have.get(k, 0), n) for k, n in PENDING_PHRASES.items()
              if have.get(k, 0) < n}
    lines = [f"{k}: {n} (pending {p}) at lines {hits[k]}"
             for k, (n, p) in sorted(grew.items())]
    pytest.fail(
        "retired phrases in files models are told to trust (state/genome/lexicon.yml "
        "says what to write instead):\n  " + "\n  ".join(lines or ["(none new)"])
        + ("\nfixed — lower or delete these in PENDING_PHRASES:\n  "
           + "\n  ".join(f"{k}: now {a}, pending {b}" for k, (a, b) in sorted(shrank.items()))
           if shrank else ""))


def test_the_phrase_matcher_sees_through_markdown():
    """Proves (d) can go red: emphasis, backticks and a line break between the
    words must not hide a retired phrase, and a longer word must not match."""
    rx = _phrase_rx("digest organ")
    assert rx.search("the **Digest**\n> organ ingests")
    assert rx.search("`digest` organs")
    assert not rx.search("digest organism")
    assert not rx.search("mail digest organizer")
