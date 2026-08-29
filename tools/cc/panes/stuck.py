"""tools/stuck-status.py — what has STOPPED, as opposed to what failed.

Every list the reader returns becomes rows of one table with a `kind` column,
because "what has been sitting still" is one question even when it has five
sources.
"""
ID, LABEL, TITLE = "stuck", "Stuck", "what has stopped moving"
READER = "tools/stuck-status.py"
REFRESH = 300
COLUMNS = ["kind", "id", "age_days", "detail"]
DEMO = {"fees": [{"fee": "04", "slug": "systems-docs-drift", "status": "open",
                  "age_days": 39.9}]}


def build_rows(data):
    rows = []
    for kind, items in sorted(data.items()):
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                rows.append({"kind": kind, "id": "", "age_days": "", "detail": str(it)})
                continue
            age = it.get("age_days")
            rows.append({
                "kind": kind,
                "id": it.get("id") or it.get("slug") or it.get("fee") or it.get("uuid") or "",
                "age_days": f"{age:.0f}" if isinstance(age, (int, float)) else "",
                "detail": "; ".join(f"{k}={v}" for k, v in it.items()
                                    if k not in ("id", "slug", "fee", "uuid", "age_days")),
            })
    rows.sort(key=lambda r: -float(r["age_days"] or 0))
    return rows
