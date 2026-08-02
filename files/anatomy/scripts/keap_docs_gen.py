#!/usr/bin/env python3
"""KEAP docs-as-knowledge generator — the estate's PROSE as typed KEAP nodes.

Companion to `keap_selfmodel_gen.py`. That script emits the estate's SHAPE —
`nos.<stack>.<system>` nodes and their credentials. This one emits the estate's
PROSE — the READMEs, agent briefs and skill sheets under `docs/systems/` — as
typed child nodes hanging off the very system nodes the self-model already
placed. It does NOT invent a second tree; it augments the first (design decision
§3, `docs/archive/cortex-docs-schema.md`).

WHY A SEPARATE FILE THAT MERGES INTO THE SELF-MODEL'S CANONICAL TREE
    `knowledge/ingest.mjs` owns a domain SUBTREE wipe-then-insert: ingesting a
    file whose `domain` is `nos.devops` deletes every `nos.devops.%` row and
    re-inserts only that file's nodes. Two files claiming the same domain, or two
    ingest passes sharing the `nos` root, therefore delete each other's nodes
    (the stale-domain sweep prunes any `nos.*` marker absent from the current
    run's file set). So doc nodes cannot be a parallel tree or a second pass:
    they must land in the SAME per-stack domain file the self-model wrote, and be
    ingested in the SAME pass. This generator reads those files and appends.

THE FOUR KINDS, DECLARED NOT INFERRED (design §1/§2)
    A block's kind is read from a signal already present in well-written
    markdown — never guessed from topic:

        `**Trigger:**` lead line     → skill   (invocable; carries recall phrases)
        `**When …**` / `**If …**`    → hint    (true only under a condition)
        a fenced ``` code block      → snippet (correct only byte-for-byte)
        anything else                → note    (the standing-claim default)

    File-level frontmatter `type:` sets a file's default; a section's own signal
    sharpens it. Absent frontmatter ⇒ note. Priority is Trigger > When/If > fence
    > default, because a skill that happens to carry a code block is still a skill
    (design §1, "skill vs snippet").

PROVENANCE IN A NODE-KEYED SIDECAR, NEVER THE BODY (design §4)
    Each doc node carries `{repo, path, commit, blob_sha, generated_at}` in its
    `brief` — which `ingest.mjs` writes to `taxonomy_metadata`, NOT to
    `node_descriptions`. The description (`en`) is the only thing the vector index
    reads; keeping the churning commit/blob fields out of it is what stops the
    corpus re-embedding on every commit (`hidden_fees/04`). `blob_sha` is the
    git-blob hash of the working-tree file (deterministic, no git needed);
    `commit`/`generated_at` come from git history, best-effort.

IDS THROUGH THE ONE GATE (design §5)
    Every id segment routes through `keap_selfmodel_gen.slug_or_die` — the same
    charset the self-model uses, pinned by `test_selfmodel_slug_charset.py`. There
    is no second charset to drift (`hidden_fees/11`). A doc whose title cannot
    slug (leading digit, empty) dies loudly rather than landing at a dead anchor.

COVERAGE IS DATA, NOT A LOG LINE (design §6, and the C1 gap it repeats)
    The run reports, as a machine-readable field: nodes per kind, the services
    covered, and the services MISSED BY NAME. A service in the manifest with no
    `docs/systems/<svc>/` tree is `missed` — never silently absent. "Silence is
    indistinguishable from 'no such capability'" (`hidden_fees/04`); the 91-node
    self-model gap survived a green P-4 precisely because coverage was logged and
    never asserted. The store reads this field and refuses to boot on zero nodes.

python3 stdlib only, except PyYAML (a hard playbook dependency, via the sibling).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

# ── the sibling self-model producer: one slug gate, one estate model ──────────
# Imported by path so this file runs from any cwd (the store shells it out with
# an absolute path; pytest loads it the same way). Everything id-shaped defers to
# it — there is deliberately no second slugifier here.
_SM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keap_selfmodel_gen.py")


def _load_selfmodel():
    spec = importlib.util.spec_from_file_location("keap_selfmodel_gen", _SM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = _load_selfmodel()

DOC_KINDS = ("skill", "hint", "note", "snippet")

# The files a service's doc tree may hold, and the slug PREFIX each contributes to
# a block id — so a "## Authentication" section in README and in SKILLS produce
# distinct ids (`readme-authentication`, `skills-authentication`) rather than
# colliding. A prefix is also what rescues a heading that begins with a digit:
# `## 2fa setup` → `readme-2fa-setup`, whose first char is a letter.
DOC_FILES = ("README.md", "AGENTS.md", "SKILLS.md")

_FENCE_RE = re.compile(r"^```(\w+)?\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FRONTMATTER_RE = re.compile(r"^---\s*$")
_TRIGGER_RE = re.compile(r"^\s*\*\*Trigger:\*\*\s*(.+?)\s*$", re.M)
_CONDITION_RE = re.compile(r"^\s*\*\*(When|If)\b.*", re.M)


# ── frontmatter + section parsing ─────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (file-level `type:` or None, body-with-frontmatter-stripped).

    A leading `---`-fenced block of flat `key: value` scalars — the exact block
    `keap_selfmodel_gen.render_skill_card` emits. Anything else is body verbatim.
    """
    lines = text.splitlines()
    if not lines or not _FRONTMATTER_RE.match(lines[0]):
        return None, text
    ftype = None
    for i in range(1, len(lines)):
        if _FRONTMATTER_RE.match(lines[i]):
            m = re.match(r"^type:\s*(\S+)", "\n".join(lines[1:i]), re.M)
            if m and m.group(1) in DOC_KINDS:
                ftype = m.group(1)
            return ftype, "\n".join(lines[i + 1:])
    return None, text  # unterminated frontmatter → treat whole file as body


