# Contributing to nOS

Read [CLAUDE.md](CLAUDE.md) first. It is the working contract for humans and for
Claude Code alike; this file only covers the fork-and-PR mechanics.

## Work in a fork

1. Fork `thisisait/nOS` on GitHub and clone your fork.
2. Branch from `dev`: `feat/<name>` or `fix/<name>`. Never branch from `master`.
3. Your estate settings live in `config.yml` and `credentials.yml` (copy the
   `default.*.yml` keys you need). Both are gitignored: never commit them, and
   never edit `default.config.yml` / `default.credentials.yml` to hold your
   own values (domain, email, paths, passwords).
4. Keep your fork's `dev` current: `git fetch upstream && git rebase upstream/dev`.

## Before you open a PR

Run the offline gates. They need no running estate, no Docker and no secrets:

```bash
pip3 install pytest pyyaml jsonschema httpx jinja2 requests textual 'ansible-core>=2.20'
ansible-galaxy install -r requirements.yml   # once, for --syntax-check
python3 -m pytest tests/anatomy -q -p no:cacheprovider > /tmp/anatomy.txt 2>&1; tail -5 /tmp/anatomy.txt
ansible-playbook main.yml --syntax-check
tools/ci-local.sh          # frozen CI toolchain + syntax-check (slower, closest to CI)
```

Read the pytest summary from the file: `pytest | tail` reports tail's exit
code, not pytest's.

## The one rule reviewers enforce

**A fix ships with the gate that would have caught it, and the gate is shown
red against the broken code first.** Write the test, run it, see it fail, then
fix. Put both runs in the PR. A test edited in the same PR as the code it
guards, so that it passes, is not a gate ([ssot/doctrine/gates.md](ssot/doctrine/gates.md)).

## Commits

Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:` …), subject ≤ 50
characters, body ≤ 6 bullets: the part touched, the symptom, the fix, the gate.
No `Co-Authored-By`, no `--author` override. Small separate commits over one
large one.

## What never goes into a commit

- `config.yml`, `credentials.yml`, `~/.nos/*`, any token, key or password.
- Your own hostname, domain, email, home path or volume path in code, tests or
  defaults: derive them from facts (`ansible_facts['env']['HOME']`) or a config
  variable, and use neutral fixture values (`alice`, `example.test`) in tests.
- The name of any organisation running nOS.
- Generated state under `state/` unless a gate asks you to regenerate it.

## CI and review on a fork PR

CI (`.github/workflows/ci.yml`) runs on `pull_request` and uses no repository
secrets, so it runs the same on a fork PR (GitHub may hold a first-time
contributor's run until a maintainer approves it). The macOS integration job is advisory
(`continue-on-error`). CodeRabbit reviews every PR into `dev` or `master`
against [docs/review/threat-checklist.md](docs/review/threat-checklist.md);
it is advisory, verify each comment against the code before acting on it.
