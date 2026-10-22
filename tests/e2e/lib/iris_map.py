"""An ephemeral e2e tester in the thalamus identity map, for the length of one run.

The thalamus speaks only with a person ~/.nos/identity-map.yml names (serve.rs reads the file on
every connection), and the map is rendered by pazny.receptor from the roster. A browser journey
through the face's Iris logs in as an ephemeral `nos-tester-e2e-*` user, so the run adds that one
login (the operator's ruling 2026-10-22) and its teardown removes it; the next converge re-renders
the map from the roster anyway. Only tester names are ever touched.

    add(username, group)   remove(username)   sweep()   (path overridable: NOS_IDENTITY_MAP)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PREFIX = "nos-tester-e2e-"


def _path() -> Path:
    return Path(os.environ.get("NOS_IDENTITY_MAP") or Path.home() / ".nos" / "identity-map.yml")


def _edit(change) -> bool:
    """Read the map (JSON, which is YAML), apply `change` to its logins, write it back atomically
    with the same mode. False when the map is absent: no thalamus on this host, nothing to do."""
    p = _path()
    if not p.is_file():
        return False
    doc = json.loads(p.read_text(encoding="utf-8"))
    logins = doc.setdefault("logins", {})
    if not change(logins):
        return True
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".identity-map.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=4, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, p.stat().st_mode & 0o777)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def _tester(username: str) -> str:
    if not username.startswith(PREFIX):
        raise ValueError(f"{username!r} is not an e2e tester; the roster owns every other login")
    return username


def add(username: str, group: str) -> bool:
    _tester(username)
    return _edit(lambda logins: logins.update({username: {"username": username, "groups": [group]}}) or True)


def remove(username: str) -> bool:
    _tester(username)
    return _edit(lambda logins: logins.pop(username, None) is not None)


def sweep() -> bool:
    """Every tester login left behind by a run that never tore down."""
    def drop(logins: dict) -> bool:
        gone = [k for k in logins if k.startswith(PREFIX)]
        for k in gone:
            del logins[k]
        return bool(gone)
    return _edit(drop)
