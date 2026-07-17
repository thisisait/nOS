"""devlog_lib — shared WordPress REST + Bone event client for the devlog.

Consumed by files/anatomy/scripts/devlog-sync.py (playbook sync engine) and
tools/devlog-post.py (on-site namespace writes / the /devlog skill helper).
stdlib-only on purpose: runs on the host python with no venv.

Audit doctrine (docs/devlog/README.md): every WordPress write travels through
these clients so the matching Bone event (actor_id=agent:devlog) is never
skipped. Bone HMAC bodies are canonical JSON — separators=(",", ":") +
sort_keys=True — because Bone re-serializes the parsed dict the same way
before verifying (the 2026-05-17 canonical-JSON lesson).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ACTOR_ID = "agent:devlog"
HASH_MARKER = "nos-devlog-hash:"


class WPError(RuntimeError):
    pass


class WPClient:
    """Minimal WordPress REST v2 client (Application Password basic auth)."""

    def __init__(self, base_url: str, user: str, app_password: str, timeout: int = 20):
        self.base = base_url.rstrip("/")
        token = base64.b64encode(f"{user}:{app_password}".encode()).decode()
        self._auth = f"Basic {token}"
        self.timeout = timeout
        # WP_BASE_URL is loopback (http://127.0.0.1:<port>), but WordPress redirects
        # http→https on the SAME host (siteurl is the public https domain), so the
        # loopback leg presents a cert for the DOMAIN, not the IP → urllib's default
        # verify raises "certificate is not valid for '127.0.0.1'" (blank died here at
        # ok=1496, 2026-07-17). This is a LOCAL, app-password-authed call to loopback;
        # verifying a public-domain cert against 127.0.0.1 is meaningless. Skip verify
        # for LOOPBACK ONLY — a non-loopback base_url still verifies normally.
        self._ssl_ctx = None
        host = (urllib.parse.urlparse(base_url).hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        # Use the "unpretty" ?rest_route= endpoint, NOT the pretty /wp-json/
        # permalink. WP_BASE_URL is loopback http, but the permalink form triggers
        # WordPress's canonical redirect (trailing-slash + http→https to the PUBLIC
        # domain https://wordpress.<tld>) — and the host can't resolve that domain,
        # so the call dies (blank ok=1496, 2026-07-17: "certificate is not valid for
        # 127.0.0.1" then a cross-host 301). ?rest_route= bypasses the permalink/
        # redirect layer entirely → 200 on plain loopback http, no headers needed.
        route = urllib.parse.quote(f"/wp/v2{path}", safe="/")
        url = f"{self.base}/?rest_route={route}"
        if params:
            url += "&" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(
                req, timeout=self.timeout, context=self._ssl_ctx
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "null")
                return payload, dict(resp.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise WPError(f"{method} {path} -> {exc.code}: {detail}") from None

    def me(self) -> dict:
        data, _ = self._request("GET", "/users/me", params={"context": "edit"})
        return data

    def _ensure_term(self, taxonomy: str, slug: str, name: str, parent: int | None = None) -> int:
        data, _ = self._request("GET", f"/{taxonomy}", params={"slug": slug, "per_page": 100})
        for term in data:
            if term["slug"] == slug:
                return term["id"]
        body: dict = {"slug": slug, "name": name}
        if parent is not None:
            body["parent"] = parent
        data, _ = self._request("POST", f"/{taxonomy}", body=body)
        return data["id"]

    def ensure_namespace_category(self, namespace: str) -> int:
        """devlog parent + one child per namespace; '/' flattens to '-'."""
        parent = self._ensure_term("categories", "devlog", "Devlog")
        slug = namespace.replace("/", "-")
        return self._ensure_term("categories", slug, namespace, parent=parent)

    def ensure_tags(self, tags: list[str]) -> list[int]:
        return [self._ensure_term("tags", t, t) for t in tags]

    def list_posts(self, *, author: int, category: int) -> list[dict]:
        """Every post (any status) by this author in this category, raw content."""
        posts, page = [], 1
        while True:
            data, headers = self._request(
                "GET",
                "/posts",
                params={
                    "author": author,
                    "categories": category,
                    "status": "publish,draft,pending,private,future",
                    "context": "edit",
                    "per_page": 100,
                    "page": page,
                },
            )
            posts.extend(data)
            if page >= int(headers.get("X-WP-TotalPages", "1") or "1"):
                return posts
            page += 1

    def create_post(self, body: dict) -> dict:
        data, _ = self._request("POST", "/posts", body=body)
        return data

    def update_post(self, post_id: int, body: dict) -> dict:
        data, _ = self._request("POST", f"/posts/{post_id}", body=body)
        return data

    def delete_post(self, post_id: int) -> dict:
        data, _ = self._request("DELETE", f"/posts/{post_id}", params={"force": "true"})
        return data


def content_with_hash(body_html: str, content_hash: str) -> str:
    """Append the sync drift-detection marker to the stored post content."""
    return f"{body_html}\n<!-- {HASH_MARKER} {content_hash} -->"


def extract_hash(raw_content: str) -> str | None:
    marker = raw_content.rfind(HASH_MARKER)
    if marker < 0:
        return None
    tail = raw_content[marker + len(HASH_MARKER):]
    return tail.split("-->", 1)[0].strip() or None


def emit_bone_event(
    bone_url: str,
    hmac_secret: str,
    event_type: str,
    run_id: str,
    actor_action_id: str,
    result: dict,
    timeout: int = 10,
) -> bool:
    """POST one HMAC-signed event to Bone. Returns False (never raises) on
    failure — devlog writes must not die because telemetry is down; the
    caller logs the miss."""
    if not bone_url or not hmac_secret:
        return False
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": event_type,
        "run_id": run_id,
        "source": "devlog",
        "actor_id": ACTOR_ID,
        "actor_action_id": actor_action_id,
        # Bone's wing client maps payload['result'] -> events.result_json
        # (JSON-encodes dicts itself) — sending 'result_json' lands empty.
        "result": result,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ts = str(int(time.time()))
    digest = hmac.new(
        hmac_secret.encode("utf-8"), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    req = urllib.request.Request(
        f"{bone_url.rstrip('/')}/api/v1/events", data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Wing-Timestamp", ts)
    req.add_header("X-Wing-Signature", digest)
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False
