<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\AuthentikClient;
use App\Model\EventRepository;
use App\Model\UserInvitationRepository;
use Nette\Application\BadRequestException;
use RuntimeException;

/**
 * Wing /users — operator-facing identity console (Anatomy A15, 2026-05-17).
 *
 * Four views:
 *   GET  /users                — list every Authentik user with groups + last login
 *   GET  /users/invite         — invite form (apps multi-select + per-app tier)
 *   POST /users/invite-create  — actually mint the Authentik invitation
 *   GET  /users/invitations    — audit table of every Wing-issued invitation
 *   POST /users/revoke         — revoke an outstanding invitation
 *
 * All four are gated by `requireSuperAdmin()` — user management is the
 * canonical Tier-1 operation. UI-level diagnostics use the AuthentikClient
 * configured-flag so a fresh install (no `nos-api` token yet) shows a
 * one-line operator hint instead of bleeding raw 401s.
 *
 * Multi-tenant model: the invite form lets the operator pick a tenant slug
 * (default + any extra tenants declared in default.config.yml::tenants_extra),
 * which becomes the prefix on the dynamic group binding (e.g. `nos-tenantA-
 * users` vs the base `nos-users`). The base RBAC tier is always one of the
 * canonical four (providers/admins/managers/users/guests). The two are
 * additive — a "tenant-A manager" gets both `nos-managers` AND
 * `nos-tenant-a-managers` so global Tier-2 RBAC keeps working while tenant
 * scoping layers on top.
 *
 * fixed_data shape sent to Authentik:
 *   {
 *     "target_groups": ["nos-managers", "nos-tenant-a-managers"],
 *     "target_apps":   [{"slug":"gitea","role":"manager"}, ...],
 *     "tenant":        "tenant-a",
 *     "invited_by":    "<actor_id>",
 *     "invitation_uuid": "<wing-side uuid>"
 *   }
 * The enrollment flow's expression policy reads `prompt_data.target_groups`
 * and binds the new user to each group; `target_apps` is informational +
 * audit-only (Authentik authorization stays group-driven).
 */
final class UsersPresenter extends BasePresenter
{
	protected string $activeTab = 'users';

	private const DEFAULT_INVITE_TTL_HOURS = 72;
	private const ENROLLMENT_FLOW_SLUG = 'nos-enrollment';

	public function __construct(
		private AuthentikClient $authentik,
		private UserInvitationRepository $invitations,
		private EventRepository $events,
	) {
	}

	public function startup(): void
	{
		parent::startup();
		$this->requireSuperAdmin();
	}

	// ── /users — directory ───────────────────────────────────────────────

	public function renderDefault(?string $search = null): void
	{
		$this->template->authentikConfigured = $this->authentik->isConfigured();
		$this->template->users  = [];
		$this->template->groups = [];
		$this->template->search = $search;
		$this->template->error  = null;

		if (!$this->authentik->isConfigured()) {
			return;
		}

		try {
			$users = $this->authentik->listUsers($search);
			$groups = $this->authentik->listGroups();
		} catch (RuntimeException $e) {
			$this->template->error = $e->getMessage();
			return;
		}

		// Decorate each user with the RBAC tier + tenant prefix(es). Cheap
		// since groups are already inlined via include_groups=true.
		$decorated = [];
		foreach ($users as $u) {
			$tiers = [];
			$tenants = [];
			$other = [];
			foreach (($u['groups_obj'] ?? $u['groups'] ?? []) as $g) {
				$name = is_array($g) ? ($g['name'] ?? '') : (string) $g;
				if ($name === '') {
					continue;
				}
				if (preg_match('/^nos-(providers|admins|managers|users|guests)$/', $name)) {
					$tiers[] = $name;
				} elseif (str_starts_with($name, 'nos-tenant-')) {
					$tenants[] = $name;
				} elseif (str_starts_with($name, 'nos-')) {
					$other[] = $name;
				}
			}
			$decorated[] = $u + [
				'_tiers'   => $tiers,
				'_tenants' => $tenants,
				'_other'   => $other,
			];
		}

		$this->template->users  = $decorated;
		$this->template->groups = $groups;
	}

	// ── /users/invite — form ─────────────────────────────────────────────

