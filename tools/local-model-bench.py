#!/usr/bin/env python3
"""Measure a local model on the one job the estate has for it, with code as judge.

THE ARGUMENT FOR MEASURING RATHER THAN ARGUING. This host is an M4 Max with
36 GB and 63 containers. `qwen2.5-coder:32b` is 19 GB of that, and it is
configured as Hermes's heavy model on the strength of nobody having checked.
The roadmap carries four `local-llm-*` rows that all presuppose a model choice
nobody has measured.

So: run the candidates through the same task set and read the numbers.

WHAT MAKES THIS CHEAP, AND IT IS NOT AN ACCIDENT. cortex-lang is a typed
pipeline IR with a validator (`POST /agent/v1/validate`) and a closed opcode
registry. A chain is valid or it is not, and a parser says which — so scoring
needs no large model, no rubric, no human. The roadmap row `local-llm-corpus`
names this exactly: "the opcode registry and the validator as a free oracle."

An oracle that costs nothing is what makes a 4B candidate worth a try instead of
reaching for 32B by default.

WHAT IS SCORED (state/local-model-bench.yml carries the tasks)

    valid    the validator accepted the chain              hard pass/fail
    opcode   it used the opcode the task asked for         did it understand?
    tokens   prompt_eval_count + eval_count from ollama    what it cost
    seconds  wall clock                                    what you wait for

Tokens are first-class because that is the axis a loaded box actually feels, and
because it is the axis ThinkingCap-Qwen3.6-27B (BottleCap AI, Apache-2.0)
competes on — ~46% fewer thinking tokens at equal accuracy. A claim like that is
either true on our tasks or it is not, and this tells us which in one run.

WHAT THIS DOES NOT DO. It does not pull models — an unattended 19 GB download is
not a benchmark's business. It does not rank "the best model"; it prints the
numbers and leaves the trade-off to whoever is paying for the RAM. And it never
writes a roadmap row: `tools/roadmap-update.py` owns claims, and a benchmark is
evidence, not a claim.

Usage:
    tools/local-model-bench.py                       # every installed model
    tools/local-model-bench.py --model qwen3:14b --model hermes3:8b
    tools/local-model-bench.py --json results.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "state/local-model-bench.yml"
GRAMMAR = REPO / "state/cortex-lang.gbnf"
OLLAMA = "http://127.0.0.1:11434"
KEAP = "http://127.0.0.1:8091"

#: `--grammar` does NOT go through Ollama, and that is the whole reason this
#: block exists rather than an `options: {grammar: …}` one-liner.
#:
#: MEASURED 2026-08-22. Ollama's /api/generate accepts unknown keys in `options`
#: and DROPS them. hermes3:8b, temperature 0, seed 1, asked to "Say hello.":
#:
#:     no grammar                        -> 'Hello! How can I assist you today?'
#:     options.grammar = root ::= "ZZZ"  -> 'Hello! How can I assist you today?'
#:
#: Byte-identical. A grammar passed that way is a knob that reports itself as
#: set and constrains nothing — the estate's signature defect, and it would have
#: been invisible here because the SCORE would have moved anyway (a better
#: prompt also improves it). So constrained runs talk to `llama-server`, which
#: takes --grammar-file and refuses to start if the grammar does not parse.
#:
#: llama-server ships INSIDE the Homebrew ollama formula rather than on PATH.
LLAMA_SERVER_CANDIDATES = (
    "/opt/homebrew/opt/ollama/libexec/lib/ollama/llama-server",
    "/usr/local/opt/ollama/libexec/lib/ollama/llama-server",
)
OLLAMA_MANIFESTS = Path.home() / ".ollama/models/manifests/registry.ollama.ai/library"
OLLAMA_BLOBS = Path.home() / ".ollama/models/blobs"

#: Models that answer none of these tasks by design — embedders have no chat
#: surface, and asking one to emit a chain measures nothing.
NOT_CHAT = re.compile(r"embed|rerank|bge|minilm", re.I)


def _die(msg: str) -> None:
    sys.exit(f"REFUSING: {msg}")


def _keap_ro_token() -> str:
    import os
    tok = os.environ.get("KEAP_AGENT_TOKEN_RO", "").strip()
    if tok:
        return tok
    tok = subprocess.run(
        ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RO"],
        capture_output=True, text=True).stdout.strip()
    if not tok:
        _die("no KEAP_AGENT_TOKEN_RO — the validator is the judge, and without "
             "it this tool would score nothing while looking like it worked.")
    return tok


def installed_models() -> list[str]:
    out = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if out.returncode != 0:
        _die("`ollama list` failed — is the daemon up?")
    names = [ln.split()[0] for ln in out.stdout.splitlines()[1:] if ln.strip()]
    return [n for n in names if not NOT_CHAT.search(n)]


def generate(model: str, system: str, prompt: str, timeout: int) -> dict:
    body = {
        "model": model, "system": system, "prompt": prompt, "stream": False,
        # Deterministic: a benchmark whose score moves between runs measures the
        # sampler, not the model.
        "options": {"temperature": 0, "seed": 1},
    }
    req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"},
                                 method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"error": str(exc)[:120], "seconds": time.monotonic() - started}
    return {
        "text": data.get("response", ""),
        "tokens": (data.get("prompt_eval_count", 0) or 0) + (data.get("eval_count", 0) or 0),
        "eval_tokens": data.get("eval_count", 0) or 0,
        "seconds": time.monotonic() - started,
    }


def _llama_server_bin() -> str:
    for path in LLAMA_SERVER_CANDIDATES:
        if os.access(path, os.X_OK):
            return path
    _die("no llama-server found. It ships inside the Homebrew ollama formula "
         f"(looked in: {', '.join(LLAMA_SERVER_CANDIDATES)}). Without it there "
         "is no grammar-constrained path — and Ollama's API silently drops a "
         "grammar, so there is no fallback that would be honest.")


def _gguf_for(model: str) -> str:
    """Resolve an ollama model name to the GGUF blob llama-server loads.

    Ollama stores plain GGUF under blobs/ and names it in the manifest, so this
    reads rather than converts. `hermes3:8b` -> manifests/hermes3/8b.
    """
    name, _, tag = model.partition(":")
    manifest = OLLAMA_MANIFESTS / name / (tag or "latest")
    if not manifest.exists():
        _die(f"no ollama manifest at {manifest} — is {model} pulled?")
    layers = json.loads(manifest.read_text(encoding="utf-8")).get("layers", [])
    for layer in layers:
        if "model" in layer.get("mediaType", ""):
            blob = OLLAMA_BLOBS / layer["digest"].replace("sha256:", "sha256-")
            if not blob.exists():
                _die(f"manifest names a blob that is not there: {blob}")
            return str(blob)
    _die(f"{model}'s manifest declares no model layer")


class GrammarServer:
    """A llama-server bound to state/cortex-lang.gbnf, for one model.

    It refuses to start if the grammar does not parse, which is the property
    that makes this path honest: an unusable grammar is a startup failure here,
    where Ollama would have accepted the run and constrained nothing.
    """

    def __init__(self, model: str, port: int = 8121, ctx: int = 2048):
        self.model, self.port, self.ctx = model, port, ctx
        self.proc: subprocess.Popen | None = None
        self.log = tempfile.NamedTemporaryFile(
            prefix="llama-server-", suffix=".log", delete=False, mode="w+")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "GrammarServer":
        self.proc = subprocess.Popen(
            [_llama_server_bin(), "-m", _gguf_for(self.model),
             "--host", "127.0.0.1", "--port", str(self.port),
             "-c", str(self.ctx), "-ngl", "99",
             "--grammar-file", str(GRAMMAR)],
            stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.log.seek(0)
                tail = "".join(self.log.readlines()[-6:]).strip()
                _die(f"llama-server exited before serving {self.model}.\n{tail}")
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=2) as resp:
                    if json.loads(resp.read()).get("status") == "ok":
                        return self
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                time.sleep(2)
        self.__exit__(None, None, None)
        _die(f"llama-server never became healthy for {self.model}")

    def __exit__(self, *_exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def generate(self, system: str, prompt: str, timeout: int) -> dict:
        # ChatML, because every candidate in state/local-model-bench.yml uses it.
        body = {
            "prompt": (f"<|im_start|>system\n{system}<|im_end|>\n"
                       f"<|im_start|>user\n{prompt}<|im_end|>\n"
                       f"<|im_start|>assistant\n"),
            "temperature": 0, "seed": 1, "n_predict": 384,
        }
        req = urllib.request.Request(
            f"{self.url}/completion", data=json.dumps(body).encode(),
            headers={"content-type": "application/json"}, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"error": str(exc)[:120], "seconds": time.monotonic() - started}
        predicted = data.get("tokens_predicted", 0) or 0
        return {
            "text": data.get("content", ""),
            "tokens": (data.get("tokens_evaluated", 0) or 0) + predicted,
            "eval_tokens": predicted,
            "seconds": time.monotonic() - started,
        }


def first_chain(text: str) -> str:
    """The model was asked for one line. Take the first line that looks like a
    chain anyway — refusing to parse a fenced answer would score formatting, and
    formatting is a prompt problem, not a capability one."""
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if line.startswith("@") or "|" in line:
            return line
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def validate(chain: str, token: str) -> dict | None:
    """None means the judge could not answer — which is NOT a failing score.

    The first version of this exited when the validator timed out. It was right
    to refuse to score, and wrong about what it had found: the validator was
    timing out BECAUSE the model under test had taken the machine. Aborting
    threw away the measurement. Returning None keeps it, and `estate_latency`
    below reports it as the number it is.
    """
    req = urllib.request.Request(
        f"{KEAP}/agent/v1/validate", data=json.dumps({"source": chain}).encode(),
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read())["data"]
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def estate_latency(timeout: int = 25) -> float | None:
    """How long the knowledge API takes to say hello. None = it did not.

    THIS IS A FIRST-CLASS RESULT, not instrumentation. Measured 2026-08-08 on an
    M4 Max / 36 GB running 63 containers:

        qwen3:14b resident (14 GB, 100% GPU) -> /agent/v1/health TIMES OUT at 25s
        `ollama stop qwen3:14b`              -> 0.33s, then 0.09s, 0.06s

    `qwen3:14b` is `openclaw_model`, the estate's own default. So the default
    model does not merely slow the estate down, it makes the knowledge API
    unavailable while it is loaded — and no benchmark that only reports accuracy
    would ever say so. A model this box cannot host is not a candidate however
    well it scores.
    """
    started = time.monotonic()
    try:
        req = urllib.request.Request(f"{KEAP}/agent/v1/health")
        with urllib.request.urlopen(req, timeout=timeout):
            return time.monotonic() - started
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def main() -> int:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", action="append", help="repeatable; default: all installed")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--json", metavar="PATH", help="also write the raw results")
    ap.add_argument("--grammar", action="store_true",
                    help="constrain decoding with state/cortex-lang.gbnf via "
                         "llama-server (NOT ollama, which drops it silently)")
    args = ap.parse_args()

    if args.grammar and not GRAMMAR.exists():
        _die(f"--grammar asked for, and there is no grammar at {GRAMMAR}")

    if not TASKS.exists():
        _die(f"no task set at {TASKS}")
    spec = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    system, tasks = spec["system"], spec["tasks"]
    token = _keap_ro_token()

    models = args.model or installed_models()
    if not models:
        _die("no chat models installed — `ollama pull` one first")
    print(f"{len(models)} model(s) × {len(tasks)} task(s), judged by "
          f"{KEAP}/agent/v1/validate\n")

    idle = estate_latency()
    print(f"  estate baseline: /agent/v1/health "
          f"{'%.2fs' % idle if idle is not None else 'TIMEOUT'} with no model resident\n")

    results = []
    for model in models:
        rows, under_load = [], None
        # One server per model, torn down before the next: two resident sets on
        # a 36 GB box with ~50 containers is how the estate latency this file
        # measures gets ruined by the file measuring it.
        server = GrammarServer(model) if args.grammar else None
        with server if server else contextlib.nullcontext():
            for n, task in enumerate(tasks):
                gen = (server.generate(system, task["prompt"], args.timeout)
                       if server else
                       generate(model, system, task["prompt"], args.timeout))
                # Measured once, right after the first generation, when the
                # weights are certainly resident and the estate competes with
                # them.
                if n == 0:
                    under_load = estate_latency()
                if "error" in gen:
                    rows.append({"id": task["id"], "valid": False, "opcode_ok": False,
                                 "tokens": 0, "seconds": gen["seconds"],
                                 "error": gen["error"], "chain": ""})
                    continue
                chain = first_chain(gen["text"])
                verdict = validate(chain, token) if chain else {"valid": False}
                rows.append({
                    "id": task["id"],
                    "chain": chain[:120],
                    # An unreachable judge scores nothing. Marking it False would
                    # blame the model for taking the machine, which is a separate
                    # finding with its own column.
                    "valid": bool(verdict.get("valid")) if verdict is not None else None,
                    "opcode_ok": bool(re.search(rf"\b{re.escape(task['expect_opcode'])}\s*\(", chain)),
                    "tokens": gen["tokens"],
                    "eval_tokens": gen["eval_tokens"],
                    "seconds": round(gen["seconds"], 1),
                    "errors": ([e.get("code") for e in (verdict.get("errors") or [])][:2]
                               if verdict is not None else ["judge-unreachable"]),
                })

        ok = sum(1 for r in rows if r["valid"] is True)
        both = sum(1 for r in rows if r["valid"] is True and r["opcode_ok"])
        unjudged = sum(1 for r in rows if r["valid"] is None)
        toks = sum(r["tokens"] for r in rows)
        secs = sum(r["seconds"] for r in rows)
        lat = ("TIMEOUT" if under_load is None else f"{under_load:.2f}s")
        print(f"  {model}")
        print(f"    valid {ok}/{len(rows)} · valid AND asked-for opcode {both}/{len(rows)}"
              f" · {toks} tokens · {secs:.0f}s · estate while resident: {lat}")
        if unjudged:
            print(f"    {unjudged} task(s) unscored — the judge could not answer "
                  "while this model held the machine")
        for r in rows:
            mark = ("unscored" if r["valid"] is None else
                    "ok  " if r["valid"] and r["opcode_ok"] else
                    "VALID-but-wrong-op" if r["valid"] else "fail")
            detail = r.get("error") or ", ".join(filter(None, r.get("errors") or []))
            print(f"      {mark:<19} {r['id']:<18} {r['chain'][:56]}"
                  + (f"   [{detail}]" if detail else ""))
        print()
        results.append({"model": model, "rows": rows, "valid": ok,
                        "valid_and_intended": both, "unscored": unjudged,
                        "tokens": toks, "seconds": round(secs, 1),
                        "estate_latency_s": under_load})

    print("  model                      valid  intent  tokens   seconds   estate")
    for r in sorted(results, key=lambda r: (-r["valid_and_intended"], r["tokens"])):
        lat = "TIMEOUT" if r["estate_latency_s"] is None else f"{r['estate_latency_s']:.2f}s"
        print(f"  {r['model']:<26} {r['valid']:>2}/{len(tasks)}   "
              f"{r['valid_and_intended']:>2}/{len(tasks)}  {r['tokens']:>6}   "
              f"{r['seconds']:>7.0f}   {lat:>7}")
    print("\n  Ranked by intended-opcode hits, then by tokens spent. `estate` is what "
          "\n  the knowledge API answered in WHILE that model was resident — a TIMEOUT "
          "\n  there disqualifies a model on this host whatever else it scored.")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\n  raw results -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
