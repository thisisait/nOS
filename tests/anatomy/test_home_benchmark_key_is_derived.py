"""The home benchmark's key is derived from the estate, and its scorer is not a rubber stamp.

WHY. "Every LLM feels at home" (roadmap row `home-benchmark`) is a claim until
code scores it. A key typed by hand would score the author's memory, not the
estate; a scorer that rewards any answer, or turns a dead backend into 0.0,
would write success itself. Tool: tools/home-benchmark.py; set:
state/home-benchmark.yml. Offline: no model is ever called here.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("home_benchmark", REPO / "tools/home-benchmark.py")
hb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hb)


def _answers(bench: dict, fill) -> dict:
    return {"status": "ok", "model": "fixture", "questions": [{"id": q["id"], "text": q["text"]}
                                                             for q in bench["questions"]],
            "answers": {q["id"]: fill(q) for q in bench["questions"]}}


def test_the_set_regenerates_deterministically() -> None:
    a, b = hb.build(), hb.build()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert len(a["questions"]) >= 30, f"only {len(a['questions'])} questions derived"
    assert len({q["family"] for q in a["questions"]}) >= 8


def test_every_key_is_nonempty_derived_and_not_spelled_anywhere() -> None:
    bench = hb.build()
    template = hb.SET.read_text(encoding="utf-8")
    for q in bench["questions"]:
        assert q["key"], f"{q['id']}: empty key"
        assert set(q["key"]) <= set(bench["universes"][q["family"]]), f"{q['id']}: key outside its universe"
        assert not hb.hits(template, q["key"]), f"{q['id']}: answer literal in {hb.SET.name}"
        assert not hb.hits(q["text"], q["key"]), f"{q['id']}: the question spells its own answer"


def test_the_key_scores_one_and_nothing_scores_zero() -> None:
    bench = hb.build()
    assert hb.score(_answers(bench, lambda q: ", ".join(q["key"])), bench)["score"] == 1.0
    assert hb.score(_answers(bench, lambda q: ""), bench)["score"] == 0.0
    # Phrasing is free; a path counts for the name it ends in.
    prose = hb.score(_answers(bench, lambda q: "It is `tools/" + "` and `".join(q["key"]) + "`."), bench)
    assert prose["score"] == 1.0
    # Naming every candidate is not knowing which one.
    shotgun = hb.score(_answers(bench, lambda q: ", ".join(bench["universes"][q["family"]])), bench)
    assert shotgun["score"] < 0.5, shotgun["families"]


def test_a_failing_backend_is_unavailable_never_a_number(tmp_path) -> None:
    bench = hb.build()
    ctx = tmp_path / "context.md"
    ctx.write_text("# a front door\n")

    def down(*_a):
        raise ConnectionRefusedError("fixture backend is down")

    for rec in (hb.ask(bench, ctx, "ollama:fixture", call=down),
                hb.ask(bench, ctx, "ollama:fixture", call=lambda *_a: {"text": "I am not sure."}),
                hb.ask(bench, ctx, "no-such-backend:x")):
        assert rec["status"] == "UNAVAILABLE", rec
        assert rec["context"]["tokens_est"] >= 1
        res = hb.score(rec, bench)
        assert res["status"] == "UNAVAILABLE" and "score" not in res, res


def test_a_saved_run_is_scored_without_a_model_and_staleness_refuses(tmp_path) -> None:
    bench = hb.build()
    ctx = tmp_path / "context.md"
    ctx.write_text("x" * 400)
    reply = "\n".join(f"Q{n:02d}: {', '.join(q['key'])}" for n, q in enumerate(bench["questions"], 1))
    rec = hb.ask(bench, ctx, "ollama:fixture", call=lambda *_a: {"text": reply, "tokens": 123})
    assert rec["status"] == "ok" and rec["context"]["tokens_est"] == 100
    saved = tmp_path / "answers.json"
    saved.write_text(json.dumps(rec))
    hb.BACKENDS.clear()  # scoring must not need one
    try:
        assert hb.main(["score", str(saved)]) == 0
    finally:
        hb.BACKENDS["ollama"] = hb._ollama_call
    rec["questions"][0]["text"] += " (changed)"
    assert hb.score(rec, bench)["status"] == "STALE"
