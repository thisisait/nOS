# 18 — A second environment: VPS, local VM, or neither yet

**Status: assessment, not a plan.** Written 2026-08-19 on the operator's
question: would a "fixed" virtualization of the nOS core stop the friction —
and, newly, would a rented VPS be the better second environment for real e2e
tests? Roadmap context: `sere-a` shipped, `sere-b` **blocked**, `sere-c`
queued ("the live estate is a mutex, not a test bed").

## Conclusion first

**Neither, yet.** A second environment of either kind is bought with the same
prerequisite, and that prerequisite is the actual blocker: `sere-b`'s Linux
wet-test passes an **empty estate** — `docker compose up infra` returns rc=1,
the STRICT health probe reads `0/0 ready` as green, and the job stayed green
for weeks with no containers at all (`docs/hidden_fees/08`, CLAUDE.md Known
Tech Debt). Until a second environment can FAIL, adding one adds a surface
that certifies nothing while costing money (VPS) or RAM (VM). The first move
is therefore not procurement: it is making the health gate refuse `0/0`, then
proving one stack (infra) actually converges on a non-Mac host. That work is
identical whether the host is a VPS or a VM, so it postpones nothing. Once a
second environment can prove something, **the VPS is the better first buy**
for this host — and note the friction that motivated the question is mostly
not drift at all: today's expensive incidents (the 598 KB desynced-base MR,
the hand-typed promotion) were git-topology defects, now enforced by
`tools/forge-sync.py` + the driver preflight, and no second environment would
have prevented them.

## What a VPS buys that a local VM does not

- **Real isolation from the mutex.** One Mac, one Docker daemon, one Traefik
  on :443 (`sere-c`). A VM still shares the M4 Max's 36 GB with ~50 resident
  containers plus a resident Ollama model; the measured budget on this host
  says a 14B model alone pushed KEAP to timeout. A full second estate
  (~50 containers, GitLab alone wants several GB) inside a VM on this machine
  is not a test bed, it is a way to make BOTH estates flaky.
- **A genuinely different substrate.** Linux kernel, real ext4 instead of
  VirtioFS (which already broke restic and puma in ways only a real second
  substrate surfaced), public DNS reachability — the Bluesky federation and
  LE-certificate paths are untestable on `.local` at home.
- **Always-on.** A nightly `nos --remove=data --confirm` blank-and-converge —
  the single most valuable test nOS can run — cannot run on the operator's
  daily driver, ever. That is the test that catches what the CI runner's
  empty estate cannot.

## What a local VM buys that a VPS does not

- **Free macOS coverage.** nOS's primary target is macOS/Apple Silicon; a VPS
  is Linux. M3+ nested virtualization makes a macOS VM technically possible,
  and only a macOS guest tests the launchd organs, Homebrew paths and Docker
  Desktop specifics. But RAM is the binding constraint: a macOS guest wants
  8–16 GB to be honest, on a host already committed.
- **No new attack/cost surface.** No monthly bill, no public IP to harden, no
  second secrets custody problem.
- **Snapshot/restore** — cheap "fixed" baselines. This is the drift argument,
  and it is the weakest one: drift on THIS estate (the dead Woodpecker OAuth
  client, the rejected Gitea token, the ghost agent rows) is drift of the
  LIVE system; a pristine VM image tells you what a fresh install looks like,
  which the blank-reset path already proves, and says nothing about the
  estate that actually serves.

## What it costs to make a second environment prove something

1. **Close the empty-estate read** (`sere-b` items 1–3): the health probe
   must treat `0/0 ready` and a failed compose render as RED. Days, not
   weeks; entirely local work.
2. **A Linux-honest stack subset.** The full 50-service estate will not fit a
   cheap VPS; a committed profile (infra + observability + one app stack,
   ~4 GB) is the realistic wet-test target. `profiles/` already has the
   pattern.
3. **Secrets and identity for a second estate.** A second
   `~/.nos/secrets.yml`, a second Authentik realm, and a rule that the two
   estates never share a credential — the P1 lesson at estate scale.
4. **Something that reads the result.** A green converge nobody reads is the
   drift-watch lesson again; the nightly result must land in the Wing inbox
   as one row, red or green.

## What I would do first

1. Make `stack-health-probe.py` refuse `0/0` (closes `sere-b`'s lie; also
   fixes the CI claim). 2. Prove `tools/nos-stacks.sh infra` converges in a
   Linux container/VM locally — zero spend. 3. Only then rent the smallest
   VPS that fits the committed profile (~8 GB / 4 vCPU) and give it the
   nightly blank-and-converge; keep macOS coverage on the existing (honest,
   `continue-on-error`) GitHub runner until a self-hosted Mac runner is worth
   its keep. A local macOS VM stays the answer to a question nobody is
   currently blocked on.
