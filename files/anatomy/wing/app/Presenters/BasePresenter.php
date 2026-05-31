<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\AuditChainRepository;
use App\Model\EventRepository;
use App\Model\NotificationRepository;
use Nette\Application\UI\Presenter;

abstract class BasePresenter extends Presenter
{
	protected string $activeTab = 'overview';

	// W4 (2026-05-17): @inject populates every BasePresenter subclass without
	// touching constructors. Used by beforeRender() to populate the top-nav
	// unread/pending badges. Public-with-@inject is the Nette idiom for
	// "cross-cutting concerns BasePresenter wants to add."
	/** @inject */
	public NotificationRepository $notificationsForBadge;

	/** @inject */
	public EventRepository $eventsForBadge;

	/** @inject */
	public AuditChainRepository $auditChainForBadge;

	/**
	 * RBAC tier → Authentik group(s). Tier 1 is the most privileged; access is
	 * cumulative (a tier-1 admin satisfies any higher-numbered tier gate). The
	 * group names are the canonical nOS RBAC groups (CLAUDE.md "RBAC" +
	 * authentik_rbac_tiers defaults) and are pinned here as a hard security
	 * contract — a rename in default.config.yml must be matched in code.
	 */
	private const TIER_GROUPS = [
		1 => ['nos-providers', 'nos-admins'],
		2 => ['nos-managers'],
		3 => ['nos-users'],
		4 => ['nos-guests'],
	];

	/**
	 * Minimum RBAC tier required to reach ANY action of this presenter.
	 * null = no tier gate (public / any forward-authed identity). A subclass
	 * sets e.g. `protected ?int $minAccessTier = 1;` to require Tier-1, and
	 * BasePresenter::startup() enforces it BY DEFAULT — so a new privileged
	 * presenter is gated by a single declarative property instead of an
	 * easy-to-forget startup() override (the A13.7 regression class).
	 */
	protected ?int $minAccessTier = null;

	/**
	 * SEC-6 (2026-05-23): edge-trust validation runs BEFORE any action
	 * method or beforeRender. If WING_EDGE_TOKEN env is set, every
	 * request MUST carry a matching X-Wing-Edge-Token header (injected
	 * by Traefik's wing-edge@file middleware). Direct-loopback requests
	 * that bypass Traefik (curl from another process on the host)
	 * arrive without the header and are refused — even if they spoof
	 * X-Authentik-Username.
	 *
	 * Graceful degradation when WING_EDGE_TOKEN env is empty (fresh
	 * install pre-regen, or operator explicitly disabled): skip the
	 * check. The 127.0.0.1 bind (Wing Caddyfile, SEC-6) is still the
	 * first defense; this header is the second.
	 */
	public function startup(): void
	{
		parent::startup();
		$this->enforceEdgeTrust();
		// Standard RBAC gate — enforced for EVERY presenter that declares a
		// minimum tier. Privileged subclasses opt in with one property
		// ($minAccessTier) instead of an easy-to-forget startup() override.
		if ($this->minAccessTier !== null) {
			$this->requireTier($this->minAccessTier);
		}
	}

	private function enforceEdgeTrust(): void
	{
		$expected = (string) (getenv('WING_EDGE_TOKEN') ?: '');
		if ($expected === '') {
			// Edge-trust not yet configured — skip (fresh install path).
			// SEC-3 lazy-regen populates this on first main.yml run; the
			// next plist render + Restart wing handler will activate it.
			return;
		}
		$got = (string) ($this->getHttpRequest()->getHeader('X-Wing-Edge-Token') ?? '');
		// Timing-safe compare so a brute-force attempt can't oracle the
		// match position from response latency.
		if (!hash_equals($expected, $got)) {
			$this->error(
				'Forbidden -- request did not pass through the Traefik edge. '
				. 'Browser access must come via https://wing.<tld>/, not '
				. 'direct localhost:9000.',
				403,
			);
		}
	}

