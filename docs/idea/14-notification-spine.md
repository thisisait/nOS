# 14 — One notification spine

**Status: items 2 and 3 shipped 2026-08-08 (Click link + tool-path
notification fix; A11 retired into /inbox). Item 1 was found unsound under
adversarial review the same day and is re-scoped below — its safe kernel
(refuse anonymous answers) shipped; the chat reply path is deliberately NOT
built. No channel carries an answer back yet, and the plan no longer
pretends one is a small step away.**

> One abstract channel. Chats, mail, approval surfaces and alerts are
> implementations of it — not four systems that each grew a notifier.

## The shape

```
        an event happens
               │
      ┌────────┴────────┐
      │   THE SPINE     │   severity · actor · actor_action_id · POINTER
      └────────┬────────┘
     ┌─────────┼─────────┐
  transports          surfaces
  ntfy · mail         approvals · questions
  chat · inbox        alerts · digest
```

Two stores, and the split is the whole design:

| | holds | why it cannot be the other |
|---|---|---|
| `events` | the **lineage** — append-only | audit, judges and SERE read it; it must never be edited |
| `agent_questions` | the **resolution** — one row | an append-only log cannot enforce resolve-once |

That second line is not a preference. A11 `/approvals` is the demonstration:
two operators clicking Approve at the same instant both *append* a decision
event, and `EventRepository::listPendingApprovals` filters on merely **having**
one. Approve + reject reads as "decided", and the winner is whichever the reader
sees first. Nothing detects it.

So the resolution lives in one row closed by a conditional `UPDATE`, and the
event is emitted **only on the winning write**. The table is not a second copy
of the lineage — it holds the one fact the lineage structurally cannot.

## The standing invariant

**A notification is a POINTER, NOT A PAYLOAD.**

Everything downstream rests on it. ntfy's edge gate was removed so a phone can
subscribe (a push client cannot complete an Authentik browser flow), which means
a subscribe credential now lives on a device that gets lost. The safety argument
is that a stolen one buys a list of *"something happened"* and never the
something. Pinned by `test_a_notification_is_a_pointer.py`.

This was learned the expensive way on 2026-08-08: the reply token was written
into notification metadata, which `GET /api/v1/notifications` returns verbatim,
and conductor holds `mcp-wing`. The agent could have read the credential that
answers its own question. Getting the hard part right (hashing at rest, one file
away) is what made the easy part invisible.

## Shipped

| | commit |
|---|---|
| `agent_questions` + resolve-once + first-responder-wins + deadline-in-WHERE | `aa8a234c` |
| `ask_operator` tool; token never reaches the model | `78d3e25c` |
| both P0s from adversarial review (tool never loaded; token in notifications) | `0831fc4e` |
| ntfy auth actually enforced; publisher ≠ admin | `798231cc` |
| edge gate removed for mobile; pointer-not-payload gated | `277eabd8` |
| approvals and questions become one surface; lineage events | `4590dc48` |
| `/inbox` answers; `Inbox:markRead` finally has a route | `3dbede9d` |
| Click link + the tool path finally notifies (item 2 + the gap) | `00dd2bd9` |
| A11 retired: /approvals → /inbox, one resolution store (item 3) | `fdeaf2c8` |
| anonymous answers refused; the cited gate now exists (item 1 kernel) | (with this doc) |

## What is left — the completion plan, as reviewed 2026-08-08

Three items. The original order (2 → 1 → 3) rested on two claims that did not
survive review: *"the link must exist before a channel carries it"* (the chat
path never carries the click link) and *"A11 must not be retired until
something else does its job"* (something else already did — `4590dc48` +
`3dbede9d` shipped /inbox answering, including approvals, before this plan was
written). The executed order was **2 → 3 → 1-kernel**: smallest first, the
retirement blocked on nothing, and the chat path turned out not to be
buildable safely at all today.

---

### 1. Chat reply path — REVIEWED AND RE-SCOPED (2026-08-08)

The item as first written was wrong three ways, each checked against the
estate rather than the plan's own prose:

- **`[q:<token>]` puts the credential in the chat.** A Telegram reply lives in
  Telegram's message history on Telegram's servers — the same class of
  resting-place as the metadata leak this feature already shipped and
  retracted once. The plan's own trap list forbids the token in a URL and in
  `notifications`, then writes it into a chat protocol. A human replying to a
  question must reference it by uuid; only software may hold a credential.
- **"Hermes must fetch the token by a path that authenticates Hermes" is
  impossible.** The token exists in plaintext exactly once, in `ask()`'s
  return value; only its SHA-256 is at rest. Wing structurally cannot hand it
  out later. Only handed-at-ask-time could work — which requires a
  per-question credential store inside the gateway.
- **Hermes cannot safely hold ANY answer credential today.** Hermes is
  upstream git-cloned software (`NousResearch/hermes-agent`); the only
  execution surface this repo controls inside it is LLM-facing `SKILL.md`
  instructions, and its tool executor runs with the daemon's env. A reply
  credential in `~/.hermes/.env` — per-question token or Hermes-as-itself
  service credential alike — is a credential inside an LLM agent's reach,
  the same defect class as the reply token in a ToolResult. And measured
  live: no Telegram/Discord channel is configured (`~/.hermes/config.yaml`),
  so the acceptance criterion could not even be observed.

**What the answer looks like when it is built** (not now, and not by a skill):
a *deterministic* channel adapter — non-LLM code parsing `[q:<uuid>] yes`
before any model sees the message — that authenticates AS ITSELF with its own
minted credential (blast-radius rules: minted + persisted via
`templates/secrets.yml.j2`, never prefix-derived) against an adapter-specific
Wing path, maps the chat identity to an operator from an explicit allowlist,
and **refuses** unmapped identities. Hermes-as-itself makes the per-question
token unnecessary for that caller; the token stays for a session-less HTTP
orchestrator that filed the question itself and holds the 201 body.

