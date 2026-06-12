---
id: 2026-06-08-ci-filter-saga
title: "21 cycles of 'No filter named bool': a CI postmortem"
date: 2026-06-08
namespace: nos-core
summary: "CI Integration jobs started dying mid-playbook with 'No filter named bool' — then 'to_nice_json', then default() failing to trap undefined. Five misdiagnoses and 21 push-and-pray cycles later, the real cause: the GitHub runner's filter-load path imports VaultDecryptionContext, a symbol that only exists in ansible-core 2.21 — so the fix was a NEWER ansible, not an older pin. The saga's lasting artifact is a frozen 1:1 toolchain reproducible locally before any release push."
tags: [ci, ansible, incident, postmortem]
actors: [pazny, claude]
related: [tools/ci-local.sh, tools/ci-freeze.env, requirements.lock.yml]
---
## A failure that made no sense

The error class was absurd on its face: mid-playbook, on the GitHub
Integration jobs only, Jinja2 started claiming that `bool` was not a filter.
Then `to_nice_json`. Then `regex_replace`. Then — the truly disorienting
one — `| default()` stopped trapping undefined variables, which is roughly
Ansible's equivalent of arithmetic failing. Locally: green. Pytest jobs:
green. Only the jobs that actually *ran the playbook* on the hosted runner
fell over, and a dev box could not reproduce a single symptom.

## The misdiagnosis tour

Over ~21 push-and-debug cycles, the failure got blamed on, in order: the
ansible-core 2.20.6 patch bump (a patch release flipping CI red with zero
repo change is a compelling suspect), Python 3.14 on the runner, the
deprecated `{{ vars }}` eager-resolve path (a known trap in this codebase,
which made it a plausible repeat offender), `ansible.cfg`, and a
mixed/baked pip install. Each theory produced commits. A clean-venv
diagnostic finally disproved the whole list at once: single
`ansible.__path__`, `PYTHONPATH` unset, `import ansible.plugins.filter.core`
works fine — and the playbook still died.

## The real cause, found by comparison

The mechanism: on these runners, the full playbook's filter-load path
imports **`VaultDecryptionContext` from
`ansible._internal._yaml._dumper`** — a symbol **added in ansible-core
2.21**. Our pin held 2.20.x, whose `_dumper.py` lacks it. The import fails,
ansible silently **skips loading `ansible.builtin.core` filter plugins**,
and from that moment every filter — including `default` — throws "No filter
named" mid-run. Not a version too new; a version too *old* for a load path
that only this runner exercises. A dev box never touches that path, which
is why nothing reproduced.

The fix is anticlimactic, as real fixes usually are: the two Integration
jobs install ansible into a fresh venv at **2.21.0** — already
forward-compat-verified months earlier under Track H — and prepend its
`bin` to `$GITHUB_PATH`. The operator's daily driver stays 2.20.5; CI's
2.21 is just the wet-test floor the runner demands.

## The artifact: a toolchain you can freeze

The expensive part wasn't the bug, it was the loop: every hypothesis cost a
full CI round-trip because nothing local mirrored the CI environment. So
the saga's structural output is the frozen 1:1 toolchain:
`tools/ci-freeze.env` (Python + ansible-core pins) plus
`requirements.lock.yml` (exact collection pins) as a single source of truth
consumed by **both** the CI Integration jobs and `tools/ci-local.sh`, which
rebuilds the identical venv on the dev box and runs the filter-load probe +
syntax-check in seconds, or the full wet-test on demand. Running it before
the release push would have collapsed 21 cycles to roughly one.

The honest caveat is committed alongside: this freezes the *toolchain*, not
the *environment*. GitHub's hosted macOS runner has a second, independent
quirk (the custom-module interpreter ignoring every Python pin we know how
to set), which is why macOS Integration is non-blocking and the Linux job
is the gating wet-test. A truly identical environment needs a self-hosted
runner — deferred, knowingly.

## Where it stands

CI is green, pinned to `ansible-core==2.21.0` exactly, and the operative
memory rule is now written down where it can't be unlearned: when CI is red
and local can't reproduce, **compare exact versions and error text across
passing-vs-failing jobs first** — don't hypothesize. Every one of the five
misdiagnoses was a hypothesis that a ten-minute comparison would have
killed.
