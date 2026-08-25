<?php

declare(strict_types=1);

/**
 * Inbox reconciler — marks a notification read only on evidence (2026-08-19).
 *
 * MEASURED, and the reason this file exists: 69 unread CRITICAL/HIGH rows were
 * 23 distinct problems. Eight were pulse jobs green at that moment; twelve were
 * "Backup FAILED" from a fortnight during which the backup had long recovered;
 * one incident sat in the inbox TWICE — the firing row and the relay's own
 * "RESOLVED:" row, both unread. A notification is an EVENT and the inbox is a
 * STATE, and until this file nothing reconciled them: markRead() had exactly
 * one caller, the operator's mouse.
 *
 * THE ONE RULE. This estate's hardest-won lesson is that no step records its
 * own success — and a reconciler that marks a row read because it BELIEVES the
 * condition cleared is that defect wearing a new hat. So every mark-read here
 * is preceded by a READ of the condition's own source, and the row's
 * metadata_json records verbatim WHAT was read:
 *
 *   pulse-run rows  ("Pulse job X failing/recovered")
 *       source: pulse_runs — the latest FINISHED run for that job must exist,
 *       be green (exit 0 or a declared findings code from
 *       pulse_jobs.findings_exit_codes), and have finished at/after the row.
 *   alert rows      (prometheus-alert-relay origin)
 *       source: the relay — its "RESOLVED:" row (written only after the relay
 *       observed the alert gone AND Bone answered 2xx) paired by fingerprint,
 *       corroborated against the relay's live seen-state file. A fingerprint
 *       still present in the state file is a contradiction: refuse.
 *   backup rows     ("Backup FAILED ...", origin_plugin=backup)
 *       source: backup-status.json — a COMPLETED later run (in_progress=false,
 *       last_run after the row) with >0 sources and zero failures.
 *   agent questions ("Agent asks: <name>")
 *       source: agent_questions — status != 'open' (answered/expired/
 *       cancelled). The ask was the condition; a decided ask is not pending.
 *
 * A SECOND VERDICT, AND A SECOND COLUMN (2026-08-24). The rules above all ask
 * "did the CONDITION clear". Report rows have no condition — this file said so
 * itself and left them alone — but they do have a successor, and once an
 * emitter has declared it restates itself (by sending a `supersede_key`), a
 * later message from that same sender is evidence about the earlier one.
 *
 * Such rows are RETIRED, not marked read. `wing_inbox_read_at` is a claim about
 * a human and nobody read these; stamping it would be the estate recording a
 * decision the operator never made. `superseded_at` + `superseded_by` say the
 * true thing and keep the lineage.
 *
 * The list of emitters that restate themselves is NOT in this file. It is read
 * from what emitters have actually sent (`declared_repeaters`), so the
 * judgement stays with the sender — a table here could retire rows for an
 * emitter that never opted in, and two gitleaks findings are two secrets.
 * The consequence is deliberate: an emitter that has not fired since the
 * mechanism shipped has no backlog cleared until it does.
 *
 * WHAT IT REFUSES TO TOUCH, by construction:
 *   - anything it cannot classify (unknown titles/origins) — counted, listed,
 *     left unread;
 *   - a report row whose emitter has never declared that it repeats;
 *   - the newest row from any emitter — it is the current word, not a stale one;
 *   - a job that has never run, or has no finished run since the row — absence
 *     is not resolution;
 *   - a source it cannot read — the row stays unread, the run says so, and the
 *     exit code goes to 2 so Pulse's own state-change alarm announces it;
 *   - severities/reports that are not conditions (e.g. "Backup OK" info rows)
 *     — a report row is news, not state, and news is the operator's to read.
 *
 * DRY RUN IS THE DEFAULT (the estate's destructive-op doctrine): without
 * --apply this prints every verdict and writes nothing.
 *
 * Env:
 *   WING_DB_PATH         default ~/wing/app/data/wing.db
 *   ALERT_RELAY_STATE    default ~/.nos/prom-alerts-seen.json
 *   BACKUP_STATUS_FILE   default ~/.nos/backup-status.json
 *
 * Exit codes:
 *   0  reconciled cleanly (zero or more rows marked)
 *   1  fatal: wing.db unreadable / schema missing
 *   2  at least one pending row's evidence source was unreadable
 */

