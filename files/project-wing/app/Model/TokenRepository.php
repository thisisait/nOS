<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

final class TokenRepository
{
	public function __construct(
		private Explorer $db,
	) {
	}


	/**
	 * Validate a Bearer token against SHA-256 hash stored in DB.
	 * Returns token row (without hash) or null.
	 * Updates last_used_at on successful validation.
	 */
	public function validate(string $token): ?array
	{
		$hash = hash('sha256', $token);

		$row = $this->db->table('api_tokens')
			->where('token', $hash)
			->where('active', 1)
			->fetch();

		if (!$row) {
			return null;
		}

		$this->db->table('api_tokens')
			->where('id', $row['id'])
			->update(['last_used_at' => (new \DateTimeImmutable)->format('Y-m-d H:i:s')]);

		$result = $row->toArray();
		unset($result['token']); // never return hash to caller
		return $result;
	}


	/**
	 * Create a new API token. Stores SHA-256 hash, not plaintext.
	 */
	public function create(string $token, string $name = 'default', ?string $createdBy = null): void
	{
		$hash = hash('sha256', $token);

		$this->db->table('api_tokens')->insert([
			'token' => $hash,
			'name' => $name,
			'created_by' => $createdBy,
		]);
	}


	/**
	 * Check if a token (plaintext) already exists in the DB.
	 */
	public function exists(string $token): bool
	{
		$hash = hash('sha256', $token);
		$count = $this->db->table('api_tokens')
			->where('token', $hash)
			->count('*');
		return $count > 0;
	}


	/**
	 * List all tokens (for admin UI). Hash is masked.
	 */
	public function list(): array
	{
		$items = [];
		foreach ($this->db->table('api_tokens')->order('created_at DESC')->fetchAll() as $row) {
			$item = $row->toArray();
			// Show only first 8 chars of hash
			$item['token_masked'] = substr($item['token'], 0, 8) . '...';
			unset($item['token']);
			$items[] = $item;
		}
		return $items;
	}
}
