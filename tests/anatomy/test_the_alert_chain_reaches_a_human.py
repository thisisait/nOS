"""Every link of the alert chain, because the last one was never built.

MEASURED 2026-08-05, and it is the reason this file exists:

    $ curl -s 127.0.0.1:9090/api/v1/alerts | jq '.data.alerts | length'   → 5
    $ curl -s 127.0.0.1:9090/api/v1/status/config | grep -c alertmanager  → 0

Five `NosWarningServiceDegraded` alerts — qdrant, gitea, firefly and two
exporters — had been FIRING since 2026-07-26. Ten days. Six rule files with
`runbook_url` annotations evaluate on schedule, and Prometheus has no
`alerting:` block, so nothing exists downstream of the evaluation. A curated
alert corpus whose delivery was never connected.

THREE MORE BREAKS IN THE SAME CHAIN, all fixed in the same commit:

  * `nos_cve_open` had no producer. The rules said so themselves, honestly, and
    marked themselves `nos_status: deferred` — which still means the CRITICAL
    CVE alert could not fire during the REM-137 window when `pending_critical`
    was 1. A producer had existed all along under a different metric name.
  * That producer wrote to `/var/lib/node-exporter/textfile`, a Linux
    node_exporter path absent on this host, behind a `[[ -d && -w ]]` guard
    that skipped it in silence. Alloy reads `~/.nos/metrics/textfile`, where
    `backup.prom` already lands — so the mechanism worked and only the address
    was wrong.
  * The off-site restic mirror had no notification path at all: a failed or
    corrupt copy #2 was discoverable at restore time and nowhere earlier. Its
    wrapper was also rendered 0755 with the repository's decryption key inline.

WHAT THIS FILE PINS is the shape of the chain, not its runtime: whether an
alert is firing today is a converge's question. Pytest owns the wiring.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RELAY = REPO / "files/anatomy/scripts/prometheus-alert-relay.py"
PLUGIN = REPO / "files/anatomy/plugins/alert-relay-base/plugin.yml"
RULES = REPO / "files/anatomy/plugins/prometheus-base/provisioning/rules/04-security.yml"
HOOK = REPO / "hooks/playbook-end.d/20-cve-drift-check.sh"
BACKUP = REPO / "tasks/backup.yml"
WEAKNESSES = REPO / "files/anatomy/bone/weaknesses.py"
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
WING_POST = REPO / "roles/pazny.wing/tasks/post.yml"


def test_the_relay_exists_and_is_registered():
    """A courier nobody dispatches is the defect one layer down."""
    assert RELAY.is_file(), "the alert relay script is gone"
    assert PLUGIN.is_file(), "the alert-relay plugin manifest is gone"
    manifest = yaml.safe_load(PLUGIN.read_text(encoding="utf-8"))
    jobs = (manifest.get("pulse") or {}).get("jobs") or []
    assert jobs, "alert-relay-base declares no pulse job, so nothing runs the relay"
    job = jobs[0]
    assert job["command"].endswith("prometheus-alert-relay.py"), job["command"]
    assert re.match(r"^\S+ \S+ \S+ \S+ \S+$", job["schedule"]), job["schedule"]


def test_every_env_token_the_relay_needs_is_renderable():
    """The catalog does a literal str.replace over a FIXED token map.

    An unknown `{{ token }}` survives into Wing verbatim and 400s the converge.
    test_pulse_catalog_renders_every_token.py owns the general rule; this pins
    the specific token this plugin introduced, and that its NOS_* feed exists.
    """
    assert '"{{ prometheus_port }}"' in CATALOG.read_text(encoding="utf-8"), (
        "the catalog no longer knows {{ prometheus_port }}, so the relay's "
        "PROMETHEUS_URL reaches Wing unrendered"
    )
    assert "NOS_PROMETHEUS_PORT" in WING_POST.read_text(encoding="utf-8"), (
        "the substitution key exists but nothing feeds it a value — it would "
        "render to an empty string, which is worse than an unrendered token "
        "because it looks like a URL"
    )


def test_delivery_is_recorded_by_the_delivery():
    """The stamp goes on after Bone answers, never on the attempt.

    Stamping on send is the "success marker written by the attempting code"
    defect this estate has now found in four places; here it would silently
    drop every alert raised during a Bone outage.
    """
    tree = ast.parse(RELAY.read_text(encoding="utf-8"))

    def _sets_delivered(node) -> bool:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            target = sub.targets[0]
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "delivered_at"):
                return True
        return False

    # AST, not a regex: `if notify(...)` wraps its arguments across lines, and a
    # `[^)]*` pattern silently fails to match that — which would make this gate
    # red on correct code and, worse, green on a one-line rewrite of broken code.
    assert _sets_delivered(tree), "nothing records delivery at all"
    guarded = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and getattr(node.test.func, "id", None) == "notify"
        and any(_sets_delivered(stmt) for stmt in node.body)
        for node in ast.walk(tree)
    )
    assert guarded, (
        "delivered_at is set outside the success branch of notify() — a failed "
        "POST would mark the alert as delivered and it would never retry"
    )


def test_the_relay_does_not_report_success_when_it_delivered_nothing():
    source = RELAY.read_text(encoding="utf-8")
    assert "EXIT_UNDELIVERED" in source and "EXIT_NO_POLL" in source, (
        "the relay is back to a blanket exit 0 — a courier that cannot reach "
        "the source or the destination must not report success, because a "
        "non-zero exit IS its escalation path (Wing raises a HIGH inbox row on "
        "the first failure of any pulse job)"
    )


def test_the_cve_alerts_watch_a_metric_that_has_a_producer():
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    exprs = [
        rule["expr"]
        for group in rules.get("groups", [])
        for rule in group.get("rules", [])
        if "expr" in rule
    ]
    assert exprs, "no alert expressions parsed — this gate is blind"
    assert not [e for e in exprs if "nos_cve_open" in e], (
        "an alert still watches nos_cve_open, a metric no code in this repo "
        "emits — it cannot fire, which is absence rendered as calm"
    )
    hook = HOOK.read_text(encoding="utf-8")
    for expr in exprs:
        metric = expr.split("{")[0].strip()
        if metric.startswith("nos_security"):
            assert metric in hook, (
                f"{metric} is alerted on but {HOOK.name} does not emit it"
            )


def test_the_metric_is_written_where_the_collector_reads():
    """The producer wrote to a directory that does not exist on this host."""
    hook = HOOK.read_text(encoding="utf-8")
    # `.+` and anchored to end of line, not `[^}"]+`: the default itself contains
    # a `}` (`${HOME:-/nonexistent}`), and the narrower class stopped at it and
    # reported the whole declaration missing.
    default = re.search(r'^TEXTFILE_DIR="\$\{TEXTFILE_DIR:-(.+)\}"$', hook, re.M)
    assert default, "TEXTFILE_DIR's default is gone from the hook"
    assert "node-exporter" not in default.group(1), (
        f"TEXTFILE_DIR defaults to {default.group(1)!r} again — a Linux "
        f"node_exporter convention this host does not have, and the write is "
        f"guarded by [[ -d && -w ]] so it fails silently"
    )
    assert ".nos/metrics/textfile" in default.group(1), (
        f"TEXTFILE_DIR defaults to {default.group(1)!r}, which is not the "
        f"directory Alloy's textfile collector reads "
        f"(node_exporter_textfile_dir in default.config.yml)"
    )


def test_the_offsite_mirror_can_report_its_own_failure():
    body = BACKUP.read_text(encoding="utf-8")
    assert "trap notify_fail ERR" in body, (
        "the off-site restic mirror is back to failing in silence — copy #2 "
        "would be discovered broken at restore time, the worst moment"
    )


def test_the_offsite_key_is_not_world_readable():
    body = BACKUP.read_text(encoding="utf-8")
    wrapper = body.split("backup-run.sh wrapper script")[-1]
    assert 'export RESTIC_PASSWORD="{{ restic_password }}"' not in wrapper, (
        "the repository's decryption key is inline in the wrapper again"
    )
    assert "restic.env" in body and "mode: '0600'" in body, (
        "the 0600 credentials file is gone; the key is back in a script"
    )
    assert re.search(r"agents/backup-run\.sh\"\n\s+mode: '0700'", body), (
        "backup-run.sh is not 0700 — anything it holds is world-readable"
    )


def test_the_loop_can_see_the_live_signals():
    """SERE's aggregator was blind to both signals the estate produces at runtime."""
    source = WEAKNESSES.read_text(encoding="utf-8")
    for fn in ("_source_prometheus_alerts", "_source_pulse_runs"):
        assert f"def {fn}(" in source, f"{fn} is gone"
        assert f'"{fn.replace("_source_", "").replace("_", "-")}": {fn},' in source, (
            f"{fn} is defined but not registered in collect() — a source that "
            f"is never called reports nothing and looks like agreement"
        )
    assert '"prometheus-alerts",' in source and '"pulse-runs",' in source, (
        "the live sources are not in SOURCE_ORDER, so collect() will KeyError "
        "or skip them"
    )


def test_a_live_weakness_cannot_key_a_retry_ceiling():
    """No repo file backs a live alert, so it must not mint a §4 lift key.

    The ledger keys the retry ceiling on (weakness_id, evidence_sha), both
    derived from file content. A source with no file must declare
    evidence_committed=False or a proposer gains a ceiling it can refresh by
    waiting for the next scrape.
    """
    source = WEAKNESSES.read_text(encoding="utf-8")
    for fn in ("_source_prometheus_alerts", "_source_pulse_runs"):
        # Assert before slicing: without this the retro-red run raised IndexError
        # instead of printing why, and a gate whose failure is a traceback tells
        # the next reader nothing.
        assert f"def {fn}(" in source, f"{fn} is gone — see the test above"
        body = source.split(f"def {fn}(")[1].split("\ndef ")[0]
        assert "evidence_committed=False" in body, (
            f"{fn} does not mark its findings uncommitted — they would be "
            f"proposable, and their evidence hash changes on its own"
        )
