<?php

declare(strict_types=1);

namespace App\AgentKit;

use Symfony\Component\Yaml\Yaml;

/**
 * Token search over COMMITTED STATIC FILES. No service, no database, no HTTP.
 *
 * Measured 2026-08-30: qwen3:14b, asked how many security findings are open,
 * invented GET /api/v1/security/findings/open/count and 404'd. The answer —
 * GET /api/v1/remediation — was already described in wing.openapi.yml, which
 * nothing read. This is the index over what the agent was already handed.
 *
 * ONE CONSUMER TODAY: `ContractSearchTool`, over the two OpenAPI surfaces. The
 * design brief called this bucket 1 of an entity resolver as well, and this
 * docblock claimed the second consumer for a day before anyone checked — it
 * does not exist, and a class that says it is shared when it is not is how a
 * generalisation gets defended that nothing ever asked for. If a resolver
 * arrives it can pass its own entries to the constructor; until then this is a
 * search over two files.
 *
 * Anything it can return was already grep-able by the caller — so it answers
 * "how do I say the thing", never "what do you have", and it can never become
 * an existence oracle over private structure.
 *
 * ponytail: token overlap + a hand-written CZ→EN synonym table. Ceiling is a
 * query whose words share no lemma and no synonym entry with any indexed
 * text; upgrade to nomic-embed-text cosine ranking (Ollama is already up)
 * when the table starts fighting itself.
 */
final class StaticIndex
{
	/** Words that appear in nearly every summary and decide nothing. */
	private const STOPWORDS = [
		'a', 'an', 'the', 'of', 'for', 'to', 'by', 'in', 'on', 'api', 'v1',
		'je', 'jsou', 'mi', 'na', 'v', 've', 'co', 'jak', 'kolik', 'ukaz',
		'ukaž', 'me', 'my', 'and', 'or', 'id',
		'how', 'many', 'much', 'what', 'which', 'show', 'tell', 'is', 'are',
		'do', 'does', 'need', 'want', 'please',
	];

	/**
	 * CZ (and loose EN) prefixes → the words this estate's contracts use.
	 * Keys are matched as PREFIXES, which is the cheap stand-in for a Czech
	 * stemmer: `nález`, `nálezy`, `nálezů` all hit `nález`.
	 *
	 * @var array<string, array<int, string>>
	 */
	private const SYNONYMS = [
		'bezpečnost' => ['security', 'remediation', 'vulnerability'],
		'bezpecnost' => ['security', 'remediation', 'vulnerability'],
		'nález' => ['finding', 'remediation'],
		'nalez' => ['finding', 'remediation'],
		'otevřen' => ['open', 'pending'],
		'otevren' => ['open', 'pending'],
		'uzavřen' => ['closed', 'resolved'],
		'uzavren' => ['closed', 'resolved'],
		'zranitelnost' => ['vulnerability', 'advisory', 'cve'],
		'událost' => ['event'],
		'udalost' => ['event'],
		'úloh' => ['job', 'pulse'],
		'uloh' => ['job', 'pulse'],
		'záloh' => ['backup'],
		'zaloh' => ['backup'],
		'seznam' => ['list'],
		'služb' => ['service', 'system'],
		'sluzb' => ['service', 'system'],
		'stav' => ['status', 'health'],
		'zdraví' => ['health'],
		'zdravi' => ['health'],
		'migrac' => ['migration'],
		'povýšen' => ['upgrade'],
		'nasazen' => ['deploy'],
		'uživatel' => ['user'],
		'uzivatel' => ['user'],
		'heslo' => ['secret', 'credential'],
		'tajemství' => ['secret'],
		'souhlas' => ['consent'],
		'chyb' => ['error', 'failure'],
		// EN entries earn their place too: this estate calls a security
		// finding a `remediation` item, so the plain-English question misses
		// by vocabulary exactly the way the Czech one does.
		'security' => ['remediation', 'advisory', 'gitleaks'],
		'finding' => ['remediation', 'gitleaks'],
		'vulnerab' => ['remediation', 'advisory', 'cve'],
		'open' => ['pending'],
		'closed' => ['resolved'],
	];

	/** At most this many answers from one route family — five verbs of one
	 *  route is a dump, not a decision. */
	private const MAX_PER_FAMILY = 2;

	/** @var array<string, int>|null document frequency, built once per index */
	private ?array $df = null;

	/** @param array<int, array{source: string, label: string, tokens: array<int, string>}> $entries */
	public function __construct(private readonly array $entries)
	{
	}

