<?php

declare(strict_types=1);

namespace App\AgentKit\Outcome;

/**
 * The three-stage output contract (Q9, 2026-08-29).
 *
 * An agent delivers through tools — db rows, structured files. Prose is a
 * report for a human, never the artifact a verdict reads. When a structured
 * output arrives malformed there are exactly three stages, in this order:
 *
 *   1. A HARDCODED deterministic parser repairs SHAPE ONLY: a fenced block, a
 *      prose preamble, a trailing comma, an unclosed bracket. NO MODEL RUNS IN
 *      THIS STEP — a model asked to fix its own output rewrites the content
 *      while it is in there, and the repair becomes an edit nobody authorised.
 *   2. Only if that fails: ONE bounded format-only re-ask, quoting the original
 *      content back. No new reasoning, no second chance, no third.
 *   3. If both fail the run records UNPARSEABLE. Never satisfied, never a
 *      quietly-dropped field.
 *
 * ANY repair — parser or re-ask — is reported, and the caller writes it to
 * agent_sessions.output_repaired. Silent repair is a success marker written by
 * the thing that failed.
 */
final class OutputRepair
{
	public const OK = 'ok';
	public const REPAIRED = 'repaired';
	public const UNPARSEABLE = 'unparseable';

	/**
	 * @param ?callable(string): string $reask ONE format-only re-ask. Null =
	 *        stage 2 is unavailable (no client), which is UNPARSEABLE, not ok.
	 * @return array{status: string, value: ?array<mixed>, stage: string, raw: string}
	 */
	public static function parse(string $raw, ?callable $reask = null): array
	{
		$decoded = self::decode($raw);
		if ($decoded !== null) {
			return ['status' => self::OK, 'value' => $decoded, 'stage' => 'clean', 'raw' => $raw];
		}

		$shaped = self::repairShape($raw);
		$decoded = $shaped === null ? null : self::decode($shaped);
		if ($decoded !== null) {
			return ['status' => self::REPAIRED, 'value' => $decoded, 'stage' => 'parser', 'raw' => $shaped];
		}

		if ($reask === null) {
			return ['status' => self::UNPARSEABLE, 'value' => null, 'stage' => 'no_reask', 'raw' => $raw];
		}
		$second = (string) $reask($raw);
		$decoded = self::decode($second);
		if ($decoded === null) {
			$shaped = self::repairShape($second);
			$decoded = $shaped === null ? null : self::decode($shaped);
			$second = $shaped ?? $second;
		}
		if ($decoded !== null) {
			// A re-ask that succeeded is still a repair: the first output was
			// not usable and something had to be done about it.
			return ['status' => self::REPAIRED, 'value' => $decoded, 'stage' => 'reask', 'raw' => $second];
		}
		return ['status' => self::UNPARSEABLE, 'value' => null, 'stage' => 'reask_failed', 'raw' => $second];
	}

	/** @return array<mixed>|null */
	private static function decode(string $text): ?array
	{
		$text = trim($text);
		if ($text === '') {
			return null;
		}
		$decoded = json_decode($text, true);
		return is_array($decoded) ? $decoded : null;
	}

	/**
	 * SHAPE ONLY. Every transformation here is mechanical and reversible in
	 * meaning: nothing is added to the content, nothing is renamed, no value is
	 * guessed. Returns null when there is no JSON-shaped span to work with.
	 */
	private static function repairShape(string $text): ?string
	{
		// A fenced block: take what is inside the first fence.
		if (preg_match('/```(?:json|JSON)?\s*(.+?)\s*```/s', $text, $m) === 1) {
			$text = $m[1];
		} else {
			$text = preg_replace('/^\s*```(?:json|JSON)?\s*/', '', $text) ?? $text;
		}
		// A prose preamble or postamble: the JSON span is first opener to last
		// closer. Anything outside it is commentary the consumer never wanted.
		$starts = array_filter([strpos($text, '{'), strpos($text, '[')], 'is_int');
		if ($starts === []) {
			return null;
		}
		$start = min($starts);
		$ends = array_filter([strrpos($text, '}'), strrpos($text, ']')], 'is_int');
		$end = $ends === [] ? strlen($text) - 1 : max($ends);
		$text = substr($text, $start, max(1, $end - $start + 1));
		// Trailing commas before a closer.
		$text = preg_replace('/,\s*([}\]])/', '$1', $text) ?? $text;
		return self::balance($text);
	}

	/**
	 * Close whatever the model left open, in the order it opened it. String
	 * state is tracked so a brace inside a value is not mistaken for structure
	 * — that mistake turns a truncated string into a different string.
	 */
	private static function balance(string $text): string
	{
		$stack = [];
		$inString = false;
		$escaped = false;
		$len = strlen($text);
		for ($i = 0; $i < $len; $i++) {
			$ch = $text[$i];
			if ($escaped) {
				$escaped = false;
				continue;
			}
			if ($ch === '\\') {
				$escaped = true;
				continue;
			}
			if ($ch === '"') {
				$inString = !$inString;
				continue;
			}
			if ($inString) {
				continue;
			}
			if ($ch === '{' || $ch === '[') {
				$stack[] = $ch === '{' ? '}' : ']';
			} elseif ($ch === '}' || $ch === ']') {
				array_pop($stack);
			}
		}
		if ($inString) {
			$text .= '"';
		}
		// Drop a dangling `"key":` or trailing comma left by the truncation,
		// then close the open containers innermost-first.
		$text = preg_replace('/,\s*$/', '', $text) ?? $text;
		$text = preg_replace('/,?\s*"[^"]*"\s*:\s*$/', '', $text) ?? $text;
		return $text . implode('', array_reverse($stack));
	}
}
