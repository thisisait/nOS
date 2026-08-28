#!/usr/bin/env python3
"""Draw a workflow definition as a tree, with live progress if a run is going.

WHY. A workflow script is 600 lines of prompts and the thing an operator needs
from it is twenty: which phases, which agents, on which model, and — while it
runs — which of them have finished. Reading that out of the file means leaving
the terminal, and `/workflows` shows progress without showing the DEFINITION, so
neither surface answers "what is about to happen".

WHAT IT READS. The script text (the artifact, not a description of it) and, when
a run exists, that run's `journal.jsonl`. Progress is derived from the journal's
`started`/`result` lines — it is never inferred from elapsed time, and an agent
with a `started` and no `result` renders as RUNNING, not as done.

WHAT IT CANNOT SEE. Whether the phases will run in the order printed: `args.only`
and any `wants()`-style gate live in the script's control flow, not its text.
A phase shown here is a phase the script CAN run, not one it WILL.

Usage:
    tools/workflow-tree.py <script.js>   # definition + the newest run's progress
    tools/workflow-tree.py --latest      # the most recently edited script
    tools/workflow-tree.py --no-color
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PROJECTS = pathlib.Path.home() / ".claude" / "projects"
GLOBS = ("docs/plans/**/*workflow*.js", ".claude/workflows/*.js")

DESC_CHARS = 200
PROMPT_CHARS = 50


class C:
    """Colours, off in one place when stdout is not a terminal."""
    on = True

    @classmethod
    def _w(cls, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if cls.on else s

    dim = classmethod(lambda c, s: c._w("2", s))
    bold = classmethod(lambda c, s: c._w("1", s))
    red = classmethod(lambda c, s: c._w("31", s))
    green = classmethod(lambda c, s: c._w("32", s))
    yellow = classmethod(lambda c, s: c._w("33", s))
    blue = classmethod(lambda c, s: c._w("34", s))
    cyan = classmethod(lambda c, s: c._w("36", s))


def strip_comments(src: str) -> str:
    """Blank comments, keep offsets — so a comment about agent() is not read as one."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(c if c == "\n" else " " for c in src[i:j])); i = j
        else:
            out.append(src[i]); i += 1
    return "".join(out)