$home = $_SERVER['HOME'] ?? getenv('HOME') ?: '/tmp';
$wingDb = getenv('WING_DB_PATH') ?: ($home . '/wing/app/data/wing.db');
$relayStatePath = getenv('ALERT_RELAY_STATE') ?: ($home . '/.nos/prom-alerts-seen.json');
$backupStatusPath = getenv('BACKUP_STATUS_FILE') ?: ($home . '/.nos/backup-status.json');
$apply = in_array('--apply', $argv, true);

if (!file_exists($wingDb)) {
	fwrite(STDERR, "fatal: wing.db not found at {$wingDb}\n");
	exit(1);
}
try {
	$db = new SQLite3($wingDb, $apply ? SQLITE3_OPEN_READWRITE : SQLITE3_OPEN_READONLY);
	$db->busyTimeout(5000);
	$db->enableExceptions(true);
} catch (\Throwable $exc) {
	fwrite(STDERR, "fatal: cannot open wing.db: {$exc->getMessage()}\n");
	exit(1);
}

/** SQLite datetime('now') carries no zone marker and IS UTC; ISO-8601 rows
 *  carry their own. Never let strtotime guess the host zone. */
function parse_utc(?string $s): ?int
{
	if ($s === null || trim($s) === '') {
		return null;
	}
	if (!preg_match('/(Z|[+-]\d{2}:?\d{2})\s*$/', $s)) {
		$s .= ' UTC';
	}
	$t = strtotime($s);
	return $t === false ? null : $t;
}

/** Latest FINISHED run for a job, or null. Read, never inferred. */
function latest_finished_run(SQLite3 $db, string $jobId): ?array
{
	$stmt = $db->prepare(
		'SELECT run_id, exit_code, fired_at, finished_at FROM pulse_runs
		  WHERE job_id = :j AND finished_at IS NOT NULL AND exit_code IS NOT NULL
		  ORDER BY fired_at DESC LIMIT 1'
	);
	$stmt->bindValue(':j', $jobId, SQLITE3_TEXT);
	$row = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
	return $row === false ? null : $row;
}

/**
 * Verdict for one unread row.
 * @return array{action:'mark'|'leave'|'unreadable', reason:string, evidence?:array<string,mixed>}
 */
function verdict_pulse(SQLite3 $db, array $n): array
{
	$meta = $n['metadata'];
	$jobId = (string) ($meta['job_id'] ?? '');
	if ($jobId === '' && preg_match('/^Pulse job (\S+) (failing|recovered)/', (string) $n['title'], $m)) {
		$jobId = $m[1]; // pre-2026-08-19 rows carry the job only in the title
	}
	if ($jobId === '') {
		return ['action' => 'leave', 'reason' => 'cannot determine job_id'];
	}

	$stmt = $db->prepare('SELECT findings_exit_codes, removed_at FROM pulse_jobs WHERE id = :j');
	$stmt->bindValue(':j', $jobId, SQLITE3_TEXT);
	$job = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
	if ($job === false) {
		return ['action' => 'leave', 'reason' => "job {$jobId} not in catalog — no current condition to read"];
	}
	if (!empty($job['removed_at'])) {
		return ['action' => 'leave', 'reason' => "job {$jobId} removed at {$job['removed_at']} — condition unreadable"];
	}
	$findings = json_decode((string) ($job['findings_exit_codes'] ?? '[]'), true);
	$findings = is_array($findings) ? array_map('intval', $findings) : [];

	$run = latest_finished_run($db, $jobId);
	if ($run === null) {
		return ['action' => 'leave', 'reason' => "job {$jobId} has no finished run — absence is not resolution"];
	}
	$exit = (int) $run['exit_code'];
	$green = ($exit === 0) || in_array($exit, $findings, true);
	if (!$green) {
		return ['action' => 'leave', 'reason' => "job {$jobId} latest run rc={$exit} — still red"];
	}
	// The evidencing run must not PREDATE the news. 120s grace covers the
	// recovered row, whose own run finishes moments before the row is written.
	$runEnd = parse_utc((string) $run['finished_at']);
	$rowAt = parse_utc((string) $n['created_at']);
	if ($runEnd === null || $rowAt === null || $runEnd < $rowAt - 120) {
		return ['action' => 'leave', 'reason' => "job {$jobId} last green run predates the notification"];
	}
	return [
		'action' => 'mark',
		'reason' => "pulse_runs: latest finished run {$run['run_id']} rc={$exit} at {$run['finished_at']}",
		'evidence' => [
			'read_from' => 'pulse_runs',
			'job_id' => $jobId,
			'run_id' => $run['run_id'],
			'exit_code' => $exit,
			'fired_at' => $run['fired_at'],
			'finished_at' => $run['finished_at'],
		],
	];
}

