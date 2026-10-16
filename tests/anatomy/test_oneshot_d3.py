"""tools/oneshot-poc.py speaks vLLM-SR Decision 3.0 (d3-flash, d3-mini) two ways, offline.

`--backend d3`: d3's own System One server (llama serve / vllm-sr / d3_server.py), answers in
d3_runtime.product_answer's shape. `--backend d3-ollama`: the GGUF in Ollama, asked d3's
code-readout prompt (d3_format.py) one question at a time; the reply is one option code.
"""

from __future__ import annotations

import io
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_oneshot_systemone import CASES, SCRIPTS, _poc, _scripted
from test_oneshot_unconstrained import ollama  # noqa: F401  (the fake Ollama fixture)


def _entropy_conf(ps):
    return 1 - -sum(p * math.log(p) for p in ps if p > 0) / math.log(len(ps))


def _d3_answer(q, v):
    """d3_runtime.product_answer for scripted value `v` at 0.9: no `confidence` on noul, entropy elsewhere."""
    if q["type"] == "noul":
        return {"type": "noul", "noul": 0.9 if v else 0.1}
    keys = list(q["criteria"]) if q["type"] == "choice" else [str(i) for i in range(len(q["criteria"]))]
    top = str(v) if q["type"] == "choice" else str(q["criteria"].index(str(v)))
    probs = {k: 0.9 if k == top else 0.1 / (len(keys) - 1) for k in keys}
    if q["type"] == "choice":
        return {"type": "choice", "choice": top, "probabilities": probs, "confidence": _entropy_conf(probs.values())}
    return {"type": "score", "score": sum(int(k) * p for k, p in probs.items()), "probabilities": probs,
            "confidence": _entropy_conf(probs.values()), "legend": dict(zip(keys, q["criteria"]))}


class _D3(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.posts.append({"path": self.path, "body": body})
        answers = {i: self.server.answer(i, q) for i, q in body["questions"].items()}
        raw = json.dumps({"model": "vllm-d3-flash", "answers": {k: v for k, v in answers.items() if v},
                          "usage": {"input_tokens": 1, "output_tokens": 0}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


@pytest.fixture
def d3():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _D3)
    srv.posts, srv.answer = [], lambda i, q: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()
    srv.server_close()


def test_a_d3_server_answers_the_battery_and_the_plan_compiles(d3):
    poc, script = _poc(), SCRIPTS["top3-next"]
    d3.answer = lambda i, q: _d3_answer(q, _scripted(script, i))
    backend = {"backend": "d3", "base_url": d3.url, "model": "vllm-sr/d3-flash"}
    dec = lambda r: poc.systemone_decider(r, backend, poc.fake_decider(script), 0.3)  # noqa: E731
    trace = io.StringIO()
    res = poc.run(CASES["top3-next"], lambda t: script.get("normalised") or " ".join(t), dec, trace, "d3-flash")
    assert res["ok"], res
    assert d3.posts and all(p["path"] == "/v1/systemone" for p in d3.posts)
    rows = [json.loads(x) for x in trace.getvalue().splitlines()]
    d3_rows = [r for r in rows if r.get("by") == "vllm-sr/d3-flash"]
    assert d3_rows and all(r["calibrated"] and r["constrained"] for r in d3_rows)
    assert any("confidence" in r for r in d3_rows)


def test_a_malformed_d3_answer_is_refused_and_escalated(d3):
    poc, asked = _poc(), []
    bad = {"s1.table": {"type": "choice", "choice": "zzz", "probabilities": {"zzz": 1.0}},
           "s1.ok": {"type": "noul", "noul": "yes"}}  # and s1.dir gets no answer at all
    d3.answer = lambda i, q: bad.get(i)
    qs = [{"id": "s1.table", "kind": "choice", "text": "which table?", "options": ["a", "b"]},
          {"id": "s1.ok", "kind": "yesno", "text": "ok?"},
          {"id": "s1.dir", "kind": "choice", "text": "which way?", "options": ["asc", "desc"]}]
    wave = poc.systemone_decider("r", {"backend": "d3", "base_url": d3.url, "model": "m"},
                                 lambda q: asked.append(q["id"]) or (q["options"][0] if q["options"] else True))
    assert list(wave(qs)) == ["a", True, "asc"]
    assert asked == ["s1.table", "s1.ok", "s1.dir"]
    assert all(q["by"] == "llm" and q["escalated"] for q in qs), qs


def test_the_gguf_in_ollama_gets_d3s_own_prompt_and_one_code_back(ollama):  # noqa: F811
    poc, replies = _poc(), iter(["B", "A", "C", "maybe"])
    ollama.no_format = False
    ollama.reply = lambda body: next(replies)
    body = {"model": "m", "state": "Checkout fails", "questions": {
        "team": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "Payments", "tech": None}},
        "urgent": {"type": "noul", "instructions": "Urgent?"},
        "sev": {"type": "score", "instructions": "How bad?", "criteria": ["None", "Minor", "Major"]},
        "odd": {"type": "noul", "instructions": "Odd?"}}}
    resp = poc.ask_systemone(body, {"backend": "d3-ollama", "model": "m"})
    a = resp["answers"]
    assert a["team"]["choice"] == "tech" and a["urgent"]["noul"] == 1.0 and a["sev"]["probabilities"]["2"] == 1.0
    assert "refused" in a["odd"] and resp["calibrated"] is False and resp["constrained"] is False
    sent = ollama.posts[0]
    assert "format" not in sent and sent["messages"][0]["content"] == poc.D3_SYSTEM
    assert sent["messages"][1]["content"] == (
        "State:\nCheckout fails\n\nQuestion:\nWhich team?\n\nOptions:\nA: billing: Payments\nB: tech\n\n"
        "Reply with only the code of the best option.")
    assert "A: No / false\nB: Yes / true" in ollama.posts[1]["messages"][1]["content"]
    assert "A: None\nB: Minor\nC: Major" in ollama.posts[2]["messages"][1]["content"]


def test_a_remote_d3_server_is_refused_without_allow_remote(monkeypatch):
    poc = _poc()
    monkeypatch.setenv("NOS_LIVE", "1")
    monkeypatch.setattr(poc, "_http", lambda *a: pytest.fail("refused run sent the state"))
    assert poc.main(["--backend", "d3", "--base-url", "https://decision.vllm-sr.ai", "--case", "top3-next"]) == 2
