<?php

declare(strict_types=1);

namespace App\AgentKit\Memory;

use App\AgentKit\Agent;
use App\AgentKit\AgentLoader;
use App\AgentKit\LLMClient\Factory as LLMFactory;
use App\AgentKit\LLMClient\LLMPermanentError;
use App\AgentKit\LLMClient\LLMTransientError;
use App\AgentKit\LLMClient\Message;
use App\AgentKit\Telemetry\AuditEmitter;
use App\Model\AgentSessionRepository;
use Symfony\Component\Yaml\Yaml;

/**
 * Dreams — async memory-consolidation cycle for an agent (post-A14, U-B-Dreams).
 *
 * Reads the LAST N agent_sessions for an agent, plus the current
 * agent_memory_stores entries, runs the agent's primary LLM under a strictly
 * read-only "dream" tool roster, and parses the LLM's strict-JSON response
 * to apply per-entry deltas (`create` / `update` / `delete`) to the store.
 *
 * Why a dedicated class instead of reusing Runner.run():
 *   - The Runner's run() signature is locked by U-B-MA's parallel scope
 *     partition; we cannot grow it with a "dream mode" parameter without
 *     creating a merge conflict.
 *   - Dream cycles need a different system prompt + a tool restriction the
 *     Runner does not enforce (the Runner will happily invoke any tool the
 *     agent declares; the Dreamer refuses any tool not in `dream.tool_roster`).
 *   - The output shape (deltas as strict JSON) is dream-cycle-specific.
 *
 * Tool roster restriction: the Dreamer issues the LLM call with NO tools
 * declared at all. The LLM is told to emit ONLY a single JSON document in
 * its end_turn text — no tool_use blocks. This is the strictest possible
 * read-only mode: even a future tool that *could* be in the dream roster
 * (mcp-wing-read, mcp-bone-read) is not surfaced to the LLM during a
 * dream call. The roster declared in agent.yml is recorded in audit logs
 * for forensic clarity but the runtime gate is structural: no tools, full
 * stop. This closes the contract requirement "the dream Runner MUST refuse
 * to invoke tools NOT in the dream roster" — by structurally never offering
 * any tool, the negative case (calling a forbidden tool) is unreachable.
 *
 * Telemetry: emits agent_session_start / agent_session_end events with a
 * trigger=dream marker; per-delta events fire as agent_message with
 * (uuid, title, length) payloads only — never the full content.
 */
final class Dreamer
{
	public const MAX_RECENT_SESSIONS = 200;
	public const MAX_STORE_LIMIT = 200;
	public const DEFAULT_RECENT = 50;
	public const DEFAULT_STORE_LIMIT = 20;

	public function __construct(
		private readonly AgentLoader $loader,
		private readonly LLMFactory $llmFactory,
		private readonly AgentSessionRepository $sessions,
		private readonly MemoryStore $memory,
		private readonly AuditEmitter $audit,
	) {
	}

