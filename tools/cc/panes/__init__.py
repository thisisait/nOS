"""The pane registry — discovered, not typed twice.

Every module in this directory that declares an `ID` is a pane. The palette,
the tmux launcher and `--dump` all read THIS list, so adding a pane is adding
one file; there is no second place to register it and therefore no second place
to forget.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

ORDER = ["red", "awaiting", "agents", "timeline", "loop", "rem", "roadmap"]


def all_panes() -> dict[str, ModuleType]:
    found: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules([str(Path(__file__).parent)]):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "ID"):
            found[mod.ID] = mod
    # ORDER is the operator's reading order (what is wrong, then what needs
    # you, then what happened); anything not listed sorts after it, so a new
    # pane appears rather than vanishing.
    rank = {pid: i for i, pid in enumerate(ORDER)}
    return dict(sorted(found.items(), key=lambda kv: (rank.get(kv[0], 99), kv[0])))


def get(pane_id: str) -> ModuleType:
    panes = all_panes()
    if pane_id not in panes:
        raise KeyError(f"no pane {pane_id!r}; have: {', '.join(panes)}")
    return panes[pane_id]