def iter_sections(body: str):
    """Yield (title, lines) per heading section, fence-aware.

    A `#`-led line INSIDE a fenced code block is content, not a heading — so a
    shell comment or a markdown sample never splits a section. The preamble
    before the first heading yields with title ''.
    """
    title = ""
    buf: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = _HEADING_RE.match(line) if not in_fence else None
        if m:
            if title or any(s.strip() for s in buf):
                yield title, buf
            title, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if title or any(s.strip() for s in buf):
        yield title, buf


def _first_fence(lines: list[str]) -> tuple[str | None, str | None]:
    """(language, verbatim code) of the FIRST fenced block in a section, or (None, None)."""
    lang = None
    code: list[str] | None = None
    for line in lines:
        m = _FENCE_RE.match(line)
        if m and code is None:
            lang = m.group(1) or ""
            code = []
        elif m and code is not None:
            return (lang or None), "\n".join(code)
        elif code is not None:
            code.append(line)
    return (None, None)


def classify(lines: list[str], default_kind: str) -> dict:
    """Read a section's kind from its block signals (design §2), priority-ordered.

    Trigger > When/If > fenced-code > file default. A skill carrying a code block
    is a skill, not a snippet — the trigger wins, which is the whole "skill vs
    snippet" wall (design §1).
    """
    joined = "\n".join(lines)
    trig = _TRIGGER_RE.search(joined)
    if trig:
        return {"kind": "skill", "trigger": trig.group(1).strip()}
    cond = _CONDITION_RE.search(joined)
    if cond:
        return {"kind": "hint", "condition": cond.group(0).strip()}
    lang, code = _first_fence(lines)
    if code is not None:
        return {"kind": "snippet", "lang": lang, "code": code}
    return {"kind": default_kind}


# ── provenance ────────────────────────────────────────────────────────────────

def git_blob_sha(data: bytes) -> str:
    """The git object id of a blob — `sha1("blob <len>\\0" + data)`. Matches
    `git hash-object` byte-for-byte, but needs no git, no index, no commit: it is
    a pure function of the working-tree bytes, so it is stable and traceable even
    for an untracked or dirty file."""
    h = hashlib.sha1()
    h.update(b"blob " + str(len(data)).encode() + b"\x00")
    h.update(data)
    return h.hexdigest()


