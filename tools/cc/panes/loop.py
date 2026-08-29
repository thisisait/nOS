"""tools/loop-status.py — weakness source to proposal to verdict."""
ID, LABEL, TITLE = "loop", "Loops", "weakness -> proposal -> verdict"
READER = "tools/loop-status.py"
REFRESH = 120
COLUMNS = ["source", "gloss", "proposals", "pass", "fail", "indeterminate", "unjudged"]
DEMO = {"sources": [{"source": "rem", "gloss": "remediation queue", "proposals": 34,
                     "pass": 23, "fail": 5, "indeterminate": 6, "unjudged": 0}]}


def build_rows(data):
    return data.get("sources", [])


def meta(data):
    return {"live_weaknesses": data.get("live_weakness_count"),
            "proposals": data.get("proposals")}
