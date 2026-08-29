"""tools/roadmap-status.py — every roadmap row, never a top-N."""
ID, LABEL, TITLE = "roadmap", "Roadmap", "roadmap"
READER = "tools/roadmap-status.py"
REFRESH = 300
COLUMNS = ["slug", "status", "track", "kind", "severity", "title"]
DEMO = {"rows": [{"slug": "rel-011", "status": "shipped", "track": "release",
                  "kind": "epic", "title": "v0.11-beta"}]}


def build_rows(data):
    return data.get("rows", [])
