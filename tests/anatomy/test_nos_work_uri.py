"""The nos-work:// routing address parses and matches as the spec says.

dtt-routing-address: tools/nos_work_uri.py is the executable definition of the
grammar in docs/plans/routing-address.md. Its demo() carries the spec's worked
examples; this gate runs them (so a change that breaks the grammar fails here)
and pins the load-bearing rules directly.
"""

from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import nos_work_uri as u  # noqa: E402


def test_self_checks_pass():
    u.demo()  # raises on any grammar regression


def test_spec_doc_exists():
    assert os.path.isfile(os.path.join(_REPO, "docs/plans/routing-address.md")), \
        "the routing-address spec the parser implements is missing"


def test_assignment_subset_capability():
    cap = u.parse("nos-work://local/agent:minimax/repo+dtt/code-fix/*")
    assert u.satisfies(cap, u.parse("nos-work://local/*/repo/code-fix/2026-09-10"))
    # KAM subset is strict: a need outside the grant is not satisfied.
    assert not u.satisfies(cap, u.parse("nos-work://local/*/repo+keap/code-fix/*"))


def test_where_is_hard():
    ext = u.parse("nos-work://ext-cloud/agent:x/repo/code-fix/*")
    assert not u.satisfies(ext, u.parse("nos-work://local/*/repo/code-fix/*")), \
        "a hard-local assignment must not be placed on an ext-cloud-only capability"


def test_kdy_is_not_a_match_segment():
    # Different KDY must NOT change satisfiability — it is scheduling, not a grant.
    cap = u.parse("nos-work://local/*/repo/code-fix/*")
    a1 = u.parse("nos-work://local/*/repo/code-fix/2026-09-10")
    a2 = u.parse("nos-work://local/*/repo/code-fix/@nightly")
    assert u.satisfies(cap, a1) == u.satisfies(cap, a2) is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
