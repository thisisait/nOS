#!/usr/bin/env python3
"""Apgar: score a newborn model on its first page in the estate — code is the judge.

Like the newborn score, it is taken in the first minutes: the model (the
NEWBORN) sees ONE file (the IMPRINT, the first page a newborn model reads) and
nothing else. Roadmap row `apgar`. The question set (state/apgar.yml) holds
templates only; every answer key is DERIVED at run time from the estate's own
sources (anatomy graph, manifest, task types, routing graph, agent.yml files,
tools/README.md, doctrine titles), so the key moves when the estate does.

    questions   print the set and its derived key (offline)
    ask         give the newborn the imprint (or none: the control) + the questions
    score       compare a saved answers file to the key — calls no model

A score means nothing alone: `ask --no-imprint` records the CONTROL (what the
newborn guesses with nothing to read) and `score --control` prints score,
control and lift per family. The lift is what the imprint bought.

Scoring is per question, on the `Qnn:` line only: comma-separated identifiers,
matched exactly against the family's names; a key slot may hold alternatives
(either copy of a duplicated doctrine). F1 over slots. Prose on the line is a
format failure, scored 0 — never scanned for words. No model judges.

Two failures, kept apart: UNAVAILABLE (the newborn could not be asked — no
number, exit 2) and a format failure (it answered without `Qnn:` lines — a
recorded low score, `ask` exits 1). The imprint's size is recorded beside the
score: the target is a better score from a SMALLER imprint.

`ask` is the only live path, and only the operator starts it: a resident local
model starves other services on this host (memory: local-model-budget).

Usage:
    tools/apgar.py questions [--json]
    tools/apgar.py ask --imprint CLAUDE.md --model ollama:hermes3:8b --out newborn.json
    tools/apgar.py ask --no-imprint --model ollama:hermes3:8b --out control.json
    tools/apgar.py score newborn.json --control control.json [--json]
"""
from __future__ import annotations

import argparse
import collections
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
SET = REPO / "state/apgar.yml"
TOKEN = re.compile(r"[A-Za-z0-9_.:/#@+-]+")
QLINE = re.compile(r"^\W*(Q\d+)\W*?[:.)\-]\s*(.*)$", re.I)
NO_ANSWER = {"", "unknown", "none", "-", "n/a"}
REPEAT = 2  # at most this many questions whose every key slot was already asked


# ── derivations: root -> (universe, [(fill, key)]) ─────────────────────────────
# A key is a set of names; a frozenset inside it is ONE slot with alternatives.
# Kinds are read with .get: the graph gains kinds, and a new one is not an error.

def _graph(root: Path) -> dict:
    return json.loads((root / "state/anatomy-graph.json").read_text(encoding="utf-8"))


def _of(node_id: str, kind: str) -> str | None:
    return node_id.split(":", 1)[1] if node_id.startswith(kind + ":") else None


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
        src, dst = _of(e.get("from", ""), "service"), _of(e.get("to", ""), "service")
        if e.get("kind") == "data" and src and dst:
            deps.setdefault(dst, set()).add(src)
    universe = {_of(k, "service") for k, v in g["nodes"].items() if v.get("kind") == "service"}
    return universe - {None}, [({"service": s}, d) for s, d in sorted(deps.items())]


def doctrine_files(root: Path):
    """Articles in ssot/doctrine plus the warehouse originals INDEX `proposed:`
    names. A promoted article has one home, so it is never expected in docs/."""
    proposed = yaml.safe_load((root / "ssot/INDEX.yml").read_text(encoding="utf-8")).get("proposed") or []
    files = sorted((root / "ssot/doctrine").glob("*.md")) + [root / p for p in proposed]
    titles: dict[str, set] = {}
    for f in files:
        m = re.search(r"^# (.+)$", f.read_text(encoding="utf-8"), re.M)
        if m:
            # The subtitle names the TOPIC; the title alone would hand over the file name.
            title = m.group(1).split(" — ", 1)[-1].strip()
            titles.setdefault(title, set()).add(f.relative_to(root).as_posix())
    universe = set().union(*titles.values())
    return universe, [({"title": t}, {frozenset(p)}) for t, p in sorted(titles.items())]


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
        if e.get("kind") == "can-do":
            can.setdefault(e["source"].split(":", 1)[1], set()).add(e["target"].split(":", 1)[1])
    return set(r["task_types"]), [({"agent": a}, s) for a, s in sorted(can.items())]


