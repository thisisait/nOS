<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Reads the plugin-harvested hub cards (data/hub-cards.json, written by the
 * wing-base aggregator at post_compose — P1a). The HubPresenter overlays the
 * card metadata (icon, tier) onto the systems it renders, so the /hub shows
 * the per-plugin icons + can RBAC-filter by tier without touching the systems
 * table. Render-time overlay → no DB/ingest change, no drift.
 */
final class HubCardRepository
{
	private string $path;

	public function __construct()
	{
		$dir = getenv('WING_DATA_DIR') ?: dirname(__DIR__, 2) . '/data';
		$this->path = rtrim($dir, '/') . '/hub-cards.json';
	}

	/**
	 * @return array<string, array<string, mixed>> normalised-slug => card
	 */
	public function bySlug(): array
	{
		if (!is_file($this->path)) {
			return [];
		}
		$doc = json_decode((string) @file_get_contents($this->path), true);
		if (!is_array($doc)) {
			return [];
		}
		$out = [];
		foreach (($doc['cards'] ?? []) as $card) {
			if (!empty($card['slug'])) {
				$out[$this->norm((string) $card['slug'])] = $card;
			}
		}
		return $out;
	}

	/** Slugs are hyphenated (open-webui); systems ids are underscored (open_webui). */
	private function norm(string $s): string
	{
		return strtolower(str_replace('_', '-', $s));
	}
}
