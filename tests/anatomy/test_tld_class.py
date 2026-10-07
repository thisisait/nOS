"""Anatomy gate — which tenant domains count as LOCAL is said in one place.

`tenant_domain_is_local` (a default layer) picks mkcert + dnsmasq over ACME.
`.internal` (ICANN-reserved 2024) and `.home.arpa` (RFC 8375) are private by
design; `.local` stays local but is mDNS-only (RFC 6762), so a client firm on it
gets a warning. Python readers derive the list via nos_identity.local_tld_suffixes.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

ENV = jinja2.Environment(undefined=jinja2.StrictUndefined)


def is_local(domain: str) -> bool:
    expr = ni.default_config()["tenant_domain_is_local"]
    return ENV.from_string(expr).render(tenant_domain=domain) == "True"


@pytest.mark.parametrize("domain, local", [
    ("firm.internal", True), ("firm.home.arpa", True), ("dev.local", True),
    ("firm.lan", True), ("localhost", True), ("firm.eu", False), ("pazny.eu", False),
])
def test_tld_class(domain, local):
    assert is_local(domain) is local
    assert ni.is_local_domain(domain) is local, "the Python reader disagrees with the playbook"


def _warning():
    pre = yaml.safe_load((REPO / "main.yml").read_text())[0]["pre_tasks"]
    return next(t for t in pre if "mDNS" in str(t.get("name", "")))


@pytest.mark.parametrize("domain, org, warns", [
    ("dev.local", "", False),            # the operator's own default: no client, no warning
    ("firm.local", "Firm s.r.o.", True),
    ("firm.internal", "Firm s.r.o.", False),
])
def test_a_client_on_mdns_local_is_warned(domain, org, warns):
    t = _warning()
    assert "ansible.builtin.debug" in t, "a warning, not a refusal: .local stays accepted"
    when = t["when"] if isinstance(t["when"], list) else [t["when"]]
    ctx = {"tenant_domain": domain, "instance_org": org}
    assert all(ENV.from_string("{{ " + w + " }}").render(ctx) == "True" for w in when) is warns


# A quoted suffix other than `.local` (too common to grep) is a copy of the list.
COPY = re.compile(r"[\"']\.(?:lan|test|localhost|internal|home\.arpa)[\"']")
ALLOWED = {str(p.relative_to(REPO)) for p in ni.default_layers()} | {   # the one source
    "tests/anatomy/test_profile_builder_refuses_contradictions.py",      # pins the extractor's output
}


def test_no_second_copy_of_the_list():
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for rel in files:
        if rel.startswith("docs/") or rel in ALLOWED or not rel.endswith((".py", ".yml", ".yaml", ".j2", ".sh", ".js", ".ts", ".php", ".tpl")):
            continue
        p = REPO / rel
        if not p.is_file():
            continue
        lines = p.read_text(errors="ignore").splitlines()
        # a LIST is two or more suffixes in one file; a lone ".test" is a file suffix, not a TLD list
        if len({m.group(0).strip("\"'") for line in lines for m in COPY.finditer(line)}) < 2:
            continue
        hits += [f"{rel}:{n}" for n, line in enumerate(lines, 1) if COPY.search(line)]
    assert not hits, "a second local-TLD list — derive it from nos_identity.local_tld_suffixes():\n" + "\n".join(hits)
