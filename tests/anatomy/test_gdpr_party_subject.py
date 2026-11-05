"""GDPR forget/export accept an org party slug (party-ico-NNNNNNNN) as the subject.

The subject asserts are a host-RCE guard (the subject reaches container_exec
one-liners), so they are EVALUATED here, not grepped: a party slug passes and is
routed only to the digest closure; shell metacharacters still fail.
"""
from __future__ import annotations

import pathlib
import re

import jinja2
import pytest
import yaml
from ansible.plugins.filter.core import regex_search

REPO = pathlib.Path(__file__).resolve().parents[2]
ENV = jinja2.Environment()
ENV.filters["regex_search"] = regex_search
ENV.filters["bool"] = bool

FILES = {"forget": REPO / "tasks" / "gdpr-forget.yml", "export": REPO / "tasks" / "gdpr-export.yml"}
GOOD_PARTY = "party-ico-00000112"
BAD = ["a@b; rm -rf / #", "party-ico-1; x", "Party-ICO-00000112", "party ico 1",
       "party-ico-1 ", "", "party-", "party-$(id)", "party-ico-1\nx", "party-ico-1\n", "-party-ico-1", "a@b.co\n"]


def _tasks(kind):
    return yaml.safe_load(FILES[kind].read_text())


def _task(kind, needle):
    hits = [t for t in _tasks(kind) if needle in t["name"]]
    assert len(hits) == 1, f"{kind}: expected one task matching {needle!r}"
    return hits[0]


def _expr(src: str) -> str:
    """Strip a whole-value '{{ ... }}' so Jinja compiles it as one expression."""
    m = re.fullmatch(r"\s*\{\{(.*)\}\}\s*", src, re.S)
    return m.group(1) if m else src


def _accepts(kind, subject) -> bool:
    var = f"{kind}_subject"
    ctx = {} if subject is None else {var: subject}
    return all(ENV.compile_expression(e)(**ctx)
               for e in _task(kind, "Validate data subject")["ansible.builtin.assert"]["that"])


def _is_party(kind, subject) -> bool:
    facts = _task(kind, "Resolve confirm flag")["ansible.builtin.set_fact"]
    return bool(ENV.compile_expression(_expr(facts[f"_{kind}_party"]))(**{f"{kind}_subject": subject}))


@pytest.mark.parametrize("kind", FILES)
def test_party_slug_and_email_accepted(kind):
    assert _accepts(kind, GOOD_PARTY)
    assert _accepts(kind, "user@example.com")


@pytest.mark.parametrize("kind", FILES)
@pytest.mark.parametrize("subject", BAD + [None])
def test_shell_metacharacters_still_rejected(kind, subject):
    assert not _accepts(kind, subject)


@pytest.mark.parametrize("kind", FILES)
def test_party_routes_only_to_digest_closure(kind):
    assert _is_party(kind, GOOD_PARTY) and not _is_party(kind, "user@example.com")
    when = _task(kind, "Build plan from services")["when"]
    item = {"flag": "always"}
    assert not ENV.compile_expression(when)(**{f"_{kind}_party": True, "item": item}), \
        "a party subject must never enter the email-keyed service fan-out"
    assert ENV.compile_expression(when)(**{f"_{kind}_party": False, "item": item})
    party = _task(kind, "Party subject — digest")
    assert f"_{kind}_party" in str(party["when"])
    tool = "digest-teardown.py" if kind == "forget" else "party-graph.py"
    assert tool in " ".join(_argv(kind, False))
    assert GOOD_PARTY in _argv(kind, False), "the slug must be one argv element, never shell text"


def _argv(kind, confirm):
    argv = _task(kind, "Party subject — digest")["ansible.builtin.command"]["argv"]
    ctx = {f"{kind}_subject": GOOD_PARTY, f"_{kind}_confirm": confirm, "playbook_dir": "/r", "nos_tools_python": "/venv/bin/python"}
    if isinstance(argv, str):
        return ENV.compile_expression(_expr(argv))(**ctx)
    return [ENV.from_string(a).render(**ctx) for a in argv]


def test_forget_confirm_only_when_operator_confirms():
    assert "--confirm" not in _argv("forget", False), "dry-run must stay the default"
    assert "--confirm" in _argv("forget", True)
    assert "--erase-party" in _argv("forget", False)
