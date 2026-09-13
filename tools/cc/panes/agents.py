"""tools/agent-status.py — one row per agent session."""
ID, LABEL, TITLE = "agents", "Agents", "what the agents did, and how the runs ended"
READER = "tools/agent-status.py"
REFRESH = 20
COLUMNS = ["uuid", "agent", "trigger", "status", "outcome", "tokens_in", "tokens_out", "age"]
DEMO = {
    "running": [
        {"uuid": "11aa22bb", "agent": "surveyor", "trigger": "pulse", "status": "running",
         "outcome": None, "tokens_in": 0, "tokens_out": 0, "age": "3m"},
    ],
    "recent": [
        {"uuid": "be9d107f", "agent": "librarian", "trigger": "pulse", "status": "idle",
         "outcome": "needs_revision", "tokens_in": 120794, "tokens_out": 56042, "age": "4h"},
        {"uuid": "2ef638ac", "agent": "surveyor", "trigger": "pulse", "status": "idle",
         "outcome": "satisfied", "tokens_in": 47497, "tokens_out": 9292, "age": "4h"},
    ],
}


def build_rows(data):
    # Running first: a session in progress is the row an operator acts on.
    # The reader's human CLI is prose; the pane is the JSON table.
    return list(data.get("running") or []) + list(data.get("recent") or [])
