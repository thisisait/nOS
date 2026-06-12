# nOS Fleet Mode — Review & Reconciliation (2026-05-30)

> Operator asked: *"the playbook must be able to spin up an inventory of
> servers as needed when it is the 'main' node and fleet mode is on (p2p /
> server-client / mesh) — maybe it's called something else now, do a review."*
>
> This is that review. It reconciles the aspirational design
> ([fleet-architecture.md](fleet-architecture.md)) with what the code actually
> does today, confirms the naming, maps the three topologies onto the existing
> substrate, and recommends a phased path. **No live config was broken — the
> staleness this review was expected to find mostly isn't real (see §5).**

## 1. Naming — it IS "fleet mode" (Track F)

The feature is not hiding under another name. Today's surface:

- **Config:** `instance_name` / `instance_role` (standalone | headquarters |
  factory | office | division) / `instance_parent`, `provider_admin_email`,
  `provider_tailscale_tag`, `configure_heartbeat`, `heartbeat_endpoint`
  (`default.config.yml` ~ll. 99-116, 196-197).
- **Roadmap:** **Track F** (`docs/roadmap-2026q2.md`) — scoped narrowly to the
  FQDN-composition half (`host_alias`).
- **Design:** `docs/fleet-architecture.md` (the full provider→client→box vision).

There is **no** `main_node` / `leader` / `controller` / `swarm` / `node_role`
terminology in code. The specific capability the operator described — *a main
node that spins up an inventory of other servers* — has **no name and no
implementation**. It is genuinely greenfield; this review proposes calling it
**fleet provisioning** (or **fleet controller mode**) to distinguish it from
the existing telemetry/identity "fleet mode".

## 2. What exists today

| Capability | State | Evidence |
|---|---|---|
| `host_alias` / `tenant_domain` FQDN decomposition (many boxes share a TLD with distinct hostnames) | **Built, works** | `default.config.yml` ll. 22-78; `_host_alias_seg` used across 69 files |
| Instance identity vars (`instance_name/role/org/location`) | **Built** (labels only) | `default.config.yml` ll. 99-101 |
| `instance_parent` (hierarchy slug) | **Declared, dead** | no consumer (`git grep` → config + docs only) |
| Tailscale (WireGuard) install | **Partial — interactive only** | `tasks/tailscale.yml` installs the cask + prints a "log in by hand" debug msg; `tailscale_auth_key` is declared but **never read** → no automated join, no ACL/tagging |
| Heartbeat daemon | **Partial — TX only, gated off** | `files/heartbeat/heartbeat.py` POSTs box status; `configure_heartbeat: false` by default; **no receiver/aggregator exists anywhere** |
| Bone `POST /api/run-tag` | **Built — local only** | `files/anatomy/bone/main.py` runs `ansible-playbook main.yml --tags <tag>` on the **local** host against the **local** inventory; no `-i`/`--limit`, cannot target a peer |
| Multi-host inventory | **Greenfield** | `inventory` is a single `127.0.0.1 ansible_connection=local`; `tests/inventory` likewise; no host groups |
| Main-node / leader logic | **Greenfield** | none |
| Heartbeat receiver / fleet dashboard | **Greenfield** | TX half only; `files/anatomy/bone/state.py:50` marks the central aggregator "future" |
| Authentik federation, Puter fleet UI | **Greenfield / aspirational** | `fleet-architecture.md` §4-5 |

**Bottom line:** the *transport-and-identity scaffolding* exists (Tailscale,
instance vars, FQDN namespacing, a one-way heartbeat, a local run-tag hook).
The *control plane* — inventory of peers, a main node that provisions them, and
the receiver that aggregates their state — does not.

## 3. The three topologies, mapped onto nOS

