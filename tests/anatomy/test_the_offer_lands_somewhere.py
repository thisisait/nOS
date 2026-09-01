"""A view `offer` builds a URL. Something has to be listening at the far end.

MEASURED 2026-09-01, by the adversarial reviewer of the collab build. The face
composed `<wing>/inbox?ref=<session uuid>` for a caddy-sessions row, three
comments explained what the ref was for, and `InboxPresenter::renderDefault`
took `(?string $severity, bool $unreadOnly)` — no `ref`. Nette drops a query
parameter no render method declares, silently and by design, so the link opened
the plain inbox and the operator saw an ordinary queue with no sign that
anything had been followed. Nothing was broken; nothing arrived either.

That is the shape this gate exists for: a caller and a callee written a day
apart in two languages, each internally consistent, with no artifact that
compares them. Two things are asserted, both by reading code rather than prose:

  1. every query key the face puts in a Wing URL is a parameter the presenter
     accepts — the join that was missing;
  2. the `status` values a view `offer` fires on are values something actually
     writes. `open-inbox` triggers on `status: asked`, and `asked` was a
     declared-but-never-written status for a day: an offer that can never
     appear looks exactly like an offer nobody needed.

WHY NOT A LIVE PROBE. A running Wing would prove more, and would also skip on
every machine that has not converged — the state in which this defect was
written. This reads four committed files and cannot skip.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
VIEW_TS = REPO / "files/anatomy/face/src/lib/tables/view.ts"
WING_PRESENTERS = REPO / "files/anatomy/wing/app/Presenters"
CADDY = REPO / "files/anatomy/ears/caddy.py"
TABLES = REPO / "state/keap-tables"


def _wing_links() -> list[tuple[str, str]]:
    """(presenter, query key) for every `<base>/<path>?<key>=` the face builds.

    Read out of the template literals, so a link added tomorrow is checked
    without anyone remembering this file exists.
    """
    src = VIEW_TS.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2))
            for m in re.finditer(r"\}/([a-z][a-z0-9-]*)\?([a-z_]+)=", src)]


def _render_params(presenter: str) -> set[str]:
    php = WING_PRESENTERS / f"{presenter.capitalize()}Presenter.php"
    if not php.is_file():
        return set()
    src = php.read_text(encoding="utf-8")
    out: set[str] = set()
    # renderDefault + actionDefault both receive query parameters in Nette.
    for m in re.finditer(r"function (?:render|action)Default\(([^)]*)\)", src, re.S):
        out |= set(re.findall(r"\$([a-zA-Z][a-zA-Z0-9_]*)", m.group(1)))
    return out


def test_the_sweep_sees_a_link() -> None:
    """Positive control — no links parsed makes the assertion below vacuous."""
    assert _wing_links(), (
        f"no `<base>/<path>?<key>=` literal found in {VIEW_TS.name}; the URLs are "
        "built somewhere else now and this gate is measuring nothing"
    )


def test_every_query_key_the_face_sends_is_one_wing_accepts() -> None:
    for presenter, key in _wing_links():
        params = _render_params(presenter)
        assert params, (
            f"the face links to /{presenter} and no {presenter.capitalize()}Presenter "
            "with a default render was found — the link goes nowhere"
        )
        assert key in params, (
            f"the face sends ?{key}= to /{presenter}, whose render method takes "
            f"{sorted(params)}. Nette drops an undeclared query parameter without "
            "complaint, so the deep-link degrades to the plain page and looks like "
            "it worked."
        )


def test_every_offer_fires_on_a_status_something_writes() -> None:
    """An `offer` gated on a value nothing produces is a surface switched off
    in a way no reader can see."""
    written = set(re.findall(r'status = "([a-z]+)"', CADDY.read_text(encoding="utf-8")))
    written |= set(re.findall(r'"status": "([a-z]+)"', CADDY.read_text(encoding="utf-8")))
    checked = 0
    for table in sorted(TABLES.glob("*.table.yml")):
        doc = yaml.safe_load(table.read_text(encoding="utf-8")) or {}
        for pred in ((doc.get("view") or {}).get("offer") or {}).get("when") or []:
            if pred.get("column") != "status":
                continue
            checked += 1
            assert pred.get("value") in written, (
                f"{table.name}: the offer fires when status == {pred.get('value')!r}, "
                f"and the only statuses written are {sorted(written)}. The hand-off "
                "can never appear."
            )
    assert checked, (
        "no status-gated offer found in state/keap-tables — either they moved or "
        "the parse broke; this gate must not pass by finding nothing"
    )
