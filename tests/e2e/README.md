# nOS Tier-2 wet-test — Playwright suite

Mechanical mirror of [`docs/tier2-wet-test-checklist.md`](../../docs/tier2-wet-test-checklist.md).
See [`docs/wet-test-automation.md`](../../docs/wet-test-automation.md) for the
Cowork-driven loop architecture.

## Status (2026-05-03)

- **Infra ready** — config, package.json, TS setup all in place
- **Test bodies stubbed** — every test is `test.fixme()`; real assertions
  land post-H once we have one green wet test to model API shapes against
- **Python companion** at [`tests/wet/`](../wet/) covers sections 6/7/9
  (SQLite + JSONL + YAML) which aren't a Playwright surface

## One-time setup

```bash
cd tests/e2e
npm ci                          # installs Playwright + types
npx playwright install chromium # downloads the Chromium binary
```

## Running

```bash
# Default: dev box (NOS_HOST=dev.local, APPS_SUBDOMAIN=apps)
npx playwright test

# Override target
NOS_HOST=pazny.eu APPS_SUBDOMAIN=apps npx playwright test

# JSON output for Cowork ingestion
npx playwright test --reporter=json > .playwright-out/results.json
```

Results land in `.playwright-out/` (gitignored). HTML report at
`.playwright-out/html/index.html`.

## Adding a test

1. Find the matching section in `docs/tier2-wet-test-checklist.md`.
2. Open `tier2-wet-test.spec.ts`, find or create the `describe` block
   for that Section ID.
3. Replace `test.fixme(true, '...')` with the real assertion.
4. Cross-reference `docs/wet-test-automation.md` for the Cowork escape-
   hatch contract — small fixes auto-commit, big fixes file as questions.

## Why some sections aren't here

Sections 0/1/6/7/9/10/12 of the checklist are not Playwright surfaces:

- **0** — pre-flight (covered by `pytest tests/apps`)
- **1** — blank run (operator-only, needs `-K`)
- **6/7/9** — SQLite / JSONL / YAML (covered by `tests/wet/`)
- **10** — `tools/nos-smoke.py` CLI (Cowork runs directly)
- **12** — recovery workflow (operator decision, not autonomous)