def git_commit_of(repo_root: str, rel_path: str) -> tuple[str | None, str | None]:
    """(last commit sha touching rel_path, its committer ISO date), best-effort.

    Untracked / no-git / detached — anything that fails — degrades to (None,
    None). commit+blob together make staleness a query (design §4); their absence
    is honest, not fatal.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "log", "-1", "--format=%H%x00%cI", "--", rel_path],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None, None
        sha, _, date = out.stdout.strip().partition("\x00")
        return (sha or None), (date or None)
    except Exception:
        return None, None


def git_blob_at(repo_root: str, commit: str, rel_path: str) -> str | None:
    """The blob sha git RECORDS for rel_path AT commit, or None if the path is not
    in that commit / anything fails. This is what makes commit+blob a coherent
    pair: it is the hash you would get from `git cat-file blob` walking down from
    `commit`, so it can be compared against the working-tree blob_sha."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--verify", "-q", f"{commit}:{rel_path}"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return out.stdout.strip()
    except Exception:
        return None


def provenance(repo_root: str, abs_path: str, data: bytes) -> dict:
    rel = os.path.relpath(abs_path, repo_root)
    blob_sha = git_blob_sha(data)          # hash of the WORKING-TREE bytes we embed
    commit, generated_at = git_commit_of(repo_root, rel)

    # commit+blob only make staleness a query (§4) if they describe the SAME bytes.
    # `commit` is the last commit touching the path in HEAD history; `blob_sha` is
    # the working-tree file the generator just read. While authoring — or running
    # against a working copy — the file is frequently DIRTY, and then the commit's
    # recorded blob is a DIFFERENT object: pairing them would name a commit from
    # which `git cat-file blob <blob_sha>` is unreachable. Rather than ship that
    # self-contradiction, verify the pair; if the bytes are not in the named commit,
    # the honest provenance is "uncommitted" — drop the commit, keep the blob, and
    # flag it so a consumer sees WHY the commit is absent (dirty) vs. no-git (null).
    dirty = False
    if commit is not None and git_blob_at(repo_root, commit, rel) != blob_sha:
        dirty = True
        commit = None
        generated_at = None

    prov = {
        "repo": os.path.basename(repo_root.rstrip("/")) or "nos",
        "path": rel,
        "commit": commit,
        "blob_sha": blob_sha,
        "generated_at": generated_at,  # the doc's own commit time — the temporal axis §6
    }
    if dirty:
        prov["dirty"] = True
    return prov


# ── build the doc nodes ───────────────────────────────────────────────────────

def _doc_dir(docs_root: str, sslug: str) -> str | None:
    d = sm.DOCS_DIR_ALIASES.get(sslug, sslug)
    p = os.path.join(docs_root, d)
    return p if os.path.isdir(p) else None


def _en_for(kind: str, title: str, body: str, meta: dict) -> str:
    """The embedded description — what a query matches. A snippet's body is its
    verbatim code (byte-for-byte is the point); every other kind is its prose,
    titled so the topic is in the vector."""
    if kind == "snippet":
        lang = meta.get("lang")
        head = f"{title} ({lang})" if lang else title
        return f"{head}\n\n{meta.get('code', '').strip()}".strip()
    prose = body.strip()
    return f"{title}\n\n{prose}".strip() if title else prose


