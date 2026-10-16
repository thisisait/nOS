#!/usr/bin/env python3
"""One-shot execution PoC: a battery of tiny constrained questions compiles a thalamus tool plan.

Pipeline: (a) a mid-size model only NORMALISES the person's turns into one canonical request;
(b) a question battery is derived from the thalamus tool schemas (state/fixtures/oneshot/
thalamus-tools.json, pinned to serve::tools() by thalamus/tests/tool_schemas.rs) and a table
catalogue (state/fixtures/oneshot/catalogue.yml); (c) the questions go out as a SystemOne body
{model, state, questions: {id: {type: noul|choice|score, instructions, criteria}}} (the format of
Jev, Clef and Clef-flash), one body per WAVE: the walk sends what it can ask before an answer steers
it, split at --max-per-call (64). ask_systemone() has two backends: `ollama` (one `format` schema of
enums, think off, temperature 0, one-hot answers, calibrated: false) and `http` (POST /v1/systemone
to clef_mlx.py serve, SGLang, llama.cpp, Workers AI or TypeSafe; calibrated). An int over 10 values,
a number or free text has no SystemOne type and goes to the normaliser model (`by: llm` in the
trace), as does a calibrated answer under --abstain. A non-local http host is refused without
--allow-remote; the trace records each answer's processor. (d) the walker that asked the questions is also the
compiler: replayed over the recorded answers it yields the plan, a JSON tool-call sequence;
(e) a dry run validates every call against its schema. Nothing is executed.

Every step's tool question offers the FULL tool list plus "done". A later call names an earlier
read's row as "$step1.rows[0].__id". Optional scorer (--scorer embed): bge-m3 embeddings pick a
table/column/value when the top-1 margin clears --margin, else the decision model is asked; the
margin is in the trace either way. Every question, answer and latency goes to --trace (JSONL).

Offline (default): scripted fake models from state/fixtures/oneshot/fake-answers.yml; an
unscripted question fails that case. Live talks to Ollama (OLLAMA_HOST, default localhost:11434):
    python3 tools/oneshot-poc.py                                  # offline eval, scripted cases
    NOS_LIVE=1 python3 tools/oneshot-poc.py --case top3-next --decision-model qwen3.5:2b
    NOS_LIVE=1 python3 tools/oneshot-poc.py --decision-model qwen3.5:2b,gemma4:e2b --scorer embed
    NOS_LIVE=1 python3 tools/oneshot-poc.py --backend http --base-url http://127.0.0.1:8000  # local Clef-flash
Models: --normaliser-model (NOS_ONESHOT_NORMALISER, qwen3.5:9b), --decision-model (comma list,
NOS_ONESHOT_DECISION, qwen3.5:2b), --embed-model (bge-m3).

Measured: per case, plan ok against the iris-bench checks that translate to a plan (tools_called,
tools_not_called, kinds_drawn, query_uses, chart_source, approval_*, proposes_nothing; the rest
need a real answer and are counted n/t), questions asked, total latency.

Known limits: the catalogue is a fixture (live list_tables needs the socket); offer_dashboard's
untyped widget objects are skipped; free text is not checked against the request (the trace
flags `in_text`); a low embed margin falls through to the decision model, not the 9B; the plan is
validated, never run, so a wrong row reference or an empty result goes unseen.

--format-mode auto (default): an Ollama that answers HTTP 501 "structured output is unavailable"
(the MLX engine) to a `format` is asked in plain chat for the rest of the run; the reply's first
JSON object is checked against each question's options, and a bad or missing answer escalates.
Every trace row says `constrained`; the switch's reason lands once, as `format_fallback`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "state/fixtures/oneshot"
TOOLS = json.loads((FIX / "thalamus-tools.json").read_text(encoding="utf-8"))
SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}
CATALOGUE = yaml.safe_load((FIX / "catalogue.yml").read_text(encoding="utf-8"))
NONE, DONE, MAX_STEPS = "(none)", "done", 4
FIRST = ("table", "query", "source")  # the entity anchors: asked before their siblings
SERVE_FILLS = {"series"}               # serve's normalize_show fills a sourced chart's series
CARD = {"propose_row_edit": "row_diff_approval", "propose_row_insert": "row_diff_approval",
        "propose_row_delete": "row_diff_approval", "propose_table_create": "table_schema_approval",
        "propose_column_add": "column_add_approval"}
DRAWS = {"query_rows": "table_results", "red_status": "red_status", "approvals_awaiting": "approvals_list",
         "search_memory": "list", "nos_guide": "list", "estate_services": "table", "list_tables": "table",
         "inbox": "inbox_list", "offer_dashboard": "dashboard"}
REF = re.compile(r"^\$step(\d+)\.rows\[0\]\.__id$")
FORMAT_MODE = "auto"                   # --format-mode: auto | constrained | unconstrained
UNCONSTRAINED, FALLBACK_NEWS = {}, []  # host -> why it lost `format`; reasons not yet traced
NO_FORMAT = "structured output is unavailable"


class Refused(Exception):
    """An answer set the compiler will not turn into a call."""


def _bench():
    spec = importlib.util.spec_from_file_location("iris_bench", REPO / "tools/iris-bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _table(title):
    return next((t for t in CATALOGUE["tables"] if t["title"] == title), None)


# ── (b)+(d) the battery and the compiler: one walker, asked live or replayed over answers ──

def build(request: str, ask) -> dict:
    """Ask the battery through `ask(question) -> answer`; return {triage, plan}."""
    triage = {s: ask({"id": f"sys.{s}", "kind": "yesno", "leaf": True,
                      "text": f"Does the request need {s.replace('_', ' ')}?"}) for s in CATALOGUE["systems"]}
    triage["multi_step"] = ask({"id": "multi_step", "kind": "yesno", "leaf": True,
                                "text": "Does it need more than one tool call?"})
    plan = []
    for n in range(1, MAX_STEPS + 1):
        tool = ask({"id": f"s{n}.tool", "kind": "choice", "options": list(SCHEMAS) + [DONE],
                    "text": f"Step {n}: which tool runs next? done = nothing more."})
        if tool == DONE:
            break
        ctx = {"tool": tool, "table": None, "steps": plan, "source": False}
        args = _walk(SCHEMAS[tool], f"s{n}", "", ask, ctx, True)
        plan.append({"tool": tool, "args": args})
    return {"triage": triage, "plan": plan}


def _walk(sch, pid, name, ask, ctx, required, parent=None):
    """One schema node -> its value (or NONE to omit), asking only what the node leaves open."""
    q = lambda kind, text, **kw: ask({"id": pid, "kind": kind, "text": text, **kw})  # noqa: E731
    what = f"{ctx['tool']} {pid.split('.', 1)[-1]}: {sch.get('description', '')}".strip()
    if "const" in sch:
        return sch["const"]
    if "oneOf" in sch:  # show's component: pick the branch by its kind
        kinds = [b["properties"]["kind"]["const"] for b in sch["oneOf"]]
        kind = q("choice", f"{what} which component kind?", options=kinds, entity=True)
        return _walk(sch["oneOf"][kinds.index(kind)], pid, name, ask, ctx, True)
    if "anyOf" in sch:  # a column is a label or {label, kind, ...}: the object says more
        return _walk(next(b for b in sch["anyOf"] if b.get("type") == "object"), pid, name, ask, ctx, required)
    opt = [] if required else [NONE]
    table = ctx["table"]
    if name == "table":
        v = q("choice", f"{what} which table?", options=[t["title"] for t in CATALOGUE["tables"]] + opt, entity=True)
        ctx["table"] = _table(v) or ctx["table"]
        return v
    if name in ("column", "group_by", "y", "x") and "enum" not in sch and table:
        cols = [c["key"] for c in table["columns"] if name != "y" or c["kind"] == "number"]
        return q("choice", f"{what} which column?", options=cols + opt, entity=True, leaf=name != "column")
    if name == "row_id":
        refs = [f"$step{i + 1}.rows[0].__id" for i, s in enumerate(ctx["steps"]) if s["tool"] == "query_rows"]
        if refs:
            return q("choice", f"{what} which earlier read's row?", options=refs, leaf=True)
        return q("text", what, leaf=True)
    if name == "value" and parent is not None and table:
        return _where_value(pid, what, q, table, parent)
    if name == "values" and table:  # column -> value: one question per column of the chosen table
        out = {}
        for c in table["columns"]:
            v = _cell(f"{pid}.{c['key']}", f"{what} new value of {c['key']}?", ask, c)
            if v != NONE:
                out[c["key"]] = v
        return out
    if "enum" in sch:  # a where's op steers its value's question: not a leaf
        return q("choice", what, options=list(sch["enum"]) + opt, leaf=name != "op")
    t = sch.get("type")
    if t == "boolean":
        return q("choice", what, options=["yes", "no"] + opt, leaf=True) if opt else q("yesno", what, leaf=True)
    if t in ("integer", "number"):
        if opt and not q("yesno", f"{what} set it?", id_suffix=".use"):
            return NONE
        lo, hi = sch.get("minimum"), sch.get("maximum")
        return q("int", what, min=lo, max=hi, leaf=True) if t == "integer" else q("number", what, leaf=True)
    if t == "array":
        items = sch.get("items") or (SCHEMAS["query_rows"]["properties"]["where"]["items"] if name == "where" else None)
        if items is None:
            return NONE
        lo, hi = (sch.get("minItems", 0) if required else 0), sch.get("maxItems", 8)
        n = ask({"id": f"{pid}.n", "kind": "int", "text": f"{what} how many?", "min": lo, "max": hi})
        if n == 0 and not required:
            return NONE
        if "prefixItems" in items:
            return [[_walk(p, f"{pid}.{i}.{j}", "", ask, ctx, True) for j, p in enumerate(items["prefixItems"])]
                    for i in range(n)]
        return [_walk(items, f"{pid}.{i}", name, ask, ctx, True) for i in range(n)]
    if t == "object":
        props = sch.get("properties")
        if not props:
            if required:
                raise Refused(f"{pid}: an untyped object; the battery has no question for it")
            return NONE  # ponytail: offer_dashboard's widget specs, add a sub-battery when dashboards matter
        if opt and not q("yesno", f"{what} include it?", id_suffix=".use"):
            return NONE
        req = set(sch.get("required", []))
        out = {}
        for k in sorted(props, key=lambda k: (k not in FIRST, FIRST.index(k) if k in FIRST else 0, k)):
            if k in SERVE_FILLS and ctx["source"]:
                out[k] = [{"name": "rows", "points": [["", 0]]}]  # what normalize_show inserts
                continue
            v = _walk(props[k], f"{pid}.{k}", k, ask, ctx, k in req, out)
            if v != NONE:
                out[k] = v
            if k == "source":
                ctx["source"] = v != NONE
        return out
    if opt and not q("yesno", f"{what} set it?", id_suffix=".use"):
        return NONE
    return q("text", what, leaf=True)


def _where_value(pid, what, q, table, parent):
    q = lambda *a, _q=q, **kw: _q(*a, leaf=True, **kw)  # noqa: E731
    col = next((c for c in table["columns"] if c["key"] == parent.get("column")), {"kind": "text"})
    op = parent.get("op")
    if op == "between":
        return [q("text", f"{what} from?", id_suffix=".from"), q("text", f"{what} to?", id_suffix=".to")]
    if col["kind"] == "select" and op in ("eq", "neq"):
        return q("choice", what, options=col["options"], entity=True)
    return q("number", what) if col["kind"] == "number" and op in ("lt", "gt") else q("text", what)


def _cell(pid, what, ask, col):
    if col["kind"] == "select":
        return ask({"id": pid, "kind": "choice", "text": what, "options": col["options"] + [NONE], "entity": True,
                    "leaf": True})
    if not ask({"id": f"{pid}.use", "kind": "yesno", "text": f"{what} set it?"}):
        return NONE
    return ask({"id": pid, "kind": "number" if col["kind"] == "number" else "text", "text": what, "leaf": True})


# ── (e) the dry run ──

def validate(plan: list[dict]) -> list[dict]:
    """Refuse a call its schema refuses, or a row reference to a step that is not an earlier read."""
    for i, call in enumerate(plan, 1):
        def deref(v):
            if isinstance(v, str) and (m := REF.match(v)):
                k = int(m.group(1))
                if not (k < i and plan[k - 1]["tool"] == "query_rows"):
                    raise Refused(f"step {i}: {v} is not an earlier query_rows")
                return "row-id"
            return {k: deref(x) for k, x in v.items()} if isinstance(v, dict) else [deref(x) for x in v] if isinstance(v, list) else v
        if call["tool"] not in SCHEMAS:
            raise Refused(f"step {i}: no tool {call['tool']!r}")
        errs = sorted(jsonschema.Draft202012Validator(SCHEMAS[call["tool"]]).iter_errors(deref(call["args"])), key=str)
        if errs:
            raise Refused(f"step {i} {call['tool']}: {errs[0].message} at {list(errs[0].absolute_path)}")
    return plan


def compile_answers(request: str, answers: dict) -> dict:
    """The compiler proper: replay the battery over recorded answers, then validate the plan."""
    def ask(qn):
        key = qn["id"] + qn.get("id_suffix", "")
        if key not in answers:
            raise Refused(f"no answer for {key}")
        return check_answer(qn, answers[key])
    out = build(request, ask)
    validate(out["plan"])
    return out


def check_answer(qn, a):
    """An answer outside its question's constraint is refused, never coerced."""
    k = qn["kind"]
    ok = (isinstance(a, bool) if k == "yesno" else a in qn["options"] if k == "choice"
          else isinstance(a, int) and not isinstance(a, bool) and (qn.get("min") is None or a >= qn["min"])
          and (qn.get("max") is None or a <= qn["max"]) if k == "int"
          else isinstance(a, (int, float)) and not isinstance(a, bool) if k == "number" else isinstance(a, str))
    if not ok:
        raise Refused(f"{qn['id']}{qn.get('id_suffix', '')}: {a!r} is not a {k} answer")
    return a


