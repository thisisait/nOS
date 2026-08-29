"""tools/agent-status.py — one row per agent session."""
ID, LABEL, TITLE = "agents", "Agents", "what the agents did, and how the runs ended"
READER = "tools/agent-status.py"
REFRESH = 20
COLUMNS = ["uuid", "agent", "trigger", "status", "outcome", "tokens_in", "tokens_out", "age"]
DEMO = {"recent": [
    {"uuid": "be9d107f", "agent": "librarian", "trigger": "pulse", "status": "idle",
     "outcome": "needs_revision", "tokens_in": 120794, "tokens_out": 56042, "age": "4h"},
    {"uuid": "2ef638ac", "agent": "surveyor", "trigger": "pulse", "status": "idle",
     "outcome": "satisfied", "tokens_in": 47497, "tokens_out": 9292, "age": "4h"},
]}


def build_rows(data):
    return data.get("recent", [])