function verdict_alert(SQLite3 $db, array $n, string $relayStatePath): array
{
	$fp = (string) ($n['metadata']['fingerprint'] ?? '');
	if ($fp === '') {
		return ['action' => 'leave', 'reason' => 'relay row without fingerprint — cannot pair'];
	}

	// The relay's live seen-state is the current condition. Unreadable → refuse.
	$raw = @file_get_contents($relayStatePath);
	if ($raw === false) {
		return ['action' => 'unreadable', 'reason' => "relay state {$relayStatePath} unreadable — leaving row unread"];
	}
	$state = json_decode($raw, true);
	if (!is_array($state)) {
		return ['action' => 'unreadable', 'reason' => "relay state {$relayStatePath} unparseable — leaving row unread"];
	}
	if (array_key_exists($fp, $state)) {
		return ['action' => 'leave', 'reason' => "fingerprint {$fp} still in relay state — alert firing"];
	}

	$isResolvedRow = ($n['metadata']['resolved'] ?? false) === true;
	if (!$isResolvedRow) {
		// A firing row needs the relay's OWN later observation that it cleared:
		// the RESOLVED row, which the relay writes only after seeing the alert
		// gone and Bone answering 2xx. No such row → the relay never said so.
		$stmt = $db->prepare(
			"SELECT uuid, created_at, metadata_json FROM notifications
			  WHERE origin_plugin = 'prometheus-alert-relay'
			    AND created_at > :after
			    AND metadata_json LIKE :fp
			  ORDER BY created_at ASC"
		);
		$stmt->bindValue(':after', (string) $n['created_at'], SQLITE3_TEXT);
		$stmt->bindValue(':fp', '%"' . SQLite3::escapeString($fp) . '"%', SQLITE3_TEXT);
		$res = $stmt->execute();
		$resolvedRow = null;
		while (($r = $res->fetchArray(SQLITE3_ASSOC)) !== false) {
			$m = json_decode((string) $r['metadata_json'], true) ?: [];
			if (($m['fingerprint'] ?? '') === $fp && ($m['resolved'] ?? false) === true) {
				$resolvedRow = $r;
				break;
			}
		}
		if ($resolvedRow === null) {
			return ['action' => 'leave', 'reason' => "no RESOLVED row from the relay for {$fp} — relay has not said it cleared"];
		}
		return [
			'action' => 'mark',
			'reason' => "relay resolved it at {$resolvedRow['created_at']} (row {$resolvedRow['uuid']}); fingerprint absent from live state",
			'evidence' => [
				'read_from' => 'alert-relay',
				'fingerprint' => $fp,
				'resolved_row' => $resolvedRow['uuid'],
				'resolved_row_created_at' => $resolvedRow['created_at'],
				'state_file' => $relayStatePath,
				'fingerprint_in_state' => false,
			],
		];
	}

	// The RESOLVED row itself: it is the relay's delivered observation, and the
	// live state just confirmed the alert is not firing. Its information is
	// consumed by this reconciliation.
	return [
		'action' => 'mark',
		'reason' => "relay's own RESOLVED row; fingerprint {$fp} absent from live state",
		'evidence' => [
			'read_from' => 'alert-relay',
			'fingerprint' => $fp,
			'state_file' => $relayStatePath,
			'fingerprint_in_state' => false,
		],
	];
}