class _Wave(Exception):
    """The walk reached a question whose answer steers it: send the wave first."""


def build_waves(request: str, answer_wave, known: dict) -> dict:
    """Walk over `known`; each unknown question joins the wave, a steering one ends it.

    A leaf's placeholder never steers the walk, so every wave holds real-path questions only.
    `answer_wave(questions)` fills `known`; the last walk, with nothing unknown, is the plan.
    """
    while True:
        wave = []

        def ask(qn):
            k = qn["id"] + qn.get("id_suffix", "")
            if k in known:
                return known[k]
            wave.append(qn)
            if not qn.get("leaf"):
                raise _Wave
            return None
        try:
            out = build(request, ask)
        except _Wave:
            out = None
        if not wave:
            return out
        answer_wave(wave)


# ── SystemOne: the battery for one state, one body per wave (Jev, Clef, Clef-flash) ──

LOCAL = {"127.0.0.1", "localhost", "::1"}
TOOL_DESC = {t["function"]["name"]: t["function"]["description"].split(". ")[0] for t in TOOLS} | {DONE: "nothing more"}


def to_systemone(qn):
    """Our question as a SystemOne one, or None: int over 10 values, number and text have no type."""
    k = qn["kind"]
    if k == "yesno":
        return {"type": "noul", "instructions": qn["text"]}
    if k == "choice":
        desc = TOOL_DESC if qn["id"].endswith(".tool") else {}
        return {"type": "choice", "instructions": qn["text"],
                "criteria": {str(o): desc.get(o, str(o)) for o in qn["options"]}}
    lo, hi = qn.get("min"), qn.get("max")
    if k == "int" and lo is not None and hi is not None and 2 <= hi - lo + 1 <= 10:
        return {"type": "score", "instructions": qn["text"], "criteria": [str(v) for v in range(lo, hi + 1)]}
    return None


