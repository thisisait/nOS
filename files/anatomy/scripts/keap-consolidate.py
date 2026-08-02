#!/usr/bin/env python3
"""keap-consolidate — the cortex consolidator (the "dream" sweep).

Pulse job (keap-base). The human-sleep analogy: while the operator rests,
this job walks the RAW data piles that landed in nOS during the day —
Nextcloud user files, the ~/keap/inbox drop dir, operator-imported MariaDB
databases — and registers every new/changed item as a KEAP DATAPOINT
through the unified intake (/ingest/v1/capture, capture-tier token). The
downstream night shift then makes them knowledge: keap-embed-sync gives
them vectors (semantic findability), keap-lint candidates duplicates and
deserts, and the librarian judges. Consolidation NEVER writes the curated
layer — datapoints land in the review queue like every other capture.

── FAN-OUT (S2, docs/archive/cortex-corpus-parallel.md §2) ─────────────────
Sweep ONCE, feed N targets. `keap` is the incumbent and is always first;
`cortex` is the parallel organ, added when CORTEX_API_URL + its own
capture token are set. Absent those, this file behaves exactly as it did.

Four properties hold the fan-out together, and each closes a specific way
this could have gone wrong:

  1. THE INCUMBENT DECIDES THE EXIT CODE. A target that fails preflight is
     skipped with a recorded reason; only the incumbent's failure is a
     non-zero exit. The parallel target must never be able to degrade the
     production pipeline — otherwise standing up a shadow to MEASURE
     reliability would have COST reliability, which is a bad trade to
     discover at 03:00. Failure domains are split on day one because
     retrofitting the split after the first page is much harder.
  2. PER-TARGET STATE. The signature ledger grows a target dimension
     (v2). With one shared ledger, an item KEAP accepted while the organ
     was down would be recorded as swept and NEVER offered to the organ
     again — the corpora would differ forever and the nightly diff would
     blame ingestion. A v1 file is read as `targets.keap.*`, so the
     incumbent does not re-sweep 128 captures on the first run.
  3. NO ROLLBACK. There is no distributed transaction here, and
     simulating one means issuing a DESTRUCTIVE write in response to a
     TRANSPORT error. Deleting a row from KEAP because the organ was
     restarting is the worst available outcome. Re-sends are free instead:
     capture ids are deterministic (sid()) and /ingest/v1/capture upserts,
     so delivery is at-least-once with a deterministic key, which at the
     store is exactly-once. When unsure, send again.
  4. THE BUDGET IS PER TARGET, AND COUNTS ITEMS, NOT POSTS. Otherwise a
     second target halves the effective sweep rate and a lagging target
     starves permanently behind a moving cap — and, worse, a lagging
     target STARVES THE INCUMBENT. One shared counter meant the organ's
     empty ledger spent the whole 200-item budget inside the first root
     (a 30 000-file Nextcloud tree KEAP already holds), so the sweep
     broke out before `~/keap/inbox` was walked at all and a file the
     operator dropped tonight waited 30000/200 = 150 nights to reach
     KEAP. That is the parallel target degrading the production
     pipeline, which property 1 says cannot happen. Each target now
     spends its OWN budget: the walk continues while ANY target can
     still take work, so the incumbent always reaches the end of the
     root list on its own schedule.

  5. THE INCUMBENT DECIDES THE EXIT CODE — AT THE END, NOT ONLY AT
     PREFLIGHT. A store that was up at 04:15 and restarted at 04:16
     fails every POST, is marked DOWN after three, and used to leave the
     run returning 0 with a cheerful "N new/changed datapoints" line
     counting what the SHADOW took. A night on which production accepted
     nothing must not be indistinguishable from a clean one.

Effects OUTSIDE the stores happen once: the MariaDB `docker exec` sweep
runs once and its rows feed every target, and the notification fires once
with a per-target breakdown.

Sources (all optional; a missing source is skipped silently):
  filesystem  NOS_CONSOLIDATE_FS_ROOTS   colon-separated roots. Two shapes:
                <dir>            — walked recursively (the ~/keap/inbox drop dir)
                <dir>/*/files    — Nextcloud data layout (per-user files/)
              Small text files (.md .txt ≤64 KiB) ship their content as the
              capture text so they embed meaningfully; binaries ship
              path+size metadata (content extraction = phase 2).
  mariadb     NOS_MARIADB_ROOT_PASSWORD + NOS_CONSOLIDATE_DB_EXCLUDE
              (comma list of provisioned service DBs). Anything OUTSIDE the
              exclude list is an operator-imported knowledge dump: one
              datapoint per table (columns summary + row count).

State: ~/.nos/keap-consolidate-state.json (signature per item PER TARGET;
only new/changed items POST).

THE LEDGER IS A CACHE OF WHAT A STORE HOLDS, NOT A RECORD OF WHAT WAS
SENT. It lives outside both stores, so a store that is rebuilt while its
ledger survives would never be re-fed: the files are unchanged, the
signatures still match, and every `dp-<sha1>` capture row is gone for
good. `~/cortex/data` is documented as expendable ("re-materialises …
so removing it loses nothing without a source", tasks/removal-set.yml)
— true of the taxonomy, false of the captures. So each target's ledger
is stamped with that target's STORE EPOCH, read from its
`/ingest/v1/health`; when the epoch changes the target's ledger is
dropped and the next sweep re-offers everything it swept. Re-sends are
free by construction (property 3). A target that publishes no epoch
keeps today's behaviour exactly, and the nightly diff reports the
resulting gap as `feeder-ledger-ahead-of-store` rather than as an
ingestion defect.

Env:
  KEAP_API_URL                default http://127.0.0.1:8091
  KEAP_AGENT_TOKEN_CAPTURE    required (write-only intake tier)
  CORTEX_API_URL              set to fan out to the cortex organ (e.g.
                              http://127.0.0.1:8098); empty = single target
  CORTEX_AGENT_TOKEN_CAPTURE  the organ's OWN capture token. Deliberately a
                              DIFFERENT env name holding a DIFFERENT secret:
                              one name meaning two secrets on one host is
                              how a write token reaches the wrong daemon.
  NOS_CONSOLIDATE_FS_ROOTS    e.g. "$HOME/nextcloud-data:$HOME/keap/inbox"
  NOS_MARIADB_CONTAINER       default infra-mariadb-1
  NOS_MARIADB_ROOT_PASSWORD   empty = skip the SQL sweep
  NOS_CONSOLIDATE_DB_EXCLUDE  comma list (provisioned service DBs)
  NOS_CONSOLIDATE_MAX         per-run new-datapoint cap (default 200)
  NOS_NOTIFY_BIN              nos-notify.sh (batch summary; optional)

Exit: 0 swept (even 0 new), 1 config error, 2 the INCUMBENT was
unreachable OR went down mid-run. A parallel target being down is
reported, never fatal.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

FS_ROOTS = [p for p in os.environ.get("NOS_CONSOLIDATE_FS_ROOTS", "").split(":") if p.strip()]
DB_CONTAINER = os.environ.get("NOS_MARIADB_CONTAINER", "infra-mariadb-1")
DB_PASSWORD = os.environ.get("NOS_MARIADB_ROOT_PASSWORD", "")
DB_EXCLUDE = {
    d.strip()
    for d in os.environ.get("NOS_CONSOLIDATE_DB_EXCLUDE", "").split(",")
    if d.strip()
} | {"mysql", "information_schema", "performance_schema", "sys"}
MAX_NEW = int(os.environ.get("NOS_CONSOLIDATE_MAX", "200"))
NOTIFY_BIN = os.environ.get("NOS_NOTIFY_BIN", "")
STATE_PATH = Path.home() / ".nos" / "keap-consolidate-state.json"
STATE_VERSION = 2

MEDIA_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".mkv", ".mp3", ".wav", ".flac", ".ogg"}
TEXTUAL_EXT = {".md", ".txt", ".pdf", ".doc", ".docx", ".odt", ".rtf", ".csv", ".json", ".xml", ".html", ".epub"}
SKIP_NAMES = {".DS_Store", "Thumbs.db", "index.html", "nextcloud.log"}
INLINE_TEXT_EXT = {".md", ".txt"}
INLINE_TEXT_MAX = 64 * 1024

# A target that fails this many POSTs in a row is marked DOWN for the rest of
# the run. Without it, a crashed organ costs one 30 s timeout per swept item —
# a 200-item budget would hold the job for over an hour and the incumbent's
# sweep would finish long after the window it was scheduled in.
CONSECUTIVE_FAILURE_LIMIT = 3


def sid(key: str) -> str:
    """Stable capture id for a source key — re-sweeps update, never duplicate."""
    return "dp-" + hashlib.sha1(key.encode()).hexdigest()[:24]


class Target:
    """One write destination. Holds its OWN signature ledger, health and budget."""

    def __init__(self, name: str, base: str, token: str, incumbent: bool):
        self.name = name
        self.base = base.rstrip("/")
        self.token = token
        self.incumbent = incumbent
        self.state: dict = {}
        self.up = True
        self.reason = ""
        self.sent = 0
        self.failed = 0
        self._streak = 0
        # PER-TARGET, so a lagging shadow cannot spend the incumbent's sweep.
        self.budget = MAX_NEW
        # The store epoch this target published at preflight (None = it does not
        # publish one, which is today's behaviour for the KEAP container).
        self.epoch: str | None = None
        self.ledger_reset = False

    def ledger(self, source: str) -> dict:
        return self.state.setdefault(source, {})

    @property
    def hungry(self) -> bool:
        """Can this target still take work this run?"""
        return self.up and self.budget > 0

    def preflight(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base}/ingest/v1/health")
            raw = urllib.request.urlopen(req, timeout=10).read()
        except (urllib.error.URLError, OSError) as exc:
            self.up = False
            self.reason = f"unreachable: {exc}"
            return False
        # The epoch is OPTIONAL and its absence is not an error: KEAP's container
        # serves `{status: 'OK'}` and nothing else, and must keep working.
        try:
            body = json.loads(raw.decode())
            epoch = (body.get("data") or {}).get("storeEpoch")
            self.epoch = str(epoch) if isinstance(epoch, (str, int)) and str(epoch) else None
        except (ValueError, AttributeError):
            self.epoch = None
        return True

    def post_capture(self, envelope: dict) -> bool:
        """One capture. Returns success; NEVER raises past this boundary."""
        req = urllib.request.Request(
            f"{self.base}/ingest/v1/capture",
            data=json.dumps(envelope).encode(),
            method="POST",
        )
        req.add_header("content-type", "application/json")
        req.add_header("authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                res.read()
        except (urllib.error.URLError, OSError) as exc:
            self.failed += 1
            self._streak += 1
            if not self.reason:
                self.reason = f"post failed: {exc}"
            if self._streak >= CONSECUTIVE_FAILURE_LIMIT:
                self.up = False
                self.reason = f"{CONSECUTIVE_FAILURE_LIMIT} consecutive failures; last: {exc}"
            return False
        self.sent += 1
        self._streak = 0
        return True


def build_targets() -> list[Target]:
    """Targets in delivery order — the INCUMBENT is always first."""
    targets = [
        Target(
            "keap",
            os.environ.get("KEAP_API_URL", "http://127.0.0.1:8091"),
            os.environ.get("KEAP_AGENT_TOKEN_CAPTURE", ""),
            incumbent=True,
        )
    ]
    cortex_url = os.environ.get("CORTEX_API_URL", "").strip()
    cortex_token = os.environ.get("CORTEX_AGENT_TOKEN_CAPTURE", "").strip()
    if cortex_url and cortex_token:
        targets.append(Target("cortex", cortex_url, cortex_token, incumbent=False))
    elif cortex_url and not cortex_token:
        # Loud, and NOT a silent single-target run: a fan-out configured with a
        # URL and no token would quietly stop feeding the shadow, and the
        # nightly diff would report the resulting divergence as an ingestion
        # bug in the organ.
        print(
            "keap-consolidate: CORTEX_API_URL is set but CORTEX_AGENT_TOKEN_CAPTURE is empty — "
            "the cortex target is NOT being fed",
            file=sys.stderr,
        )
    return targets


# ── State: one ledger per target, with a v1 read-shim ────────────────────────

def load_state(targets: list[Target]) -> None:
    """Hydrate each target's ledger.

    A v1 file has top-level `fs`/`mariadb` and describes ONE target's worth of
    truth — the incumbent's. Reading it as `targets.keap.*` is what stops the
    first run under the new job from re-sweeping every datapoint KEAP already
    holds. Written as a read-time shim rather than a migration script: a
    migration that has to run exactly once, correctly, before any other work is
    a strictly worse thing to own than a branch in a reader.
    """
    try:
        raw = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        raw = {}
    if raw.get("version") == STATE_VERSION:
        per_target = raw.get("targets", {})
    else:
        per_target = {"keap": {k: v for k, v in raw.items() if k in ("fs", "mariadb")}}
    for t in targets:
        t.state = per_target.get(t.name, {})
        # ── the ledger is a cache of that STORE, and outlived it before ───────
        # A wiped store keeps its ledger, every signature still matches, and no
        # capture row is ever re-POSTed — the datapoints are simply gone. The
        # epoch closes it without an operator having to know this file exists:
        # a rebuilt store publishes a different one, and its ledger is dropped.
        # Only when the target PUBLISHES an epoch; a target that does not keeps
        # exactly today's behaviour rather than being re-fed every night.
        if not t.epoch:
            continue
        recorded = t.state.get("_epoch")
        if recorded and recorded != t.epoch:
            t.state = {}
            t.ledger_reset = True
            print(
                f"keap-consolidate: target '{t.name}' reports store epoch {t.epoch} but its ledger was "
                f"written against {recorded} — the store was rebuilt, so its ledger is dropped and this "
                "run re-offers everything (ids are deterministic; the intake upserts)",
                file=sys.stderr,
            )
        t.state["_epoch"] = t.epoch


def save_state(targets: list[Target]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"version": STATE_VERSION, "targets": {t.name: t.state for t in targets}})
    )


def needing(targets: list[Target], source: str, key: str, signature: str) -> list[Target]:
    """Targets that still have budget AND do not already hold this signature.

    Computed BEFORE the envelope is built, so an item nobody needs costs one
    dict lookup rather than a file read.
    """
    return [t for t in targets if t.hungry and t.ledger(source).get(key) != signature]


def exhausted(targets: list[Target]) -> bool:
    """True when no target can take another item — the only reason to stop
    walking. Stopping when the FIRST target fills its budget is what let a
    lagging shadow end the incumbent's sweep inside the first root."""
    return not any(t.hungry for t in targets)


