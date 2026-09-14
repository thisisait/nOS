"""S7 — mcp Grafana SA token is minted once, not every converge.

p=54800: post.yml always POSTed a new epoch-named token, sed'd UPDATED, then
restarted mcp-grafana (~27s verify). Persist the key and render it before
compose-up; mint only when the file is missing.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MAIN = REPO / "roles" / "pazny.mcp_gateway" / "tasks" / "main.yml"
POST = REPO / "roles" / "pazny.mcp_gateway" / "tasks" / "post.yml"


def _walk(tasks):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for key in ("block", "rescue", "always"):
            yield from _walk(t.get(key))


def _name(t: dict) -> str:
    return str(t.get("name", ""))


def _when(t: dict) -> str:
    w = t.get("when")
    if w is None:
        return ""
    if isinstance(w, list):
        return " && ".join(str(x) for x in w)
    return str(w)


def test_main_reads_persisted_token_before_compose_render():
    tasks = list(_walk(yaml.safe_load(MAIN.read_text(encoding="utf-8"))))
    slurp_i = next(
        (i for i, t in enumerate(tasks) if "Read the persisted Grafana SA token" in _name(t)),
        -1,
    )
    render_i = next(
        (i for i, t in enumerate(tasks) if "Render compose override fragment" in _name(t)),
        -1,
    )
    assert slurp_i >= 0, f"{MAIN}: must slurp .grafana_sa_token before rendering"
    assert render_i > slurp_i, (
        f"{MAIN}: compose render is task {render_i}, token slurp is {slurp_i} — "
        "placeholder-then-sed was the 27s restart"
    )


def test_main_slurp_does_not_run_when_the_file_is_missing():
    tasks = list(_walk(yaml.safe_load(MAIN.read_text(encoding="utf-8"))))
    slurp = next(t for t in tasks if "Read the persisted Grafana SA token" in _name(t))
    when = _when(slurp)
    assert "exists" in when, f"{MAIN}: slurp must be gated on the persist file; when={when}"
    assert "default({})" in when, (
        f"{MAIN}: skipped stat has no .stat; bare .stat.exists | default(false) "
        f"fails the role when grafana is off or the file is missing: {when}"
    )


def test_post_does_not_mint_when_the_file_exists():
    tasks = list(_walk(yaml.safe_load(POST.read_text(encoding="utf-8"))))
    mint = next(t for t in tasks if "Create Grafana SA token for mcpo" in _name(t))
    when = _when(mint)
    assert "not" in when and "exists" in when and "_mcp_grafana_tok_stat.stat" in when, (
        f"{POST}: mint must skip when .grafana_sa_token exists; when={when}"
    )
    body = mint.get("ansible.builtin.uri") or mint.get("uri") or {}
    name = ((body.get("body") or {}).get("name") or "")
    assert "epoch" not in str(name), (
        f"token name still includes epoch — that is one Grafana token per converge: {name}"
    )


def test_post_deletes_named_token_before_remint():
    tasks = list(_walk(yaml.safe_load(POST.read_text(encoding="utf-8"))))
    names = [_name(t) for t in tasks]
    drop_i = next(i for i, n in enumerate(names) if "mcpo-token" in n and "Drop" in n)
    mint_i = next(i for i, n in enumerate(names) if "Create Grafana SA token for mcpo" in n)
    assert drop_i < mint_i, "409: leftover mcpo-token must be deleted before POST"
    drop = tasks[drop_i]
    uri = drop.get("ansible.builtin.uri") or drop.get("uri") or {}
    assert str(uri.get("method", "")).upper() == "DELETE"
    assert "mcpo-token" in _when(drop)


def test_post_when_clauses_survive_a_skipped_mint():
    tasks = list(_walk(yaml.safe_load(POST.read_text(encoding="utf-8"))))
    persist = next(t for t in tasks if "Persist Grafana SA token" in _name(t))
    when = _when(persist)
    assert "is not skipped" in when, (
        f"{POST}: `_grafana_token.json.key is defined` errors when mint is skipped; when={when}"
    )
    assert "json.key is defined" not in when
    rerender = next(t for t in tasks if "Re-render compose override" in _name(t))
    rwhen = _when(rerender)
    assert "is not skipped" in rwhen
    assert "is changed" in rwhen


def test_post_does_not_sed_updated_every_run():
    text = POST.read_text(encoding="utf-8")
    assert "echo \"UPDATED\"" not in text
    assert "_mcpo_token_update" not in text
