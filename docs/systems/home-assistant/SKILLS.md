# Home Assistant — Skills

> Callable actions for Home Assistant. API-first using Long-Lived Access Token.

## Authentication

- **Method:** Bearer token (Long-Lived Access Token)
- **Token:** `~/agents/tokens/home-assistant.token`
- **Base URL:** `https://home.dev.local`
- **Header:** `Authorization: Bearer <token>`

---

## get-states

**Trigger:** "show all devices", "what's the state of [entity]"
**Method:** API
**Endpoint:** `GET /api/states` or `GET /api/states/{entity_id}`
**Input:** Optional entity_id (e.g., `light.living_room`)
**Output:** `{ "entity_id": "...", "state": "on", "attributes": {...} }`

---

## call-service

**Trigger:** "turn on [device]", "set [entity] to [value]", "toggle [switch]"
**Method:** API
**Endpoint:** `POST /api/services/{domain}/{service}`
**Input:**
```json
{
  "entity_id": "light.living_room",
  "brightness": 255
}
```
**Output:** Updated state array

**Example:**
```
"Turn on living room light"
POST /api/services/light/turn_on
{ "entity_id": "light.living_room" }
```

---

## trigger-automation

**Trigger:** "run automation [name]", "trigger [automation]"
**Method:** API
**Endpoint:** `POST /api/services/automation/trigger`
**Input:** `{ "entity_id": "automation.morning_routine" }`
**Output:** Updated state

---

## activate-scene

**Trigger:** "activate scene [name]", "set mood [scene]"
**Method:** API
**Endpoint:** `POST /api/services/scene/turn_on`
**Input:** `{ "entity_id": "scene.movie_night" }`
**Output:** Scene activated

---

## get-history

**Trigger:** "show history for [entity]", "what happened with [sensor]"
**Method:** API
**Endpoint:** `GET /api/history/period/{timestamp}?filter_entity_id={entity_id}`
**Input:** Entity ID, timestamp range
**Output:** Array of state changes over time

---

## fire-event

**Trigger:** "fire event [type]", "send custom event"
**Method:** API
**Endpoint:** `POST /api/events/{event_type}`
**Input:** `{ "key": "value" }` (event data)
**Output:** `{ "message": "Event fired." }`

---

## list-automations

**Trigger:** "show automations", "list all automations"
**Method:** API
**Endpoint:** `GET /api/states` (filter by `automation.*`)
**Input:** None
**Output:** List of automation entities with state (on/off) and last triggered
