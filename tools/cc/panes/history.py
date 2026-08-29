"""`git log` — the reader that answers "what did we just do to ourselves".

Not a `tools/*.py --json` reader, so it fetches its own. One row per commit:
the pane that used to tail a decorated log wrapped every long subject onto two
lines and scrolled the NEWEST commits off the top, which is the scrollback lie
in its purest form.
"""
import subprocess
from pathlib import Path

ID, LABEL, TITLE = "history", "History", "recent commits"
REFRESH = 60
COLUMNS = ["sha", "age", "who", "subject"]
REPO = Path(__file__).resolve().parents[3]
SEP = "\x1f"
DEMO = {"rows": [{"sha": "b68ac24", "age": "2 hours ago", "who": "Pázny",
                  "subject": "fix(wing): send Bone a Bearer"}]}


def fetch():
    try:
        out = subprocess.run(
            ["git", "log", "-25", f"--pretty=%h{SEP}%ar{SEP}%an{SEP}%s"],
            capture_output=True, text=True, timeout=15, cwd=REPO)
    except Exception as e:  # noqa: BLE001
        return None, f"git log failed: {e}"
    if out.returncode != 0:
        return None, f"git log exited {out.returncode}: {out.stderr.strip()[:120]}"
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split(SEP)
        if len(parts) == 4:
            rows.append(dict(zip(COLUMNS, parts)))
    return {"rows": rows}, None


def build_rows(data):
    return data.get("rows", [])
