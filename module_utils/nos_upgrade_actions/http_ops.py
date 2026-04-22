"""http.wait / http.get_all — lightweight HTTP helpers for upgrade steps.

These are deliberately thinner than ``ansible.builtin.uri``.  We want:

* No dependency on the Ansible runtime (callable from pure Python unit tests).
* A pluggable transport so tests inject a fake.
* Support for tcp://host:port as a cheap liveness probe (used by the Redis
  and Postgres recipes where a full HTTP endpoint is unavailable).

All HTTP/HTTPS verification accepts self-signed certs by default (the nos
dev.local domain is served by an internal CA).  Set ``verify: true`` in
the action to enable strict verification.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import os.path
import socket
import ssl
import time


try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
    from urllib.parse import urlparse
except ImportError:  # pragma: no cover — py2 fallback (not supported in nos)
    from urllib2 import Request, urlopen, URLError, HTTPError  # type: ignore
    from urlparse import urlparse  # type: ignore


def _expand(ctx, path):
    if not path:
        return path
    expander = ctx.get("expand_path") if ctx else None
    if expander is not None:
        return expander(path)
    return os.path.expandvars(os.path.expanduser(path))


def _ok(changed, **extra):
    out = {"success": True, "changed": bool(changed)}
    if extra:
        out["result"] = extra
    return out


def _fail(error, **extra):
    out = {"success": False, "changed": False, "error": str(error)}
    if extra:
        out["result"] = extra
    return out


# ---------------------------------------------------------------------------
# transport (pluggable for tests)

def _do_http(ctx, url, method="GET", headers=None, verify=False, timeout=10):
    """Perform a single HTTP/HTTPS request.  Returns (status:int, body:bytes)."""
    injected = ctx.get("http_request") if ctx else None
    if injected is not None:
        return injected(url=url, method=method, headers=headers or {},
                        verify=verify, timeout=timeout)
    req = Request(url, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    sslctx = None
    if url.startswith("https://") and not verify:
        sslctx = ssl.create_default_context()
        sslctx.check_hostname = False
        sslctx.verify_mode = ssl.CERT_NONE
    try:
        resp = urlopen(req, timeout=timeout, context=sslctx) if sslctx else urlopen(req, timeout=timeout)
        body = resp.read()
        status = resp.getcode()
        return status, body
    except HTTPError as he:
        try:
            body = he.read() or b""
        except Exception:
            body = b""
        return he.code, body


def _do_tcp(ctx, host, port, timeout=5):
    """TCP connect probe — returns True on success."""
    injected = ctx.get("tcp_probe") if ctx else None
    if injected is not None:
        return bool(injected(host=host, port=int(port), timeout=timeout))
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


def _sleep(ctx, seconds):
    injected = ctx.get("sleep") if ctx else None
    if injected is not None:
        injected(seconds)
    else:
        time.sleep(seconds)


def _resolve_token(ctx, token_var):
    """Resolve a bearer token by name via ``ctx['vars']`` or environment."""
    if not token_var:
        return None
    if ctx and "vars" in ctx and token_var in (ctx["vars"] or {}):
        return ctx["vars"][token_var]
    return os.environ.get(token_var.upper()) or os.environ.get(token_var)


# ---------------------------------------------------------------------------
# http.wait

def handle_http_wait(action, ctx):
    """Poll a URL until it returns an acceptable status or timeout elapses.

    action keys:
      url            (required) — http://, https://, or tcp://host:port
      expect_status  (int, default 200) — only for http(s)
      timeout_sec    (int, default 60)
      interval_sec   (int, default 3)
      verify         (bool, default false) — strict TLS
    """
    url = action.get("url")
    if not url:
        return _fail("http.wait requires 'url'")
    expect_status = int(action.get("expect_status", 200))
    timeout_sec = int(action.get("timeout_sec", 60))
    interval_sec = max(1, int(action.get("interval_sec", 3)))
    verify = bool(action.get("verify", False))

    if ctx.get("dry_run"):
        return _ok(False, dry_run=True, url=url)

    parsed = urlparse(url)
    mode = parsed.scheme.lower() if parsed.scheme else "http"

    deadline = time.time() + timeout_sec
    attempts = 0
    last_err = None

    while time.time() < deadline:
        attempts += 1
        try:
            if mode == "tcp":
                host = parsed.hostname or "localhost"
                port = parsed.port
                if port is None:
                    return _fail("http.wait tcp url missing port: %r" % url)
                if _do_tcp(ctx, host, port, timeout=min(5, interval_sec)):
                    return _ok(False, url=url, attempts=attempts, mode="tcp")
                last_err = "tcp_connect_failed"
            else:
                status, _body = _do_http(ctx, url, timeout=min(10, interval_sec * 2),
                                         verify=verify)
                if status == expect_status:
                    return _ok(False, url=url, attempts=attempts, status=status)
                last_err = "status=%d" % status
        except (URLError, socket.timeout, OSError) as exc:
            last_err = str(exc)
        _sleep(ctx, interval_sec)

    return _fail("http.wait timeout after %ds (%d attempts, last=%s)"
                 % (timeout_sec, attempts, last_err),
                 url=url, attempts=attempts)


# ---------------------------------------------------------------------------
# http.get_all

def handle_http_get_all(action, ctx):
    """Fetch a URL once and write the response body to disk.

    The name ``get_all`` is spec-defined — in practice it's a one-shot GET
    that is intended for paginated listings the caller treats as opaque.
    Pagination is deliberately NOT walked here; recipes that need it should
    use custom.module with ansible.builtin.uri in a loop.

    action keys:
      url     (required)
      save_to (required) — destination path (created if missing)
      auth:
        type: bearer
        token_var: <name>   # resolved from ctx['vars'] or env
      headers (optional)
      verify  (bool, default false)
      timeout_sec (int, default 15)
      ignore_errors (bool, default false) — if true, a non-2xx returns
        success=True with result.ok=False so the recipe can continue.
    """
    url = action.get("url")
    save_to = _expand(ctx, action.get("save_to"))
    if not url or not save_to:
        return _fail("http.get_all requires 'url' and 'save_to'")

    headers = dict(action.get("headers") or {})
    auth = action.get("auth") or {}
    if auth.get("type") == "bearer":
        token = _resolve_token(ctx, auth.get("token_var"))
        if token:
            headers["Authorization"] = "Bearer %s" % token

    verify = bool(action.get("verify", False))
    timeout = int(action.get("timeout_sec", 15))
    ignore_errors = bool(action.get("ignore_errors", False))

    if ctx.get("dry_run"):
        return _ok(True, would_fetch=True, url=url, save_to=save_to)

    try:
        status, body = _do_http(ctx, url, headers=headers, verify=verify, timeout=timeout)
    except (URLError, socket.timeout, OSError) as exc:
        if ignore_errors:
            return _ok(False, url=url, ok=False, error=str(exc))
        return _fail("http.get_all request failed: %s" % exc, url=url)

    if status < 200 or status >= 300:
        if ignore_errors:
            return _ok(False, url=url, ok=False, status=status)
        return _fail("http.get_all got status %d" % status, url=url, status=status)

    try:
        parent = os.path.dirname(os.path.abspath(save_to))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(save_to, "wb") as fh:
            fh.write(body or b"")
    except OSError as exc:
        return _fail("http.get_all write failed: %s" % exc,
                     url=url, save_to=save_to)

    return _ok(True, url=url, save_to=save_to, bytes_written=len(body or b""),
               status=status)
