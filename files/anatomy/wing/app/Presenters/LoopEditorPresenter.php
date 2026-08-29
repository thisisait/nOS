<?php

declare(strict_types=1);

namespace App\Presenters;

use Symfony\Component\Yaml\Yaml;

/**
 * Wing /loop-editor — every agent's HARNESS, read-only.
 *
 * THE REASON THIS EXISTS BEFORE THE THING IT GUARDS. Q6 (operator, 2026-08-28)
 * made harness enhancement an operator toggle rather than a count of successful
 * sessions, and put the surface FIRST: you cannot consent to what you cannot
 * see. The harness — agent.yml, the system prompt, the tool roster, the write
 * grants, the gate set — IS the set of gates on an agent, and until now it was
 * only readable by opening seven directories in a checkout.
 *
 * READ-ONLY, and there is no edit path to add later without re-deciding: an
 * editor that writes the harness is the `harness` proposal kind wearing a
 * browser, which is exactly what DISABLED_INTENTS refuses. No action* method
 * lives here (the presenter gate contract asserts that, not just this comment).
 *
 * WHY IT READS FILES AND NOT wing.db. The harness is git-owned. wing.db holds
 * what an agent DID; this page holds what it is ALLOWED to do, and those must
 * not share a writer — the same split as roadmap `status` vs `verified`.
 *
 * ABSENCE IS ABSENCE. NOS_REPO_ROOT unset, ledger.py unparseable, grants file
 * missing — each renders as a stated UNKNOWN. An empty tool roster must never
 * be indistinguishable from an agent with no tools.
 */
final class LoopEditorPresenter extends BasePresenter
{
	protected string $activeTab = 'loop-editor';

	/** Names every capability and write grant in the estate. Tier-1. */
	protected ?int $minAccessTier = 1;

	/** The committed toggle. Repo IS the value — see the fixture's header. */
	private const TOGGLE_FIXTURE = 'state/fixtures/loop-config.seed.yml';
	private const TOGGLE_TABLE = 'loop-config';
	private const TOGGLE_ROW = 'harness_proposals_enabled';
	private const LEDGER = 'files/anatomy/bone/ledger.py';
	private const GRANTS = 'docs/plans/rsi-research/artifacts/wing-write-grants.json';

	public function renderDefault(): void
	{
		$root = trim((string) getenv('NOS_REPO_ROOT'));
		$this->template->repoRoot = $root;
		$this->template->harnesses = $root === '' ? [] : $this->harnesses($root);
		$this->template->intents = $this->intents($root);
		$this->template->toggle = $this->toggle($root);
		$this->template->toggleAddress = self::TOGGLE_TABLE . ' / ' . self::TOGGLE_ROW;
	}

	/** @return array<int, array<string, mixed>> one entry per agent on disk */
	private function harnesses(string $root): array
	{
		$dir = $root . '/files/anatomy/agents';
		$grants = $this->grants($root);
		$out = [];
		foreach (glob($dir . '/*/agent.yml') ?: [] as $path) {
			$name = basename(dirname($path));
			$raw = (string) file_get_contents($path);
			try {
				$def = (array) Yaml::parse($raw);
			} catch (\Throwable $exc) {
				$def = [];
			}
			$systemPath = dirname($path) . '/' . (string) ($def['system_prompt_path'] ?? 'system.md');
			$out[] = [
				'name' => $name,
				'agentYml' => $raw,
				'agentYmlParsed' => $def !== [],
				'systemPrompt' => is_file($systemPath) ? (string) file_get_contents($systemPath) : null,
				'systemPromptPath' => 'files/anatomy/agents/' . $name . '/' . basename($systemPath),
				'tools' => array_map(
					static fn($t): string => is_array($t) ? (string) ($t['id'] ?? '?') : (string) $t,
					(array) ($def['tools'] ?? []),
				),
				'gateset' => ($def['outcomes'] ?? [])['gateset'] ?? null,
				'capabilities' => array_map('strval', (array) ($def['capabilities'] ?? [])),
				'runnerStatus' => ($def['metadata'] ?? [])['runner_status'] ?? null,
				'grants' => $grants === null ? null : ($grants[$name] ?? []),
			];
		}
		return $out;
	}

