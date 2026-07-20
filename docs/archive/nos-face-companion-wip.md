# nOS-face companion — WIP handoff (paused 2026-07-19)

> **ARCHIVED 2026-07-20 — the work landed.** Everything this handoff describes as
> "UNCOMMITTED" was committed (`8de00130` iframe windows + create-table UI,
> `e5c3734f` Czech-safe slug contract) and shipped in `v0.9-beta`. Kept for
> archaeology; the "UNCOMMITTED" wording below is preserved as written and is no
> longer true.

Paused mid-flight to pivot to the blank/uninstall drift epic
([`blank-uninstall-managed-resources.md`](blank-uninstall-managed-resources.md)).
This captures exactly what shipped so the thread resumes cleanly.

## Shipped this arc (built + gated + LIVE-verified, but **UNCOMMITTED**)

All changes are in the working tree under `files/anatomy/face/` + one seed file.
Deployed live via `tools/nos-stacks.sh face` and Playwright-verified on
`127.0.0.1:5090` (edge-token + `nos-admins` headers). **Not committed** — awaiting
operator go.

### F2 — Systems iframe app ("iframes to existing services")
- `src/lib/components/ServiceFrame.svelte` (NEW) — iframe primitive: top bar with
  always-present **Open ↗** + Reload; `embed===false` → clean open-in-tab card with
  "try inline anyway" (for `X-Frame-Options`-blocked services). Cross-origin
  frame-blocks are NOT JS-detectable → the Open ↗ bar is the honest fallback.
- `+page.svelte` — non-native, non-CP window with a `url` now renders `<ServiceFrame>`
  instead of the old dead placeholder; `launchHub` passes `url`/`embed`.
- `contracts/index.ts` — `url?`/`embed?` on `WindowModel` + `WindowGeometry`; `embed?`
  on `HubApp`. `stores/desktop.ts` — `openWindow` carries them.
- `state/keap-tables/systems.table.yml` — added an `embed` (boolean) column (SoT for
  iframe-embeddability in the LeanIX/explore view).
- **Latent bug fixed:** `bff/hub/+server.ts` filtered by `slug`, but Wing emits `id`
  + a loopback `url` → the dock was ALWAYS empty ("máme jen jednu app?"). Rewrote the
  mapping to key on `id`, take the public `domain_url`, and admit only
  `has_web_ui + enabled` services → **37 services** now populate the dock (monogram
  icons, sorted). Verified: click Apache Superset → iframe window, no placeholder.

### F1a — Create-table UI ("správa dataTables")
- `src/lib/components/CreateTableModal.svelte` (NEW) — title→auto-slug (dash-regex),
  columns builder (kind/required/options), /explore metadata (description + anchor).
- `src/lib/tables/createtable.ts` (NEW) + `.test.ts` (13 vitest) — pure helpers
  (slug derivation/validation, column validation, build-create-body).
- `api/tables.ts` — `tablesCreateTable(body: CreateTableBody)`.
- `bff/config/+server.ts` — returns `canWriteTables` (RBAC gate; BFF POST re-enforces).
- `TablesApp.svelte` — "＋ New" button (manager+ only) → modal → refresh + select.
- **Latent bug fixed:** live KEAP rows have no `id` → `{#each rows (row.id)}` = N
  duplicate `undefined` keys → Svelte `each_key_duplicate` crash unmounted **any**
  live KEAP table (Tables app, Control Panel rawDataTable surfaces). Fixed in
  `bff/tables/+server.ts` `withStableIds()` — one layer, all consumers. Verified:
  tables render rows, modal opens, no console errors.

### F1b — Explore
Face-side complete (open-in-tab + try-inline). Blocked only on KEAP framing.

Gates green throughout: **svelte-check 0/0 · 113 vitest · lint clean.**

## Open items (KEAP-side; prompt already drafted)
Deployed KEAP is **v1.12.1**; the list-all fix is **v1.14.1** (not yet pinned/deployed),
so `GET /agent/v1/tables` (list-all) still 401s on the bearer → face uses the
known-`face-*`-slugs fallback. Pending on KEAP:
1. list-all accepts the RO agent bearer (bump pin to ≥ v1.14.1, redeploy).
2. `/explore` framing: `frame-ancestors 'self' https://face.<tld>` (drop
   `X-Frame-Options: SAMEORIGIN`) → Explore inline works, no face change needed.
3. Confirm create-table `anchors`/`description` render the table as an `/explore` node;
   give the anchor-format contract.
4. (future) native graph-data endpoint `/agent/v1/graph` → render Explore natively,
   no iframe.

## Resume checklist
1. Commit the uncommitted face work (13 files) — clean baseline.
2. Bump `keap_repo_ref`/`keap_version` to ≥ v1.14.1 when the operator's KEAP is ready;
   drop the known-slugs fallback in `bff/tables` once list-all works.
3. Re-verify Explore inline once framing is relaxed; delete the `face.controls`
   orphan (see the blank epic).
4. `dev` push (deferred — see release flow).
