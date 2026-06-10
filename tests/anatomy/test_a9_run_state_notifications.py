"""W6.1 gates (2026-06-10) — pulse run state-change + backup result emitters.

The Inbox had been a dead surface: the dispatch worker fired every minute
against a `notifications` table with ZERO rows ever, because nothing emitted.
Two structural emitters close that:

1. Wing `Api\\PulsePresenter::actionRunFinish` — the single choke point that
   sees EVERY pulse run result, including the daemon-exception synthetic
   rc=255 (a job whose script never exec'd — the 2026-06-10 EACCES on
   scan-runner.sh — emits here too; a per-script emitter is skipped by
   exactly the failures that matter most). State-change semantics so a
   per-minute job failing repeatedly can't flood the inbox.

2. backup.sh `notify_result` — the launchd backup agent is NOT a pulse job,
   so emitter #1 never sees it; it posts its own result via Bone HMAC.

These are source-contract gates (same pattern as the other PHP-surface
anatomy tests): they pin the load-bearing lines so a refactor can't silently
drop the emit.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

PULSE_PRESENTER = REPO / "files/anatomy/wing/app/Presenters/Api/PulsePresenter.php"
PULSE_REPO = REPO / "files/anatomy/wing/app/Model/PulseRepository.php"
BACKUP_SH = REPO / "roles/pazny.backup/files/backup.sh"
COMMON_NEON = REPO / "files/anatomy/wing/app/config/common.neon"


def test_run_finish_calls_state_change_emitter():
    src = PULSE_PRESENTER.read_text()
    finish = src[src.index("function actionRunFinish"):]
    finish = finish[:finish.index("private function")]
    assert "emitRunStateChangeNotification" in finish, (
        "actionRunFinish no longer calls the state-change notification "
        "emitter — pulse job failures would stop reaching the inbox"
    )


def test_emitter_has_state_change_guard_and_is_best_effort():
    src = PULSE_PRESENTER.read_text()
    body = src[src.index("function emitRunStateChangeNotification"):]
    # State-change guard: steady state (incl. repeat failure) must NOT emit —
    # dispatch-notifications fires per-minute; repeat-failure emits would mean
    # ~1440 inbox rows/day from one broken job.
    assert "$failedNow === $failedBefore" in body
    assert "return; // steady state" in body or "steady state" in body
    # Severities per transition.
    assert "'high'" in body and "'info'" in body
    # Best-effort: a broken notifications table must never 500 run-recording.
    assert "catch (\\Throwable" in body


def test_pulse_repository_previous_exit_excludes_current_run():
    src = PULSE_REPO.read_text()
    assert "function previousExitCode" in src
    body = src[src.index("function previousExitCode"):]
    assert "run_id != ?" in body, (
        "previousExitCode must exclude the just-finished run, else every "
        "failure compares against itself and the transition never fires"
    )
    assert "finished_at IS NOT NULL" in body


def test_notification_repository_registered_in_di():
    """O22 doctrine: Nette DI does not auto-discover — an unregistered
    repository resolves to a runtime 500 on first request."""
    assert "App\\Model\\NotificationRepository" in COMMON_NEON.read_text()


def test_backup_notify_result_wired():
    src = BACKUP_SH.read_text()
    assert "notify_result()" in src, "backup.sh lost the notify_result fn"
    # Called from main() after status_finalize — the status JSON must be
    # complete before the result is summarized.
    main_body = src[src.index("main() {"):]
    assert re.search(r"status_finalize\s*\n\s*notify_result", main_body), (
        "notify_result must run after status_finalize in main()"
    )


def test_backup_notify_canonical_hmac_contract():
    src = BACKUP_SH.read_text()
    body = src[src.index("notify_result()"):]
    # The fn body embeds a python heredoc whose dict literal closes with a
    # column-0 "}" — slice to the heredoc terminator + closing brace instead.
    body = body[:body.index("\nPY\n}") + 5]
    # Canonical JSON — Bone re-serialises sort_keys+compact and verifies HMAC
    # byte-for-byte; any drift breaks the signature.
    assert 'separators=(",", ":")' in body and "sort_keys=True" in body
    # Bare-hex HMAC over ts + "." + body (same contract as the events pipe).
    assert 'b"."' in body and "hexdigest()" in body
    # Empty secret (fresh install pre-regen) must disable silently, and the
    # whole emit must be non-fatal to the backup itself.
    assert 'NOTIFY_HMAC_SECRET}" ]] &&' in body
    assert "non-fatal" in body


def test_backup_notify_severity_split():
    src = BACKUP_SH.read_text()
    body = src[src.index("notify_result()"):]
    # fail -> high, success -> info, zero-sources -> high (a backup that
    # "succeeds" by backing up nothing is a failure in disguise).
    assert body.count('"high"') >= 2
    assert '"info"' in body
