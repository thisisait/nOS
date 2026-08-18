# 16 — Onboarding an agent is five declarations, and nothing names the set

**Status: AFFORDABLE HALF PAID 2026-08-18** (the gate). The structural close —
one derived source — remains open. Filed the same day from the surveyor
onboarding (2026-08-17); one symptom of the shape paid then too (the runner's
silent audit-POST failure — see occurrence in
[07](07-messages-that-outlive-their-mode.md) and
`tests/anatomy/test_wing_event_post_failure_is_not_silent.py`).

> **The gate found a live instance on the run that introduced it.** `curator`
> had asked for `WING_API_TOKEN: "{{ curator_wing_api_token }}"` in its pulse
> env since it shipped. The secret was templated, present in
> `default.credentials.yml`, the Authentik client existed and the pulse catalog
> knew the name — and `roles/pazny.wing/tasks/post.yml` mentioned curator zero
> times, so the `api_tokens` row was never written and Wing would have rejected
> the token at request time. **Four of five declarations in place**, every gate
> green, and the only signal available was a 401 at 02:00.
>
> Gate: `tests/anatomy/test_an_agent_is_wired_everywhere_it_asks_to_be.py`. It
> triggers on the agent's OWN declaration — an agent that asks for a token is
> checked everywhere, one that does not (`migration-author`,
> `upgrade-advisor`, `upgrade-architect` run operator-driven) is not checked at
> all. So it cannot be satisfied by editing the gate: there is no list here to
> add a name to, only the agent to wire or the request to withdraw.

## The fee

A new claude-CLI agent is not one thing. To exist it must be declared in (at
least) five places, none of which references the others:

1. **Authentik client** — `nos-<agent>` in the agent-clients blueprint /
   OpenTofu registry (`30-agent-clients.yaml.j2`; cited from
   `roles/pazny.wing/tasks/post.yml:304` as "pre-provisioned").
2. **Wing API token secret** — a `<agent>_wing_api_token` var that must reach
   `~/.nos/secrets.yml` under the name every runner will guess later.
3. **Wing token provisioning** — a per-agent `provision-token.php` task block
   in `roles/pazny.wing/tasks/post.yml` (conductor `:221`, surveyor `:302`,
   drift-watch `:284`, … — the file grows one hand-written block per agent).
4. **Pulse catalog substitution** — the token table AND the POST body in
   `wing/tasks/post.yml` (two allow-lists; memory
   `pulse-catalog-literal-substitution` records missing either one twice).
5. **Pulse job env** — `env_json` in the plugin's `pulse_jobs:` block
   (`NOS_AGENT_*`, model pin, scopes).

Nothing validates the set. Miss one and every gate stays green — the failure
arrives at runtime, deep inside `pulse-run-agent.sh`, as ONE symptom naming
ONE layer (`NOS_AGENT_CLIENT_SECRET is not set`, a 403 on the first scoped
call, a token POST that 401s) with no indication that the cause is "the set
is incomplete". The 2026-08-17 surveyor run demonstrated the adjacent cost:
a ceremony can complete, cost $0.96, and still be wired wrongly enough that
its audit trail never lands.

## The rule this bills against

A thing that exists only as the intersection of N declarations needs either a
single declaration it is derived from, or a gate that checks the intersection.
This estate already learned it once at smaller N: the pulse-catalog two-list
lesson (memory `pulse-catalog-literal-substitution`).

## What paying it off looks like

- **One source:** the agent's own `agent.yml` (already schema-gated) grows the
  onboarding facets (client id, secret var name, pulse env), and post.yml /
  catalog / blueprint render FROM it — the same aggregate-and-render move the
  plugin loader made for `authentik:` blocks in Track Q.
- **Or one gate:** a pytest that, for every `files/anatomy/agents/<name>/`,
  asserts all five declaration sites mention the agent — cheap, catches the
  missing-member failure at commit time instead of at 02:00.

The gate is the affordable first step; the single source is the structural
close. Until one exists, every new agent re-runs this gauntlet from memory.
