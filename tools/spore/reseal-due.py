#!/usr/bin/env python3
"""Exit 0 when the spore is due a re-seal, 1 when not, 2 when a record is unreadable.

Due = the newest blank (~/.nos/blank-runs.jsonl `started`) is later than the last seal
(~/.nos/spore-seals.log, appended by nos-spore.sh): that blank re-minted the secret master and
the sealed spore no longer opens the estate. And the backup is fresh enough to seal on
(backup-fresh.py < 6 h, the bar nos-spore.sh refuses below). `--done`: sealed since that blank.
"""
import json
import pathlib
import subprocess
import sys

NOS = pathlib.Path.home() / ".nos"


def lines(path: pathlib.Path) -> list[str]:
    return [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


try:
    blank = max((json.loads(x)["started"] for x in lines(NOS / "blank-runs.jsonl")), default="")
    sealed = max(lines(NOS / "spore-seals.log"), default="").strip()  # same %Y-%m-%dT%H:%M:%SZ form
    if "--done" in sys.argv:
        sys.exit(0 if blank and sealed > blank else 1)
    hours = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("backup-fresh.py"))],
                           capture_output=True, text=True, check=True, timeout=60).stdout.strip()
except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
    print(f"UNKNOWN: {type(exc).__name__}: {exc}")
    sys.exit(2)
fresh = hours.isdigit() and int(hours) < 6
print(f"blank={blank or 'none'} sealed={sealed or 'never'} backup={hours} h")
sys.exit(0 if fresh and blank > sealed else 1)
