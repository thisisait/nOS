"""iris-bench and oneshot-poc say which weights answered: a run without a digest is not evidence.

nos-assay (a private repo) keeps runs as decisions' evidence; a model NAME can be re-pointed
upstream, so each run records the Ollama manifest digest of every model it used, the nOS commit
and its own argv. A digest it could not read is null with the reason — never a guess.
"""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
D9 = "d63f830f28d515fefea546f213fca7a75e9dd5176ef51a6deabc952d1c99a911"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Tags(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        raw = json.dumps({"models": [{"name": "qwen3.5:9b", "digest": D9},
                                     {"name": "bge-m3:latest", "digest": "b" * 64}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


@pytest.fixture
def tags():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Tags)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_an_ollama_model_gets_its_digest_and_an_unknown_one_none(tags):
    bench = _load("iris_bench", "tools/iris-bench.py")
    p = bench.provenance({"decision": "qwen3.5:9b", "embed": "bge-m3", "other": "nope:1b"}, tags)
    by = {m["role"]: m for m in p["models"]}
    assert by["decision"]["digest"] == f"sha256:{D9}" and by["decision"]["source"] == "ollama:qwen3.5:9b"
    assert by["embed"]["digest"] == "sha256:" + "b" * 64  # bge-m3 is bge-m3:latest
    assert by["other"]["digest"] is None
    assert len(p["nos_commit"]) == 40 and isinstance(p["argv"], list)


def test_an_unreachable_ollama_records_why_and_no_digest():
    bench = _load("iris_bench", "tools/iris-bench.py")
    p = bench.provenance({"decision": "qwen3.5:9b"}, "http://127.0.0.1:9")
    assert p["models"][0]["digest"] is None and p["tags_error"]


def test_iris_bench_reads_the_model_from_the_session_uri(tags):
    bench = _load("iris_bench", "tools/iris-bench.py")
    assert bench.uri_models(["ollama-qwen3.5:9b", "mistral-eu-mistral-small"], tags) == {
        "ollama-qwen3.5:9b": "qwen3.5:9b", "mistral-eu-mistral-small": "mistral-eu-mistral-small"}


def test_a_domain_resolves_under_nos_assay_dir(tmp_path, monkeypatch):
    bench = _load("iris_bench", "tools/iris-bench.py")
    (tmp_path / "domains/d1").mkdir(parents=True)
    (tmp_path / "domains/d1/cases.yml").write_text("[]\n")
    monkeypatch.setenv("NOS_ASSAY_DIR", str(tmp_path))
    assert bench.cases_path("default.yml", "d1") == tmp_path / "domains/d1/cases.yml"
    assert bench.cases_path("default.yml", None) == Path("default.yml")
    monkeypatch.delenv("NOS_ASSAY_DIR")
    with pytest.raises(SystemExit):
        bench.cases_path("default.yml", "d1")


def test_oneshot_out_carries_the_provenance(tmp_path, monkeypatch):
    poc = _load("oneshot_poc", "tools/oneshot-poc.py")
    monkeypatch.delenv("NOS_LIVE", raising=False)
    out = tmp_path / "o.json"
    poc.main(["--trace", str(tmp_path / "t"), "--out", str(out)])
    p = json.loads(out.read_text())["provenance"]
    assert {m["role"] for m in p["models"]} == {"decision", "normaliser"}
    assert len(p["nos_commit"]) == 40 and "--out" in p["argv"]