def pulse_commands(root: Path):
    jobs = {_of(k, "pulse"): v.get("command_name") or ""
            for k, v in _graph(root)["nodes"].items() if v.get("kind") == "pulse"}
    scripts = {j: c for j, c in jobs.items() if j and re.fullmatch(r"[\w.-]+\.(py|sh)", c)}
    return set(scripts.values()), [({"job": j}, {c}) for j, c in sorted(scripts.items())]


def install_flags(root: Path):
    rows = yaml.safe_load((root / "state/manifest.yml").read_text(encoding="utf-8"))["services"]
    return {s["install_flag"] for s in rows}, [({"service": s["id"]}, {s["install_flag"]}) for s in rows]


DERIVE = {f.__name__: f for f in (readers, tool_holders, service_deps, doctrine_files,
                                   task_type_writes, agent_task_types, pulse_commands, install_flags)}


# ── the set ───────────────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slots(key) -> list[list[str]]:
    return sorted(sorted([k]) if isinstance(k, str) else sorted(k) for k in key)


def _stems(text: str) -> set[str]:
    words = re.split(r"[^a-z0-9]+", re.sub(r"\.(py|sh|md|ya?ml)\b", "", text.lower()))
    return {w.rstrip("s")[:5] for w in words if len(w) >= 3}


def shared_stems(fill: dict, names, common) -> set[str]:
    """Word stems the question's wording shares with its key, beyond the family's
    common ones (`status` in every reader): code-fix for `writes: code`."""
    asked = set().union(*(_stems(str(v)) for v in fill.values()))
    return (set().union(*(_stems(n) for n in names)) - set(common)) & asked


def build(set_path: Path = SET, root: Path = REPO) -> dict:
    """Questions + keys, regenerated from the sources. Same sources, same set."""
    spec = yaml.safe_load(set_path.read_text(encoding="utf-8"))
    questions, universes, commons, spread = [], {}, {}, {}
    for fam in spec["families"]:
        universe, items = DERIVE[fam["derive"]](root)
        universes[fam["id"]] = sorted(universe)
        items = [(fill, _slots(key)) for fill, key in items if key]
        names = [{n for slot in key for n in slot} for _, key in items]
        stem_n = collections.Counter(s for ns in names for s in set().union(*map(_stems, ns)))
        common = sorted(s for s, c in stem_n.items() if c > len(items) / 2)
        commons[fam["id"]] = common
        # A question whose words give its key away measures reading, not knowing.
        items = [(fill, key) for (fill, key), ns in zip(items, names)
                 if not hits(fam["template"].format(**fill), ns) and not shared_stems(fill, ns, common)]
        # Rarest key first, and no slot repeated while another is unused: a sample
        # that is mostly one name is answered by guessing that name.
        rng = random.Random(f"{spec['seed']}:{fam['id']}")
        pool = list(items)
        rng.shuffle(pool)
        freq = collections.Counter(tuple(s) for _, key in pool for s in key)
        used: collections.Counter = collections.Counter()
        picked = []
        while pool and len(picked) < fam["count"]:
            best = min(pool, key=lambda it: (sum(used[tuple(s)] for s in it[1]),
                                             max(freq[tuple(s)] for s in it[1])))
            pool.remove(best)
            if all(used[tuple(s)] >= REPEAT for s in best[1]):
                continue  # nothing new in it: a third run-agent.sh question teaches nothing
            picked.append(best)
            used.update(tuple(s) for s in best[1])
        if picked:
            spread[fam["id"]] = {"pool": len(items), "asked": len(picked),
                                 "pool_top_share": round(freq.most_common(1)[0][1] / len(items), 3),
                                 "sample_top": used.most_common(1)[0][1]}
        for n, (fill, key) in enumerate(picked, 1):
            questions.append({"id": f"{fam['id']}.{n}", "family": fam["id"], "class": fam["class"],
                              "text": fam["template"].format(**fill), "fill": fill, "key": key})
    return {"set": str(set_path.relative_to(root)) if set_path.is_relative_to(root) else str(set_path),
            "set_sha256": _sha(set_path), "system": spec["system"], "questions": questions,
            "universes": universes, "common": commons, "spread": spread}


# ── scoring: exact identifiers on the Qnn line, outside any model ─────────────

def _forms(tok: str) -> set[str]:
    tok = tok.strip(".,;:`'\"()[]*").lower()
    out = {tok, tok.split("#")[0]}
    return out | {t.rsplit(":", 1)[1] for t in out if ":" in t}


def _match(item: str, names: dict) -> str | None:
    for f in _forms(item):
        for low, orig in names.items():
            if f == low or f.endswith("/" + low):
                return orig
    return None


