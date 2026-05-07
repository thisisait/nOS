<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Persistence for agent_vaults + agent_credentials. Plaintext NEVER stored
 * in agent_credentials.secret_ref — those are pointers ("env:NAME" or
 * "infisical:/path") resolved at session-open time by CredentialResolver.
 */
final class AgentVaultRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}

	public function findByName(string $name): ?array
	{
		$row = $this->db->table('agent_vaults')
			->where('name', $name)
			->where('archived_at', null)
			->fetch();
		return $row !== null ? $row->toArray() : null;
	}

	/**
	 * @param array<string, mixed> $metadata
	 */
	public function createVault(string $name, string $displayName, array $metadata = []): int
	{
		$this->db->table('agent_vaults')->insert([
			'uuid'         => bin2hex(random_bytes(16)),
			'name'         => $name,
			'display_name' => $displayName,
			'metadata_json'=> json_encode($metadata) ?: '{}',
		]);
		return (int) $this->db->getConnection()->getPdo()->lastInsertId();
	}

	public function upsertCredential(int $vaultId, string $scope, string $displayName, string $secretRef): void
	{
		$existing = $this->db->table('agent_credentials')
			->where('vault_id', $vaultId)
			->where('scope', $scope)
			->where('archived_at', null)
			->fetch();
		if ($existing !== null) {
			$this->db->table('agent_credentials')
				->where('id', $existing->id)
				->update([
					'display_name' => $displayName,
					'secret_ref' => $secretRef,
				]);
			return;
		}
		$this->db->table('agent_credentials')->insert([
			'vault_id'     => $vaultId,
			'scope'        => $scope,
			'display_name' => $displayName,
			'secret_ref'   => $secretRef,
		]);
	}

	public function getCredentialRef(int $vaultId, string $scope): ?string
	{
		$row = $this->db->table('agent_credentials')
			->where('vault_id', $vaultId)
			->where('scope', $scope)
			->where('archived_at', null)
			->fetch();
		return $row !== null ? (string) $row->secret_ref : null;
	}

	/**
	 * @return array<int, array<string, mixed>>
	 */
	public function listVaults(bool $includeArchived = false): array
	{
		$q = $this->db->table('agent_vaults')->order('id DESC');
		if (!$includeArchived) {
			$q->where('archived_at', null);
		}
		$out = [];
		foreach ($q->fetchAll() as $row) {
			$out[] = $row->toArray();
		}
		return $out;
	}

	/**
	 * @return array<int, array{scope: string, display_name: string}>
	 */
	public function listCredentials(int $vaultId): array
	{
		$out = [];
		foreach ($this->db->table('agent_credentials')
			->where('vault_id', $vaultId)
			->where('archived_at', null)
			->order('scope ASC')
			->fetchAll() as $row) {
			$out[] = [
				'scope' => (string) $row->scope,
				'display_name' => (string) $row->display_name,
			];
		}
		return $out;
	}
}
