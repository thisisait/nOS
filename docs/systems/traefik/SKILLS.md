# Traefik — Skills

> **Read-only introspection only.** Traefik's dashboard API (`api.insecure: true`) is bound to `127.0.0.1:8082` and exposes GET-only endpoints for inspecting live routers, services and health. Routing is **not** mutated through this API — it flows through the file provider (`conf.d/`, auto-derived from `state/manifest.yml`) and Docker labels. There is no create/update/delete skill because there is no write surface.

## Access

- **Base URL:** `http://127.0.0.1:8082` (loopback only)
- **Auth:** none (the loopback bind is the access control)

---

## health-ping

**Trigger:** "is Traefik up", "is the edge proxy alive", "check Traefik health"
**Method:** API (read-only)
**Endpoint:** `GET /ping`
**Input:** none
**Output:** `200 OK` with body `OK`

---

## get-overview

**Trigger:** "Traefik overview", "how many routers/services are loaded", "edge proxy summary"
**Method:** API (read-only)
**Endpoint:** `GET /api/overview`
**Input:** none
**Output:** counts of routers, services, middlewares and enabled providers/features

---

## list-http-routers

**Trigger:** "list Traefik routers", "which routes are live", "is <service> routed", "show HTTP routers"
**Method:** API (read-only)
**Endpoint:** `GET /api/http/routers`
**Input:** none
**Output:** a list of router objects, each with `name`, `rule` (the Host match), `service`, `middlewares`, `status` (`enabled`/`disabled`), and `provider` (`file` or `docker`)

---

## list-http-services

**Trigger:** "list Traefik services", "show upstream backends", "what does <router> forward to"
**Method:** API (read-only)
**Endpoint:** `GET /api/http/services`
**Input:** none
**Output:** `[{ "name": "...", "loadBalancer": { "servers": [{ "url": "http://nos-host:<port>" }] }, "serverStatus": {...}, "provider": "file|docker" }]`

---

## get-rawdata

**Trigger:** "dump Traefik config", "full router/service/middleware state", "debug Traefik routing"
**Method:** API (read-only)
**Endpoint:** `GET /api/rawdata`
**Input:** none
**Output:** the complete live routers + services + middlewares graph (all providers)

---

## No write skills

There is intentionally no add-route / set-middleware / reload skill. To change routing:
- **Tier-1:** edit the manifest-derived render; `conf.d/services.yml` + `middlewares.yml` are watched (`watch: true`) and hot-reload.
- **Tier-2:** add router labels to the app's compose service (Docker provider).

Both paths go through the playbook, never a live API write.