function verdict_backup(array $n, string $backupStatusPath): array
{
	$raw = @file_get_contents($backupStatusPath);
	if ($raw === false) {
		return ['action' => 'unreadable', 'reason' => "backup status {$backupStatusPath} unreadable — leaving row unread"];
	}
	$status = json_decode($raw, true);
	if (!is_array($status)) {
		return ['action' => 'unreadable', 'reason' => "backup status {$backupStatusPath} unparseable — leaving row unread"];
	}
	if (($status['in_progress'] ?? false) === true) {
		return ['action' => 'leave', 'reason' => 'backup run in progress — no completed evidence'];
	}
	$lastRun = (int) ($status['last_run'] ?? 0);
	$rowAt = parse_utc((string) $n['created_at']);
	if ($lastRun === 0 || $rowAt === null || $lastRun <= $rowAt) {
		return ['action' => 'leave', 'reason' => 'no completed backup run AFTER this notification'];
	}
	$sources = $status['sources'] ?? [];
	if (!is_array($sources) || count($sources) === 0) {
		return ['action' => 'leave', 'reason' => 'latest backup run recorded zero sources — that is its own alarm'];
	}
	$failed = [];
	foreach ($sources as $s) {
		if (!(bool) ($s['success'] ?? false)) {
			$failed[] = (string) ($s['name'] ?? '?');
		}
	}
	if ($failed !== []) {
		return ['action' => 'leave', 'reason' => 'latest backup run still has failures: ' . implode(', ', $failed)];
	}
	return [
		'action' => 'mark',
		'reason' => "backup-status.json: run at " . gmdate('c', $lastRun) . " with " . count($sources) . " sources, 0 failed",
		'evidence' => [
			'read_from' => 'backup-status.json',
			'status_file' => $backupStatusPath,
			'last_run' => $lastRun,
			'last_run_iso' => gmdate('c', $lastRun),
			'source_count' => count($sources),
			'failed_count' => 0,
		],
	];
}

function verdict_question(SQLite3 $db, array $n): array
{
	$qUuid = (string) ($n['metadata']['question_uuid'] ?? '');
	if ($qUuid === '') {
		return ['action' => 'leave', 'reason' => 'agent-inbox row without question_uuid'];
	}
	$stmt = $db->prepare('SELECT status, answered_by, answered_at FROM agent_questions WHERE uuid = :u');
	$stmt->bindValue(':u', $qUuid, SQLITE3_TEXT);
	$q = $stmt->execute()->fetchArray(SQLITE3_ASSOC);
	if ($q === false) {
		return ['action' => 'leave', 'reason' => "question {$qUuid} not found — absence is not resolution"];
	}
	if (($q['status'] ?? 'open') === 'open') {
		return ['action' => 'leave', 'reason' => "question {$qUuid} still open — the ask is pending"];
	}
	return [
		'action' => 'mark',
		'reason' => "agent_questions: {$qUuid} status={$q['status']}"
			. (!empty($q['answered_by']) ? " by {$q['answered_by']} at {$q['answered_at']}" : ''),
		'evidence' => [
			'read_from' => 'agent_questions',
			'question_uuid' => $qUuid,
			'status' => $q['status'],
			'answered_by' => $q['answered_by'],
			'answered_at' => $q['answered_at'],
		],
	];
}

/**
 * Emitters that have DECLARED they restate themselves, read from the database
 * rather than from a list here.
 *
 * An emitter declares by ACTING: once it has sent one notification carrying a
 * `supersede_key`, the class exists and it is the sender's own word. A table of
 * (origin_plugin, actor_id) pairs in this file would be a second copy of a
 * declaration that already lives in the emitters — and it would let this tool
 * retire rows for an emitter that never opted in, which is precisely the
 * judgement `supersede_key` exists to keep with the sender.
 *
 * The consequence is deliberate and self-limiting: an emitter that has not yet
 * fired since the mechanism shipped has no entry here, and its backlog is left
 * alone until it does. This tool never runs ahead of the sender.
 *
 * @return array<string, array{key:string, uuid:string, created_at:string}>
 *         keyed "origin|actor" -> the NEWEST row that pair has produced
 */
