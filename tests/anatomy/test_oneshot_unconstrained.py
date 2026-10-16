"""tools/oneshot-poc.py on an Ollama whose engine has no structured output (MLX: HTTP 501 to any `format`).

Offline only: a stdlib fake Ollama on a random 127.0.0.1 port answers 501 to a `format` body and
plain chat otherwise. The unconstrained reply is parsed strictly; a bad answer escalates, never coerced.
"""

from __future__ import annotations

import io
import json
import re
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_oneshot_systemone import CASES, SCRIPTS, _poc, _scripted

NO_FORMAT = {"error": "structured output is unavailable"}


class _Ollama(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        srv = self.server
        srv.posts.append(body)
        if "format" in body and srv.no_format:
            code, data = 501, NO_FORMAT
        else:
            code, data = 200, {"message": {"role": "assistant", "content": srv.reply(body)}}
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


@pytest.fixture
def ollama(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
    srv.posts, srv.no_format, srv.reply = [], True, lambda body: "{}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("OLLAMA_HOST", srv.url)
    yield srv
    srv.shutdown()
    srv.server_close()


def _keys(body):
    return re.findall(r"^- (\S+): ", body["messages"][1]["content"], re.M)


def test_a_501_switches_the_run_to_unconstrained_and_the_plan_compiles(ollama):
    poc, script = _poc(), SCRIPTS["top3-next"]

    def reply(body):  # a fenced JSON object of every question the battery lists
        got = {k: ("yes" if v else "no") if isinstance(v, bool) else str(v)
               for k in _keys(body) for v in [_scripted(script, k)]}
        return "```json\n" + json.dumps(got) + "\n```"
    ollama.reply = reply
    backend = {"backend": "ollama", "model": "qwen3.5:2b"}
    dec = lambda r: poc.systemone_decider(r, backend, poc.fake_decider(script))  # noqa: E731
    trace = io.StringIO()
    res = poc.run(CASES["top3-next"], lambda t: script.get("normalised") or " ".join(t), dec, trace, "qwen3.5:2b")
    assert res["ok"], res
    assert res["mode"] == "mixed"  # the battery went unconstrained; the scripted 9B rows did not
    assert sum("format" in p for p in ollama.posts) == 1, "the fallback holds for the rest of the run"
    rows = [json.loads(x) for x in trace.getvalue().splitlines()]
    assert all(isinstance(r.get("constrained"), bool) for r in rows), rows
    assert not any(r["constrained"] for r in rows if r.get("by") == "qwen3.5:2b")
    why = [r["format_fallback"] for r in rows if "format_fallback" in r]
    assert len(why) == 1 and "structured output is unavailable" in why[0]


def test_an_invalid_or_missing_answer_is_refused_and_escalated(ollama):
    poc, asked = _poc(), []
    ollama.reply = lambda body: json.dumps({"s1.table": "c", "s1.dir": "desc"})  # "c" is no option; s1.ok absent
    qs = [{"id": "s1.table", "kind": "choice", "text": "which table?", "options": ["a", "b"]},
          {"id": "s1.dir", "kind": "choice", "text": "which way?", "options": ["asc", "desc"]},
          {"id": "s1.ok", "kind": "yesno", "text": "ok?"}]
    wave = poc.systemone_decider("r", {"backend": "ollama", "model": "m"}, lambda q: asked.append(q["id"]) or (
        "b" if q["kind"] == "choice" else True))
    assert list(wave(qs)) == ["b", "desc", True]
    assert asked == ["s1.table", "s1.ok"]
    assert "'c'" in qs[0]["escalated"] and qs[0]["by"] == "llm" and qs[0]["constrained"] is False
    assert "escalated" not in qs[1] and qs[1]["by"] == "m"
    assert "escalated" in qs[2]


def test_a_code_fenced_reply_parses_and_prose_alone_does_not():
    poc = _poc()
    assert poc._json_reply('Sure:\n```json\n{"a": "x", "b": 2}\n```\nanything') == {"a": "x", "b": 2}
    with pytest.raises(ValueError):
        poc._json_reply("I would pick the first table.")


def test_the_9b_path_falls_back_too(ollama):
    poc = _poc()
    ollama.reply = lambda body: '{"answer": 3}'
    qn = {"id": "s1.limit", "kind": "int", "text": "how many?", "min": 1, "max": 50, "options": None}
    assert poc.live_decider("qwen3.5:9b", "top 3")(qn) == 3 and qn["constrained"] is False
    assert "JSON object" in ollama.posts[-1]["messages"][0]["content"] and "format" not in ollama.posts[-1]


def test_constrained_mode_still_sends_format_and_never_falls_back(ollama):
    poc = _poc()
    poc.FORMAT_MODE = "constrained"
    body = {"model": "m", "state": "s", "questions": {"x": {"type": "noul", "instructions": "x?"}}}
    with pytest.raises(urllib.error.HTTPError):
        poc.ask_systemone(body, {"backend": "ollama", "model": "m"})
    assert len(ollama.posts) == 1 and ollama.posts[0]["format"]["properties"]["x"]["enum"] == ["yes", "no"]
    ollama.no_format, ollama.reply = False, lambda b: '{"x": "yes"}'
    resp = poc.ask_systemone(body, {"backend": "ollama", "model": "m"})
    assert resp["constrained"] is True and "format" in ollama.posts[-1]


def test_the_flag_reaches_the_run_and_the_table_shows_the_mode(tmp_path, monkeypatch, capsys):
    poc = _poc()
    monkeypatch.delenv("NOS_LIVE", raising=False)
    poc.main(["--format-mode", "unconstrained", "--trace", str(tmp_path / "t"), "--out", str(tmp_path / "o")])
    assert poc.FORMAT_MODE == "unconstrained"
    assert re.search(r"^case\s+model\s+mode\s", capsys.readouterr().out, re.M)