	/**
	 * Measured write grants, keyed by agent. NULL = the artifact is unreadable,
	 * which is not the same fact as "this agent was granted nothing".
	 *
	 * @return array<string, array<int, string>>|null
	 */
	private function grants(string $root): ?array
	{
		$path = $root . '/' . self::GRANTS;
		if (!is_file($path)) {
			return null;
		}
		$doc = json_decode((string) file_get_contents($path), true);
		if (!is_array($doc) || !isset($doc['grants'])) {
			return null;
		}
		$out = [];
		foreach ((array) $doc['grants'] as $g) {
			$routes = [];
			foreach ((array) ($g['routes'] ?? []) as $r) {
				$routes[] = trim(((string) ($r['method'] ?? '')) . ' ' . ((string) ($r['path'] ?? '')));
			}
			$out[(string) ($g['agent'] ?? '?')] = $routes;
		}
		return $out;
	}

	/**
	 * Q6 seam (3): the proposal intent classes, disabled ones marked.
	 *
	 * Parsed out of ledger.py rather than restated here. A second copy of a
	 * closed enum is a copy that drifts, and the one that drifts is always the
	 * one the operator is reading.
	 *
	 * @return array{classes: array<int, array{name: string, disabled: bool}>, toggleNote: ?string, source: string}
	 */
	private function intents(string $root): array
	{
		$src = $root === '' ? '' : (string) @file_get_contents($root . '/' . self::LEDGER);
		$all = $this->frozenset($src, 'INTENT_CLASSES');
		$off = $this->frozenset($src, 'DISABLED_INTENTS');
		$note = null;
		if (preg_match('/^DISABLED_INTENT_TOGGLE = "(.*)"$/m', $src, $m)) {
			$note = $m[1];
		}
		$classes = [];
		foreach ($all as $name) {
			$classes[] = ['name' => $name, 'disabled' => in_array($name, $off, true)];
		}
		return ['classes' => $classes, 'toggleNote' => $note, 'source' => self::LEDGER];
	}

	/**
	 * ponytail: regex over one committed literal, not a Python parse. The gate
	 * (test_the_harness_toggle_defaults_off.py) imports the real module, so a
	 * spelling change there goes red before this page can quietly show nothing.
	 *
	 * @return array<int, string>
	 */
	private function frozenset(string $src, string $name): array
	{
		if (!preg_match('/^' . preg_quote($name, '/') . ' = frozenset\(\{(.*?)\}\)/ms', $src, $m)) {
			return [];
		}
		preg_match_all('/"([a-z][a-z0-9-]*)"/', $m[1], $hits);
		return $hits[1];
	}

	/**
	 * The committed toggle row. `enabled` is deliberately NOT coerced to bool
	 * on a missing row: null means "no such row", which is a different thing to
	 * report than "off".
	 *
	 * @return array{found: bool, enabled: ?bool, row: array<string, mixed>, path: string}
	 */
	private function toggle(string $root): array
	{
		$path = self::TOGGLE_FIXTURE;
		$row = [];
		if ($root !== '' && is_file($root . '/' . $path)) {
			try {
				$doc = (array) Yaml::parseFile($root . '/' . $path);
			} catch (\Throwable $exc) {
				$doc = [];
			}
			foreach ((array) ($doc[self::TOGGLE_TABLE] ?? []) as $candidate) {
				if (is_array($candidate) && ($candidate['slug'] ?? null) === self::TOGGLE_ROW) {
					$row = $candidate;
					break;
				}
			}
		}
		return [
			'found' => $row !== [],
			'enabled' => $row === [] ? null : (bool) ($row['enabled'] ?? false),
			'row' => $row,
			'path' => $path,
		];
	}
}