def deliver(wanting: list[Target], source: str, key: str, signature: str, envelope: dict) -> None:
    """Offer one swept item to the targets that asked for it.

    Each target spends ITS OWN budget unit — an item is one item of work for
    every store that has to take it, and a store that already holds it does no
    work at all.

    State is recorded PER TARGET and only AFTER that target's ack, so a failed
    target's signature stays unwritten and the next run retries it and only it.
    The budget is spent either way: a target that cannot take 200 items is not
    made healthier by being handed 200 more.
    """
    for t in wanting:
        t.budget -= 1
        if t.post_capture(envelope):
            t.ledger(source)[key] = signature


# ── Filesystem sweep ──────────────────────────────────────────────────────────

def iter_fs_files():
    for root in FS_ROOTS:
        rootp = Path(os.path.expanduser(root))
        if not rootp.is_dir():
            continue
        # Nextcloud layout: <data>/<user>/files/** — sweep only user files,
        # never appdata/cache. A plain dir (the inbox) is walked whole.
        user_dirs = [d / "files" for d in rootp.iterdir() if (d / "files").is_dir()]
        for base in user_dirs or [rootp]:
            for path in base.rglob("*"):
                if not path.is_file() or path.name in SKIP_NAMES or path.name.startswith("."):
                    continue
                yield base, path


