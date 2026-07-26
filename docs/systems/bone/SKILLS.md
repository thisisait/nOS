# Bone — Skills

> Callable actions on the Bone host organ. Base URL `http://localhost:8099`. Privileged routes need `Authorization: Bearer <jwt>` from Authentik `client_credentials` with the stated scope; the events sink uses HMAC over `bone_secret`.

## check-liveness

**Trigger:** "is Bone up", "bone health", "check the bone daemon"
**Method:** API
**Endpoint:** `GET /api/health`
**Auth:** none (ungated liveness)
**Output:** `{"status":"ok","uptime":<seconds>,"auth_ready":<bool>}`

## check-aggregate-health

**Trigger:** "cluster health", "are all services healthy", "aggregate health"
**Method:** API
**Endpoint:** `GET /api/health/aggregate`
**Auth:** Bearer JWT, scope `nos:state:read`
**Output:** `{"status":"ok|degraded","services":[...],"healthy":<n>,"unhealthy":<n>}`

## read-state

**Trigger:** "read nOS state", "what is the runtime state", "get state"
**Method:** API
**Endpoint:** `GET /api/state`
**Auth:** Bearer JWT, scope `nos:state:read`
**Output:** The merged runtime state document (`~/.nos/state.yml`).

## list-services

**Trigger:** "list registered services", "service registry", "what services are known"
**Method:** API
**Endpoint:** `GET /api/state/services`
**Auth:** Bearer JWT, scope `nos:state:read`
**Output:** The canonical service list. (`GET /api/services` returns the raw `service-registry.json`, same scope.)

## run-tag

**Trigger:** "run the playbook tag", "converge tag", "apply tag"
**Method:** API
**Endpoint:** `POST /api/run-tag?tag=<tag>`
**Auth:** Bearer JWT, scope `nos:run-tag`
**Input:** `tag` — must match `^[A-Za-z][A-Za-z0-9_,-]{0,99}$` (rejects flag-like values).
**Output:** `{"tag":"...","returncode":<int>,"output":"<tail of stdout>"}`
**Effect:** Runs `ansible-playbook main.yml --tags <tag>` on the host (real mutation; 600s timeout).

## plan-upgrade

**Trigger:** "plan an upgrade", "preview upgrade recipe", "dry-run upgrade"
**Method:** API
**Endpoint:** `POST /api/upgrades/{service}/{recipe_id}/plan`
**Auth:** Bearer JWT
**Output:** The upgrade plan (no side effects). List recipes with `GET /api/upgrades/{service}`.

## apply-upgrade

**Trigger:** "apply the upgrade", "run upgrade recipe"
**Method:** API
**Endpoint:** `POST /api/upgrades/{service}/{recipe_id}/apply` (or `/apply-detached`)
**Auth:** Bearer JWT
**Effect:** Executes the recipe's `apply` phase — NOT a dry-run. Plan first.

## preview-migration

**Trigger:** "preview a migration", "what would this migration do"
**Method:** API
**Endpoint:** `POST /api/migrations/{migration_id}/preview`
**Auth:** Bearer JWT
**Output:** The migration preview. Apply with `POST /api/migrations/{migration_id}/apply`; undo with `/rollback`.

## emit-event

**Trigger:** "record a telemetry event", "send an event to Bone", "log to the timeline"
**Method:** API
**Endpoint:** `POST /api/v1/events`
**Auth:** HMAC — `X-Wing-Timestamp: <unix>` + `X-Wing-Signature: sha256=<hmac(bone_secret, "{ts}.{canonical-json-body}")>`
**Input:** Single event object, or a batch `{"events":[...]}`. Body is canonicalised (`json.dumps(sort_keys, separators=",:")`) before signing.
**Output:** Persisted event row (sinks to the Wing SQLite store); readable via `GET /api/events`.

## post-notification

**Trigger:** "raise a notification", "queue an alert", "notify the operator"
**Method:** API
**Endpoint:** `POST /api/v1/notifications`
**Auth:** HMAC — `X-Wing-Timestamp` + `X-Wing-Signature` (as for events)
**Input:** `{severity: critical|high|medium|low|info, title, body?, channels?, target_actor_id?}`; batches as `{"notifications":[...]}`.
**Output:** Queued notification; the wing-base Pulse worker dispatches it to `wing-inbox` / `ntfy` / `mail` per the routing sidecar.
