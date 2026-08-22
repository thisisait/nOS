# 20 — Reading BagelHole/DevOps-Security-Agent-Skills against this estate

**Read 2026-08-22.** MIT, 324 stars, 163 `SKILL.md` files, created 2026-01-27,
**last pushed 2026-05-22 — three months dormant**, 933 KB total (~5.8 KB/skill,
163 files across 15 commits, so bulk-authored rather than individually earned).

The question was not "is it good" but **"where is it ahead of us"**. Answer: one
place, measurably. Everything else it describes, this estate either does not run
or already enforces more strongly.

## Where it is ahead — container runtime hardening

Measured across all 53 `roles/pazny.*/templates/compose.yml.j2`:

```
security_opt      0
cap_drop          0
read_only: true   1
user:             2
```

Fifty-three services, **not one** declares `no-new-privileges`, drops a single
capability, or runs read-only. `security/hardening/container-hardening` is a thin
document (102 lines, generic) but the practice it names is ahead of ours because
ours is zero. `security/ai/mcp-server-security` §10.3 carries a seccomp profile;
we set none anywhere.

This is not theoretical for us. cAdvisor ran `privileged: true`, uid 0, docker
socket live, host `/` at `/rootfs` — **and `SecurityOpt label=disable`**, i.e. it
actively switched a control off. It was found by a human reading a compose
template, not by any gate. (It is gone as of the 2026-08-22 converge, REM-197.)

**Second, smaller:** `§8 Rate Limiting` (per-client + token budget). REM-169 is
open and says zero rate limiting on 28 of 30 Tier-1 routers. Their patterns are a
usable starting point for a row we already have.

## Where this estate is ahead, and it is most of the document

`security/ai/ai-coding-agent-guardrails` (1138 lines) is the one most relevant to
the loop, and section by section we already do it harder:

| their section | their mechanism | ours |
| --- | --- | --- |
| Command Allowlists | a `.cursorrules` file | `budget.py` ALLOWED_ROOTS + deny rules, pulse command allow-list checked **twice** (registration and spawn) |
| File System Access Controls | prose + globs | `budget.py` path rules, judge sandboxes, the loop's `files/anatomy/bone/**` self-deny |
| Code Review Gates | a GitHub Actions workflow | judge gate sets with a WORM verdict chain, `loop-review.py`'s three questions, `_refuse_master`, `_owns_remote_tip` |
| Branch Protection for Agent Branches | branch rules | a server ruleset **plus** four-holder forge topology with a base-equality preflight in both directions |
| Secret Protection | git-secrets pre-commit + output scanning | gitleaks nightly, the BFF allow-list projection (57 secrets stopped), `no_log`, HKDF derivation, a canary designed |
| Audit Logging | structured logs + OTel | a hash-chained WORM audit table with `actor_action_id` lineage joining agent, event and run |

Their `prompt-injection-defense` offers regex detection
(`ignore\s+previous\s+instructions`) as its concrete technique. That is the class
of control this estate refuses on principle: it produces confidence rather than
safety. The five principles above it — instruction hierarchy, context
segregation, tool permissioning, output policy, human approval — are sound, and
we implement three of them in code.

One thing worth recording: their principle #5 is *"human approval required for
high-impact operations"*, which is exactly the gap found here independently the
day before — `requires_operator` is stamped by the ledger and read by no acting
code (`loop-requires-operator`). An outside document naming your own finding is
corroboration, not news, but it is worth writing down.

## Verdict: read four, adopt none

**Do not pull, do not copy into `.claude/skills/`.** A skill is loaded into the
context of agents that hold credentials, write code and open merge requests.
Adding 163 unvalidated third-party instruction files to that surface is a
supply-chain decision, and this estate runs `npm-supply-chain:daily-ioc-scan`
nightly because it takes that seriously. Ninety percent of the corpus is inert
here anyway — Kubernetes, AWS/Azure/GCP, Datadog, New Relic, Vercel, Firebase,
PlanetScale; we run Docker Compose, LGTM and our own metal.

