<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\SystemRepository;

/**
 * Hub — central dashboard showing all self-hosted systems.
 * Reads from SQLite `systems` table (populated by registry ingest +
 * manual/scan entries). Replaces the old "Components" tab — all data
 * is unified here.
 */
final class HubPresenter extends BasePresenter
{
	protected string $activeTab = 'hub';

	public function __construct(
		private SystemRepository $systems,
	) {
	}

	public function renderDefault(): void
	{
		$stats = $this->systems->stats();
		$tree = $this->systems->tree();
		$byStack = $this->systems->byStack();

		// Collect unique stacks and categories for filter buttons
		$stacks = [];
		$categories = [];
		foreach ($this->systems->list()['systems'] as $sys) {
			if ($sys['category'] !== 'stack') {
				$s = $sys['stack'] ?? 'other';
				$stacks[$s] = ($stacks[$s] ?? 0) + 1;
				$c = $sys['category'] ?? 'other';
				$categories[$c] = ($categories[$c] ?? 0) + 1;
			}
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
