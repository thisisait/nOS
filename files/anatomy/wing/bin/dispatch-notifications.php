<?php

declare(strict_types=1);

/**
 * Wing notification dispatch worker (Anatomy A9, 2026-05-16).
 *
 * Reads pending notifications from wing.db (channels_json contains "ntfy" or
 * "mail" AND the matching *_dispatched_at column is NULL), delivers them, and
 * stamps the per-channel dispatched_at + error column on the row.
 *
 * Designed for Pulse-eligible execution (runner=subprocess, every minute by
 * default) — idempotent, partial-failure-safe, no lock files (per-row
 * dispatched_at marker is the lock).
 *
 * Channels:
 *   ntfy  — HTTP POST to NTFY_URL/nos-<severity> with title + body
 *   mail  — Raw SMTP to MAIL_HOST:MAIL_PORT (dev-mode: no TLS, no auth,
 *           targeted at mailpit). Stalwart TLS path is future work — the
 *           script no-ops with a clear log if MAIL_HOST is empty.
 *
 * Env vars (read at startup):
 *   WING_DB_PATH           default: ~/wing/app/data/wing.db
 *   NTFY_URL               default: http://127.0.0.1:2586    (empty = skip)
 *   MAIL_HOST              default: 127.0.0.1                (empty = skip)
 *   MAIL_PORT              default: 1025
 *   MAIL_FROM              default: wing@dev.local
 *   MAIL_RECIPIENT         required if MAIL_HOST set (operator address)
 *   DISPATCH_BATCH_LIMIT   default: 50 per channel per run
 *   DISPATCH_DRY_RUN       1 = log only, do not deliver, do not stamp
 *
 * Exit codes:
 *   0  — clean run (zero or more deliveries, no fatal errors)
 *   1  — fatal: schema missing, DB unreadable
 *   2  — partial: at least one delivery failed (notification stamped with
 *        error, but the run completed — Pulse re-tries on next tick)
 */

$wingDb = getenv('WING_DB_PATH') ?: ($_SERVER['HOME'] . '/wing/app/data/wing.db');
$ntfyUrl = getenv('NTFY_URL') ?: 'http://127.0.0.1:2586';
$mailHost = getenv('MAIL_HOST') ?: '127.0.0.1';
$mailPort = (int) (getenv('MAIL_PORT') ?: 1025);
$mailFrom = getenv('MAIL_FROM') ?: 'wing@dev.local';
$mailRecipient = getenv('MAIL_RECIPIENT') ?: '';
$batchLimit = (int) (getenv('DISPATCH_BATCH_LIMIT') ?: 50);
$dryRun = (getenv('DISPATCH_DRY_RUN') === '1');

// 2026-05-17: TLS + auth support for Stalwart (Track G production mail).
// MAIL_TLS_MODE:
//   none      — raw SMTP (default; mailpit dev sink)
//   starttls  — EHLO → STARTTLS → wrap socket → EHLO → AUTH LOGIN
//                 (Stalwart submission port 587)
//   implicit  — wrap socket BEFORE EHLO → AUTH LOGIN
//                 (Stalwart SMTPS port 465)
// MAIL_USERNAME / MAIL_PASSWORD — used in AUTH LOGIN when TLS mode set.
// MAIL_TLS_VERIFY (default "1") — set to "0" only for self-signed dev certs.
$mailTlsMode = strtolower(getenv('MAIL_TLS_MODE') ?: 'none');
$mailUsername = getenv('MAIL_USERNAME') ?: '';
$mailPassword = getenv('MAIL_PASSWORD') ?: '';
$mailTlsVerify = (getenv('MAIL_TLS_VERIFY') ?: '1') !== '0';

