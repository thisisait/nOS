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
  0   success (or uptime_kuma_api not installed — we soft-skip)
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
# HMAC helpers (mirror callback_plugins/glasswing_telemetry.py)
# ---------------------------------------------------------------------------

def hmac_signature(secret: str, body: bytes) -> Optional[str]:
    """Compute ``sha256=<hex>`` HMAC for the X-Glasswing-Signature header."""
    if not secret:
        return None
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    digest = hmac.new(key, body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


# ---------------------------------------------------------------------------
# Kuma API wrapper
# ---------------------------------------------------------------------------

class KumaClient:
    """Thin wrapper over uptime_kuma_api.UptimeKumaApi.

    Responsibilities:
      - login (or initial setup if fresh install)
      - idempotent CRUD for monitors
      - idempotent CRUD for notifications
      - status-page creation + monitor assignment
    """

    def __init__(self, url: str, user: str, password: str, dry_run: bool = False):
        self.url = url
        self.user = user
        self.password = password
        self.dry_run = dry_run
        self._api = None
        self._monitor_types = None

    # ----- connect ---------------------------------------------------------

    def connect(self) -> bool:
        try:
            from uptime_kuma_api import UptimeKumaApi, MonitorType, NotificationType
        except ImportError:
            log("SKIP: uptime-kuma-api not installed (pip install uptime-kuma-api)")
            return False

        self._MonitorType = MonitorType
        self._NotificationType = NotificationType
        self._api = UptimeKumaApi(self.url)
        try:
            self._api.setup(self.user, self.password)
            log(f"[+] Initial setup complete (user: {self.user})")
        except Exception:
            try:
                self._api.login(self.user, self.password)
                log(f"[+] Logged in as {self.user}")
            except Exception as e:
                log(f"[-] Login failed: {e}")
                return False
        return True

    def disconnect(self) -> None:
        if self._api is not None:
            try:
                self._api.disconnect()
            except Exception:
                pass

    # ----- monitors --------------------------------------------------------

    def list_monitors(self) -> Dict[str, Dict[str, Any]]:
        try:
            mons = self._api.get_monitors()
        except Exception as e:
            log(f"[-] get_monitors failed: {e}")
            return {}
        return {m["name"]: m for m in mons}

    def _monitor_type_enum(self, kind: str):
        """Translate string → MonitorType enum, tolerating missing symbols."""
        mapping = {
            "http": "HTTP",
            "tcp": "PORT",          # uptime-kuma-api calls TCP "PORT"
            "keyword": "KEYWORD",
            "docker": "DOCKER",
            "ping": "PING",
        }
        key = mapping.get(kind, kind.upper())
        return getattr(self._MonitorType, key, None)

    def upsert_monitor(self, spec: Dict[str, Any],
                       existing: Dict[str, Dict[str, Any]]) -> Tuple[str, Optional[int]]:
        """Create or update a single monitor. Returns (action, monitor_id)."""
        name = spec["name"]
        kind = spec.get("type", "http")
        mt = self._monitor_type_enum(kind)
        if mt is None:
            log(f"[-] Unsupported monitor type '{kind}' for {name}")
            return ("skip", None)

        base_kwargs: Dict[str, Any] = {
            "type": mt,
            "name": name,
            "interval": spec.get("interval", 60),
            "maxretries": spec.get("maxretries", 2),
            "retryInterval": spec.get("retry_interval", 60),
        }

        if kind == "http":
            base_kwargs["url"] = spec["url"]
            base_kwargs["accepted_statuscodes"] = spec.get(
                "accepted_statuscodes", ["200-299", "301", "302", "401", "403"])
            base_kwargs["ignoreTls"] = bool(spec.get("ignore_tls", True))
            if spec.get("keyword"):
                base_kwargs["keyword"] = spec["keyword"]
        elif kind == "tcp":
            base_kwargs["hostname"] = spec.get("hostname", "127.0.0.1")
            base_kwargs["port"] = int(spec["port"])
        elif kind == "keyword":
            base_kwargs["url"] = spec["url"]
            base_kwargs["keyword"] = spec["keyword"]
            base_kwargs["ignoreTls"] = bool(spec.get("ignore_tls", True))
        elif kind == "docker":
            base_kwargs["docker_container"] = spec["docker_container"]
            base_kwargs["docker_host"] = spec.get("docker_host", 1)
        elif kind == "ping":
            base_kwargs["hostname"] = spec.get("hostname", "127.0.0.1")

        # Optional: TLS cert-expiry threshold (HTTP monitors only).
        if kind == "http" and spec.get("expiry_notification"):
            base_kwargs["expiryNotification"] = True

        if self.dry_run:
            log(f"[dry] upsert monitor {name} ({kind}) → {base_kwargs}")
            return ("dry", None)

        if name in existing:
            mon_id = existing[name]["id"]
            try:
                self._api.edit_monitor(mon_id, **base_kwargs)
                vlog(f"[=] Updated {name} (id={mon_id})")
                return ("updated", mon_id)
            except Exception as e:
                # Some fields aren't editable via edit_monitor on older versions.
                log(f"[!] edit failed for {name}: {e}")
                return ("error", mon_id)
        try:
            resp = self._api.add_monitor(**base_kwargs)
            mon_id = resp.get("monitorID") if isinstance(resp, dict) else None
            log(f"[+] Created {name} (id={mon_id})")
            return ("created", mon_id)
        except Exception as e:
            log(f"[-] Failed: {name} — {e}")
            return ("error", None)

    # ----- notifications ---------------------------------------------------

    def list_notifications(self) -> Dict[str, Dict[str, Any]]:
        try:
            nots = self._api.get_notifications()
        except Exception as e:
            log(f"[-] get_notifications failed: {e}")
            return {}
        return {n["name"]: n for n in nots}

    def upsert_ntfy(self, name: str, server_url: str, topic: str,
                    existing: Dict[str, Dict[str, Any]],
                    is_default: bool = True) -> Optional[int]:
        NT = self._NotificationType
        if not hasattr(NT, "NTFY"):
            log("[-] uptime-kuma-api build has no NTFY notification type")
            return None
        args = {
            "type": NT.NTFY,
            "name": name,
            "isDefault": is_default,
            "applyExisting": True,
            "ntfyserverurl": server_url,
            "ntfytopic": topic,
            "ntfyPriorityNotification": 4,  # default priority
        }
        if self.dry_run:
            log(f"[dry] upsert ntfy notification {name} → {server_url}/{topic}")
            return None
        try:
            if name in existing:
                nid = existing[name]["id"]
                self._api.edit_notification(nid, **args)
                vlog(f"[=] Updated ntfy notification {name} (id={nid})")
                return nid
            resp = self._api.add_notification(**args)
            nid = resp.get("id") if isinstance(resp, dict) else None
            log(f"[+] Created ntfy notification {name} (id={nid})")
            return nid
        except Exception as e:
            log(f"[-] ntfy notification upsert failed: {e}")
            return None

    def upsert_webhook(self, name: str, url: str, body_template: Dict[str, Any],
                       hmac_secret: Optional[str],
                       existing: Dict[str, Dict[str, Any]],
                       is_default: bool = True) -> Optional[int]:
        NT = self._NotificationType
        if not hasattr(NT, "WEBHOOK"):
            log("[-] uptime-kuma-api build has no WEBHOOK notification type")
            return None

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
                extra_headers["X-Glasswing-Signature"] = sig
                extra_headers["X-Glasswing-Source"] = "uptime-kuma"

        args = {
            "type": NT.WEBHOOK,
            "name": name,
            "isDefault": is_default,
            "applyExisting": True,
            "webhookURL": url,
            "webhookContentType": "json",
            "webhookCustomBody": body_json,
            "webhookAdditionalHeaders": json.dumps(extra_headers) if extra_headers else "",
        }
        if self.dry_run:
            log(f"[dry] upsert webhook notification {name} → {url}")
            return None
        try:
            if name in existing:
                nid = existing[name]["id"]
                try:
                    self._api.edit_notification(nid, **args)
                    vlog(f"[=] Updated webhook notification {name} (id={nid})")
                    return nid
                except Exception as e:
                    log(f"[!] webhook edit failed ({e}); leaving as-is")
                    return nid
            resp = self._api.add_notification(**args)
            nid = resp.get("id") if isinstance(resp, dict) else None
            log(f"[+] Created webhook notification {name} (id={nid})")
            return nid
        except Exception as e:
            log(f"[-] webhook notification upsert failed: {e}")
            return None

    # ----- status page -----------------------------------------------------

    def ensure_status_page(self, slug: str, title: str,
                           monitor_ids: List[int],
                           description: str = "") -> bool:
        """Create or update the public status page."""
        if self.dry_run:
            log(f"[dry] ensure status page slug={slug} title={title} "
                f"monitors={len(monitor_ids)}")
            return True

        # Try create; if it exists, fall back to save_status_page.
        try:
            self._api.add_status_page(slug=slug, title=title)
            log(f"[+] Created status page /{slug}")
        except Exception as e:
            vlog(f"[=] status page /{slug} exists or add failed: {e}")

        # Group all monitors under a single public list.
        public_group = [{
            "name": "Services",
            "weight": 1,
            "monitorList": [{"id": mid} for mid in monitor_ids if mid],
        }]

        try:
            self._api.save_status_page(
                slug=slug,
                title=title,
                description=description,
                publicGroupList=public_group,
                theme="auto",
                showTags=True,
            )
            log(f"[+] Saved status page /{slug} with {len(monitor_ids)} monitors")
            return True
        except Exception as e:
            log(f"[-] save_status_page failed: {e}")
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

    client = KumaClient(args.url, args.user, args.password, dry_run=args.dry_run)
    if not client.connect():
        return 0

    try:
        # 1) Monitors (idempotent).
        existing = client.list_monitors()
        created = updated = errored = 0
        name_to_id: Dict[str, int] = {}
        for m in monitors:
            action, mid = client.upsert_monitor(m, existing)
            if action == "created":
                created += 1
            elif action == "updated":
                updated += 1
            elif action == "error":
                errored += 1
            if mid is None and m["name"] in existing:
                mid = existing[m["name"]].get("id")
            if mid:
                name_to_id[m["name"]] = mid

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
                name=webhook_cfg.get("name", "nOS → Glasswing"),
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
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv[1:])

    VERBOSE = args.verbose
    return _modern_run(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