	public function beforeRender(): void
	{
		$this->template->activeTab = $this->activeTab;

		// Asset cache-buster (W5 fix): style.css was linked with no version,
		// so CSS edits stayed invisible behind the browser cache (the burger
		// overlay shipped unstyled). Key the stylesheet URLs on the on-disk
		// mtime so every deploy busts the cache automatically.
		$cssPath = dirname(__DIR__, 2) . '/www/assets/style.css';
		$this->template->assetVer = @filemtime($cssPath) ?: 1;

		// SEC-14 (2026-05-23): expose CSRF token so every Latte form
		// can emit `<input type="hidden" name="_csrf" value="{$csrfToken}">`.
		// requirePostMethod() validates the field on every state-changing
		// action.
		$this->template->csrfToken = $this->getCsrfToken();

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

		// A12 (2026-05-07, updated 2026-05-17): expose Tier-1 super-admin
		// flag to the layout so the header can show the Admin tab + the
		// big-red-button only to operators in nos-providers OR nos-admins
		// (per CLAUDE.md RBAC table — both are Tier-1). Server-side guards
		// live in BasePresenter::requireSuperAdmin() (called from each
		// privileged presenter's startup()) — this flag is purely for UI
		// visibility.
		$this->template->isSuperAdmin = $this->callerHasGroup('nos-providers')
			|| $this->callerHasGroup('nos-admins');

		// W3 (2026-05-17): authentik_domain for the layout's logout link.
		// Was hardcoded to `auth.dev.local`, which broke on every public-TLD
		// install (pazny.eu, etc.). Read AUTHENTIK_DOMAIN env (set by the
		// wing launchd plist + propagated through pazny.wing's .env render);
		// fall back to a sensible dev default rather than dying when the env
		// is empty on a fresh-bootstrap dev box.
		$this->template->authentikDomain = getenv('AUTHENTIK_DOMAIN') ?: 'auth.dev.local';

		// W4 (2026-05-17): live unread/pending counts for the Inbox +
		// Approvals tab badges. Both repos are cheap to query (countUnread
		// is a single COUNT(*); countPendingApprovals scans the pending
		// queue capped at 200). Failures are swallowed — a missing DB
		// shouldn't blow up every page render; the badges just hide.
		try {
			$this->template->unreadInboxCount = $this->notificationsForBadge->countUnread();
		} catch (\Throwable) {
			$this->template->unreadInboxCount = 0;
		}
		try {
			$this->template->pendingApprovalsCount = $this->eventsForBadge->countPendingApprovals();
		} catch (\Throwable) {
			$this->template->pendingApprovalsCount = 0;
		}
		// Audit-chain integrity badge — ONLY when the chain is enabled (strict
		// '1' gate, matching EventRepository + bone/clients/wing.py). Reads the
		// cached verdict (Pulse-refreshed); never walks the chain per render.
		// On a chain-off install the variable stays unset -> badge hides.
		if (getenv('WING_AUDIT_CHAIN_ENABLED') === '1') {
			try {
				$this->template->auditChainVerdict = $this->auditChainForBadge->verdict();
			} catch (\Throwable) {
				// swallow — a missing audit_chain_meta just hides the badge
			}
		}
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
		// The Nette identity's roles ARE the caller's Authentik groups —
		// ForwardAuthUserStorage rebuilds them from the forward-auth headers on
		// every request, so this is the standard Nette authorization API rather
		// than ad-hoc header parsing. Returns false when no identity (logged out).
		return $this->getUser()->isInRole($group);
	}

	/**
	 * The caller's most-privileged (lowest-numbered) RBAC tier, derived from
	 * their Authentik group roles, or PHP_INT_MAX when they hold no recognised
	 * tier group (incl. logged-out). Cumulative: a tier-1 admin returns 1 and
	 * thus satisfies any requireTier(>=1).
	 */
	protected function callerTier(): int
	{
		foreach (self::TIER_GROUPS as $tier => $groups) {
			foreach ($groups as $group) {
				if ($this->getUser()->isInRole($group)) {
					return $tier;
				}
			}
		}
		return PHP_INT_MAX;
	}

