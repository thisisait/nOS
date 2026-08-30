"""tools/usage-status.py — token spend per provider per window, limits if declared."""
ID, LABEL, TITLE = "usage", "Usage", "subscription spend (measured locally)"
READER = "tools/usage-status.py"
REFRESH = 120
COLUMNS = ["provider", "window", "total", "output", "msgs", "limit", "pct"]
DEMO = {
    "limits_declared": True,
    "providers": [
        {"provider": "claude", "state": "ok", "note": "", "last_activity": "now",
         "windows": [{"window": "5h", "total": 12_400_000, "output": 61_000,
                      "input": 900, "cache": 12_339_100, "messages": 240,
                      "limit": 30_000_000, "pct": 41.3},
                     {"window": "7d", "total": 96_000_000, "output": 410_000,
                      "input": 7000, "cache": 95_583_000, "messages": 1810,
                      "limit": 150_000_000, "pct": 64.0}]},
        {"provider": "minimax", "state": "UNKNOWN", "windows": [],
         "source": "-", "note": "no local transcript artifact known"},
    ],
}


def build_rows(data):
    rows = []
    for p in data.get("providers", []):
        if p.get("state") != "ok":
            # A provider with no source is UNKNOWN on every window, not 0 — the
            # zero would read as "nothing spent", which is the wrong answer.
            rows.append({"provider": p.get("provider", "?"), "window": "-",
                         "total": "?", "output": "?", "msgs": "?",
                         "limit": "?", "pct": p.get("note", "")})
            continue
        for w in p["windows"]:
            rows.append({"provider": p["provider"], "window": w["window"],
                         "total": f"{w['total']:,}", "output": f"{w['output']:,}",
                         "msgs": w["messages"], "limit": f"{w['limit']:,}"
                         if w.get("limit") else "-",
                         "pct": f"{w['pct']}%" if w.get("pct") is not None
                         else "not declared"})
    return rows


def meta(data):
    return {"limits_declared": data.get("limits_declared"),
            "generated_at": data.get("generated_at")}
