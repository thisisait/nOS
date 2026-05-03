# Anatomy of nOS

> The body-of-nOS metaphor — how the internal systems are named, what each
> one does, and where new capabilities land as the organism grows.
> Branding reference for https://thisisait.eu ("This is AIT — Agentic IT").

---

## The body

nOS is not a monolith. It's a small body of cooperating services, each with
one job, each named after the organ that performs the analogous role in a
living thing. New capabilities land as new organs, not as new flags.

```
                       ┌─────────────┐
                       │    BRAIN    │  LLM orchestration, policy,
                       │  (planned)  │  decision-making, vector memory
                       └──────┬──────┘  (Qdrant, OpenClaw, Hermes,
                              │          Ollama, MLX)
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
        │   WING    │   │   BONE    │   │    GUT    │
        │  defense  │   │ structure │   │ digestion │
        │           │   │           │   │ (planned) │
        │ pentest   │   │ HTTP API  │   │ RSS feeds │
        │ CVE feed  │   │ subprocess│   │ log ingest│
        │ advisory  │   │ dispatch  │   │ metrics   │
        │ upgrade   │   │ state     │   │ telemetry │
        │  observ.  │   │  ingester │   │ normalize │
        └───────────┘   └───────────┘   └───────────┘
                              │
                              │
                       ┌──────▼──────┐
                       │  PLAYBOOK   │  Ansible — the nervous system
                       │   (main.yml)│  wiring every organ together
                       └─────────────┘
```

---

## Organ roster

### BONE  *(the skeleton — holds the stack together across time)*

Formerly **BoxAPI**. The local FastAPI service every other organ talks to
when it needs to touch disk, run Ansible, or read state.

- **Role of the role**: fronts the on-disk truth (`~/.nos/state.yml`,
  `recipes/*`) and the only process allowed to shell out to
  `ansible-playbook` in this codebase.
- **Files**: current/pre-R role `roles/pazny.bone/`, target role `n_os.anatomy.bone`; source `files/anatomy/bone/`
- **Vars prefix**: `bone_*` (e.g. `bone_port`, `bone_api_key_env`)
- **Env prefix**: `BONE_*` (formerly `BOXAPI_*`)
- **Service label**: `eu.thisisait.bone` (launchd)
- **HTTP port**: `8069`
- **API surface**: `/api/state`, `/api/events`, `/api/migrations/*`,
  `/api/upgrades/*`, `/api/patches/*`, `/api/coexistence/*`
- **Why "bone"**: bones persist. They carry load, they don't ingest, they
  don't decide. Bone is the schema — the skeleton the soft tissue hangs on.
  Silent 99 % of the time; the story only gets interesting when something
  else asks it to move.

### WING  *(the defense organ — pentest, advisory, observability)*

Formerly **Glasswing**. The read model. The place humans click to answer
*what's installed, what's pending, what just happened, what's dual-running*.

- **Role of the role**: security-research dashboard + maintenance control
  panel. Reads the SQLite mirror of `events`, `migrations_applied`,
  `upgrades_applied`, `patches_applied`, `coexistence_tracks`. Proxies
  command actions (apply, cutover, …) through Bone.
- **Files**: current/pre-R role `roles/pazny.wing/`, target role `n_os.anatomy.wing`; source `files/anatomy/wing/`
- **Vars prefix**: `wing_*`
- **Env prefix**: `WING_*` (formerly `GLASSWING_*`)
- **Callback plugin**: `callback_plugins/wing_telemetry.py`
- **Service label**: `eu.thisisait.wing` (launchd)
- **HTTP port**: `8070`
- **Public hostname**: `wing.dev.local`
- **API surface**: `/api/v1/events`, `/api/v1/state/*`,
  `/api/v1/migrations/*`, `/api/v1/upgrades/*`, `/api/v1/patches/*`,
  `/api/v1/coexistence/*`, `/api/v1/dashboard/summary`
- **Why "wing"**: wings are the organ of sensing and reaction — they catch
  wind, they warn of predators, they carry the body out of danger. Wing's
  job is the same: see CVEs/advisories/pentest findings/upgrade drift
  coming and surface them to the pilot (the human). Glasswing was the
  original name; its insect wings are translucent and full of veins, which
  is how an observability UI should feel.

### GUT  *(planned — data ingestion and normalization)*

Placeholder. Gut eats raw data (RSS feeds, upstream changelogs, CVE feeds,
log streams from the playbook runs, system metrics) and breaks it down
into rows Wing and Brain can use.

- **Likely files**: `roles/pazny.gut/`, `files/gut/`
- **Likely vars prefix**: `gut_*`
- **Likely env prefix**: `GUT_*`
- **Not yet built.** When it lands, it will sit between the external world
  and Wing, so Wing doesn't have to do raw HTTP scraping inside its
  presenters. Candidates for in-scope: RSS → advisory ingest, GitHub
  release polling, log aggregation from `~/.nos/events.sqlite`, metric
  scraping from observability roles.

### BRAIN  *(planned — LLM orchestration and decision-making)*

Placeholder. Brain is the superior layer that can ask Bone to do things,
read from Wing, and reason over memory held in Gut.

