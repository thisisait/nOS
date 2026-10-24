"""How do I do X with nOS: tools/nos-guide.py, Iris's nos_guide (operator 2026-10-15).

Deterministic retrieval over the repo's docs (split by heading, ranked by token
overlap, Czech folded to ASCII with a small synonym map) plus, when the question
names a manifest service, the steps derived from the repo: the config.yml line,
the converge tag read from the include_role that runs under its install flag
(never a hand list), and the verify command. Iris never runs them; the person does.
A source it cannot read is named in `unknown`, never an empty answer.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "nos-guide.py"
sys.path.insert(0, str(REPO / "tools"))
import nos_identity  # noqa: E402

_spec = importlib.util.spec_from_file_location("_nos_guide", TOOL)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


def _w(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


STACK_UP = """\
- { name: n8n render, ansible.builtin.include_role: { name: pazny.n8n, apply: { tags: ['automation-n8n'] } },
    when: "install_n8n | default(false)", tags: ['automation-n8n'] }
- { name: kuma render, ansible.builtin.include_role: { name: pazny.uptime_kuma, apply: { tags: ['uptime-kuma'] } },
    when: "install_uptime_kuma | default(false)", tags: ['uptime-kuma'] }
"""


@pytest.fixture
def estate(tmp_path, monkeypatch):
    _w(tmp_path, "state/manifest.yml",
       "services:\n"
       "  - {id: n8n, category: automation, install_flag: install_n8n}\n"
       "  - {id: uptime_kuma, category: observability, install_flag: install_uptime_kuma}\n")
    monkeypatch.setattr(nos_identity, "REPO", tmp_path)
    monkeypatch.setattr(nos_identity, "MANIFEST", tmp_path / "state/manifest.yml")
    nos_identity.default_layers()[-1].write_text("install_n8n: false\ninstall_uptime_kuma: false\n", encoding="utf-8")
    _w(tmp_path, "config.yml", "install_uptime_kuma: true\n")
    _w(tmp_path, "main.yml", "- hosts: all\n  tasks:\n    - import_tasks: tasks/stacks/stack-up.yml\n")
    _w(tmp_path, "tasks/stacks/stack-up.yml", STACK_UP)
    _w(tmp_path, "docs/systems/n8n/README.md",
       "# n8n\n\nWorkflow automation.\n\n## Quick Reference\n\nEnable it with `install_n8n: true` in config.yml.\n\n"
       "```bash\n# a comment in a code block is not a heading\nnos --tags n8n\n```\n\n## Health Check\n\ncurl the healthz.\n")
    _w(tmp_path, "docs/systems/uptime-kuma/README.md", "# Uptime Kuma\n\n## Monitors\n\nStatus pages.\n")
    _w(tmp_path, "docs/nos-cli.md",
       "# nos CLI\n\nThe operator entry point.\n\n## Update nOS (pull, then converge)\n\n"
       "```bash\ncd \"$NOS_SRC\" && git pull\nnos\n```\n\n## The ladder\n\nremove=data wipes data.\n")
    _w(tmp_path, "README.md", "# nOS\n\nA home lab.\n\n## Install\n\nRun the playbook once by hand.\n")
    _w(tmp_path, "docs/glossary.md", "# Glossary\n\n## organ\n\nA part with one job.\n")
    _w(tmp_path, "profiles/core.yml",
       "# ====\n# profiles/core.yml — the smallest working nOS\n#\n# plain: desktop, assistant and memory behind SSO.\n# ====\ninstall_face: true\n")
    return tmp_path


def _paths(out):
    return [(p["path"], p["heading"]) for p in out["passages"]]


def test_enabling_a_service_ranks_its_doc_first(estate):
    out = G.collect("How do I turn on n8n?")
    assert _paths(out)[0][0] == "docs/systems/n8n/README.md", out
    assert len(out["passages"]) <= 3 and all(len(p["text"]) <= 1200 for p in out["passages"])
    assert out["unknown"] == []


def test_czech_is_folded_and_its_verbs_are_synonyms(estate):
    assert {"zapni", "enable", "install", "sluzbu"} <= set(G.tokens("Zapni službu"))
    assert {"update", "upgrade"} <= set(G.tokens("aktualizuj"))
    assert {"disable"} <= set(G.tokens("vypni"))
    top = _paths(G.collect("aktualizuj nOS"))[0]
    assert top == ("docs/nos-cli.md", "Update nOS (pull, then converge)"), top
    assert _paths(G.collect("Jak zapnu n8n?"))[0][0] == "docs/systems/n8n/README.md"


def test_a_heading_inside_a_code_block_does_not_split(estate):
    q = [p for p in G.collect("enable n8n quick reference")["passages"] if p["heading"] == "Quick Reference"]
    assert q and "nos --tags n8n" in q[0]["text"], q


def test_a_profile_header_is_a_passage(estate):
    assert _paths(G.collect("the smallest working nOS profile"))[0][0] == "profiles/core.yml"


def test_the_service_block_is_derived_from_manifest_config_and_main(estate):
    s = G.collect("zapni n8n")["service"]
    assert s == {"id": "n8n", "install_flag": "install_n8n", "enabled": False,
                 "config_line": "install_n8n: true", "converge": "nos --tags automation-n8n",
                 "verify": "nos --tags automation-n8n,verify"}, s
    k = G.collect("vypni uptime kuma")["service"]
    assert (k["id"], k["enabled"], k["config_line"], k["converge"]) == \
        ("uptime_kuma", True, "install_uptime_kuma: false", "nos --tags uptime-kuma"), k


def test_the_tag_follows_the_include_not_a_list(estate):
    _w(estate, "tasks/stacks/stack-up.yml", STACK_UP.replace("automation-n8n", "renamed"))
    assert G.collect("enable n8n")["service"]["converge"] == "nos --tags renamed"


def test_no_service_named_means_no_service_block(estate):
    assert G.collect("aktualizuj nOS")["service"] is None


def test_an_unreadable_doc_is_named_in_unknown_and_the_rest_still_answers(estate):
    (estate / "docs/glossary.md").write_bytes(b"\xff\xfe not utf-8")
    out = G.collect("turn on n8n")
    assert "docs/glossary.md" in out["unknown"], out
    assert _paths(out)[0][0] == "docs/systems/n8n/README.md"


def test_a_missing_manifest_is_unknown_not_silently_no_service(estate):
    (estate / "state/manifest.yml").unlink()
    out = G.collect("turn on n8n")
    assert out["service"] is None and "state/manifest.yml" in out["unknown"], out


def test_the_cli_exits_0_with_json_on_the_real_repo():
    def run(q):
        got = subprocess.run([sys.executable, str(TOOL), "--json", q], capture_output=True, text=True, timeout=60)
        assert got.returncode == 0, got.stderr
        return json.loads(got.stdout)
    out = run("turn on n8n")
    assert set(out) == {"question", "passages", "service", "unknown"}
    assert out["service"]["converge"] == "nos --tags n8n" and out["service"]["config_line"] == "install_n8n: true"
    up = run("aktualizuj nOS")
    assert any(p["path"] == "docs/nos-cli.md" and "nos update" in p["text"] for p in up["passages"]), up