def hits(text: str, universe) -> set[str]:
    """Names a free text spells anywhere — used to keep answers OUT of questions."""
    names = {u.lower(): u for u in universe}
    return {m for tok in TOKEN.findall(text or "") if (m := _match(tok, names))}


def identifiers(line: str | None) -> list[str] | None:
    """The comma-separated identifiers on a Qnn line; None when it is prose or absent."""
    if line is None:
        return None
    if line.strip().strip("`'\".*").lower() in NO_ANSWER:
        return []
    items = [p.strip().strip("`'\"*").rstrip(".").strip("`'\"") for p in re.split(r"[,;]", line)]
    items = [p for p in items if p]
    return None if any(re.search(r"\s", p) for p in items) else items


def grade(line: str | None, key: list[list[str]], universe) -> dict:
    items = identifiers(line)
    if items is None:
        return {"score": 0.0, "parsed": False, "found": []}
    names = {u.lower(): u for u in universe}
    hit_slots, wrong = set(), set()
    for it in items:
        name = _match(it, names)
        slot = next((i for i, s in enumerate(key) if name in s), None)
        if slot is None:
            wrong.add(name or it.lower())
        else:
            hit_slots.add(slot)
    tp = len(hit_slots)
    return {"score": round(2 * tp / (tp + len(wrong) + len(key)), 3) if tp else 0.0,
            "parsed": True, "found": sorted(wrong | {key[i][0] for i in hit_slots})}


def _score_one(answers: dict, bench: dict) -> dict:
    if answers.get("status") != "ok":
        return {"status": "UNAVAILABLE", "why": answers.get("why", "no answers recorded")}
    asked = {q["id"]: q["text"] for q in answers.get("questions", [])}
    stale = [q["id"] for q in bench["questions"] if asked.get(q["id"]) != q["text"]]
    if stale:
        return {"status": "STALE", "why": f"{len(stale)} question(s) changed since the run "
                f"(e.g. {stale[0]}) — re-run ask"}
    rows = [{"id": q["id"], "family": q["family"], "key": q["key"],
             **grade(answers["answers"].get(q["id"]), q["key"], bench["universes"][q["family"]])}
            for q in bench["questions"]]
    per = collections.defaultdict(list)
    for r in rows:
        per[r["family"]].append(r["score"])
    return {"status": "ok", "score": round(sum(r["score"] for r in rows) / len(rows), 3),
            "families": {f: round(sum(v) / len(v), 3) for f, v in sorted(per.items())},
            "unparsed": sum(1 for r in rows if not r["parsed"]), "questions": rows,
            "model": answers.get("model"), "imprint": answers.get("imprint")}


def score(answers: dict, bench: dict | None = None, control: dict | None = None) -> dict:
    """Score a saved answers record, and its lift over a no-imprint control. Never calls a model."""
    bench = bench or build()
    res = _score_one(answers, bench)
    if control is None or res["status"] != "ok":
        return res
    if not (control.get("imprint") or {}).get("control"):
        return {"status": "UNAVAILABLE", "why": "the control file is not an `ask --no-imprint` run", "run": res}
    ctl = _score_one(control, bench)
    if ctl["status"] != "ok":
        return {"status": ctl["status"], "why": f"control: {ctl['why']}", "run": res}
    lift = {f: round(s - ctl["families"][f], 3) for f, s in res["families"].items()}
    return {**res, "control": ctl, "lift": lift, "lift_total": round(res["score"] - ctl["score"], 3)}


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