def blank_literals(src: str) -> str:
    """Comments AND string bodies blanked in ONE pass, offsets preserved.

    One pass, not two, because the order matters and getting it wrong is silent:
    blanking comments first makes `http://127.0.0.1` inside a prompt look like a
    comment, which eats the rest of that line — including the backtick that ends
    the template — and every call after it disappears. Measured: five of twenty
    agent call sites vanished that way, and the tree rendered a workflow with
    three phases that had no agents.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "'\"`":
            j = i + 1
            while j < n and src[j] != ch:
                j += 2 if src[j] == "\\" else 1
            j = min(j, n - 1)
            out.append(ch)
            out.append("".join(c if c == "\n" else " " for c in src[i + 1:j]))
            out.append(src[j] if j > i else "")
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(c if c == "\n" else " " for c in src[i:j])); i = j
        else:
            out.append(ch); i += 1
    return "".join(out)


def meta_of(src: str) -> dict:
    m = re.search(r"export\s+const\s+meta\s*=\s*\{", src)
    if not m:
        return {}
    depth, i = 0, m.end() - 1
    while i < len(src):
        depth += (src[i] == "{") - (src[i] == "}")
        if depth == 0:
            break
        i += 1
    block = src[m.start():i + 1]
    name = re.search(r"name:\s*'([^']*)'", block)
    desc = re.search(r"description:\s*'((?:[^'\\]|\\.)*)'", block)
    phases = [
        {"title": t, "detail": d}
        for t, d in re.findall(r"title:\s*'([^']*)'(?:\s*,\s*detail:\s*'((?:[^'\\]|\\.)*)')?", block)
    ]
    return {
        "name": name.group(1) if name else "(unnamed)",
        "description": (desc.group(1) if desc else "").replace("\\'", "'"),
        "phases": phases,
    }


def agents_of(src: str) -> list[dict]:
    """Every agent call, in source order, with its opts and prompt opening.

    Matches the CALL, then walks forward to its closing paren so the opts object
    is read from the same expression rather than from the next one along.
    """
    code = blank_literals(src)
    out = []
    for m in re.finditer(r"\b(?:A|agent)\s*\(", code):
        depth, i = 0, m.end() - 1
        while i < len(code):
            depth += (code[i] == "(") - (code[i] == ")")
            if depth == 0:
                break
            i += 1
        call = src[m.end():i]
        label = re.search(r"label:\s*'([^']*)'", call)
        phase = re.search(r"phase:\s*'([^']*)'", call)
        model = re.search(r"model:\s*'([^']*)'", call)
        effort = re.search(r"effort:\s*'([^']*)'", call)
        schema = "schema:" in call
        # The prompt is the first argument: skip a leading ${RULES}-style splice
        # and any blank lines, then take the first real words.
        body = call.lstrip()
        body = re.sub(r"^`\s*", "", body)
        body = re.sub(r"^\$\{[A-Za-z_]\w*\}\s*", "", body)
        opening = " ".join(body.split())[:PROMPT_CHARS]
        # A forwarding call — `agent(prompt, opts)` inside a wrapper — is not a
        # ceremony. Its first argument is a bare identifier, never a prompt.
        if re.match(r"^[a-z_]\w*\s*,", opening):
            continue
        out.append({
            "label": label.group(1) if label else "(unlabelled)",
            "phase": phase.group(1) if phase else None,
            "model": model.group(1) if model else None,
            "effort": effort.group(1) if effort else None,
            "schema": schema,
            "opening": opening,
        })
    return out


def newest_run(name: str) -> pathlib.Path | None:
    """The most recently touched journal for a workflow of this name."""
    best = None
    for j in PROJECTS.glob("*/subagents/workflows/*/journal.jsonl"):
        if best is None or j.stat().st_mtime > best.stat().st_mtime:
            best = j
    return best


def progress(journal: pathlib.Path | None) -> dict[str, str]:
    """label -> done | running. Absent from the map means it has not started."""
    if not journal or not journal.is_file():
        return {}
    state: dict[str, str] = {}
    ids: dict[str, str] = {}
    for line in journal.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = d.get("label") or ids.get(d.get("agentId", "")) or d.get("agentId")
        if not key:
            continue
        if d.get("label") and d.get("agentId"):
            ids[d["agentId"]] = d["label"]
        if d.get("type") == "started":
            state.setdefault(key, "running")
        elif d.get("type") == "result":
            state[key] = "done"
    return state


MARK = {"done": ("✔", C.green), "running": ("●", C.yellow)}


def render(path: pathlib.Path, journal: pathlib.Path | None) -> str:
    src = path.read_text(encoding="utf-8")
    meta = meta_of(src)
    agents = agents_of(src)
    done = progress(journal)
    by_phase: dict[str, list[dict]] = {}
    for a in agents:
        by_phase.setdefault(a["phase"] or "(no phase)", []).append(a)

    L = []
    rel = path.relative_to(REPO) if path.is_relative_to(REPO) else path
    L.append(C.bold(str(rel)))
    L.append(C.cyan(meta.get("name", "?")))
    desc = meta.get("description", "")
    if desc:
        L.append(C.dim(desc[:DESC_CHARS] + ("…" if len(desc) > DESC_CHARS else "")))
    n_done = sum(1 for v in done.values() if v == "done")
    if done:
        L.append(C.dim(f"run: {n_done}/{len(agents)} agents done"
                       f"{'  (' + journal.parent.name + ')' if journal else ''}"))
    else:
        L.append(C.dim(f"{len(agents)} agents, {len(meta.get('phases', []))} phases — no run yet"))
    L.append("")

    titles = [p["title"] for p in meta.get("phases", [])]
    for t in titles + [k for k in by_phase if k not in titles]:
        rows = by_phase.get(t, [])
        states = [done.get(r["label"]) for r in rows]
        if rows and all(s == "done" for s in states):
            head = C.green(f"▸ {t}")
        elif any(s for s in states):
            head = C.yellow(f"▸ {t}")
        elif not rows:
            head = C.dim(f"▸ {t}  (no agent declares this phase)")
        else:
            head = f"▸ {t}"
        L.append(head)
        for i, a in enumerate(rows):
            last = i == len(rows) - 1
            stem = "  └─ " if last else "  ├─ "
            mark, col = MARK.get(done.get(a["label"], ""), (" ", lambda s: s))
            bits = [b for b in (a["model"], a["effort"], "schema" if a["schema"] else None) if b]
            tag = C.blue(" [" + " ".join(bits) + "]") if bits else ""
            L.append(f"{stem}{col(mark)} {a['label']}{tag}")
            L.append(("     " if last else "  │  ") + C.dim(a["opening"]))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("script", nargs="?", type=pathlib.Path)
    ap.add_argument("--latest", action="store_true", help="the most recently edited script")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    C.on = sys.stdout.isatty() and not args.no_color and os.environ.get("NO_COLOR") is None

    path = args.script
    if path is None or args.latest:
        found = [p for g in GLOBS for p in REPO.glob(g)]
        if not found:
            print("no workflow script found — nothing to draw, which is not an empty workflow")
            return 1
        path = max(found, key=lambda p: p.stat().st_mtime)
    if not path.is_file():
        print(f"no such script: {path}")
        return 1

    meta = meta_of(path.read_text(encoding="utf-8"))
    print(render(path, newest_run(meta.get("name", ""))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
