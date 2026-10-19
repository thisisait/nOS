"""pazny.vllm keeps what the #60 review asked of it.

- no GPU is a FACT: the role ends with a message (refuses only with
  vllm_require_gpu), so a profile that turns every ai row on stays green;
- the weight fetch keeps its container until a reader saw how it ended;
- Open WebUI's lists are read null-safe (default(x, true) | list);
- the health-wait outlasts vLLM's start window;
- the pre-allocation is checked against available memory before start.
"""
from __future__ import annotations

import pathlib

import yaml

ROLE = pathlib.Path(__file__).resolve().parents[2] / "roles" / "pazny.vllm"


def _main() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def test_no_gpu_ends_the_role_instead_of_failing():
    tasks = _main()
    end = [t for t in tasks if t.get("ansible.builtin.meta") == "end_role"]
    assert end and "nvidia.com/gpu=all" in str(end[0]["when"])
    refuse = next(t for t in tasks if "refuse when required" in t.get("name", ""))
    assert "vllm_require_gpu" in str(refuse["when"])


def test_the_fetch_is_read_before_it_is_removed():
    run = next(t for t in _main() if "Fetch the pinned snapshot" in t.get("name", ""))
    assert "--rm" not in run["ansible.builtin.command"]["argv"]
    names = [t.get("name", "") for t in _main()]
    assert any("A failed fetch fails the converge" in n for n in names)


def test_open_webui_lists_are_null_safe():
    post = (ROLE / "tasks" / "post.yml").read_text()
    assert "OPENAI_API_BASE_URLS | default([], true) | list" in post


def test_the_wait_and_the_memory_are_checked():
    names = [t.get("name", "") for t in _main()]
    assert any("health-wait outlasts" in n for n in names)
    assert any("pre-allocation the host cannot fit" in n for n in names)
