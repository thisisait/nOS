"""D5 unit 4 (art30-live-view) — retro-red gate.

RETRO-RED: before this commit `GdprPresenter` had exactly one action
(`renderDefault`) and `KeapCortexClient` had no method that could resolve one
party by slug. `grep -c 'public function render' GdprPresenter.php` was 1;
`grep -c 'tableRowBySlug' KeapCortexClient.php` was 0. Both assertions below
fail on that tree.

Leak gate mirrors D4's (test_gdpr_controller_records_runtime_only.py): a
STATIC source scan of `renderClientRecords` + `controllerRecordFor` for any
repository/insert/write call, plus the RBAC reconciliation (D5's own new
requirement — the class-wide tier-1 gate must not swallow the one action
that needs tier-managers).
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESENTER = REPO / "files/anatomy/wing/app/Presenters/GdprPresenter.php"
KEAP_CLIENT = REPO / "files/anatomy/wing/app/Model/KeapCortexClient.php"
TEMPLATE = REPO / "files/anatomy/wing/app/Templates/Gdpr/ClientRecords.latte"


def _method_body(src: str, name: str) -> str:
    m = re.search(rf"function {name}\([^)]*\)[^{{]*\{{", src)
    assert m, f"{name}() not found"
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"unbalanced braces in {name}()")


def test_keap_client_gained_a_fetch_row_by_slug_method():
    src = KEAP_CLIENT.read_text(encoding="utf-8")
    assert "public function tableRowBySlug(" in src


def test_gdpr_presenter_gained_the_client_records_action():
    src = PRESENTER.read_text(encoding="utf-8")
    assert "public function renderClientRecords(" in src
    assert TEMPLATE.is_file(), "no Latte template for the new action"


def test_client_records_action_never_writes_anything():
    """Leak/write gate: renderClientRecords + its helper touch no repository,
    no ->insert(/->update(/->delete(, no file write. A refresh must recompute
    from KEAP every time — nothing may be persisted (D4's runtime-only rule)."""
    src = PRESENTER.read_text(encoding="utf-8")
    body = _method_body(src, "renderClientRecords") + _method_body(src, "controllerRecordFor")
    forbidden = ["->insert(", "->update(", "->delete(", "file_put_contents", "fwrite(",
                 "this->repo->"]
    hits = [f for f in forbidden if f in body]
    assert not hits, f"renderClientRecords/controllerRecordFor writes: {hits}"


def test_rbac_reconciliation_client_records_is_reachable_at_tier_managers():
    """The class-wide $minAccessTier=1 gate must not swallow this one action:
    startup() must drop the class gate to tier-managers (2) SPECIFICALLY for
    the clientRecords action, or the consultant seat 403s on their own
    client's Art-30 record (the gap the wf-def calls out explicitly)."""
    src = PRESENTER.read_text(encoding="utf-8")
    assert "protected ?int $minAccessTier = 1;" in src, "renderDefault/DSAR/breaches still gate at tier-1"
    startup = _method_body(src, "startup")
    assert "'clientRecords'" in startup, "startup() has no per-action carve-out for clientRecords"
    assert "requireTier(2)" in startup, "clientRecords is not explicitly re-gated at tier-managers"


def test_client_records_scans_party_by_slug_not_all_records_into_all_records():
    """all_records() (the committed register) must never gain a caller here —
    that would be a second route to the same D4 leak this action must avoid."""
    src = PRESENTER.read_text(encoding="utf-8")
    assert "all_records" not in src