def sweep_fs(targets: list[Target]) -> int:
    new = 0
    for base, path in iter_fs_files():
        if exhausted(targets):
            break
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        signature = f"{int(st.st_mtime)}:{st.st_size}"
        wanting = needing(targets, "fs", key, signature)
        if not wanting:
            continue
        ext = path.suffix.lower()
        modality = "media" if ext in MEDIA_EXT else "text"
        text = None
        if ext in INLINE_TEXT_EXT and st.st_size <= INLINE_TEXT_MAX:
            try:
                text = path.read_text(errors="replace")[:8000]
            except OSError:
                text = None
        rel = str(path.relative_to(base))
        envelope = {
            "id": sid(f"fs:{key}"),
            "source": {"kind": "app", "name": "consolidator"},
            "modality": modality,
            "title": path.name,
            "text": text or f"{rel} ({st.st_size} B)",
            "tags": ["consolidated", "fs"],
            "metadata": {
                "origin": "filesystem",
                "root": str(base),
                "path": rel,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "ext": ext.lstrip("."),
            },
        }
        deliver(wanting, "fs", key, signature, envelope)
        new += 1
    return new


# ── MariaDB sweep (operator-imported knowledge dumps) ─────────────────────────

def mariadb_query(query: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "mariadb", "-uroot", f"-p{DB_PASSWORD}",
         "-N", "--batch", "-e", query],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return [line.split("\t") for line in out.stdout.splitlines() if line]


