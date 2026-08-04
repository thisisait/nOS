#!/usr/bin/env python3
"""
Uptime Kuma — auto-configure monitors, notifications, and public status page.

Invoked by the ``pazny.uptime_kuma`` role after the container starts.

This version (Sprint 1, Wave 3) is spec-driven: a single YAML/JSON config file
describes:
  - monitors       (HTTP / TCP / keyword / docker / cert-expiry)
  - notifications  (ntfy + webhook to Bone / Wing with HMAC)
  - status_page    (public read-only view + slug)

Usage
-----
  setup-monitors.py --url URL --user USER --password PASS --config CFG [--dry-run] [-v]

  # Legacy CLI (kept for backwards compatibility with the old task):
  setup-monitors.py <URL> <USER> <PASS> '<MONITORS_JSON>'

Exit codes
----------
  0   success (or the kuma2 transport is unimportable — we soft-skip)
  1   hard failure (login + setup both failed)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

VERBOSE = False


def log(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def vlog(msg: str) -> None:
    if VERBOSE:
        log("[v] " + msg)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> Dict[str, Any]:
    """Load YAML or JSON config. YAML is optional (lib may be missing)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = fh.read()
    # Try JSON first (fast path; the Ansible task writes JSON).
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore
        return yaml.safe_load(data)
    except ImportError:
        raise SystemExit(
            f"[-] Config at {path} is not valid JSON and PyYAML is not installed.")


# ---------------------------------------------------------------------------
# HMAC helpers (mirror callback_plugins/wing_telemetry.py)
# ---------------------------------------------------------------------------

