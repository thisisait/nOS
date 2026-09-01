# `collab` — the agent-conversation channel (rough draft, 2026-09-01)

Working name for the main communication surface: chat with agents, generative
UI, debug/admin mode. Tauri-compatible from day one — same SvelteKit code as
the web desktop today, wrapped by a native shell once a dev identity exists.

## 1. Component vocabulary for a chat turn

The model **selects and parameterises**, never authors markup — this is
already the law (`view.ts` header, `VIEW_ACTIONS`, `narrowView`). A `collab`
turn is one row of `caddy-sessions`, rendered through the SAME closed
vocabulary every other DataTable uses. Nothing new needed at the row level:
`style: chat` already exists, `askColumn`/`bodyColumn` already split a row
into two bubbles.

What's actually missing is not a chat bubble — it's what a model can attach
*inside* an answer bubble once the chain has run. Two new pieces, both scoped
tightly to stay inside the closed-vocabulary rule:

- **`chain` as a sub-table, not a text blob.** `caddy-sessions.chain` is
  `kind: text` today — a JSON dump the model wrote. A chain is itself row-
  shaped (step, tool, args, result), so render it as a **nested `grid`**
  (reuse `resolveView`, zero new code) rather than inventing a "chain viewer"
  component. If it doesn't already deserialize row-shaped, that's the actual
  one-afternoon task, not a new render style.
- **One new offer action: `open-inbox`.** Q15 says Wing is the only answering
  channel — collab may *display* a pending question, never answer it inline.
  `VIEW_ACTIONS` today has exactly `focus-highlight`. A turn whose `status =
  asked` needs an offer that hands off to `/inbox?ref=<session_uuid>` — that's
  a second catalog entry (handler ships first, per the fail-closed rule), not
  a chat-specific concept. `open-inbox`'s handler is `window.open`/navigate to
  a fixed Wing route built from a column value already on the row — no new
  data shape crosses the trust boundary.

Left out, deliberately: a "streaming token" component (turns are rows, not
scrollback — a row lands when the turn is done, matching `status`), a
markdown renderer beyond what `blog`'s body column already does, and any
per-message action beyond the two above. Nothing here justifies more than
`chat` + nested `grid` + one catalog id.

## 2. Where turns live, and how the app reads them

**Both, by design — that's what `session_uuid` is for**, not an either/or.
`caddy-sessions` (KEAP DataTable) is the row the face reads and renders: it
carries the operator-facing facts (`transcript`, `chain`, `status`, the two
ratings) and goes through the *existing* path — `bff/tables/+server.ts` →
`narrowView` → `resolveView` → `chat` style. wing.db (`agent_sessions` /
`agent_threads` / `agent_iterations`, joined on `actor_action_id ==
session_uuid`) is where the depth lives — OTel span, token tally, per-tool
calls — read on demand (debug mode, §4), not on every render.

The BFF stays a **projection, not a proxy**: `bff/tables` already narrows
KEAP's `view` block before it reaches the client, and a debug-mode read of
wing.db must go through an equally narrow allow-listed route (a new
`bff/agent-sessions/[uuid]` GET that returns a fixed shape — thread list,
iteration count, trace link — never an arbitrary SQL passthrough). Writing
the operator's two ratings goes through the *table write path* (`canWrite`),
same as any other DataTable row edit — no bespoke rating endpoint.

## 3. Tauri-shaped — what must NOT be assumed

Checked against the actual code, not guessed:

- **Identity is already header-based, not cookie-based** — `hooks.server.ts`
  reads `X-Authentik-uid` + a Traefik-injected edge token, never a session
  cookie. This holds unchanged in a Tauri webview pointed at `face.<tld>`
  through Traefik. **No violation found here.**
- **Per-user state already goes through Bone via `uid`** (`bff/userstate`),
  not `localStorage`. Window geometry, wallpaper, layout picks all survive a
  quit/relaunch and a different device. **No violation found.**
- **What collab must NOT do, going in:** hold a running turn's state only in
  the SvelteKit page store. A turn is a `caddy-sessions` row with `status`;
  the row is the durable state, and the UI is a view over it — so closing the
  window (or the whole app, Tauri or not) mid-turn loses nothing the row
  didn't already have. This falls out of decision "a conversation is rows,"
  it isn't new — but it's worth stating as the concrete Tauri consequence:
  **no in-memory-only chat state, ever, even for the "typing…" affordance.**
  Poll or subscribe against the row's `status`, don't hold local truth.
