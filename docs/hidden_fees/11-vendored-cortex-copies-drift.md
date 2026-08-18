# 11 — The vendored cortex copies drift, and nothing measures it

## The fee

`files/anatomy/cortex/` is a verbatim copy of KEAP's cortex modules, its
`knowledge/` tree, its conformance fixtures and eight of its specs. Two full
implementations of one language now exist, plus three copies of the documents
that govern them (KEAP, organ, ledger).

The organ's CI runs the **organ's own** vendored fixtures. It is self-consistent
and therefore structurally incapable of noticing that it has diverged from the
tree it was cut from. Nothing compares the two.

Already visible: `cortex-validate.md` cites `server/migrations.ts:60` in the
organ and `:83` in KEAP, because v1.28.0's dead-schema comment moved the line by
23. Both are correct *for their own tree*, which is the point — the drift is
benign today and there is no mechanism that would tell us when it stops being.

## When the bill comes due

The first KEAP change that touches the taxonomy, a verb, or an opcode without a
re-vendor. The organ keeps answering confidently against the old vocabulary, and
`ast.binding` stamps are issued for a language the source repo no longer speaks.

## How it was found

While auditing whether the vendored specs carried the provenance header the
ledger claimed for them. They did not — 3 of 8 — and diffing the rest against
KEAP surfaced the migrations.ts line skew.

## What closes it

Deleting one of the two implementations. That is **S5** in
`docs/archive/cortex-self-core.md`, and it is the only real answer; everything
before it is mitigation.

One mitigation landed 2026-07-26: `tests/anatomy/test_cortex_vendored_docs.py`
asserts every vendored spec carries a provenance header. It stops the failure
mode where someone edits the copy, believes the spec is fixed, and loses the
change at the next re-vendor.

**"Nothing in this repo can" detect drift was true of the REPO and false of the
HOST (corrected 2026-08-18).** `~/keap/src` is a full checkout the playbook puts
there, sitting beside the vendored tree the whole time. The comparison was never
impossible, only never written. `tools/cortex-drift.py` is it — a reader, not a
gate, because CI has no KEAP checkout and inventing one would be a third copy to
keep in step. On a host without the checkout it says drift is UNKNOWN rather
than absent.

It reads three claims out of the files themselves rather than keeping lists:
`LOCALLY AUTHORED (not a port)` excludes the organ's own programs (`index.ts`
shares a NAME with KEAP's backend and is a different thing — 694 lines of noise
on the first run), and `nOS Sn DIFF` markers set aside divergence someone
declared. What is left is the category entry 11 is actually about: **drift
nobody wrote down**.

First run, organ 0.1.0 vs KEAP 1.40.1 — 160 identical, **14 undeclared**, 2
declared, 9 locally authored. Two of the fourteen are not cosmetic:

- `server/cortex-opcodes.ts` — the organ's `MODEL_URI_RE` accepts
  `claude-*` and `openai-*`; KEAP's accepts neither. **Two implementations of
  one language disagreeing about what the language is**, which is the bill this
  entry predicted (*"`ast.binding` stamps are issued for a language the source
  repo no longer speaks"*) arriving before anyone looked.
- `server/fs-roots.ts` — the organ's overlap guard checks EVERY per-user root;
  KEAP's still reads `KEAP_USER_FILES_DIR`, a variable the organ's plist never
  sets, so the guard's `if` never runs. The organ carries a fix for
  cross-user file exposure that KEAP does not. Drift can run in both
  directions, and the direction that matters is not always ours.

The one live detector is KEAP's `cortex.ontologyDrift` on `/agent/v1/health`
(v1.29.0): under organ mode it compares the two `onto1` digests and reports
`match` / `differs`. It watches the **ontology**, not the code and not the prose,
and it cannot be a gate because `differs` legitimately means two different things
before and after S2 gives the organ its own corpus.