	/**
	 * Run a dream cycle for the named agent.
	 *
	 * @return DreamResult
	 */
	public function dream(
		string $agentName,
		int $sessionLimit = self::DEFAULT_RECENT,
		int $storeLimit = self::DEFAULT_STORE_LIMIT,
		bool $dryRun = false,
	): DreamResult {
		$sessionLimit = max(1, min($sessionLimit, self::MAX_RECENT_SESSIONS));
		$storeLimit = max(1, min($storeLimit, self::MAX_STORE_LIMIT));

		$agent = $this->loader->load($agentName);
		$dreamCfg = $this->loadDreamConfig($agent);

		if (!$dreamCfg['enabled']) {
			throw new \RuntimeException(
				"Agent '{$agentName}' is not opted into the dream cycle " .
				"(agent.yml dream.enabled is not true)."
			);
		}

		// Bound by agent.yml::dream.max_entries (≤ storeLimit by design).
		$effectiveStoreLimit = min($storeLimit, $dreamCfg['max_entries']);

		$sizeBefore = $this->memory->size($agentName);
		$beforeEntries = $this->memory->recall($agentName, self::MAX_STORE_LIMIT);
		$recentSessions = $this->sessions->listRecent($sessionLimit, $agentName);

		$dreamSessionUuid = self::uuid();
		$traceId = self::traceId();

		$this->audit->emit(
			type: 'agent_session_start',
			actorActionId: $dreamSessionUuid,
			actorId: 'agent:' . $agentName,
			task: "dream:{$agentName}",
			result: [
				'trigger' => 'dream',
				'session_limit' => $sessionLimit,
				'store_limit' => $effectiveStoreLimit,
				'sessions_seen' => count($recentSessions),
				'store_size_before' => $sizeBefore,
				'declared_tool_roster' => $dreamCfg['tool_roster'],
				'dry_run' => $dryRun,
			],
			traceId: $traceId,
		);

		$llm = $this->llmFactory->fromUri($agent->modelPrimaryUri);
		$systemPrompt = $this->buildDreamSystemPrompt($agent, $dreamCfg);
		$userPrompt = $this->buildDreamUserPrompt(
			$agent,
			$beforeEntries,
			$recentSessions,
			$effectiveStoreLimit,
		);

		$messages = [Message::userText($userPrompt)];

		// Tool restriction enforcement (structural): pass an EMPTY tool list
		// to the LLM. The LLM has no way to invoke any tool — including ones
		// in dream.tool_roster — during a dream cycle. The roster is a future-
		// looking declaration recorded in audit; the actual runtime gate is
		// the empty $tools array below.
		try {
			$response = $llm->send($systemPrompt, $messages, [], 4096);
		} catch (LLMTransientError | LLMPermanentError $exc) {
			$this->audit->emit(
				type: 'agent_session_end',
				actorActionId: $dreamSessionUuid,
				actorId: 'agent:' . $agentName,
				task: "dream:{$agentName}",
				result: [
					'trigger' => 'dream',
					'stop_reason' => 'error',
					'error' => $exc->getMessage(),
				],
				traceId: $traceId,
			);
			throw $exc;
		}

		// Refuse any tool_use the LLM somehow emitted. By contract the LLM
		// should only emit JSON text since we passed no tools, but defence
		// in depth: fail loud rather than silently honouring a tool_use.
		if ($response->toolUseBlocks() !== []) {
			$this->audit->emit(
				type: 'agent_session_end',
				actorActionId: $dreamSessionUuid,
				actorId: 'agent:' . $agentName,
				task: "dream:{$agentName}",
				result: [
					'trigger' => 'dream',
					'stop_reason' => 'tool_use_refused',
					'reason' => 'dream cycle does not permit tool invocation',
				],
				traceId: $traceId,
			);
			throw new \RuntimeException(
				'Dream cycle response contained tool_use blocks; aborting (read-only enforcement).'
			);
		}

		$decisions = $this->parseDecisions($response->textOutput());
		$deltas = [];
		if (!$dryRun) {
			foreach ($decisions as $decision) {
				$deltas[] = $this->applyDecision($agentName, $decision, $dreamSessionUuid, $traceId);
			}
			$pruned = $this->memory->prune($agentName, $effectiveStoreLimit);
			if ($pruned > 0) {
				$deltas[] = [
					'action' => 'pruned',
					'count' => $pruned,
				];
			}
		} else {
			foreach ($decisions as $decision) {
				$deltas[] = [
					'action' => $decision['action'] ?? 'noop',
					'title' => $decision['title'] ?? '',
					'length' => isset($decision['content']) ? strlen((string) $decision['content']) : 0,
					'dry_run' => true,
				];
			}
		}

		$sizeAfter = $this->memory->size($agentName);

		$this->audit->emit(
			type: 'agent_session_end',
			actorActionId: $dreamSessionUuid,
			actorId: 'agent:' . $agentName,
			task: "dream:{$agentName}",
			result: [
				'trigger' => 'dream',
				'stop_reason' => 'end_turn',
				'sessions_scanned' => count($recentSessions),
				'store_size_before' => $sizeBefore,
				'store_size_after' => $sizeAfter,
				'deltas' => $deltas,
				'tokens' => [
					'input' => $response->tokensInput,
					'output' => $response->tokensOutput,
				],
			],
			traceId: $traceId,
		);

		return new DreamResult(
			agent: $agentName,
			sessionUuid: $dreamSessionUuid,
			traceId: $traceId,
			sessionsScanned: count($recentSessions),
			storeSizeBefore: $sizeBefore,
			storeSizeAfter: $sizeAfter,
			deltas: $deltas,
			tokensInput: $response->tokensInput,
			tokensOutput: $response->tokensOutput,
			dryRun: $dryRun,
		);
	}

