"""tools/permission-status.py — what macOS will and will not let this estate do.

Probes, log verdicts and the launchd roster are one question — *is anything
about to stall on a dialog nobody is looking at* — so they become one table
with a `kind` column. DENIED sorts first; it is the only row worth acting on.
"""
ID, LABEL, TITLE = "perms", "Permissions", "what macOS will let us do"
READER = "tools/permission-status.py"
REFRESH = 1800          # a grant changes when a human changes it, not on a timer
COLUMNS = ["kind", "state", "subject", "detail"]
DEMO = {
    "days": 2,
    "probes": [{"capability": "Full Disk Access", "state": "DENIED",
                "detail": "~/Library/.../com.apple.TCC: Operation not permitted",
                "subject": "/usr/bin/python3", "matters": "other apps' data"}],
    "grants": [{"binary": "com.docker.docker", "service": "SystemPolicyAllFiles",
                "state": "DENIED", "requests": 16}],
    "agents": [{"agent": "eu.thisisait.nos.cortex", "version_pinned": True,
                "binary": "~/.nvm/versions/node/v24.20.0/bin/node"}],
}

_RANK = {"DENIED": 0, "UNKNOWN": 1, "LIMITED": 2, "OK": 3}


def build_rows(data):
    rows = []
    for p in data.get("probes") or []:
        rows.append({"kind": "probe", "state": p.get("state", "?"),
                     "subject": p.get("capability", ""),
                     "detail": (p.get("detail") or "").replace("\n", " ")[:120]})
    for g in data.get("grants") or []:
        if "error" in g:
            rows.append({"kind": "grant", "state": "UNKNOWN",
                         "subject": "the TCC log", "detail": g["error"][:120]})
            continue
        rows.append({"kind": "grant", "state": g.get("state", "?"),
                     "subject": g.get("service", ""),
                     "detail": f"{g.get('binary','')} x{g.get('requests',0)}"[:120]})
    for a in data.get("agents") or []:
        # A launchd agent is never OK or DENIED here — nothing this reader runs
        # speaks for it. UNPROVEN is the honest state, and the version-pinned
        # ones are the subset whose grant an ordinary upgrade silently drops.
        rows.append({"kind": "agent", "state": "UNPROVEN",
                     "subject": a.get("agent", "").replace("eu.thisisait.nos.", ""),
                     "detail": a.get("binary", "")
                     + ("  <- version-pinned" if a.get("version_pinned") else "")})
    rows.sort(key=lambda r: (_RANK.get(r["state"], 9), r["kind"], r["subject"]))
    return rows