def from_systemone(qn, a):
    """(answer, confidence): noul confidence is max(p, 1 - p); score takes its most probable level."""
    if a["type"] == "noul":
        return a["noul"] >= 0.5, max(a["noul"], 1 - a["noul"])
    probs = a.get("probabilities") or {}
    conf = a.get("confidence", max(probs.values(), default=None))
    if a["type"] == "choice":
        return {str(o): o for o in qn["options"]}[a["choice"]], conf
    return qn["min"] + int(max(probs, key=probs.get)), conf


def _host(url):
    return urllib.parse.urlsplit(url).hostname or ""


def ask_systemone(body: dict, backend: dict) -> dict:
    """POST-shaped SystemOne call, split at max_per_call; `calibrated` says if confidence means anything."""
    kind, url = backend["backend"], backend.get("base_url") or ""
    if kind == "http" and _host(url) not in LOCAL and not backend.get("allow_remote"):
        raise Refused(f"{_host(url)!r} is a remote processor: pass --allow-remote to send it the state")
    ids, n = list(body["questions"]), backend.get("max_per_call") or 64
    out = {"model": backend["model"], "answers": {}, "calls": 0, "calibrated": kind == "http",
           "processor": _host(url or os.environ.get("OLLAMA_HOST", "http://localhost:11434"))}
    for i in range(0, len(ids), n):
        part = dict(body, model=backend["model"], questions={k: body["questions"][k] for k in ids[i:i + n]})
        out["answers"] |= (_s1_http if kind == "http" else _s1_ollama)(part, backend)
        out["calls"] += 1
    out["constrained"] = kind == "http" or constrained(url or None)
    return out