	public function renderInvite(): void
	{
		$this->template->authentikConfigured = $this->authentik->isConfigured();
		$this->template->apps     = [];
		$this->template->tenants  = ['default'];
		$this->template->rbacTiers = [
			'nos-managers' => 'Tier 2 — manager (Gitea, n8n, ERPNext, …)',
			'nos-users'    => 'Tier 3 — user (Nextcloud, Vaultwarden, Open WebUI, …)',
			'nos-guests'   => 'Tier 4 — guest (Kiwix, Jellyfin, WordPress, …)',
			'nos-admins'   => 'Tier 1 — admin (Portainer, Infisical, Grafana) — ⚠ super-admin',
		];
		$this->template->defaultTtlHours = self::DEFAULT_INVITE_TTL_HOURS;
		$this->template->enrollmentFlowSlug = self::ENROLLMENT_FLOW_SLUG;
		$this->template->error = null;

		if (!$this->authentik->isConfigured()) {
			return;
		}

		try {
			$apps = $this->authentik->listApplications();
			$flows = $this->authentik->listEnrollmentFlows();
		} catch (RuntimeException $e) {
			$this->template->error = $e->getMessage();
			return;
		}

		$flowSlugs = array_column($flows, 'slug');
		$this->template->enrollmentFlowReady = in_array(self::ENROLLMENT_FLOW_SLUG, $flowSlugs, true);

		// Sort applications by name for predictable UX.
		usort($apps, fn($a, $b) => strcasecmp((string) ($a['name'] ?? ''), (string) ($b['name'] ?? '')));
		$this->template->apps = $apps;

		// Extra tenants come from forward-auth headers? No — declared in
		// default.config.yml::tenants_extra. Wing reads from env (the role
		// renders the list into the launchd plist as TENANT_SLUGS comma-sep).
		$extraRaw = (string) (getenv('TENANT_SLUGS') ?: '');
		if ($extraRaw !== '') {
			$extras = array_filter(array_map('trim', explode(',', $extraRaw)));
			$this->template->tenants = array_values(array_unique(array_merge(['default'], $extras)));
		}
	}

	public function actionInviteCreate(): void
	{
		$this->requirePostMethod();
		$this->requireSuperAdmin();

		if (!$this->authentik->isConfigured()) {
			$this->error('Authentik bootstrap token not configured', 503);
		}

		$post = $this->getHttpRequest()->getPost();

		$tier = (string) ($post['tier'] ?? '');
		$validTiers = ['nos-managers', 'nos-users', 'nos-guests', 'nos-admins'];
		if (!in_array($tier, $validTiers, true)) {
			$this->error('Invalid tier: must be one of ' . implode(', ', $validTiers), 400);
		}

		$tenant = (string) ($post['tenant'] ?? 'default');
		if (!preg_match('/^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]?$/', $tenant)) {
			$this->error('Invalid tenant slug', 400);
		}

		$ttlHours = (int) ($post['ttl_hours'] ?? self::DEFAULT_INVITE_TTL_HOURS);
		if ($ttlHours < 1 || $ttlHours > 24 * 30) {
			$this->error('Invalid TTL (1..720 hours)', 400);
		}

		$emailHint = trim((string) ($post['email_hint'] ?? ''));
		$nameHint  = trim((string) ($post['name_hint'] ?? ''));
		if ($emailHint !== '' && !filter_var($emailHint, FILTER_VALIDATE_EMAIL)) {
			$this->error('email_hint is not a valid email address', 400);
		}

		// Build the additive group list. Tier is always present; tenant-
		// scoped group only when tenant != default.
		$groups = [$tier];
		if ($tenant !== 'default') {
			$groups[] = 'nos-tenant-' . $tenant . '-' . substr($tier, strlen('nos-'));
		}

		// Apps selection: post['apps'][] of app slugs; tier per app via
		// post['app_role'][<slug>] (optional, defaults to global tier).
		$apps = [];
		$slugs = $post['apps'] ?? [];
		if (!is_array($slugs)) {
			$slugs = [];
		}
		foreach ($slugs as $slug) {
			$slug = (string) $slug;
			if (!preg_match('/^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]?$/', $slug)) {
				continue;
			}
			$role = (string) (($post['app_role'][$slug] ?? '') ?: substr($tier, strlen('nos-')));
			$apps[] = ['slug' => $slug, 'role' => $role];
		}

		$expires = (new \DateTimeImmutable('+' . $ttlHours . ' hours'))->format(\DateTimeImmutable::ATOM);
		$invitationUuid = self::uuid4();
		$actorId = $this->getActorId();
		$actorActionId = self::uuid4();

		$displayName = sprintf(
			'nos-invite-%s-%s',
			$tenant,
			substr($invitationUuid, 0, 8),
		);

		$fixedData = [
			'target_groups'   => $groups,
			'target_apps'     => $apps,
			'tenant'          => $tenant,
			'invited_by'      => $actorId,
			'invitation_uuid' => $invitationUuid,
			'email_hint'      => $emailHint ?: null,
			'name_hint'       => $nameHint ?: null,
		];

		try {
			$res = $this->authentik->createInvitation(
				$displayName,
				self::ENROLLMENT_FLOW_SLUG,
				$expires,
				true,
				$fixedData,
			);
		} catch (RuntimeException $e) {
			$this->error('Authentik refused invitation: ' . $e->getMessage(), 502);
		}

		$invitationPk = (string) ($res['pk'] ?? '');
		if ($invitationPk === '') {
			$this->error('Authentik returned no invitation pk', 502);
		}

		$invitationUrl = $this->authentik->buildInvitationUrl(self::ENROLLMENT_FLOW_SLUG, $invitationPk);

		$rowId = $this->invitations->insert([
			'uuid'             => $invitationUuid,
			'invitation_pk'    => $invitationPk,
			'invitation_url'   => $invitationUrl,
			'email_hint'       => $emailHint ?: null,
			'name_hint'        => $nameHint ?: null,
			'tenant'           => $tenant,
			'target_groups'    => $groups,
			'target_apps'      => $apps,
			'expires_at'       => $expires,
			'single_use'       => true,
			'actor_id'         => $actorId,
			'actor_action_id'  => $actorActionId,
			'metadata'         => [
				'authentik_display_name' => $displayName,
				'enrollment_flow_slug'   => self::ENROLLMENT_FLOW_SLUG,
				'ttl_hours'              => $ttlHours,
			],
		]);

		// A10 audit lineage — one events row per issue with full context.
		try {
			$this->events->insert([
				'type'            => 'user_invitation_issued',
				'task'            => 'Invitation created: ' . $displayName,
				'source'          => 'wing',
				'actor_id'        => $actorId,
				'actor_action_id' => $actorActionId,
				'result'          => [
					'invitation_uuid'    => $invitationUuid,
					'invitation_pk'      => $invitationPk,
					'tenant'             => $tenant,
					'target_groups'      => $groups,
					'target_apps'        => $apps,
					'expires_at'         => $expires,
					'wing_invitation_id' => $rowId,
				],
			]);
		} catch (\Throwable) {
			// audit failure must not block invitation delivery; the local
			// user_invitations row already captures the action.
		}

		$this->redirect('Users:created', ['uuid' => $invitationUuid]);
	}

