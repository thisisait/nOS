# 48 — An authority that is live in doctrine and blueprint in git

**Found** 2026-09-02; **closed** 2026-09-03 (two clauses).

## What it looked like

CLAUDE.md: "`authentik_engine: tofu` is the live authority." The cutover doc:
"STATUS: CUTOVER COMPLETE." The committed default: `authentik_engine:
"blueprint"`, `manage_authentik_with_tofu: false`, with a DO-NOT-FLIP warning.

All three true — about different subjects. The cutover happened on THIS
operator's estate (config.yml opts in); doctrine wrote it as if it were the
repo's stock default. A fork reads "tofu is live", gets blueprint.

## The close

One clause in each doc: tofu is the authority ON ESTATES THAT OPTED IN; a
fresh checkout defaults to blueprint until the adopt script proves `tofu plan`
no-op. The committed default is correct and unchanged — the docs now say whose
truth they carry.
