<?php

declare(strict_types=1);

namespace App\AgentKit;

use App\AgentKit\LLMClient\LLMClientInterface;
use App\AgentKit\LLMClient\Message;

/**
 * one_shot mode — bind, ONE call, validate the emitted chain, record.
 *
 * The ops plane (nos-ops) runs small local models over a labelled task
 * family. A tool-use loop measures the harness as much as the model, so this
 * mode has no loop at all: no tools are offered, no retry wraps the call, no
 * outcome iteration follows it. Exactly one send() per run, always.
 *
 * The verdict is written by THIS reader, never by the model — 'valid' means
 * the emitted text parsed as JSON and satisfied the agent's declared schema,
 * and the word `satisfied` deliberately does not appear: that one belongs to
 * a gate run (see test_satisfaction_is_written_by_a_gate_run.py).
 */
final class OneShot
{
	/**
	 * @return array{verdict: string, chain: ?array<mixed>, error: ?string, raw: string, stop_reason: string, tokens_input: int, tokens_output: int}
	 */
	public static function run(LLMClientInterface $llm, Agent $agent, string $prompt): array
	{
		// Tools are withheld on purpose: an offered tool schema is an
		// invitation to a second round trip, and there is no second round.
		$resp = $llm->send(
			$agent->systemPrompt ?? '',
			[Message::userText($prompt)],
			[],
			$agent->maxOutputTokens,
		);
		$raw = $resp->textOutput();
		$chain = null;
		$error = self::check($raw, $agent->oneShotSchema, $chain);

		return [
			'verdict' => $error === null ? 'valid' : 'failed',
			'chain' => $chain,
			'error' => $error,
			'raw' => $raw,
			'stop_reason' => $resp->stopReason,
			'tokens_input' => $resp->tokensInput,
			'tokens_output' => $resp->tokensOutput,
		];
	}

	/**
	 * @param array<mixed> $schema
	 * @param-out ?array<mixed> $chain
	 * @return ?string null = the chain is valid; else why it is not
	 */
	private static function check(string $raw, array $schema, ?array &$chain): ?string
	{
		$chain = null;
		$text = trim($raw);
		// A 1B model fences its JSON. Measuring fence discipline is not the
		// point of the harness, so strip it before judging the chain.
		if (preg_match('/```(?:json)?\s*(.+?)```/s', $text, $m) === 1) {
			$text = trim($m[1]);
		}
		$decoded = json_decode($text, true);
		if (!is_array($decoded)) {
			return 'emitted chain is not JSON: ' . substr($text, 0, 120);
		}
		$error = self::against($decoded, $schema, '$');
		if ($error !== null) {
			return $error;
		}
		$chain = $decoded;

		return null;
	}

	/**
	 * JSON Schema subset — type / required / properties / items / enum.
	 * Enough for an extraction chain; a real validator drops in behind the
	 * same call if a schema ever needs more.
	 *
	 * @param array<mixed> $schema
	 */
	private static function against(mixed $value, array $schema, string $at): ?string
	{
		$type = $schema['type'] ?? null;
		if (is_string($type) && !self::isType($value, $type)) {
			return "{$at}: expected {$type}, got " . get_debug_type($value);
		}
		if (isset($schema['enum']) && is_array($schema['enum'])
			&& !in_array($value, $schema['enum'], true)) {
			return "{$at}: " . var_export($value, true) . ' is not in the declared enum';
		}
		if (is_array($value)) {
			foreach ((array) ($schema['required'] ?? []) as $key) {
				if (!array_key_exists($key, $value)) {
					return "{$at}." . (string) $key . ': required key missing';
				}
			}
			foreach ((array) ($schema['properties'] ?? []) as $key => $sub) {
				if (is_array($sub) && array_key_exists($key, $value)) {
					$error = self::against($value[$key], $sub, "{$at}." . (string) $key);
					if ($error !== null) {
						return $error;
					}
				}
			}
			if (is_array($schema['items'] ?? null)) {
				foreach ($value as $i => $item) {
					$error = self::against($item, $schema['items'], "{$at}[{$i}]");
					if ($error !== null) {
						return $error;
					}
				}
			}
		}

		return null;
	}

	private static function isType(mixed $value, string $type): bool
	{
		return match ($type) {
			// An empty PHP array is both; the schema's own word decides.
			'object' => is_array($value) && ($value === [] || !array_is_list($value)),
			'array' => is_array($value) && ($value === [] || array_is_list($value)),
			'string' => is_string($value),
			'number' => is_int($value) || is_float($value),
			'integer' => is_int($value),
			'boolean' => is_bool($value),
			'null' => $value === null,
			// A misspelt type word must fail loudly, not wave the chain through.
			default => false,
		};
	}
}
