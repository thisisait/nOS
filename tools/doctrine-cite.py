#!/usr/bin/env python3
"""Resolve every doctrine citation in the estate — or say exactly which do not.

WHAT THIS IS
------------
The constitution exists (CLAUDE.md, docs/idea/*, docs/doctrine/*,
files/anatomy/docs/*, the judge-sets comment blocks) and the code cites it
constantly — measured 2026-08-06: 694 `§`-citations across 130 files under
{files,tools,state,tasks,roles,main.yml}, 72 of them a bare `§5` with no
document qualifier, plus DECISION/Constraint/M/A/SEC/REM shapes on top.
Nothing verified a single one. A citation is a claim that a paragraph exists
and says what the citing code assumes; this tool makes each one resolvable —
`doctrine:<doc>#<section>` — or reports it as a finding.

It is the same refusal tools/anatomy-graph-gen.py makes for a dangling
`upstream:`: an identifier that resolves to nothing is a graph lying at
birth. Here the graph is the citation network.

RESOLUTION, per shape (measured inventory, not assumed):
  §N / §N.M / §Na / §N(a)   a section heading in a corpus doc. The document
                            comes from (in order): a doc path on the SAME
                            LINE; the citing file's HEADER declaration (its
                            first ~50 lines naming a corpus doc — the
                            judge-sets.yml "Contract: docs/idea/…" shape);
                            the citing file itself when it IS a corpus doc.
                            A bare § with none of those is UNQUALIFIED —
                            reported, never guessed.
  DECISION 2b               `> ### DECISION 2b — …` headings (loop contract)
  Constraint A..H           the §8 CONSTRAINT COMPLIANCE table rows
  M1..M7                    the §0 measured-claims table rows
  REM-nnn                   ids in docs/llm/security/remediation-queue.json
  A6..A19 (epic ids)        CLAUDE.md bold/parenthetical epic registry
  SEC-nn                    corpus prose registry (defined nowhere as a
                            heading — reported as registry-resolved when a
                            corpus doc carries the id, which is weaker and
                            SAYS so)

FINDING CLASSES (the two the operator asked for, split further where the
split is measurable):
  resolved            doc + section both exist
  moved               the named doc lacks the section, but a doc of the same
                      basename under docs/archive/ carries it (several docs
                      were archived 2026-08-02)
  wrong               qualified, doc exists, section absent everywhere
  missing-doc         qualified, the named doc does not exist at all
  unqualified         bare citation with no resolution path — not an error,
                      an address that is not yet an address

Usage:
    python3 tools/doctrine-cite.py            # human report, counts + worst offenders
    python3 tools/doctrine-cite.py --json     # full citation dump (stdout)

No repo state is written: the committed artifact of this layer is the
doctrine nodes in state/anatomy-graph.json (anatomy-graph-gen imports this
module), and the gate is tests/anatomy/test_doctrine_citations_resolve.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Where citations are harvested FROM. tests/ is included deliberately — a
#: gate's docstring citing §2.4 is exactly the governed-by edge the SERE UI
#: wants to highlight. docs/ is the corpus, not a harvest root; a doc citing
#: a doc is corpus-internal cross-reference, out of scope here.
HARVEST_ROOTS = ("files", "tools", "state", "tasks", "roles", "tests", "main.yml")
HARVEST_SUFFIXES = {".py", ".yml", ".yaml", ".sh", ".php", ".ts", ".svelte", ".j2",
                    ".md", ".cfg", ".neon", ".sql", ".js", ".latte", ".json"}
SKIP_DIRS = {"node_modules", ".svelte-kit", "build", "dist", "vendor",
             "__pycache__", ".git"}
#: Corpus docs living under a harvest root (files/anatomy/docs) are corpus,
#: not citing code — harvesting them would count the law citing itself.
#: GENERATED artifacts are an ECHO, never an authored claim. The contract
#: exports lift Bone's and Wing's docblocks verbatim into OpenAPI descriptions,
#: so every `§` a source file already contributes gets counted a SECOND time the
#: moment someone regenerates. Measured 2026-08-10: regenerating the three
#: contracts after two features had landed pushed the unqualified count from 124
#: to 127 — three citations nobody wrote, in a file nobody edits, failing a
#: ceiling whose whole purpose is to notice new claims. The source citations
#: themselves are still harvested from the source, which is where they can
#: actually be fixed.
SKIP_FILES_PREFIX = ("files/anatomy/docs/", "files/anatomy/cortex/docs/",
                     "files/anatomy/cortex/README.md",
                     "files/anatomy/skills/contracts/")

#: This tool and its gate QUOTE citations as data — KNOWN_FINDINGS carries
#: the phantom REM-088 verbatim, docstrings carry §-examples. Harvesting
#: them turns every quoted finding into a live finding of itself, forever.
SELF_REFERENTIAL = ("tools/doctrine-cite.py",
                    "tests/anatomy/test_doctrine_citations_resolve.py")

#: The constitution corpus. docs/** includes idea, doctrine, archive,
#: compliance, hidden_fees — archive membership is what powers the `moved`
#: class, so it must stay in. The cortex tree carries its OWN spec corpus
#: (files/anatomy/cortex/docs/specs/*) — first run without it misclassified
#: every cortex-validate.md §-citation as `wrong` via a header doc it never
#: meant.
CORPUS_GLOBS = ("CLAUDE.md", "docs/**/*.md", "files/anatomy/docs/*.md",
                "files/anatomy/cortex/docs/**/*.md", "files/anatomy/cortex/README.md")

REMEDIATION_QUEUE = REPO / "docs" / "llm" / "security" / "remediation-queue.json"

# ── citation shapes ────────────────────────────────────────────────────────

RE_SECTION = re.compile(r"§\s?([0-9]+(?:\.[0-9a-z]+)*(?:\([a-z]\)|[a-z])?)")
RE_DOC_PATH = re.compile(r"((?:docs|files/anatomy/docs)/[A-Za-z0-9_./-]+\.md)")
RE_DECISION = re.compile(r"DECISION\s+([0-9]+[a-z]?)\b")
RE_CONSTRAINT = re.compile(r"[Cc]onstraint\s+([A-H])\b")
RE_M = re.compile(r"\b(M[1-9])\b")
RE_REM = re.compile(r"\b(REM-[0-9]{3})\b")

#: Repos this estate cites but does not contain. Their `docs/` paths are
#: shaped exactly like ours, so without this table they resolve against this
#: checkout and report as permanently missing. Adding one is a statement that
#: we depend on someone else's written word — keep the list short and name
#: the upstream, so a reader can go and check it.
FOREIGN_REPOS = {
    "KEAP": "thisisait/nos-keap",
}

#: Ids that were CITED but never persisted. `docs/llm/security/2026-04-08-vuln-report.md`
#: records the gap: REM-088…092 appear in `scan-state.json` notes while the queue
#: runs REM-087 -> REM-093. Four were re-persisted at fresh ids (111/113/114);
#: REM-088 was left, and its debt was satisfied structurally instead (the
#: postgresql pin advanced 16.13 -> 16.14, filed COVERED/CLEAN, no item needed).
#:
#: They are declared rather than silenced because you cannot document a phantom
#: without writing its id, and the first attempt at that documentation simply
#: moved the same three findings four lines up the file. A declared phantom is
#: a fact with a citation; an undeclared one is a lookup that fails forever.
PHANTOM_REM_IDS = {
    "REM-088": "never persisted; postgresql pin advanced to 16.14, filed COVERED/CLEAN",
}
RE_SEC = re.compile(r"\b(SEC-[0-9]{2})\b")
#: Epic ids only where the surrounding text says anatomy/epic — a bare
#: "A9" in code matches container names and hex; the measured live shapes
#: are "A9 notification", "(A17, 2026-05-20)", "Anatomy A14", "per A19".
RE_EPIC = re.compile(r"\b(A[0-9]{1,2})\b(?=[ ,)]|$)")


def _norm_section(s: str) -> str:
    """§2(a) → 2a; §2.c → 2c; trailing dot stripped. The citation and the
    heading meet on one spelling or they do not meet."""
    s = s.replace("(", "").replace(")", "").rstrip(".")
    return re.sub(r"\.([a-z])$", r"\1", s)


# ── corpus index ───────────────────────────────────────────────────────────


@dataclass
class DocIndex:
    path: str
    sections: dict[str, str] = field(default_factory=dict)   # id -> heading text
    decisions: dict[str, str] = field(default_factory=dict)
    m_ids: set[str] = field(default_factory=set)
    constraints: set[str] = field(default_factory=set)


#: `2c` with no dot is a real heading shape — blank-uninstall-managed-
#: resources.md `### 2c. ROOT of the uid orphans…`, cited by uid.ts:10.
RE_HEAD_NUM = re.compile(r"^>?\s*#{1,6}\s+\(?([0-9]+[a-z]?(?:\.[0-9a-z]+)*)\)?[\.\s:]+(.*)")
RE_HEAD_LETTER = re.compile(r"^>?\s*#{1,6}\s+\(([a-z])\)\s*(.*)")
RE_HEAD_DECISION = re.compile(r"^>?\s*#{1,6}\s+DECISION\s+([0-9]+[a-z]?)\s*[—-]?\s*(.*)")
RE_ROW_M = re.compile(r"^\|\s*(M[1-9])\s*\|\s*([^|]*)")
RE_ROW_CONSTRAINT = re.compile(r"^\|\s*\*\*([A-H])\*\*\s*\|\s*([^|]*)")
#: A bold-titled top-level numbered list item under a numbered heading is an
#: address in this estate's citation practice: contract `## 9` has no 9.x
#: subheadings, yet budget.py cites §9.3 and means item 3 of that list
#: ("max_attempts … Guesses"). Bold-titled ONLY — indexing every numbered
#: list would mint addresses nobody intended.
RE_ITEM_BOLD = re.compile(r"^([0-9]+)\.\s+\*\*(.+?)\*\*")


def index_doc(path: Path) -> DocIndex:
    rel = str(path.relative_to(REPO))
    idx = DocIndex(path=rel)
    current_major: str | None = None
    current_full: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := RE_HEAD_DECISION.match(line):
            idx.decisions[m.group(1)] = m.group(2).strip()
            continue
        if m := RE_HEAD_NUM.match(line):
            sec = _norm_section(m.group(1))
            idx.sections[sec] = m.group(2).strip()
            current_major = sec.split(".")[0]
            current_full = sec
            continue
        if (m := RE_HEAD_LETTER.match(line)) and current_major is not None:
            idx.sections[f"{current_major}{m.group(1)}"] = m.group(2).strip()
            continue
        if m := RE_ROW_M.match(line):
            idx.m_ids.add(m.group(1))
            idx.sections[m.group(1)] = m.group(2).strip()
            continue
        if m := RE_ROW_CONSTRAINT.match(line):
            idx.constraints.add(m.group(1))
            idx.sections[f"constraint-{m.group(1)}"] = m.group(2).strip()
            continue
        if (m := RE_ITEM_BOLD.match(line)) and current_full is not None \
                and "." not in current_full:
            # Only under a TOP-LEVEL heading: an item under "### 5.2" must not
            # mint a phantom "5.1" address.
            idx.sections.setdefault(f"{current_full}.{m.group(1)}", m.group(2).strip())
    return idx


def build_corpus() -> dict[str, DocIndex]:
    corpus: dict[str, DocIndex] = {}
    for pattern in CORPUS_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            if path.is_file():
                corpus[str(path.relative_to(REPO))] = index_doc(path)
    return corpus


def epic_registry() -> set[str]:
    """A-epic ids CLAUDE.md actually declares (bold lead or parenthetical
    with an anatomy/date context), not every A<n> substring."""
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    ids: set[str] = set()
    ids.update(re.findall(r"\*\*(A[0-9]{1,2})[ .]", text))
    ids.update(re.findall(r"[Aa]natomy\s+(A[0-9]{1,2})\b", text))
    ids.update(re.findall(r"\((A[0-9]{1,2})[,)]", text))
    return ids


def rem_registry() -> set[str]:
    if not REMEDIATION_QUEUE.exists():
        return set()
    doc = json.loads(REMEDIATION_QUEUE.read_text(encoding="utf-8"))
    items = doc.get("items") or doc.get("queue") or doc
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            v = o.get("id")
            if isinstance(v, str) and v.startswith("REM-"):
                out.add(v)
            for vv in o.values():
                walk(vv)
        elif isinstance(o, list):
            for vv in o:
                walk(vv)
    walk(items)
    return out


# ── harvest ────────────────────────────────────────────────────────────────


@dataclass
class Citation:
    file: str
    line: int
    shape: str          # section|decision|constraint|m|rem|sec|epic
    key: str            # normalised id, e.g. "2.4", "DECISION 2b", "REM-118"
    doc: str | None     # resolved corpus doc, when any
    how: str            # sameline|header|self|registry|none
    status: str = ""    # resolved|moved|wrong|missing-doc|unqualified|unknown-id|phantom
    heading: str = ""   # the target heading text, when resolved


def _iter_harvest_files():
    for root in HARVEST_ROOTS:
        p = REPO / root
        if p.is_file():
            yield p
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file() or f.suffix not in HARVEST_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            rel = str(f.relative_to(REPO))
            if rel.startswith(SKIP_FILES_PREFIX) or rel in SELF_REFERENTIAL:
                continue
            yield f


#: Sub-trees carrying their own corpus cite docs by TREE-relative path —
#: cortex-lang.ts:6 names "docs/specs/cortex-validate.md (this repo…)" and
#: means files/anatomy/cortex/docs/specs/. First run misattributed all of
#: those to the nOS doc named second on the same line.
SUBTREE_ROOTS = ("files/anatomy/cortex/",)


def _corpus_doc(raw: str, citing: str, corpus: dict[str, DocIndex]) -> str | None:
    if raw in corpus:
        return raw
    # The expansion applies to EVERY citing file, not only in-subtree ones —
    # roles/pazny.keap cites the cortex tree's docs/specs/deploy-knowledge-
    # mount-split.md from outside it, and with one subtree root the
    # expansion is unambiguous. `citing` stays in the signature for the day
    # a second subtree root makes it load-bearing.
    _ = citing
    for root in SUBTREE_ROOTS:
        if root + raw in corpus:
            return root + raw
    return None


def _header_docs(lines: list[str], citing: str, corpus: dict[str, DocIndex]) -> list[str]:
    """The citing file's declared authorities: every corpus-doc path named in
    its first 50 lines, in order of appearance. A LIST, not one winner —
    test_loop_plugin_is_thin.py cites the parent design at line 3 and the
    contract further down, and its bare §3.1 belongs to the second. A bare
    citation resolves against the first declared authority that HAS the
    section; that is still the file's own declaration, never a corpus-wide
    guess."""
    out: list[str] = []
    for line in lines[:50]:
        for m in RE_DOC_PATH.finditer(line):
            hit = _corpus_doc(m.group(1), citing, corpus)
            if hit and hit not in out:
                out.append(hit)
    return out


def harvest(corpus: dict[str, DocIndex]) -> list[Citation]:
    out: list[Citation] = []
    for f in _iter_harvest_files():
        rel = str(f.relative_to(REPO))
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "§" not in text and not any(
                t in text for t in ("DECISION", "onstraint", "REM-", "SEC-")):
            # cheap pre-filter; M/epic shapes only ever co-occur with these
            # in the measured corpus, and a full regex pass over every file
            # would make the gate the slowest test in the suite
            if not RE_M.search(text) and not RE_EPIC.search(text):
                continue
        out.extend(harvest_file(f, rel, corpus))
    return out


def harvest_file(f: Path, rel: str, corpus: dict[str, DocIndex]) -> list[Citation]:
    """Citations of ONE file — the anatomy graph generator calls this for the
    node-source manifests so governed_by edges come from the same resolver
    the gate runs, never a second implementation."""
    out: list[Citation] = []
    text = f.read_text(encoding="utf-8", errors="replace")
    if text:
        lines = text.splitlines()
        headers = _header_docs(lines, rel, corpus)
        header = headers[0] if headers else None
        self_doc = rel if rel in corpus else None
        # Tier 2 authorities: corpus docs named ANYWHERE in the file. Still
        # the file's own declaration — test_loop_plugin_is_thin.py names the
        # contract at line 305 and its bare §3.1 belongs to it; fs-sync.ts
        # names cortex-corpus-parallel.md at line 59. Used only when the
        # first-50-lines authorities lack the section; never corpus-wide.
        filedocs: list[str] = []
        for line in lines:
            for m in RE_DOC_PATH.finditer(line):
                hit = _corpus_doc(m.group(1), rel, corpus)
                if hit and hit not in filedocs:
                    filedocs.append(hit)
        for i, line in enumerate(lines, 1):
            sameline = next((hit for m in RE_DOC_PATH.finditer(line)
                             if (hit := _corpus_doc(m.group(1), rel, corpus))), None)
            # A doc path named on the line but absent from the corpus is a
            # MISSING DOC — recorded, not silently ignored: the devlog gate
            # cited a docs/plans/ design file whose home is now
            # docs/archive/agentic-upgrade-adjustments-design.md §5.4
            # (the 2026-08-02 archive sweep).
            sameline_missing = next(
                (m.group(1) for m in RE_DOC_PATH.finditer(line)
                 if _corpus_doc(m.group(1), rel, corpus) is None), None)
            for m in RE_SECTION.finditer(line):
                key = _norm_section(m.group(1))
                # An external standard is not the constitution: "RFC 6749
                # §4.4.3" resolves against the IETF, not this repo. Named as
                # its own shape so the corpus classes stay clean.
                if re.search(r"RFC\s*\d+\s*$", line[:m.start()]):
                    out.append(Citation(rel, i, "external", f"RFC {key}",
                                        None, "external", status="resolved-external"))
                    continue

                # A citation into a repo we do not own is not a broken link —
                # it is a different KIND of claim, and this estate already has
                # a doctrine for it (docs/doctrine/foreign-properties.md: "a
                # gotcha that is someone else's property is doctrine"). Two
                # such cites in roles/pazny.keap read as `missing-doc` for
                # months because KEAP's `docs/specs/*` look exactly like ours
                # and resolve against this checkout, where they will never be.
                # Qualify them and they classify honestly; leave them and the
                # findings list carries two entries nobody can ever close.
                foreign = next((name for name, path in FOREIGN_REPOS.items()
                                if re.search(rf"\b{name}\s+\S*$", line[:m.start()])
                                or re.search(rf"\b{name}\s+docs/", line)), None)
                if foreign:
                    out.append(Citation(rel, i, "external", f"{foreign} §{key}",
                                        FOREIGN_REPOS[foreign], "foreign-repo",
                                        status="resolved-external"))
                    continue

                def _has(d: str) -> bool:
                    return key in corpus[d].sections or key in corpus[d].decisions

                if sameline:
                    doc, how = sameline, "sameline"
                elif sameline_missing:
                    # the citation NAMES its doc; the doc is gone. Carry the
                    # raw path so resolve() can try the archive by basename.
                    out.append(Citation(rel, i, "section", key,
                                        sameline_missing, "sameline-missing"))
                    continue
                elif headers and any(_has(h) for h in headers):
                    doc = next(h for h in headers if _has(h))
                    how = "header"
                elif any(_has(d) for d in filedocs):
                    doc = next(d for d in filedocs if _has(d))
                    how = "file-doc"
                elif header:
                    # reported against the file's PRIMARY declared contract —
                    # a genuinely-wrong citation needs an owner to be a finding
                    doc, how = header, "header"
                elif self_doc:
                    doc, how = self_doc, "self"
                else:
                    doc, how = None, "none"
                out.append(Citation(rel, i, "section", key, doc, how))
            for m in RE_DECISION.finditer(line):
                out.append(Citation(rel, i, "decision", f"DECISION {m.group(1)}",
                                    None, "registry"))
            for m in RE_CONSTRAINT.finditer(line):
                out.append(Citation(rel, i, "constraint", m.group(1), None, "registry"))
            # M1..M9 only in files whose declared contract defines M-ids —
            # first run measured 2038 raw \bM[1-9]\b matches, and the bulk
            # were Apple Silicon chip names ("M1+", "M2 Macs"). An id shape
            # that collides with a product line resolves only where the
            # citing file has opted into the namespace.
            if any(corpus[h].m_ids for h in headers):
                for m in RE_M.finditer(line):
                    out.append(Citation(rel, i, "m", m.group(1), None, "registry"))
            for m in RE_REM.finditer(line):
                out.append(Citation(rel, i, "rem", m.group(1), None, "registry"))
            for m in RE_SEC.finditer(line):
                out.append(Citation(rel, i, "sec", m.group(1), None, "registry"))
    return out


# ── resolve ────────────────────────────────────────────────────────────────


def resolve(citations: list[Citation], corpus: dict[str, DocIndex]) -> None:
    rems = rem_registry()
    epics = epic_registry()
    decision_docs = {d for d, idx in corpus.items() if idx.decisions}
    m_docs = {d for d, idx in corpus.items() if idx.m_ids}
    constraint_docs = {d for d, idx in corpus.items() if idx.constraints}
    sec_docs = set()
    for d in corpus:
        try:
            if RE_SEC.search((REPO / d).read_text(encoding="utf-8", errors="replace")):
                sec_docs.add(d)
        except OSError:
            continue  # synthetic corpus in unit tests has no files on disk
    def archived_holder(basename: str, sec: str) -> str | None:
        """A same-basename corpus doc that carries the section — the doc
        MOVED, and both destinations are real: docs/archive/ (2026-08-02
        sweep) and files/anatomy/docs/ (anatomy A1 moved framework-plan.md
        et al. there on 2026-05-03; state/schema/*.json still cite the old
        docs/ path). Same basename is required: a bare §5 exists in half the
        corpus and matching on the section alone would 'resolve' anything."""
        candidates = sorted(
            d for d, idx in corpus.items()
            if Path(d).name == basename
            and (sec in idx.sections or sec in idx.decisions))
        archived = [d for d in candidates if d.startswith("docs/archive/")]
        return (archived or candidates or [None])[0]

    for c in citations:
        if c.status:
            continue  # pre-classified at harvest (resolved-external)
        if c.shape == "section":
            if c.doc is None:
                c.status = "unqualified"
                continue
            idx = corpus.get(c.doc)
            if idx is None:
                # the named doc does not exist — the archive-by-basename
                # check below decides between `moved` and `missing-doc`
                holder = archived_holder(Path(c.doc).name, c.key)
                if holder:
                    c.status, c.doc, c.how = "moved", holder, "archive"
                    c.heading = corpus[holder].sections.get(
                        c.key) or corpus[holder].decisions.get(c.key, "")
                else:
                    c.status = "missing-doc"
                continue
            if c.key in idx.sections:
                c.status = "resolved"
                c.heading = idx.sections[c.key]
            elif c.key in idx.decisions:
                # "§5a" cites DECISION 5a — the contract's own header line
                # spells it "§5 (DECISION 5, 5a)", so the decision heading IS
                # the paragraph the citation means.
                c.status = "resolved"
                c.heading = idx.decisions[c.key]
            else:
                holder = archived_holder(Path(c.doc).name, c.key)
                if holder:
                    c.status, c.doc, c.how = "moved", holder, "archive"
                    c.heading = corpus[holder].sections[c.key]
                else:
                    c.status = "wrong"
        elif c.shape == "decision":
            key = c.key.split()[1]
            holder = next((d for d in sorted(decision_docs)
                           if key in corpus[d].decisions), None)
            if holder:
                c.status, c.doc = "resolved", holder
                c.heading = corpus[holder].decisions[key]
            else:
                c.status = "unknown-id"
        elif c.shape == "constraint":
            holder = next((d for d in sorted(constraint_docs)
                           if c.key in corpus[d].constraints), None)
            if holder:
                c.status, c.doc = "resolved", holder
                c.heading = corpus[holder].sections.get(f"constraint-{c.key}", "")
            else:
                c.status = "unknown-id"
        elif c.shape == "m":
            holder = next((d for d in sorted(m_docs) if c.key in corpus[d].m_ids), None)
            if holder:
                c.status, c.doc = "resolved", holder
                c.heading = corpus[holder].sections.get(c.key, "")
            else:
                c.status = "unknown-id"
        elif c.shape == "rem":
            if c.key in rems:
                c.status, c.doc = "resolved", "docs/llm/security/remediation-queue.json"
            elif c.key in PHANTOM_REM_IDS:
                # Declared absent, with a reason. Its own class so the tally
                # still SHOWS it — a phantom folded into `resolved` would be
                # the estate's oldest defect (a marker written by the thing
                # being measured) in a new place.
                c.status, c.doc = "phantom", PHANTOM_REM_IDS[c.key]
            else:
                c.status, c.doc = "unknown-id", None
        elif c.shape == "sec":
            holder = next(iter(sorted(sec_docs)), None)
            c.status = "resolved" if holder else "unknown-id"
            c.doc = holder
        elif c.shape == "epic":
            c.status = "resolved" if c.key in epics else "unknown-id"
            c.doc = "CLAUDE.md" if c.status == "resolved" else None


def run() -> tuple[list[Citation], dict[str, DocIndex]]:
    corpus = build_corpus()
    citations = harvest(corpus)
    resolve(citations, corpus)
    return citations, corpus


# ── report ─────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="resolve doctrine citations")
    ap.add_argument("--json", action="store_true", help="dump every citation")
    args = ap.parse_args()
    citations, corpus = run()

    if args.json:
        json.dump([asdict(c) for c in citations], sys.stdout, indent=1)
        return 0

    by_status: dict[str, int] = {}
    by_shape: dict[str, dict[str, int]] = {}
    for c in citations:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        by_shape.setdefault(c.shape, {})
        by_shape[c.shape][c.status] = by_shape[c.shape].get(c.status, 0) + 1

    print(f"corpus: {len(corpus)} docs indexed; "
          f"{sum(len(i.sections) for i in corpus.values())} addressable sections")
    print(f"citations: {len(citations)} total")
    for shape in sorted(by_shape):
        print(f"  {shape:11s} " + "  ".join(
            f"{k}={v}" for k, v in sorted(by_shape[shape].items())))
    print("classes: " + "  ".join(f"{k}={v}" for k, v in sorted(by_status.items())))

    findings = [c for c in citations if c.status in ("wrong", "missing-doc",
                                                     "moved", "unknown-id")]
    if findings:
        print(f"\nfindings ({len(findings)}):")
        for c in findings[:60]:
            print(f"  {c.status:11s} {c.file}:{c.line}  {c.shape} {c.key}"
                  + (f"  ({c.doc}, via {c.how})" if c.doc else ""))
        if len(findings) > 60:
            print(f"  … {len(findings) - 60} more (--json for all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
