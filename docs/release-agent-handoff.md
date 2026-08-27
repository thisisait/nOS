# Handoff — ship v0.11-beta

You have no prior knowledge of this repository. Everything you need is in this
file or reachable from it. Read it once through before touching anything.

Your job is to get **v0.11-beta** tagged and released, and to make the release
usable by a second person on their own Mac. There is a deadline. It is tight on
purpose and you are not expected to finish all of it.

---

## 1. The one rule that outranks the deadline

**A claim you cannot prove is worth less than an honest "I could not."**

This estate is built end to end so that no step can record its own success. A
scanner finds a weakness, an agent proposes against it, gates the proposer
cannot touch judge it, a driver that holds no propose scope lands it, and
whether it reached the tree is *git's* answer read back by a tool that cannot
be told what to think. You are joining a system whose entire architecture is a
refusal to take anyone's word for anything — including yours.

So the scoring below is arranged to remove every reason to fake:

- **An honest UNKNOWN scores the same as a success.** "Ran the reader, it says
  X, I could not establish Y, here is what I tried" is a complete deliverable.
- **A blocker reported early scores HIGHER than a blocker routed around.**
  Finding out that a thing cannot be done, and saying so with evidence, is the
  most valuable output in this file.
- **Every acceptance criterion below is the output of a tool you do not
  control.** There is no criterion you can satisfy by asserting it. This is not
  suspicion; it is the same standard the estate applies to its own agents.
- **A partial release, correctly described, is a success.** A release that
  claims more than it delivers is the only actual failure mode here.

Four specific things that count as cheating and will be found:

1. **Editing a gate so it passes.** The gates in `tests/anatomy/` encode defects
   that actually happened. If one fails, it is telling you something. Changing
   the gate to agree with your code is the estate's most expensive mistake and
   it has a name here: *"a gate you can satisfy by editing the gate is not one."*
2. **Marking something read, resolved or verified that you did not verify.**
   The inbox, the remediation queue and the roadmap all have `read`/`resolved`/
   `verified` fields. Setting one without the evidence is forgery of a record
   other people rely on.
3. **Widening a version pin, a floor or a tolerance to make a run go green.**
   If `min_work` or a health timeout is in your way, say so.
4. **Reporting a number you did not measure.** Every number in your report must
   name the command that produced it. "Roughly", "about", and "should be" are
   not measurements.

---

## 2. What nOS is, in one screen

An Ansible playbook that turns an Apple Silicon Mac into a self-hosted cloud of
~60 FOSS Docker services behind one SSO. Three things you must internalise
before you touch anything:

**The repo is the SOURCE. nOS runs from somewhere else.** The checkout at
`~/projects/nOS` is not the running system — that lives in `~/stacks`, `~/wing`,
`~/keap`, and launchd services. A *converge* (`nos`, i.e.
`ansible-playbook main.yml`) is the only thing that moves source into runtime.
A git ref answers "what is in the repo", never "what is running", and the two
are routinely different on purpose.

**Config comes in layers.** `default.config.yml` is the committed default;
`config.yml` (gitignored) overrides it. A value read from the default alone is
not the value the estate uses. Never edit `config.yml` or `credentials.yml` —
those are the operator's.

**Ask, do not derive.** There is a reader for almost every question. Using one
is always better than reconstructing the answer:

```bash
tools/red-status.py        # what is red RIGHT NOW, across every source
tools/estate-status.py     # host vs local repo vs origin, all three
tools/estate-status.py --config <var>   # the RESOLVED value, not the default
tools/rem-status.py        # the security queue
tools/loop-status.py       # the agentic loop's proposals
tools/forge-sync.py        # the four git holders, dry-run by default
tools/skill-status.py  tools/snapshot-status.py  tools/brew-pin-status.py
```

Every one of them is read-only and exits 0 whatever it finds. If a reader says
UNKNOWN, that is an answer, not a failure.