def _s1_http(body, backend):
    url = backend["base_url"].rstrip("/")
    url += "" if urllib.parse.urlsplit(url).path.strip("/") else "/v1/systemone"  # Workers AI: the full run URL
    headers = {"Content-Type": "application/json"}
    if backend.get("token_env"):
        headers["Authorization"] = f"Bearer {os.environ[backend['token_env']]}"
    return _http(url, body, headers)["answers"]


def _s1_ollama(body, backend):
    """Every question one enum property of one `format` schema; the answers are one-hot, uncalibrated."""
    qs = body["questions"]
    enum = {k: ["yes", "no"] if q["type"] == "noul" else list(q["criteria"]) for k, q in qs.items()}
    fmt = {"type": "object", "properties": {k: {"enum": e} for k, e in enum.items()}, "required": list(qs)}
    ask = "\n".join(f"- {k}: {q.get('instructions', '')}" + (f" Options: {json.dumps(q['criteria'])}" if
                    q["type"] != "noul" else " yes or no") for k, q in qs.items())
    state = body["state"] if isinstance(body["state"], str) else json.dumps(body["state"])
    try:
        got = _json_reply(_chat(backend["model"], DECIDE, f"Request: {state}\nQuestions:\n{ask}", fmt,
                                host=backend.get("base_url")))
    except ValueError:
        got = {}  # no JSON object: every question is missing, so every one escalates
    out = {}
    for k, q in qs.items():
        if not isinstance(got.get(k), str) or got[k] not in enum[k]:
            out[k] = {"type": q["type"], "refused": f"{k}: {got.get(k)!r} is not one of the listed answers"}
            continue
        if q["type"] == "noul":
            out[k] = {"type": "noul", "noul": 1.0 if got[k] == "yes" else 0.0}
        else:
            keys = list(q["criteria"]) if q["type"] == "choice" else [str(i) for i in range(len(enum[k]))]
            top = got[k] if q["type"] == "choice" else str(enum[k].index(got[k]))
            out[k] = {"type": q["type"], q["type"]: top, "probabilities": {x: float(x == top) for x in keys}}
    return out


