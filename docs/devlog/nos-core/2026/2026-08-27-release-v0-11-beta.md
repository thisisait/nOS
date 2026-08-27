---
id: 2026-08-27-release-v0-11-beta
title: "v0.11-beta — the loop closes, and the estate learns to be asked"
date: 2026-08-27
namespace: nos-core
summary: "472 commits in the twenty-five days after v0.10-beta. v0.10 asked who writes the success record; v0.11 answers a harder one: can the estate improve itself without a human standing in the middle of it? A scanner finds a weakness, an agent proposes against it, gates the proposer cannot touch judge it, and a driver holding no propose scope lands it — the first two commits to reach the tree that way. Around it: nine readers that answer questions instead of leaving them to be derived, a backend that is a binding rather than a provider, datastore transport measured instead of declared, and the release notes' own beta criteria re-measured rather than restated."
tags: [release, agentic-loop, agentkit, security, transport, readers, nos-face, cortex]
release: v0.11-beta
actors: [pazny, claude]
related: [RELEASE.md, docs/doctrine/loops.md, docs/minimax-groundwork.md, docs/hidden_fees/08-empty-stack-reads-as-success.md]
---

`v0.10-beta` asked who writes the success record. The answer — far too often,
the step itself — reshaped a release. `v0.11-beta` asks the question one level
up: **can this estate improve itself, and would anyone be able to tell if it
only appeared to?**

## The loop, and the edge nobody had built

The parts had been in place for months. A scanner finds weaknesses. An agent can
author a patch. Gates can judge one. Nothing joined them, and the join is the
whole idea: for as long as a human carried a proposal from one stage to the next,
the loop was a diagram with a person standing in the middle of it.

v0.11 closes it. A weakness becomes a proposal, the proposal is judged by gates
its author cannot reach, and a driver that holds no propose scope opens the
merge request. Two commits reached the tree that way — the first the estate has
ever landed without a hand on each step.

What that took was mostly *refusals*. The proposer may not touch the oracle that
will grade it. The driver may not propose. A judged verdict is bound to tree
identity, so a proposal that passed against a different tree is re-judged rather
than trusted. `gate-add` — the one intent that may write the gates' own
directory, because forbidding it would mean the loop can never add a gate — is
narrowed to files the diff *creates*, and is never auto-accepted.

And an honest failure: for months **no model-authored proposal had ever been
produced**, and the reason was found on the last day before the tag. The propose
skill sends the proposer to the budget endpoint for the closed `intent_class`
enum, deliberately listing none of them itself so the doc cannot go stale. The
budget response did not carry the enum. A proposer tried nine plausible words,
was refused nine times by an error that echoed back its own guess, and correctly
gave up. Every proposal authored before that was a lucky guess or an operator
typing. The budget now carries the enum and the refusal names it.

## An agent runtime that can be held to something

`AgentKit` gained the bound path in earnest: a session declares a backend, the
resolver walks eight fail-closed gates before a single token moves, and the
agent's own Article-30 record is one of them — a routing the compliance register
does not declare refuses the session outright, because running it elsewhere
instead would execute a ceremony whose record is known-false.

MiniMax is armed, with four agents bound and the two code-authoring,
opus-pinned ceremonies held on the default backend. That carve-out is a
judgement about who may run commands as the operator, not a technical limit,
and it is written down as one.

The bound path also *finished a run* for the first time — 129 seconds, no
ceiling, where every August attempt had died on one. The two failures that
followed were worth more than the success: a byte-truncated payload made
`json_encode` refuse an entire request body and killed a session at 118k tokens,
and a grader's well-formed JSON carrying one word outside its enum was told
three times that it "was not strict JSON", so it kept correcting what it had got
right. Both are fixed at the point every caller meets, rather than in the tool
where each was found — the second one only happened because the first fix had
been applied to a single file nine days earlier.

## The estate answers questions instead of leaving them to be derived

Nine readers shipped, and the pattern behind them matters more than the count: a
notification is an event, and red is a *state*, and until this release the estate
had no way to be asked for the state. Establishing that two nightly jobs had been
failing for two days — having correctly notified once and then gone quiet by
design — took six ad-hoc SQL queries. Now it takes one command.

Every one of them is strictly a reader, exits 0 whatever it finds, and reports an
unreadable source as UNKNOWN rather than as green. Several shipped *ahead* of the
mechanism they measure, which is deliberate: a number nobody can ask for is a
number nobody will fix.

## Transport, measured rather than declared

`sslmode=require` in a connection string is a claim. The release replaces it with
a count: how many backends on the fabric actually negotiated TLS, sampled from
the server's own view. PostgreSQL reads 34 of 34. MariaDB reads 45% cumulative
and says so in amber, because a fix moves the trend and not the number already
banked — and because `require_secure_transport` is still off, which is the only
switch that can certify an end state.

One service never appeared in any sample at all: its connection pool drops the
connection between queries. Silence is not encryption, so the reader asks that
service's own session directly rather than counting its absence as a pass.

## What did not get done, said plainly

The notes carry a section listing six criteria for dropping `-beta`. Two are met;
four are not, and they are named with what is missing. A GitLab CVSS 9.4 sits
open because no upgrade recipe reaches its fix. The `master` ruleset requires
signed commits and has never once been satisfied — every release to date bypassed
it with an admin override, which makes it a gate that only ever reports its own
defeat.

The Linux integration job is green and does not yet prove the playbook. Six
hidden fees turned out to have been paid weeks ago with only their prose saying
otherwise, which is its own small lesson about where truth lives.

None of that is hedging. It is the same rule the loop is built on, applied to the
release notes: absence of evidence is not recorded here as success.
