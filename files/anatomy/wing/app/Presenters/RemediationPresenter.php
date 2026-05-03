<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\RemediationRepository;

final class RemediationPresenter extends BasePresenter
{
	protected string $activeTab = 'remediation';

	public function __construct(
		private RemediationRepository $repo,
	) {
	}

	public function renderDefault(): void
	{
		$this->template->items = $this->repo->list(['limit' => 200]);
	}
}
