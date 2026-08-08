# 14 — One notification spine

**Status: half built. The write half ships; no channel carries an answer back yet.**

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

## What is left — the completion plan

Three items. **Order matters: 2 → 1 → 3.** The link must exist before a channel
carries it, and A11 must not be retired until something else does its job.

---

### 1. Hermes reply path — answer from a chat

**What.** A `[q:<token>]` reply in Telegram/Discord resolves the question.
Hermes is the cross-channel gateway; it holds the channel session and can
identify the human. It `POST`s `/api/v1/inbox/questions/<uuid>/answer` with the
reply token.

**Why the token exists at all.** This is the *only* caller that needs it. Wing
uses the Authentik session (stronger: it names a person). The token is for the
operator with no session — in Telegram at 23:00.

**Traps, all verified today:**

- **The token reaches nobody today.** `deliver_ntfy` sends `Title`, `Priority`,
  `Tags`, `Click` and has never read `metadata.reply_token`; the mail path reads
  title/body/severity. The token is minted, hashed at rest, and delivered
  nowhere. Any design that assumes it currently arrives is wrong.
- **It must not travel through `notifications`.** That table is returned in full
  by `GET /api/v1/notifications` to any bearer caller. Hermes must fetch the
  token by a path that authenticates Hermes, or be handed it at ask time.
- **`answered_by` must name a human, not a channel.** `channel:telegram` is an
  audit dead end. Map the chat identity to an operator; if it cannot be mapped,
  refuse rather than record an anonymous approval.
- **`answered_via` already exists** and is emitted into the lineage — use it.

**Acceptance.** A question asked by an agent is answered from a chat message;
`events` shows exactly one decision with `via: telegram` and a real
`operator_username`; a second reply to the same question is refused with the
answer that won.

---

### 2. The `Click` link — a notification you can act on

**What.** Every question notification carries
`Click: https://wing.<tld>/inbox`, so the phone notification opens the queue.

**Why first.** It is small, it closes the operator's original ask (*"přijde
notifikace s odkazem"*), and it is the honest interim answer while 1 is
unbuilt: the link goes to a surface that authenticates the reader, so it needs
no credential at all.

**Traps:**

- **Never put the token in the URL.** A click URL lands in `metadata`, in ntfy's
  server cache, and in the phone's notification history. The link points at
  `/inbox`; the *reader* is authenticated there.
- **`deliver_ntfy` already supports `Click`** — it reads `metadata.click_url`.
  The presenter simply never sets it. This is one field, not a feature.
- **`/inbox` is now `minAccessTier = 1`.** A link that 403s for a Tier-2
  operator is worse than no link; either the link is Tier-1-only or the queue
  gains a lower-tier read view. Decide, do not discover.

**Acceptance.** A phone notification for a question opens `/inbox` with that
question visible. The URL contains no credential. `test_a_notification_is_a_pointer`
still passes.

---

### 3. Retire A11 `/approvals`

**What.** `ApprovalsPresenter` and its two routes go away; approvals are
`kind='approval'` questions rendered by `/inbox`.

**Why it is safe.** Measured 2026-08-08: the live estate holds **zero**
`agent_approval_*` events. The surface has never been used, so there is nothing
to migrate. Its own gate named the trigger for revisiting — *"a SECOND surface
that programmatically gates on approvals"* — and `agents-inbox` is it.

**Traps:**

- **Its decision path has two silent failures**, and they are the reason to
  retire rather than repair: `postDecision` returns early on an empty
  `WING_EVENTS_HMAC_SECRET`, and then does `curl_exec($ch);` discarding the
  result. During the secret desync found this morning, every decision would have
  401'd in silence. Nothing would have said so.
- **`test_approval_queue_event_backed.py` must be rewritten, not deleted.** Its
  three assertions encode a real decision. Replace them with the successor
  contract; a deleted gate reads as a lifted constraint.
- **The event types stay.** `agent_approval_request` / `_decision` are still
  emitted for `kind='approval'`, so every audit query keyed on them survives.
- **The orphan Authentik provider** for ntfy (recorded in
  `PROVIDER_NOT_EDGE_ATTACHED`) is unrelated debt — do not fold it in.

**Acceptance.** `/approvals` returns 404 or redirects to `/inbox`; an approval
asked via `ask_operator` renders with Approve/Reject; the rewritten gate fails if
a second approval store appears.

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
