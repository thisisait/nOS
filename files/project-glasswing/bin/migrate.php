<?php

declare(strict_types=1);

/**
 * Glasswing — One-time JSON to SQLite data migration.
 * Usage: php bin/migrate.php --json-dir=/path/to/docs/llm/security
 */

$jsonDir = null;
$dataDir = null;
foreach ($argv as $arg) {
	if (str_starts_with($arg, '--json-dir=')) {
		$jsonDir = substr($arg, 11);
	}
	if (str_starts_with($arg, '--data-dir=')) {
		$dataDir = substr($arg, 11);
	}
}
$dataDir ??= __DIR__ . '/../data';
$dbPath = $dataDir . '/glasswing.db';

if (!$jsonDir || !is_dir($jsonDir)) {
	echo "Usage: php bin/migrate.php --json-dir=/path/to/docs/llm/security\n";
	exit(1);
}

if (!file_exists($dbPath)) {
	echo "Database not found at $dbPath. Run bin/init-db.php first.\n";
	exit(1);
}

$db = new SQLite3($dbPath);
$db->enableExceptions(true);
$db->exec('PRAGMA journal_mode = WAL');
$db->exec('PRAGMA foreign_keys = ON');

// Check if already migrated
$count = $db->querySingle('SELECT COUNT(*) FROM components');
if ($count > 0) {
	echo "Already migrated ($count components in database). Skipping.\n";
	$db->close();
	exit(0);
}

$stats = [
	'components' => 0, 'remediation' => 0, 'targets' => 0,
	'advisories' => 0, 'areas_tested' => 0, 'areas_planned' => 0,
	'findings' => 0, 'probes' => 0,
];

$db->exec('BEGIN TRANSACTION');