def build_docs(manifest_path: str, docs_root: str, repo_root: str) -> dict:
    """Walk `docs/systems/<svc>/` and return doc nodes grouped by domain, plus the
    coverage claim as data.

    Anchors come from `keap_selfmodel_gen.build_slug_model` — so a doc can only
    hang off a system node the self-model actually placed, and coverage is
    measured against the SAME 63-service estate, not a guess.
    """
    model = sm.build_slug_model(manifest_path, docs_root)
    systems = model["systems"]

    nodes_by_domain: dict[str, list[dict]] = {}
    provenance_by_id: dict[str, dict] = {}
    counts = {k: 0 for k in DOC_KINDS}
    covered: list[str] = []
    missed: list[str] = []
    empty: list[str] = []          # a doc tree EXISTS but produced zero nodes
    docs_ignored: list[str] = []   # <sslug>/<file> prose outside the allowlist
    prov_unresolved = 0            # doc nodes whose commit could not be resolved

    for sid in sorted(systems):
        sv = systems[sid]
        sslug = sv["slug"]
        ddir = _doc_dir(docs_root, sslug)
        if not ddir:
            missed.append(sslug)   # genuinely NO docs/systems/<svc>/ tree
            continue

        # Prose that lives outside the fixed allowlist (RUNBOOK.md, GUIDE.md, a
        # typo'd AGENT.md) contributes zero nodes. Silently dropping it is the fee:
        # authored prose on disk vanishing from the corpus with no signal. Name
        # every unrecognized `.md` so it is REVEALED, not omitted — a consumer can
        # then see the gap is "not parsed", not "does not exist".
        try:
            for entry in sorted(os.listdir(ddir)):
                if entry.endswith(".md") and entry not in DOC_FILES \
                        and os.path.isfile(os.path.join(ddir, entry)):
                    docs_ignored.append(f"{sslug}/{entry}")
        except OSError:
            pass

        anchor = sv["node_id"]                 # nos.<stack>.<system>
        domain = f"{sm.ROOT_ID}.{sv['stack']}"  # the per-stack domain file to merge into
        seen: set[str] = set()
        produced = 0
        # A per-SYSTEM ordinal, not per-file: it must monotonically order every doc
        # child of this system across README → AGENTS → SKILLS. The old per-file
        # reset made README §N, AGENTS §N and SKILLS §N all share 100+N, so a
        # consumer sorting a system's children by `ordinal` (the field's whole
        # purpose) got ties. Start at 100 so doc children still sort AFTER the
        # system's credential (ordinal 0).
        doc_ordinal = 100

        for fname in DOC_FILES:
            fpath = os.path.join(ddir, fname)
            if not os.path.isfile(fpath):
                continue
            data = open(fpath, "rb").read()
            ftype, bodytext = parse_frontmatter(data.decode("utf-8", "replace"))
            default_kind = ftype or "note"
            filebase = sm.slug_or_die(os.path.splitext(fname)[0], "doc filename")
            prov = provenance(repo_root, fpath, data)

            for title, lines in iter_sections(bodytext):
                body = "\n".join(lines).strip()
                meta = classify(lines, default_kind)
                if meta["kind"] == "snippet":
                    if not (meta.get("code") or "").strip():
                        continue
                elif not body:
                    continue

                stub = title if title else "body"
                base_slug = sm.slug_or_die(f"{filebase}-{stub}", "doc block")
                # Two sections that share heading TEXT (a second `## Notes`, a
                # repeated `### Example`/`### Parameters` — routine when one file
                # documents several skills or endpoints) would slug identically.
                # Raising here aborted keap_docs_gen, which fails the ENTIRE organ
                # boot (runDocs throws), not just the one node. The schema asks
                # strangers to "write the markdown they would write anyway", so a
                # repeat is expected input, not corruption. Namespace the id by the
                # occurrence ordinal instead: the FIRST keeps the clean slug (stable
                # ids for existing docs), each subsequent one gets `-2`, `-3`, …
                # deterministically by document order — legitimate repeats coexist.
                block_slug = base_slug
                dup = 2
                while block_slug in seen:
                    block_slug = f"{base_slug}-{dup}"
                    dup += 1
                seen.add(block_slug)

                node_id = f"{anchor}.{block_slug}"
                brief = {
                    "doc": {
                        "kind": meta["kind"],
                        "source": fname,
                        "provenance": prov,
                    }
                }
                if meta.get("trigger"):
                    brief["doc"]["trigger"] = meta["trigger"]
                if meta.get("condition"):
                    brief["doc"]["condition"] = meta["condition"]
                if meta.get("lang"):
                    brief["doc"]["lang"] = meta["lang"]

                node = {
                    "id": node_id,
                    "level": node_id.count("."),
                    "kind": "ext",
                    "parentId": anchor,
                    "name": title or filebase,
                    "zone": "free",
                    # Monotonic across the whole system (see doc_ordinal above), so
                    # the field actually sequences README-then-AGENTS-then-SKILLS.
                    "ordinal": doc_ordinal,
                    "en": _en_for(meta["kind"], title, body, meta),
                    "brief": brief["doc"],
                }
                nodes_by_domain.setdefault(domain, []).append(node)
                provenance_by_id[node_id] = prov
                counts[meta["kind"]] += 1
                produced += 1
                doc_ordinal += 1
                if prov.get("commit") is None:
                    prov_unresolved += 1

        if produced:
            covered.append(sslug)
        else:
            # A tree that yielded nothing is still MISSED (no usable docs), but it
            # is NOT the same as "no tree at all" — record it as `empty` too so the
            # two causes are distinguishable instead of collapsing to one value.
            missed.append(sslug)
            empty.append(sslug)

    total = counts["skill"] + counts["hint"] + counts["note"] + counts["snippet"]
    return {
        "nodes_by_domain": nodes_by_domain,
        "provenance_by_id": provenance_by_id,
        "coverage": {
            "doc_nodes": total,
            "nodes_by_kind": counts,
            "services_total": len(systems),
            "services_covered": sorted(covered),
            "services_missed": sorted(missed),
            # `empty` ⊆ `missed`: services WITH a docs tree that produced no node.
            "services_empty": sorted(empty),
            # Prose on disk outside the README/AGENTS/SKILLS allowlist, by name.
            "docs_ignored": sorted(docs_ignored),
            # Doc nodes whose commit is null (dirty working tree, or read outside a
            # git repo) — a resolvable pair is a query, an unresolvable one is a
            # COUNTED absence, never a silent one.
            "provenance_unresolved": prov_unresolved,
            "domains_merged": sorted(nodes_by_domain),
        },
    }


