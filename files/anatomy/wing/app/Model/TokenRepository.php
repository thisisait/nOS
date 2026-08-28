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
	 * Does a token's `scopes` list permit this HTTP method?
	 *
	 * ROUTE CLASS IS THE METHOD. At startup() — before any action runs — the
	 * only thing known about what the caller is about to do is the verb, and
	 * every API presenter here branches on exactly that. So GET/HEAD is the
	 * read class and everything else is the write class; no second table of
	 * route names to drift from the router.
	 *
	 * NULL/'' = unscoped = UNRESTRICTED. See the column's note in
	 * bin/init-db.php for why this default is the opposite of cortex's.
	 */
	public static function permits(?string $scopes, string $method): bool
	{
		$granted = array_filter(array_map('trim', explode(',', (string) $scopes)));
		if (!$granted) {
			return true;
		}
		if (in_array(strtoupper($method), ['GET', 'HEAD'], true)) {
			return (bool) array_intersect($granted, ['wing.read', 'wing.write']);
		}
		return in_array('wing.write', $granted, true);
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
