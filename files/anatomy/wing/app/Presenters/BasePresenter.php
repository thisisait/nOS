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

		// Authentik proxy auth headers (populated by Traefik forward-auth /
		// the legacy nginx setup). Authentik joins groups with whitespace /
		// pipe / comma depending on the property mapping; tolerate all so
		// a config drift doesn't silently degrade RBAC.
		$request = $this->getHttpRequest();
		$this->template->authUser = $request->getHeader('X-Authentik-Username');
		$this->template->authEmail = $request->getHeader('X-Authentik-Email');
		$this->template->authName = $request->getHeader('X-Authentik-Name');
		$this->template->authGroups = $request->getHeader('X-Authentik-Groups');
		$this->template->isAuthenticated = (bool) $this->template->authUser;

		// A12 (2026-05-07): expose Tier-1 super-admin flag to the layout
		// so the header can show the Admin tab + the big-red-button only
		// to operators in the nos-providers group. Server-side guards live
		// in AdminPresenter::requireSuperAdmin (and any future Tier-1-only
		// presenters) — this flag is purely for UI visibility.
		$tokens = preg_split(
			'/[\\s,|]+/',
			(string) $this->template->authGroups,
			-1,
			PREG_SPLIT_NO_EMPTY,
		) ?: [];
		$this->template->isSuperAdmin = in_array('nos-providers', $tokens, true);
	}
}
