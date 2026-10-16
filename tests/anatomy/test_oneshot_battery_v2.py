"""tools/oneshot-poc.py battery v2, from the same failures under qwen3.5:9b and vllm-d3-mini (2026-10-16).

Both picked offer_dashboard for every chart, KPI and choice (show's offered description named none
of them), never chose "done" among 15 tools, and answered "how many?" with duplicated conditions.
nos-assay runs/2026-10-16-h1-oneshot-9b and -d3mini hold the traces.
"""

from __future__ import annotations

from test_oneshot_systemone import _poc


def _ask(answers, asked):
    def ask(qn):
        k = qn["id"] + qn.get("id_suffix", "")
        asked.append((k, qn["kind"], qn["text"]))
        return answers.get(k, False if qn["kind"] == "yesno" else None)
    return ask


def test_show_is_offered_with_its_component_kinds():
    poc = _poc()
    q = poc.to_systemone({"id": "s1.tool", "kind": "choice", "text": "t", "options": list(poc.SCHEMAS) + ["done"]})
    assert all(k in q["criteria"]["show"] for k in ("chart", "kpi", "choice")), q["criteria"]["show"]


def test_a_later_step_is_a_yes_no_question_first():
    poc, asked = _poc(), []
    poc.build("r", _ask({"multi_step": True, "s1.tool": "list_tables", "s2.more": False}, asked))
    ids = [a[0] for a in asked]
    assert "s2.more" in ids and "s2.tool" not in ids
    more = next(a for a in asked if a[0] == "s2.more")
    assert more[1] == "yesno" and "list_tables" in more[2]


def test_a_list_grows_one_yes_at_a_time():
    poc, asked = _poc(), []
    answers = {"multi_step": False, "s1.tool": "query_rows", "s1.table": "iris-bench-2",
               "s1.where.0.add": True, "s1.where.0.column": "status", "s1.where.0.op": "eq",
               "s1.where.0.value": "next", "s1.where.1.add": False}
    out = poc.build("r", _ask(answers, asked))
    ids = [a[0] for a in asked]
    assert not any(i.endswith(".n") for i in ids), [i for i in ids if i.endswith(".n")]
    assert out["plan"][0]["args"]["where"] == [{"column": "status", "op": "eq", "value": "next"}]
    assert "s1.where.2.add" not in ids