# ── merge into the self-model's canonical tree ────────────────────────────────

def merge_into_canonical(canonical_dir: str, nodes_by_domain: dict, result: dict) -> None:
    """Append doc nodes into each per-stack domain file the self-model wrote.

    One writer per domain, one ingest pass: the doc nodes join the system +
    credential nodes already in `nos/<domain>.json`, so `ingest.mjs`'s
    domain-scoped wipe-then-insert carries all three together. A missing target
    file is a hard error — it means the self-model did not run first, and a doc
    node with no parent system would ingest to a dangling anchor.
    """
    for domain in sorted(nodes_by_domain):
        rel = os.path.join(sm.ROOT_ID, f"{domain}.json")
        path = os.path.join(canonical_dir, rel)
        if not os.path.isfile(path):
            raise SystemExit(
                f"keap_docs_gen: canonical domain file {rel!r} is absent under {canonical_dir}. "
                "Run keap_selfmodel_gen (--schema slug) FIRST — doc nodes append to its tree, "
                "they do not create one."
            )
        doc = json.loads(open(path, encoding="utf-8").read())
        existing = {n["id"] for n in doc.get("nodes", [])}
        for node in nodes_by_domain[domain]:
            if node["id"] in existing:
                raise SystemExit(
                    f"keap_docs_gen: doc node {node['id']!r} collides with a self-model node "
                    "in the same domain. A doc block must not shadow a system or credential id."
                )
        merged = doc.get("nodes", []) + nodes_by_domain[domain]
        merged.sort(key=lambda n: n["id"])
        doc["nodes"] = merged
        body = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
        sm._write_if_changed(path, body, result)


def generate(canonical_dir: str, docs: dict) -> dict:
    result = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}
    merge_into_canonical(canonical_dir, docs["nodes_by_domain"], result)
    return result


# ── cli ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Merge docs/systems prose into the self-model canonical tree as typed nodes.")
    ap.add_argument("--manifest", required=True, help="path to state/manifest.yml")
    ap.add_argument("--docs-root", default="docs/systems", help="root holding <svc>/{README,AGENTS,SKILLS}.md")
    ap.add_argument("--canonical", required=True,
                    help="the self-model's canonical/ dir (already written by keap_selfmodel_gen --schema slug); merged in place")
    ap.add_argument("--repo-root", default="", help="git repo root for provenance (default: derived from --docs-root)")
    args = ap.parse_args(argv)

    repo_root = args.repo_root or os.path.abspath(os.path.join(args.docs_root, os.pardir, os.pardir))
    docs = build_docs(args.manifest, args.docs_root, repo_root)
    result = generate(args.canonical, docs)
    out = {**result, **docs["coverage"]}
    print(json.dumps(out, sort_keys=True))

    # Zero doc nodes is a loud failure, not a quiet success: an empty docs tree is
    # the "corpus exhausted" lie the store refuses to boot on. Absence is not
    # emptiness — if the walk found nothing, the caller must know.
    if docs["coverage"]["doc_nodes"] == 0:
        print("keap_docs_gen: produced ZERO doc nodes — nothing to ingest.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
