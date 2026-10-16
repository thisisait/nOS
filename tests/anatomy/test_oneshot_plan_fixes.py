"""tools/oneshot-poc.py fixes from the client run 2026-10-16 (qwen3.5:2b, MLX, unconstrained): 1/8 plans.

The trace: 56 triage answers missing (dotted keys), 1 for "1" on every count, instructions echoed as
answers, a JSONDecodeError ending a case, steps 2-3 never "done", list_tables refused as untyped.
"""

from __future__ import annotations

import json

from test_oneshot_systemone import _poc
from test_oneshot_unconstrained import ollama  # noqa: F401  (fixture)


def test_unconstrained_keys_are_flat_and_a_number_answers_its_label(ollama):  # noqa: F811
    poc = _poc()
    poc.FORMAT_MODE = "unconstrained"
    seen = []

    def reply(body):
        user = body["messages"][1]["content"]
        seen.append(body)
        assert "s1.where.n" not in user and "s1__where__n" in user, user
        return json.dumps({"sys__keap_table": "yes", "s1__where__n": 1})
    ollama.reply = reply
    body = {"model": "m", "state": "s", "questions": {
        "sys.keap_table": {"type": "noul", "instructions": "Does the request need keap table?"},
        "s1.where.n": {"type": "score", "instructions": "query_rows where.n: how many?",
                       "criteria": ["0", "1", "2"]}}}
    a = poc.ask_systemone(body, {"backend": "ollama", "model": "m"})["answers"]
    assert a["sys.keap_table"]["noul"] == 1.0, a
    assert a["s1.where.n"]["probabilities"]["1"] == 1.0, a
    assert '"sys__keap_table"' in seen[0]["messages"][0]["content"]  # an example of the shape


def test_a_reply_that_is_not_json_is_asked_once_more(ollama):  # noqa: F811
    poc = _poc()
    poc.FORMAT_MODE = "unconstrained"
    replies = iter(["{list_tables: yes}", '{"answer": "query_rows"}'])
    ollama.reply = lambda body: next(replies)
    qn = {"id": "s1.tool", "kind": "choice", "text": "which tool?", "options": ["query_rows", "done"]}
    assert poc.live_decider("qwen3.5:9b", "top 3")(qn) == "query_rows"
    assert "not valid JSON" in ollama.posts[-1]["messages"][-1]["content"]


def test_a_single_step_request_is_not_asked_for_a_second_step():
    poc, asked = _poc(), []
    answers = {"multi_step": False, "s1.tool": "list_tables"}

    def ask(qn):
        asked.append(qn["id"])
        return answers[qn["id"]] if qn["id"] in answers else False
    out = poc.build("list the tables", ask)
    assert out["plan"] == [{"tool": "list_tables", "args": {}}]
    assert "s2.tool" not in asked


def test_a_later_step_question_names_the_steps_so_far():
    poc, texts = _poc(), {}
    answers = {"multi_step": True, "s1.tool": "list_tables", "s2.tool": "done"}

    def ask(qn):
        texts[qn["id"]] = qn["text"]
        return answers.get(qn["id"], False)
    poc.build("r", ask)
    assert "list_tables" in texts["s2.tool"]