	/**
	 * Parse + validate the agent.yml::dream block. Defaults match the schema:
	 * enabled=false, tool_roster=[], max_entries=20.
	 *
	 * @return array{enabled: bool, tool_roster: array<int, string>, max_entries: int}
	 */
	private function loadDreamConfig(Agent $agent): array
	{
		$yamlPath = $agent->sourceDir . '/agent.yml';
		$raw = Yaml::parseFile($yamlPath);
		$dreamRaw = $raw['dream'] ?? [];
		if (!is_array($dreamRaw)) {
			$dreamRaw = [];
		}
		$enabled = (bool) ($dreamRaw['enabled'] ?? false);
		$rosterRaw = $dreamRaw['tool_roster'] ?? [];
		$roster = [];
		if (is_array($rosterRaw)) {
			foreach ($rosterRaw as $id) {
				if (is_string($id)) {
					$roster[] = $id;
				}
			}
		}
		// Hard subset enforcement: only mcp-wing-read / mcp-bone-read are
		// permissible. Unknown ids are dropped silently in config but logged
		// at warn level via stderr to surface mis-config.
		$allowed = ['mcp-wing-read', 'mcp-bone-read'];
		$filtered = array_values(array_intersect($roster, $allowed));
		if (count($filtered) !== count($roster)) {
			$rejected = array_values(array_diff($roster, $allowed));
			error_log(
				"[dreamer] agent '{$agent->name}' dream.tool_roster has non-readonly entries " .
				'rejected: ' . implode(', ', $rejected)
			);
		}
		$maxEntries = (int) ($dreamRaw['max_entries'] ?? self::DEFAULT_STORE_LIMIT);
		if ($maxEntries < 1) {
			$maxEntries = self::DEFAULT_STORE_LIMIT;
		}
		if ($maxEntries > self::MAX_STORE_LIMIT) {
			$maxEntries = self::MAX_STORE_LIMIT;
		}
		return [
			'enabled' => $enabled,
			'tool_roster' => $filtered,
			'max_entries' => $maxEntries,
		];
	}

	/**
	 * @param array{enabled: bool, tool_roster: array<int, string>, max_entries: int} $cfg
	 */
	private function buildDreamSystemPrompt(Agent $agent, array $cfg): string
	{
		$base = $agent->systemPrompt ?? '';
		$dreaming = <<<TXT
You are now in DREAM MODE for the agent '{$agent->name}'. The dream cycle's
purpose is to consolidate the agent's memory store: distil recurring facts
from recent sessions, deduplicate against the existing store, and prune
stale entries.

You MAY NOT invoke any tools during this cycle. You have no tool roster.
Respond ONLY with a single JSON document in this exact shape:

{
  "decisions": [
    {"action": "create", "title": "<stable, short, dash-separated>", "content": "<markdown body>"},
    {"action": "update", "title": "<existing title>", "content": "<replacement markdown body>"},
    {"action": "delete", "title": "<existing title>"}
  ]
}

Rules:
 - Every "title" MUST be stable across cycles — it is the deduplication key.
 - "content" SHOULD be Markdown, no front-matter, ≤ 4 KiB per entry.
 - Maximum {$cfg['max_entries']} total live entries after this cycle.
 - If you have nothing to change, return {"decisions": []}.
 - Do NOT include text outside the JSON document.

The original agent system prompt follows for context but does NOT override
these dream rules.

— BEGIN ORIGINAL SYSTEM PROMPT —
TXT;
		return $dreaming . "\n" . $base . "\n— END ORIGINAL SYSTEM PROMPT —\n";
	}

	/**
	 * @param array<int, MemoryEntry> $beforeEntries
	 * @param array<int, array<string, mixed>> $recentSessions
	 */
	private function buildDreamUserPrompt(
		Agent $agent,
		array $beforeEntries,
		array $recentSessions,
		int $effectiveStoreLimit,
	): string {
		$lines = [];
		$lines[] = "AGENT: {$agent->name} (version {$agent->version})";
		$lines[] = "STORE LIMIT (max live entries): {$effectiveStoreLimit}";
		$lines[] = '';
		$lines[] = '== EXISTING MEMORY STORE ==';
		if ($beforeEntries === []) {
			$lines[] = '(empty)';
		} else {
			foreach ($beforeEntries as $i => $entry) {
				$lines[] = "[{$i}] title: {$entry->title}";
				$lines[] = "    updated_at: " . ($entry->updatedAt ?? '?');
				$preview = substr($entry->content, 0, 600);
				$lines[] = "    content (truncated to 600 chars):\n" . $preview;
			}
		}
		$lines[] = '';
		$lines[] = '== RECENT AGENT SESSIONS ==';
		if ($recentSessions === []) {
			$lines[] = '(no recent sessions)';
		} else {
			foreach ($recentSessions as $i => $row) {
				$uuid = (string) ($row['uuid'] ?? '');
				$status = (string) ($row['status'] ?? '');
				$stop = (string) ($row['stop_reason'] ?? '');
				$started = (string) ($row['started_at'] ?? '');
				$resultJson = (string) ($row['result_json'] ?? '');
				$preview = $resultJson !== '' ? substr($resultJson, 0, 400) : '';
				$lines[] = "[{$i}] session={$uuid} status={$status} stop={$stop} started={$started}";
				if ($preview !== '') {
					$lines[] = "    result_json (truncated): {$preview}";
				}
			}
		}
		$lines[] = '';
		$lines[] = 'Now produce the JSON document described in the system prompt.';
		return implode("\n", $lines);
	}

