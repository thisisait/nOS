#!/usr/bin/env python3
"""Score Czech ASR models on the operator's own voice: WER/CER, wake-phrase hits, latency, peak RSS.

Roadmap row ears-whisper-cs-bench (2026-10-15). The ear today is parakeet-tdt-0.6b-v3; its rivals are
whisper large-v3-turbo with Czech forced and Canary-1B-v2 (FLEURS cs WER 7.9 % vs 11.0 %). Measure
before switching ears_asr_model: the result file is the reader, nothing here changes the ear.

    tools/ears-asr-bench.py --setup                   # NOS_LIVE=1: a venv with the three models' libs
    tools/ears-asr-bench.py --record ~/ears-bench/rec  # NOS_LIVE=1: read each prompt aloud, once
    tools/ears-asr-bench.py --run ~/ears-bench/rec [--model parakeet --model whisper-turbo --model canary]

Recording stores the operator's voice (the ear itself never does), so it is opt-in, kept outside the
repo, and the prompts are fixed (state/fixtures/ears-asr-bench.yml). Each model runs in its own worker
process, so peak RSS is that model's alone.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import resource
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "state" / "fixtures" / "ears-asr-bench.yml"
HOME = Path.home()
VENV = HOME / "ears-bench" / "venv"
LISTENER_ENV = HOME / "ears" / "listener.env"
SECONDS = {"short": 3, "wake": 4, "command": 6, "general": 8}
MODELS = {
    "parakeet": "mlx-community/parakeet-tdt-0.6b-v3",
    "whisper-turbo": "mlx-community/whisper-large-v3-turbo",
    "canary": "mlx-community/canary-1b-v2",
    "echo": "",  # offline gate: reads <id>.txt beside the wav
}
DEFAULT_MODELS = ["parakeet", "whisper-turbo", "canary"]
PIP = ["parakeet-mlx", "mlx-whisper", "mlx-audio", "pyyaml"]


def _words(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s.lower())
    return re.findall(r"[^\W_]+", s)


def _lev(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r, h = _words(ref), _words(hyp)
    return 0.0 if not r and not h else _lev(r, h) / max(len(r), 1)


def cer(ref: str, hyp: str) -> float:
    r, h = " ".join(_words(ref)), " ".join(_words(hyp))
    return 0.0 if not r and not h else _lev(list(r), list(h)) / max(len(r), 1)


def wake_heard(text: str, phrases: list[str]) -> bool:
    said = " ".join(_words(text))
    return any(" ".join(_words(p)) in said for p in phrases)


def _listener_env() -> dict:
    out = {}
    if LISTENER_ENV.exists():
        for line in LISTENER_ENV.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def _cases() -> list[dict]:
    return yaml.safe_load(CASES.read_text(encoding="utf-8"))


def cmd_setup() -> int:
    VENV.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    subprocess.run([str(VENV / "bin" / "pip"), "install", "-q", "--upgrade", *PIP], check=True)
    print(f"bench venv ready: {VENV}")
    return 0


def cmd_record(dest: Path, only: str | None) -> int:
    env = _listener_env()
    spec, gain = env.get("EARS_INPUT", ":0"), env.get("EARS_INPUT_GAIN", "1.0")
    dest.mkdir(parents=True, exist_ok=True)
    for c in _cases():
        if only and c["id"] != only:
            continue
        secs = SECONDS[c["kind"]]
        input(f"\n[{c['id']}] read aloud ({secs}s): «{c['text']}»  — Enter to start ")
        wav = dest / f"{c['id']}.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "avfoundation", "-i", spec,
                        "-af", f"volume={gain}", "-ac", "1", "-ar", "16000", "-t", str(secs), str(wav)], check=True)
        print(f"  saved {wav.name}")
    return 0


def _transcribe_all(model: str, wavs: list[Path]) -> dict:
    """Runs inside the worker: load the model once, time each clip."""
    repo = MODELS[model]
    if model == "parakeet":
        from parakeet_mlx import from_pretrained
        m = from_pretrained(repo)
        run = lambda p: m.transcribe(str(p)).text  # noqa: E731
    elif model == "whisper-turbo":
        import mlx_whisper
        run = lambda p: mlx_whisper.transcribe(str(p), path_or_hf_repo=repo, language="cs")["text"]  # noqa: E731
    elif model == "canary":
        # ponytail: mlx-audio's STT API is unverified on this host; a failure is reported per model, not fatal.
        from mlx_audio.stt.utils import load_model
        m = load_model(repo)
        run = lambda p: getattr(m.generate(str(p), language="cs"), "text", "")  # noqa: E731
    else:
        run = lambda p: p.with_suffix(".txt").read_text(encoding="utf-8")  # noqa: E731
    out = {}
    for w in wavs:
        t0 = time.monotonic()
        text = run(w)
        out[w.stem] = {"text": text, "seconds": round(time.monotonic() - t0, 3)}
    return out


def cmd_worker(model: str, rec: Path) -> int:
    wavs = sorted(rec.glob("*.wav"))
    res = _transcribe_all(model, wavs)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
    print(json.dumps({"clips": res, "peak_rss_mb": round(rss_mb, 1)}))
    return 0


def score(model: str, worker: dict, cases: list[dict], phrases: list[str]) -> dict:
    by_id = {c["id"]: c for c in cases}
    heard = worker["clips"]
    rows, per_kind = [], {}
    for cid, h in heard.items():
        c = by_id.get(cid)
        if not c:
            continue
        row = {"id": cid, "kind": c["kind"], "wer": wer(c["text"], h["text"]), "cer": cer(c["text"], h["text"]),
               "seconds": h["seconds"], "heard": h["text"]}
        if c["kind"] == "wake":
            row["wake"] = wake_heard(h["text"], phrases)
        rows.append(row)
        per_kind.setdefault(c["kind"], []).append(row)
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    kinds = {k: {"wer": mean([r["wer"] for r in rs]), "cer": mean([r["cer"] for r in rs]),
                 **({"wake_hit_rate": mean([1.0 if r["wake"] else 0.0 for r in rs])} if k == "wake" else {})}
             for k, rs in per_kind.items()}
    return {"repo": MODELS[model], "clips": len(rows), "missing": len(cases) - len(rows),
            "wer": mean([r["wer"] for r in rows]), "cer": mean([r["cer"] for r in rows]),
            "seconds_per_clip": mean([r["seconds"] for r in rows]), "peak_rss_mb": worker["peak_rss_mb"],
            "per_kind": kinds, "rows": rows}


def cmd_run(rec: Path, models: list[str], out: Path, python: str) -> int:
    cases = _cases()
    phrases = [p.strip() for p in _listener_env().get("EARS_WAKE_PHRASE", "hej jeffe").split(",") if p.strip()]
    result = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "recordings": str(rec), "models": {}}
    for m in models:
        py = sys.executable if m == "echo" else python
        p = subprocess.run([py, __file__, "--worker", m, str(rec)], capture_output=True, text=True)
        if p.returncode != 0:
            result["models"][m] = {"error": (p.stderr.strip().splitlines() or ["worker failed"])[-1][:400]}
            print(f"{m:<14} ERROR {result['models'][m]['error']}")
            continue
        s = score(m, json.loads(p.stdout.strip().splitlines()[-1]), cases, phrases)
        result["models"][m] = s
        wake = s["per_kind"].get("wake", {}).get("wake_hit_rate")
        print(f"{m:<14} WER {s['wer']:.3f}  CER {s['cer']:.3f}  wake {wake}  {s['seconds_per_clip']}s/clip  "
              f"{s['peak_rss_mb']} MB  ({s['clips']} clips, {s['missing']} missing)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"→ {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--record", type=Path)
    ap.add_argument("--only", help="re-record one prompt id")
    ap.add_argument("--run", type=Path)
    ap.add_argument("--model", action="append", choices=sorted(MODELS))
    ap.add_argument("--out", type=Path, default=HOME / "ears-bench" / "last-run.json")
    ap.add_argument("--python", default=str(VENV / "bin" / "python"))
    ap.add_argument("--worker", nargs=2, metavar=("MODEL", "DIR"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.worker:
        return cmd_worker(a.worker[0], Path(a.worker[1]))
    if (a.setup or a.record) and os.environ.get("NOS_LIVE") != "1":
        print("--setup installs models and --record stores your voice; set NOS_LIVE=1.", file=sys.stderr)
        return 2
    if a.setup:
        return cmd_setup()
    if a.record:
        return cmd_record(a.record.expanduser(), a.only)
    if a.run:
        return cmd_run(a.run.expanduser(), a.model or DEFAULT_MODELS, a.out.expanduser(), a.python)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
