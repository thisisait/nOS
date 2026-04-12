<?php

declare(strict_types=1);

namespace App\Presenters;

use Nette\Application\UI\Presenter;

abstract class BasePresenter extends Presenter
{
	protected string $activeTab = 'overview';

	public function beforeRender(): void
	{
		$this->template->activeTab = $this->activeTab;

		// Authentik proxy auth headers (populated by nginx forward auth)
		$request = $this->getHttpRequest();
		$this->template->authUser = $request->getHeader('X-Authentik-Username');
		$this->template->authEmail = $request->getHeader('X-Authentik-Email');
		$this->template->authName = $request->getHeader('X-Authentik-Name');
		$this->template->authGroups = $request->getHeader('X-Authentik-Groups');
		$this->template->isAuthenticated = (bool) $this->template->authUser;
	}
}
