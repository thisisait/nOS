#!/usr/bin/env python3
"""One control-centre pane. `nos-cc.sh` runs several; you can run one anywhere.

    tools/nos-pane.py                 # the default pane (red), TUI
    tools/nos-pane.py awaiting        # a named pane
    tools/nos-pane.py --list          # every pane the registry found
    tools/nos-pane.py rem --dump text # what tmux capture-pane would give an LLM
    tools/nos-pane.py red --dump json # the same rows, before layout
    tools/nos-pane.py --demo          # fixtures; no estate needed

Ctrl+P inside the TUI switches which pane this is. Read-only, always: nothing
here signs, lands, answers or converges.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cc import contract  # noqa: E402
from cc import panes as registry  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pane", nargs="?", default="red")
    ap.add_argument("--list", action="store_true", help="pane ids and labels")
    ap.add_argument("--demo", action="store_true", help="fixtures, no estate")
    ap.add_argument("--dump", choices=["text", "json"], help="print, no TUI")
    args = ap.parse_args()

    found = registry.all_panes()
    if args.list:
        for pid, mod in found.items():
            print(f"{pid:<10} {mod.LABEL:<14} {mod.TITLE}")
        return 0
    if args.pane not in found:
        print(f"no pane {args.pane!r}; have: {', '.join(found)}", file=sys.stderr)
        return 2

    pane = found[args.pane]
    if args.dump:
        t = contract.table(pane, args.demo)
        if args.dump == "json":
            json.dump({k: v for k, v in t.items() if k != "detail"},
                      sys.stdout, indent=2, sort_keys=True, default=str)
            sys.stdout.write("\n")
        else:
            print(contract.render_text(t, pane.TITLE))
        # Exit 0 even on UNKNOWN: reporting IS the job, same as every reader in
        # this directory. A pane that exited nonzero would make a tmux pane
        # holding it look like a crashed command.
        return 0

    from cc.app import ControlCentreApp

    ControlCentreApp(args.pane, args.demo).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
