<?php

declare(strict_types=1);

namespace App\Security;

use Nette\Http\IRequest;
use Nette\Security\IIdentity;
use Nette\Security\SimpleIdentity;
use Nette\Security\UserStorage;

/**
 * Stateless UserStorage that derives the Nette identity from Authentik
 * forward-auth headers on EVERY request.
 *
 * Why a custom storage instead of `User::login()`:
 *   - Wing's auth is header-authoritative. Authentik's proxy outpost (Traefik
 *     forward-auth) injects X-Authentik-Username / -Groups / -Email / -Name on
 *     every request, and BasePresenter::enforceEdgeTrust() proves the request
 *     actually passed through the edge (X-Wing-Edge-Token) — so the headers are
 *     trustworthy and re-evaluated each request (a group change in Authentik
 *     takes effect immediately).
 *   - Calling `User::login()` per request would regenerate Nette's session id
 *     (fixation defense), which would churn — and silently invalidate — the
 *     CSRF token BasePresenter stores in that same session. So we keep the
 *     session out of the auth path entirely: save/clear/setExpiration are
 *     no-ops, and getState() reads the request.
 *
 * The identity's roles ARE the caller's Authentik groups, so the standard
 * Nette authorization API works directly:
 *     $user->isInRole('nos-admins')      // true if X-Authentik-Groups has it
 *     $user->getRoles()                  // ['nos-providers', ...]
 *
 * Replaces the framework default `security.userStorage` (session-backed) via
 * an explicit override in config/common.neon.
 */
final class ForwardAuthUserStorage implements UserStorage
{
	public function __construct(
		private IRequest $request,
	) {
	}

	public function getState(): array
	{
		$username = trim((string) ($this->request->getHeader('X-Authentik-Username') ?? ''));
		if ($username === '') {
			// No forward-auth identity on this request → not logged in. A
			// presenter that requires a tier will 403; public reads still pass.
			return [false, null, null];
		}

		// Authentik joins groups with whitespace / pipe / comma depending on the
		// property mapping — tolerate all three (mirrors BasePresenter parsing).
		$rawGroups = (string) ($this->request->getHeader('X-Authentik-Groups') ?? '');
		$roles = preg_split('/[\s,|]+/', $rawGroups, -1, PREG_SPLIT_NO_EMPTY) ?: [];

		$identity = new SimpleIdentity($username, $roles, [
			'email' => (string) ($this->request->getHeader('X-Authentik-Email') ?? ''),
			'name'  => (string) ($this->request->getHeader('X-Authentik-Name') ?? ''),
		]);

		return [true, $identity, null];
	}

	// Header-authoritative + stateless: nothing is persisted. The identity is
	// rebuilt from the request on every getState() call.
	public function saveAuthentication(IIdentity $identity): void
	{
	}

	public function clearAuthentication(bool $clearIdentity): void
	{
	}

	public function setExpiration(?string $expire, bool $clearIdentity): void
	{
	}
}