function declared_repeaters(SQLite3 $db): array
{
	$out = [];
	$res = $db->query(
		"SELECT n.origin_plugin, n.actor_id, n.uuid, n.created_at,
		        (SELECT k.supersede_key FROM notifications k
		          WHERE k.supersede_key IS NOT NULL
		            AND ifnull(k.origin_plugin,'') = ifnull(n.origin_plugin,'')
		            AND ifnull(k.actor_id,'')      = ifnull(n.actor_id,'')
		          ORDER BY k.created_at DESC, k.id DESC LIMIT 1) AS declared_key
		   FROM notifications n
		  WHERE n.target_actor_id = 'operator'
		  ORDER BY n.created_at DESC, n.id DESC"
	);
	while (($r = $res->fetchArray(SQLITE3_ASSOC)) !== false) {
		if (($r['declared_key'] ?? null) === null) {
			continue;                       // this emitter never opted in
		}
		$pair = ($r['origin_plugin'] ?? '') . '|' . ($r['actor_id'] ?? '');
		if (isset($out[$pair])) {
			continue;                       // rows arrive newest-first
		}
		$out[$pair] = [
			'key'        => (string) $r['declared_key'],
			'uuid'       => (string) $r['uuid'],
			'created_at' => (string) $r['created_at'],
			// How many distinct message shapes wear this identity. >1 means a
			// shared sender — see verdict_restated. The prefix is coarse on
			// purpose: "Backup OK - 14 sources, 615.0 MB" and "…617.6 MB" are
			// one shape, "S2 diff: …" and "nOS macOS update settled…" are two.
			'shared'     => (int) shape_count($db, $r['origin_plugin'], $r['actor_id']),
		];
	}
	return $out;
}

/** Distinct message shapes under one (origin_plugin, actor_id). */
function shape_count(SQLite3 $db, ?string $origin, ?string $actor): int
{
	// SHAPE = the title with its DIGITS REMOVED. A restatement class differs by
	// numbers — "Backup OK - 14 sources, 615.0 MB" and "…617.6 MB" — and never
	// by words. The first cut compared the first 18 characters and called
	// "Backup OK - 1" and "Backup OK - 2" two different shapes, refusing a
	// class it should have accepted: a heuristic that fails CLOSED is still a
	// heuristic that is wrong. Digits are the thing that varies; strip them.
	$stmt = $db->prepare(
		"SELECT COUNT(DISTINCT replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(title,'0',''),'1',''),'2',''),'3',''),'4',''),'5',''),'6',''),'7',''),'8',''),'9','')) FROM notifications
		  WHERE ifnull(origin_plugin,'') = ifnull(:o,'')
		    AND ifnull(actor_id,'')      = ifnull(:a,'')"
	);
	$stmt->bindValue(':o', $origin, SQLITE3_TEXT);
	$stmt->bindValue(':a', $actor, SQLITE3_TEXT);
	$row = $stmt->execute()->fetchArray(SQLITE3_NUM);
	return $row === false ? 99 : (int) $row[0];   // unreadable => refuse
}


/**
 * Has this row been RESTATED by a later one from the same emitter?
 *
 * This is the only verdict in this file that is not about a condition
 * CLEARING. The others read a source and ask "is it still failing"; this one
 * asks "has the sender said it again", which is a different question with a
 * different answer column — see the `supersede` action in the sweep.
 *
 * @return array{action:'supersede'|'leave', reason:string, evidence?:array<string,mixed>}
 */
