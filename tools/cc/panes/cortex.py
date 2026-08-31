"""tools/cortex-status.py — the cortex organ, both runtimes and the seam.

The organ that had a Grafana dashboard and neither a pane nor a face view,
while every other organ had at least two surfaces. Rows are ordered by what
would ruin your morning: a broken seam first, then an unreachable half, then
the facts.
"""
ID, LABEL, TITLE = "cortex", "Cortex", "one organ, two runtimes"
READER = "tools/cortex-status.py"
REFRESH = 300           # a registry hash moves on a deploy, not on a timer
COLUMNS = ["state", "part", "detail"]
DEMO = {
    "validate": {"reachable": True, "version": "0.1.0", "surface": "enabled",
                 "registry_hash": "cx1:1fe4e8517d0b2b7f", "spine_in_sync": True,
                 "ontology": "onto1:c0018195889bb732"},
    "execute": {"reachable": True, "runtime": "wing (php)", "covers_keap": True,
                "handlers": ["get", "map", "rank"], "uncovered": [],
                "registry_hash": "cx1:1fe4e8517d0b2b7f"},
    "seam": {"agree": True, "validate": "cx1:1fe4e8517d0b2b7f", "detail": ""},
    "traffic": {"readable": True, "stages_7d": 152, "chains_7d": 127,
                "by_length": {"1": 102, "2": 25}},
}

_RANK = {"BROKEN": 0, "UNKNOWN": 1, "OK": 2}


def build_rows(data):
    rows = []
    seam = data.get("seam") or {}
    agree = seam.get("agree")
    rows.append({
        "state": {True: "OK", False: "BROKEN", None: "UNKNOWN"}[agree],
        "part": "seam",
        # The hash IS the detail: two halves publishing the same string is the
        # whole claim, so show it rather than a tick.
        "detail": (seam.get("validate") or "?") if agree
        else (seam.get("detail") or "")[:110],
    })

    for part in ("validate", "execute"):
        half = data.get(part) or {}
        if not half.get("reachable"):
            rows.append({"state": "UNKNOWN", "part": part,
                         "detail": f"unreachable — {(half.get('detail') or '')[:90]}"})
            continue
        if part == "validate":
            detail = (f"node :8098  v{half.get('version')}  {half.get('surface')}  "
                      f"spine {'in sync' if half.get('spine_in_sync') else 'OUT OF SYNC'}")
            state = "OK" if half.get("spine_in_sync") else "BROKEN"
        else:
            handlers = half.get("handlers") or []
            uncovered = half.get("uncovered") or []
            detail = (f"{half.get('runtime')}  {len(handlers)} handler(s): "
                      f"{' '.join(handlers)}")
            if uncovered:
                detail += f"  UNCOVERED: {', '.join(uncovered)}"
            state = "OK" if half.get("covers_keap") and not uncovered else "BROKEN"
        rows.append({"state": state, "part": part, "detail": detail})

    t = data.get("traffic") or {}
    if t.get("readable"):
        shape = ", ".join(f"{n}-stage x{c}" for n, c in sorted((t.get("by_length") or {}).items()))
        rows.append({"state": "OK", "part": "traffic",
                     "detail": f"{t.get('stages_7d')} stage(s) in "
                               f"{t.get('chains_7d')} chain(s), 7d  {shape}"})
    else:
        rows.append({"state": "UNKNOWN", "part": "traffic",
                     "detail": (t.get("detail") or "")[:90]})

    rows.sort(key=lambda r: (_RANK.get(r["state"], 9), r["part"]))
    return rows