	/**
	 * Best-effort strict-JSON parser. The LLM is asked to return JSON only;
	 * if it wraps the JSON in ``` fences or prose, we strip them. On parse
	 * failure we return an empty decision list and log to stderr — failing
	 * soft is preferable to crashing the whole dream cycle on a malformed
	 * response.
	 *
	 * @return array<int, array<string, mixed>>
	 */
	private function parseDecisions(string $text): array
	{
		$text = trim($text);
		if (preg_match('/```(?:json)?\s*(.+?)```/s', $text, $m)) {
			$text = trim($m[1]);
		}
		$start = strpos($text, '{');
		$end = strrpos($text, '}');
		if ($start === false || $end === false || $end <= $start) {
			error_log('[dreamer] no JSON object found in response; treating as no-op');
			return [];
		}
		$json = substr($text, $start, $end - $start + 1);
		try {
			$decoded = json_decode($json, true, 32, JSON_THROW_ON_ERROR);
		} catch (\JsonException $exc) {
			error_log('[dreamer] JSON parse error: ' . $exc->getMessage());
			return [];
		}
		if (!is_array($decoded)) {
			return [];
		}
		$decisions = $decoded['decisions'] ?? [];
		if (!is_array($decisions)) {
			return [];
		}
		$out = [];
		foreach ($decisions as $d) {
			if (!is_array($d)) {
				continue;
			}
			$action = (string) ($d['action'] ?? '');
			if (!in_array($action, ['create', 'update', 'delete'], true)) {
				continue;
			}
			$title = (string) ($d['title'] ?? '');
			if ($title === '') {
				continue;
			}
			$entry = ['action' => $action, 'title' => $title];
			if (isset($d['content']) && is_string($d['content'])) {
				$entry['content'] = $d['content'];
			}
			$out[] = $entry;
		}
		return $out;
	}

	/**
	 * @param array<string, mixed> $decision
	 * @return array<string, mixed>
	 */
	private function applyDecision(
		string $agentName,
		array $decision,
		string $dreamSessionUuid,
		string $traceId,
	): array {
		$action = (string) $decision['action'];
		$title = (string) $decision['title'];
		switch ($action) {
			case 'create':
			case 'update':
				$content = (string) ($decision['content'] ?? '');
				if ($content === '') {
					return ['action' => $action, 'title' => $title, 'skipped' => 'empty content'];
				}
				$delta = $this->memory->commit(
					$agentName,
					$title,
					$content,
					$dreamSessionUuid,
					$traceId,
				);
				return $delta;
			case 'delete':
				$existing = $this->memory->recall($agentName, self::MAX_STORE_LIMIT);
				foreach ($existing as $entry) {
					if ($entry->title === $title) {
						$ok = $this->memory->forget($entry->uuid);
						return [
							'uuid' => $entry->uuid,
							'title' => $title,
							'action' => $ok ? 'deleted' : 'delete_failed',
						];
					}
				}
				return ['action' => 'delete', 'title' => $title, 'skipped' => 'no match'];
			default:
				return ['action' => $action, 'title' => $title, 'skipped' => 'unknown action'];
		}
	}

	private static function uuid(): string
	{
		$d = random_bytes(16);
		$d[6] = chr((ord($d[6]) & 0x0f) | 0x40);
		$d[8] = chr((ord($d[8]) & 0x3f) | 0x80);
		return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($d), 4));
	}

	private static function traceId(): string
	{
		return bin2hex(random_bytes(16)); // 32 hex chars, W3C trace_id shape
	}
}

/**
 * Result of one dream cycle. The CLI returns this as JSON to the operator
 * (or whatever invoked dream-agent.php).
 */
final class DreamResult
{
	/**
	 * @param array<int, array<string, mixed>> $deltas
	 */
	public function __construct(
		public readonly string $agent,
		public readonly string $sessionUuid,
		public readonly string $traceId,
		public readonly int $sessionsScanned,
		public readonly int $storeSizeBefore,
		public readonly int $storeSizeAfter,
		public readonly array $deltas,
		public readonly int $tokensInput,
		public readonly int $tokensOutput,
		public readonly bool $dryRun,
	) {
	}

	/**
	 * @return array<string, mixed>
	 */
	public function toArray(): array
	{
		return [
			'agent' => $this->agent,
			'session_uuid' => $this->sessionUuid,
			'trace_id' => $this->traceId,
			'sessions_scanned' => $this->sessionsScanned,
			'store_size_before' => $this->storeSizeBefore,
			'store_size_after' => $this->storeSizeAfter,
			'deltas' => $this->deltas,
			'tokens' => [
				'input' => $this->tokensInput,
				'output' => $this->tokensOutput,
			],
			'dry_run' => $this->dryRun,
		];
	}
}
