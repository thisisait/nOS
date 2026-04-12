# WordPress — Skills

> Callable actions for WordPress. Each skill is API-first using `openclaw-bot` Application Password.

## Authentication

- **Method:** Basic auth (Application Password)
- **Token:** `~/agents/tokens/wordpress.token`
- **Base URL:** `https://wp.dev.local`
- **Header:** `Authorization: Basic <base64(openclaw-bot:app-password)>`

---

## list-posts

**Trigger:** "list posts", "show recent articles", "what has been published"
**Method:** API
**Endpoint:** `GET /wp-json/wp/v2/posts`
**Input:** Query params: `search` (optional), `per_page` (optional), `status` (optional)
**Output:** `[{ "id": 1, "title": { "rendered": "..." }, "status": "publish", "date": "...", "link": "..." }]`

---

## create-post

**Trigger:** "create post", "write article", "publish new post"
**Method:** API
**Endpoint:** `POST /wp-json/wp/v2/posts`
**Input:**
```json
{
  "title": "<post title>",
  "content": "<HTML content>",
  "status": "draft",
  "categories": [<category_id>],
  "tags": [<tag_id>]
}
```
**Output:** Created post object with `id` and `link`

---

## list-pages

**Trigger:** "list pages", "show all pages", "what pages exist"
**Method:** API
**Endpoint:** `GET /wp-json/wp/v2/pages`
**Input:** Query params: `search` (optional), `per_page` (optional)
**Output:** `[{ "id": 1, "title": { "rendered": "..." }, "status": "publish", "link": "..." }]`

---

## manage-media

**Trigger:** "upload image", "list media", "add attachment"
**Method:** API
**Endpoint:** `POST /wp-json/wp/v2/media` (upload), `GET /wp-json/wp/v2/media` (list)
**Input (upload):**
- Header: `Content-Disposition: attachment; filename="<name>"`
- Body: binary file data
- Content-Type: `image/jpeg`, `image/png`, etc.

**Input (list):** Query params: `search` (optional), `media_type` (optional)
**Output:** `[{ "id": 1, "title": { "rendered": "..." }, "source_url": "...", "media_type": "image" }]`