- **Likely files**: `roles/pazny.brain/`, `files/brain/`
- **Likely vars prefix**: `brain_*`
- **Likely env prefix**: `BRAIN_*`
- **Likely ingredients**: OpenClaw (agentic shell), Hermes (tool-calling
  adapter), Ollama (local LLM runtime), Apple MLX (on-device inference),
  Qdrant (vector memory store).
- **Not yet built.** The first step here is probably a thin
  `brain-chat` surface that proxies to Ollama/OpenClaw/Hermes, with
  Qdrant as long-term memory and Wing's SQLite as short-term recall.

---

## Naming conventions

Rule of thumb: **every organ owns exactly one verb, one noun, one
prefix**, and that prefix repeats everywhere.

For an organ named `<organ>` (lowercase, ≤ 5 chars):

| Surface | Rule | Example (bone) |
|---|---|---|
| Ansible role | current/pre-R: `roles/pazny.<organ>/`; target for control-plane organs: `n_os.anatomy.<organ>` | `pazny.bone` → `n_os.anatomy.bone` |
| Role files | `files/anatomy/<organ>/` for control-plane source | `files/anatomy/bone/` |
| Ansible var prefix | `<organ>_*` | `bone_port`, `bone_api_key_env` |
| Install toggle | `install_<organ>` | `install_bone: true` |
| Environment variable prefix | `<ORGAN>_*` | `BONE_PORT`, `BONE_API_KEY` |
| Launchd / systemd label | `eu.thisisait.<organ>` | `eu.thisisait.bone` |
| Docker container | `data-<organ>-*` or `<organ>-*` (by stack) | `data-bone-1` |
| Local hostname | `<organ>.dev.local` | `bone.dev.local`, `wing.dev.local` |
| PHP namespace | `App\Model\<Organ>Client` | `App\Model\BoneClient` |
| Callback plugin | `callback_plugins/<organ>_telemetry.py` | `wing_telemetry.py` |
| Docs page | `docs/<organ>-integration.md` or `docs/<organ>-plan.md` | `docs/wing-integration.md` |

Exceptions kept on purpose:

- **Service installer roles stay outside anatomy namespace.** `pazny.grafana`
  and other Tier-1 services remain ordinary bones until Track Q thins them;
  Tendons&Vessels live in `files/anatomy/plugins/<service>-base/`, not inside
  the service role.
- **HTTP API paths don't change** when an organ renames. `/api/v1/state`
  stays `/api/v1/state`. External consumers don't care what we call the
  organ — they care about the contract.
- **Database schema doesn't change.** Tables (`events`,
  `migrations_applied`, `upgrades_applied`, `patches_applied`,
  `coexistence_tracks`) are content, not identity. No renames.
- **Event schema properties don't change.** `migration_id`, `upgrade_id`,
  `patch_id`, `coexistence_service` are IDs, not brands.

---

## Adding a new organ — recipe

The patch suite (see `docs/integration-map.md` §*Extending the map*) is the
reference procedure for adding one more capability *inside* an existing
organ. Adding a *new organ* is one level up:

1. **Declare it here first.** Add a section in this file: what it does,
   one sentence. If the sentence has an "and" in it, the organ is two
   organs.
2. **Reserve the prefix.** Pick a ≤ 5-char lowercase name; sanity-check
   it isn't already used as a var prefix, role name, or table name.
3. **Boot the skeleton**:
   - `n_os.anatomy.<organ>` control-plane role (current pre-R compatibility may still use `roles/pazny.<organ>/`)
   - `files/anatomy/<organ>/` (code)
   - Add `install_<organ>` toggle to `default.config.yml`
   - Wire it into `main.yml` (usually last, so its inputs are ready)
4. **Give it a state block.** Decide which key it owns in
   `~/.nos/state.yml` (e.g. Bone owns `services{}` and
   `{migrations,upgrades,patches}_applied[]`; Wing owns nothing there —
   it's downstream).
5. **Register it in Wing** if it has a UI surface:
   - `App\Model\<Organ>Repository` (if it has persistent records)
   - `App\Presenters\Api\<Organ>Presenter` (if it has a REST surface)
   - Dashboard block (if it contributes a KPI)
6. **Add its event types** to `state/schema/event.schema.json` and
   `App\Model\EventRepository::VALID_TYPES`. Add its tag regex to
   `callback_plugins/wing_telemetry.py`.
7. **Document it.** Add a row to the suite matrix in
   `docs/integration-map.md`.

---

## Public branding

The project manifest at https://thisisait.eu frames this codebase as
**AIT — Agentic IT**. Internally we talk about *organs* (bone, wing, gut,
brain); on the marketing surface we keep the organism framing:

- **nOS** — the whole body (our internal services + the FOSS services
  provisioned through the playbook).
- **AIT** — the discipline: Agentic IT, the practice of letting the
  playbook-plus-LLM loop own day-two operations.
- **This is AIT** — the manifesto voice ( https://thisisait.eu ).

Visualization candidate for the web presentation: a mythical creature
(sketch: dragon-ish or chimera, TBD) whose organs carry the organ names
above, rendered as hover-enabled regions of a central illustration. Each
region links to its docs page and its Wing dashboard view.

---

## See also

- [`integration-map.md`](integration-map.md) — suite-by-suite data flow.
- [`framework-plan.md`](framework-plan.md) — framework design narrative.
- [`framework-overview.md`](framework-overview.md) — reader's introduction.
- https://thisisait.eu — public manifesto.
