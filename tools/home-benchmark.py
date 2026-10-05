#!/usr/bin/env python3
"""Score how at home a model is in the estate, from ONE context file — code is the judge.

Roadmap row `home-benchmark`. The question set (state/home-benchmark.yml) holds
templates only; every answer key is DERIVED at run time from the estate's own
sources (anatomy graph, manifest, task types, routing graph, agent.yml files,
tools/README.md, doctrine titles), so the key moves when the estate does.

    questions   print the set and its derived key (offline)
    ask         give a model the context file + the questions, write raw answers
    score       compare a saved answers file to the key — calls no model

Scoring is per question: the exact identifiers found in the answer, restricted
to that family's universe of names, against the key — F1 of the two sets.
Listing every name costs precision; prose costs nothing and earns nothing. No
model judges. A backend that is unreachable, errors, or replies without
`Qnn:` lines is UNAVAILABLE, never a number. The context's size is recorded
beside the score: the target is a better score at a SMALLER context.

`ask` is the only live path, and only the operator starts it: a resident local
model starves other services on this host (memory: local-model-budget).

Usage:
    tools/home-benchmark.py questions [--json]
    tools/home-benchmark.py ask --context CLAUDE.md --model ollama:hermes3:8b --out answers.json
    tools/home-benchmark.py score answers.json [--json]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SET = REPO / "state/home-benchmark.yml"
TOKEN = re.compile(r"[A-Za-z0-9_.:/#@+-]+")
QLINE = re.compile(r"^\W*(Q\d+)\W*?[:.)\-]\s*(.*)$", re.I)


# ── derivations: root -> (universe, [(fill, key)]) ─────────────────────────────

def _graph(root: Path) -> dict:
    return json.loads((root / "state/anatomy-graph.json").read_text(encoding="utf-8"))


def readers(root: Path):
    text = (root / "tools/README.md").read_text(encoding="utf-8")
    section = text.split("## Readers", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^- `([^`]+)` — (.+)$", section, re.M)
    items = []
    for name, desc in rows:
        if name.endswith("-status.py"):
            desc = re.sub(rf"^(READER: |{re.escape(Path(name).stem)}\s+—\s+)", "", desc)
            items.append(({"description": desc.strip()}, {name}))
    return {n for n, _ in rows}, items


def _agents(root: Path) -> list[dict]:
    return [yaml.safe_load(Path(f).read_text(encoding="utf-8"))
            for f in sorted(glob.glob(str(root / "files/anatomy/agents/*/agent.yml")))]


def tool_holders(root: Path):
    holders: dict[str, set] = {}
    agents = _agents(root)
    for a in agents:
        for t in a.get("tools") or []:
            holders.setdefault(t["id"] if isinstance(t, dict) else t, set()).add(a["name"])
    return {a["name"] for a in agents}, [({"tool": t}, s) for t, s in sorted(holders.items())]


def service_deps(root: Path):
    g = _graph(root)
    deps: dict[str, set] = {}
    for e in g["edges"]:
        if e["kind"] == "data" and e["from"].startswith("service:") and e["to"].startswith("service:"):
            deps.setdefault(e["to"].split(":", 1)[1], set()).add(e["from"].split(":", 1)[1])
    universe = {k.split(":", 1)[1] for k, v in g["nodes"].items() if v["kind"] == "service"}
    return universe, [({"service": s}, d) for s, d in sorted(deps.items())]


def doctrine_files(root: Path):
    titles: dict[str, set] = {}
    for d in ("ssot/doctrine", "docs/doctrine"):
        for f in sorted((root / d).glob("*.md")):
            m = re.search(r"^# (.+)$", f.read_text(encoding="utf-8"), re.M)
            if m and f.name != "README.md":
                # The subtitle names the TOPIC; the title alone would hand over the file name.
                title = m.group(1).split(" — ", 1)[-1].strip()
                titles.setdefault(title, set()).add(f"{d}/{f.name}")
    universe = set().union(*titles.values())
    return universe, [({"title": t}, p) for t, p in sorted(titles.items())]


def task_type_writes(root: Path):
    types = yaml.safe_load((root / "state/task-types.yml").read_text(encoding="utf-8"))["task_types"]
    by: dict[str, set] = {}
    for name, c in types.items():
        by.setdefault(str(c["writes"]), set()).add(name)
    return set(types), [({"writes": w}, s) for w, s in sorted(by.items())]


def agent_task_types(root: Path):
    r = json.loads((root / "state/routing-graph.json").read_text(encoding="utf-8"))
    can: dict[str, set] = {}
    for e in r["edges"]:
        if e["kind"] == "can-do":
            can.setdefault(e["source"].split(":", 1)[1], set()).add(e["target"].split(":", 1)[1])
    return set(r["task_types"]), [({"agent": a}, s) for a, s in sorted(can.items())]


def pulse_commands(root: Path):
    jobs = {k.split(":", 1)[1]: v.get("command_name") or ""
            for k, v in _graph(root)["nodes"].items() if v["kind"] == "pulse"}
    # A job named after its script spells the answer; only the others are asked.
    scripts = {j: c for j, c in jobs.items()
               if re.fullmatch(r"[\w.-]+\.(py|sh)", c) and Path(c).stem not in j}
    return set(scripts.values()), [({"job": j}, {c}) for j, c in sorted(scripts.items())]


def install_flags(root: Path):
    rows = yaml.safe_load((root / "state/manifest.yml").read_text(encoding="utf-8"))["services"]
    universe = {s["install_flag"] for s in rows}
    # A flag spelled install_<id> is guessable without any context, so it is not asked.
    return universe, [({"service": s["id"]}, {s["install_flag"]}) for s in rows
                      if s["install_flag"] != f"install_{s['id']}"]


DERIVE = {f.__name__: f for f in (readers, tool_holders, service_deps, doctrine_files,
                                   task_type_writes, agent_task_types, pulse_commands, install_flags)}


# ── the set ───────────────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(set_path: Path = SET, root: Path = REPO) -> dict:
    """Questions + keys, regenerated from the sources. Same sources, same set."""
    spec = yaml.safe_load(set_path.read_text(encoding="utf-8"))
    questions, universes = [], {}
    for fam in spec["families"]:
        universe, items = DERIVE[fam["derive"]](root)
        universes[fam["id"]] = sorted(universe)
        # A question that spells its own answer measures reading, not knowing.
        items = [(fill, key) for fill, key in items if key and not
                 (hits(fam["template"].format(**fill), key))]
        rng = random.Random(f"{spec['seed']}:{fam['id']}")
        for n, (fill, key) in enumerate(rng.sample(items, min(fam["count"], len(items))), 1):
            questions.append({"id": f"{fam['id']}.{n}", "family": fam["id"], "class": fam["class"],
                              "text": fam["template"].format(**fill), "key": sorted(key)})
    return {"set": str(set_path.relative_to(root)) if set_path.is_relative_to(root) else str(set_path),
            "set_sha256": _sha(set_path), "system": spec["system"],
            "questions": questions, "universes": universes}


# ── scoring: exact identifiers, outside any model ────────────────────────────

def _forms(tok: str) -> set[str]:
    tok = tok.strip(".,;:`'\"()[]").lower()
    out = {tok, tok.split("#")[0]}
    return out | {t.rsplit(":", 1)[1] for t in out if ":" in t}


def hits(answer: str, universe) -> set[str]:
    """Universe names the answer spells; a path counts for the name it ends in."""
    names = {u.lower(): u for u in universe}
    found = set()
    for tok in TOKEN.findall(answer or ""):
        for f in _forms(tok):
            found |= {orig for low, orig in names.items() if f == low or f.endswith("/" + low)}
    return found


def f1(found: set, key: set) -> float:
    tp = len(found & key)
    return 0.0 if not tp else 2 * tp / (len(found) + len(key))


def score(answers: dict, bench: dict | None = None) -> dict:
    """Score a saved answers record. Never calls a model; UNAVAILABLE stays UNAVAILABLE."""
    if answers.get("status") != "ok":
        return {"status": "UNAVAILABLE", "why": answers.get("why", "no answers recorded")}
    bench = bench or build()
    asked = {q["id"]: q["text"] for q in answers.get("questions", [])}
    stale = [q["id"] for q in bench["questions"] if asked.get(q["id"]) != q["text"]]
    if stale:
        return {"status": "STALE", "why": f"{len(stale)} question(s) changed since the run "
                f"(e.g. {stale[0]}) — re-run ask"}
    rows = []
    for q in bench["questions"]:
        found = hits(answers["answers"].get(q["id"], ""), bench["universes"][q["family"]])
        rows.append({"id": q["id"], "family": q["family"], "score": round(f1(found, set(q["key"])), 3),
                     "found": sorted(found), "key": q["key"]})
    fams = sorted({r["family"] for r in rows})
    per = {f: round(sum(r["score"] for r in rows if r["family"] == f)
                    / sum(1 for r in rows if r["family"] == f), 3) for f in fams}
    return {"status": "ok", "score": round(sum(r["score"] for r in rows) / len(rows), 3),
            "families": per, "questions": rows, "model": answers.get("model"),
            "context": answers.get("context")}


# ── asking: the one live path ─────────────────────────────────────────────────

def _ollama_call(name: str, system: str, prompt: str, num_ctx: int) -> dict:
    """Reuse local-model-bench's client; refuse unless the ollama row is local."""
    rows = yaml.safe_load((REPO / "state/llm-backends.yml").read_text(encoding="utf-8"))["backends"]
    if not (rows.get("ollama") or {}).get("local"):
        raise RuntimeError("state/llm-backends.yml has no local ollama row")
    spec = importlib.util.spec_from_file_location("local_model_bench", REPO / "tools/local-model-bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.generate(name, system, prompt, timeout=600, num_ctx=num_ctx, keep_alive=0)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out


BACKENDS = {"ollama": _ollama_call}


def ask(bench: dict, context: Path, model: str, call=None) -> dict:
    text = context.read_text(encoding="utf-8")
    qids = {f"Q{n:02d}": q["id"] for n, q in enumerate(bench["questions"], 1)}
    prompt = (f"<context>\n{text}\n</context>\n\nQuestions:\n"
              + "\n".join(f"{n}: {q['text']}" for n, q in zip(qids, bench["questions"])))
    tokens_est = len(text) // 4  # ponytail: chars/4, no tokenizer offline; prompt_tokens is measured
    num_ctx = max(8192, 1 << (len(prompt) // 3 + 2048).bit_length())
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model,
              "set": bench["set"], "set_sha256": bench["set_sha256"],
              "context": {"path": str(context), "sha256": _sha(context), "bytes": len(text.encode()),
                          "tokens_est": tokens_est},
              "questions": [{"id": q["id"], "text": q["text"]} for q in bench["questions"]]}
    backend, _, name = model.partition(":")
    try:
        call = call or BACKENDS.get(backend)
        if call is None:
            raise RuntimeError(f"no adapter for backend '{backend}' (have: {', '.join(BACKENDS)})")
        out = call(name, bench["system"], prompt, num_ctx)
        answers = {}
        for line in (out.get("text") or "").splitlines():
            m = QLINE.match(line.strip())
            if m and m.group(1).upper() in qids:
                answers[qids[m.group(1).upper()]] = m.group(2).strip()
        if not answers:
            raise ValueError("reply carried no Qnn: lines — a format failure, not a score")
    except Exception as exc:  # noqa: BLE001 — every failure is the same answer: no score
        return {**record, "status": "UNAVAILABLE", "why": f"{type(exc).__name__}: {exc}"[:200]}
    return {**record, "status": "ok", "answers": answers, "raw": out.get("text", ""),
            "prompt_tokens": out.get("tokens"), "num_ctx": num_ctx}


# ── CLI ───────────────────────────────────────────────────────────────────────

def _render(res: dict) -> str:
    if res["status"] != "ok":
        return f"home-benchmark: {res['status']} — {res['why']}"
    ctx = res.get("context") or {}
    out = [f"home-benchmark  model {res['model']}  context {ctx.get('path')} "
           f"(~{ctx.get('tokens_est')} tokens est, {ctx.get('bytes')} bytes)",
           f"score {res['score']:.3f} over {len(res['questions'])} questions"]
    out += [f"  {f:18} {s:.3f}" for f, s in res["families"].items()]
    out += [f"  {r['id']:20} {r['score']:.2f}  found={','.join(r['found']) or '-'}  key={','.join(r['key'])}"
            for r in res["questions"] if r["score"] < 1]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", default=str(SET), help="question set (default: the home set)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("questions")
    q.add_argument("--json", action="store_true")
    a = sub.add_parser("ask")
    a.add_argument("--context", required=True, help="the ONE file the model may see")
    a.add_argument("--model", required=True, help="<backend>:<model>, e.g. ollama:hermes3:8b")
    a.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("answers")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    bench = build(Path(args.set).resolve())

    if args.cmd == "questions":
        if args.json:
            print(json.dumps(bench, indent=2))
        else:
            for q in bench["questions"]:
                print(f"{q['id']:20} {q['text']}\n{'':20} key: {', '.join(q['key'])}")
            print(f"{len(bench['questions'])} questions, set sha256 {bench['set_sha256'][:12]}")
        return 0
    if args.cmd == "ask":
        rec = ask(bench, Path(args.context), args.model)
        Path(args.out).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        print(f"home-benchmark ask: {rec['status']}"
              + (f" — {rec['why']}" if rec["status"] != "ok" else f", {len(rec['answers'])} answers")
              + f" → {args.out}")
        return 0 if rec["status"] == "ok" else 2
    res = score(json.loads(Path(args.answers).read_text(encoding="utf-8")), bench)
    print(json.dumps(res, indent=2) if args.json else _render(res))
    return 0 if res["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
