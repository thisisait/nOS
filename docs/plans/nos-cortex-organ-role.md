# P-4b: the cortex organ role — steps 9–12, blank trimmed

Status: **implemented through step 11 + docs**, 2026-07-25 — steps 9 (role),
10 (plugin + KEAP env plumb), 11 (CI job + shims) and the Docs consolidation
are committed on `feat/cortex-organ`; the live `--tags cortex` converge (step
12 trimmed) is the operator's next act after merge to `dev`. Two deviations
from the written design, both deliberate and recorded in the commits: the
daemon runs IN-PLACE from `files/anatomy/cortex/` (the self-model NOS_ROOT is
module-relative — an rsynced copy could not see the estate), and `cortex-base`
declares NO pulse job (embed-sync is C2 scope; the C1 daemon has no embed
surface). Workflow definition at
`tools/workflows/nos-cortex-organ-role.js` (first entry in the repo's own
workflows dir — nOS `.gitignore` excludes `.claude/*`, so the KEAP-side
convention of `.claude/workflows/` does not carry over). Runs on
**`feat/cortex-organ`**, continuing the P-4 commit series.

## Where this picks up

P-4 (`nos-cortex-organ-port`, defined in the KEAP repo's `.claude/workflows/`)
landed build-sequence steps 1–8 of `nos-cortex-organ-design.md` §6 on
`feat/cortex-organ` (`6ee8b552..fbaf5f4b`, 2026-07-25):

- organ vendored under `files/anatomy/cortex/`, pure port green, store wired,
  ANN at the measured optimum (float8 + `max_neighbors=20`);
- the hard gate holds: **`onto1:76d1f3ad728b382b`** over the real tree;
- daemon on `127.0.0.1:8098` (validate + opcodes + health), fail-closed auth;
- post-P-4, the **C1 self-model gap** was found and closed
  (`files/anatomy/cortex/docs/C1-GAP-selfmodel.md`): the organ now runs
  `keap_selfmodel_gen.py` itself and reaches live parity
  **1841 nodes / 1051 ext / 1841 descriptions**, with a coverage assertion so
  a slug-rootless materialisation fails.

## Scope decision for this stage (operator, 2026-07-25)

- **Steps 9–11 in full**: `roles/pazny.cortex`, `cortex-base` plugin + Pulse
  `keap-embed-sync`, CI `cortex` Node-22 job + `tests/anatomy/` shims.
- **Step 12 trimmed**: live verify via **`--tags cortex` converge only** — the
  workflow never runs a blank/`--remove`. The full blank verify stays an
  operator ceremony after review.
- **Step 13 (KEAP P-5 cutover) out of scope**: separate supervised PR in the
  KEAP repo, per the design and `cortex-full-scope-decision.md` (C4).
  `keap-base` gains `cortex_backend_url` as *render-only* plumbing now.
- **Branch**: continue on `feat/cortex-organ`; one PR to `dev` for the whole
  organ once the role lands and verification is green.

## Standing corrections (law, from `cortex-full-scope-decision.md`)

1. **No `db_identity` carry-over** — the organ mints its own UUID; the drift
   check answering "is this the same database?" must stay truthful.
2. **No shared `keap.db`** — not read-only, not transitionally. The store is
   `~/cortex/data/cortex.db`, materialised from git + the self-model generator.

## Docs consolidation (new, operator-requested)

The transplant has left cortex specs strewn across two repos. This stage adds a
**Docs phase**: inventory every cortex-relevant spec in KEAP `docs/specs/` and
nOS `docs/plans/`, judge each (done / superseded / live-here / live-keap /
split), copy the still-live organ-side ones into
`files/anatomy/cortex/docs/specs/` (5 already vendored by P-4), and write
`docs/plans/cortex-specs-ledger.md` with a post-transplant-cleanup column.
**KEAP stays read-only** — the deletion pass there happens after C4, when the
whole "body transplant for the cortex" is complete.

## Deliberately NOT done here

- full blank verify (`nos --remove=data --confirm`) — operator ceremony;
- step 13 / P-5: deleting KEAP's `server/cortex-*.ts`, flipping its client to
  the organ — separate supervised PR;
- the shared onto1-conformance CI gate on the **KEAP** side — rides P-5;
- KEAP docs cleanup — post-transplant;
- C2 (corpus + ingestion migration) and C3 (quality pipelines) — own design
  passes per the scope decision.

## One threat-model nuance (verify pass, 2026-07-25)

"Pure loopback" means no *route* and no *bind* beyond 127.0.0.1 — it does NOT
mean containers cannot reach the daemon: Docker Desktop's
`host.docker.internal` resolves to the host, and a container can hit
`:8098` through it (that is exactly how the P-5 cutover will work, and why
`CORTEX_BACKEND_URL` renders that address). The trust boundary for container
callers is therefore the fail-closed bearer auth (tokenless ⇒ 503,
timingSafeEqual), not the loopback bind; the bind only removes the *network*
exposure. Design §5's "unreachable from containers" claim holds for
Docker-published loopback ports (A19), not for host-bound daemons.

## Open questions carried forward (design §7, still open)

- public `/agent` route: stays unbuilt until a caller outside
  Bone/Wing/Pulse/host-AgentKit appears (§7 Q5);
- backup: confirm `~/cortex/data/` joins the host-daemon restic set, and
  whether the regenerable ANN/FTS indexes are excluded (§7 Q6);
- the converge's sudo `vars_prompt` may force an operator-run
  `ansible-playbook main.yml --tags cortex` — the workflow's Converge stage
  hands off honestly rather than working around it.
