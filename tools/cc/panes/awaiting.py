"""tools/awaiting-operator.py — what cannot proceed without a human.

Variant C's subject, which is the one screen an operator opens to DO something
rather than to know something. It stays a reader: signing, answering and
landing are separate deliberate acts.
"""
ID, LABEL, TITLE = "awaiting", "Awaiting you", "what cannot proceed without you"
READER = "tools/awaiting-operator.py"
REFRESH = 45
COLUMNS = ["kind", "severity", "age", "what", "where"]
DEMO = {"items": [{"kind": "signature", "severity": "high", "age": "-",
                   "what": "the apex ruling was AMENDED after it was signed",
                   "where": "files/anatomy/apex/ruling.yml",
                   "note": "read the change and re-sign, or revert it"}],
        "unknown": []}


def build_rows(data):
    return data.get("items", [])


def detail(row, data):
    out = dict(row)
    out["act"] = {
        "signature": "tools/apex-sign.py  (then --confirm)",
        "question": "answer in Wing /inbox",
        "proposal": "nos-loop history; landing is deliberate",
        "inbox": "Wing /inbox",
    }.get(row.get("kind"), "—")
    return out


def meta(data):
    return {"unknown_sources": data.get("unknown", [])}
