"""Anatomy gate — tfstate + ansible.log stay 0600 across a converge.

Live disk was chmod'd 2026-09-13; OpenTofu apply rewrites
``terraform/authentik/terraform.tfstate*`` at umask 0644, and ansible.cfg
``log_path`` creates ``~/.nos/ansible.log`` at 0644. Both hold secrets.
A one-shot chmod is not a pin — a playbook task with ``mode: '0600'`` is.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODE_0600 = re.compile(r"""mode:\s*['"]?0600['"]?""")


def _task_blocks(text: str) -> list[str]:
    return re.split(r"\n(?=\s*- name:)", text)


def test_tofu_apply_pins_tfstate_0600():
    body = (REPO / "tasks/tofu-authentik.yml").read_text(encoding="utf-8")
    blocks = _task_blocks(body)
    apply_i = next(
        (
            i
            for i, block in enumerate(blocks)
            if "tofu apply" in block and "destroy-guard passed" in block
        ),
        None,
    )
    assert apply_i is not None, "tofu apply task missing from tasks/tofu-authentik.yml"
    later = blocks[apply_i + 1 :]
    pins = [
        b
        for b in later
        if "terraform.tfstate" in b and MODE_0600.search(b)
    ]
    assert pins, (
        "after tofu apply, a task must set terraform.tfstate* to mode 0600 "
        "(apply rewrites the files at 0644)"
    )


def test_playbook_pins_ansible_log_0600():
    body = (REPO / "main.yml").read_text(encoding="utf-8")
    pins = [
        b
        for b in _task_blocks(body)
        if MODE_0600.search(b)
        and re.search(r"(?:path|dest):\s*.*ansible\.log", b)
    ]
    assert pins, (
        "playbook must pin ~/.nos/ansible.log to mode 0600 "
        "(ansible.cfg log_path creates it 0644)"
    )
