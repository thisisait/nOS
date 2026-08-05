"""Anatomy gate — Prometheus alert rules referencing UNDELIVERED metrics are
labelled `nos_status: deferred` (not silent dead code).

WHY: several alert rules in the prometheus-base provisioning point at metrics
that have NO producer anywhere in the repo — they wait on features that have
not shipped through A18+:

  log_pattern_matches_total              -> Loki->Prom log-metric bridge (unbuilt)
  paperclip_queue_depth                  -> Paperclip queue exporter (unbuilt)
  nos_upgrade_available                  -> state_manager/Wing upgrade exporter (unbuilt)
  nos_migration_pending                  -> state_manager exporter hook (unbuilt)
  nos_cve_open                           -> Wing CVE pushgateway (unbuilt)
  nos_vaultwarden_admin_token_age_seconds-> vaultwarden token-mtime scraper (unbuilt)
  probe_dns_lookup_time_seconds          -> blackbox_exporter dns module (unwired)

A rule referencing an undefined metric SILENTLY never fires. Left as a bare
`TODO`, it reads like active monitoring — operators believe coverage exists
when it does not. This gate pins the structural fix: each such rule carries a
machine-checkable `nos_status: deferred` label + a `deferred_dependency`
annotation naming the missing producer, and no `TODO` referencing those metrics
survives. When a producer ships, drop the label here AND in the rule file.

This gate is intentionally STRICT in the other direction too: if someone adds a
producer for one of these metrics (so the alert can finally fire), the
DELIVERED set below must shrink — leaving a now-live alert mislabelled
`deferred` would suppress it from operator dashboards.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
RULES_DIR = REPO / "files/anatomy/plugins/prometheus-base/provisioning/rules"

# Metrics that have NO producer in the codebase today (verified: a repo-wide
# grep over *.php/*.py/*.yml/*.j2/*.river outside the rules dir finds zero
# emitters). Any alert whose expr references one of these is a never-firing
# rule and MUST be marked deferred.
UNDELIVERED_METRICS = (
    "log_pattern_matches_total",
    "paperclip_queue_depth",
    "nos_upgrade_available",
    "nos_migration_pending",
    # nos_cve_open LEFT this list 2026-08-05. It never had a producer and the
    # rules honestly said so — and the CRITICAL alert therefore could not fire
    # during the REM-137 window when pending_critical was 1. A producer had
    # existed the whole time under another name: 20-cve-drift-check.sh emits
    # nos_security_pending_total, into a directory that did not exist. Both ends
    # now agree, so those two alerts are live and are no longer deferred.
    "nos_vaultwarden_admin_token_age_seconds",
    "probe_dns_lookup_time_seconds",
)

RULE_FILES = ("02-network.yml", "03-apps.yml", "04-security.yml")


def _iter_alerts():
    """Yield (file, group_name, alert_dict) for every alert rule in the set."""
    for fname in RULE_FILES:
        path = RULES_DIR / fname
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for group in doc.get("groups", []):
            for rule in group.get("rules", []):
                if "alert" in rule:
                    yield fname, group.get("name", "?"), rule


def _references_undelivered(expr: str) -> str | None:
    for metric in UNDELIVERED_METRICS:
        if metric in expr:
            return metric
    return None


def test_rule_files_exist_and_parse():
    for fname in RULE_FILES:
        path = RULES_DIR / fname
        assert path.is_file(), f"missing rule file {path}"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "groups" in doc, f"{fname}: no groups key"


def test_undelivered_metric_alerts_are_marked_deferred():
    """Every alert referencing an undelivered metric carries the deferred label
    + a deferred_dependency annotation."""
    offenders = []
    matched = 0
    for fname, group, rule in _iter_alerts():
        metric = _references_undelivered(str(rule.get("expr", "")))
        if not metric:
            continue
        matched += 1
        labels = rule.get("labels", {}) or {}
        annotations = rule.get("annotations", {}) or {}
        if labels.get("nos_status") != "deferred":
            offenders.append(
                f"{fname}:{group}:{rule['alert']} references undelivered "
                f"`{metric}` but lacks `nos_status: deferred` label"
            )
        if not str(annotations.get("deferred_dependency", "")).strip():
            offenders.append(
                f"{fname}:{group}:{rule['alert']} references undelivered "
                f"`{metric}` but lacks a `deferred_dependency` annotation"
            )
    assert offenders == [], "\n".join(offenders)
    # Sanity: the set is non-empty — guards against a regex/path typo that would
    # make this test vacuously pass.
    # Vacuity guard, not a target. It read >=10 until the two CVE alerts were
    # connected to a real metric on 2026-08-05 — a floor on the COUNT OF
    # DEFERRALS goes red when a deferral is honoured, which is backwards. It
    # exists only to catch a regex or path typo that would match nothing.
    assert matched >= 8, (
        f"expected >=8 deferred-metric alerts, matched {matched} — "
        "did the rule files move or get gutted?"
    )


def test_no_stale_todo_for_undelivered_metrics():
    """No `TODO` comment referencing an undelivered metric survives — the
    deferral is documented via the explicit `DEFERRED`/label contract instead."""
    offenders = []
    for fname in RULE_FILES:
        text = (RULES_DIR / fname).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "TODO" not in line:
                continue
            for metric in UNDELIVERED_METRICS:
                if metric in line:
                    offenders.append(f"{fname}:{lineno}: stale TODO -> {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_deferred_label_only_on_undelivered_alerts():
    """Inverse guard: an alert is labelled deferred ONLY if it actually
    references an undelivered metric. Prevents a delivered alert from being
    wrongly suppressed as deferred."""
    offenders = []
    for fname, group, rule in _iter_alerts():
        labels = rule.get("labels", {}) or {}
        if labels.get("nos_status") != "deferred":
            continue
        if _references_undelivered(str(rule.get("expr", ""))) is None:
            offenders.append(
                f"{fname}:{group}:{rule['alert']} is labelled deferred but its "
                "expr references no known-undelivered metric — drop the label or "
                "update UNDELIVERED_METRICS"
            )
    assert offenders == [], "\n".join(offenders)
