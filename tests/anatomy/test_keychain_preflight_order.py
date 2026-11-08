"""The codesign keychain dialog is asked in pre_tasks, before any role signs (2026-11-03).

A converge stopped two thirds in on "codesign wants to use the key" (pazny.medulla).
Pins the joint: tasks/preflight-keychain.yml is imported ahead of the first include_role,
carries exactly the tags that select a keychain codesign (`--tags backrest` must not ask,
ruling 2026-11-04), and looks up the same identity the signing roles use.
"""
from __future__ import annotations

import pathlib
import re

import yaml

from .test_a_declared_tag_can_be_reached import TOP, Walker

REPO = pathlib.Path(__file__).resolve().parents[2]
# A keychain sign: codesign -s/--sign with an identity. Ad-hoc `--sign -` (pazny.ears) needs no key.
_KEY_SIGN = re.compile(r"codesign\b[^\n]*?\s(?:-s|--sign)\s+(?![\"']?-[\"']?(?:\s|$))")


def test_keychain_preflight_runs_before_first_role():
    pre = yaml.safe_load((REPO / "main.yml").read_text())[0]["pre_tasks"]
    idx = [i for i, t in enumerate(pre) if t.get("import_tasks") == "tasks/preflight-keychain.yml"]
    assert idx, "main.yml pre_tasks no longer imports tasks/preflight-keychain.yml"
    first_role = next(i for i, t in enumerate(pre) if "ansible.builtin.include_role" in t or "include_role" in t)
    assert idx[0] < first_role, "the keychain preflight must run before the first include_role"


def test_keychain_preflight_uses_the_signing_identity():
    defaults = yaml.safe_load((REPO / "roles/pazny.thalamus/defaults/main.yml").read_text())
    body = (REPO / "tasks/preflight-keychain.yml").read_text()
    assert f"default('{defaults['thalamus_signing_cn']}')" in body
    tail = defaults["thalamus_signing_keychain"].split("}}", 1)[1]
    assert f"~ '{tail}')" in body


class _Signers(Walker):
    """The tag walk of test_a_declared_tag_can_be_reached, recording what selects each keychain sign."""

    def __init__(self) -> None:
        super().__init__()
        self.inh: frozenset = frozenset()
        self.signers: dict[str, set[str]] = {}

    def walk(self, tasks, path, inherited, gate, depth=0):
        prev, self.inh = self.inh, inherited
        try:
            super().walk(tasks, path, inherited, gate, depth)
        finally:
            self.inh = prev

    def record(self, path, task, own, gate):
        super().record(path, task, own, gate)
        body = next((task[k] for k in ("ansible.builtin.shell", "ansible.builtin.command", "shell", "command")
                     if k in task), None)
        if isinstance(body, dict):
            body = " ".join(map(str, body.get("argv") or [body.get("cmd", "")]))
        if path.name == "preflight-keychain.yml" or not isinstance(body, str) or not _KEY_SIGN.search(body):
            return
        sel = set(own | self.inh) if gate is TOP else set(own | self.inh) & set(gate)
        self.signers[f"{path.relative_to(REPO)}: {task.get('name')}"] = sel


def test_keychain_preflight_tags_are_exactly_the_signing_tags():
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    preflight = next(t for t in play["pre_tasks"] if t.get("import_tasks") == "tasks/preflight-keychain.yml")
    walker = _Signers()
    for section in ("pre_tasks", "tasks", "post_tasks", "handlers"):
        walker.walk(play.get(section) or [], REPO / "main.yml", frozenset(), TOP, 0)
    assert len(walker.signers) >= 2, f"walk found {sorted(walker.signers)}; medulla binary, nOS.app sign (the pupil retired 2026-11-08)"
    want = set().union(*walker.signers.values())
    assert set(preflight["tags"]) == want, (
        f"preflight tags {sorted(preflight['tags'])} must equal the tags that select a keychain sign "
        f"{sorted(want)}: {walker.signers}"
    )


def test_keychain_preflight_asks_only_when_thalamus_installs():
    # Every keychain sign sits under import_role pazny.thalamus; with it off, `--tags keap` still asked (2026-11-04).
    play = yaml.safe_load((REPO / "main.yml").read_text())[0]
    preflight = next(t for t in play["pre_tasks"] if t.get("import_tasks") == "tasks/preflight-keychain.yml")
    signer = next(t for t in play["tasks"] if (t.get("ansible.builtin.import_role") or {}).get("name") == "pazny.thalamus")
    assert signer["when"] in preflight["when"], f"preflight `when` lacks the signer's guard {signer['when']!r}"
