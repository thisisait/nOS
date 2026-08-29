"""tools/rem-status.py — the pending security queue."""
ID, LABEL, TITLE = "rem", "Security", "remediation queue (pending)"
READER = "tools/rem-status.py"
REFRESH = 300
COLUMNS = ["id", "severity", "component", "current_version", "fix_version"]
DEMO = {"pending_by_severity": {"CRITICAL": 1, "HIGH": 3},
        "pending": [{"id": "REM-059", "severity": "MEDIUM", "component": "rustfs",
                     "current_version": "1.0.0-alpha.90", "fix_version": "1.0.0-rc.1"}]}


def build_rows(data):
    return data.get("pending", [])


def meta(data):
    return {"by_severity": data.get("pending_by_severity"), "total": data.get("total")}