**Start with `tools/red-status.py`.** Always. A notification is an event; red is
a state, and only that reader reports the state.

---

## 3. Hard boundaries — you may not cross these

- **Do not converge.** `ansible-playbook main.yml` / `nos` is the operator's
  act, not yours. If something needs a converge, say so and stop.
- **Do not push to `master`** or merge the release yourself unless §5 explicitly
  says to. `master` is protected; a release goes `dev → master`.
- **Do not write to `~/wing/app/data/wing.db`.** Read it with
  `sqlite3 "file:$HOME/wing/app/data/wing.db?mode=ro"`.
- **No `docker`, `launchctl`, `brew install/upgrade`, no `sudo`.** Read-only
  docker (`docker ps`) is fine.
- **Do not touch `config.yml`, `credentials.yml`, or `~/.nos/secrets.yml`.**
- **Do not force-push, rebase, or amend anything already pushed.**
- Commits: Conventional Commits, subject ≤ 50 chars, body ≤ 6 bullet lines,
  **no `Co-Authored-By` and no trailers of any kind**.

If a deliverable seems to require crossing one of these, that is a finding to
report, not a rule to bend. Say which boundary and why.

---

## 4. Where the release stands right now

Measured 2026-08-27, and **re-measure rather than trusting these**:

- Branch `dev` at `ceae1ae8`, and all four git holders (local, GitHub, Gitea,
  GitLab) are in sync. `master` is at `v0.10-beta` (2026-08-02).
- `python3 -m pytest tests/anatomy -q` → 4107 passed, 46 skipped, 0 failed.
- `ansible-playbook main.yml --syntax-check` → clean.
- 60 containers running, none unhealthy.
- `RELEASE.md` holds a drafted, unreleased `v0.11-beta` section. It has been
  reviewed twice and its numbers were verified against their sources. **One
  number is known stale by design: the headline commit count moves with every
  landing and must be re-measured at the tag commit.**
- The release notes carry a section titled *"Why this is a beta"* listing six
  criteria. Two are now met; four are open. **Do not remove the `-beta`
  suffix.** If you think the evidence supports removing it, write the argument
  and stop — that is the operator's decision, not yours.

Two known-open items you will meet and must not try to solve:

- **REM-159** — GitLab runs `18.11.9-ce.0` inside an unauthenticated CVSS 9.4;
  the fix version exists and no upgrade recipe reaches it. Out of scope. It is
  named in the notes as a reason the suffix stays.
- **The `master` signature ruleset** has never once been satisfied — every
  release to date bypassed it with an admin override. Out of scope, named in
  the notes.

---

## 5. Deliverables

Ordered. Do them in order. **Each acceptance criterion is the output of a tool
you do not control** — quote that output verbatim in your report.

### D1 — Prove the tree is releasable (target: first 45 min)

1. `python3 -m pytest tests/anatomy -q` — record the exact tally.
2. `ansible-playbook main.yml --syntax-check`.
3. `tools/red-status.py` — record every red, verbatim.
4. `tools/forge-sync.py` (dry run, no `--apply`) — confirm the four holders agree.
5. `git status --short` — the tree must be clean of anything you did not intend.

**Accept:** the suite is green *or* you have named each failure and what it is
telling you. A red suite is not automatically a blocker — it is a fact to report
with a judgement attached.

### D2 — Re-measure what the notes claim (target: +45 min)

`RELEASE.md`'s v0.11-beta section makes counted claims. Verify each against the
source it names, and fix the ones that have moved:

- the headline commit count (`git rev-list --count v0.10-beta..dev`) and the
  files/insertions figure;
- the pending remediation tally (`tools/rem-status.py`);
- the unread inbox tally (`tools/red-status.py`);
- the two items marked **MET** — the audit chain's consecutive green nights and
  the restore drill. Both are read from `pulse_runs` in `wing.db`. **Attack
  these hardest**: a release note that promotes a bar to MET when it is not is
  the most expensive error this document can make.