- **The one place to watch:** `bff/ask/+server.ts` is a one-shot
  request/response with no persistence — fine for the palette's throwaway
  prompt, wrong shape for collab. A collab turn must open its
  `caddy-sessions` row (status=`running`) *before* the agent starts, not
  after — otherwise a killed webview (Tauri window closed mid-flight) leaves
  no record whatsoever, browser or native.
- **Not yet violated, but untested:** nothing in `face` today assumes a
  browser-only API (no direct `document.cookie`, no `window.opener` chat
  bridge beyond the file-picker's `postMessage`, which is same-origin and
  Tauri-webview-compatible). Treat this as "checked, clean" rather than
  "assumed fine."

## 4. Debug/admin mode

A view, not a store — same rule as the Anatomy apps (Bone/Wing/Pulse views
already ship this pattern: read a registry, render rows, never write a
second copy). For collab specifically:

- **Session detail** = the existing `agent_sessions`→`agent_threads`→
  `agent_iterations` chain, already reachable via Wing's `/agents/<name>/
  sessions/<uuid>` deep-dive — collab's debug mode is a `chat`-row action
  ("open in Wing") for the deep case, plus an inline `grid` of iterations for
  the common case (tool calls, timings) so the operator isn't forced to
  Tab-out for every turn.
- **What makes it useful on day one:** the four things already recorded and
  currently invisible from face — `mode` (local/cloud, "did this leave the
  machine"), the validator/grader verdict if the agent has a rubric, the
  OTel trace link, and the two ratings side by side with what was asked. All
  four are columns that already exist or a join that already exists; day-one
  debug mode is a **second `TableView` block on the same table** (a
  `tiles`-style admin variant exposing `meta: [mode, model, session_uuid]`)
  before it is any bespoke screen.

## 5. First afternoon

Ship the smallest thing that is real, not a mock:

1. Point a `collab` native app (`apps/native/`, form=`view`) at the
   `caddy-sessions` table through the existing `bff/tables` + `TablesApp`
   render path — **zero new server code** if the table's `view` block is
   authored with `style: chat`, `askColumn: transcript`, `bodyColumn:
   chain` (or a placeholder body until the agent writes real chains).
2. Wire one write path: an agent (conductor, or a throwaway test agent)
   appends a `caddy-sessions` row with `status: running` → `answered`,
   `session_uuid` set. This proves the row-is-truth model end to end before
   any UI polish.
3. Confirm the degrade path: pull `bodyColumn` or `askColumn` and watch it
   fall back to `grid` with `degradedFrom: 'chat'` — this is free (`view.ts`
   already does it) and is the cheapest possible proof the generative-UI
   contract holds for a table nobody has finished authoring yet.

That's a rendered, real conversation table, one live write path, and one
proof that a malformed declaration fails safe — judgeable by the operator
without a single new server route.

## Contradictions / open questions found against the brief

- **KEAP's `tableViewStyleSchema` doesn't accept `chat`** (noted in the ask
  as already known) — until that lands, `caddy-sessions.table.yml` cannot
  declare `style: chat` from KEAP's side; the face client resolves it fine,
  but KEAP's own authoring validator would reject the block. This blocks
  step 1 of §5 at the KEAP repo, not the face repo — flag it, don't design
  around it silently.
- **`caddy-sessions.chain` is `kind: text`**, i.e. a JSON string column, not
  a nested table. §1's "nested grid for the chain" needs either a real
  sub-table (new KEAP concept) or a client-side JSON.parse-and-render of the
  text column — the latter is smaller and is what "one afternoon" in §5
  assumes; note it explicitly so nobody expects a KEAP schema change for v1.

## One component sketch — the chain-as-nested-grid

```svelte
<!-- inside the chat body slot, when body.kind === 'text' and JSON-parses -->
<script lang="ts">
  import { resolveView } from '$lib/tables/view';
  export let raw: string; // caddy-sessions.chain cell
  let steps: { step: number; tool: string; args: string; result: string }[] = [];
  try { steps = JSON.parse(raw); } catch { steps = []; }
  const chainTable = {
    slug: 'chain-inline', title: 'Chain', source: 'fallback' as const,
    columns: [
      { key: 'step', label: 'Step', kind: 'number' as const },
      { key: 'tool', label: 'Tool', kind: 'text' as const },
      { key: 'result', label: 'Result', kind: 'text' as const }
    ],
    rows: steps.map((s, i) => ({ id: String(i), ...s }))
  };
  $: view = resolveView(chainTable);
</script>

{#if steps.length}
  <!-- reuse the grid renderer already used for every other table -->
  <GridView table={chainTable} {view} />
{:else}
  <pre>{raw}</pre>
{/if}
```

No new render style, no new contract field — `resolveView`/`GridView` are
the same functions every DataTable already calls.
