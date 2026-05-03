"""HTTP client for the Authentik REST API v3.

This thin client is shared between ``library/nos_authentik.py`` and the
``authentik_proxy`` action handlers invoked by ``library/nos_migrate.py``.

Design goals:

* **Single dependency**: ``requests`` (already a playbook-wide dep via
  ``ansible.builtin.uri``/``get_url`` stacks).  We do not pull in any Authentik
  SDK — the surface we need is tiny (CRUD on groups and providers/applications),
  and the upstream SDK drags in pydantic + opengenerators-aio which is heavy
  for a migration helper.
* **Idempotent by convention**: every high-level helper returns ``changed``
  and resolves the "already in desired state" case silently.
* **Retry on transient failures**: 3 attempts with exponential backoff on
  connection errors and 5xx responses.
* **No global state**: the caller passes base URL + token.  The token may come
  from four different sources (task var, ``~/.nos/secrets.yml``, env var,
  explicit kwarg) — resolution lives in ``resolve_token``.
* **Tested against Authentik 2026.1.x** (API version v3, unchanged since 2024.2).

Public API:

    client = NosAuthentikClient(base_url, token, timeout=15)
    client.wait_reachable(timeout_sec=30)
    groups = client.list_groups()
    group  = client.get_group_by_name("devboxnos-admins")
    client.rename_group(group["pk"], "nos-admins")
    providers = client.list_oauth2_providers()
    apps      = client.list_applications()

Any non-2xx response raises ``AuthentikApiError`` after retries are exhausted.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import time

try:
    import requests
except ImportError:  # pragma: no cover — requests is a hard runtime dep
    requests = None

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.5  # seconds; doubled each retry


class AuthentikApiError(Exception):
    """Raised when the Authentik API returns an unrecoverable error."""

    def __init__(self, message, status_code=None, body=None, url=None):
        super(AuthentikApiError, self).__init__(message)
        self.status_code = status_code
        self.body = body
        self.url = url


# ---------------------------------------------------------------------------
# Token + endpoint resolution
# ---------------------------------------------------------------------------

def resolve_endpoint(explicit=None, authentik_port=None, authentik_domain=None):
    """Pick the API base URL following spec priority.

    Order:
      1. ``explicit`` (task var ``authentik_api_url``)
      2. ``http://127.0.0.1:<port>/api/v3`` when ``authentik_port`` is set
      3. ``https://<domain>/api/v3`` when ``authentik_domain`` is set

    Returned URL is stripped of trailing slash.  Caller may append ``/groups/``.
    """
    if explicit:
        return explicit.rstrip("/")
    if authentik_port:
        return "http://127.0.0.1:%s/api/v3" % (authentik_port,)
    if authentik_domain:
        return "https://%s/api/v3" % (authentik_domain,)
    raise AuthentikApiError(
        "Cannot resolve Authentik endpoint: provide authentik_api_url, "
        "authentik_port, or authentik_domain."
    )


def resolve_token(explicit=None, secrets_path=None, env_var="ANSIBLE_AUTHENTIK_TOKEN"):
    """Pick the API token following spec priority.

    Order:
      1. ``explicit`` (task var ``authentik_api_token``)
      2. ``authentik_bootstrap_token`` from ``~/.nos/secrets.yml``
      3. ``ANSIBLE_AUTHENTIK_TOKEN`` env var
      4. Fail with a descriptive error.
    """
    if explicit:
        return explicit

    if secrets_path is None:
        secrets_path = os.path.expanduser("~/.nos/secrets.yml")
    if os.path.isfile(secrets_path) and yaml is not None:
        try:
            with open(secrets_path, "r") as fh:
                data = yaml.safe_load(fh) or {}
            token = data.get("authentik_bootstrap_token")
            if token:
                return token
        except (IOError, OSError, yaml.YAMLError):
            # Fall through to env var — secrets file is best-effort.
            pass

    env_token = os.environ.get(env_var)
    if env_token:
        return env_token

    raise AuthentikApiError(
        "No Authentik API token found. Provide authentik_api_token, set "
        "authentik_bootstrap_token in ~/.nos/secrets.yml, or export "
        "ANSIBLE_AUTHENTIK_TOKEN."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NosAuthentikClient(object):
    """Thin wrapper around ``requests`` with Authentik idioms baked in.

    The client is stateless beyond a ``requests.Session`` for connection reuse.
    All high-level helpers (``list_groups``, ``rename_group``, ...) return
    plain dicts / lists of dicts.
    """

    def __init__(self, base_url, token, timeout=DEFAULT_TIMEOUT,
                 retries=DEFAULT_RETRIES, backoff=DEFAULT_BACKOFF, verify_tls=True):
        if requests is None:  # pragma: no cover
            raise AuthentikApiError("python-requests is required for nos_authentik_client")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.backoff = backoff
        self.verify_tls = verify_tls
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": "Bearer %s" % (token,),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "nos-authentik-client/1.0",
        })

    # -- low-level ---------------------------------------------------------

    def _url(self, path):
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _request(self, method, path, params=None, json_body=None, allow_statuses=None):
        """Issue an HTTP request with retry on connection + 5xx failures.

        ``allow_statuses`` — iterable of status codes treated as success even
        if not 2xx (e.g. 404 from ``get_group`` → returns None).
        """
        url = self._url(path)
        last_exc = None
        backoff = self.backoff
        for attempt in range(1, self.retries + 1):
            try:
                resp = self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=json.dumps(json_body) if json_body is not None else None,
                    timeout=self.timeout,
                    verify=self.verify_tls,
                )
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise AuthentikApiError(
                    "Authentik API unreachable after %d attempts: %s" % (self.retries, exc),
                    url=url,
                ) from exc

            status = resp.status_code
            if 200 <= status < 300:
                return resp
            if allow_statuses and status in allow_statuses:
                return resp
            if 500 <= status < 600 and attempt < self.retries:
                time.sleep(backoff)
                backoff *= 2
                continue

            # Non-retryable failure — raise.
            body_preview = ""
            try:
                body_preview = resp.text[:500]
            except Exception:  # noqa: BLE001
                pass
            raise AuthentikApiError(
                "Authentik API %s %s returned %d: %s" % (method, url, status, body_preview),
                status_code=status,
                body=body_preview,
                url=url,
            )

        # Should be unreachable — loop either returns or raises.
        raise AuthentikApiError(
            "Authentik API request failed: %s" % (last_exc,),
            url=url,
        )

    def get(self, path, params=None, allow_statuses=None):
        resp = self._request("GET", path, params=params, allow_statuses=allow_statuses)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def post(self, path, json_body=None):
        resp = self._request("POST", path, json_body=json_body)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def patch(self, path, json_body=None):
        resp = self._request("PATCH", path, json_body=json_body)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def delete(self, path):
        resp = self._request("DELETE", path, allow_statuses=(404,))
        return resp.status_code in (200, 202, 204)

    # -- reachability ------------------------------------------------------

    def wait_reachable(self, timeout_sec=30, poll_interval=1.0):
        """Poll until API responds or the timeout elapses.

        Uses ``GET /core/users/me/`` because it is cheap, always available,
        and validates both connectivity and the auth token in one call.
        """
        deadline = time.monotonic() + timeout_sec
        last_error = None
        # Use a private mini-client (bypasses retry stack) for speed.
        while time.monotonic() < deadline:
            try:
                resp = self._session.get(
                    self._url("/core/users/me/"),
                    timeout=min(self.timeout, 5),
                    verify=self.verify_tls,
                )
                if 200 <= resp.status_code < 500:
                    # 401 also counts as reachable — host is up, token may be bad,
                    # but that's a separate concern handled by later calls.
                    return True
                last_error = "HTTP %d" % (resp.status_code,)
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)
            time.sleep(poll_interval)
        return False

    # -- groups ------------------------------------------------------------

    def list_groups(self, search=None, page_size=100):
        """Return every group (handles Authentik pagination)."""
        groups = []
        page = 1
        while True:
            params = {"page": page, "page_size": page_size}
            if search:
                params["search"] = search
            data = self.get("/core/groups/", params=params)
            results = (data or {}).get("results", [])
            groups.extend(results)
            pagination = (data or {}).get("pagination") or {}
            # Authentik returns pagination with ``next`` number or 0 when done.
            next_page = pagination.get("next")
            if not next_page or next_page == page:
                break
            page = next_page
        return groups

    def get_group_by_name(self, name):
        """Exact-match lookup by group name. Returns the group dict or ``None``."""
        # Authentik supports filtering by exact name.
        data = self.get("/core/groups/", params={"name": name})
        for g in (data or {}).get("results", []) or []:
            if g.get("name") == name:
                return g
        return None

    def get_group(self, pk):
        return self.get("/core/groups/%s/" % (pk,))

    def create_group(self, name, attributes=None, parent=None, is_superuser=False):
        body = {"name": name, "is_superuser": bool(is_superuser)}
        if attributes is not None:
            body["attributes"] = attributes
        if parent is not None:
            body["parent"] = parent
        return self.post("/core/groups/", json_body=body)

    def rename_group(self, pk, new_name):
        return self.patch("/core/groups/%s/" % (pk,), json_body={"name": new_name})

    def delete_group(self, pk):
        return self.delete("/core/groups/%s/" % (pk,))

    # -- policy bindings ---------------------------------------------------

    def list_policy_bindings_for_group(self, group_pk):
        """Bindings where ``group == group_pk``."""
        data = self.get("/policies/bindings/", params={"group": group_pk, "page_size": 100})
        return (data or {}).get("results", []) or []

    # -- oauth2 providers + applications ----------------------------------

    def list_oauth2_providers(self, search=None, page_size=100):
        providers = []
        page = 1
        while True:
            params = {"page": page, "page_size": page_size}
            if search:
                params["search"] = search
            data = self.get("/providers/oauth2/", params=params)
            results = (data or {}).get("results", []) or []
            providers.extend(results)
            pagination = (data or {}).get("pagination") or {}
            next_page = pagination.get("next")
            if not next_page or next_page == page:
                break
            page = next_page
        return providers

    def get_oauth2_provider_by_name(self, name):
        data = self.get("/providers/oauth2/", params={"name": name})
        for p in (data or {}).get("results", []) or []:
            if p.get("name") == name:
                return p
        return None

    def rename_oauth2_provider(self, pk, new_name):
        return self.patch("/providers/oauth2/%s/" % (pk,), json_body={"name": new_name})

    def list_applications(self, page_size=100):
        apps = []
        page = 1
        while True:
            data = self.get("/core/applications/", params={"page": page, "page_size": page_size})
            results = (data or {}).get("results", []) or []
            apps.extend(results)
            pagination = (data or {}).get("pagination") or {}
            next_page = pagination.get("next")
            if not next_page or next_page == page:
                break
            page = next_page
        return apps

    def get_application_by_slug(self, slug):
        data = self.get("/core/applications/", params={"slug": slug})
        for a in (data or {}).get("results", []) or []:
            if a.get("slug") == slug:
                return a
        return None

    def get_application_by_name(self, name):
        data = self.get("/core/applications/", params={"name": name})
        for a in (data or {}).get("results", []) or []:
            if a.get("name") == name:
                return a
        return None

    def update_application(self, slug, payload):
        return self.patch("/core/applications/%s/" % (slug,), json_body=payload)
