#!/usr/bin/env python3
"""
nOS backup_status_exporter

Reads ~/.nos/backup-status.json (written by the pazny.backup role) and emits
Prometheus textfile-format metrics to a .prom file that node_exporter /
prometheus.exporter.unix's textfile collector will scrape.

Designed for frequent invocation (every minute is fine) from cron or a launchd
agent. Writes atomically (tmp file + rename). Exits 0 even if the status file
is missing — in that case the .prom output is empty except for a heartbeat
so dashboards can detect "no backup ever ran".

Contract (input JSON shape, written by pazny.backup role):
{
  "last_run":    <unix_ts_seconds>,
  "duration_ms": <int>,
  "sources": [
    {"name": "...", "size_bytes": N, "duration_ms": N, "success": true/false},
    ...
  ]
}

Output metrics:
  nos_backup_last_run_timestamp_seconds       (gauge)
  nos_backup_duration_seconds                 (gauge)
  nos_backup_source_size_bytes{source}        (gauge)
  nos_backup_source_success{source}           (gauge, 1/0)
  nos_backup_source_duration_seconds{source}  (gauge)
  nos_backup_exporter_last_run_timestamp_seconds (gauge — heartbeat)
  nos_backup_status_file_present              (gauge, 1/0)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_STATUS_FILE = Path(os.environ.get(
    "NOS_BACKUP_STATUS_FILE",
    str(Path.home() / ".nos" / "backup-status.json"),
))
DEFAULT_OUTPUT_FILE = Path(os.environ.get(
    "NOS_BACKUP_PROM_FILE",
    "/var/lib/node_exporter/textfile/backup.prom",
))


def _escape_label(value: str) -> str:
    """Escape a label value per Prometheus exposition format."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _render(status: dict | None, now: float) -> str:
    lines: list[str] = []

    lines += [
        "# HELP nos_backup_exporter_last_run_timestamp_seconds Unix timestamp "
        "of the last exporter run (heartbeat)",
        "# TYPE nos_backup_exporter_last_run_timestamp_seconds gauge",
        f"nos_backup_exporter_last_run_timestamp_seconds {now:.0f}",
        "",
        "# HELP nos_backup_status_file_present Whether the backup-status.json "
        "file exists (1/0)",
        "# TYPE nos_backup_status_file_present gauge",
        f"nos_backup_status_file_present {1 if status is not None else 0}",
        "",
    ]

    if status is None:
        return "\n".join(lines) + "\n"

    last_run = status.get("last_run")
    if isinstance(last_run, (int, float)):
        lines += [
            "# HELP nos_backup_last_run_timestamp_seconds Unix timestamp of "
            "the last backup run",
            "# TYPE nos_backup_last_run_timestamp_seconds gauge",
            f"nos_backup_last_run_timestamp_seconds {float(last_run):.0f}",
            "",
        ]

    duration_ms = status.get("duration_ms")
    if isinstance(duration_ms, (int, float)):
        lines += [
            "# HELP nos_backup_duration_seconds Duration of the last backup "
            "run in seconds",
            "# TYPE nos_backup_duration_seconds gauge",
            f"nos_backup_duration_seconds {float(duration_ms) / 1000.0:.3f}",
            "",
        ]

    sources = status.get("sources") or []
    if isinstance(sources, list) and sources:
        # size
        lines += [
            "# HELP nos_backup_source_size_bytes Backup size by source",
            "# TYPE nos_backup_source_size_bytes gauge",
        ]
        for src in sources:
            if not isinstance(src, dict):
                continue
            name = _escape_label(src.get("name", "unknown"))
            size = src.get("size_bytes")
            if isinstance(size, (int, float)):
                lines.append(
                    f'nos_backup_source_size_bytes{{source="{name}"}} '
                    f"{int(size)}"
                )
        lines.append("")

        # success
        lines += [
            "# HELP nos_backup_source_success Whether the source's last "
            "backup succeeded (1/0)",
            "# TYPE nos_backup_source_success gauge",
        ]
        for src in sources:
            if not isinstance(src, dict):
                continue
            name = _escape_label(src.get("name", "unknown"))
            success = 1 if src.get("success") else 0
            lines.append(
                f'nos_backup_source_success{{source="{name}"}} {success}'
            )
        lines.append("")

        # duration
        lines += [
            "# HELP nos_backup_source_duration_seconds Duration per source "
            "in seconds",
            "# TYPE nos_backup_source_duration_seconds gauge",
        ]
        for src in sources:
            if not isinstance(src, dict):
                continue
            name = _escape_label(src.get("name", "unknown"))
            d_ms = src.get("duration_ms")
            if isinstance(d_ms, (int, float)):
                lines.append(
                    f'nos_backup_source_duration_seconds{{source="{name}"}} '
                    f"{float(d_ms) / 1000.0:.3f}"
                )
        lines.append("")

        # total source count + success count
        total = len(sources)
        ok = sum(1 for s in sources if isinstance(s, dict) and s.get("success"))
        lines += [
            "# HELP nos_backup_source_count Total number of backup sources "
            "in the last run",
            "# TYPE nos_backup_source_count gauge",
            f"nos_backup_source_count {total}",
            "",
            "# HELP nos_backup_source_success_count Number of sources whose "
            "last backup succeeded",
            "# TYPE nos_backup_source_success_count gauge",
            f"nos_backup_source_success_count {ok}",
            "",
        ]

    return "\n".join(lines) + "\n"


def _read_status(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        # Corrupt status file — emit just the heartbeat/"not present".
        sys.stderr.write(f"backup_status_exporter: unreadable status file: {exc}\n")
        return None


def _atomic_write(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(output.parent),
        prefix=output.name + ".",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, output)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    status_file = DEFAULT_STATUS_FILE
    output_file = DEFAULT_OUTPUT_FILE

    # Minimal CLI: --status <path> --output <path>
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--status" and i + 1 < len(argv):
            status_file = Path(argv[i + 1])
            i += 2
        elif arg == "--output" and i + 1 < len(argv):
            output_file = Path(argv[i + 1])
            i += 2
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            sys.stderr.write(f"backup_status_exporter: unknown arg: {arg}\n")
            i += 1

    status = _read_status(status_file)
    content = _render(status, now=time.time())

    try:
        _atomic_write(output_file, content)
    except OSError as exc:
        sys.stderr.write(f"backup_status_exporter: write failed: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