def sweep_mariadb(targets: list[Target]) -> int:
    """ONE `docker exec` sweep, whose rows feed every target.

    The load this puts on MariaDB is an effect OUTSIDE the stores, so it must
    not scale with the number of targets — the fan-out is about where the
    datapoints land, not about how often the estate is interrogated.
    """
    if not DB_PASSWORD:
        return 0
    try:
        tables = mariadb_query(
            "SELECT table_schema, table_name, table_rows FROM information_schema.tables "
            "WHERE table_type='BASE TABLE'"
        )
    except (RuntimeError, subprocess.SubprocessError, FileNotFoundError) as exc:
        print(f"keap-consolidate: mariadb sweep skipped: {exc}", file=sys.stderr)
        return 0
    new = 0
    for schema, table, rows_s in tables:
        if exhausted(targets):
            break
        if schema in DB_EXCLUDE:
            continue
        try:
            cols = mariadb_query(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema='{schema}' AND table_name='{table}' ORDER BY ordinal_position"
            )
        except RuntimeError:
            continue
        rows = int(rows_s or 0)
        col_sig = ",".join(f"{c}:{t}" for c, t in cols)
        # Row count enters the signature only by order of magnitude, so a
        # growing table doesn't re-capture every night.
        signature = hashlib.sha1(f"{col_sig}|{len(str(rows))}".encode()).hexdigest()[:16]
        key = f"{schema}.{table}"
        wanting = needing(targets, "mariadb", key, signature)
        if not wanting:
            continue
        envelope = {
            "id": sid(f"mariadb:{key}"),
            "source": {"kind": "app", "name": "consolidator"},
            "modality": "text",
            "title": f"SQL: {key}",
            "text": f"Imported table {key} (~{rows} rows). Columns: "
                    + "; ".join(f"{c} {t}" for c, t in cols[:40]),
            "tags": ["consolidated", "sql", schema],
            "metadata": {
                "origin": "mariadb",
                "database": schema,
                "table": table,
                "rows": rows,
                "columns": [{"name": c, "type": t} for c, t in cols[:100]],
            },
        }
        deliver(wanting, "mariadb", key, signature, envelope)
        new += 1
    return new