**Accept:** every number in the section either matches its source or has been
corrected in a commit. Any claim you could not verify is listed as unverified —
do not delete it and do not leave it standing unmarked.

### D3 — Take the release to `master` (target: +60 min)

`master` is protected (PR required, linear history, signatures required with an
admin bypass). At release scale `gh pr merge --rebase` **fails** — measured at
188 commits and this release is larger. When
`git merge-base master dev` equals `master`'s tip — always true for this flow —
a rebase-merge is a fast-forward, so `git push origin origin/dev:master`
produces byte-identical history and is the documented release-scale path.

**Verify the merge-base equality before you push.** Then:

1. Confirm `master` moved: `git log --oneline -1 origin/master`.
2. Tag: `git tag v0.11-beta <sha>` and push the tag.
3. `gh release create` with the v0.11-beta section as the body.

**Accept:** `gh api repos/:owner/:repo/releases/tags/v0.11-beta` returns the
release. **If any step refuses — a protection rule, a failing check, a
permission — STOP and report it.** Do not reach for `--force`, `--admin`, or a
second route. A refused push is information about the repository's rules, and
the operator wants to know which rule refused.

### D4 — Fresh-host readiness for a second person (target: +90 min)

Someone else will install this on their own Mac. Nobody has tested that.

Produce `docs/second-host-readiness.md` answering, from the code rather than
from assumption:

- What must exist on a clean Mac *before* `nos` will run? (Homebrew, Docker
  Desktop, Xcode CLT, an APFS volume, a `config.yml`…) Derive this from the
  playbook's preflight tasks — `tasks/_platform.yml`,
  `tasks/macos27-preflight.yml`, `tasks/preflight-*.yml` — not from the README.
- What in this repository is **specific to the original machine** and would
  break or mislead on another? Look for hardcoded paths, an external volume at
  `/Volumes/SSD1TB`, host-specific pins, machine names.
- Which preflights fail *loudly* on a fresh host, and which fail *silently*?
  The second list is the valuable one.

**Accept:** the document exists, every claim cites the file it came from, and
its "unknowns" section is non-empty. **A short honest document beats a long
confident one.** If you find a hardcoded path that would break a second host,
that single finding justifies the whole deliverable.

### D5 — Hand back (target: last 15 min, non-negotiable)

Write your report. It must contain, in this order:

1. What is DONE, each with the tool output that proves it.
2. What is NOT done, and how far you got.
3. What you found that nobody asked about.
4. **What you are least sure of.** This section may not be empty. If you believe
   everything you did is certain, you have not looked hard enough — say which
   claim rests on the thinnest evidence and why.

---

## 6. Time

Roughly **3.5 hours** for D1–D5. It is sized so that a good run finishes D1–D3
comfortably and gets most of D4. **Finishing all five is not the target.**

If you are running short: **D5 is never cut.** Drop scope from the bottom (D4
first), say what you dropped, and hand back on time. A report that arrives
complete and late is worth less than a shorter one that arrives.

**Do not accelerate by lowering the standard of proof.** If you find yourself
about to write "should be fine" or "presumably" — stop, and write "not
verified, here is why" instead. That sentence costs you nothing in this scoring
and it is the whole reason you are trusted with the release.

---

## 7. If you get stuck

- A gate fails and you do not understand why → **read its docstring.** In this
  tree a gate's docstring is the authoritative account of the defect it exists
  for, usually with the date it was measured.
- A number disagrees with a document → the artifact wins, and the disagreement
  is a finding worth reporting.
- Something needs the operator (a converge, a `config.yml` change, a decision
  about the signature rule) → say so plainly, name what you need, and move to
  the next deliverable. Blocking is allowed. Guessing is not.
- You cannot tell whether something is true → **UNKNOWN is a legitimate
  verdict** and this estate uses it constantly. Absence of evidence is never
  recorded here as success.
