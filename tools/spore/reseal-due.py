#!/usr/bin/env python3
"""Exit 0 when the spore is due a re-seal, 1 when not, 2 when a record is unreadable.

Due = the newest blank (~/.nos/blank-runs.jsonl `started`) is later than the last seal
(~/.nos/spore-seals.log, appended by nos-spore.sh): that blank re-minted the secret master and
the sealed spore no longer opens the estate. Backup age is not part of it (it made the condition
flap daily); nos-spore.sh itself refuses a backup over 6 h old. `--done`: sealed since that blank.
"""
import json
import pathlib
import sys

NOS = pathlib.Path.home() / ".nos"


def lines(path: pathlib.Path) -> list[str]:
    return [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


try:
    blank = max((json.loads(x)["started"] for x in lines(NOS / "blank-runs.jsonl")), default="")
    sealed = max(lines(NOS / "spore-seals.log"), default="").strip()  # same %Y-%m-%dT%H:%M:%SZ form
except (OSError, ValueError, KeyError, TypeError) as exc:
    print(f"UNKNOWN: {type(exc).__name__}: {exc}")
    sys.exit(2)
print(f"blank={blank or 'none'} sealed={sealed or 'never'}")
if "--done" in sys.argv:
    sys.exit(0 if blank and sealed > blank else 1)
sys.exit(0 if blank > sealed else 1)
