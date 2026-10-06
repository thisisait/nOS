#!/usr/bin/env python3
"""Merge the keys nOS declares (TOML on stdin) into an existing TOML file.

Declared keys win; every other key in the file is kept. Prints `changed` or
`unchanged`, writes only on change. Comments in the old file are not kept
(OpenHuman rewrites the file itself on migration anyway). Stdlib only.
Usage: toml_merge.py <path> < declared.toml      toml_merge.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
import tomllib


def merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() else json.dumps(k)


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_val(x)}" for k, x in v.items()) + " }"
    return json.dumps(str(v))  # ponytail: dates/times become strings; add when a config carries one


def dump(d: dict, prefix: str = "") -> str:
    scalars = {k: v for k, v in d.items() if not isinstance(v, dict)
               and not (isinstance(v, list) and v and all(isinstance(x, dict) for x in v))}
    lines = [f"{_key(k)} = {_val(v)}" for k, v in scalars.items()]
    for k, v in d.items():
        name = f"{prefix}.{_key(k)}" if prefix else _key(k)
        if isinstance(v, dict):
            lines += ["", f"[{name}]", dump(v, name).strip("\n")]
        elif k not in scalars:  # array of tables
            for item in v:
                lines += ["", f"[[{name}]]", dump(item, name).strip("\n")]
    return "\n".join(x for i, x in enumerate(lines) if x or i) + "\n"


def main(path: str) -> int:
    p = pathlib.Path(path)
    old = tomllib.loads(p.read_text()) if p.is_file() else {}
    new = merge(old, tomllib.loads(sys.stdin.read()))
    if p.is_file() and tomllib.loads(p.read_text()) == new:
        print("unchanged")
        return 0
    text = dump(new)
    assert tomllib.loads(text) == new, "writer round-trip failed"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    print("changed")
    return 0


def selftest() -> None:
    old = {"schema_version": 3, "a": {"keep": 1, "x": "old"}, "srv": [{"name": "s", "env": {"K": "v"}}],
           "weird key": [1, 2], "z": {"y": {"w": True}}}
    new = merge(old, {"a": {"x": "new"}, "b": {"c": False}})
    assert new["a"] == {"keep": 1, "x": "new"} and new["schema_version"] == 3 and new["b"] == {"c": False}
    assert tomllib.loads(dump(new)) == new, dump(new)
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        sys.exit(0)
    sys.exit(main(sys.argv[1]))
