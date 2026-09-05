"""nos-work:// — parse + match the routing address (dtt-routing-address).

The executable definition of the grammar in docs/plans/routing-address.md. One
parser everywhere; the planner (face/Wing) implements the same rules in its own
language against this reference and its self-test.

    nos-work://<WHERE>/<WHO>/<KAM>/<CO>/<KDY>

Each segment is a SET joined by '+', or '*' for "any/unconstrained". An
ASSIGNMENT (what a work-item needs) is satisfiable by a CAPABILITY (what a
principal may do) when, for each structural segment (WHERE/WHO/KAM/CO), the need
is covered by the grant — `assignment ⊆ capability`. KDY is scheduling, not a
subset match, so it is excluded from satisfies().
"""

from __future__ import annotations

import re

SCHEME = "nos-work://"
SEGMENTS = ("where", "who", "kam", "co", "kdy")
#: The segments satisfies() matches. KDY is a scheduling constraint, not a grant.
_MATCH_SEGMENTS = ("where", "who", "kam", "co")
_VALUE = re.compile(r"^[A-Za-z0-9_.:@/-]+$")


class WorkURI:
    __slots__ = ("where", "who", "kam", "co", "kdy")

    def __init__(self, where, who, kam, co, kdy):
        self.where, self.who, self.kam, self.co, self.kdy = where, who, kam, co, kdy

    def seg(self, name: str) -> set[str]:
        return getattr(self, name)

    def __repr__(self) -> str:
        def j(s):
            return "*" if s == {"*"} else "+".join(sorted(s))
        return SCHEME + "/".join(j(self.seg(n)) for n in SEGMENTS)


def parse(uri: str) -> WorkURI:
    if not uri.startswith(SCHEME):
        raise ValueError(f"not a nos-work URI (must start with {SCHEME!r}): {uri!r}")
    rest = uri[len(SCHEME):]
    parts = rest.split("/") if rest else []
    # KAM values may contain '/' (fs:tenants/x) — but so would over-splitting. To
    # keep the grammar unambiguous, fs: paths use ':' + '-'/'.'; '/' is ONLY the
    # segment separator. So exactly 5 segments.
    if len(parts) != 5:
        raise ValueError(
            f"a work URI has exactly 5 segments (WHERE/WHO/KAM/CO/KDY); got "
            f"{len(parts)}: {uri!r}")
    segs = []
    for name, raw in zip(SEGMENTS, parts):
        if raw == "*":
            segs.append({"*"})
            continue
        vals = raw.split("+")
        for v in vals:
            if not v or not _VALUE.match(v):
                raise ValueError(f"{name} segment has an invalid value {v!r} in {uri!r}")
        segs.append(set(vals))
    return WorkURI(*segs)


def _covers(grant_val: str, need_val: str, *, kam: bool) -> bool:
    if grant_val == need_val:
        return True
    if kam and grant_val == "all":
        return True
    # A bare scope grant covers its own scoped verbs: keap covers keap.read.
    return need_val.startswith(grant_val + ".")


def _segment_covered(grant: set[str], need: set[str], *, kam: bool) -> bool:
    # '*' means unconstrained on EITHER side: an any-grant covers everything; an
    # any-need constrains nothing (the planner/anyone fills it).
    if "*" in grant or "*" in need:
        return True
    return all(any(_covers(g, n, kam=(kam)) for g in grant) for n in need)


def satisfies(capability: WorkURI, assignment: WorkURI) -> bool:
    """True when the assignment's needs are within the capability's grants."""
    return all(
        _segment_covered(capability.seg(s), assignment.seg(s), kam=(s == "kam"))
        for s in _MATCH_SEGMENTS
    )


def demo() -> None:
    cap = parse("nos-work://local/agent:minimax/repo+dtt/code-fix/*")
    assert repr(parse(repr(cap))) == repr(cap), "parse/repr must round-trip"
    # satisfied: local⊆{local}, WHO any, repo⊆{repo,dtt}, code-fix⊆{code-fix}
    assert satisfies(cap, parse("nos-work://local/*/repo/code-fix/2026-09-10"))
    # WHERE fails: eu-cloud not granted
    assert not satisfies(cap, parse("nos-work://eu-cloud/*/repo/code-fix/*"))
    # KAM fails: keap not in {repo,dtt}
    assert not satisfies(cap, parse("nos-work://local/*/keap/code-fix/*"))
    # scoped verb covered by bare scope: dtt.write ≤ dtt
    assert satisfies(cap, parse("nos-work://local/*/dtt.write/code-fix/*"))
    # CO fails: design not in {code-fix}
    assert not satisfies(cap, parse("nos-work://local/*/repo/design/*"))
    # 'all' grant covers any KAM need
    allcap = parse("nos-work://*/agent:conductor/all/*/*")
    assert satisfies(allcap, parse("nos-work://eu-cloud/*/keap+internet/converge/*"))
    # a hard-local assignment is NOT satisfied by an ext-cloud-only capability
    ext = parse("nos-work://ext-cloud/agent:x/repo/code-fix/*")
    assert not satisfies(ext, parse("nos-work://local/*/repo/code-fix/*"))
    # malformed
    for bad in ("http://x", "nos-work://a/b/c", "nos-work://a/b/c/d/e/f"):
        try:
            parse(bad); raise AssertionError(f"should have rejected {bad!r}")
        except ValueError:
            pass
    print("nos_work_uri: all self-checks passed")


if __name__ == "__main__":
    demo()
