# -*- coding: utf-8 -*-
# (c) 2026, This is AIT / nOS project
# GNU GPL v3.0 — distributed with the nOS Ansible playbook.
"""
wing_telemetry — Ansible callback plugin.

Emits structured lifecycle events (see ``state/schema/event.schema.json``) to
the Wing telemetry ingestion endpoint (BoxAPI ``/api/v1/events``), with
HMAC-SHA256 authentication, bounded batching, and a SQLite fallback queue when
the HTTP transport is unreachable.

The plugin is **inactive by default**. It activates only when one of:

* env var ``NOS_TELEMETRY_ENABLED=1`` is set, or
* play var ``wing_telemetry_enabled: true`` is present.

When inactive, every callback hook is a no-op (zero network / disk overhead).

Configuration (environment variables)
-------------------------------------
``WING_EVENTS_URL``              default ``http://api.dev.local/api/v1/events``
``WING_EVENTS_HMAC_SECRET``      shared secret; if unset, best-effort read
                                      from ``~/.nos/secrets.yml`` (key
                                      ``wing_events_hmac_secret``)
``WING_EVENTS_SQLITE_FALLBACK``  default ``/tmp/nos-events-fallback.db``
``WING_EVENTS_BATCH_SIZE``       default ``10``
``WING_EVENTS_FLUSH_INTERVAL_SEC`` default ``5``
``WING_EVENTS_DEBUG``            ``1`` prints each event to stderr and
                                      flushes immediately (no batching).
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
    name: wing_telemetry
    type: notification
    short_description: Emit nOS lifecycle events to Wing / BoxAPI.
    description:
      - "Streams structured playbook / task / migration / upgrade events to the
        Wing read model via BoxAPI /api/v1/events."
      - "Inactive unless NOS_TELEMETRY_ENABLED=1 or play var
        wing_telemetry_enabled=true is set."
      - "HMAC-SHA256 signs every batch; batches fall back to SQLite on HTTP
        failure so the operator can replay later."
    requirements:
      - "whitelisting in ansible.cfg (callback_plugins path + callbacks_enabled)"
"""

import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone

try:
    from ansible.plugins.callback import CallbackBase
except ImportError:  # pragma: no cover - allows import under pytest w/o ansible
    class CallbackBase(object):  # type: ignore[no-redef]
        CALLBACK_VERSION = 2.0
        CALLBACK_TYPE = "notification"
        CALLBACK_NAME = "wing_telemetry"

        def __init__(self, *_, **__):
            pass


# --------------------------------------------------------------------------- #
# Helpers (module-level so tests can exercise them without instantiating      #
# the callback and without bringing up an Ansible execution context).         #
# --------------------------------------------------------------------------- #

_SENSITIVE_KEY_RE = re.compile(r"password|token|secret|key|credential",
                               re.IGNORECASE)
_MIGRATION_TAG_RE = re.compile(r"^\s*\[\s*Migrate\s*\]", re.IGNORECASE)
_UPGRADE_TAG_RE = re.compile(r"^\s*\[\s*Upgrade\s*\]", re.IGNORECASE)
_PATCH_TAG_RE = re.compile(r"^\s*\[\s*Patch\s*\]", re.IGNORECASE)
_COEXIST_TAG_RE = re.compile(r"^\s*\[\s*Coexist(?:ence)?\s*\]", re.IGNORECASE)


