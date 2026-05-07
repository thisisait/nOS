<?php

declare(strict_types=1);

namespace App\AgentKit\Vault;

use App\Model\AgentVaultRepository;

/**
 * Resolves secret_ref strings into actual secret values at session-open time.
 *
 * secret_ref schemes (the only supported forms):
 *   - "env:VAR_NAME"          read from process env
 *   - "infisical:/path"       reserved; not yet wired (returns null)
 *
 * Plaintext secrets NEVER live in agent_credentials. This class is the only
 * place a secret materialises in memory; AgentKit handles it through
 * function locals only — never logged, never stored back, never echoed.
 *
 * Resolution order for a given scope (e.g. 'anthropic-api'):
 *   1. If a vault is bound to the current session, look for an
 *      agent_credentials row with matching scope, decode secret_ref,
 *      return resolved value.
 *   2. Else env-var fallback by deterministic name:
 *      'anthropic-api' -> ANTHROPIC_API_KEY
 *      'mcp-wing'      -> WING_API_TOKEN
 *      …
 *   3. Else null. Caller decides whether that's fatal.
 */
final class CredentialResolver
{
	private ?int $vaultId = null;

	public function __construct(
		private readonly AgentVaultRepository $vaults,
	) {
	}

	public function bindVault(?int $vaultId): void
	{
		$this->vaultId = $vaultId;
	}

	public function resolve(string $scope): ?string
	{
		if ($this->vaultId !== null) {
			$ref = $this->vaults->getCredentialRef($this->vaultId, $scope);
			if ($ref !== null) {
				$resolved = $this->dereference($ref);
				if ($resolved !== null) {
					return $resolved;
				}
			}
		}
		// Env-var fallback by deterministic name.
		$envName = $this->scopeToEnvName($scope);
		$value = getenv($envName);
		return $value !== false && $value !== '' ? $value : null;
	}

	private function dereference(string $secretRef): ?string
	{
		if (str_starts_with($secretRef, 'env:')) {
			$envName = substr($secretRef, 4);
			$value = getenv($envName);
			return $value !== false && $value !== '' ? $value : null;
		}
		if (str_starts_with($secretRef, 'infisical:')) {
			// Reserved for B4 vault refresh wiring against Infisical CLI.
			// For now log + treat as missing so the caller falls back to env.
			error_log('[agentkit] infisical: secret_ref scheme not yet wired (' . $secretRef . ')');
			return null;
		}
		return null;
	}

	private function scopeToEnvName(string $scope): string
	{
		$known = [
			'anthropic-api' => 'ANTHROPIC_API_KEY',
			'openclaw-api'  => 'OPENCLAW_API_KEY',
			'mcp-wing'      => 'WING_API_TOKEN',
			'mcp-bone'      => 'BONE_SECRET',
		];
		return $known[$scope] ?? strtoupper(str_replace('-', '_', $scope));
	}
}