**Read as reference, once:** `security/scanning/{sbom-supply-chain,
vulnerability-scanning, container-scanning, dependency-scanning}`. These are
concrete — `syft`/`grype`/`cosign` invocations, CycloneDX vs SPDX — and they
land on a named gap: CLAUDE.md records `inspektor` as deferred pending "a
trivy/grype/nuclei substrate plugin". That is a spec input, not a dependency.

## What goes to Q2

1. **A container hardening baseline** across the 53 templates:
   `security_opt: ["no-new-privileges:true"]` everywhere, `cap_drop: [ALL]` with
   per-service `cap_add`, `read_only: true` where the service tolerates it. This
   is genuinely a multi-day change — dropping capabilities breaks services in
   ways only a converge finds — and it must be ratcheted, not attempted in one
   sweep.
2. **The `inspektor` substrate plugin**, spec'd from their scanning skills.
3. **Rate limiting**, folded into REM-169 rather than filed fresh.

## What was NOT done today, and why

The obvious move — start adding `security_opt` to compose templates — was
deliberately not taken. A converge was running while this was read, and editing
the templates it is applying is how a half-applied estate happens. The hardening
baseline is a Q2 item with its own ratchet, not an afternoon.

## The full sweep — because the first pass was a sample, not a read

The first version of this file judged 163 skills after reading **six**, and
estimated "~90% inert" from filenames. Challenged on it, the repo was cloned and
searched. The estimate was directionally right and is now earned:

**Corpus:** 163 `SKILL.md`, 69,477 lines, median 410, min 100, max 1253.

**How much of it touches this estate**, counted across every file:

```
authentik  0    gitea  0    woodpecker  0    keycloak  0    litestream  0    borg  0
ansible    1    ← the thing nOS IS
sqlite     2    launchd  3    traefik  3    restic  3    ollama  5    oidc  11
nginx     28    systemd 19   docker compose 19   (generic, mostly Linux/k8s framing)
```

**The technique cluster that is real:** trivy 16 · mtls 12 · canary 10 · grype 8 ·
seccomp 7 · cosign 6 · no-new-privileges 6 · sigstore 4 · syft 4 · slsa 4.

**Two candidates chased to a clean no:**

* `canary` (10 files) looked like it might serve `sec-p3`. It is **deployment**
  canary — traffic splits, `canaryTrafficPercent`, kubectl rollouts. Not a
  honeytoken. Nothing for us.
* `model-supply-chain-security` (402 lines) looked like the gem: we pull four
  models from a public registry and verify nothing about them. But it is written
  for **publishers** — sign your own weights with cosign, SLSA provenance for
  training, Kyverno admission control. We are consumers. Ollama stores blobs
  content-addressed (`sha256-…`), so integrity holds by construction; what is
  missing is *authenticity*, and upstream offers no signing for this path. The
  skill does not close that.

**And one where they are simply behind:** `gdpr-compliance` (560 lines) has nine
sections — legal bases, Article 30 mapping, consent, DSAR, DPA, DPIA, checklist.
Every one is already covered here, DPIA included (identified in
`docs/compliance/gov-readiness-audit-2026q2.md`).

**No gem.** The sweep was still worth its hour: it turned two maybes into
defensible noes, and it replaced an assertion about 163 files with a count.

## A correction, recorded because the method matters

The first pass of this read reported **three** privileged containers, from
`grep -l "privileged: *true"` across the templates. Wrong three ways: woodpecker's
match is a COMMENT describing REM-002 hardening that already shipped;
homeassistant's is behind `homeassistant_privileged`, which resolves to `false`;
and live, `docker inspect` finds exactly **one** — `infra-docker-socket-proxy-1`,
which is REM-212's mitigation surface.

Matching text instead of code, in a document about a repository whose own
weakness is bulk-authored text. The estate's own rule caught it, one layer up,
the same afternoon it caught the same bug in `test_config_stock_jinja_only.py`.
