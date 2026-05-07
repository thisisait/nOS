"""Thin Authentik admin-API wrapper for ephemeral test users (A13.6).

Why a separate module instead of extending ``files/anatomy/module_utils/
nos_authentik_client.py``?

The production client is used by Ansible modules (``library/nos_authentik.py``)
and by ``library/nos_migrate.py``'s ``authentik_proxy`` action handler. Adding
user-CRUD methods would change a contract path that's already pinned by
production migrations + the playbook. The test-identity layer is allowed to
drift faster (we own it, we test it, it never runs against prod data),
so it lives here as a self-contained ``requests``-based wrapper.

Public API:

    admin = AuthentikAdmin.from_env()
    admin.wait_reachable(timeout_sec=30)
    user = admin.create_user(username, name, email)
    admin.set_user_password(user["pk"], password)
    group = admin.get_group_by_name("nos-providers")
    admin.add_user_to_group(group["pk"], user["pk"])
    # ... test runs ...
    admin.delete_user(user["pk"])

Token resolution mirrors the production client:
  1. ``AUTHENTIK_API_TOKEN`` env var (CI / explicit)
  2. ``authentik_bootstrap_token`` from ``~/.nos/secrets.yml`` (operator dev)
  3. Hard fail with a clear diagnostic.

Endpoint resolution:
  1. ``AUTHENTIK_API_URL`` env var (full URL, e.g. ``https://auth.dev.local/api/v3``)
  2. ``http://127.0.0.1:9003/api/v3`` (loopback, default for dev)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests
import yaml


DEFAULT_LOOPBACK_URL = "http://127.0.0.1:9003/api/v3"
# A13.6 (2026-05-07): bumped from 15s to 60s — local Authentik dev instance
# can stall under repeated test-run load (observed 130s for /core/users/me/
# during a back-to-back four-run pytest hammer). Override via env for CI
# deployments hitting a fresh / better-resourced cluster.
DEFAULT_TIMEOUT_S = 60
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_S = 0.5


class AuthentikAdminError(RuntimeError):
    """Raised when the Authentik admin API returns an unrecoverable error."""

    def __init__(self, message: str, status_code: int | None = None,
                 body: str | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.url = url


def _resolve_token() -> str:
    explicit = os.environ.get("AUTHENTIK_API_TOKEN")
    if explicit:
        return explicit

    secrets_path = os.path.expanduser("~/.nos/secrets.yml")
    if os.path.isfile(secrets_path):
        try:
            with open(secrets_path, "r") as fh:
                data = yaml.safe_load(fh) or {}
            token = data.get("authentik_bootstrap_token")
            if token:
                return token
        except (IOError, OSError, yaml.YAMLError):
            pass

    raise AuthentikAdminError(
        "No Authentik admin token found. Set AUTHENTIK_API_TOKEN or write "
        "authentik_bootstrap_token to ~/.nos/secrets.yml."
    )


def _resolve_url() -> str:
    explicit = os.environ.get("AUTHENTIK_API_URL")
    if explicit:
        return explicit.rstrip("/")
    return DEFAULT_LOOPBACK_URL


@dataclass
class AuthentikUser:
    """Subset of the Authentik user object we care about."""
    pk: int
    username: str
    name: str
    email: str
    is_active: bool
    raw: dict


@dataclass
class AuthentikGroup:
    pk: str           # Authentik groups use UUID strings
    name: str
    is_superuser: bool
    raw: dict


class AuthentikAdmin:
    """Admin operations on Authentik users + groups via /api/v3."""

    def __init__(self, base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT_S,
                 verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify_tls = verify_tls
        self._sess = requests.Session()
        self._sess.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "nos-e2e-tester/1.0",
        })

    @classmethod
    def from_env(cls) -> "AuthentikAdmin":
        """Build a client from environment / ~/.nos/secrets.yml — the canonical
        path for pytest fixtures so individual tests don't carry credentials.

        Timeout knob: ``AUTHENTIK_API_TIMEOUT`` (seconds) — useful when the
        local Authentik gets sluggish during repeated test-run hammering.
        """
        url = _resolve_url()
        token = _resolve_token()
        # Loopback dev — accept self-signed mkcert chain
        verify = not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost")
        try:
            timeout = float(os.environ.get("AUTHENTIK_API_TIMEOUT", DEFAULT_TIMEOUT_S))
        except ValueError:
            timeout = DEFAULT_TIMEOUT_S
        return cls(url, token, timeout=timeout, verify_tls=verify)

    # -- low-level ------------------------------------------------------

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _request(self, method: str, path: str, params: dict | None = None,
                 json_body: dict | None = None,
                 allow_statuses: tuple[int, ...] = ()) -> requests.Response:
        url = self._url(path)
        backoff = DEFAULT_BACKOFF_S
        last_exc: Exception | None = None
        for attempt in range(1, DEFAULT_RETRIES + 1):
            try:
                resp = self._sess.request(
                    method, url, params=params, json=json_body,
                    timeout=self.timeout, verify=self.verify_tls,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < DEFAULT_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise AuthentikAdminError(
                    f"Authentik unreachable after {DEFAULT_RETRIES} attempts: {exc}",
                    url=url,
                ) from exc

            if 200 <= resp.status_code < 300 or resp.status_code in allow_statuses:
                return resp
            if 500 <= resp.status_code < 600 and attempt < DEFAULT_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise AuthentikAdminError(
                f"Authentik {method} {url} returned {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
                body=resp.text[:500],
                url=url,
            )
        raise AuthentikAdminError(f"Unreachable: {last_exc}", url=url)

    # -- reachability ---------------------------------------------------

    def wait_reachable(self, timeout_sec: float = 30) -> bool:
        """Poll ``GET /core/users/me/`` until reachable. Validates connectivity
        and (200 path) the bootstrap token in one round trip."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                resp = self._sess.get(
                    self._url("/core/users/me/"),
                    timeout=min(self.timeout, 5),
                    verify=self.verify_tls,
                )
                if 200 <= resp.status_code < 500:
                    return True
            except requests.RequestException:
                pass
            time.sleep(1.0)
        return False

    # -- user CRUD ------------------------------------------------------

    def create_user(self, username: str, name: str, email: str,
                    is_active: bool = True,
                    attributes: dict | None = None) -> AuthentikUser:
        """POST /core/users/. Returns the created user."""
        body: dict = {
            "username": username,
            "name": name,
            "email": email,
            "is_active": is_active,
            "path": "users",
            "type": "internal",
        }
        if attributes is not None:
            body["attributes"] = attributes
        resp = self._request("POST", "/core/users/", json_body=body)
        data = resp.json()
        return AuthentikUser(
            pk=data["pk"], username=data["username"], name=data["name"],
            email=data["email"], is_active=data["is_active"], raw=data,
        )

    def set_user_password(self, user_pk: int, password: str) -> None:
        """POST /core/users/<pk>/set_password/."""
        self._request(
            "POST", f"/core/users/{user_pk}/set_password/",
            json_body={"password": password},
        )

    def delete_user(self, user_pk: int) -> bool:
        """DELETE /core/users/<pk>/. Returns True if deleted (404 also returns True
        — idempotent teardown)."""
        resp = self._request(
            "DELETE", f"/core/users/{user_pk}/",
            allow_statuses=(404,),
        )
        return resp.status_code in (200, 204, 404)

    def get_user_by_username(self, username: str) -> AuthentikUser | None:
        resp = self._request("GET", "/core/users/", params={"username": username})
        for u in resp.json().get("results", []) or []:
            if u.get("username") == username:
                return AuthentikUser(
                    pk=u["pk"], username=u["username"], name=u.get("name", ""),
                    email=u.get("email", ""), is_active=u.get("is_active", False),
                    raw=u,
                )
        return None

    def list_users_by_prefix(self, username_prefix: str) -> list[AuthentikUser]:
        """For orphan-sweep: list every user whose username starts with the prefix.

        SAFETY (A13.6 incident, 2026-05-07): Authentik's user list endpoint
        SILENTLY IGNORES unknown filter parameters and returns ALL users.
        Originally this method passed ``username__startswith=<prefix>`` and
        trusted the server to honor it — when it didn't, the atexit hook
        wiped out 8 users (only akadmin survived because Authentik's DELETE
        returned 405 on superuser). NEVER trust server-side filtering here.

        We use ``search=<prefix>`` to narrow the result set (Authentik does
        respect ``search`` and matches it against username/name/email), then
        ALWAYS filter client-side on the exact prefix. Belt-and-suspenders.

        If ``username_prefix`` is empty/None, we refuse — destroying every
        user is never the right answer for a "list" call.
        """
        if not username_prefix:
            raise AuthentikAdminError(
                "list_users_by_prefix called with empty prefix — refusing "
                "to enumerate every user (this guard exists because of the "
                "A13.6 incident where unfiltered iteration deleted 8 users)"
            )
        out: list[AuthentikUser] = []
        page = 1
        while True:
            resp = self._request(
                "GET", "/core/users/",
                # ``search`` is honored; ``username__startswith`` is NOT —
                # but we client-side filter below regardless, so it's fine
                # if the server returns extra hits.
                params={"search": username_prefix,
                        "page": page, "page_size": 100},
            )
            data = resp.json()
            for u in data.get("results", []) or []:
                # CRITICAL: client-side prefix check. This is the actual
                # safety boundary — the server-side ``search`` is just an
                # optimization to avoid pulling 1000 rows.
                if not u.get("username", "").startswith(username_prefix):
                    continue
                out.append(AuthentikUser(
                    pk=u["pk"], username=u["username"], name=u.get("name", ""),
                    email=u.get("email", ""), is_active=u.get("is_active", False),
                    raw=u,
                ))
            pagination = data.get("pagination") or {}
            next_page = pagination.get("next")
            if not next_page or next_page == page:
                break
            page = next_page
        return out

    # -- group lookup + membership --------------------------------------

    def get_group_by_name(self, name: str) -> AuthentikGroup | None:
        resp = self._request("GET", "/core/groups/", params={"name": name})
        for g in resp.json().get("results", []) or []:
            if g.get("name") == name:
                return AuthentikGroup(
                    pk=g["pk"], name=g["name"],
                    is_superuser=g.get("is_superuser", False), raw=g,
                )
        return None

    def add_user_to_group(self, group_pk: str, user_pk: int) -> None:
        """POST /core/groups/<group_pk>/add_user/ — Authentik's documented
        membership-mutation endpoint. Body shape: ``{"pk": <user_pk_int>}``.

        404 is acceptable (group already gone — happens during chaotic teardown).
        """
        self._request(
            "POST", f"/core/groups/{group_pk}/add_user/",
            json_body={"pk": user_pk},
            allow_statuses=(404,),
        )

    def remove_user_from_group(self, group_pk: str, user_pk: int) -> None:
        self._request(
            "POST", f"/core/groups/{group_pk}/remove_user/",
            json_body={"pk": user_pk},
            allow_statuses=(404,),
        )
