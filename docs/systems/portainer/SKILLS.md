# Portainer — Skills

> Callable actions for Portainer. API-first using JWT token.

## Authentication

- **Method:** Bearer JWT (obtained via `POST /api/auth`)
- **Token:** `~/agents/tokens/portainer.token`
- **Base URL:** `https://portainer.dev.local`

---

## list-containers

**Trigger:** "list containers", "show running services", "what's running"
**Method:** API
**Endpoint:** `GET /api/endpoints/1/docker/containers/json?all=true`
**Input:** None
**Output:** `[{ "Id": "...", "Names": ["/name"], "State": "running", "Status": "Up 2 hours" }]`

---

## restart-container

**Trigger:** "restart [service]", "bounce [container]"
**Method:** API
**Endpoint:** `POST /api/endpoints/1/docker/containers/{id}/restart`
**Input:** Container ID
**Output:** `204 No Content`

---

## container-logs

**Trigger:** "show logs for [service]", "check [container] logs"
**Method:** API
**Endpoint:** `GET /api/endpoints/1/docker/containers/{id}/logs?stdout=true&stderr=true&tail=100`
**Input:** Container ID, tail count
**Output:** Raw log text

---

## list-stacks

**Trigger:** "list stacks", "show deployed stacks"
**Method:** API
**Endpoint:** `GET /api/stacks`
**Input:** None
**Output:** `[{ "Id": 1, "Name": "infra", "Status": 1, "CreationDate": "..." }]`

---

## container-stats

**Trigger:** "resource usage", "how much memory is [service] using"
**Method:** API
**Endpoint:** `GET /api/endpoints/1/docker/containers/{id}/stats?stream=false`
**Input:** Container ID
**Output:** CPU, memory, network, block IO stats