**What shipped now — the kernel that was true regardless of transport:**
`POST /api/v1/inbox/questions/<uuid>/answer` refuses an anonymous identity.
`answered_by` is required, must not be `unknown`, and must not be shaped
`agent:*` / `channel:*`; the old silent fallback to the bearer token's name (a
service, not a person) is gone. Pinned by
`test_only_a_gated_presenter_answers_without_a_token.py` — a gate the
repository docblock had cited for hours before it existed.

---

### 2. The `Click` link — SHIPPED 2026-08-08, plus the hole the plan missed

**What.** Every question notification carries
`Click: <WING_PUBLIC_URL>/inbox` (`WING_PUBLIC_URL=https://{{ wing_domain }}`,
provisioned in both the launchd plist and the systemd `wing.env`; empty env →
no Click header, never a fabricated URL).

**What the plan missed, and was the bigger half of the work:** the flagship
ask path never notified anyone. The notification insert lived only in
`Api\InboxPresenter` — but `AskOperatorTool` talks to the repository directly
(deliberately, so the token never rides an HTTP response) and the repository
inserted nothing. A tool-asked question reached no phone and no mailbox; it
sat open until its deadline and then decided itself. The insert (with the
never-quieter-than-`high` floor and the click_url) now lives in
`AgentQuestionRepository::ask()`, the one place both ask paths share — same
argument as the in-process event emit: what must not drift from the ask lives
with the ask.

**Decisions taken, not discovered:** the link is Tier-1-only, matching
/inbox's `$minAccessTier = 1` — answering authorises an agent, so the
deciding surface stays gated; a lower-tier read view is not worth a second
surface. The URL carries no credential and no per-question addressing.

Pinned by `test_a_question_notification_carries_a_click.py` (retro-red: 4/5
tests failed against the pre-fix tree). `test_a_notification_is_a_pointer`
still passes; the credential gates followed the insert to its new home.

---

### 3. Retire A11 `/approvals` — SHIPPED 2026-08-08

**What shipped.** `ApprovalsPresenter` + its template + its **three** routes
(the plan said two — approve, reject, AND the bare list route) are gone;
`/approvals` permanently redirects to `/inbox`; approvals are
`kind='approval'` questions rendered there with Approve/Reject.

**Why it was safe** — re-verified at implementation time against the live
`wing.db` (read with its `-wal`): **zero** `agent_approval_*` events, and the
`agent_questions` table did not exist live yet either, so nothing could have
raced in since the plan measured.

**What the plan under-scoped:** "the presenter and its two routes" was maybe a
third of the surface. Also readers of A11: the `@layout` nav tab (key 3, now
deliberately unassigned) with its `pendingApprovalsCount` badge, the
BasePresenter badge query (`EventRepository::countPendingApprovals` — the
badge now counts OPEN QUESTIONS via `AgentQuestionRepository::countOpen`,
deadline-aware so the tab number cannot disagree with the page), the
Dashboard "Pending approvals" stat, `EventRepository`'s three approval
readers (deleted — "pending" is a resolution question the event log cannot
answer race-free), and **six** test files naming the presenter or template.
A naive "delete and 404" would have left a dead nav tab and five red gates.

**Kept, as planned:** the `agent_approval_request` / `_decision` event types —
emitted by `AgentQuestionRepository`, decision only on the winning UPDATE.
The rewritten `test_approval_queue_event_backed.py` (retro-red against the
pre-retirement tree) pins: surface gone, legacy URL redirects, still no
second approval store in the schema, the event types survive with exactly ONE
writer, and the decision emit sits inside the `$affected === 1` branch.
AdminPresenter still carries A11's HMAC-post shape (empty-secret return +
discarded curl result) for halt/resume events — known debt, recorded in its
docblock, deliberately not folded into this retirement. Neither was the
orphan ntfy Authentik provider.

---

## Gotchas for whoever implements this

Learned today, each the hard way:

1. **A gate must read code, never prose.** Four gates written for this feature
   failed against correct code — twice because the search region was too wide,
   twice because they matched their own explanatory comment (one block contained
   `reply_token` only because the comment said *"NO reply_token"*). Strip
   comments; scope to the smallest syntactic unit.
2. **`php -l` does not load a class.** `AskOperatorTool` passed lint and fataled
   on load for want of one `use`. Eight grep-only tests were green against it.
   `test_every_registered_tool_actually_loads.py` executes PHP now — keep it that
   way.
3. **An unroutable `{plink}` renders as `#`.** `Inbox:markRead` had no route and
   nothing had been marked read since May. Check `action="…"` on the live page
   whenever a form ships.
4. **Read `wing.db` with its `-wal`.** `cp wing.db` alone reports a
   checkpoint-old snapshot as current. Use
   `sqlite3 "file:…/wing.db?mode=ro"`.
5. **Pulse env tokens must be BARE.** The catalog does literal substitution, not
   Jinja; `{{ x | default(y) }}` reaches Wing verbatim and 400s. Three gates
   enforce this and it still caught a fresh mistake.
6. **A new prefix-derived credential trips the blast-radius ratchet.** Mint and
   persist instead — and add it to `templates/secrets.yml.j2`, or it churns every
   converge.

## What would prove the whole thing works

Not a green suite. One question, asked by a real agent on a real run, notified to
a phone, answered from a chat, with the lineage showing a single decision, the
right `operator_username`, the channel it came back through, and
`waited_seconds` — the one number the loop cannot reconstruct afterwards,
because the row is append-only and the moment has passed.