function verdict_restated(array $n, array $repeaters): array
{
	$pair = ($n['origin_plugin'] ?? '') . '|' . ($n['actor_id'] ?? '');
	if (!isset($repeaters[$pair])) {
		return ['action' => 'leave', 'reason' => 'emitter has not declared that it restates itself'];
	}
	$newest = $repeaters[$pair];
	// `> 1`, not `!empty()`. The first cut refused every class, because
	// !empty(1) is TRUE in PHP — a guard that fires on the healthy case is
	// a guard that stops the feature. Caught by running it, not reading it.
	if (($newest['shared'] ?? 99) > 1) {
		// AN IDENTITY SHARED BY DIFFERENT MESSAGE SHAPES IS NOT A CLASS.
		// Found by the night of 2026-08-24: `nos-notify.sh` hardcodes
		// origin_plugin `os-resume` / actor `agent:os-resume` for EVERY caller,
		// and it is the shared sender for the KEAP consolidator, the KEAP
		// linter, the cortex corpus diff and a readiness probe as well as the
		// os-update settle it was named for. Thirty-three rows wear a borrowed
		// identity.
		//
		// This function keys the class on that identity. So the first real
		// `os-resume-settled` emission would have retired S2-diff findings and
		// KEAP batches on the strength of a declaration that has nothing to do
		// with them — silently, in a tool the operator now runs routinely.
		//
		// Refuse, and say so. The detection is not inference: it is more than
		// one distinct title shape under one identity, which no genuine
		// restatement class produces.
		return ['action' => 'leave',
		        'reason' => "identity {$pair} carries {$newest['shared']} distinct "
		                  . "message shapes — it is a shared sender, not a class; "
		                  . "the emitters must carry their own origin_plugin"];
	}
	if ($newest['uuid'] === $n['uuid']) {
		return ['action' => 'leave', 'reason' => 'this IS the latest word from its emitter'];
	}
	$mine  = parse_utc((string) $n['created_at']);
	$their = parse_utc($newest['created_at']);
	if ($mine === null || $their === null) {
		return ['action' => 'leave', 'reason' => 'unparseable timestamp — refusing to compare'];
	}
	if ($mine >= $their) {
		return ['action' => 'leave', 'reason' => 'no later row from this emitter'];
	}
	return [
		'action'   => 'supersede',
		'reason'   => "restated by {$newest['uuid']} at {$newest['created_at']} "
		            . "(class '{$newest['key']}', declared by the emitter itself)",
		'evidence' => [
			'superseded_by'      => $newest['uuid'],
			'successor_sent_at'  => $newest['created_at'],
			'declared_class'     => $newest['key'],
		],
	];
}

// ── Main sweep ───────────────────────────────────────────────────────────────

$rows = [];
// The restated rule needs TWO columns the base table has not always had:
// `superseded_at` (init-db.php's ALTER sweep) and `actor_id` (A10). Ask for
// both before naming either — a bare reference aborts the WHOLE tool, taking
// the four evidence rules down with it on an estate that is merely behind.
// Found by breaking it: a hand-rolled minimal table in the existing gate has
// no actor_id, and the reconciler died with exit 255 rather than doing the
// work it could still do.
$have = [];
$cols = $db->query("PRAGMA table_info(notifications)");
while (($c = $cols->fetchArray(SQLITE3_ASSOC)) !== false) {
	$have[$c['name']] = true;
}
$hasSupersede = isset($have['superseded_at']) && isset($have['actor_id']);

$res = $db->query(
	"SELECT id, uuid, severity, title, origin_plugin, metadata_json, created_at"
	. ($hasSupersede ? ", actor_id" : "") . "
	   FROM notifications
	  WHERE target_actor_id = 'operator' AND wing_inbox_read_at IS NULL"
	. ($hasSupersede ? " AND superseded_at IS NULL" : "") . "
	  ORDER BY id ASC"
);
while (($r = $res->fetchArray(SQLITE3_ASSOC)) !== false) {
	$r['metadata'] = json_decode((string) ($r['metadata_json'] ?? '{}'), true) ?: [];
	$rows[] = $r;
}

$repeaters = $hasSupersede ? declared_repeaters($db) : [];

$marked = 0;
$superseded = 0;
$left = 0;
$unreadable = 0;
$unclassified = 0;