| Topology | Meaning for an AIT fleet | Maps onto | Near-term priority |
|---|---|---|---|
| **server-client** (provider → client / hub-spoke) | A main/provider node provisions and manages client boxes; per-client CEO autonomy below it. This is the `fleet-architecture.md` model. | **Control-plane decision (§4):** push (main runs Ansible against `[fleet_nodes]` over Tailscale SSH) *or* pull (central caller hits each box's Bone `/api/run-tag`). | **Recommended first** — matches the existing role model + Bone hook |
| **mesh** | Every node peers with every other; the provider has ACL-gated reach to all. | **Tailscale (WireGuard) is already the intended substrate.** Mesh is the *transport*, not the *control plane* — server-client/p2p ride on top of it. | Substrate work (automate Tailscale join) is the shared prerequisite |
| **p2p** | Nodes as equals, no central authority; each runs its own playbook; coordination via shared/gossiped state + heartbeat. | Needs a distributed state-merge (the `nos_state` framework + heartbeat could seed it) and conflict resolution. | **Lowest** — least defined, highest design cost |

The cleanest framing: **Tailscale = mesh transport for all three**; the
topology choice is really *"who decides what runs where"* — and that's the
server-client-vs-p2p (centralised-vs-peer) control-plane decision in §4.

## 4. The control-plane decision (operator input needed)

"Main node spins up an inventory of servers" needs ONE of:

- **(A) Push model** — the main node runs `ansible-playbook` against a
  `[fleet_nodes]` inventory group over Tailscale SSH (`--limit`, per-host
  `config.yml`). Classic Ansible; main node needs SSH reach + each node's vars.
- **(B) Pull model** — a central orchestrator calls each node's authenticated
  Bone `POST /api/run-tag` over Tailscale; each node re-runs its **local**
  playbook. The repo already leans this way (Bone exists, run-tag exists).

Either way the **heartbeat receiver** (the missing RX half) is needed — scope
it as a Wing `/fleet` view consuming Bone-aggregated peer state.

**Recommendation:** start **server-client + pull (B)**, because the Bone
`/api/run-tag` hook already exists and per-node-local-playbook keeps each box
self-describing (no central inventory of every node's secrets). Push (A) can be
added later for bootstrap/imaging.

## 5. Staleness check — what this review did NOT need to fix

The brief expected stale fleet config. Most of it isn't:

- **Heartbeat `SERVICE_REGISTRY` path is correct, NOT stale.** The plist +
  `heartbeat.py` default `~/projects/default/service-registry.json` is exactly
  where `tasks/service-registry.yml`, `export-state.yml`, `import-state.yml` and
  `blank-reset.yml` all read/write it; the live file exists (18 KB, current).
  Blindly "fixing" this path would have **broken** it.
- **No live `czechbot.eu` endpoint.** `heartbeat_endpoint` defaults to `""`; the
  only `czechbot.eu` references are in the **aspirational** `fleet-architecture.md`
  (pre-rebrand prose), not in any live config. → a doc refresh, not a code fix.
- **Real gap that IS worth closing:** `tasks/heartbeat.yml` deploys a launchd
  plist with **no systemd-user branch** — so heartbeat is macOS-only, blocking a
  mixed Mac/Linux fleet (the operator's "Pi runner managing Macs" vision). This
  belongs to the Linux port (`docs/linux-port.md`), not this review.

## 6. Recommended phased path

- **F0 — this review.** Reconcile (done). Operator decides push-vs-pull (§4) and
  which topology leads (recommend server-client).
- **F1 — scaffolding, opt-in, ZERO change to the single-box default** *(ready to
  build once F0 is decided)*:
  - a fleet inventory **example** (`[fleet_main]` = localhost + empty
    `[fleet_nodes]`, commented), opt-in via `-i`; `ansible.cfg` keeps pointing at
    the localhost-only `inventory` so existing runs are byte-for-byte unchanged;
  - `fleet_mode` (default `false`) + `node_role` (default `standalone`) vars with
    a documented contract + a no-op guarded block;
  - wire the **already-declared-but-unused** `tailscale_auth_key` into
    `tasks/tailscale.yml` for non-interactive `tailscale up --authkey`
    (`--advertise-tags={{ provider_tailscale_tag }}`); promote to a
    `pazny.tailscale` role. This turns the mesh substrate from manual to
    automatable — the real foundation for any fleet.
- **F2 — control plane** (push or pull per F0) + the heartbeat **receiver**
  (Wing `/fleet` view; the RX half that doesn't exist yet).
- **F3 — Authentik federation + Puter fleet UI** (aspirational; `fleet-architecture.md` §4-5).
- **Cross-cutting:** a mixed-OS fleet depends on the Linux port — heartbeat
  needs a systemd-user branch; OpenClaw/Hermes are still Darwin-gated.

## 7. What changed with this review

- This document (the reconciliation the operator asked for).
- A pointer header added to `fleet-architecture.md` flagging it as the
  pre-rebrand **aspirational design**, superseded for current-state accuracy by
  this review.
- **No live config edited** — §5 explains why the expected staleness fixes were
  either wrong (registry path) or doc-only (czechbot.eu).
