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
		// in BasePresenter::requireSuperAdmin() (called from each presenter's
		// startup()) — this flag is purely for UI visibility.
		$this->template->isSuperAdmin = $this->callerHasGroup('nos-providers');
	}

	// ── Authorization helpers (A13.7, 2026-05-07) ─────────────────────────
	//
	// All RBAC + state-mutation gates live here in the base class so every
	// privileged presenter inherits the same canonical implementation.
	// Background: A13.7 security review (security/2026-05-07-approvals-rbac.md)
	// found that ApprovalsPresenter shipped without a tier check — any
	// authenticated Authentik user including tier-4 nos-guests could
	// approve agent actions. Root cause was the gate logic living as a
	// PRIVATE method on AdminPresenter, so adding a new privileged
	// presenter required remembering to copy-paste it. Moving the gate
	// to BasePresenter as PROTECTED methods makes "I forgot to gate"
	// catastrophic-by-default rather than easy-to-miss.

	/**
	 * Returns true if the forward-auth groups header contains the named group.
	 * Authentik uses pipe / comma / whitespace as separators depending on the
	 * property mapping — tolerate all three.
	 */
	protected function callerHasGroup(string $group): bool
	{
		$raw = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Groups') ?? '');
		$tokens = preg_split('/[\\s,|]+/', $raw, -1, PREG_SPLIT_NO_EMPTY) ?: [];
		return in_array($group, $tokens, true);
	}

	/**
	 * Reject the request with 403 unless the forward-auth header includes the
	 * named group. Server-side gate — UI-level hiding of buttons is cosmetic
	 * only; this is the real authorization boundary.
	 */
	protected function requireGroup(string $group): void
	{
		if (!$this->callerHasGroup($group)) {
			$this->error(
				'Forbidden -- membership in `' . $group . '` group required.',
				403,
			);
		}
	}

	/**
	 * Tier-1 super-admin gate. Used by AdminPresenter (big-red-button halt /
	 * resume) and ApprovalsPresenter (rubber-stamp queue for agent actions).
	 *
	 * The constant ``nos-providers`` is duplicated here intentionally rather
	 * than imported from default.config.yml — it's a hard contract pinned by
	 * the anatomy gate ``test_security_admin_gate_unchanged`` so a config
	 * rename can't silently bypass the boundary.
	 */
	protected function requireSuperAdmin(): void
	{
		$this->requireGroup('nos-providers');
	}

	/**
	 * Reject the request with 405 unless the HTTP method is POST. Used by
	 * every state-changing action so a phishing GET (e.g. ``<img src>`` or
	 * a top-level navigation from a malicious page while the operator is
	 * logged in) cannot trigger the mutation. Templates must use
	 * ``<form method="post" action="...">`` to call these actions.
	 */
	protected function requirePostMethod(): void
	{
		$method = (string) $this->getHttpRequest()->getMethod();
		if (strtoupper($method) !== 'POST') {
			$this->error(
				'Method Not Allowed -- this action accepts POST only (state-changing).',
				405,
			);
		}
	}
}
