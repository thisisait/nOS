"""tools/ears-asr-bench.py scores Czech ASR models on the operator's own recordings, offline here.

Roadmap row ears-whisper-cs-bench (2026-10-15): parakeet-tdt-0.6b-v3 (today's ear) vs whisper
large-v3-turbo (cs forced) vs Canary-1B-v2. The models run only on the operator's host; this gate pins
the scoring and the pipeline with an `echo` model that reads a sidecar transcript.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "ears-asr-bench.py"
CASES = yaml.safe_load((REPO / "state/fixtures/ears-asr-bench.yml").read_text(encoding="utf-8"))


def _bench():
    spec = importlib.util.spec_from_file_location("ears_asr_bench", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fixture_covers_each_kind_with_unique_ids():
    assert len(CASES) >= 30
    assert len({c["id"] for c in CASES}) == len(CASES)
    kinds = {c["kind"] for c in CASES}
    assert kinds == {"wake", "command", "general", "short"}, kinds


def test_wer_and_cer_on_czech_text():
    b = _bench()
    assert b.wer("Příliš žluťoučký kůň", "příliš žluťoučký kůň!") == 0.0, "case and punctuation are not errors"
    assert b.wer("a b c d", "a x c d") == 0.25
    assert b.wer("a b", "a b c d") == 1.0, "two insertions over two words"
    assert b.wer("kůň", "kun") == 1.0, "a lost diacritic is a wrong word"
    assert 0 < b.cer("kůň", "kun") < 1
    assert b.wer("", "") == 0.0


def test_the_wake_phrase_is_heard_or_not():
    b = _bench()
    phrases = ["hej jeffe", "hey jeff"]
    assert b.wake_heard("Hej, Jeffe, kolik máme řádků?", phrases)
    assert not b.wake_heard("Hey Jeff hmm", ["hej jeffe"])
    assert b.wake_heard("hey jeff", phrases)


def test_a_run_scores_every_recording_with_every_model(tmp_path):
    rec = tmp_path / "rec"
    rec.mkdir()
    for c in CASES[:3]:
        (rec / f"{c['id']}.wav").write_bytes(b"RIFF")
        # the echo model hears the sidecar; one word wrong on the second case
        heard = c["text"] if c is not CASES[1] else c["text"] + " navíc"
        (rec / f"{c['id']}.txt").write_text(heard, encoding="utf-8")
    out = tmp_path / "res.json"
    r = subprocess.run([sys.executable, str(TOOL), "--run", str(rec), "--model", "echo", "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    res = json.loads(out.read_text())
    m = res["models"]["echo"]
    assert m["clips"] == 3 and m["missing"] == len(CASES) - 3
    assert m["wer"] > 0 and m["per_kind"]["wake"]["wake_hit_rate"] == 1.0
    assert "seconds_per_clip" in m and "peak_rss_mb" in m


def test_recording_and_setup_refuse_without_the_operator():
    """--record stores the operator's voice and --setup installs models: both need NOS_LIVE=1."""
    for args in (["--record", "/tmp/x"], ["--setup"]):
        r = subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        assert r.returncode == 2, (args, r.stdout, r.stderr)
