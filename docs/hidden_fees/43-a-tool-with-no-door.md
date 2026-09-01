# 43 — A capability that shipped complete, gated, documented and unspendable

**Status:** PAID 2026-09-01, same day it was found. Gate:
`tests/anatomy/test_exec_is_spendable.py`.

## The fee

`ExecTool` — the caddy's primary tool, one cortex-lang sentence per call — was
built, registered in `common.neon`, added to `agent.schema.yaml`'s tool enum,
given a 238-line adversarial gate of its own, and **would have returned HTTP 403
on every call, for every agent, from the moment it deployed**.

`CortexExecutorPresenter::startup` refuses any bearer missing ANY of the three
cortex capability axes, deliberately and correctly:

```php
$this->capability = CortexCapability::fromToken($this->validatedToken);
if ($this->capability === null) {
    $this->sendError('this token carries no cortex capability. …a token that is
        powerful elsewhere is not a way in.', 403);
}
```

The tool presents `NOS_AGENT_WING_TOKEN`. Exactly one row in
`roles/pazny.wing/tasks/post.yml` carried cortex axes — `cortex-executor`, a
service principal with no `agent.yml` and therefore no agent to present it. Nine
agent tokens, none with a cortex column. The door was built and every key was
cut for a different lock.

## Why nothing caught it

The three declarations that had to agree live in three files, in three
languages, and **no artifact compared any two of them**:

| declaration | file | says |
|---|---|---|
| `tools: [exec]` | `files/anatomy/agents/jeff/agent.yml` | who may call it |
| `--cortex-verbs/…` | `roles/pazny.wing/tasks/post.yml` | whose token the route accepts |
| `requiredScopes()` | `ExecTool.php` | what the registry admits |

Each gate present was internally satisfied. `ToolRegistry` checks scope 1 against
scope 3 and both were consistent. `test_the_mint_matches_the_manifest.py`
compares `wing.*` scopes and says in its own docstring that the cortex axis is
"declared in exactly ONE place… a gap this gate can only report, not close."

**And the tool's own gate could not see it either**, which is the part worth
keeping. `test_exec_adds_no_capability.py` drives the real class over a Guzzle
`MockHandler`: it proves what goes ON THE WIRE — one route, `{source, commit:false}`,
`confirm` refused before any request — and a mock answers 200 to a bearer no real
route would accept. A check that cannot fail for the reason the thing is broken
is not weaker evidence, it is evidence about a different question. The mock gate
is right and stays; what was missing was anyone asking whether the principal it
hands over is one the estate ever minted.

## What was paid

* `jeff_wing_api_token` — registry entry, credential, `main.yml` reconcile,
  `secrets.yml.j2` row, and a mint task carrying all three axes (`get,resolve,
  map,filter,rank,classify` × `tax,rel` × `default` — the executor's own P1
  surface, `db:` deliberately absent).
* `jeff-cloud` gets NO such row. Executing is local, but the ROWS return into the
  model's context, and for the cloud twin that is estate ontology leaving the
  machine — an Article-30 fact, not a setting.
* The gate: agents holding `exec` **equal** agents minted a complete cortex
  token. Equality, so it fails both ways — a holder with no token 403s and reads
  the refusal as an estate fact; a mint with no holder is a standing grant
  nobody spends. Plus: a partial mint (verbs, no namespaces) is refused, because
  `fromToken` returns null on a half-written grant while the task looks like it
  opened something.

## The general shape, which is why this is a fee and not a bug

Three separate 2026-08/09 findings share it: `conductor` minted
`wing.read,wing.write` for an agent holding no write tool; `dispatched_at`
stamped by the sender; and this. **A declaration that nothing contradicts is not
a declaration that anything checked.** The estate's rule — a success marker is
written by a reader, never by the code that attempted the work — has a corollary
this file is the evidence for: *a capability is proven by the principal that can
spend it, never by the file that declares it.*

## Still open

Nothing here proves the LIVE `api_tokens` row. That needs a converged host, and
`test_the_mint_matches_the_manifest.py` already owns that comparison — it will
pick the new row up on the next run against a converged estate. The first real
`exec` call has not happened.
