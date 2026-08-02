# Plan — repoint the 3 dead `agent-operable-nos.md` links + gate the roadmap

Status: PLAN (not implemented)
Branch: `feat/v0.7-overnight`
Item: `v0.7 / docs / archive-links-to-nonexistent-agent-operable-nos`
Author context: nOS, AIT. Docs-only fix; one new anatomy gate; no live mutation.

---

## 1. Problem / why

`docs/agent-operable-nos.md` was **deleted** in commit `1ce3e33f`
(2026-05-20, *"remove superseded agent-operable-nos.md (Czech, replaced by
A14)"*). It was a 2026-04-26 Czech strategy doc proposing an
Eye/Ear/Brain/Spine/Hand anatomy extension. The deletion commit explicitly
states it was superseded by the A8 conductor → A14 AgentKit runtime
(`docs/ait-runtime-architecture.md`), and that it violated the post-rebrand
**English-only** doctrine. Its references in `main.yml`, `roles/pazny.linux.apt`
and `docs/anatomy-runtime-flow.md` were updated at deletion time — but the commit
message says: *"roadmap-2026q2.md historical-section refs left intact
(archaeology)."*

That decision left **three** live references to the dead file, all in
`docs/roadmap-2026q2.md` (the file lives at `docs/` root, so a **bare** link
resolves with base = `docs/`):

| Line | Form | Resolves to | Verdict |
|------|------|-------------|---------|
| 199 | `[`` `docs/agent-operable-nos.md` `` ``](agent-operable-nos.md)` | `docs/agent-operable-nos.md` | **404** — a clickable markdown link under a *"Reference docs (read these before starting any track)"* heading. The worst of the three: it actively tells a reader (human or agent) to open a file that does not exist. |
| 756 | `### Telemetry expansion (deferred from `` `agent-operable-nos.md` ``)` | n/a (inline code span, not a link) | Stale **prose** mention. Not a 404, but names a doc the reader cannot find. |
| 1264 | `referenced in `` `agent-operable-nos.md` ``, holds for Q3` | n/a (inline code span, not a link) | Same — stale prose mention in the Appendix stretch-goals. |

Why it matters now (v0.7 cleanup): the line-199 link is in the **entry-point
reference list** a reader is told to read *before starting any track*. nOS is
moving toward agent-operable docs (Conductor reads roadmaps); a dead link in the
canonical "read these first" block is a literal dead end for both an operator
clicking it in the GitHub UI / a local markdown renderer **and** for an agent
crawling the doc graph. The existing `test_framework_docs_links.py` gate already
exists *precisely* to kill this class of breakage (it pins the anatomy-A1 doc
relocations, the `docs/archive/` `../`-prefix fix, and the integration-map fix)
— but it does **not yet cover `roadmap-2026q2.md`**, so this dead link slipped
through. This is a `verify-ok`-shaped item only in that the *prose* is harmless;
the *link* is a genuine 404 that must be fixed AND gated so it cannot regress.