try {
	// 1. versions.json -> components
	$versionsFile = $jsonDir . '/versions.json';
	if (file_exists($versionsFile)) {
		$data = json_decode(file_get_contents($versionsFile), true);
		$components = $data['components'] ?? $data;

		$stmt = $db->prepare(
			'INSERT OR IGNORE INTO components
			(id, name, category, stack, image, version_var, default_version, pinned, network_exposed, has_web_ui, priority, upstream_repo, port, domain)
			VALUES (:id, :name, :category, :stack, :image, :version_var, :default_version, :pinned, :network_exposed, :has_web_ui, :priority, :upstream_repo, :port, :domain)'
		);

		foreach ($components as $comp) {
			$stmt->bindValue(':id', $comp['id']);
			$stmt->bindValue(':name', $comp['name']);
			$stmt->bindValue(':category', $comp['category'] ?? 'docker');
			$stmt->bindValue(':stack', $comp['stack'] ?? null);
			$stmt->bindValue(':image', $comp['image'] ?? null);
			$stmt->bindValue(':version_var', $comp['version_var'] ?? null);
			$stmt->bindValue(':default_version', $comp['default_version'] ?? null);
			$stmt->bindValue(':pinned', (int) ($comp['pinned'] ?? true));
			$stmt->bindValue(':network_exposed', (int) ($comp['network_exposed'] ?? false));
			$stmt->bindValue(':has_web_ui', (int) ($comp['has_web_ui'] ?? false));
			$stmt->bindValue(':priority', $comp['priority'] ?? 'medium');
			$stmt->bindValue(':upstream_repo', $comp['upstream_repo'] ?? null);
			$stmt->bindValue(':port', $comp['port'] ?? null);
			$stmt->bindValue(':domain', $comp['domain'] ?? null);
			$stmt->execute();
			$stmt->reset();
			$stats['components']++;
		}
		echo "  components: {$stats['components']}\n";
	}

	// 2. scan-state.json -> scan_config + component_scan_state + attack_probes
	$scanFile = $jsonDir . '/scan-state.json';
	if (file_exists($scanFile)) {
		$data = json_decode(file_get_contents($scanFile), true);
		$config = $data['config'] ?? [];

		// Update scan_config singleton
		$cfgStmt = $db->prepare(
			'UPDATE scan_config SET
			batch_size=:bs, schedule=:sch, strategy=:str, cve_refresh_interval_hours=:crih,
			misconfig_refresh_interval_days=:mrid, attack_probe_rotation_size=:aprs,
			scanner_version=:sv, last_full_scan=:lfs, last_advisory_check=:lac,
			last_remediation_applied=:lra, next_batch=:nb WHERE id=1'
		);
		$cfgStmt->bindValue(':bs', $config['batch_size'] ?? 5);
		$cfgStmt->bindValue(':sch', $config['schedule'] ?? '2x daily (06:00, 18:00)');
		$cfgStmt->bindValue(':str', $config['strategy'] ?? 'oldest_first');
		$cfgStmt->bindValue(':crih', $config['cve_refresh_interval_hours'] ?? 24);
		$cfgStmt->bindValue(':mrid', $config['misconfig_refresh_interval_days'] ?? 7);
		$cfgStmt->bindValue(':aprs', $config['attack_probe_rotation_size'] ?? 8);
		$cfgStmt->bindValue(':sv', $config['scanner_version'] ?? '1.0.0');
		$cfgStmt->bindValue(':lfs', $data['last_full_scan'] ?? null);
		$cfgStmt->bindValue(':lac', $data['last_advisory_check'] ?? null);
		$cfgStmt->bindValue(':lra', $data['last_remediation_applied'] ?? null);
		$nb = $data['rotation']['next_batch'] ?? null;
		$cfgStmt->bindValue(':nb', $nb ? json_encode($nb) : null);
		$cfgStmt->execute();

		// component_scan_state
		$compStates = $data['components'] ?? [];
		$csStmt = $db->prepare(
			'INSERT OR IGNORE INTO component_scan_state
			(component_id, last_checked, last_cve_scan, last_misconfig_scan, last_attack_probe, findings_count, status)
			VALUES (:cid, :lc, :lcve, :lm, :la, :fc, :st)'
		);
		foreach ($compStates as $cid => $cs) {
			$csStmt->bindValue(':cid', $cid);
			$csStmt->bindValue(':lc', $cs['last_checked'] ?? null);
			$csStmt->bindValue(':lcve', $cs['last_cve_scan'] ?? null);
			$csStmt->bindValue(':lm', $cs['last_misconfig_scan'] ?? null);
			$csStmt->bindValue(':la', $cs['last_attack_probe'] ?? null);
			$csStmt->bindValue(':fc', $cs['findings_count'] ?? 0);
			$csStmt->bindValue(':st', $cs['status'] ?? 'pending');
			$csStmt->execute();
			$csStmt->reset();
		}

		// attack_probes
		$probes = $data['attack_probe_schedule'] ?? [];
		$probeStmt = $db->prepare(
			'INSERT OR IGNORE INTO attack_probes (cycle_mod, name, description, last_run, findings, completed)
			VALUES (:cm, :n, :d, :lr, :f, :c)'
		);
		foreach ($probes as $probe) {
			$probeStmt->bindValue(':cm', $probe['cycle_mod'] ?? 0);
			$probeStmt->bindValue(':n', $probe['name'] ?? '');
			$probeStmt->bindValue(':d', $probe['description'] ?? null);
			$probeStmt->bindValue(':lr', $probe['last_run'] ?? null);
			$probeStmt->bindValue(':f', $probe['findings'] ?? 0);
			$probeStmt->bindValue(':c', (int) ($probe['completed'] ?? false));
			$probeStmt->execute();
			$probeStmt->reset();
			$stats['probes']++;
		}

		// Synthetic initial cycle
		$cycleNum = $data['scan_cycle'] ?? $data['current_cycle'] ?? 0;
		$synStmt = $db->prepare('INSERT OR IGNORE INTO scan_cycles (cycle_number, notes) VALUES (:cn, :n)');
		$synStmt->bindValue(':cn', $cycleNum);
		$synStmt->bindValue(':n', 'Initial migration from scan-state.json');
		$synStmt->execute();

		echo "  scan_state: config + " . count($compStates) . " components + {$stats['probes']} probes\n";
	}

	// 3. remediation-queue.json -> remediation_items
	$remFile = $jsonDir . '/remediation-queue.json';
	if (file_exists($remFile)) {
		$data = json_decode(file_get_contents($remFile), true);
		$items = $data['items'] ?? $data;

		$stmt = $db->prepare(
			'INSERT OR IGNORE INTO remediation_items
			(id, finding_ref, component_id, severity, current_version, fix_version, remediation_type,
			remediation_detail, status, auto_fixable, source, confidence, found_at, resolved_at, scan_cycle)
			VALUES (:id, :fr, :cid, :sev, :cv, :fv, :rt, :rd, :st, :af, :src, :conf, :fa, :ra, :sc)'
		);

		foreach ($items as $item) {
			$stmt->bindValue(':id', $item['id']);
			$stmt->bindValue(':fr', $item['finding_ref'] ?? null);
			$stmt->bindValue(':cid', $item['component'] ?? null);
			$stmt->bindValue(':sev', $item['severity']);
			$stmt->bindValue(':cv', $item['current_version'] ?? null);
			$stmt->bindValue(':fv', $item['fix_version'] ?? null);
			$stmt->bindValue(':rt', $item['remediation_type'] ?? null);
			$stmt->bindValue(':rd', $item['remediation_detail'] ?? null);
			$stmt->bindValue(':st', $item['status'] ?? 'pending');
			$stmt->bindValue(':af', (int) ($item['auto_fixable'] ?? false));
			$stmt->bindValue(':src', $item['source'] ?? null);
			$stmt->bindValue(':conf', $item['confidence'] ?? 'medium');
			$stmt->bindValue(':fa', $item['found_at'] ?? date('c'));
			$stmt->bindValue(':ra', $item['resolved_at'] ?? null);
			$stmt->bindValue(':sc', $item['scan_cycle'] ?? null);
			$stmt->execute();
			$stmt->reset();
			$stats['remediation']++;
		}
		echo "  remediation: {$stats['remediation']}\n";
	}

	// 4. pentest-journal.json -> pentest_targets + areas + findings + patches
	$pentestFile = $jsonDir . '/pentest-journal.json';
	if (file_exists($pentestFile)) {
		$data = json_decode(file_get_contents($pentestFile), true);
		$targets = $data['targets'] ?? [];

		$tStmt = $db->prepare(
			'INSERT OR IGNORE INTO pentest_targets (id, component_id, version_tested, upstream_repo, language, attack_surface, status)
			VALUES (:id, :cid, :vt, :ur, :lang, :as, :st)'
		);
		$atStmt = $db->prepare(
			'INSERT OR IGNORE INTO pentest_areas_tested (target_id, area, date, technique, files_reviewed, result, details, next_steps)
			VALUES (:tid, :area, :date, :tech, :fr, :res, :det, :ns)'
		);
		$apStmt = $db->prepare(
			'INSERT OR IGNORE INTO pentest_areas_planned (target_id, area, description, files_of_interest, methods_of_interest, attack_class, priority, rationale)
			VALUES (:tid, :area, :desc, :foi, :moi, :ac, :pri, :rat)'
		);
		$fStmt = $db->prepare(
			'INSERT OR IGNORE INTO pentest_findings
			(id, target_id, severity, title, description, affected_versions, proof_of_concept, files,
			attack_class, exploitability, confidence, disclosure_status, upstream_issue, patch_pr,
			devboxnos_mitigation, remediation, found_at)
			VALUES (:id, :tid, :sev, :title, :desc, :av, :poc, :files, :ac, :exp, :conf, :ds, :ui, :pr, :dm, :rem, :fa)'
		);

		foreach ($targets as $target) {
			$tid = $target['id'];
			$tStmt->bindValue(':id', $tid);
			$tStmt->bindValue(':cid', $target['component'] ?? $tid);
			$tStmt->bindValue(':vt', $target['version_tested'] ?? null);
			$tStmt->bindValue(':ur', $target['upstream_repo'] ?? null);
			$tStmt->bindValue(':lang', $target['language'] ?? null);
			$tStmt->bindValue(':as', isset($target['attack_surface']) ? json_encode($target['attack_surface']) : null);
			$tStmt->bindValue(':st', $target['status'] ?? 'planned');
			$tStmt->execute();
			$tStmt->reset();
			$stats['targets']++;

			foreach ($target['areas_tested'] ?? [] as $at) {
				$atStmt->bindValue(':tid', $tid);
				$atStmt->bindValue(':area', $at['area']);
				$atStmt->bindValue(':date', $at['date'] ?? date('c'));
				$atStmt->bindValue(':tech', $at['technique'] ?? null);
				$atStmt->bindValue(':fr', isset($at['files_reviewed']) ? json_encode($at['files_reviewed']) : null);
				$atStmt->bindValue(':res', $at['result'] ?? 'no_findings');
				$atStmt->bindValue(':det', $at['details'] ?? null);
				$atStmt->bindValue(':ns', $at['next_steps'] ?? null);
				$atStmt->execute();
				$atStmt->reset();
				$stats['areas_tested']++;
			}

			foreach ($target['areas_planned'] ?? [] as $ap) {
				$apStmt->bindValue(':tid', $tid);
				$apStmt->bindValue(':area', $ap['area']);
				$apStmt->bindValue(':desc', $ap['description'] ?? null);
				$apStmt->bindValue(':foi', isset($ap['files_of_interest']) ? json_encode($ap['files_of_interest']) : null);
				$apStmt->bindValue(':moi', isset($ap['methods_of_interest']) ? json_encode($ap['methods_of_interest']) : null);
				$apStmt->bindValue(':ac', $ap['attack_class'] ?? null);
				$apStmt->bindValue(':pri', $ap['priority'] ?? 'medium');
				$apStmt->bindValue(':rat', $ap['rationale'] ?? null);
				$apStmt->execute();
				$apStmt->reset();
				$stats['areas_planned']++;
			}

			foreach ($target['findings'] ?? [] as $f) {
				$fStmt->bindValue(':id', $f['id']);
				$fStmt->bindValue(':tid', $tid);
				$fStmt->bindValue(':sev', $f['severity']);
				$fStmt->bindValue(':title', $f['title']);
				$fStmt->bindValue(':desc', $f['description'] ?? null);
				$fStmt->bindValue(':av', $f['affected_versions'] ?? null);
				$fStmt->bindValue(':poc', $f['proof_of_concept'] ?? null);
				$fStmt->bindValue(':files', isset($f['files']) ? json_encode($f['files']) : null);
				$fStmt->bindValue(':ac', $f['attack_class'] ?? null);
				$fStmt->bindValue(':exp', $f['exploitability'] ?? null);
				$fStmt->bindValue(':conf', $f['confidence'] ?? 'medium');
				$fStmt->bindValue(':ds', $f['disclosure_status'] ?? 'not_reported');
				$fStmt->bindValue(':ui', $f['upstream_issue'] ?? null);
				$fStmt->bindValue(':pr', $f['patch_pr'] ?? null);
				$fStmt->bindValue(':dm', $f['devboxnos_mitigation'] ?? null);
				$fStmt->bindValue(':rem', $f['remediation'] ?? null);
				$fStmt->bindValue(':fa', $f['found_at'] ?? date('c'));
				$fStmt->execute();
				$fStmt->reset();
				$stats['findings']++;
			}
		}

		// Patches from patch_development
		$patchData = $data['patch_development']['patches'] ?? [];
		$pStmt = $db->prepare(
			'INSERT OR IGNORE INTO patches (id, finding_ref, component_id, upstream_repo, description, patch_file, tests_added, upstream_pr, status)
			VALUES (:id, :fr, :cid, :ur, :desc, :pf, :ta, :up, :st)'
		);
		foreach ($patchData as $patch) {
			$pStmt->bindValue(':id', $patch['id']);
			$pStmt->bindValue(':fr', $patch['finding_ref'] ?? null);
			$pStmt->bindValue(':cid', $patch['component'] ?? null);
			$pStmt->bindValue(':ur', $patch['upstream_repo'] ?? null);
			$pStmt->bindValue(':desc', $patch['description'] ?? null);
			$pStmt->bindValue(':pf', $patch['patch_file'] ?? null);
			$pStmt->bindValue(':ta', $patch['tests_added'] ?? null);
			$pStmt->bindValue(':up', $patch['upstream_pr'] ?? null);
			$pStmt->bindValue(':st', $patch['status'] ?? 'draft');
			$pStmt->execute();
			$pStmt->reset();
		}

		echo "  pentest: {$stats['targets']} targets, {$stats['areas_tested']} tested, {$stats['areas_planned']} planned, {$stats['findings']} findings\n";
	}

	// 5. Advisory .md files -> advisories
	$mdFiles = glob($jsonDir . '/*-advisory.md');
	foreach ($mdFiles as $mdFile) {
		$filename = basename($mdFile);
		$text = file_get_contents($mdFile);

		preg_match('/^(\d{4}-\d{2}-\d{2})/', $filename, $m);
		$date = $m[1] ?? date('Y-m-d');

		$title = null;
		if (preg_match('/^#+\s*(.+)$/m', $text, $tm)) {
			$title = trim($tm[1]);
		}

		$hasCritical = (int) (stripos($text, 'CRITICAL') !== false);
		$hasPentest = (int) (preg_match('/PENTEST-\d+/', $text) === 1);

		$scanCycle = null;
		if (preg_match('/Scan Cycle\s*(\d+)/i', $text, $cm)) {
			$scanCycle = (int) $cm[1];
		}

		$advStmt = $db->prepare(
			'INSERT OR IGNORE INTO advisories (filename, title, date, has_critical, has_pentest, full_text, scan_cycle)
			VALUES (:fn, :t, :d, :hc, :hp, :ft, :sc)'
		);
		$advStmt->bindValue(':fn', $filename);
		$advStmt->bindValue(':t', $title);
		$advStmt->bindValue(':d', $date);
		$advStmt->bindValue(':hc', $hasCritical);
		$advStmt->bindValue(':hp', $hasPentest);
		$advStmt->bindValue(':ft', $text);
		$advStmt->bindValue(':sc', $scanCycle);
		$advStmt->execute();
		$stats['advisories']++;
	}
	if ($stats['advisories'] > 0) {
		echo "  advisories: {$stats['advisories']}\n";
	}

	$db->exec('COMMIT');
	echo "\nMigration complete. Totals: {$stats['components']} components, {$stats['remediation']} remediation, {$stats['targets']} targets, {$stats['advisories']} advisories\n";

} catch (\Throwable $e) {
	$db->exec('ROLLBACK');
	echo "Migration FAILED: " . $e->getMessage() . "\n";
	exit(1);
}

$db->close();
