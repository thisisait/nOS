<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Wing-side audit-trail for operator-issued Authentik invitations
 * (Anatomy A15, 2026-05-17).
 *
 * Insert path: UsersPresenter::createInvitationAction (POST) calls
 * AuthentikClient::createInvitation, then writes the local row via insert()
 * so /users/invitations has a record even if Authentik later deletes the
 * invitation (single-use redemption → Authentik cleans up its row).
 *
 * Read path: /users/invitations renders the table — operator can see who
 * was invited, by whom, with what app/role mix, redemption state.
 *
 * Mutators kept narrow:
 *   * markRedeemed — webhook OR operator-side reconcile sets redeemed_at.
 *   * markRevoked  — operator hits "revoke" → AuthentikClient::deleteInvitation,
 *                    then we stamp revoked_at locally.
 *
 * All writes carry A10 actor_id (the operator's Authentik client_id from
 * forward-auth headers); the issue action also gets a /events row whose
 * actor_action_id we store in actor_action_id so the audit trail joins.
 */
final class UserInvitationRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	/**
	 * @param array<string,mixed> $payload
	 *   Required keys:
	 *     - invitation_pk      string
	 *     - invitation_url     string
	 *     - expires_at         string (ISO8601)
	 *     - actor_id           string
	 *   Optional:
	 *     - uuid               string (auto-minted if absent)
	 *     - email_hint         string|null
	 *     - name_hint          string|null
	 *     - tenant             string (default 'default')
	 *     - target_groups      list<string>
	 *     - target_apps        list<array{slug:string,role?:string}>
	 *     - single_use         bool (default true)
	 *     - actor_action_id    string|null
	 *     - metadata           array
	 * @return int row id
	 */
	public function insert(array $payload): int
	{
		foreach (['invitation_pk', 'invitation_url', 'expires_at', 'actor_id'] as $req) {
			if (empty($payload[$req])) {
				throw new \InvalidArgumentException("UserInvitationRepository::insert missing {$req}");
			}
		}

		$groups = $payload['target_groups'] ?? [];
		if (!is_array($groups)) {
			$groups = [];
		}
		$apps = $payload['target_apps'] ?? [];
		if (!is_array($apps)) {
			$apps = [];
		}
		$metadata = $payload['metadata'] ?? [];
		if (!is_array($metadata)) {
			$metadata = [];
		}

		$row = [
			'uuid'               => (string) ($payload['uuid'] ?? self::uuid4()),
			'invitation_pk'      => (string) $payload['invitation_pk'],
			'invitation_url'     => (string) $payload['invitation_url'],
			'email_hint'         => $payload['email_hint'] ?? null,
			'name_hint'          => $payload['name_hint']  ?? null,
			'tenant'             => (string) ($payload['tenant'] ?? 'default'),
			'target_groups_json' => json_encode(array_values($groups)),
			'target_apps_json'   => json_encode(array_values($apps)),
			'expires_at'         => (string) $payload['expires_at'],
			'single_use'         => !empty($payload['single_use'] ?? true) ? 1 : 0,
			'actor_id'           => (string) $payload['actor_id'],
			'actor_action_id'    => $payload['actor_action_id'] ?? null,
			'metadata_json'      => json_encode($metadata),
		];

		$this->db->table('user_invitations')->insert($row);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	/** @return list<array<string,mixed>> */
	public function listAll(int $limit = 200): array
	{
		$rows = $this->db->query(
			'SELECT * FROM user_invitations ORDER BY created_at DESC LIMIT ?',
			$limit,
		)->fetchAll();
		return array_map(fn($r) => (array) $r, $rows);
	}

	public function findByInvitationPk(string $invitationPk): ?array
	{
		$row = $this->db->query(
			'SELECT * FROM user_invitations WHERE invitation_pk = ? LIMIT 1',
			$invitationPk,
		)->fetch();
		return $row ? (array) $row : null;
	}

	public function findByUuid(string $uuid): ?array
	{
		$row = $this->db->query(
			'SELECT * FROM user_invitations WHERE uuid = ? LIMIT 1',
			$uuid,
		)->fetch();
		return $row ? (array) $row : null;
	}

	public function countPending(): int
	{
		$row = $this->db->query(
			"SELECT COUNT(*) AS n FROM user_invitations "
			. "WHERE redeemed_at IS NULL AND revoked_at IS NULL "
			. "AND expires_at > datetime('now')",
		)->fetch();
		return $row ? (int) $row->n : 0;
	}

	public function markRedeemed(string $invitationPk, ?string $userPk = null): void
	{
		$this->db->query(
			"UPDATE user_invitations SET redeemed_at = datetime('now'), redeemed_user_pk = ? "
			. "WHERE invitation_pk = ? AND redeemed_at IS NULL",
			$userPk,
			$invitationPk,
		);
	}

	public function markRevoked(string $invitationPk): void
	{
		$this->db->query(
			"UPDATE user_invitations SET revoked_at = datetime('now') "
			. "WHERE invitation_pk = ? AND revoked_at IS NULL",
			$invitationPk,
		);
	}

	/**
	 * Stash the Cesta B (A18) Infisical + Stalwart provisioning result for
	 * the given invitation row id. Idempotent: subsequent calls overwrite
	 * the snapshot. Schema column `provisioning_json` was added 2026-05-20.
	 *
	 * @param int                                       $rowId
	 * @param array<string,mixed>                       $result
	 */
	public function setProvisioningResult(int $rowId, array $result): void
	{
		$this->db->query(
			'UPDATE user_invitations SET provisioning_json = ? WHERE id = ?',
			json_encode($result, JSON_THROW_ON_ERROR),
			$rowId,
		);
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