	/**
	 * Reject with 403 unless the caller's tier is at least as privileged as
	 * $minTier (lower number = more privileged). The declarative
	 * $minAccessTier property routes through here from startup().
	 */
	protected function requireTier(int $minTier): void
	{
		if ($this->callerTier() > $minTier) {
			$this->error(
				'Forbidden -- this resource requires RBAC tier ' . $minTier
				. ' or higher; your Authentik groups do not grant it.',
				403,
			);
		}
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
	 * resume), ApprovalsPresenter (rubber-stamp queue for agent actions),
	 * and AgentsPresenter (AgentKit runtime catalog).
	 *
	 * Per the CLAUDE.md RBAC table, **Tier-1 = `nos-providers` OR
	 * `nos-admins`** (both groups). Pre-2026-05-17 this gate only
	 * accepted `nos-providers`, which 403'd every operator whose
	 * identity (e.g. `akadmin`) was provisioned with `nos-admins`
	 * instead. Surfaced live on pazny.eu when the operator hit
	 * /approvals + /agents and got 403 despite being a super-admin.
	 *
	 * The two group names stay duplicated here (not imported from
	 * default.config.yml) — they're a hard security contract pinned
	 * by the anatomy gate `test_security_admin_gate_unchanged` so a
	 * config rename can't silently bypass the boundary.
	 */
	protected function requireSuperAdmin(): void
	{
		if (!$this->callerHasGroup('nos-providers') && !$this->callerHasGroup('nos-admins')) {
			$this->error(
				'Forbidden -- Tier-1 super-admin membership (nos-providers or nos-admins) required.',
				403,
			);
		}
	}

	/**
	 * Reject the request with 405 unless the HTTP method is POST. Used by
	 * every state-changing action so a phishing GET (e.g. ``<img src>`` or
	 * a top-level navigation from a malicious page while the operator is
	 * logged in) cannot trigger the mutation. Templates must use
	 * ``<form method="post" action="...">`` to call these actions.
	 *
	 * SEC-14 (2026-05-23) extension: in addition to method enforcement,
	 * validates a session-bound CSRF token. Without this, a logged-in
	 * super-admin visiting a malicious page would have their session
	 * cookie (Authentik's, SameSite=Lax by default) ride along on a
	 * hidden auto-submitting form to https://wing.<tld>/admin/halt,
	 * /users/invite-create, /approvals/approve/<id>, etc. — full RBAC
	 * bypass via the operator's own browser.
	 *
	 * Templates emit the token as a hidden input named `_csrf` via the
	 * `$csrfToken` variable populated by beforeRender(). Use:
	 *
	 *   <form method="post" action="{link …}">
	 *     <input type="hidden" name="_csrf" value="{$csrfToken}">
	 *     ...
	 *   </form>
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
		$this->validateCsrfToken();
	}

	/**
	 * Validate the `_csrf` POST field against the session-bound token.
	 * The token is generated lazily on first use per Nette session and
	 * reused across all forms within the same session — rotating per-
	 * form would require server-side state per form and gain nothing
	 * since the attack window is the same.
	 *
	 * Timing-safe compare so a brute-force attempt can't oracle the
	 * match position from response latency.
	 */
	private function validateCsrfToken(): void
	{
		$expected = $this->getCsrfToken();
		$got = (string) ($this->getHttpRequest()->getPost('_csrf') ?? '');
		if ($got === '' || !hash_equals($expected, $got)) {
			$this->error(
				'Forbidden -- CSRF token missing or invalid. Reload the form and try again.',
				403,
			);
		}
	}

	/**
	 * Mint or retrieve the session-bound CSRF token. Used by both
	 * server-side validation (requirePostMethod) and template render
	 * (beforeRender exposes $csrfToken).
	 *
	 * Stored in Nette's session under the 'csrf' section. Persistent
	 * for the duration of the operator's session; rotated when the
	 * session expires or is destroyed.
	 */
	protected function getCsrfToken(): string
	{
		$session = $this->getSession('csrf');
		// Nette's SessionSection acts like an object — properties are
		// keys. `token` lives there for the session's lifetime.
		if (empty($session->token)) {
			$session->token = bin2hex(random_bytes(32));  // 256-bit hex
		}
		return (string) $session->token;
	}
}