def systemone_decider(request, backend, llm_ask, abstain=0.6, scorer=None):
    """A wave answerer: SystemOne-typed questions in one battery, the rest (and abstentions) to `llm_ask`."""
    def wave(qns):
        typed = {}
        for qn in qns:
            if scorer and qn["kind"] == "choice" and qn.get("entity"):
                pick, margin = scorer(request, qn["options"])
                qn["margin"] = round(margin, 4)
                if pick is not None:
                    qn["embed"] = pick
                    continue
            if (sq := to_systemone(qn)) is not None:
                typed[qn["id"] + qn.get("id_suffix", "")] = sq
        resp = ask_systemone({"model": backend["model"], "state": request, "questions": typed}, backend) if typed else {}
        for qn in qns:
            k = qn["id"] + qn.get("id_suffix", "")
            if "embed" in qn:
                qn["by"] = "embed"
                yield qn.pop("embed")
                continue
            if k in typed:
                ans = resp["answers"][k]
                qn.update(by=backend["model"], processor=resp["processor"], calibrated=resp["calibrated"],
                          constrained=resp["constrained"])
                if "refused" in ans:
                    qn["escalated"] = ans["refused"]  # refused, never coerced: the 9B asks it again
                else:
                    a, conf = from_systemone(qn, ans)
                    if not resp["calibrated"]:
                        yield a
                        continue
                    qn["confidence"] = conf
                    if conf is not None and conf >= abstain:
                        yield a
                        continue
                    qn["abstained"] = qn.pop("confidence")
            a = llm_ask(qn)
            qn["by"] = "llm"
            yield a
    return wave


def per_question(ask):
    """The old one-question-per-call decider as a wave answerer."""
    return lambda qns: (ask(qn) for qn in qns)


# ── (a)+(c) models: Ollama in live mode, scripted fakes offline ──

def _http(url, body, headers):
    """A local endpoint never goes through a proxy: a proxy is a processor too."""
    proxy = {} if _host(url) in LOCAL else None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy))
    with opener.open(urllib.request.Request(url, json.dumps(body).encode(), headers), timeout=300) as r:
        return json.loads(r.read())


