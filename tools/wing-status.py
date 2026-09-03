#!/usr/bin/env python3
"""What Wing actually is: 46 tables, who writes each, who reads it, what it costs.

WHY THIS EXISTS. The operator's words, 2026-08-29: *"wing začíná být těžko
uchopitelný orgán"* — Wing is becoming a hard organ to get hold of. That is not
a vague complaint, it is an unanswerable question. Wing is 33k lines of PHP, 23
web presenters, 25 API presenters, 27 CLI scripts and 46 tables covering nine
unrelated concerns (audit, GDPR, pentest, remediation, agents, pulse, upgrades,
coexistence, users). Nothing in the estate could say which of those tables carry
anything, which are written and never read, or what any of it costs on disk.

The estate already answers its other "what is true right now" questions with a
reader rather than by hand — `red-status`, `agent-status`, `loop-status`,
`rem-status`, `identity-status`. Wing had none, so every question about Wing was
answered by grepping, and a grep answers once.

WHAT IT FOUND ON ITS FIRST RUN, which is why it is worth its own file:

    events         380 248 rows   1085 MB    97% of rows are Ansible task noise
    result_json    921 MB total   of which `task_ok` alone is 657 MB
    single rows    up to 4.1 MB   pazny.state_manager introspection results
    largest key    `invocation`   Ansible echoing back the module's OWN ARGUMENTS

and fourteen tables holding zero rows, three of them AgentKit subsystems
(`agent_vaults`, `agent_credentials`, `agent_subscriptions`) that have shipped,
been documented, and never once been exercised.

WHAT IT WILL NOT DO. It never writes. It opens the database read-only (`mode=ro`)
so it cannot even be asked to. It does not purge, vacuum, migrate or repair; the
retention purge is `bin/purge-events.php` and stays a deliberate act with an
operator behind it, because deleting audit rows is not a thing a status command
should be able to do by accident.

THE CEILING, stated because it decides how much the "unread" column is worth.
Access is found by matching TEXT around each occurrence of the table's name, in
BOTH idioms this codebase uses: raw SQL (`INSERT INTO t`, `FROM t`) and Nette's
fluent builder (`->table('t')->insert(...)`). The first draft of this file
matched SQL only and reported ten tables as write-only, of which most were
false — `agent_threads` is written by `$this->db->table('agent_threads')
->insert(...)`, which contains no SQL at all. That miss is recorded here rather
than quietly fixed because it is the same shape the estate keeps paying for: a
detector that reads one spelling reports the other as absent.

What survives the fix is still text matching, so a table named at runtime is
invisible, and `no reader` means *no reader found by this method*. The tool
prints that qualifier rather than the claim. Upgrade path: parse the PHP with
nikic/php-parser — worth it the day a dynamic table name exists, which grepping
for `table($` and `FROM {$` says it does not today.

Usage:
  tools/wing-status.py                 # the map
  tools/wing-status.py --json          # same, machine-readable
  tools/wing-status.py --cost          # bytes only, biggest first
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
WING_DB = pathlib.Path.home() / "wing" / "app" / "data" / "wing.db"
SCHEMA = REPO / "files/anatomy/skills/contracts/wing.db-schema.sql"

# Where a query to wing.db can legitimately come from. Bone owns the loop_*
# tables in the same file, which is why its tree is in here beside Wing's.
SEARCH = ("files/anatomy/wing/app", "files/anatomy/wing/bin", "files/anatomy/bone",
          "tools", "files/anatomy/face/src", "files/anatomy/plugins")

SUFFIXES = (".php", ".py", ".ts", ".svelte", ".sh", ".sql", ".j2", ".latte")

# Read BEFORE the name (`INSERT INTO t`) and AFTER it (`->table('t')->insert`),
# because the two idioms put the verb on opposite sides.
BEFORE_W = re.compile(r"(insert(\s+or\s+\w+)?\s+into|replace\s+into|update|delete\s+from)\s*$", re.I)
BEFORE_R = re.compile(r"(from|join)\s*$", re.I)
AFTER_W = re.compile(r"^\W{0,4}\s*->\s*(insert|update|delete)\b", re.I | re.S)
AFTER_R = re.compile(
    r"^\W{0,4}\s*->\s*(select|where|order|group|limit|fetch\w*|count|get|min|max|sum)\b",
    re.I | re.S)


def _files() -> list[tuple[str, str]]:
    """(relative path, body) for every source file that could touch wing.db."""
    out = []
    for d in SEARCH:
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if (p.suffix not in SUFFIXES or not p.is_file()
                    or p == pathlib.Path(__file__).resolve()  # its own examples
                    or "node_modules" in p.parts or "vendor" in p.parts):
                continue
            try:
                out.append((str(p.relative_to(REPO)), p.read_text(encoding="utf-8")))
            except (UnicodeDecodeError, OSError):
                continue
    return out


def _declared() -> set[str]:
    body = SCHEMA.read_text(encoding="utf-8")
    return set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", body))


def _access(tables: list[str],
            files: list[tuple[str, str]] | None = None) -> dict[str, dict[str, set[str]]]:
    """Per table: which files write it, which read it. One pass over the tree.

    Classified from the CONTEXT of each occurrence of the bare name, so both
    `INSERT INTO agent_threads` and `->table('agent_threads')->insert(` land in
    the same bucket. An occurrence with no verb on either side (a comment, a
    docstring, a column list) is deliberately counted as neither.
    """
    acc = {t: {"writers": set(), "readers": set()} for t in tables}
    pats = {t: re.compile(rf"\b{re.escape(t)}\b") for t in tables}
    for path, body in (_files() if files is None else files):
        for t, pat in pats.items():
            for m in pat.finditer(body):
                before, after = body[max(0, m.start() - 40):m.start()], body[m.end():m.end() + 40]
                if BEFORE_W.search(before) or AFTER_W.match(after):
                    acc[t]["writers"].add(path)
                elif BEFORE_R.search(before) or AFTER_R.match(after):
                    acc[t]["readers"].add(path)
    return acc


def collect() -> dict:
    # 2026-08-20 measurement, bit again 2026-09-03 (agent-status): a bare
    # mode=ro open dies once Wing checkpoints and drops the WAL sidecars.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ledger_open", REPO / "tools" / "_ledger_open.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db, how = mod.open_ledger_ro(WING_DB)
    if db is None:
        return {"error": how, "tables": []}

    # dbstat is a virtual table compiled into most builds; absence is reported,
    # never guessed at, because a fabricated size is worse than none.
    try:
        size = dict(db.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY 1"))
    except sqlite3.Error:
        size = {}

    tables, declared = [], _declared()
    live = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    names = sorted(set(live) | declared)
    acc = _access(names)
    for t in names:
        row: dict = {"table": t, "declared": t in declared, "live": t in live}
        row["rows"] = (db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                       if t in live else None)
        # Index pages belong to the table that owns them, or a 1 GB table
        # reports as 700 MB and the biggest cost hides in the smallest column.
        row["bytes"] = size.get(t, 0) + sum(
            b for n, b in size.items() if n.startswith(f"idx_{t}_"))
        # NOT subtracted. A repository both writes and reads its own table, and
        # a first draft that removed writers from readers called `gdpr_processing`
        # write-only because its only reader is the class that also inserts.
        # Write-only has to mean "read NOWHERE", or the bucket reports a code
        # layout instead of a fact about the data.
        row["writers"] = sorted(acc[t]["writers"])
        row["readers"] = sorted(acc[t]["readers"])
        tables.append(row)

    return {"db": str(WING_DB), "bytes": WING_DB.stat().st_size, "tables": tables}


def _bucket(t: dict) -> str:
    if not t["live"]:
        return "MISSING"          # declared in the contract, absent from the db
    if not t["declared"]:
        return "UNDECLARED"       # in the db, in no committed schema
    if not t["rows"]:
        return "EMPTY"
    if not t["readers"]:
        return "WRITE-ONLY"
    return "LIVE"


def render(data: dict, cost_only: bool = False) -> int:
    if data.get("error"):
        print(f"UNKNOWN — {data['error']}")
        return 0
    ts = data["tables"]
    print(f"wing.db — {data['bytes'] / 1e6:.0f} MB, {len(ts)} tables\n")

    if cost_only:
        for t in sorted(ts, key=lambda r: -r["bytes"])[:15]:
            print(f"  {t['bytes'] / 1e6:>8.1f} MB  {str(t['rows']):>8} rows  {t['table']}")
        return 0

    # The headline, because 45 buckets of rows do not by themselves say where
    # the organ's weight is. It is in one table, and it is in one column of it.
    big = max(ts, key=lambda r: r["bytes"])
    if big["bytes"] > 0.5 * data["bytes"]:
        print(f"  {big['bytes'] / data['bytes']:.0%} of the organ is one table: "
              f"{big['table']} ({big['rows']:,} rows)\n")

    order = ["WRITE-ONLY", "EMPTY", "UNDECLARED", "MISSING", "LIVE"]
    for bucket in order:
        rows = [t for t in ts if _bucket(t) == bucket]
        if not rows:
            continue
        print(f"  {bucket} ({len(rows)})")
        for t in sorted(rows, key=lambda r: -(r["bytes"] or 0)):
            n = "—" if t["rows"] is None else f"{t['rows']:,}"
            mb = f"{t['bytes'] / 1e6:.0f} MB" if t["bytes"] > 1e6 else ""
            note = ""
            if bucket == "WRITE-ONLY":
                note = f"  written by {', '.join(t['writers']) or 'nothing found'}"
            elif bucket == "EMPTY" and not t["writers"]:
                note = "  and nothing writes it"
            print(f"    {n:>10} rows {mb:>8}  {t['table']}{note}")
        if bucket == "UNDECLARED":
            print("    ^ in wing.db, in no committed schema. Bone creates the")
            print("      loop_* tables in Wing's file; only Wing exports a")
            print("      contract, so the contract does not describe the db.")
        print()

    print("  'no reader' means no reader FOUND — SQL is matched as text, so a")
    print("  table named at runtime would not be seen. See this file's header.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cost", action="store_true", help="bytes only, biggest first")
    args = ap.parse_args(argv)
    data = collect()
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    return render(data, args.cost)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
