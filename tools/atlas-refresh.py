#!/usr/bin/env python3
"""Regenerate the nos-atlas data GeoLibre serves (Pulse geolibre:atlas-refresh).

Records the reader snapshot nos-atlas' README asks for, read-only, into a temp dir:
red-status.json and estate-status.json (`--json`, `--no-fetch`), and pulse_jobs /
pulse_runs from wing.db opened read-only WITHOUT command, args or env. Then runs
`node src/generator/build.ts` from the nos-atlas checkout and copies its output into
<data-dir>/plugins/nos-atlas/data, the directory the container mounts :ro.

  tools/atlas-refresh.py --data-dir ~/nos/.../geolibre/data --atlas-src ~/projects/nos-atlas

The taxonomy fixture is NOT rebuilt here (build-fixture.ts writes into the checkout).
Exit 0 done or off (empty --data-dir), 2 a step failed (nothing copied).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from _ledger_open import open_ledger_ro  # noqa: E402

# The columns nos-atlas reads; anything else (command, args_json, env_json,
# stdout_tail) never leaves the ledger.
JOB_COLS = ("id", "plugin_name", "job_name", "runner", "schedule", "category", "paused",
            "paused_reason", "next_fire_at", "last_fired_at", "findings_exit_codes")
RUN_COLS = ("job_id", "fired_at", "exit_code", "duration_ms")
NODES = ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node")


def pulse_tables(conn) -> tuple[list[dict], list[dict]]:
    def rows(table: str, wanted: tuple[str, ...], tail: str) -> list[dict]:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        cols = [c for c in wanted if c in have]
        cur = conn.execute(f"SELECT {', '.join(cols)} FROM {table} {tail}")
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    return (rows("pulse_jobs", JOB_COLS, "ORDER BY rowid"),
            rows("pulse_runs", RUN_COLS,
                 "WHERE fired_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days') "
                 "ORDER BY fired_at DESC LIMIT 5000"))


def _reader(script: str, *args: str) -> dict:
    out = subprocess.run([sys.executable, str(REPO / "tools" / script), *args],
                         capture_output=True, text=True, timeout=300, check=False)
    return json.loads(out.stdout)


def snapshot(dest: pathlib.Path) -> None:
    (dest / "red-status.json").write_text(json.dumps(_reader("red-status.py", "--json")))
    (dest / "estate-status.json").write_text(json.dumps(_reader("estate-status.py", "--json", "--no-fetch")))
    conn, how = open_ledger_ro()
    jobs, runs = pulse_tables(conn) if conn else ([], [])
    if not conn:
        print(f"wing.db unreadable ({how}): the buildings will read UNKNOWN")
    (dest / "pulse_jobs.json").write_text(json.dumps(jobs))
    (dest / "pulse_runs.json").write_text(json.dumps(runs))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", required=True, help="geolibre_data_dir; empty = GeoLibre off")
    ap.add_argument("--atlas-src", required=True, help="the nos-atlas checkout (nos_atlas_src_dir)")
    a = ap.parse_args(argv)
    if not a.data_dir or not a.atlas_src:
        print("geolibre is off (no data dir): nothing to do")
        return 0
    src = pathlib.Path(a.atlas_src)
    fixture = src / "fixtures/keap-taxonomy.json"
    node = shutil.which("node") or next((n for n in NODES if pathlib.Path(n).is_file()), None)
    if not fixture.is_file() or not node:
        print(f"cannot build: fixture {fixture} present={fixture.is_file()}, node={node}", file=sys.stderr)
        return 2
    dest = pathlib.Path(a.data_dir) / "plugins/nos-atlas/data"
    with tempfile.TemporaryDirectory(prefix="atlas-") as tmp:
        snap, out = pathlib.Path(tmp, "snapshot"), pathlib.Path(tmp, "out")
        snap.mkdir()
        try:
            snapshot(snap)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            print(f"snapshot failed: {exc}", file=sys.stderr)
            return 2
        gen = subprocess.run(
            [node, "src/generator/build.ts", "--fixture", str(fixture), "--snapshot", str(snap),
             "--nos", str(REPO), "--out", str(out)],
            cwd=src, capture_output=True, text=True, timeout=480, check=False)
        print(gen.stdout.strip())
        if gen.returncode != 0 or not (out / "style.json").is_file():
            print(f"generator exit {gen.returncode}: {gen.stderr.strip()[-2000:]}", file=sys.stderr)
            return 2
        shutil.copytree(out, dest, dirs_exist_ok=True)
    print(f"atlas data → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