def _base(host=None):
    return (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")


def _ollama(path, body, host=None):
    return _http(_base(host) + path, body, {"Content-Type": "application/json"})


def constrained(host=None):
    return FORMAT_MODE == "constrained" or FORMAT_MODE == "auto" and _base(host) not in UNCONSTRAINED


def _chat(model, system, user, fmt=None, host=None):
    body = {"model": model, "stream": False, "think": False, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if fmt and constrained(host):
        try:
            return _ollama("/api/chat", dict(body, format=fmt), host)["message"]["content"]
        except urllib.error.HTTPError as e:
            why = e.read().decode("utf-8", "replace").strip()
            if FORMAT_MODE == "constrained" or e.code != 501 or NO_FORMAT not in why:
                raise
            UNCONSTRAINED[_base(host)] = f"HTTP 501 {why} from {_base(host)}"
            FALLBACK_NEWS.append(UNCONSTRAINED[_base(host)])
    if fmt:  # unconstrained: the same keys and answers, asked in words, checked by the caller
        keys = "\n".join(f"- {k}: " + (" | ".join(map(str, p["enum"])) if "enum" in p else json.dumps(p))
                         for k, p in fmt["properties"].items())
        body["messages"][0]["content"] += ("\nReply with ONE JSON object {key: answer} and nothing else. "
                                           f"Use only these keys, each answer exactly one listed value:\n{keys}")
    return _ollama("/api/chat", body, host)["message"]["content"]


def _json_reply(text):
    """The first JSON object in a reply (a code fence or prose around it ignored), else ValueError."""
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in the reply")
    return json.JSONDecoder().raw_decode(text, i)[0]


NORMALISE = ("Rewrite the person's turns as ONE self-contained request in English. Resolve pronouns and "
             "references to earlier turns. Keep table names, row titles, numbers, dates and quoted values "
             "exactly. Do not answer it. Output only the request.")
DECIDE = "You answer one small question about a request to a home-lab assistant. Answer only the JSON asked for."
ANSWER = {"yesno": {"enum": ["yes", "no"]}, "number": {"type": "number"}, "text": {"type": "string", "maxLength": 200}}


def live_normaliser(model):
    return lambda turns: _chat(model, NORMALISE, "\n".join(f"Turn {i + 1}: {t}" for i, t in enumerate(turns))).strip()


def live_decider(model, request, scorer=None):
    tools = "\n".join(f"- {n}: {t['function']['description'].split('. ')[0]}" for n, t in
                      ((t["function"]["name"], t) for t in TOOLS))

    def ask(qn):
        if scorer and qn["kind"] == "choice" and qn.get("entity"):
            pick, margin = scorer(request, qn["options"])
            qn["margin"] = round(margin, 4)
            if pick is not None:
                qn["by"] = "embed"
                return pick
        k = qn["kind"]
        s = {"enum": qn["options"]} if k == "choice" else {"type": "integer", **{x: qn[y] for x, y in (
            ("minimum", "min"), ("maximum", "max")) if qn.get(y) is not None}} if k == "int" else ANSWER[k]
        extra = f"\nTools:\n{tools}" if qn["id"].endswith(".tool") else ""
        opts = f"\nOptions: {', '.join(map(str, qn['options']))}" if k == "choice" else ""
        a = _json_reply(_chat(model, DECIDE, f"Request: {request}{extra}\nQuestion: {qn['text']}{opts}",
                              {"type": "object", "properties": {"answer": s}, "required": ["answer"]}))["answer"]
        qn.update(by=model, constrained=constrained())
        return a == "yes" if k == "yesno" else a
    return ask


def pick_by_margin(q, opts, margin):
    """Nearest option by cosine; None when the top-1 lead over top-2 is under `margin` (escalate)."""
    cos = lambda a, b: sum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b) or 1)  # noqa: E731
    s = sorted(((cos(q, v), i) for i, v in enumerate(opts)), reverse=True)
    lead = s[0][0] - (s[1][0] if len(s) > 1 else -1.0)
    return (s[0][1] if lead >= margin else None), lead


def embed_scorer(model, margin):
    cache = {}

    def vec(text):
        if text not in cache:
            cache[text] = _ollama("/api/embed", {"model": model, "input": text})["embeddings"][0]
        return cache[text]

    def score(request, options):
        real = [o for o in options if o != NONE]  # (none) has no meaning to embed: the model decides it
        if len(real) < len(options) or len(real) < 2:
            return None, 0.0
        i, lead = pick_by_margin(vec(request), [vec(o) for o in real], margin)
        return (real[i] if i is not None else None), lead
    return score


def fake_decider(script):
    """Offline: answers from the case's script; `sys` lists the systems it says yes to."""
    def ask(qn):
        key = qn["id"] + qn.get("id_suffix", "")
        if key.startswith("sys."):
            return key[4:] in script.get("sys", [])
        if key == "multi_step":
            return bool(script.get("multi_step", False))
        if key not in script["answers"]:
            raise Refused(f"unscripted question {key}")
        qn["by"] = "fake"
        return script["answers"][key]
    return ask


# ── the run: trace, eval against the iris-bench checks ──