def ask(bench: dict, imprint: Path | None, model: str, call=None) -> dict:
    """imprint=None is the control run: the same questions, nothing to read."""
    text = imprint.read_text(encoding="utf-8") if imprint else ""
    qids = {f"Q{n:02d}": q["id"] for n, q in enumerate(bench["questions"], 1)}
    prompt = (f"<imprint>\n{text}\n</imprint>\n\nQuestions:\n"
              + "\n".join(f"{n}: {q['text']}" for n, q in zip(qids, bench["questions"])))
    num_ctx = max(8192, 1 << (len(prompt) // 3 + 2048).bit_length())
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model,
              "set": bench["set"], "set_sha256": bench["set_sha256"],
              # ponytail: tokens_est is chars/4 (no tokenizer offline); prompt_tokens is measured
              "imprint": {"control": imprint is None, "path": str(imprint) if imprint else None,
                          "sha256": _sha(imprint) if imprint else None, "bytes": len(text.encode()),
                          "tokens_est": len(text) // 4},
              "questions": [{"id": q["id"], "text": q["text"]} for q in bench["questions"]]}
    backend, _, name = model.partition(":")
    try:
        call = call or BACKENDS.get(backend)
        if call is None:
            raise RuntimeError(f"no adapter for backend '{backend}' (have: {', '.join(BACKENDS)})")
        out = call(name, bench["system"], prompt, num_ctx)
    except Exception as exc:  # noqa: BLE001 — every failure to ASK is the same answer: no score
        return {**record, "status": "UNAVAILABLE", "why": f"{type(exc).__name__}: {exc}"[:200]}
    answers = {}
    for line in (out.get("text") or "").splitlines():
        m = QLINE.match(line.strip())
        if m and m.group(1).upper() in qids:
            answers[qids[m.group(1).upper()]] = m.group(2).strip()
    return {**record, "status": "ok", "answers": answers, "parsed": len(answers),
            "raw": out.get("text", ""), "prompt_tokens": out.get("tokens"), "num_ctx": num_ctx}


def exit_code(rec: dict) -> int:
    """2 = the newborn could not be asked; 1 = it answered, not in the Qnn format; 0 = it answered."""
    if rec.get("status") != "ok":
        return 2
    return 1 if rec.get("parsed", 0) < len(rec.get("questions", [])) else 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _ctx(c: dict | None) -> str:
    c = c or {}
    return "none (control)" if c.get("control") else f"{c.get('path')} (~{c.get('tokens_est')} tokens est)"


def _render(res: dict) -> str:
    if res["status"] != "ok":
        run = res.get("run")
        tail = f"\n  run alone: {run['score']:.3f}, no lift without a control" if run else ""
        return f"apgar: {res['status']} — {res['why']}{tail}"
    ctl = res.get("control")
    out = [f"apgar  newborn {res['model']}  imprint {_ctx(res['imprint'])}",
           f"score {res['score']:.3f} over {len(res['questions'])} questions"
           + (f", {res['unparsed']} not in the Qnn format (scored 0)" if res["unparsed"] else "")]
    if ctl:
        out.append(f"control {ctl['score']:.3f}  lift {res['lift_total']:+.3f}  (control imprint: {_ctx(ctl['imprint'])})")
        out.append(f"  {'family':18} {'score':>6} {'control':>8} {'lift':>7}")
        out += [f"  {f:18} {s:6.3f} {ctl['families'][f]:8.3f} {res['lift'][f]:+7.3f}"
                for f, s in res["families"].items()]
    else:
        out.append("no --control: this number cannot be told from guessing")
        out += [f"  {f:18} {s:.3f}" for f, s in res["families"].items()]
    out += [f"  {r['id']:20} {r['score']:.2f}  found={','.join(r['found']) or '-'}  "
            f"key={','.join('|'.join(s) for s in r['key'])}" for r in res["questions"] if r["score"] < 1]
    return "\n".join(out)


def _load(path: str | None) -> dict | None:
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] + " Named for the newborn "
                                 "score: taken in the first minutes, on what it was shown first.")
    ap.add_argument("--set", default=str(SET), help="question set (default: state/apgar.yml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("questions")
    q.add_argument("--json", action="store_true")
    a = sub.add_parser("ask")
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--imprint", help="the imprint: the ONE file the newborn may read")
    src.add_argument("--no-imprint", action="store_true", help="the control run: same questions, nothing to read")
    a.add_argument("--model", required=True, help="the newborn, <backend>:<model>, e.g. ollama:hermes3:8b")
    a.add_argument("--out", required=True)
    s = sub.add_parser("score")
    s.add_argument("answers")
    s.add_argument("--control", help="answers file of an `ask --no-imprint` run")
    s.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    bench = build(Path(args.set).resolve())

    if args.cmd == "questions":
        if args.json:
            print(json.dumps(bench, indent=2))
        else:
            for q in bench["questions"]:
                print(f"{q['id']:20} {q['text']}\n{'':20} key: {', '.join('|'.join(s) for s in q['key'])}")
            print(f"{len(bench['questions'])} questions, set sha256 {bench['set_sha256'][:12]}")
        return 0
    if args.cmd == "ask":
        rec = ask(bench, None if args.no_imprint else Path(args.imprint), args.model)
        Path(args.out).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        rc = exit_code(rec)
        print("apgar ask: " + (f"UNAVAILABLE — {rec['why']}" if rc == 2 else
              f"{rec['parsed']}/{len(rec['questions'])} answers in the Qnn format") + f" → {args.out}")
        return rc
    res = score(_load(args.answers), bench, _load(args.control))
    print(json.dumps(res, indent=2) if args.json else _render(res))
    return 0 if res["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
