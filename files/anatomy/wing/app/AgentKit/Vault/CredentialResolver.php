<?php

declare(strict_types=1);

namespace App\AgentKit\Vault;

use App\Model\AgentVaultRepository;

/**
 * Resolves secret_ref strings into actual secret values at session-open time.
 *
 * secret_ref schemes (the only supported forms):
 *   - "env:VAR_NAME"          read from process env
 *   - "infisical:/path"       resolve via Infisical CLI (Track B U-B-Vault)
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
 *
 * Infisical resolution (added Track B U-B-Vault, 2026-05-07):
 *   - `infisical:/agents/anthropic-api` → InfisicalClient::fetch()
 *   - The trailing path segment is the secret NAME, the leading segments
 *     are the parent path passed to the CLI's `--path` flag.
 *   - Path is validated against `^/[A-Za-z0-9_/-]+$` BEFORE shelling out.
 *   - CLI invoked via array-form proc_open (no /bin/sh) with a minimal
 *     env allowlist (PATH/HOME/TZ/INFISICAL_TOKEN — no ANTHROPIC_API_KEY,
 *     WING_API_TOKEN, BONE_SECRET, etc.).
 *   - On any failure (CLI missing, path malformed, exit non-zero) returns
 *     null so the caller falls back to env. Plaintext is NEVER logged.
 *
 * Caching:
 *   - Resolved values are cached at INSTANCE level for the session
 *     lifetime — once a session resolves a scope, repeat resolutions
 *     in the same Runner loop don't re-shell-out. Cache is dropped
 *     when bindVault(null) is called or the instance is destroyed.
 *   - NEVER cached to disk. NEVER cached across sessions.
 */
final class CredentialResolver
{
	private ?int $vaultId = null;

	/** @var array<string, string> session-lifetime cache, scope => value */
	private array $cache = [];

	private readonly InfisicalClient $infisical;

	public function __construct(
		private readonly AgentVaultRepository $vaults,
		?InfisicalClient $infisical = null,
	) {
		// Allow the test suite to inject a mock; production callers get
		// the default client.
		$this->infisical = $infisical ?? new InfisicalClient();
	}

	public function bindVault(?int $vaultId): void
	{
		$this->vaultId = $vaultId;
		// Drop the cache on rebind — a new session must not see leftover
		// values from the previous one.
		$this->cache = [];
	}

	public function resolve(string $scope): ?string
	{
		if (isset($this->cache[$scope])) {
			return $this->cache[$scope];
		}
		if ($this->vaultId !== null) {
			$ref = $this->vaults->getCredentialRef($this->vaultId, $scope);
			if ($ref !== null) {
				$resolved = $this->dereference($ref);
				if ($resolved !== null) {
					$this->cache[$scope] = $resolved;
					return $resolved;
				}
			}
		}
		// Env-var fallback by deterministic name.
		$envName = $this->scopeToEnvName($scope);
		$value = getenv($envName);
		if ($value !== false && $value !== '') {
			$this->cache[$scope] = $value;
			return $value;
		}
		return null;
	}

	private function dereference(string $secretRef): ?string
	{
		if (str_starts_with($secretRef, 'env:')) {
			$envName = substr($secretRef, 4);
			$value = getenv($envName);
			return $value !== false && $value !== '' ? $value : null;
		}
		if (str_starts_with($secretRef, 'infisical:')) {
			$path = substr($secretRef, strlen('infisical:'));
			// InfisicalClient::fetch validates the path shape, locates the
			// CLI binary, invokes it via array-form proc_open with a
			// minimal env allowlist, and returns null on any failure
			// (so the resolver falls back to env). Plaintext is never
			// logged at any level.
			return $this->infisical->fetch($path);
		}
		return null;
	}

	public function __destruct()
	{
		// Defence in depth — the cache should already be GC'd with the
		// instance, but explicit clear avoids any chance of leftover
		// strings in dumped memory.
		$this->cache = [];
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