def run(case, normalise, decider_for, trace, model="fake"):
    """One case end to end; every question lands in `trace` with its answer and latency."""
    bench = _bench()
    turns = bench.turns_of(case)
    t0 = time.monotonic()
    try:
        request = normalise(turns)
    except (OSError, ValueError, KeyError) as e:
        return {"id": case["id"], "ok": False, "questions": 0, "seconds": 0.0, "error": f"normaliser: {e}",
                "failed": [], "nt": [], "plan": None}
    norm_s = time.monotonic() - t0
    trace.write(json.dumps({"case": case["id"], "id": "normalised", "turns": turns, "answer": request,
                            "constrained": False, "ms": round(norm_s * 1000)}, ensure_ascii=False) + "\n")
    inner, answers, n, calls, modes = decider_for(request), {}, 0, 0, set()

    def answer_wave(qns):
        nonlocal n, calls
        calls += 1
        gen = inner(qns)
        for qn in qns:
            n += 1
            t, a, err = time.monotonic(), None, None
            try:  # a model that did not answer is a refusal too
                a = check_answer(qn, next(gen))
            except (Refused, OSError, ValueError, KeyError, StopIteration) as e:
                err = f"{type(e).__name__}: {e}" if not isinstance(e, Refused) else str(e)
            # embed and the scripted fakes pick from the options by construction: constrained
            row = {"case": case["id"], "model": model, "constrained": True, **{k: v for k, v in qn.items() if k not in ("id_suffix", "leaf")},
                   "id": qn["id"] + qn.get("id_suffix", ""), "call": calls,
                   "ms": round((time.monotonic() - t) * 1000), "answer": a}  # a batched call's ms land on its first row
            if FALLBACK_NEWS:
                row["format_fallback"] = FALLBACK_NEWS.pop()
            modes.add(row["constrained"])
            if err:
                row["refused"] = err
            elif qn["kind"] == "text":
                row["in_text"] = a.lower() in request.lower()
            trace.write(json.dumps(row, ensure_ascii=False) + "\n")  # a refused question is traced too
            if err:
                raise Refused(err)
            answers[row["id"]] = a
    res = {"id": case["id"], "request": request, "questions": 0, "plan": None, "error": None}
    try:
        out = build_waves(request, answer_wave, answers)
        res["plan"], res["triage"] = validate(out["plan"]), out["triage"]
        replay = compile_answers(request, answers)  # the compiler from the recorded answers alone
        assert replay["plan"] == res["plan"], "the compiler disagrees with the live walk"
    except Refused as e:
        res["error"] = str(e)
    res["questions"], res["calls"], res["seconds"] = n, calls, round(time.monotonic() - t0, 2)
    res["mode"] = {frozenset({True}): "constrained", frozenset({False}): "unconstrained"}.get(
        frozenset(modes), "mixed" if modes else "-")
    res["failed"], res["nt"] = score(case, res["plan"]) if res["plan"] is not None else (["plan"], [])
    res["ok"] = res["plan"] is not None and not res["failed"]
    return res


TRANSLATED = {"tools_called", "tools_not_called", "no_proposal", "proposes_nothing", "kinds_drawn", "query_uses",
              "chart_source", "approval_kind", "approval_columns", "approval_added", "approval_diff_equals",
              "no_number_without_source"}


def wire_of(plan):
    """What the bench would see on the wire if the plan ran: tools, renders with pins, cards."""
    got = {"tools": [], "renders": [], "approvals": [], "cards": [], "card_kinds": [], "text": "", "texts": []}
    for c in plan:
        tool, a = c["tool"], c["args"]
        got["tools"].append(tool)
        if tool == "show":
            comp = a.get("component", {})
            pin = {"chart" if comp.get("kind") == "chart" else "kpi": dict(a["source"], chart=comp.get("props", {}).get("chart"))} \
                if "source" in a else None
            got["renders"].append({"component": comp, "pin": pin, "by": tool})
        elif tool in DRAWS:
            got["renders"].append({"component": {"kind": DRAWS[tool], "props": {}},
                                   "pin": {"rows": a} if tool == "query_rows" else None, "by": tool})
        elif tool in CARD:
            op = {"propose_row_edit": "update", "propose_row_insert": "insert"}.get(tool, "delete")
            cols = [{"key": col.get("key") or re.sub(r"\W+", "_", col["label"].lower()).strip("_"),
                     "kind": {"bool": "boolean"}.get(col.get("kind", "text"), col.get("kind", "text"))}
                    if isinstance(col, dict) else {"key": col.lower(), "kind": "text"} for col in a.get("columns", [])]
            got["approvals"].append(f"plan-{len(got['approvals'])}")
            got["card_kinds"].append(CARD[tool])
            got["cards"].append({"table": a.get("table"), "op": op, "visibility": "private", "columns": cols,
                                 "cells": [{"key": k, "new": v, "old": None} for k, v in (a.get("values") or {}).items()],
                                 **({"existing": True} if tool == "propose_column_add" else {})})
    return got


def score(case, plan):
    """(failed, not translatable) over the case's checks, judged by iris-bench's own check()."""
    bench, got, failed, nt = _bench(), wire_of(plan), [], []
    for name, arg in case.get("checks", {}).items():
        if arg is False:
            continue
        if name not in TRANSLATED or (name == "approval_diff_equals" and arg.get("op") == "delete"):
            nt.append(name)
        elif not bench.check(name, arg, got, time.time()):
            failed.append(name)
    return failed, nt


PLAN_TOOLS = {"query_rows", "show"} | set(CARD)