foreach ($rows as $n) {
	$title = (string) $n['title'];
	$origin = (string) ($n['origin_plugin'] ?? '');

	if (str_starts_with($title, 'Pulse job ')) {
		$v = verdict_pulse($db, $n);
	} elseif ($origin === 'prometheus-alert-relay') {
		$v = verdict_alert($db, $n, $relayStatePath);
	} elseif ($origin === 'backup' && (str_starts_with($title, 'Backup FAILED') || str_starts_with($title, 'Backup ran but recorded ZERO'))) {
		$v = verdict_backup($n, $backupStatusPath);
	} elseif ($origin === 'agent-inbox' && isset($n['metadata']['question_uuid'])) {
		$v = verdict_question($db, $n);
	} elseif ($hasSupersede
	          && ($v = verdict_restated($n, $repeaters))
	          && ($v['action'] === 'supersede' || isset($repeaters[($n['origin_plugin'] ?? '') . '|' . ($n['actor_id'] ?? '')]))) {
		// LAST, on purpose. The classifiers above answer "did the condition
		// clear", which is a stronger statement than "the sender said it
		// again" — a row they can decide should be decided by them.
		//
		// A `leave` from a DECLARED identity is carried through rather than
		// folded into `unclassified`, so its reason is printed. The first cut
		// dropped it, and the shared-sender refusal — the whole point of that
		// guard — was invisible: the tool declined to act and said nothing,
		// which is the defect this file exists to refuse.
		$noop = null;
	} else {
		$unclassified++;
		echo "UNCLASSIFIED  {$n['uuid']}  [{$n['severity']}] {$title} — left for the operator\n";
		continue;
	}

	if ($v['action'] === 'supersede') {
		// A DIFFERENT COLUMN, and that is the whole point. Nobody read these
		// rows; stamping wing_inbox_read_at would be the estate recording a
		// decision the operator never made. `superseded_at` says what is true:
		// a later message from the same sender replaced this one.
		if ($apply) {
			$merged = $n['metadata'];
			$merged['reconciled'] = $v['evidence'] + [
				'reconciled_at' => gmdate('c'),
				'reconciled_by' => 'bin/reconcile-inbox.php',
			];
			$stmt = $db->prepare(
				'UPDATE notifications
				    SET superseded_at = :now, superseded_by = :by, metadata_json = :meta
				  WHERE uuid = :uuid AND wing_inbox_read_at IS NULL AND superseded_at IS NULL'
			);
			$stmt->bindValue(':now', gmdate('c'), SQLITE3_TEXT);
			$stmt->bindValue(':by', $v['evidence']['superseded_by'], SQLITE3_TEXT);
			$stmt->bindValue(':meta', json_encode($merged), SQLITE3_TEXT);
			$stmt->bindValue(':uuid', $n['uuid'], SQLITE3_TEXT);
			$stmt->execute();
			echo "RETIRED       {$n['uuid']}  {$title}\n              evidence: {$v['reason']}\n";
		} else {
			echo "WOULD RETIRE  {$n['uuid']}  {$title}\n              evidence: {$v['reason']}\n";
		}
		$superseded++;
	} elseif ($v['action'] === 'mark') {
		if ($apply) {
			$merged = $n['metadata'];
			$merged['reconciled'] = $v['evidence'] + [
				'reconciled_at' => gmdate('c'),
				'reconciled_by' => 'bin/reconcile-inbox.php',
			];
			$stmt = $db->prepare(
				'UPDATE notifications
				    SET wing_inbox_read_at = :now, metadata_json = :meta
				  WHERE uuid = :uuid AND wing_inbox_read_at IS NULL'
			);
			$stmt->bindValue(':now', gmdate('c'), SQLITE3_TEXT);
			$stmt->bindValue(':meta', json_encode($merged), SQLITE3_TEXT);
			$stmt->bindValue(':uuid', $n['uuid'], SQLITE3_TEXT);
			$stmt->execute();
			echo "MARKED READ   {$n['uuid']}  {$title}\n              evidence: {$v['reason']}\n";
		} else {
			echo "WOULD MARK    {$n['uuid']}  {$title}\n              evidence: {$v['reason']}\n";
		}
		$marked++;
	} elseif ($v['action'] === 'unreadable') {
		$unreadable++;
		echo "SOURCE UNREADABLE  {$n['uuid']}  {$title}\n              {$v['reason']}\n";
	} else {
		$left++;
		echo "LEFT UNREAD   {$n['uuid']}  {$title}\n              {$v['reason']}\n";
	}
}

$mode = $apply ? 'apply' : 'DRY RUN';
echo "reconcile-inbox ({$mode}): " . count($rows) . " unread — "
	. "{$marked} " . ($apply ? 'marked read' : 'markable') . ", "
	. "{$superseded} " . ($apply ? 'retired' : 'retirable') . ", {$left} left on evidence, "
	. "{$unreadable} source-unreadable, {$unclassified} unclassified\n";

exit($unreadable > 0 ? 2 : 0);