def hmac_signature(secret: str, body: bytes) -> Optional[str]:
    """Compute ``sha256=<hex>`` HMAC for the X-Wing-Signature header."""
    if not secret:
        return None
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    digest = hmac.new(key, body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


# ---------------------------------------------------------------------------
# Kuma API wrapper
# ---------------------------------------------------------------------------

class KumaClient:
    """Spec-driven configuration over the kuma2 Socket.IO transport.

    Responsibilities:
      - login (or initial setup if fresh install)
      - idempotent CRUD for monitors
      - idempotent CRUD for notifications
      - status-page creation + monitor assignment
    """

    def __init__(self, url: str, user: str, password: str, dry_run: bool = False,
                 timeout: float = 45):
        self.url = url
        self.user = user
        self.password = password
        self.dry_run = dry_run
        # How long to wait for each acknowledgement or pushed list
        # (Event.INFO / Event.MONITOR_LIST). The lib default (10s) is too short
        # when the host is under load during a blank run — Kuma's event delivery
        # is starved and EVERY op times out (48 monitors × timeout ≈ a 30-min
        # hang). A larger budget tolerates the load; fail-fast (in _modern_run)
        # caps the worst case if the API is genuinely unresponsive.
        self.timeout = timeout
        self._sock = None
        self._KumaSocketError = Exception

    # ----- connect ---------------------------------------------------------

    def connect(self) -> bool:
        """Open the socket and reach an authenticated state.

        TRANSPORT NOTE (2026-08-04). This used `uptime-kuma-api`, which
        supports Uptime Kuma 1.21.3 – 1.23.2 and nothing since. REM-073 moved
        the pin to 2.2.1 on 2026-07-24 and put every call out of range in one
        step; measured against a 2.2.1 container, `setup()` and `get_monitors()`
        both time out. `kuma2.Kuma2Socket` talks to the same Socket.IO handlers
        directly — see its module docstring for why that is smaller, not larger.

        `needSetup` is asked rather than inferred. The old code called `setup()`
        and treated ANY exception as "already set up, try logging in" — so a
        genuine setup failure and an already-configured server were the same
        observation, and the difference only showed up later as a login error
        with no explanation attached.
        """
        try:
            from kuma2 import Kuma2Socket, KumaSocketError
        except ImportError as e:
            log(f"SKIP: kuma2 transport not importable ({e}). "
                f"It ships beside this script in the role's files/.")
            return False

        self._KumaSocketError = KumaSocketError
        self._sock = Kuma2Socket(self.url, timeout=self.timeout)
        try:
            self._sock.connect()
        except Exception as e:
            log(f"[-] Cannot reach Kuma at {self.url}: {e}")
            return False

        try:
            if self._sock.needs_setup():
                self._sock.setup(self.user, self.password)
                log(f"[+] Created the first user unattended (user: {self.user})")
            self._sock.login(self.user, self.password)
            log(f"[+] Logged in as {self.user}")
        except Exception as e:
            log(f"[-] Authentication failed: {e}")
            return False
        return True

    def disconnect(self) -> None:
        if self._sock is not None:
            self._sock.disconnect()

    # ----- monitors --------------------------------------------------------

    def list_monitors(self) -> Dict[str, Dict[str, Any]]:
        """The monitor list is PUSHED after login, not fetched.

        Kuma has no `getMonitors` acknowledgement to call; the server sends
        `monitorList` unprompted. Kuma2Socket keeps the latest copy, which
        matters after a mutation — a stale list is how an idempotent run
        decides to create something that already exists.
        """
        return self._sock.monitors_by_name()

    def upsert_monitor(self, spec: Dict[str, Any],
                       existing: Dict[str, Dict[str, Any]]) -> Tuple[str, Optional[int]]:
        """Create or update a single monitor. Returns (action, monitor_id)."""
        from kuma2 import monitor_payload

        name = spec["name"]
        payload = monitor_payload(spec)

        if self.dry_run:
            log(f"[dry] upsert monitor {name} ({payload['type']}) → {payload}")
            return ("dry", None)

        if name in existing:
            current = existing[name]
            mon_id = current.get("id")
            # 2.x `editMonitor` takes the WHOLE monitor, not a patch: it writes
            # back every field it receives, so sending only the changed keys
            # would blank the rest. Merge onto the row the server pushed.
            merged = {**current, **payload, "id": mon_id}
            try:
                self._sock.call_ok("editMonitor", merged)
                vlog(f"[=] Updated {name} (id={mon_id})")
                return ("updated", mon_id)
            except Exception as e:
                log(f"[!] edit failed for {name}: {e}")
                return ("error", mon_id)
        try:
            resp = self._sock.call_ok("add", payload)
            mon_id = resp.get("monitorID")
            log(f"[+] Created {name} (id={mon_id})")
            return ("created", mon_id)
        except Exception as e:
            log(f"[-] Failed: {name} — {e}")
            return ("error", None)

    # ----- notifications ---------------------------------------------------

    def list_notifications(self) -> Dict[str, Dict[str, Any]]:
        """Also a push (`notificationList`), same as the monitor list."""
        return self._sock.notifications_by_name()

    def _upsert_notification(self, name: str, args: Dict[str, Any],
                             existing: Dict[str, Dict[str, Any]],
                             label: str) -> Optional[int]:
        """One event does both jobs.

        `addNotification(notification, notificationID)` CREATES when the id is
        null and EDITS when it is not — there is no separate edit event. The
        old code called a library `edit_notification` that wrapped this exact
        call, so the two paths only ever looked different from the outside.
        """
        if self.dry_run:
            log(f"[dry] upsert {label} notification {name}")
            return None
        nid = existing.get(name, {}).get("id")
        try:
            resp = self._sock.call_ok("addNotification", args, nid)
            new_id = resp.get("id", nid)
            if nid:
                vlog(f"[=] Updated {label} notification {name} (id={new_id})")
            else:
                log(f"[+] Created {label} notification {name} (id={new_id})")
            return new_id
        except Exception as e:
            log(f"[-] {label} notification upsert failed: {e}")
            return nid

    def upsert_ntfy(self, name: str, server_url: str, topic: str,
                    existing: Dict[str, Dict[str, Any]],
                    is_default: bool = True) -> Optional[int]:
        return self._upsert_notification(name, {
            "type": "ntfy",
            "name": name,
            "isDefault": is_default,
            "applyExisting": True,
            "ntfyserverurl": server_url,
            "ntfytopic": topic,
            "ntfyPriority": 4,
            "ntfyAuthenticationMethod": "none",
        }, existing, "ntfy")

    def upsert_webhook(self, name: str, url: str, body_template: Dict[str, Any],
                       hmac_secret: Optional[str],
                       existing: Dict[str, Dict[str, Any]],
                       is_default: bool = True) -> Optional[int]:
        # Uptime Kuma sends its own payload. We wrap it in a Bone-compatible
        # envelope using Kuma's custom body feature (contentType=json).
        body_json = json.dumps(body_template, separators=(",", ":"))

        # HMAC header: compute over the canonical body template bytes. Kuma
        # will substitute {{msg}}/{{monitorJSON}}/{{heartbeatJSON}} server-side;
        # downstream Bone recomputes and verifies over the received body.
        extra_headers = {}
        if hmac_secret:
            sig = hmac_signature(hmac_secret, body_json.encode("utf-8"))
            if sig:
                extra_headers["X-Wing-Signature"] = sig
                extra_headers["X-Wing-Source"] = "uptime-kuma"

        return self._upsert_notification(name, {
            "type": "webhook",
            "name": name,
            "isDefault": is_default,
            "applyExisting": True,
            "webhookURL": url,
            "webhookContentType": "custom",
            "webhookCustomBody": body_json,
            "webhookAdditionalHeaders": json.dumps(extra_headers) if extra_headers else "",
        }, existing, "webhook")

    # ----- status page -----------------------------------------------------

    def ensure_status_page(self, slug: str, title: str,
                           monitor_ids: List[int],
                           description: str = "") -> bool:
        """Create or update the public status page."""
        if self.dry_run:
            log(f"[dry] ensure status page slug={slug} title={title} "
                f"monitors={len(monitor_ids)}")
            return True

        from kuma2 import status_page_config

        if slug not in self._sock.status_page_slugs():
            try:
                self._sock.call_ok("addStatusPage", title, slug)
                log(f"[+] Created status page /{slug}")
            except Exception as e:
                vlog(f"[=] addStatusPage /{slug}: {e}")

        # Group all monitors under a single public list.
        public_group = [{
            "name": "Services",
            "weight": 1,
            "monitorList": [{"id": mid} for mid in monitor_ids if mid],
        }]

        try:
            # saveStatusPage(slug, config, imgDataUrl, publicGroupList).
            # imgDataUrl must be a STRING — the handler calls .startsWith on it,
            # so passing null fails with "Cannot read properties of null".
            self._sock.call_ok(
                "saveStatusPage",
                slug,
                status_page_config(slug, title, description),
                "/icon.svg",
                public_group,
            )
            log(f"[+] Saved status page /{slug} with {len(monitor_ids)} monitors")
            return True
        except Exception as e:
            log(f"[-] saveStatusPage failed: {e}")
            return False


# ---------------------------------------------------------------------------
# Legacy positional CLI: setup-monitors.py URL USER PASS '<MONITORS_JSON>'
# ---------------------------------------------------------------------------

def _legacy_run(argv: List[str]) -> int:
    url, user, password = argv[1], argv[2], argv[3]
    monitors = json.loads(argv[4])
    client = KumaClient(url, user, password)
    if not client.connect():
        return 0
    try:
        existing = client.list_monitors()
        created = 0
        for m in monitors:
            action, _ = client.upsert_monitor(m, existing)
            if action == "created":
                created += 1
        log(f"\nDone: {created} created, {len(existing)} existing")
    finally:
        client.disconnect()
    return 0


# ---------------------------------------------------------------------------
# Modern CLI: --config <spec>
# ---------------------------------------------------------------------------

def _modern_run(args) -> int:
    cfg = load_config(args.config)
    monitors: List[Dict[str, Any]] = cfg.get("monitors", [])
    notifications: Dict[str, Any] = cfg.get("notifications", {})
    status_page: Dict[str, Any] = cfg.get("status_page", {})

    log(f"[i] Config: {len(monitors)} monitors, "
        f"{len(notifications)} notification blocks, "
        f"status_page={'yes' if status_page else 'no'}")

    client = KumaClient(args.url, args.user, args.password, dry_run=args.dry_run,
                        timeout=args.timeout)
    if not client.connect():
        return 2  # connect/login timed out (likely load) — retryable by the role

    try:
        # 1) Monitors (idempotent).
        existing = client.list_monitors()
        created = updated = errored = 0
        consec_err = 0
        aborted = False
        name_to_id: Dict[str, int] = {}
        for m in monitors:
            action, mid = client.upsert_monitor(m, existing)
            if action == "created":
                created += 1
                consec_err = 0
            elif action == "updated":
                updated += 1
                consec_err = 0
            elif action == "error":
                errored += 1
                consec_err += 1
                # Fail-fast: a run of consecutive errors means the Kuma API is
                # unresponsive (event-wait timeouts under load) — abort rather
                # than grind every monitor (48 × timeout ≈ a 30-min hang).
                # Returns exit 3 → the role retries (until rc==0) so a later
                # attempt catches the load settling; the host-idle re-run always
                # works. Threshold 3 keeps each aborted attempt to ~3×timeout.
                if consec_err >= 3:
                    log(f"[!] Aborting: {consec_err} consecutive errors — Kuma "
                        f"API unresponsive (event-wait timeout under load).")
                    aborted = True
                    break
            if mid is None and m["name"] in existing:
                mid = existing[m["name"]].get("id")
            if mid:
                name_to_id[m["name"]] = mid

        if aborted:
            log(f"\nDone: {created} created, {updated} updated, {errored} errors "
                f"(ABORTED — Kuma API unresponsive). Monitors tracked: "
                f"{len(name_to_id)}.")
            return 3  # retryable: signals the role to re-attempt (until rc==0)

        # 2) Notifications.
        not_existing = client.list_notifications()
        ntfy_cfg = notifications.get("ntfy")
        webhook_cfg = notifications.get("webhook")

        if ntfy_cfg and ntfy_cfg.get("enabled", True):
            client.upsert_ntfy(
                name=ntfy_cfg.get("name", "nOS → ntfy"),
                server_url=ntfy_cfg["server_url"],
                topic=ntfy_cfg["topic"],
                existing=not_existing,
                is_default=ntfy_cfg.get("is_default", True),
            )

        if webhook_cfg and webhook_cfg.get("enabled", True):
            client.upsert_webhook(
                name=webhook_cfg.get("name", "nOS → Wing"),
                url=webhook_cfg["url"],
                body_template=webhook_cfg.get("body", {
                    "source": "uptime-kuma",
                    "event_type": "probe.failed",
                    "payload": {
                        "msg": "{{msg}}",
                        "monitor": "{{monitorJSON}}",
                        "heartbeat": "{{heartbeatJSON}}",
                    },
                }),
                hmac_secret=webhook_cfg.get("hmac_secret"),
                existing=not_existing,
                is_default=webhook_cfg.get("is_default", True),
            )

        # 3) Status page.
        if status_page and status_page.get("enabled", True):
            mon_ids = list(name_to_id.values())
            client.ensure_status_page(
                slug=status_page.get("slug", "nos"),
                title=status_page.get("title", "nOS Service Status"),
                description=status_page.get("description", ""),
                monitor_ids=mon_ids,
            )

        log(
            f"\nDone: {created} created, {updated} updated, "
            f"{errored} errors, {len(existing)} previously-existing. "
            f"Monitors tracked: {len(name_to_id)}.")
    finally:
        client.disconnect()
    return 0


def main() -> int:
    global VERBOSE
    argv = sys.argv

    # Legacy positional form: `setup-monitors.py URL USER PASS '<JSON>'`.
    if len(argv) == 5 and not argv[1].startswith("-"):
        return _legacy_run(argv)

    p = argparse.ArgumentParser(
        description="Configure Uptime Kuma from a spec file.")
    p.add_argument("--url", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--config", required=True,
                   help="Path to a JSON/YAML spec file.")
    p.add_argument("--timeout", type=float, default=45,
                   help="Per-event wait budget (s) for the Kuma API. Default 45 "
                        "tolerates Kuma event-delivery starvation under blank-run "
                        "load (the lib default of 10s causes a 30-min hang).")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv[1:])

    VERBOSE = args.verbose
    return _modern_run(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
