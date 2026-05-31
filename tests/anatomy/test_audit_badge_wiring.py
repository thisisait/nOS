"""Anatomy gate: audit-chain integrity badge wiring (gov P1 UI completion).

Pure-Python static checks (no Docker, no PHP runtime) that the badge is wired
default-OFF: BasePresenter sets the verdict only behind the strict
WING_AUDIT_CHAIN_ENABLED==='1' gate; @layout renders it only when set; the
cached-verdict repo is DI-registered and reads audit_chain_meta. The verdict-
write behavior + exit contract are covered behaviorally in test_audit_chain.py.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"


def test_basepresenter_strict_env_gate_and_inject():
    src = (WING / "app" / "Presenters" / "BasePresenter.php").read_text()
    assert "AuditChainRepository $auditChainForBadge" in src, "@inject repo missing"
    assert "getenv('WING_AUDIT_CHAIN_ENABLED') === '1'" in src, \
        "verdict must be gated on the STRICT '1' env check (no loose-truthy)"
    assert "$this->template->auditChainVerdict" in src


def test_layout_renders_badge_only_when_set():
    src = (WING / "app" / "Templates" / "@layout.latte").read_text()
    assert "isset($auditChainVerdict)" in src, "badge must be isset-guarded (hidden by default)"
    assert "['ok']" in src and "['known']" in src


def test_common_neon_registers_repo():
    assert "App\\Model\\AuditChainRepository" in (WING / "app" / "config" / "common.neon").read_text()


def test_repo_reads_cached_verdict_keys():
    src = (WING / "app" / "Model" / "AuditChainRepository.php").read_text()
    assert "last_verify_ok" in src and "last_verify_at" in src
    assert "audit_chain_meta" in src
    # cheap read, NOT a chain walk — must not pull in the verifier algorithm
    assert "rowHash" not in src and "AuditChain::" not in src


def test_verify_script_has_optin_write_flag():
    src = (WING / "bin" / "verify-audit-chain.php").read_text()
    assert "--write-verdict" in src
    assert "busyTimeout" in src, "verdict-write must be WAL-safe (busyTimeout)"
