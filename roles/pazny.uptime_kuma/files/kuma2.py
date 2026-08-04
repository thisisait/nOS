#!/usr/bin/env python3
"""Socket.IO transport for Uptime Kuma 2.x.

WHY THIS EXISTS — and why it is SMALLER than the library it replaces.

`uptime-kuma-api` supports Uptime Kuma 1.21.3 – 1.23.2 and has shipped nothing
since. On 2026-07-24 REM-073 moved the pin to 2.2.1 to close CVE-2026-33130,
which put the whole post-start automation out of the library's supported range
in one step. Measured 2026-08-04 against a throwaway 2.2.1 container: `setup()`
times out, `get_monitors()` times out, `login()` reports authIncorrectCreds
because the setup it depended on never happened.

The protocol did not break — the library's bookkeeping did. Every operation we
need is a plain Socket.IO handler with an ACKNOWLEDGEMENT callback:

    socket.on("setup",           (username, password, cb))
    socket.on("login",           ({username, password, token}, cb))
    socket.on("add",             (monitor, cb))
    socket.on("editMonitor",     (monitor, cb))
    socket.on("addNotification", (notification, notificationID, cb))
    socket.on("addStatusPage",   (title, slug, cb))
    socket.on("saveStatusPage",  (slug, config, imgDataUrl, publicGroupList, cb))

An ack is a request/response. The library instead waits for SERVER-PUSHED
events and reconstructs state from them, which is where it desynchronises. So
talking to the socket directly removes a layer rather than adding one.

THE ONE NON-OBVIOUS RULE, and it cost the first probe run: the server pushes
`info`, `setup` and `loginRequired` immediately after connect, and a call made
before that lands is never answered. `connect()` below waits for that push. A
client that skips the wait fails with a bare TimeoutError against a server that
is working perfectly — which reads exactly like "2.x is unsupported", and is
the wrong conclusion.

Version deltas from 1.x, all measured on 2.2.1:
  * `monitor.conditions` is NOT NULL — a v1-shaped payload dies on
    `SQLITE_CONSTRAINT: NOT NULL constraint failed: monitor.conditions`.
  * `accepted_statuscodes` is read for EVERY type, not just http; a port
    monitor without it fails on `Cannot read properties of undefined
    (reading 'every')`.
  * `editMonitor` wants the WHOLE monitor object, so edits merge onto the row
    the server pushed rather than sending a sparse patch.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

# Pushed by the server right after connect. Waiting for one of these is what
# separates "the server is busy" from "the call was made too early".
_READY_EVENTS = ("loginRequired", "info")

# Lists the server pushes unprompted after a successful login. There is no
# `getMonitors` ack to call — this IS the read path.
_LIST_EVENTS = ("monitorList", "notificationList", "statusPageList")


class KumaSocketError(RuntimeError):
    """A call was answered, and the answer was no."""


class Kuma2Socket:
    """One connection, request/response only."""

    def __init__(self, url: str, timeout: float = 45.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._sio = None
        self._pushed: Dict[str, Any] = {}

    # ----- lifecycle -------------------------------------------------------

    def connect(self) -> None:
        import socketio  # imported late so --help works without the dep

        self._sio = socketio.Client(reconnection=False)

        @self._sio.on("*")
        def _capture(event, *args):  # noqa: ANN001 — socketio passes the name
            # Keep the LATEST push per event: the server re-pushes monitorList
            # after every mutation, and a stale copy is how an idempotent run
            # decides to create something that already exists.
            self._pushed[event] = args[0] if len(args) == 1 else args

        self._sio.connect(self.url, transports=["websocket"],
                          wait_timeout=self.timeout)
        self._await_push(_READY_EVENTS, self.timeout)

    def disconnect(self) -> None:
        if self._sio is not None:
            try:
                self._sio.disconnect()
            except Exception:
                pass

    def _await_push(self, names, budget: float) -> bool:
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            if any(n in self._pushed for n in names):
                return True
            time.sleep(0.05)
        return False

    # ----- calls -----------------------------------------------------------

    def call(self, event: str, *args) -> Any:
        """One ack-style call. Returns the server's answer verbatim."""
        payload = args[0] if len(args) == 1 else (tuple(args) if args else None)
        if payload is None:
            return self._sio.call(event, timeout=self.timeout)
        return self._sio.call(event, payload, timeout=self.timeout)

    def call_ok(self, event: str, *args) -> Dict[str, Any]:
        """A call whose `ok:false` is an error rather than a return value."""
        resp = self.call(event, *args)
        if isinstance(resp, dict) and not resp.get("ok", True):
            raise KumaSocketError(f"{event}: {resp.get('msg', 'refused')}")
        return resp if isinstance(resp, dict) else {"ok": True, "value": resp}

    # ----- the two authentication paths ------------------------------------

    def needs_setup(self) -> bool:
        return bool(self.call("needSetup"))

    def setup(self, username: str, password: str) -> None:
        """Create the first user. Only ever legal once per database."""
        self.call_ok("setup", username, password)

    def login(self, username: str, password: str) -> None:
        resp = self.call("login", {"username": username, "password": password,
                                   "token": ""})
        if not isinstance(resp, dict) or not resp.get("ok"):
            msg = (resp or {}).get("msg", "refused") if isinstance(resp, dict) else "refused"
            raise KumaSocketError(f"login: {msg}")
        # The lists arrive unprompted after login; give them a moment to land
        # before anyone reads them, or the first read sees an empty estate and
        # every monitor looks new.
        self._await_push(_LIST_EVENTS, min(self.timeout, 15.0))

    # ----- reads, which are pushes ----------------------------------------

    def monitors_by_name(self) -> Dict[str, Dict[str, Any]]:
        raw = self._pushed.get("monitorList") or {}
        if not isinstance(raw, dict):
            return {}
        return {m["name"]: m for m in raw.values() if isinstance(m, dict) and m.get("name")}

    def notifications_by_name(self) -> Dict[str, Dict[str, Any]]:
        raw = self._pushed.get("notificationList") or []
        if not isinstance(raw, list):
            return {}
        return {n["name"]: n for n in raw if isinstance(n, dict) and n.get("name")}

    def status_page_slugs(self) -> List[str]:
        raw = self._pushed.get("statusPageList") or {}
        if isinstance(raw, dict):
            return [p.get("slug") for p in raw.values()
                    if isinstance(p, dict) and p.get("slug")]
        return []


