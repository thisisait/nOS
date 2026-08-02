# Calling the engine

Read this before any `nos-loop` skill. It is the **only** file in this plugin
that names an address, a port or a credential; the four skills name none, so a
change here changes all of them at once and cannot change one of them silently.

Authoritative source for everything below: `docs/idea/11-agentic-loop-contract.md`.
This file is a *client's* view of that contract. Where the two disagree, the
contract wins and this file is the bug.

## What the engine is

Modules inside **Bone** (`files/anatomy/bone/`), mounted on Bone's existing
FastAPI app. Not a new daemon, not a new port, not a new manifest entry, no edge
route. The loop deliberately has no routable surface — REM-144 was an
unauthenticated API on the edge leaking the password prefix, and the cheapest way
to satisfy "loopback only" is to add nothing that can be routed.

## Base URL — resolve it, do not memorise it

Bone's port is a variable (`bone_port`), and pointing at the wrong one has been
shipped three times in this estate (gitleaks, authentik-tofu-drift, conductor —
each an emitter aimed at Wing's 9000, each 401ing silently, one for seventeen
days). So resolve, in this order:

1. `$BONE_API_URL` if exported.
2. `bone_port` from the repo's `config.yml`, else `default.config.yml`.
3. Only then the documented default below.

```bash
BASE="${BONE_API_URL:-http://127.0.0.1:$(
  awk '$1=="bone_port:"{print $2; exit}' config.yml default.config.yml 2>/dev/null \
  || echo 8099)}"
```

`127.0.0.1` is not a preference. Bone binds loopback (`bone.plist.j2`) and is in
`traefik_skip_ids`; a loop URL with a hostname in it is a defect, not a variant.

## Tokens — two, never one

Constraint A ("the judge is code, the proposer is a model, and they never share
an identity") is enforced at the credential level, not in prose:

| identity | secret key | scopes | which skill holds it |
|---|---|---|---|
| proposer | `loop_propose_token` | `read`, `propose` | `weakness-scan`, `propose` |
| evaluator | `loop_judge_token` | `read`, `judge` | `judge` |

Both live in `~/.nos/secrets.yml` (0600), minted random by `main.yml` — never
`{prefix}_pw_*`, and Bone refuses a `_pw_`-shaped value at runtime as well as in
the repo gate.

```bash
tok() { awk -v k="$1:" '$1==k{print $2}' ~/.nos/secrets.yml | tr -d '"'; }
# use inline; never echo a token, never paste one into a report or a devlog
curl -sS -H "Authorization: Bearer $(tok loop_propose_token)" "$BASE/..."
```

A skill reads **only its own** token. That boundary is thin on a single-UID host —
the contract says so plainly (§3.3: no filesystem separation is claimed) — but it
is the boundary Hermes and a Pulse job will inherit, and it costs nothing to keep
straight from the start.

## Endpoints

| method + path | scope | returns |
|---|---|---|
| `GET /api/v1/loop/weaknesses` | read | ranked findings, each with `weakness_id` + `evidence_sha` |
| `GET /api/v1/loop/budget` | read | allowed roots, forbidden paths, size caps |
| `POST /api/v1/loop/proposals` | propose | `201` uuid + fingerprint · `409` refused |
| `POST /api/v1/loop/judge` | judge | `202` + `run_id` (async — one judge is 190 s) |
| `GET /api/v1/loop/judge/{run_id}` | read | `running`, or a verdict with per-judge evidence |
| `GET /api/v1/loop/history` | read | prior attempts at a fingerprint, and their verdicts |

There is **no endpoint that accepts a verdict.** That is the design, not an
omission: a route that takes a `result` and distinguishes writers by credential
is a lock whose key is a header. You cannot forge a value you are never asked to
supply.

**Not all of these are mounted yet.** At the time this plugin was written only
`GET /weaknesses` answers; the rest 404 until the engine's build steps 1, 2 and 4
land their routes. A 404 here is fail-closed and it is the truth — **report it and
stop**. Do not simulate a call, do not fall back to running a judge by hand, and
do not describe a cycle as having run.

## Vocabulary you must not compress

**A verdict has three values: `pass`, `fail`, `indeterminate`.** Never map
`indeterminate` onto either neighbour. It means a judge did no work or could not
run — an unplugged organ, an absent token, a sandbox that would not create. Call
it `fail` and the loop learns to "fix" a proposal in response to a down service;
call it `pass` and you have rebuilt the exact defect the loop exists to detect
(`docs/hidden_fees/08` — absence reading as success).

HTTP answers, and what each means for you:

| code | meaning | what you do |
|---|---|---|
| `201` / `202` | accepted | carry the returned id forward |
| `403` | wrong identity for that route | **the boundary working.** Do not fetch the other token |
| `409` | refused — budget or fingerprint | stop; quote the engine's reason |
| `503` | tokens not configured | report; do not work around |
| `404` | route not mounted yet | report; do not substitute |

## The one rule this file has

**Everything a skill might decide, the engine already decided.** Path budgets,
size caps, the intent-class enum, dedup, ranking, what counts as work, what a
gate set contains — none of it is written down in this plugin, on purpose. Ask
the engine and quote its answer. Anything you keep here is something Hermes,
which will call the same addresses with no Claude in the picture, will not have.
