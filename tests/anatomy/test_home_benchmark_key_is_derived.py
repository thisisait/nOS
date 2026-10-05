"""The home benchmark's key is derived from the estate, and its scorer is not a rubber stamp.

WHY. "Every LLM feels at home" (roadmap row `home-benchmark`) is a claim until
code scores it. A key typed by hand scores the author's memory; a scorer that
rewards any answer, turns a dead backend into 0.0, or reports a score without
the no-context control writes success itself. Tool: tools/home-benchmark.py;
set: state/home-benchmark.yml. Offline: no model is ever called here.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import math
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("home_benchmark", REPO / "tools/home-benchmark.py")
hb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hb)


def _record(bench: dict, fill, control: bool = False) -> dict:
    return {"status": "ok", "model": "fixture", "context": {"control": control},
            "questions": [{"id": q["id"], "text": q["text"]} for q in bench["questions"]],
            "answers": {q["id"]: fill(q) for q in bench["questions"]}}


def _first(q) -> str:
    return ", ".join(slot[0] for slot in q["key"])


def test_the_set_regenerates_deterministically() -> None:
    a, b = hb.build(), hb.build()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert len(a["questions"]) >= 50, f"only {len(a['questions'])} questions derived"
    assert len({q["family"] for q in a["questions"]}) >= 8


def test_every_key_is_nonempty_derived_and_not_spelled_anywhere() -> None:
    bench = hb.build()
    template = hb.SET.read_text(encoding="utf-8")
    for q in bench["questions"]:
        names = {n for slot in q["key"] for n in slot}
        assert q["key"] and all(q["key"]), f"{q['id']}: empty key"
        assert names <= set(bench["universes"][q["family"]]), f"{q['id']}: key outside its universe"
        assert not hb.hits(template, names), f"{q['id']}: answer literal in {hb.SET.name}"
        assert not hb.hits(q["text"], names), f"{q['id']}: the question spells its own answer"
        assert not hb.shared_stems(q["fill"], names, bench["common"][q["family"]]), (
            f"{q['id']}: the question's wording gives the key away")


def test_sampling_spreads_the_keys() -> None:
    """A family whose sample is mostly one name is answerable by guessing that name."""
    bench = hb.build()
    for fam, s in bench["spread"].items():
        assert s["sample_top"] <= max(1, math.ceil(s["pool_top_share"] * s["asked"])), (fam, s)
    single = collections.Counter((q["family"], tuple(q["key"][0])) for q in bench["questions"] if len(q["key"]) == 1)
    assert max(single.values()) <= hb.REPEAT, single.most_common(3)


def test_the_key_scores_one_and_nothing_scores_zero() -> None:
    bench = hb.build()
    assert hb.score(_record(bench, _first), bench)["score"] == 1.0
    assert hb.score(_record(bench, lambda q: ""), bench)["score"] == 0.0
    # A path counts for the name it ends in.
    path = hb.score(_record(bench, lambda q: ", ".join(f"`tools/{s[0]}`" for s in q["key"])), bench)
    assert path["score"] == 1.0
    # Prose is not an identifier line: it is a format failure, scored 0, never scanned for words.
    prose = hb.score(_record(bench, lambda q: "I think it is " + " and ".join(s[0] for s in q["key"])), bench)
    assert prose["score"] == 0.0 and prose["unparsed"] == len(bench["questions"])
    # Naming every candidate is not knowing which one.
    shotgun = hb.score(_record(bench, lambda q: ", ".join(bench["universes"][q["family"]])), bench)
    assert shotgun["score"] < 0.5, shotgun["families"]


def test_either_copy_of_a_duplicated_doctrine_is_the_full_answer() -> None:
    bench = hb.build()
    dup = [q for q in bench["questions"] if any(len(slot) > 1 for slot in q["key"])]
    assert dup, "no alternative keys derived: the either-copy rule is unexercised"
    res = hb.score(_record(bench, lambda q: ", ".join(slot[-1] for slot in q["key"])), bench)
    both = hb.score(_record(bench, lambda q: ", ".join(n for slot in q["key"] for n in slot)), bench)
    for q in dup:
        assert next(r for r in res["questions"] if r["id"] == q["id"])["score"] == 1.0
        assert next(r for r in both["questions"] if r["id"] == q["id"])["score"] == 1.0


def test_lift_is_measured_against_the_control(tmp_path) -> None:
    bench = hb.build()
    easy = bench["questions"][0]["family"]
    run = _record(bench, _first)
    control = _record(bench, lambda q: _first(q) if q["family"] == easy else "", control=True)
    res = hb.score(run, bench, control=control)
    assert res["status"] == "ok"
    assert abs(res["lift"][easy]) < 1e-9, f"control already answers {easy}: lift must be ~0, got {res['lift']}"
    other = next(f for f in res["families"] if f != easy)
    want = res["families"][other] - res["control"]["families"][other]
    assert abs(res["lift"][other] - want) < 1e-6 and want > 0, res["lift"]
    # A run with context is not a control.
    assert hb.score(run, bench, control=run)["status"] == "UNAVAILABLE"


def test_a_failing_backend_is_unavailable_and_a_bad_format_is_a_low_score(tmp_path) -> None:
    bench = hb.build()
    ctx = tmp_path / "context.md"
    ctx.write_text("# a front door\n")

    def down(*_a):
        raise ConnectionRefusedError("fixture backend is down")

    for rec in (hb.ask(bench, ctx, "ollama:fixture", call=down), hb.ask(bench, ctx, "no-such-backend:x")):
        assert rec["status"] == "UNAVAILABLE", rec
        res = hb.score(rec, bench)
        assert res["status"] == "UNAVAILABLE" and "score" not in res, res
    # The model WAS asked and answered badly: that is a result, recorded low.
    rec = hb.ask(bench, ctx, "ollama:fixture", call=lambda *_a: {"text": "I am not sure."})
    assert rec["status"] == "ok" and rec["parsed"] == 0
    res = hb.score(rec, bench)
    assert res["status"] == "ok" and res["score"] == 0.0 and res["unparsed"] == len(bench["questions"])
    assert hb.exit_code(rec) == 1 and hb.exit_code({"status": "UNAVAILABLE"}) == 2


def test_a_saved_run_is_scored_without_a_model_and_staleness_refuses(tmp_path) -> None:
    bench = hb.build()
    ctx = tmp_path / "context.md"
    ctx.write_text("x" * 400)
    reply = "\n".join(f"Q{n:02d}: {_first(q)}" for n, q in enumerate(bench["questions"], 1))
    rec = hb.ask(bench, ctx, "ollama:fixture", call=lambda *_a: {"text": reply, "tokens": 123})
    assert rec["status"] == "ok" and rec["context"]["tokens_est"] == 100 and hb.exit_code(rec) == 0
    ctl = hb.ask(bench, None, "ollama:fixture", call=lambda *_a: {"text": "Q01: unknown"})
    assert ctl["context"]["control"] is True and ctl["context"]["tokens_est"] == 0
    saved, saved_ctl = tmp_path / "answers.json", tmp_path / "control.json"
    saved.write_text(json.dumps(rec))
    saved_ctl.write_text(json.dumps(ctl))
    hb.BACKENDS.clear()  # scoring must not need one
    try:
        assert hb.main(["score", str(saved), "--control", str(saved_ctl)]) == 0
    finally:
        hb.BACKENDS["ollama"] = hb._ollama_call
    rec["questions"][0]["text"] += " (changed)"
    assert hb.score(rec, bench)["status"] == "STALE"
    assert collections.Counter(q["family"] for q in bench["questions"])  # families recorded per question
