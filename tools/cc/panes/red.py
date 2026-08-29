"""tools/red-status.py — every RED as a row, plus each freshness source."""
ID, LABEL, TITLE = "red", "Red", "what is red RIGHT NOW"
READER = "tools/red-status.py"
REFRESH = 30
COLUMNS = ["id", "signal", "status", "detail"]
DEMO = {
    "red_count": 2,
    "reds": ["2 loop proposals passed the judges and never reached the tree",
             "11 unread CRITICAL/HIGH in the Wing inbox"],
    "backups": {"stale": False, "sources": 14, "age": "15 h ago"},
    "audit_chain": {"ok": True, "unsigned": 37, "age": "11 h ago"},
    "security_scan": {"stale": False, "cycle": 46, "age": "37 h ago"},
    "restore_drill": {"stale": False, "age": "6 d ago"},
}


def build_rows(data):
    rows = [{"id": f"red-{i}", "signal": "red", "status": "RED", "detail": t}
            for i, t in enumerate(data.get("reds", []), 1)]
    for key in ("backups", "audit_chain", "security_scan", "restore_drill"):
        sub = data.get(key)
        if sub is None:
            rows.append({"id": key, "signal": key, "status": "UNKNOWN",
                         "detail": "source missing — not the same as fine"})
            continue
        bad = sub.get("stale") is True or sub.get("ok") is False
        rows.append({"id": key, "signal": key, "status": "STALE" if bad else "OK",
                     "detail": ", ".join(f"{k}={v}" for k, v in sub.items())})
    return rows


def meta(data):
    return {"red_count": data.get("red_count"), "generated_at": data.get("generated_at")}
