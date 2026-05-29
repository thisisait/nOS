<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\HubCardRepository;
use App\Model\SystemRepository;

/**
 * Hub — central dashboard showing all self-hosted systems.
 * Reads from SQLite `systems` table (populated by registry ingest +
 * manual/scan entries). Replaces the old "Components" tab — all data
 * is unified here. P1a overlays the plugin-harvested hub_card icon (+ tier)
 * so the per-plugin icons render and the viewer's tier is available for
 * RBAC-aware presentation.
 */
final class HubPresenter extends BasePresenter
{
	protected string $activeTab = 'hub';

	public function __construct(
		private SystemRepository $systems,
		private HubCardRepository $cards,
	) {
	}

	/**
	 * Backend services with no clickable browser UI; surface in /docker ps/
	 * Grafana Explore, not in /hub. (2026-05-29: caught by the URL audit gate
	 * as hard 404s on the public host — they have domain routes but no root.)
	 * TODO: promote to a `kind: backend` flag on the plugin manifest so the
	 * harvest can author this; today it's a small allow-list.
	 */
	private const BACKEND_ONLY_SLUGS = [
		'bluesky_pds', 'loki', 'tempo', 'prometheus', 'alloy', 'nginx',
	];

	public function renderDefault(): void
	{
		$stats = $this->systems->stats();
		$tree = $this->systems->tree();
		$byStack = $this->systems->byStack();

		// P1a — overlay the plugin hub_card icon (+ tier) onto each system by
		// normalised slug AND filter out non-clickable rows: TCP-only daemons
		// (postgresql/redis/mariadb/dnsmasq — no domain_url, only ip_url) and
		// backend services without a root UI. Render-time only; no DB write.
		$cardsBySlug = $this->cards->bySlug();
		$isClickable = static function (array $sys): bool {
			if (empty($sys['domain_url'])) {
				return false;   // TCP-only / no public host
			}
			if (in_array($sys['id'] ?? '', self::BACKEND_ONLY_SLUGS, true)) {
				return false;   // backend; surfaces via Grafana / clients
			}
			return true;
		};

		foreach ($byStack as $stack => $systems) {
			$kept = [];
			foreach ($systems as $sys) {
				if (!$isClickable($sys)) {
					continue;
				}
				$slug = strtolower(str_replace('_', '-', (string) ($sys['id'] ?? '')));
				if (isset($cardsBySlug[$slug])) {
					$sys['icon'] = $cardsBySlug[$slug]['icon'] ?? null;
					$sys['card_tier'] = $cardsBySlug[$slug]['tier'] ?? null;
				}
				$kept[] = $sys;
			}
			$byStack[$stack] = $kept;
		}
		// Drop now-empty stacks so the template doesn't show empty sections.
		$byStack = array_filter($byStack, static fn(array $s): bool => count($s) > 0);

		// Viewer's RBAC tier (1 = most privileged). Defaults to 1 (show all) when
		// no nos-group header is present, so /hub never blanks out for an
		// edge-token caller; the template can dim/badge by card_tier vs this.
		$this->template->viewerTier = $this->callerHasGroup('nos-providers') || $this->callerHasGroup('nos-admins') ? 1
			: ($this->callerHasGroup('nos-managers') ? 2
			: ($this->callerHasGroup('nos-users') ? 3
			: ($this->callerHasGroup('nos-guests') ? 4 : 1)));

		// Collect unique stacks and categories for filter buttons. Apply the
		// same clickable filter so the buttons' counts match the rendered grid
		// (no "infra (10)" when only 6 are shown).
		$stacks = [];
		$categories = [];
		foreach ($this->systems->list()['systems'] as $sys) {
			if ($sys['category'] === 'stack' || !$isClickable($sys)) {
				continue;
			}
			$s = $sys['stack'] ?? 'other';
			$stacks[$s] = ($stacks[$s] ?? 0) + 1;
			$c = $sys['category'] ?? 'other';
			$categories[$c] = ($categories[$c] ?? 0) + 1;
		}
		ksort($stacks);
		ksort($categories);

		$this->template->stats = $stats;
		$this->template->tree = $tree;
		$this->template->byStack = $byStack;
		$this->template->stacks = $stacks;
		$this->template->categories = $categories;
	}
}
