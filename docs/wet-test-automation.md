# Wet-test automation — Track P architecture

> **Status:** scaffolding only (this batch). Full implementation post-H.
>
> Operator-driven motivation (2026-04-29): walking
> [`docs/tier2-wet-test-checklist.md`](tier2-wet-test-checklist.md) by
> hand after every blank is necessary today but won't scale. Once the
> nOS catalog grows past 5-10 Tier-2 apps, we need a Playwright suite +
> Claude Cowork session that drives the 12 checklist sections
> autonomously and files `fix(apps):` commits when things break.

---

## Why Playwright + Claude Cowork

**Playwright** is the right tool for the browser-flow assertions
(Sections 4, 5, 11 of the checklist) because:

- Headless Chromium understands mkcert wildcards via a `--ignore-
  certificate-errors` launch arg or a custom `cert.pem` mount, so
  `*.dev.local` works without a CA install ceremony.
- The 12 checklist sections map cleanly onto Playwright's
  `describe`/`test` hierarchy — one `describe` per section, one `test`
  per pilot in sections that iterate (Sections 3-11).
- Output is structured JSON (`--reporter=json`) — no screen-scraping
  needed when a Cowork session reads the results.
- Network assertions (`expect(page).toHaveURL(/auth\./)` for the
  Authentik redirect) are first-class.