	/**
	 * Every operation in an OpenAPI document, as one entry per method+path.
	 *
	 * @return array<int, array{source: string, label: string, tokens: array<int, string>}>
	 */
	public static function openApi(string $file, string $source): array
	{
		$doc = Yaml::parseFile($file);
		$out = [];
		foreach ((array) ($doc['paths'] ?? []) as $path => $ops) {
			foreach ((array) $ops as $method => $op) {
				if (!is_array($op) || !in_array(strtolower((string) $method), ['get', 'post', 'put', 'patch', 'delete'], true)) {
					continue;
				}
				$summary = (string) ($op['summary'] ?? '');
				$label = sprintf('%-6s %-40s %s', strtoupper((string) $method), $path, $summary);
				$out[] = [
					'source' => $source,
					'label' => rtrim($label),
					// Collection + its sub-paths are one family, so a single
					// route's five verbs cannot eat all five answer slots.
					'family' => implode('/', array_slice(explode('/', trim((string) $path, '/')), 0, 3)),
					'tokens' => self::tokens($path . ' ' . $summary . ' ' . implode(' ', (array) ($op['tags'] ?? []))),
				];
			}
		}
		return $out;
	}

	/**
	 * Lowercase word tokens, stopwords dropped, CZ prefixes expanded to the
	 * EN words the contracts actually use. A token keeps itself as well as
	 * its expansions, so an EN query is unaffected by the table.
	 *
	 * @return array<int, string>
	 */
	public static function tokens(string $text): array
	{
		$words = preg_split('/[^\p{L}\p{N}]+/u', mb_strtolower($text, 'UTF-8'), -1, PREG_SPLIT_NO_EMPTY) ?: [];
		$out = [];
		foreach ($words as $word) {
			if (mb_strlen($word) < 2 || in_array($word, self::STOPWORDS, true)) {
				continue;
			}
			$out[] = $word;
			// One-rule stemmer, both sides: `events` must meet `event`.
			if (mb_strlen($word) > 3 && str_ends_with($word, 's')) {
				$out[] = mb_substr($word, 0, -1);
			}
			foreach (self::SYNONYMS as $prefix => $expansions) {
				if (str_starts_with($word, $prefix)) {
					$out = array_merge($out, $expansions);
				}
			}
		}
		return array_values(array_unique($out));
	}

	/**
	 * Rank entries by the fraction of the query's own tokens that the entry
	 * matches. Returns at most $limit rows scoring at or above $floor.
	 *
	 * @return array<int, array{source: string, label: string, score: float}>
	 */
	public function search(string $query, int $limit = 5, float $floor = 0.34): array
	{
		// Group per QUERY WORD, not per expansion: 'bezpečnostní' contributing
		// three synonyms must still count once, or a word with a fat synonym
		// row outvotes the rest of the sentence.
		$groups = [];
		foreach (preg_split('/[^\p{L}\p{N}]+/u', mb_strtolower($query, 'UTF-8'), -1, PREG_SPLIT_NO_EMPTY) ?: [] as $word) {
			$expanded = self::tokens($word);
			if ($expanded !== []) {
				$groups[] = $expanded;
			}
		}
		if ($groups === []) {
			return [];
		}

		// Weight each query word by how rare it is in the corpus: without this,
		// `seznam událostí` scored every "list …" route as high as the events
		// route, because `list` matched and `event` was one vote of two.
		$weights = array_map(fn(array $g): float => $this->idf($g), $groups);
		$total = array_sum($weights) ?: 1.0;

		$hits = [];
		foreach ($this->entries as $entry) {
			$have = array_flip($entry['tokens']);
			$matched = 0.0;
			foreach ($groups as $i => $group) {
				foreach ($group as $token) {
					if (isset($have[$token])) {
						$matched += $weights[$i];
						break;
					}
				}
			}
			$score = $matched / $total;
			if ($score >= $floor) {
				// Shorter labels win ties: the generic collection route is a
				// better first answer than one of its sub-paths, and a read
				// beats a write when the score cannot tell them apart.
				$score += str_starts_with($entry['label'], 'GET') ? 1e-4 : 0.0;
				$hits[] = [
					'source' => $entry['source'],
					'label' => $entry['label'],
					'family' => $entry['family'] ?? $entry['label'],
					// Penalty on the PATH, not the label: a long, informative
					// summary must not lose to a terse sub-route.
					'score' => round($score - mb_strlen($entry['family'] ?? '') / 1e5, 5),
				];
			}
		}
		usort($hits, static fn(array $a, array $b): int => $b['score'] <=> $a['score']);

		$out = [];
		$perFamily = [];
		foreach ($hits as $hit) {
			$family = $hit['family'];
			if (($perFamily[$family] ?? 0) >= self::MAX_PER_FAMILY) {
				continue;
			}
			$perFamily[$family] = ($perFamily[$family] ?? 0) + 1;
			unset($hit['family']);
			$out[] = $hit;
			if (count($out) >= $limit) {
				break;
			}
		}
		return $out;
	}

	/** Inverse document frequency of the rarest member of a synonym group. */
	private function idf(array $group): float
	{
		if ($this->df === null) {
			$this->df = [];
			foreach ($this->entries as $entry) {
				foreach (array_unique($entry['tokens']) as $token) {
					$this->df[$token] = ($this->df[$token] ?? 0) + 1;
				}
			}
		}
		$df = $this->df;
		$n = max(count($this->entries), 1);
		$best = 0.0;
		foreach ($group as $token) {
			$best = max($best, log($n / max($df[$token] ?? 0, 1) + 1));
		}
		return max($best, 0.05);
	}
}
