"""tools/wing-status.py — what Wing is made of, and what it costs.

The map's buckets are one question — *which of these 45 tables is actually
doing something* — so they become one table with a `state` column rather than
five panes. Sorted so the answerable rows come first: what is written and never
read, then what is empty, then what the committed contract does not describe,
then the live ones by size.
"""
ID, LABEL, TITLE = "wing", "Wing", "what the organ is made of"
READER = "tools/wing-status.py"
REFRESH = 900          # a table's row count does not move in seconds
COLUMNS = ["state", "table", "rows", "MB", "w", "r"]
DEMO = {"db": "~/wing/app/data/wing.db", "bytes": 1223000000, "tables": [
    {"table": "events", "declared": True, "live": True, "rows": 380248,
     "bytes": 1190000000, "writers": ["files/anatomy/bone/ledger.py"],
     "readers": ["files/anatomy/wing/app/Model/EventRepository.php"]},
    {"table": "users", "declared": True, "live": True, "rows": 0,
     "bytes": 4096, "writers": [], "readers": []},
]}

#: Reading order: a table nothing reads is the row worth acting on.
_RANK = {"WRITE-ONLY": 0, "EMPTY": 1, "UNDECLARED": 2, "MISSING": 3, "LIVE": 4}


def _state(t):
    if not t.get("live"):
        return "MISSING"
    if not t.get("declared"):
        return "UNDECLARED"
    if not t.get("rows"):
        return "EMPTY"
    if not t.get("readers"):
        return "WRITE-ONLY"
    return "LIVE"


def build_rows(data):
    rows = []
    for t in data.get("tables", []):
        mb = (t.get("bytes") or 0) / 1e6
        rows.append({
            "state": _state(t),
            "table": t.get("table", ""),
            "rows": "—" if t.get("rows") is None else f"{t['rows']:,}",
            # Blank rather than 0.0 below a tenth of a megabyte: forty rows of
            # "0.0 MB" hide the one row that says 1190.
            "MB": f"{mb:.0f}" if mb >= 1 else "",
            "w": str(len(t.get("writers") or [])),
            "r": str(len(t.get("readers") or [])),
        })
    rows.sort(key=lambda r: (_RANK.get(r["state"], 9),
                             -float(r["MB"] or 0),
                             r["table"]))
    return rows