def utc_now_iso():
    """Return current UTC time as an ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
        + "{:03d}Z".format(datetime.now(timezone.utc).microsecond // 1000)


def new_run_id():
    """Generate a new playbook run identifier (run_<uuid4>)."""
    return "run_" + str(uuid.uuid4())


def scrub(obj, _depth=0):
    """Recursively redact sensitive keys from a dict / list.

    Sensitive keys (case-insensitive substring match on ``password|token|
    secret|key|credential``) are replaced with the string ``"***"``. The
    returned structure is a *new* object — the caller's object is not
    mutated.
    """
    if _depth > 6:
        return "<max-depth>"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SENSITIVE_KEY_RE.search(k):
                out[k] = "***"
            else:
                out[k] = scrub(v, _depth + 1)
        return out
    if isinstance(obj, list):
        return [scrub(i, _depth + 1) for i in obj]
    if isinstance(obj, tuple):
        return [scrub(i, _depth + 1) for i in obj]
    # Primitives; drop non-JSON-serialisable by coercing to repr.
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return repr(obj)


def hmac_signature(secret, body_bytes):
    """Compute ``sha256=<hex>`` HMAC for the X-Wing-Signature header."""
    if not secret:
        return None
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    digest = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def extract_tagged_id(task_name, pattern):
    """Extract a slug from a tagged task name like ``[Migrate] 2026-04-22-foo``.

    Returns the trimmed text after the tag, minus any trailing description
    after the first ``—`` / ``-`` separator when the slug pattern matches.
    Returns ``None`` if the tag does not match.
    """
    if not task_name or not pattern.search(task_name):
        return None
    remainder = pattern.sub("", task_name, count=1).strip()
    if not remainder:
        return None
    # Take the first whitespace-delimited token — typically the id.
    token = remainder.split()[0].rstrip(":")
    return token or None


def load_hmac_secret_fallback(secrets_path="~/.nos/secrets.yml"):
    """Best-effort read of the HMAC secret from ``~/.nos/secrets.yml``.

    Uses a minimal regex parser so we don't require PyYAML at plugin load
    time. Returns ``None`` if the file or key is missing.
    """
    path = os.path.expanduser(secrets_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(
                    r"^wing_events_hmac_secret\s*:\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip('"').strip("'")
    except (OSError, UnicodeDecodeError):
        return None
    return None


# --------------------------------------------------------------------------- #
# Transports                                                                  #
# --------------------------------------------------------------------------- #

class HTTPTransport(object):
    """POST JSON batches to the BoxAPI ``/api/v1/events`` endpoint.

    Retries 3× with exponential backoff (0.5s, 1s, 2s). Raises
    :class:`TransportError` on final failure so the caller can spill the
    batch to the SQLite fallback.
    """

    def __init__(self, url, secret, timeout=5.0, session=None,
                 max_retries=3, backoff_base=0.5):
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._session = session  # tests inject a mock requests module

    def _requests(self):
        if self._session is not None:
            return self._session
        import requests  # local import so inactive plugin has no dep
        return requests

    def send_batch(self, events):
        """Send ``events`` (a list of dicts). Returns on success; raises on
        terminal failure after all retries are exhausted."""
        if not events:
            return
        # Body MUST be canonical (sort_keys=True, ensure_ascii=True) so Bone's
        # reconstruction in events.py matches byte-for-byte. Bone parses the
        # JSON, then re-serialises with the same flags, then verifies HMAC
        # over (ts + "." + reconstructed_body). Any drift in serialisation
        # breaks the signature.
        body = json.dumps({"events": events}, separators=(",", ":"),
                          sort_keys=True).encode("utf-8")
        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "wing-telemetry/1.0",
            "X-Wing-Timestamp": ts,
        }
        if self.secret:
            secret_bytes = self.secret.encode("utf-8") if isinstance(self.secret, str) else self.secret
            message = (ts + ".").encode("utf-8") + body
            digest = hmac.new(secret_bytes, message, hashlib.sha256).hexdigest()
            headers["X-Wing-Signature"] = digest

        requests = self._requests()
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(self.url, data=body, headers=headers,
                                     timeout=self.timeout)
                status = getattr(resp, "status_code", None)
                if status is not None and 200 <= status < 300:
                    return
                last_err = TransportError(
                    "bad status {}: {}".format(status,
                                               getattr(resp, "text", "")[:200]))
            except Exception as exc:  # noqa: BLE001 — any transport failure
                last_err = exc
            if attempt < self.max_retries:
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
        raise TransportError(
            "HTTP transport failed after {} attempts: {}".format(
                self.max_retries, last_err))


class TransportError(Exception):
    """Raised when the HTTP transport fails after exhausting retries."""


class SQLiteFallback(object):
    """Durable fallback queue for events the HTTP transport couldn't deliver.

    A single table, append-only. The operator replays with a separate tool.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS fallback_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      TEXT NOT NULL,
        ts          TEXT NOT NULL,
        type        TEXT NOT NULL,
        payload     TEXT NOT NULL,
        queued_at   TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_fallback_run_id
        ON fallback_events(run_id);
    """

    def __init__(self, path):
        self.path = path
        self._ensure_schema()

    def _conn(self):
        return sqlite3.connect(self.path, timeout=5.0)

    def _ensure_schema(self):
        conn = self._conn()
        try:
            conn.executescript(self.SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, events):
        if not events:
            return 0
        rows = [
            (e.get("run_id", ""),
             e.get("ts", ""),
             e.get("type", ""),
             json.dumps(e, separators=(",", ":"), ensure_ascii=False))
            for e in events
        ]
        conn = self._conn()
        try:
            conn.executemany(
                "INSERT INTO fallback_events (run_id, ts, type, payload) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return len(rows)

    def count(self):
        conn = self._conn()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM fallback_events")
            return cur.fetchone()[0]
        finally:
            conn.close()

    def fetch_batch(self, limit=100):
        """Return a list of (id, payload_dict) tuples, oldest first."""
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT id, payload FROM fallback_events ORDER BY id LIMIT ?",
                (limit,),
            )
            rows = []
            for row_id, payload in cur.fetchall():
                try:
                    rows.append((row_id, json.loads(payload)))
                except (TypeError, ValueError):
                    # Corrupt row — keep for forensics, skip drain
                    continue
            return rows
        finally:
            conn.close()

    def delete_ids(self, ids):
        """Remove drained events. Tolerate empty lists."""
        if not ids:
            return 0
        conn = self._conn()
        try:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                "DELETE FROM fallback_events WHERE id IN ({})".format(placeholders),
                ids,
            )
            conn.commit()
            return len(ids)
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# The callback plugin                                                         #
# --------------------------------------------------------------------------- #

class CallbackModule(CallbackBase):
    """Ansible notification callback — see module docstring."""

    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "notification"
    CALLBACK_NAME = "wing_telemetry"
    CALLBACK_NEEDS_WHITELIST = True

    # Default to localhost so the callback bypasses nginx (which 301s HTTP→HTTPS
    # and would break a plain-HTTP plugin). Override with WING_EVENTS_URL when
    # running on a remote box.
    DEFAULT_URL = "http://127.0.0.1:8099/api/v1/events"
    DEFAULT_SQLITE = "/tmp/nos-events-fallback.db"
    DEFAULT_BATCH_SIZE = 10
    DEFAULT_FLUSH_INTERVAL = 5.0
    SCHEMA_RELATIVE_PATH = "state/schema/event.schema.json"

    # ----- lifecycle -------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super(CallbackModule, self).__init__(*args, **kwargs)
        self._active = False
        self._activated_by_env = (
            os.environ.get("NOS_TELEMETRY_ENABLED", "") == "1")
        # We can't see play vars yet — finalise activation on playbook_start.

        self._run_id = new_run_id()
        self._buffer = []
        self._last_flush = time.time()

        self._playbook_name = None
        self._play_name = None
        self._play_started_at = None
        self._playbook_started_at = None
        self._task_started_at = {}  # task._uuid -> monotonic
        self._task_role_name = {}   # task._uuid -> role name
        self._current_migration_id = None
        self._current_upgrade_id = None
        self._current_patch_id = None
        self._current_coexistence_service = None

        self._debug = os.environ.get("WING_EVENTS_DEBUG", "") == "1"

        # Configurable knobs
        self._url = os.environ.get("WING_EVENTS_URL",
                                   self.DEFAULT_URL)
        self._sqlite_path = os.environ.get("WING_EVENTS_SQLITE_FALLBACK",
                                           self.DEFAULT_SQLITE)
        try:
            self._batch_size = int(os.environ.get(
                "WING_EVENTS_BATCH_SIZE", self.DEFAULT_BATCH_SIZE))
        except (TypeError, ValueError):
            self._batch_size = self.DEFAULT_BATCH_SIZE
        try:
            self._flush_interval = float(os.environ.get(
                "WING_EVENTS_FLUSH_INTERVAL_SEC",
                self.DEFAULT_FLUSH_INTERVAL))
        except (TypeError, ValueError):
            self._flush_interval = self.DEFAULT_FLUSH_INTERVAL

        self._secret = (os.environ.get("WING_EVENTS_HMAC_SECRET")
                        or load_hmac_secret_fallback())

        # ── Cross-tool event hooks (file-based, plugin-agnostic) ────────────
        # JSONL log appended on every playbook_start / playbook_end event so
        # external observers (Claude / Cursor / Copilot / Codex / fswatch /
        # Monitor / a CI watcher) can react without polling the Bone HTTP
        # endpoint. Always written, even when telemetry is otherwise inactive
        # (the JSONL has no HMAC requirement — it's a local file).
        self._jsonl_path = os.path.expanduser(os.path.expandvars(
            os.environ.get("NOS_PLAYBOOK_JSONL_PATH",
                           "~/.nos/events/playbook.jsonl")))
        # Optional shell hook scripts (executable files in this dir) get the
        # event JSON on stdin + a few NOS_* env vars. Failures don't propagate.
        # Default lives in-repo so contributors can drop hooks alongside their
        # changes (versioned per branch).
        try:
            _repo_default_hooks = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "hooks", "playbook-end.d")
        except Exception:  # pragma: no cover
            _repo_default_hooks = ""
        self._hooks_dir = os.path.expanduser(os.path.expandvars(
            os.environ.get("NOS_PLAYBOOK_HOOKS_DIR",
                           _repo_default_hooks)))

        # Lazily created so inactive plugin has no side effects.
        self._http = None
        self._sqlite = None
        self._schema_validator = None

    # ----- activation / schema ---------------------------------------------

    def _finalize_activation(self, play_vars):
        was_active = self._active
        if self._activated_by_env:
            self._active = True
        if play_vars and play_vars.get("wing_telemetry_enabled"):
            self._active = True
        if not self._active or was_active:
            # Either still inactive, or already activated — don't re-init
            # the transports (tests and real runs both depend on this).
            return
        # Late URL resolution: if the operator set wing_events_url at play
        # scope (typical for non-dev TLDs where api.dev.local doesn't
        # exist), prefer it over the hardcoded DEFAULT_URL. The env var
        # WING_EVENTS_URL still wins because it's the most explicit signal.
        env_url = os.environ.get("WING_EVENTS_URL", "")
        if not env_url and play_vars and play_vars.get("wing_events_url"):
            self._url = play_vars["wing_events_url"]
        if self._http is None:
            self._http = HTTPTransport(url=self._url, secret=self._secret)
        if self._sqlite is None:
            try:
                self._sqlite = SQLiteFallback(self._sqlite_path)
            except sqlite3.Error as exc:
                # If the fallback itself is broken we still want HTTP to work;
                # mark sqlite as unavailable and carry on.
                self._sqlite = None
                sys.stderr.write(
                    "[wing_telemetry] sqlite fallback unavailable: %s\n"
                    % exc)
        if self._schema_validator is None:
            self._load_schema_validator()
        # On activation, opportunistically drain anything left in the
        # fallback queue from previous runs that couldn't reach Bone.
        # This is best-effort — a slow Bone won't block the playbook.
        self._drain_fallback()

    def _drain_fallback(self):
        """Replay queued events to Bone. Drops them on success.

        Called once at activation (and could be called again in shutdown if
        we want belt-and-braces). Bounded by `WING_EVENTS_DRAIN_LIMIT` env
        (default 500) to avoid burning the playbook startup on a huge
        backlog — anything left rolls over to the next run.
        """
        if self._sqlite is None or self._http is None:
            return
        try:
            backlog = self._sqlite.count()
        except sqlite3.Error:
            return
        if backlog == 0:
            return
        try:
            limit = int(os.environ.get("WING_EVENTS_DRAIN_LIMIT", "500"))
        except (TypeError, ValueError):
            limit = 500
        drained = 0
        batch_size = min(self._batch_size, 50)
        if os.environ.get("WING_EVENTS_DEBUG") == "1":
            sys.stderr.write(
                "[wing_telemetry] draining {} queued events (limit={})\n"
                .format(backlog, limit))
        while drained < limit:
            try:
                rows = self._sqlite.fetch_batch(limit=batch_size)
            except sqlite3.Error:
                break
            if not rows:
                break
            row_ids = [rid for rid, _ in rows]
            events = [ev for _, ev in rows]
            try:
                self._http.send_batch(events)
            except TransportError:
                # Bone still unreachable — leave the rest for the next run.
                break
            try:
                self._sqlite.delete_ids(row_ids)
            except sqlite3.Error:
                # Drained-but-not-deleted is worse than re-sending — abort.
                break
            drained += len(row_ids)

    def _load_schema_validator(self):
        """Best-effort: load jsonschema validator if the lib is installed."""
        try:
            import jsonschema  # type: ignore
        except ImportError:
            return
        # Locate the schema relative to the playbook (callback_plugins/..)
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", self.SCHEMA_RELATIVE_PATH),
            os.path.join(os.getcwd(), self.SCHEMA_RELATIVE_PATH),
        ]
        for cand in candidates:
            cand = os.path.abspath(cand)
            if os.path.isfile(cand):
                try:
                    with open(cand, "r", encoding="utf-8") as fh:
                        schema = json.load(fh)
                    self._schema_validator = jsonschema.Draft7Validator(schema)
                    return
                except (OSError, ValueError, jsonschema.SchemaError):
                    return

    # ----- core emit -------------------------------------------------------

    def _make_event(self, event_type, **fields):
        ev = {
            "ts": utc_now_iso(),
            "run_id": self._run_id,
            "type": event_type,
            "playbook": self._playbook_name,
            "play": self._play_name,
            "task": None,
            "role": None,
            "host": None,
            "duration_ms": None,
            "changed": None,
            "result": None,
            "migration_id": self._current_migration_id,
            "upgrade_id": self._current_upgrade_id,
            "patch_id": self._current_patch_id,
            "coexistence_service": self._current_coexistence_service,
        }
        ev.update({k: v for k, v in fields.items() if v is not None
                   or k in ("result",)})
        # `result` can legitimately be None; for everything else None is
        # the default so it stays in the payload for schema compatibility.
        return ev

    def _emit(self, event_type, **fields):
        if not self._active:
            return
        ev = self._make_event(event_type, **fields)
        self._validate_or_warn(ev)
        if self._debug:
            sys.stderr.write("[wing_telemetry] %s\n"
                             % json.dumps(ev, ensure_ascii=False))
            sys.stderr.flush()
            self._buffer.append(ev)
            self._flush()
            return
        self._buffer.append(ev)
        if (len(self._buffer) >= self._batch_size
                or (time.time() - self._last_flush) >= self._flush_interval):
            self._flush()

    def _validate_or_warn(self, ev):
        if self._schema_validator is None:
            return
        errors = sorted(self._schema_validator.iter_errors(ev),
                        key=lambda e: e.path)
        if errors:
            msg = "; ".join(e.message for e in errors[:3])
            sys.stderr.write(
                "[wing_telemetry] schema violation for %s: %s\n"
                % (ev.get("type"), msg))

    def _flush(self):
        if not self._buffer:
            self._last_flush = time.time()
            return
        batch = self._buffer
        self._buffer = []
        self._last_flush = time.time()
        try:
            if self._http is not None:
                self._http.send_batch(batch)
        except TransportError as exc:
            if self._sqlite is not None:
                try:
                    self._sqlite.enqueue(batch)
                except sqlite3.Error as db_exc:
                    sys.stderr.write(
                        "[wing_telemetry] HTTP and SQLite both failed: "
                        "%s / %s\n" % (exc, db_exc))
            else:
                sys.stderr.write(
                    "[wing_telemetry] HTTP failed, no SQLite fallback: "
                    "%s\n" % exc)

    # ----- synthetic context (migration/upgrade/coexistence) ---------------

    def _update_synthetic_context(self, task_name):
        mig = extract_tagged_id(task_name, _MIGRATION_TAG_RE)
        upg = extract_tagged_id(task_name, _UPGRADE_TAG_RE)
        patch = extract_tagged_id(task_name, _PATCH_TAG_RE)
        cox = extract_tagged_id(task_name, _COEXIST_TAG_RE)
        if mig is not None:
            self._current_migration_id = mig
        if upg is not None:
            self._current_upgrade_id = upg
        if patch is not None:
            self._current_patch_id = patch
        if cox is not None:
            self._current_coexistence_service = cox

    # ----- Cross-tool lifecycle hooks (independent of telemetry on/off) -----

    def _publish_lifecycle(self, event_type, payload):
        """Append a lifecycle event to the JSONL log and execute hook scripts.

        Always runs, regardless of whether HMAC telemetry is active. Failures
        are swallowed — a broken hook must never poison the playbook run.
        Cross-tool by design: any agent can `tail -f` the JSONL or drop a
        shell script into hooks/playbook-end.d/. See docs/playbook-event-hooks.md.
        """
        # ── 1. Append JSONL (best-effort) ──────────────────────────────────
        try:
            d = os.path.dirname(self._jsonl_path)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(self._jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                "[wing_telemetry] JSONL append failed (%s): %s\n"
                % (self._jsonl_path, exc))

        # ── 2. Execute hook scripts (only on playbook_end) ─────────────────
        if event_type != "playbook_end":
            return
        try:
            if not self._hooks_dir or not os.path.isdir(self._hooks_dir):
                return
            entries = sorted(os.listdir(self._hooks_dir))
        except Exception:  # noqa: BLE001
            return
        recap = payload.get("recap") or {}
        env = os.environ.copy()
        env.update({
            "NOS_RUN_ID": payload.get("run_id") or "",
            "NOS_PLAYBOOK": payload.get("playbook") or "",
            "NOS_PLAYBOOK_DURATION_MS":
                str(payload.get("duration_ms") or ""),
            "NOS_PLAYBOOK_RECAP_OK": str(recap.get("ok") or 0),
            "NOS_PLAYBOOK_RECAP_CHANGED": str(recap.get("changed") or 0),
            "NOS_PLAYBOOK_RECAP_FAILED": str(recap.get("failed") or 0),
            "NOS_PLAYBOOK_RECAP_SKIPPED": str(recap.get("skipped") or 0),
            "NOS_PLAYBOOK_RECAP_UNREACHABLE":
                str(recap.get("unreachable") or 0),
            "NOS_PLAYBOOK_EVENT_JSON": json.dumps(payload, ensure_ascii=False),
        })
        import subprocess  # local import — keeps top of file lean
        for name in entries:
            if name.startswith(".") or name.endswith(".example") \
                    or name.endswith(".md"):
                continue
            path = os.path.join(self._hooks_dir, name)
            if not os.path.isfile(path) or not os.access(path, os.X_OK):
                continue
            try:
                subprocess.run(
                    [path],
                    input=json.dumps(payload, ensure_ascii=False),
                    text=True, env=env, timeout=15,
                    check=False, capture_output=True,
                )
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(
                    "[wing_telemetry] hook %s failed: %s\n" % (name, exc))

    # ----- Ansible v2 callback hooks ---------------------------------------

    def v2_playbook_on_start(self, playbook):
        name = getattr(playbook, "_file_name", None) \
            or getattr(playbook, "name", None)
        self._playbook_name = os.path.basename(name) if name else None
        self._playbook_started_at = time.monotonic()

        # Cross-tool lifecycle event (always; independent of telemetry gate).
        self._publish_lifecycle("playbook_start", {
            "ts": utc_now_iso(),
            "run_id": self._run_id,
            "type": "playbook_start",
            "playbook": self._playbook_name,
        })

        # Pull play vars at first play — but also peek here if possible so
        # inactive runs never allocate resources.
        self._finalize_activation(None)
        if not self._active:
            return
        self._emit("playbook_start",
                   playbook=self._playbook_name)

    def v2_playbook_on_play_start(self, play):
        self._play_name = getattr(play, "name", None) or ""
        # Peek into play vars for the activation toggle.
        try:
            play_vars = play.get_vars() if hasattr(play, "get_vars") else {}
        except Exception:  # noqa: BLE001
            play_vars = {}
        if not self._active:
            self._finalize_activation(play_vars)
            if self._active:
                # Retro-emit playbook_start so the stream is coherent.
                self._emit("playbook_start",
                           playbook=self._playbook_name)
        if not self._active:
            return
        self._play_started_at = time.monotonic()
        self._emit("play_start", play=self._play_name)

    def v2_playbook_on_task_start(self, task, is_conditional=False):
        if not self._active:
            return
        task_name = getattr(task, "get_name",
                            lambda: "")() or getattr(task, "name", "") or ""
        self._update_synthetic_context(task_name)
        role = getattr(task, "_role", None)
        role_name = getattr(role, "_role_name", None) if role else None
        self._task_started_at[getattr(task, "_uuid", id(task))] = \
            time.monotonic()
        self._task_role_name[getattr(task, "_uuid", id(task))] = role_name
        self._emit("task_start",
                   task=task_name,
                   role=role_name)

    def v2_playbook_on_handler_task_start(self, task):
        if not self._active:
            return
        task_name = getattr(task, "get_name",
                            lambda: "")() or getattr(task, "name", "") or ""
        role = getattr(task, "_role", None)
        role_name = getattr(role, "_role_name", None) if role else None
        self._task_started_at[getattr(task, "_uuid", id(task))] = \
            time.monotonic()
        self._task_role_name[getattr(task, "_uuid", id(task))] = role_name
        self._emit("handler_start", task=task_name, role=role_name)

    def _task_duration_ms(self, task):
        key = getattr(task, "_uuid", id(task))
        start = self._task_started_at.pop(key, None)
        if start is None:
            return None
        return int((time.monotonic() - start) * 1000)

    def _role_for(self, task):
        key = getattr(task, "_uuid", id(task))
        cached = self._task_role_name.pop(key, None)
        if cached:
            return cached
        role = getattr(task, "_role", None)
        return getattr(role, "_role_name", None) if role else None

    def _host_of(self, result):
        host = getattr(result, "_host", None)
        return getattr(host, "name", None) if host else None

    def _task_of(self, result):
        task = getattr(result, "_task", None)
        if task is None:
            return None, None
        name = getattr(task, "get_name",
                       lambda: "")() or getattr(task, "name", "") or ""
        return task, name

    def v2_runner_on_ok(self, result):
        if not self._active:
            return
        task, task_name = self._task_of(result)
        res_dict = getattr(result, "_result", {}) or {}
        changed = bool(res_dict.get("changed", False))
        ev_type = "task_changed" if changed else "task_ok"
        self._emit(
            ev_type,
            task=task_name,
            role=self._role_for(task) if task is not None else None,
            host=self._host_of(result),
            duration_ms=self._task_duration_ms(task) if task else None,
            changed=changed,
            result=scrub(res_dict),
        )

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if not self._active:
            return
        task, task_name = self._task_of(result)
        res_dict = getattr(result, "_result", {}) or {}
        self._emit(
            "task_failed",
            task=task_name,
            role=self._role_for(task) if task is not None else None,
            host=self._host_of(result),
            duration_ms=self._task_duration_ms(task) if task else None,
            changed=bool(res_dict.get("changed", False)),
            result=scrub(res_dict),
        )

    def v2_runner_on_skipped(self, result):
        if not self._active:
            return
        task, task_name = self._task_of(result)
        self._emit(
            "task_skipped",
            task=task_name,
            role=self._role_for(task) if task is not None else None,
            host=self._host_of(result),
            duration_ms=self._task_duration_ms(task) if task else None,
        )

    def v2_runner_on_unreachable(self, result):
        if not self._active:
            return
        task, task_name = self._task_of(result)
        res_dict = getattr(result, "_result", {}) or {}
        self._emit(
            "task_unreachable",
            task=task_name,
            role=self._role_for(task) if task is not None else None,
            host=self._host_of(result),
            result=scrub(res_dict),
        )

    def v2_playbook_on_stats(self, stats):
        # Recap aggregation runs whether or not telemetry is active — the
        # cross-tool lifecycle hook below needs the numbers regardless.
        recap = {"ok": 0, "changed": 0, "failed": 0,
                 "skipped": 0, "unreachable": 0,
                 "rescued": 0, "ignored": 0}
        try:
            hosts = sorted(stats.processed.keys())
        except AttributeError:
            hosts = []
        for h in hosts:
            s = stats.summarize(h)
            for k in recap:
                recap[k] += int(s.get(k, 0))
        duration_ms = None
        if self._playbook_started_at is not None:
            duration_ms = int(
                (time.monotonic() - self._playbook_started_at) * 1000)

        # ── Cross-tool lifecycle: JSONL append + hooks/playbook-end.d ──────
        self._publish_lifecycle("playbook_end", {
            "ts": utc_now_iso(),
            "run_id": self._run_id,
            "type": "playbook_end",
            "playbook": self._playbook_name,
            "duration_ms": duration_ms,
            "recap": recap,
        })

        if not self._active:
            return
        self._emit("playbook_end",
                   playbook=self._playbook_name,
                   duration_ms=duration_ms,
                   recap=recap)
        self._flush()


# Allow the file to be imported under pytest without Ansible present, while
# also behaving sensibly if Ansible imports it.
__all__ = [
    "CallbackModule",
    "HTTPTransport",
    "SQLiteFallback",
    "TransportError",
    "scrub",
    "hmac_signature",
    "extract_tagged_id",
    "new_run_id",
    "utc_now_iso",
    "_MIGRATION_TAG_RE",
    "_UPGRADE_TAG_RE",
    "_PATCH_TAG_RE",
    "_COEXIST_TAG_RE",
]