def eval_cases(cases):
    """The bench cases whose expected plan reaches query_rows, show or a propose_* tool."""
    keys = {"query_uses", "chart_source", "approval_diff_equals", "approval_columns", "approval_kind", "approval_added"}
    return [c for c in cases if keys & set(c.get("checks", {}))
            or PLAN_TOOLS & set(c.get("checks", {}).get("tools_called") or [])]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", action="append", help="a case id from iris-bench.yml (repeatable); default every eval case")
    ap.add_argument("--cases", default=str(REPO / "state/fixtures/iris-bench.yml"))
    ap.add_argument("--fake", default=str(FIX / "fake-answers.yml"), help="offline scripts")
    ap.add_argument("--normaliser-model", default=os.environ.get("NOS_ONESHOT_NORMALISER", "qwen3.5:9b"))
    ap.add_argument("--decision-model", default=os.environ.get("NOS_ONESHOT_DECISION"),
                    help="comma list: the eval runs once per model (default qwen3.5:2b, http: clef-flash)")
    ap.add_argument("--backend", choices=["ollama", "http"], default="ollama", help="the SystemOne answerer")
    ap.add_argument("--base-url", help="ollama: OLLAMA_HOST; http: a /v1/systemone server (default 127.0.0.1:8000)")
    ap.add_argument("--token-env", help="http: the env var holding a bearer token")
    ap.add_argument("--max-per-call", type=int, default=64, help="questions per SystemOne call (Workers AI: 64)")
    ap.add_argument("--format-mode", choices=["auto", "constrained", "unconstrained"], default="auto",
                    help="ollama: auto drops `format` after a 501 'structured output is unavailable'")
    ap.add_argument("--abstain", type=float, default=0.6, help="calibrated confidence under this goes to the 9B")
    ap.add_argument("--allow-remote", action="store_true", help="http: let a non-local processor see the state")
    ap.add_argument("--scorer", choices=["none", "embed"], default="none")
    ap.add_argument("--embed-model", default=os.environ.get("NOS_ONESHOT_EMBED", "bge-m3"))
    ap.add_argument("--margin", type=float, default=0.05, help="embed scorer: top-1 lead needed to skip the model")
    ap.add_argument("--trace", default=str(FIX / "last-trace.jsonl"))
    ap.add_argument("--out", default=str(FIX / "last-run.json"))
    a = ap.parse_args(argv)
    global FORMAT_MODE
    FORMAT_MODE = a.format_mode
    live = os.environ.get("NOS_LIVE") == "1"
    base = a.base_url or ("http://127.0.0.1:8000" if a.backend == "http" else None)
    if a.backend == "http" and _host(base) not in LOCAL and not a.allow_remote:
        print(f"refused: {_host(base)} is a remote processor; pass --allow-remote", file=sys.stderr)
        return 2
    a.decision_model = a.decision_model or ("clef-flash" if a.backend == "http" else "qwen3.5:2b")
    allc = yaml.safe_load(Path(a.cases).read_text(encoding="utf-8"))
    cases = [c for c in allc if c["id"] in a.case] if a.case else eval_cases(allc)
    scripts = {} if live else yaml.safe_load(Path(a.fake).read_text(encoding="utf-8"))
    if not live:
        cases = [c for c in cases if c["id"] in scripts] if not a.case else cases
    models = a.decision_model.split(",") if live else ["fake"]
    Path(a.trace).parent.mkdir(parents=True, exist_ok=True)
    results = []
    with open(a.trace, "w", encoding="utf-8") as trace:
        for model in models:
            for case in cases:
                if live:
                    scorer = embed_scorer(a.embed_model, a.margin) if a.scorer == "embed" else None
                    cfg = {"backend": a.backend, "base_url": base, "model": model, "token_env": a.token_env,
                           "max_per_call": a.max_per_call, "allow_remote": a.allow_remote}
                    norm, dec = live_normaliser(a.normaliser_model), (lambda r, c=cfg, s=scorer: systemone_decider(
                        r, c, live_decider(a.normaliser_model, r), a.abstain, s))
                elif case["id"] in scripts:
                    s = scripts[case["id"]]
                    norm = lambda turns, s=s: s.get("normalised") or " ".join(turns)  # noqa: E731
                    dec = lambda r, s=s: per_question(fake_decider(s))  # noqa: E731
                else:
                    results.append({"id": case["id"], "model": model, "ok": False, "questions": 0, "seconds": 0.0,
                                    "error": "no offline script", "failed": [], "nt": []})
                    continue
                results.append(dict(run(case, norm, dec, trace, model), model=model))
    Path(a.out).write_text(json.dumps({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "live": live,
                                       "cases": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{'case':<18} {'model':<14} {'mode':<13} {'plan ok':<8} {'#q':>4} {'calls':>5} {'secs':>7}  failed / n/t")
    for r in results:
        why = r["error"] or ", ".join(r["failed"]) or "-"
        print(f"{r['id']:<18} {r['model']:<14} {r.get('mode', '-'):<13} {'yes' if r['ok'] else 'NO':<8} {r['questions']:>4} {r.get('calls', 0):>5} "
              f"{r['seconds']:>7.2f}  "
              f"{why} / {', '.join(r['nt']) or '-'}")
    print(f"{sum(r['ok'] for r in results)}/{len(results)} plans ok · trace {a.trace}")
    return 0 if results and all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
