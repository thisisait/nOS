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

Deleting one of the two implementations. That is C4, and it is the only real
answer; everything before it is mitigation.

The one live detector is KEAP's `cortex.ontologyDrift` on `/agent/v1/health`
(v1.29.0): under organ mode it compares the two `onto1` digests and reports
`match` / `differs`. It watches the **ontology**, not the code and not the prose,
and it cannot be a gate because `differs` legitimately means two different things
before and after C2.
