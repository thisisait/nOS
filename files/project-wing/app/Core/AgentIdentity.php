<?php
/**
 * Wing -> Bone OIDC client_credentials helper.
 *
 * Mirror of module_utils/agent_identity.py - same on-disk cache layout
 * (~/.nos/agent-tokens/<client_id>.json), same Authentik token endpoint,
 * same refresh window. PHP-side Wing uses this when its read-only models
 * need to GET /api/state/services from Bone.
 *
 * No Composer deps - cURL + json_encode are stdlib so the same code works
 * on macOS Homebrew PHP and Alpine FPM containers.
 *
 * Track B (2026-04-26).
 */

declare(strict_types=1);

namespace App\Core;

use RuntimeException;

final class AgentIdentity
{
    private const REFRESH_BEFORE_EXPIRY_SECONDS = 60;

    private string $tokenUrl;
    private string $clientId;
    private string $clientSecret;
    /** @var list<string> */
    private array $scopes;
    private string $cacheDir;

    /**
     * @param list<string> $scopes
     */
    public function __construct(
        string $tokenUrl,
        string $clientId,
        string $clientSecret,
        array $scopes,
        ?string $cacheDir = null
    ) {
        $this->tokenUrl = $tokenUrl;
        $this->clientId = $clientId;
        $this->clientSecret = $clientSecret;
        $this->scopes = $scopes;
        $this->cacheDir = $cacheDir
            ?? ($_ENV['NOS_AGENT_TOKEN_DIR']
                ?? (getenv('HOME') . '/.nos/agent-tokens'));
    }

    /**
     * Build from environment / .env vars written by pazny.wing.
     * Required env keys: AUTHENTIK_DOMAIN, WING_AGENT_CLIENT_ID,
     * WING_AGENT_CLIENT_SECRET, WING_AGENT_SCOPES.
     */
    public static function fromEnv(): self
    {
        $domain = getenv('AUTHENTIK_DOMAIN') ?: 'auth.dev.local';
        $clientId = getenv('WING_AGENT_CLIENT_ID') ?: 'nos-wing';
        $clientSecret = getenv('WING_AGENT_CLIENT_SECRET') ?: '';
        $scopesRaw = getenv('WING_AGENT_SCOPES') ?: 'nos:state:read';
        $scopes = preg_split('/\s+/', trim($scopesRaw)) ?: [];
        $tokenUrl = "https://{$domain}/application/o/token/";
        return new self($tokenUrl, $clientId, $clientSecret, $scopes);
    }

    public function getToken(): string
    {
        $cached = $this->loadCached();
        if ($cached !== null) {
            return $cached['access_token'];
        }
        $fresh = $this->fetchToken();
        $this->storeCache($fresh);
        return $fresh['access_token'];
    }

    /** @return array{Authorization: string} */
    public function authorizationHeader(): array
    {
        return ['Authorization' => 'Bearer ' . $this->getToken()];
    }

    public function invalidate(): bool
    {
        $path = $this->cachePath();
        if (!is_file($path)) {
            return false;
        }
        return @unlink($path);
    }

    // -- internals -----------------------------------------------------------

    private function cachePath(): string
    {
        $safe = preg_replace('/[^A-Za-z0-9_-]/', '', $this->clientId) ?: 'default';
        return $this->cacheDir . '/' . $safe . '.json';
    }

    /** @return array{access_token: string, expires_at: int}|null */
    private function loadCached(): ?array
    {
        $path = $this->cachePath();
        if (!is_file($path)) {
            return null;
        }
        $raw = @file_get_contents($path);
        if ($raw === false) {
            return null;
        }
        $data = json_decode($raw, true);
        if (!is_array($data) || !isset($data['access_token'], $data['expires_at'])) {
            return null;
        }
        if ((int)$data['expires_at'] - time() < self::REFRESH_BEFORE_EXPIRY_SECONDS) {
            return null;
        }
        return $data;
    }

    /**
     * @param array{access_token: string, expires_at: int} $payload
     */
    private function storeCache(array $payload): void
    {
        if (!is_dir($this->cacheDir)) {
            @mkdir($this->cacheDir, 0700, true);
        }
        $tmp = $this->cachePath() . '.tmp';
        file_put_contents($tmp, json_encode($payload, JSON_UNESCAPED_SLASHES));
        @chmod($tmp, 0600);
        @rename($tmp, $this->cachePath());
    }

    /** @return array{access_token: string, expires_at: int} */
    private function fetchToken(): array
    {
        if ($this->clientSecret === '') {
            throw new RuntimeException(
                'AgentIdentity: WING_AGENT_CLIENT_SECRET is empty. '
                . 'Run the playbook so the wing role writes ~/wing/.env.'
            );
        }
        $body = http_build_query([
            'grant_type'    => 'client_credentials',
            'client_id'     => $this->clientId,
            'client_secret' => $this->clientSecret,
            'scope'         => implode(' ', $this->scopes),
        ]);

        $ch = curl_init($this->tokenUrl);
        curl_setopt_array($ch, [
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => $body,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 10,
            CURLOPT_HTTPHEADER     => [
                'Content-Type: application/x-www-form-urlencoded',
                'Accept: application/json',
            ],
        ]);
        $resp = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);

        if ($resp === false) {
            throw new RuntimeException("Authentik unreachable: {$err}");
        }
        if ($httpCode >= 400) {
            $snippet = substr((string)$resp, 0, 500);
            throw new RuntimeException("Authentik {$httpCode}: {$snippet}");
        }
        $data = json_decode((string)$resp, true);
        if (!is_array($data) || empty($data['access_token'])) {
            throw new RuntimeException('Authentik returned no access_token');
        }
        $expiresIn = (int)($data['expires_in'] ?? 3600);
        return [
            'access_token' => (string)$data['access_token'],
            'expires_at'   => time() + $expiresIn,
        ];
    }
}
