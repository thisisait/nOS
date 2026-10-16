"""tools/oneshot-poc.py speaks SystemOne: the battery for one state goes out in one body per wave.

Offline only. The HTTP backend is a stdlib server on a random 127.0.0.1 port inside the test;
the Ollama adapter is checked against a captured request, never a running Ollama.
"""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = yaml.safe_load((REPO / "state/fixtures/oneshot/fake-answers.yml").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in yaml.safe_load((REPO / "state/fixtures/iris-bench.yml").read_text(encoding="utf-8"))}


def _poc():
    spec = importlib.util.spec_from_file_location("oneshot_poc", REPO / "tools/oneshot-poc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scripted(script, qid):
    if qid.startswith("sys."):
        return qid[4:] in script.get("sys", [])
    if qid == "multi_step":
        return bool(script.get("multi_step", False))
    return script["answers"][qid]


def _answer(q, v, conf):
    """What a calibrated SystemOne server sends for scripted value `v` at confidence `conf`."""
    if q["type"] == "noul":
        return {"type": "noul", "noul": conf if v else 1 - conf}
    keys = list(q["criteria"]) if q["type"] == "choice" else [str(i) for i in range(len(q["criteria"]))]
    top = str(v) if q["type"] == "choice" else str(q["criteria"].index(str(v)))
    probs = {k: conf if k == top else (1 - conf) / (len(keys) - 1) for k in keys}
    if q["type"] == "choice":
        return {"type": "choice", "choice": top, "confidence": conf, "probabilities": probs}
    return {"type": "score", "score": float(top), "confidence": conf, "probabilities": probs,
            "legend": dict(enumerate(q["criteria"]))}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        srv = self.server
        srv.posts.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        answers = {i: _answer(q, srv.value(i), srv.conf.get(i, 0.95)) for i, q in body["questions"].items()}
        data = json.dumps({"model": body["model"], "answers": answers, "usage": {"input_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.posts, srv.conf, srv.value = [], {}, lambda i: True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _backend(srv, **kw):
    return {"backend": "http", "base_url": f"http://127.0.0.1:{srv.server_address[1]}", "model": "clef-flash", **kw}


def test_a_fake_systemone_server_answers_the_battery_and_the_plan_compiles(server, monkeypatch):
    poc, script = _poc(), SCRIPTS["top3-next"]
    monkeypatch.setattr(poc, "_ollama", lambda *a, **k: pytest.fail("the http backend reached Ollama"))
    monkeypatch.setenv("NOS_TEST_S1_TOKEN", "test-token")
    server.value = lambda i: _scripted(script, i)
    llm = poc.fake_decider(script)
    dec = lambda r: poc.systemone_decider(r, _backend(server, token_env="NOS_TEST_S1_TOKEN"), llm)  # noqa: E731
    trace = io.StringIO()
    res = poc.run(CASES["top3-next"], lambda turns: script.get("normalised") or " ".join(turns), dec, trace, "clef-flash")
    assert res["ok"] and res["plan"] == [{"tool": "query_rows", "args": {
        "table": "iris-bench-2", "limit": 3, "order_by": {"column": "points", "dir": "desc"},
        "where": [{"column": "status", "op": "eq", "value": "next"}]}}], res
    first = server.posts[0]
    assert first["path"] == "/v1/systemone" and first["auth"] == "Bearer test-token"
    # the triage and the first tool question are one battery: every one of them in ONE call
    assert set(first["body"]["questions"]) == {f"sys.{s}" for s in poc.CATALOGUE["systems"]} | {"multi_step", "s1.tool"}
    assert first["body"]["state"] == res["request"] and first["body"]["model"] == "clef-flash"
    assert first["body"]["questions"]["s1.tool"]["type"] == "choice"
    assert set(first["body"]["questions"]["s1.tool"]["criteria"]) == set(poc.SCHEMAS) | {"done"}
    assert len(server.posts) < res["questions"], "one call per question is not a battery"
    rows = [json.loads(x) for x in trace.getvalue().splitlines() if '"normalised"' not in x]
    s1 = [r for r in rows if r["by"] == "clef-flash"]
    assert s1 and all(r["processor"] == "127.0.0.1" and r["calibrated"] for r in s1)
    llm_rows = [r for r in rows if r["by"] == "llm"]
    assert "s1.limit" in {r["id"] for r in llm_rows}  # an int with 51 values has no SystemOne type
    assert all(r["kind"] in ("int", "number", "text") for r in llm_rows), llm_rows


def test_the_ollama_adapter_asks_enums_and_claims_no_calibration(monkeypatch):
    poc, sent = _poc(), []
    reply = {"is_urgent": "yes", "team": "billing", "severity": "Major"}
    monkeypatch.setattr(poc, "_ollama", lambda path, body, host=None: sent.append(body) or {
        "message": {"content": json.dumps(reply)}})
    body = {"model": "qwen3.5:2b", "state": "Checkout fails", "questions": {
        "is_urgent": {"type": "noul", "instructions": "Urgent?"},
        "team": {"type": "choice", "criteria": {"billing": "Payments", "technical": "Outages"}},
        "severity": {"type": "score", "criteria": ["No impact", "Minor", "Major", "Critical"]}}}
    resp = poc.ask_systemone(body, {"backend": "ollama", "model": "qwen3.5:2b"})
    assert len(sent) == 1 and sent[0]["think"] is False and sent[0]["options"]["temperature"] == 0
    props = sent[0]["format"]["properties"]
    assert props["is_urgent"]["enum"] == ["yes", "no"]
    assert props["team"]["enum"] == ["billing", "technical"]
    assert props["severity"]["enum"] == ["No impact", "Minor", "Major", "Critical"]
    a = resp["answers"]
    assert resp["calibrated"] is False and a["is_urgent"]["noul"] == 1.0
    assert a["team"]["probabilities"] == {"billing": 1.0, "technical": 0.0} and "confidence" not in a["team"]
    assert a["severity"]["probabilities"]["2"] == 1.0 and "confidence" not in a["severity"]
    # uncalibrated answers never abstain, whatever the cut-off
    qn = {"id": "s1.table", "kind": "choice", "text": "which table?", "options": ["a", "b"]}
    monkeypatch.setattr(poc, "_ollama", lambda *a, **k: {"message": {"content": json.dumps({"s1__table": "b"})}})
    wave = poc.systemone_decider("r", {"backend": "ollama", "model": "m"}, lambda q: pytest.fail("escalated"), 0.99)
    assert list(wave([qn])) == ["b"] and qn["calibrated"] is False and "confidence" not in qn


def test_abstain_escalates_a_calibrated_answer_below_the_cut_off(server):
    poc, llm_asked = _poc(), []
    server.value = lambda i: {"s1.table": "a", "s1.dir": "desc"}[i]
    server.conf = {"s1.table": 0.4}
    qs = [{"id": "s1.table", "kind": "choice", "text": "which table?", "options": ["a", "b"]},
          {"id": "s1.dir", "kind": "choice", "text": "which way?", "options": ["asc", "desc"]}]
    wave = poc.systemone_decider("r", _backend(server), lambda q: llm_asked.append(q["id"]) or "b", 0.6)
    assert list(wave(qs)) == ["b", "desc"] and llm_asked == ["s1.table"]
    assert qs[0]["by"] == "llm" and qs[0]["abstained"] == pytest.approx(0.4)
    assert qs[1]["by"] == "clef-flash" and qs[1]["confidence"] == pytest.approx(0.95) and "abstained" not in qs[1]
    assert len(server.posts) == 1


def test_a_remote_base_url_is_refused_without_allow_remote(monkeypatch):
    poc, sent = _poc(), []
    monkeypatch.setattr(poc, "_http", lambda url, body, headers: sent.append(url) or {
        "model": "jev", "answers": {"x": {"type": "noul", "noul": 0.9}}})
    body = {"model": "jev-latest", "state": "s", "questions": {"x": {"type": "noul"}}}
    remote = {"backend": "http", "base_url": "https://api.typesafe.ai", "model": "jev-latest"}
    with pytest.raises(poc.Refused, match="allow-remote"):
        poc.ask_systemone(body, remote)
    assert not sent, "a refused processor still received the state"
    resp = poc.ask_systemone(body, dict(remote, allow_remote=True))
    assert resp["processor"] == "api.typesafe.ai" and sent == ["https://api.typesafe.ai/v1/systemone"]
    monkeypatch.setenv("NOS_LIVE", "1")
    monkeypatch.setattr(poc, "_ollama", lambda *a, **k: pytest.fail("refused run reached Ollama"))
    assert poc.main(["--backend", "http", "--base-url", "https://api.typesafe.ai", "--case", "top3-next"]) == 2
    assert len(sent) == 1


def test_max_per_call_splits_a_large_battery(server):
    poc = _poc()
    body = {"model": "clef-flash", "state": "s", "questions": {f"q{i}": {"type": "noul"} for i in range(130)}}
    resp = poc.ask_systemone(body, _backend(server))
    assert [len(p["body"]["questions"]) for p in server.posts] == [64, 64, 2]
    assert len(resp["answers"]) == 130 and resp["calls"] == 3
    server.posts.clear()
    poc.ask_systemone(body, _backend(server, max_per_call=50))
    assert [len(p["body"]["questions"]) for p in server.posts] == [50, 50, 30]