**Claude Cowork** ([cowork docs](https://docs.claude.com/en/agents/cowork))
is the right driver for the verification loop because:

- A Cowork session has **shell pass + browser** — it can run
  `npx playwright test`, parse the JSON output, identify the failing
  section, open the relevant manifest at `apps/<slug>.yml`, propose a
  fix, run `--syntax-check`, commit as `fix(apps): ...`, push.
- The operator stays in the loop for the BLANK run only (the only
  thing that requires `-K` and host-level state changes); everything
  else — interpretation, fix proposal, commit — is autonomous.
- Failure modes that need human judgment (e.g. "this app is
  fundamentally broken upstream, demote to .draft") surface as a
  Cowork question instead of a silent commit.

The split:

| Step | Operator | Cowork session |
|---|---|---|
| Blank run (`ansible-playbook -e blank=true`) | yes | no — needs `-K` |
| Run Playwright suite | optional | yes |
| Parse JSON results | optional | yes |
| Open `docs/tier2-wet-test-checklist.md` Section N for failure context | optional | yes — reads file, cross-references |
| Diagnose failure (manifest typo, healthcheck timing, etc.) | optional | yes |
| Propose + apply fix | optional | yes — small fixes only; large changes file as Cowork question |
| Commit (`fix(apps): ...`) | optional | yes |
| Re-run partial blank (`--tags apps`) for the fix | yes (still needs `-K` for sudo) | no |
| Re-run Playwright after partial blank | optional | yes |

---

## File layout

```
nos/
  tests/e2e/
    tier2-wet-test.spec.ts        ← skeleton this batch; full impl post-H
    playwright.config.ts          ← (post-H) Headless Chromium + mkcert + reporter=json
    fixtures/                     ← (post-H) seed-data PNGs / signature samples for documenso
  docs/
    wet-test-automation.md        ← this file (architecture)
    tier2-wet-test-checklist.md   ← human-readable checklist (single source of truth)
```

The Playwright spec is the **mechanical** mirror of the checklist —
when the checklist updates, the spec updates. Section IDs (Section 0,
Section 1, …, Section 12) are stable.

---

## How a Cowork run will look

```
┌─────────────────────────────────────────────────────────┐
│ Operator: ansible-playbook main.yml -K -e blank=true   │
│ (~25 min — operator monitors via the inline-smoke step) │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ Cowork session is told: "blank done, run wet-test"      │
│ → cd tests/e2e && npx playwright test --reporter=json   │
│ → reads JSON: 11/12 sections green, Section 7 fails     │
│   for app_documenso (Bone events delivery)              │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ Cowork session reads docs/tier2-wet-test-checklist.md   │
│ Section 7 to understand expected JSON shape, then       │
│ tail ~/.nos/events/playbook.jsonl and confirms event    │
│ has app_id=documenso but NEXT_PRIVATE_DATABASE_URL was  │
│ logged earlier as "host=documenso-db" (not "documenso-  │
│ db.<apps_subdomain>") — Documenso emitted its own       │
│ telemetry shape that Bone receives as 200 but its       │
│ `app_id` was nulled out.                                │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ Diagnosis exceeds "small fix" — Cowork files a question │
│ at the operator's queue, doesn't commit autonomously.   │
│ Operator wakes up, reads the Cowork report, decides.    │
└─────────────────────────────────────────────────────────┘
```

The escape hatch (Cowork files a question rather than commits) is
critical. Cowork can apply low-risk fixes (`start_period` bump, image
tag bump, missing env var) but anything that touches role logic or
post-hooks waits for operator review.

---

## What's in this batch (scaffolding, not implementation)

- `tests/e2e/tier2-wet-test.spec.ts` — Playwright skeleton mapping
  sections 2/3/5/8/11 to `describe`/`test` blocks. Stubs only —
  every test has an `expect.fail("not yet implemented")` placeholder.
- `playwright.config.ts` is NOT included in this batch (post-H —
  needs the mkcert / cert path / `NOS_HOST` env decisions which are
  Track F territory).
- This doc.

The spec compiles (well, parses — TypeScript syntax) but won't run
green until Track P proper. Useful in this batch as a placeholder so
new Cowork sessions can `cat tests/e2e/tier2-wet-test.spec.ts` and
see the shape of what's coming.

---

## Activation (post-H)

```bash
cd tests/e2e
npm ci                          # installs Playwright + types
npx playwright install chromium # downloads the browser binary
NOS_HOST=dev.local \
  npx playwright test --reporter=json --output=results.json
```

Cowork session reads `tests/e2e/results.json`, cross-references
`docs/tier2-wet-test-checklist.md` Section IDs against the
`title` / `parent` fields in the JSON, and proceeds.

Suggested CI integration (post-H): `workflow_dispatch` only — running
Playwright against a live nOS host is too expensive for every PR.
Cowork session runs it on operator's box after each blank.

---

## Status update — 2026-05-03

Post-Track-E batch the scaffolding got two real layers:

- **`tools/post-blank.sh`** — operator-facing single-entry-point runner
  (wet pytest → nos-smoke → Wing UI deep-links). Documented in
  [`docs/post-blank.md`](post-blank.md).
- **`tests/wet/test_post_blank_state.py`** — 14 deterministic Python
  tests covering checklist sections 6/7/9 (SQLite GDPR rows, Bone JSONL
  events, smoke catalog runtime). These ARE active; they SKIP pre-blank
  and FAIL under `NOS_WET=1`.
- **[`docs/cowork-wet-test-prompt.md`](cowork-wet-test-prompt.md)** —
  the Cowork dispatch prompt; ready to paste into a Cowork session.

What's still scaffold (= Track P proper, post-H): the Playwright
bodies in `tests/e2e/tier2-wet-test.spec.ts` (sections 4/11). All
other sections have working automation today.

---

## Out of scope (current batch)

- Playwright config (deferred — needs Track F `NOS_HOST` parameterisation)
- Real Playwright test bodies (deferred — needs the wet-test loop
  running once successfully so we know what assertions are stable)
- CI integration (deferred — see "Activation" above)

---

## Track P exit criteria (post-H)

- All 12 sections of the wet-test checklist have a corresponding
  Playwright test
- Cowork session can drive a full wet-test from "blank just finished"
  to "all green, branch ready for review" hands-free
- Documented Cowork prompt template lives at
  [`docs/cowork-wet-test-prompt.md`](cowork-wet-test-prompt.md) ✅
  (drafted 2026-05-03)
- Operator reports a successful end-to-end Cowork-driven wet test in
  a Decision log entry
