# Qdrant — Skills

## Authentication

- **Method:** API key header `api-key: <QDRANT__SERVICE__API_KEY>` (read-only callers use `QDRANT__SERVICE__READ_ONLY_API_KEY`). Resolved by apps_runner from `apps/qdrant.yml` magic tokens.

## Search a collection by vector

**Trigger:** an agent needs the nearest prior findings/systems/advisories to a piece of text it already embedded.
**Method:** `POST http://127.0.0.1:6333/collections/<name>/points/search`
**Body:** `{"vector": [...], "limit": 10, "with_payload": true}`
**Returns:** scored points, highest similarity first. An empty `result` is a real answer — report it as one.

## List collections

**Trigger:** an agent needs to know what has been embedded at all before trusting a miss.
**Method:** `GET http://127.0.0.1:6333/collections`
**Returns:** collection names. Nothing here implies freshness — the canonical stores decide that.