def main() -> int:
    targets = build_targets()
    incumbent = targets[0]
    if not incumbent.token:
        print("keap-consolidate: KEAP_AGENT_TOKEN_CAPTURE not set", file=sys.stderr)
        return 1

    for t in targets:
        if not t.preflight():
            print(f"keap-consolidate: target '{t.name}' {t.reason}", file=sys.stderr)
    if not incumbent.up:
        # The incumbent, and ONLY the incumbent, is fatal.
        return 2

    load_state(targets)
    try:
        fs_new = sweep_fs(targets)
        db_new = sweep_mariadb(targets)
    finally:
        save_state(targets)

    total = fs_new + db_new
    capped_targets = [t.name for t in targets if t.budget <= 0]
    capped = f" (cap reached for {', '.join(capped_targets)} — rest lands next run)" if capped_targets else ""
    breakdown = ", ".join(
        f"{t.name} {t.sent} ok/{t.failed} failed" + ("" if t.up else " [DOWN]") for t in targets
    )
    print(f"keap-consolidate: {total} new/changed datapoints (fs {fs_new}, sql {db_new}){capped} — {breakdown}")
    for t in targets:
        if t.ledger_reset:
            print(f"keap-consolidate: target '{t.name}': ledger dropped (store epoch changed) — "
                  f"{t.sent} item(s) re-sent this run", file=sys.stderr)
        if not t.up or t.failed:
            print(f"keap-consolidate: target '{t.name}': {t.reason or 'partial failures'}", file=sys.stderr)

    if NOTIFY_BIN and os.path.exists(NOTIFY_BIN):
        # ONE notification, with the per-target breakdown in it. A second target
        # must not double the operator's night-time notification volume.
        degraded = [t for t in targets if not t.incumbent and (not t.up or t.failed)]
        if degraded:
            subprocess.run(
                [NOTIFY_BIN, "medium", "KEAP consolidator: a parallel target is degraded",
                 f"{', '.join(t.name for t in degraded)} did not take the full sweep "
                 f"({breakdown}). The incumbent is unaffected; the next run retries only "
                 "what the failed target missed.",
                 "wing-inbox"],
                check=False, timeout=30,
            )
        elif total >= 10:
            subprocess.run(
                [NOTIFY_BIN, "medium", "KEAP consolidator: data batch registered",
                 f"{total} new datapoints queued for review (fs {fs_new}, sql {db_new}){capped}. "
                 f"Targets: {breakdown}. They embed on the next keap-embed-sync run.",
                 "wing-inbox"],
                check=False, timeout=30,
            )

    # ── the incumbent decides the exit code, at the END of the run ───────────
    # Preflight was the only place this was ever checked, so a store that was up
    # at 04:15 and restarted at 04:16 produced: every POST failing, the target
    # marked DOWN after three, the rest of the sweep silently skipping it — and
    # `return 0` with a stdout line counting what the SHADOW took. Pulse recorded
    # the job green. A night on which production accepted nothing has to be
    # distinguishable from a clean one, and the exit code is the only thing above
    # this job that reads anything.
    if not incumbent.up:
        print(
            f"keap-consolidate: the INCUMBENT went down mid-run ({incumbent.reason}) — "
            f"{incumbent.sent} of {incumbent.sent + incumbent.failed} POST(s) landed. Its unacknowledged "
            "signatures were NOT recorded, so the next run retries exactly what it missed.",
            file=sys.stderr,
        )
        if NOTIFY_BIN and os.path.exists(NOTIFY_BIN):
            subprocess.run(
                [NOTIFY_BIN, "high", "KEAP consolidator: the incumbent went down mid-run",
                 f"{incumbent.reason}. {incumbent.sent} capture(s) landed before it stopped answering; "
                 f"the sweep continued for the remaining targets ({breakdown}). Nothing was lost — the "
                 "next run re-offers what KEAP did not acknowledge.",
                 "wing-inbox"],
                check=False, timeout=30,
            )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