**Honest scope note.** This is a pure documentation correction. There is no live
system, no role, no playbook behaviour involved. The "fix" is three text edits;
the load-bearing deliverable per the overnight rules ("if you cannot gate it, it
is a plan not a fix") is the **anatomy gate** that pins the roadmap's relative
`.md` links to resolve on disk — reusing the existing
`test_framework_docs_links.py` machinery verbatim.

---

## 2. Exact files / roles to touch

| File | Change |
|------|--------|
| `docs/roadmap-2026q2.md` | **L199** — repoint the link target from `agent-operable-nos.md` to the live successor `ait-runtime-architecture.md`, and rewrite the link text + descriptor so it no longer claims the dead doc exists. **L756** — replace the `deferred from \`agent-operable-nos.md\`` prose with `deferred from the pre-A14 agent-operability vision (superseded by \`ait-runtime-architecture.md\`)`. **L1264** — replace `referenced in \`agent-operable-nos.md\`` with `referenced in the pre-A14 agent-operability vision (now \`ait-runtime-architecture.md\`)`. |
| `tests/anatomy/test_framework_docs_links.py` | **ADD** one test `test_roadmap_relative_md_links_resolve()` (mirrors the existing `test_integration_map_relative_md_links_resolve()` / `test_archive_relative_md_links_resolve()` exactly), plus a small module-level WHY comment block in the same style as the two 2026-06-14 blocks already there. Reuses the existing `_MD_LINK` regex and on-disk resolution. |

No other file references the dead doc — confirmed by
`grep -rn "agent-operable-nos" .` returning **only** those three roadmap lines
(plus this plan and the deletion commit in git history, which are not tracked
content links).

### The precise edits to `docs/roadmap-2026q2.md`

**L199 (the actual 404 — the only behavioural fix):**

```diff
-- [`docs/agent-operable-nos.md`](agent-operable-nos.md) — strategic vision (Spine, Eye, Ear, Hand anatomy extensions)
++ [`docs/ait-runtime-architecture.md`](../../ait-runtime-architecture.md) — AgentKit runtime (the live successor to the retired Spine/Eye/Ear/Hand `agent-operable-nos.md` vision; A8 conductor → A14 AgentKit)
```

Rationale for the target choice: the deletion commit names
`docs/ait-runtime-architecture.md` as the live successor ("docs/anatomy-runtime-flow.md
→ ait-runtime-architecture.md (live successor)"). The file exists at `docs/` root
(verified: `git ls-files docs/ait-runtime-architecture.md`), so a bare
`ait-runtime-architecture.md` target resolves correctly from `docs/roadmap-2026q2.md`.
CLAUDE.md's AgentKit section also calls `docs/ait-runtime-architecture.md` the
"Authoritative guide" — this is the correct redirect, not a guess.

**L756 (prose, no link):**

```diff
-### Telemetry expansion (deferred from `agent-operable-nos.md`)
+### Telemetry expansion (deferred from the pre-A14 agent-operability vision, now `ait-runtime-architecture.md`)
```

**L1264 (prose, no link):**

```diff
-- **Eye organ** (CVE feed integration) — referenced in `agent-operable-nos.md`, holds for Q3
+- **Eye organ** (CVE feed integration) — from the pre-A14 agent-operability vision (now `ait-runtime-architecture.md`), holds for Q3
```

Why touch L756 + L1264 at all (they aren't 404s): leaving a named-but-absent doc
in the prose is exactly the "archaeology" the deletion commit chose — but it now
reads as a broken breadcrumb to anyone (or any agent) who tries to open it. A
one-phrase redirect to the live successor costs nothing and removes the
ambiguity without erasing the history (we keep the original name in the
sentence). These two are judgement-call polish; **L199 is the non-negotiable
fix.** If review prefers minimal surface, L199 + the gate are sufficient and
L756/L1264 can be dropped — but the gate only covers *links*, so the prose
mentions would survive untouched either way (the gate does not assert on inline
code spans, only on `](target)` link syntax — see §4).

---

## 3. Approach

1. **Repoint the link (L199)** to `ait-runtime-architecture.md`, rewriting the
   surrounding text so it describes the live doc and notes the retired vision by
   name (preserves the historical pointer without a dead link).
2. **De-stale the two prose mentions (L756, L1264)** — redirect-by-phrase to the
   successor doc; no link syntax introduced (so no new gate burden beyond §4).
3. **Extend the existing gate** `test_framework_docs_links.py` with a roadmap
   variant of the already-present resolve-on-disk test. This is the structural
   lock: it makes *any* future bare/relative `.md` link in `docs/roadmap-2026q2.md`
   that fails to resolve trip the suite — closing the exact hole that let this
   404 live for a month after the source file was deleted.

The gate is added to the **existing** `test_framework_docs_links.py` (not a new
file) because that module is the established home for "relative `.md` link
resolves on disk" gates — it already holds the identical pattern for
`docs/archive/` and `docs/integration-map.md`, both authored 2026-06-14. A new
standalone file would fragment the same concern. This matches the repo's own
precedent verbatim.

### Gate sketch (drop into `test_framework_docs_links.py`)

```python
# WHY (2026-06-XX): docs/roadmap-2026q2.md's "Reference docs" block linked
# [`docs/agent-operable-nos.md`](agent-operable-nos.md) — a file DELETED in
# 1ce3e33f (superseded by A14 AgentKit; was Czech, violated English-only). The
# deletion commit left the roadmap refs "intact (archaeology)", so the bare link
# resolved to the non-existent docs/agent-operable-nos.md and 404'd for anyone
# reading the entry-point reference list. Repointed to the live successor
# docs/ait-runtime-architecture.md. This gate pins it: every relative .md link in
# docs/roadmap-2026q2.md MUST resolve on disk.
ROADMAP = REPO / "docs" / "roadmap-2026q2.md"


def test_roadmap_relative_md_links_resolve():
    """Every relative .md link in docs/roadmap-2026q2.md must resolve to a file."""
    assert ROADMAP.is_file(), "docs/roadmap-2026q2.md must exist"
    offenders: list[str] = []
    for lineno, line in enumerate(ROADMAP.read_text().splitlines(), start=1):
        for target in _MD_LINK.findall(line):
            resolved = (ROADMAP.parent / target).resolve()
            if not resolved.is_file():
                offenders.append(
                    f"  L{lineno}: link target '{target}' does not resolve "
                    f"(→ {resolved})"
                )
    assert not offenders, (
        "Broken relative .md link(s) in docs/roadmap-2026q2.md — a target that "
        "does not resolve on disk hands a 404 to readers of the entry-point "
        "reference list:\n" + "\n".join(offenders)
    )
```

> **Pre-flight the gate against the whole file BEFORE editing.** The `_MD_LINK`
> regex matches *every* relative `.md` link in a 94 KB roadmap, not just the
> agent-operable one. Run the proposed test against the **current** tree first
> (expect it to FAIL on L199, and possibly surface *other* pre-existing dead
> relative links in the roadmap). Triage any extras:
> - genuine 404s → fix in the same commit (they are the same bug class);
> - false positives (e.g. links into `files/anatomy/docs/` via `../`, or links
>   the regex shouldn't catch) → confirm they resolve, adjust nothing (the regex
>   already skips `http(s):`, `#anchors`, `//protocol-relative`).
> This avoids shipping a gate that's red for reasons unrelated to this item.

---

## 4. Risks

- **The gate may surface OTHER dead links in the roadmap.** A 94 KB roadmap
  likely contains many relative `.md` links. The new test asserts *all* of them
  resolve, so it can go red on unrelated pre-existing breakage. **Mitigation:**
  run the test against the current tree as the very first step (§3 pre-flight),
  enumerate every offender, and decide per-link: fix-in-scope (same bug class) or
  out-of-scope (open a follow-up item, and if necessary scope the gate to *new*
  offenders only — but prefer fixing, since they're all 404s). Do **not** merge a
  red gate.
- **Wrong redirect target.** If `ait-runtime-architecture.md` were itself renamed
  later, the new link would rot. **Mitigation:** the very gate we add catches
  that — the link must resolve on disk, so a future rename trips the suite. This
  is self-protecting.
- **Prose-mention scope creep.** L756/L1264 are inline code spans, not links —
  the gate does **not** cover them, so it cannot pin those edits. **Mitigation:**
  accept that they are judgement-call polish, not gated behaviour. If review
  wants them gated too, add a narrow `assert "agent-operable-nos" not in
  ROADMAP.read_text()` substring check — but only after confirming no *intended*
  historical reference must survive (the deletion-commit author chose to keep
  them; this plan proposes redirect-not-delete, so a hard substring ban would
  conflict unless the phrase is fully rewritten). Default recommendation: do the
  redirect, and gate links only.
- **English-only doctrine.** The retired doc was Czech. The replacement text is
  English — no regression. No new var, no Jinja, no `default.config.yml` touch,
  so the stock-Jinja-vars trap does not apply.
- **No live-system or playbook impact.** Docs + a pytest gate only. Zero risk to
  the overnight unsupervised run; nothing destructive, nothing reversible-only.

---

## 5. Gates it needs

1. **NEW** `test_framework_docs_links.py::test_roadmap_relative_md_links_resolve`
   — pins every relative `.md` link in `docs/roadmap-2026q2.md` to resolve on
   disk (the structural lock; §3 sketch).
2. **Existing suite stays green** — `python3 -m pytest tests/anatomy/` (the whole
   anatomy gate set), in particular the sibling
   `test_framework_docs_links.py` cases must remain passing (the edit only
   *adds* a test + redirects a link; it must not perturb the A1-relocation or
   archive/integration-map gates).
3. **Syntax-check clean** — `ansible-playbook main.yml --syntax-check` (no
   playbook surface touched, so this is a no-regression confirmation, not a
   behavioural gate).

---

## 6. Verification recipe

```bash
# 0. Confirm the bug exists and the target lives where the plan says.
ls docs/agent-operable-nos.md            # expect: No such file (the 404 source)
ls docs/ait-runtime-architecture.md      # expect: exists (the redirect target)
grep -n "agent-operable-nos" docs/roadmap-2026q2.md   # expect: L199, L756, L1264

# 1. PRE-FLIGHT the new gate against the CURRENT tree (before any edit).
#    Add only the new test fn, run it — expect RED on L199 (and triage any
#    other roadmap relative-link offenders the regex surfaces).
python3 -m pytest tests/anatomy/test_framework_docs_links.py::test_roadmap_relative_md_links_resolve -q
#    -> expect: FAILED, listing "L199: link target 'agent-operable-nos.md' does
#       not resolve (→ .../docs/agent-operable-nos.md)" (+ any extras to triage).

# 2. Apply the three roadmap edits (L199 link repoint, L756 + L1264 prose).

# 3. Re-run the new gate — expect GREEN.
python3 -m pytest tests/anatomy/test_framework_docs_links.py::test_roadmap_relative_md_links_resolve -q

# 4. Full file gate green (no regression on the A1 / archive / integration-map cases).
python3 -m pytest tests/anatomy/test_framework_docs_links.py -q

# 5. Whole anatomy suite green.
python3 -m pytest tests/anatomy/ -q

# 6. Playbook syntax unaffected.
ansible-playbook main.yml --syntax-check

# 7. Manual confirm the redirect target resolves & no dead refs remain.
grep -n "agent-operable-nos" docs/roadmap-2026q2.md   # expect: only the
#    redirect-by-phrase prose mentions (historical name kept), NO bare link form.
grep -n "ait-runtime-architecture.md" docs/roadmap-2026q2.md   # expect: L199 link + prose
```

**Done = all of:** new gate green, full anatomy suite green, syntax-check clean,
and the `[...](agent-operable-nos.md)` link form gone from
`docs/roadmap-2026q2.md` (replaced by a resolving `ait-runtime-architecture.md`
link).

---

## 7. Commit shape (when implemented — NOT in this plan commit)

Single docs+gate commit on `feat/v0.7-overnight`:

```
docs(roadmap): repoint dead agent-operable-nos.md link

- L199 link 404'd: file deleted in 1ce3e33f (superseded by A14)
- repoint to live successor ait-runtime-architecture.md
- de-stale 2 prose mentions (L756, L1264) → redirect-by-phrase
- new gate: roadmap relative .md links must resolve on disk
```

Conventional Commits, subject ≤50 chars, surgeon-tone body ≤6 bullets, no
Co-Authored-By, no `--author`. Lands on the branch only — never pushed.
