# Jellyfin — Skills

> Callable actions for Jellyfin. Each skill is API-first using `openclaw-bot` API key.

## Authentication

- **Method:** API key
- **Token:** `~/agents/tokens/jellyfin.token`
- **Base URL:** `https://media.dev.local`
- **Header:** `X-Emby-Token: <api-key>`

---

## list-libraries

**Trigger:** "list libraries", "show media collections", "what libraries exist"
**Method:** API
**Endpoint:** `GET /Library/VirtualFolders`
**Input:** None
**Output:** `[{ "Name": "Movies", "CollectionType": "movies", "ItemId": "...", "Locations": [...] }]`

---

## search-media

**Trigger:** "search for movie", "find song", "look up [title]"
**Method:** API
**Endpoint:** `GET /Items`
**Input:** Query params: `searchTerm` (required), `IncludeItemTypes` (optional, e.g. `Movie,Series,Audio`), `Recursive` (`true`), `Limit` (optional)
**Output:** `{ "Items": [{ "Id": "...", "Name": "...", "Type": "Movie", "ProductionYear": 2024, "Overview": "..." }], "TotalRecordCount": 5 }`

---

## get-playback-info

**Trigger:** "get stream URL", "playback info for", "how to play [title]"
**Method:** API
**Endpoint:** `GET /Items/<id>/PlaybackInfo`
**Input:** Item ID
**Output:** `{ "MediaSources": [{ "Id": "...", "Path": "...", "Container": "mkv", "Size": 1234567890 }] }`