// A9 daily-digest (2026-05-17): rows at severity ≤ DIGEST_FLOOR with `mail`
// in channels get queued via mail_digest_window instead of immediate-sent.
// The separate daily worker (run via DISPATCH_DIGEST_FLUSH=1) batches them
// into one summary email. Severities ABOVE the floor always fire immediate.
// Floor `none` disables digest behavior (all mail fires immediate — pre-A9
// daily-digest behavior).
$digestFloor = strtolower(getenv('DISPATCH_MAIL_DIGEST_FLOOR') ?: 'medium');
$digestFlushMode = (getenv('DISPATCH_DIGEST_FLUSH') === '1');

$severityRank = ['critical' => 0, 'high' => 1, 'medium' => 2, 'low' => 3, 'info' => 4];
$digestFloorRank = $severityRank[$digestFloor] ?? -1;  // -1 = digest disabled
// Sanity: if operator passes "none" or unknown, treat as -1 (no digest).

if (!file_exists($wingDb)) {
	fwrite(STDERR, "fatal: wing.db not found at {$wingDb}\n");
	exit(1);
}

try {
	$db = new SQLite3($wingDb);
	$db->enableExceptions(true);
} catch (\Throwable $exc) {
	fwrite(STDERR, "fatal: cannot open wing.db: {$exc->getMessage()}\n");
	exit(1);
}

$partial = false;
$delivered = ['ntfy' => 0, 'mail' => 0];
$failed    = ['ntfy' => 0, 'mail' => 0];

/**
 * Fetch pending rows for a channel — the channel must appear in
 * channels_json AND the per-channel dispatched_at column must be NULL.
 *
 * For the mail channel additionally excludes rows already queued for the
 * daily digest (mail_digest_window IS NOT NULL) so the per-minute worker
 * doesn't re-process them.
 */