	// ── /users/created — shareable URL ───────────────────────────────────

	public function renderCreated(string $uuid): void
	{
		$row = $this->invitations->findByUuid($uuid);
		if ($row === null) {
			throw new BadRequestException('Unknown invitation uuid', 404);
		}
		$row['target_groups'] = json_decode((string) ($row['target_groups_json'] ?? '[]'), true) ?: [];
		$row['target_apps']   = json_decode((string) ($row['target_apps_json']   ?? '[]'), true) ?: [];
		$this->template->invite = $row;
	}

	// ── /users/invitations — audit table ─────────────────────────────────

	public function renderInvitations(): void
	{
		$rows = $this->invitations->listAll(200);
		foreach ($rows as &$r) {
			$r['target_groups'] = json_decode((string) ($r['target_groups_json'] ?? '[]'), true) ?: [];
			$r['target_apps']   = json_decode((string) ($r['target_apps_json']   ?? '[]'), true) ?: [];
		}
		unset($r);
		$this->template->invitations = $rows;
	}

	public function actionRevoke(): void
	{
		$this->requirePostMethod();
		$this->requireSuperAdmin();

		$post = $this->getHttpRequest()->getPost();
		$invitationPk = (string) ($post['invitation_pk'] ?? '');
		if ($invitationPk === '') {
			$this->error('invitation_pk is required', 400);
		}

		$row = $this->invitations->findByInvitationPk($invitationPk);
		if ($row === null) {
			$this->error('Unknown invitation', 404);
		}
		if (!empty($row['redeemed_at'])) {
			$this->error('Invitation already redeemed — cannot revoke', 409);
		}

		try {
			$this->authentik->deleteInvitation($invitationPk);
		} catch (RuntimeException $e) {
			// 404 from Authentik = already gone; still mark local revoked.
			if (!str_contains($e->getMessage(), 'HTTP 404')) {
				$this->error('Authentik refused revoke: ' . $e->getMessage(), 502);
			}
		}

		$this->invitations->markRevoked($invitationPk);

		try {
			$this->events->insert([
				'type'     => 'user_invitation_revoked',
				'task'     => 'Invitation revoked: ' . $invitationPk,
				'source'   => 'wing',
				'actor_id' => $this->getActorId(),
				'result'   => [
					'invitation_pk'   => $invitationPk,
					'invitation_uuid' => (string) ($row['uuid'] ?? ''),
				],
			]);
		} catch (\Throwable) {
		}

		$this->redirect('Users:invitations');
	}

	// ── helpers ──────────────────────────────────────────────────────────

	/**
	 * Authentik client_id of the operator making the request. Mirrors the
	 * pattern in Api/* presenters — bearer-token attribution is the gold
	 * standard, but browser sessions don't carry a bearer token, so we
	 * fall back to the forward-auth X-Authentik-Username header. The
	 * actor_id ends up as e.g. `operator:akadmin` so the /audit timeline
	 * can distinguish operator-issued invites from agent-issued ones.
	 */
	private function getActorId(): string
	{
		$user = (string) ($this->getHttpRequest()->getHeader('X-Authentik-Username') ?? '');
		return $user !== '' ? 'operator:' . $user : 'operator:unknown';
	}

	private static function uuid4(): string
	{
		$bytes = random_bytes(16);
		$bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
		$bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
		$hex = bin2hex($bytes);
		return sprintf(
			'%s-%s-%s-%s-%s',
			substr($hex, 0, 8),
			substr($hex, 8, 4),
			substr($hex, 12, 4),
			substr($hex, 16, 4),
			substr($hex, 20, 12),
		);
	}
}