# ---------------------------------------------------------------------------
# Payload shaping — where the 1.x → 2.x deltas live
# ---------------------------------------------------------------------------

# Our spec vocabulary → Kuma's. Kuma has always called a TCP check "port".
_TYPE_ALIASES = {"tcp": "port"}


def monitor_payload(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Build a 2.x-shaped monitor from one nOS spec entry."""
    # Normalise ONCE and branch on the wire word below. Branching on the spec
    # word instead would silently drop hostname/port for a spec that already
    # said `type: port` — the alias table would translate the type field while
    # the if-chain looked for a name that no longer matched.
    kind = _TYPE_ALIASES.get(spec.get("type", "http"), spec.get("type", "http"))
    payload: Dict[str, Any] = {
        "type": kind,
        "name": spec["name"],
        "interval": spec.get("interval", 60),
        "maxretries": spec.get("maxretries", 2),
        "retryInterval": spec.get("retry_interval", 60),
        # NOT NULL on 2.x. An empty list means "no extra conditions", which is
        # what every monitor this playbook creates wants.
        "conditions": spec.get("conditions", []),
        # Read for every type on 2.x, not just http — a port monitor without it
        # dies inside a `.every()` on undefined.
        "accepted_statuscodes": spec.get("accepted_statuscodes",
                                         ["200-299", "301", "302", "401", "403"]),
    }

    if kind in ("http", "keyword"):
        payload["url"] = spec["url"]
        payload["ignoreTls"] = bool(spec.get("ignore_tls", True))
        if spec.get("keyword"):
            payload["keyword"] = spec["keyword"]
        if spec.get("expiry_notification"):
            payload["expiryNotification"] = True
    elif kind == "port":
        payload["hostname"] = spec.get("hostname", "127.0.0.1")
        payload["port"] = int(spec["port"])
    elif kind == "docker":
        payload["docker_container"] = spec["docker_container"]
        payload["docker_host"] = spec.get("docker_host", 1)
    elif kind == "ping":
        payload["hostname"] = spec.get("hostname", "127.0.0.1")

    return payload


def status_page_config(slug: str, title: str, description: str = "") -> Dict[str, Any]:
    """The config half of saveStatusPage(slug, config, imgDataUrl, groups)."""
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "icon": "/icon.svg",
        "theme": "auto",
        "published": True,
        "showTags": True,
        "showPoweredBy": False,
        "showCertificateExpiry": False,
        "domainNameList": [],
        "customCSS": "",
        "footerText": None,
        # 2.x replaced v1's single `googleAnalyticsId` with a typed trio, and
        # validates it as `analyticsType !== null && !valid.includes(type)`.
        # OMITTING the key is therefore NOT the same as leaving it unset:
        # `undefined !== null` is true, so an absent field takes the invalid
        # branch and the save is refused with "Invalid analytics type". These
        # three nulls are load-bearing.
        "analyticsType": None,
        "analyticsId": None,
        "analyticsScriptUrl": None,
    }