function fetch_pending(SQLite3 $db, string $channel, int $limit): array
{
	$col = $channel === 'ntfy' ? 'ntfy_dispatched_at' : 'mail_dispatched_at';
	$digestExclusion = $channel === 'mail' ? ' AND mail_digest_window IS NULL' : '';
	$stmt = $db->prepare("
		SELECT id, uuid, severity, title, body, channels_json, metadata_json,
		       actor_id, origin_plugin, origin_agent, created_at
		  FROM notifications
		 WHERE {$col} IS NULL
		   AND channels_json LIKE :pattern{$digestExclusion}
		 ORDER BY id ASC
		 LIMIT :limit
	");
	$stmt->bindValue(':pattern', '%"' . $channel . '"%', SQLITE3_TEXT);
	$stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
	$res = $stmt->execute();
	$rows = [];
	while ($r = $res->fetchArray(SQLITE3_ASSOC)) {
		$r['channels'] = json_decode($r['channels_json'] ?? '[]', true) ?: [];
		$r['metadata'] = json_decode($r['metadata_json'] ?? '{}', true) ?: [];
		$rows[] = $r;
	}
	return $rows;
}

function mark_dispatched(SQLite3 $db, string $uuid, string $channel, ?string $error): void
{
	$tsCol  = $channel === 'ntfy' ? 'ntfy_dispatched_at' : 'mail_dispatched_at';
	$errCol = $channel === 'ntfy' ? 'ntfy_error'         : 'mail_error';
	$now = gmdate('c');
	if ($error === null || $error === '') {
		$stmt = $db->prepare("UPDATE notifications SET {$tsCol} = :ts WHERE uuid = :uuid");
		$stmt->bindValue(':ts', $now, SQLITE3_TEXT);
	} else {
		$stmt = $db->prepare("UPDATE notifications SET {$tsCol} = :ts, {$errCol} = :err WHERE uuid = :uuid");
		$stmt->bindValue(':ts', $now, SQLITE3_TEXT);
		$stmt->bindValue(':err', substr($error, 0, 500), SQLITE3_TEXT);
	}
	$stmt->bindValue(':uuid', $uuid, SQLITE3_TEXT);
	$stmt->execute();
}

/**
 * Queue a row for daily-digest mail (A9 daily-digest, 2026-05-17). Stamps
 * mail_digest_window with the queue-entry time; mail_dispatched_at stays
 * NULL until the digest worker flushes the queue.
 */
function queue_for_digest(SQLite3 $db, string $uuid): void
{
	$stmt = $db->prepare(
		"UPDATE notifications SET mail_digest_window = :ts
		 WHERE uuid = :uuid AND mail_digest_window IS NULL AND mail_dispatched_at IS NULL"
	);
	$stmt->bindValue(':ts', gmdate('c'), SQLITE3_TEXT);
	$stmt->bindValue(':uuid', $uuid, SQLITE3_TEXT);
	$stmt->execute();
}

/**
 * Read every row queued for digest mail (mail_digest_window IS NOT NULL,
 * mail_dispatched_at IS NULL). The digest flush worker batches these.
 * @return array<int,array<string,mixed>>
 */
function fetch_digest_queue(SQLite3 $db, int $limit = 500): array
{
	$stmt = $db->prepare("
		SELECT id, uuid, severity, title, body, channels_json, metadata_json,
		       actor_id, origin_plugin, origin_agent, created_at, mail_digest_window
		  FROM notifications
		 WHERE mail_digest_window IS NOT NULL
		   AND mail_dispatched_at IS NULL
		 ORDER BY id ASC
		 LIMIT :limit
	");
	$stmt->bindValue(':limit', $limit, SQLITE3_INTEGER);
	$res = $stmt->execute();
	$rows = [];
	while ($r = $res->fetchArray(SQLITE3_ASSOC)) {
		$r['channels'] = json_decode($r['channels_json'] ?? '[]', true) ?: [];
		$r['metadata'] = json_decode($r['metadata_json'] ?? '{}', true) ?: [];
		$rows[] = $r;
	}
	return $rows;
}

/**
 * Deliver an aggregated digest mail. One SMTP transaction → one email
 * summarizing N notifications grouped by severity. Returns null on success.
 */
function deliver_mail_digest(array $rows, string $host, int $port, string $from, string $recipient): ?string
{
	global $mailTlsMode, $mailUsername, $mailPassword, $mailTlsVerify;
	if ($recipient === '') {
		return 'MAIL_RECIPIENT env var is empty';
	}
	if (!$rows) {
		return null;
	}
	$sockOrErr = _smtp_open_session($host, $port, $mailTlsMode, $mailUsername, $mailPassword, $mailTlsVerify);
	if (is_string($sockOrErr)) {
		return $sockOrErr;
	}
	$sock = $sockOrErr;
	stream_set_timeout($sock, 5);

	$expect = function (string $expectedPrefix) use ($sock): ?string {
		$line = fgets($sock, 1024);
		if ($line === false) return 'SMTP read timed out';
		if (strpos($line, $expectedPrefix) !== 0) return 'SMTP unexpected reply: ' . trim($line);
		return null;
	};
	$send = function (string $line) use ($sock): void { fwrite($sock, $line . "\r\n"); };

	$send('MAIL FROM:<' . $from . '>');
	if (($err = $expect('250')) !== null) { fclose($sock); return $err; }
	$send('RCPT TO:<' . $recipient . '>');
	if (($err = $expect('250')) !== null) { fclose($sock); return $err; }
	$send('DATA');
	if (($err = $expect('354')) !== null) { fclose($sock); return $err; }

	// Group rows by severity for readable summary.
	$bySev = [];
	foreach ($rows as $r) {
		$bySev[$r['severity']][] = $r;
	}
	$severityOrder = ['critical', 'high', 'medium', 'low', 'info'];

	$total = count($rows);
	$subject = "[nOS] Daily digest: {$total} notification(s) — " . date('Y-m-d');

	$body = "nOS notification digest — " . gmdate('Y-m-d H:i:s') . " UTC\n";
	$body .= "{$total} notifications across this window.\n\n";
	foreach ($severityOrder as $sev) {
		if (empty($bySev[$sev])) continue;
		$body .= "── " . strtoupper($sev) . " (" . count($bySev[$sev]) . ") ────────────────\n";
		foreach ($bySev[$sev] as $r) {
			$origin = !empty($r['origin_plugin']) ? "plugin:{$r['origin_plugin']}"
			       : (!empty($r['origin_agent'])  ? "agent:{$r['origin_agent']}"
			       : ($r['actor_id'] ?? 'unknown'));
			$ts = substr((string) $r['created_at'], 0, 19);
			$body .= "  [{$ts}] {$r['title']} (by {$origin})\n";
			if (!empty($r['body'])) {
				$summary = trim(preg_replace('/\s+/', ' ', (string) $r['body']));
				if (strlen($summary) > 200) $summary = substr($summary, 0, 200) . '…';
				$body .= "    " . $summary . "\n";
			}
		}
		$body .= "\n";
	}
	$body .= "─── End of digest ───\n";
	$body .= "Open Wing /inbox to mark items read.\n";

	$msg = "From: nOS Wing <{$from}>\r\n";
	$msg .= "To: <{$recipient}>\r\n";
	$msg .= "Subject: {$subject}\r\n";
	$msg .= "X-NOS-Digest: 1\r\n";
	$msg .= "X-NOS-Digest-Count: {$total}\r\n";
	$msg .= "Content-Type: text/plain; charset=utf-8\r\n";
	$msg .= "\r\n";
	$msg .= $body;
	$msg = preg_replace('/^\./m', '..', $msg);
	$send($msg);
	$send('.');
	if (($err = $expect('250')) !== null) { fclose($sock); return $err; }
	$send('QUIT');
	fclose($sock);
	return null;
}

/**
 * Deliver one notification to ntfy. Topic = nos-<severity>. Title + body
 * become the ntfy headers/body. Returns null on success, error string on
 * failure.
 */
function deliver_ntfy(array $row, string $baseUrl): ?string
{
	$topic = 'nos-' . strtolower($row['severity']);
	$url = rtrim($baseUrl, '/') . '/' . rawurlencode($topic);

	$priority = match (strtolower($row['severity'])) {
		'critical' => '5',
		'high'     => '4',
		'medium'   => '3',
		'low'      => '2',
		default    => '1',
	};

	$tagMap = ['critical' => 'rotating_light', 'high' => 'warning', 'medium' => 'large_orange_diamond', 'low' => 'information_source', 'info' => 'speech_balloon'];
	$tag = $tagMap[strtolower($row['severity'])] ?? 'speech_balloon';

	$headers = [
		'Title: ' . substr($row['title'], 0, 250),
		'Priority: ' . $priority,
		'Tags: ' . $tag,
	];
	$click = $row['metadata']['click_url'] ?? null;
	if ($click) {
		$headers[] = 'Click: ' . $click;
	}

	$ch = curl_init($url);
	curl_setopt_array($ch, [
		CURLOPT_RETURNTRANSFER => true,
		CURLOPT_POST           => true,
		CURLOPT_POSTFIELDS     => (string) ($row['body'] ?? ''),
		CURLOPT_HTTPHEADER     => $headers,
		CURLOPT_TIMEOUT        => 5,
		CURLOPT_CONNECTTIMEOUT => 3,
	]);
	$resp = curl_exec($ch);
	$status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
	$cerr   = curl_error($ch);
	// curl_close() deprecated in PHP 8.5 (no-op since 8.0). Let $ch fall out of scope.
	unset($ch);

	if ($resp === false || $status === 0) {
		return "ntfy unreachable at {$url}: {$cerr}";
	}
	if ($status >= 400) {
		return "ntfy HTTP {$status}: " . substr((string) $resp, 0, 200);
	}
	return null;
}

/**
 * Deliver one notification via raw SMTP. No TLS, no auth — targeted at the
 * mailpit dev sink. Returns null on success, error string on failure.
 *
 * Stalwart-over-TLS path is future work; if MAIL_HOST is on a non-loopback
 * address operators must front it with something that strips/handles TLS
 * (or wait for the Stalwart-aware rewrite). This script intentionally stays
 * thin so the dispatch loop remains debuggable.
 */
/**
 * Open an SMTP socket and complete pre-MAIL setup: 220 greeting, EHLO,
 * optional STARTTLS upgrade, optional AUTH LOGIN. Returns the socket on
 * success, or a string error message on failure. Callers must
 * `fclose($sock)` themselves when done.
 *
 * 2026-05-17: Track G follow-on — adds Stalwart-compatible
 * starttls (587) + implicit (465) TLS + AUTH LOGIN support. Pre-this
 * the worker only spoke raw SMTP for the mailpit dev sink. Mode
 * resolution lives at module-load time (see $mailTlsMode / $mailUsername
 * / $mailPassword / $mailTlsVerify globals).
 *
 * @return resource|string  Socket resource on success; error string on failure.
 */
function _smtp_open_session(
	string $host,
	int $port,
	string $tlsMode,        // 'none' | 'starttls' | 'implicit'
	string $username,
	string $password,
	bool $tlsVerify,
) {
	$errno = 0;
	$errstr = '';
	$transport = $tlsMode === 'implicit' ? "tls://{$host}" : $host;
	$ctxOpts = [];
	if ($tlsMode !== 'none' && !$tlsVerify) {
		$ctxOpts['ssl'] = [
			'verify_peer' => false,
			'verify_peer_name' => false,
			'allow_self_signed' => true,
		];
	}
	$ctx = stream_context_create($ctxOpts);
	$sock = @stream_socket_client(
		"tcp://{$transport}:{$port}",
		$errno, $errstr, 5,
		STREAM_CLIENT_CONNECT,
		$ctx,
	);
	if (!$sock && $tlsMode === 'implicit') {
		// Retry via the tls:// transport syntax (some PHP builds want it
		// in the URI rather than as a context flag).
		$sock = @stream_socket_client(
			"tls://{$host}:{$port}",
			$errno, $errstr, 5,
			STREAM_CLIENT_CONNECT,
			$ctx,
		);
	}
	if (!$sock) {
		return "SMTP connect failed {$host}:{$port}: {$errstr}";
	}
	stream_set_timeout($sock, 5);

	$expect = function (string $expectedPrefix) use ($sock): ?string {
		$line = fgets($sock, 1024);
		if ($line === false) return 'SMTP read timed out';
		if (strpos($line, $expectedPrefix) !== 0) return 'SMTP unexpected reply: ' . trim($line);
		return null;
	};
	$send = function (string $line) use ($sock): void {
		fwrite($sock, $line . "\r\n");
	};
	$drain250 = function () use ($sock): void {
		while (($line = fgets($sock, 1024)) !== false) {
			if (preg_match('/^\d{3} /', $line)) break;
		}
	};

	if (($err = $expect('220')) !== null) { fclose($sock); return $err; }
	$send('EHLO wing.localhost');
	$drain250();

	if ($tlsMode === 'starttls') {
		$send('STARTTLS');
		if (($err = $expect('220')) !== null) { fclose($sock); return $err; }
		$ok = @stream_socket_enable_crypto($sock, true, STREAM_CRYPTO_METHOD_TLS_CLIENT);
		if (!$ok) { fclose($sock); return 'STARTTLS upgrade failed'; }
		$send('EHLO wing.localhost');
		$drain250();
	}

	if ($tlsMode !== 'none' && $username !== '' && $password !== '') {
		$send('AUTH LOGIN');
		if (($err = $expect('334')) !== null) { fclose($sock); return $err; }
		$send(base64_encode($username));
		if (($err = $expect('334')) !== null) { fclose($sock); return $err; }
		$send(base64_encode($password));
		if (($err = $expect('235')) !== null) { fclose($sock); return "AUTH LOGIN: {$err}"; }
	}

	return $sock;
}


function deliver_mail(array $row, string $host, int $port, string $from, string $recipient): ?string
{
	global $mailTlsMode, $mailUsername, $mailPassword, $mailTlsVerify;
	if ($recipient === '') {
		return 'MAIL_RECIPIENT env var is empty';
	}
	$sockOrErr = _smtp_open_session($host, $port, $mailTlsMode, $mailUsername, $mailPassword, $mailTlsVerify);
	if (is_string($sockOrErr)) {
		return $sockOrErr;
	}
	$sock = $sockOrErr;
	stream_set_timeout($sock, 5);

	$expect = function (string $expectedPrefix) use ($sock): ?string {
		$line = fgets($sock, 1024);
		if ($line === false) return 'SMTP read timed out';
		if (strpos($line, $expectedPrefix) !== 0) return 'SMTP unexpected reply: ' . trim($line);
		return null;
	};
	$send = function (string $line) use ($sock): void {
		fwrite($sock, $line . "\r\n");
	};

	$send('MAIL FROM:<' . $from . '>');
	if (($err = $expect('250')) !== null) { fclose($sock); return $err; }
	$send('RCPT TO:<' . $recipient . '>');
	if (($err = $expect('250')) !== null) { fclose($sock); return $err; }
	$send('DATA');
	if (($err = $expect('354')) !== null) { fclose($sock); return $err; }

	$subject = '[nOS][' . strtoupper($row['severity']) . '] ' . substr($row['title'], 0, 200);
	$bodyText = ($row['body'] ?? '');
	$origin = '';
	if (!empty($row['origin_plugin'])) {
		$origin = 'plugin:' . $row['origin_plugin'];
	} elseif (!empty($row['origin_agent'])) {
		$origin = 'agent:' . $row['origin_agent'];
	} elseif (!empty($row['actor_id'])) {
		$origin = $row['actor_id'];
	}

	$msg = "From: nOS Wing <{$from}>\r\n";
	$msg .= "To: <{$recipient}>\r\n";
	$msg .= "Subject: {$subject}\r\n";
	$msg .= "X-NOS-Severity: {$row['severity']}\r\n";
	$msg .= "X-NOS-Origin: {$origin}\r\n";
	$msg .= "X-NOS-Notification-UUID: {$row['uuid']}\r\n";
	$msg .= "Content-Type: text/plain; charset=utf-8\r\n";
	$msg .= "\r\n";
	$msg .= $bodyText;
	// SMTP dot-stuffing — escape leading dots so "." on its own line stays an end marker.
	$msg = preg_replace('/^\./m', '..', $msg);
	$send($msg);
	$send('.');
	if (($err = $expect('250')) !== null) { fclose($sock); return $err; }
	$send('QUIT');
	fclose($sock);
	return null;
}

// ── Process ntfy channel ────────────────────────────────────────────────
if ($ntfyUrl === '') {
	echo "ntfy: skipped (NTFY_URL empty)\n";
} else {
	$rows = fetch_pending($db, 'ntfy', $batchLimit);
	echo "ntfy: " . count($rows) . " pending\n";
	foreach ($rows as $row) {
		if ($dryRun) {
			echo "  DRYRUN ntfy {$row['uuid']} [{$row['severity']}] {$row['title']}\n";
			continue;
		}
		$err = deliver_ntfy($row, $ntfyUrl);
		mark_dispatched($db, $row['uuid'], 'ntfy', $err);
		if ($err === null) {
			$delivered['ntfy']++;
			echo "  OK ntfy {$row['uuid']}\n";
		} else {
			$failed['ntfy']++;
			$partial = true;
			echo "  FAIL ntfy {$row['uuid']}: {$err}\n";
		}
	}
}

// ── Process mail channel ────────────────────────────────────────────────
// Two modes:
//   * normal (default) — split pending mail rows by severity. Rows above
//     DISPATCH_MAIL_DIGEST_FLOOR fire immediately; the rest get queued
//     via mail_digest_window for the daily digest flush.
//   * digest-flush (DISPATCH_DIGEST_FLUSH=1) — read every row with
//     mail_digest_window IS NOT NULL AND mail_dispatched_at IS NULL,
//     send ONE aggregated email, stamp all rows as dispatched at once.
//     This is the daily cron path.
if ($mailHost === '' || $mailRecipient === '') {
	echo "mail: skipped (MAIL_HOST or MAIL_RECIPIENT empty)\n";
} elseif ($digestFlushMode) {
	$rows = fetch_digest_queue($db, 500);
	echo "mail-digest: " . count($rows) . " queued row(s)\n";
	if (count($rows) === 0) {
		echo "  no digest queue to flush\n";
	} elseif ($dryRun) {
		foreach ($rows as $row) {
			echo "  DRYRUN digest-include {$row['uuid']} [{$row['severity']}] {$row['title']}\n";
		}
	} else {
		$err = deliver_mail_digest($rows, $mailHost, $mailPort, $mailFrom, $mailRecipient);
		if ($err === null) {
			foreach ($rows as $row) {
				mark_dispatched($db, $row['uuid'], 'mail', null);
				$delivered['mail']++;
			}
			echo "  OK digest dispatched (" . count($rows) . " rows)\n";
		} else {
			// Failure: mark all rows with the error but don't set dispatched_at
			// so they roll into the next digest attempt. Stamp each row's
			// mail_error explicitly via a single statement per row.
			$stmt = $db->prepare("UPDATE notifications SET mail_error = :err WHERE uuid = :uuid");
			foreach ($rows as $row) {
				$stmt->bindValue(':err', substr($err, 0, 500), SQLITE3_TEXT);
				$stmt->bindValue(':uuid', $row['uuid'], SQLITE3_TEXT);
				$stmt->execute();
				$stmt->reset();
				$failed['mail']++;
			}
			$partial = true;
			echo "  FAIL digest: {$err}\n";
		}
	}
} else {
	$rows = fetch_pending($db, 'mail', $batchLimit);
	echo "mail: " . count($rows) . " pending (digest_floor={$digestFloor})\n";
	foreach ($rows as $row) {
		$rowRank = $severityRank[$row['severity']] ?? 4;
		// `rowRank > digestFloorRank` means the row's severity ranks LOWER
		// (less severe) than the floor → queue for digest. Equal-floor rows
		// digest too (floor name describes the highest severity that gets
		// digested — e.g. floor=medium means medium+low+info digest).
		if ($digestFloorRank >= 0 && $rowRank >= $digestFloorRank) {
			if ($dryRun) {
				echo "  DRYRUN queue-digest {$row['uuid']} [{$row['severity']}] {$row['title']}\n";
			} else {
				queue_for_digest($db, $row['uuid']);
				echo "  QUEUE mail {$row['uuid']} → digest\n";
			}
			continue;
		}
		if ($dryRun) {
			echo "  DRYRUN mail {$row['uuid']} [{$row['severity']}] {$row['title']}\n";
			continue;
		}
		$err = deliver_mail($row, $mailHost, $mailPort, $mailFrom, $mailRecipient);
		mark_dispatched($db, $row['uuid'], 'mail', $err);
		if ($err === null) {
			$delivered['mail']++;
			echo "  OK mail {$row['uuid']}\n";
		} else {
			$failed['mail']++;
			$partial = true;
			echo "  FAIL mail {$row['uuid']}: {$err}\n";
		}
	}
}

$db->close();

echo "summary: delivered ntfy={$delivered['ntfy']} mail={$delivered['mail']}; failed ntfy={$failed['ntfy']} mail={$failed['mail']}\n";

exit($partial ? 2 : 0);
